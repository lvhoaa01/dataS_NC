from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd

import actuator_identifiability_audit as audit
import validate_actuator_identifiability_notebook as validator


ROOT = Path(__file__).resolve().parents[1]


def make_frame(
    pump: list[int],
    fan: list[int] | None = None,
    grow_light: list[int] | None = None,
    *,
    start: str = "2024-06-01 00:00",
) -> pd.DataFrame:
    count = len(pump)
    fan = fan or [0] * count
    grow_light = grow_light or [0] * count
    values = np.arange(count, dtype=float)
    return pd.DataFrame(
        {
            "timestamp": pd.date_range(start, periods=count, freq="h"),
            "air_temperature": 25.0 + values,
            "air_humidity": 70.0 - 0.1 * values,
            "soil_temperature": 24.0 + 0.2 * values,
            "soil_moisture": 0.3 + 0.001 * values,
            "light_lux": 100.0 * values,
            "pump_state": pump,
            "fan_state": fan,
            "grow_light_state": grow_light,
        }
    )


class ActuatorIdentifiabilityNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        cls.audit_artifact_dir = (
            Path(cls.temporary_directory.name)
            / "actuator_identifiability_audit_smoke"
        )
        cls.notebook = validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            cls.namespace = validator.execute_smoke_namespace(
                cls.notebook,
                data_root=ROOT,
                preprocessing_artifact_dir=validator.LOCAL_PREPROCESSING_ARTIFACT_DIR,
                audit_artifact_dir=cls.audit_artifact_dir,
            )
        cls.source = validator.notebook_code_source(cls.notebook)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_01_notebook_json_valid_and_all_cells_compile(self) -> None:
        self.assertEqual(len(self.notebook.cells), 56)
        self.assertEqual(
            sum(cell.cell_type == "code" for cell in self.notebook.cells), 28
        )

    def test_02_concepts_are_synchronized(self) -> None:
        self.assertEqual(
            validator.validate_concepts_sync(self.notebook),
            {"status": "PASS", "logical_sections": 28},
        )

    def test_03_final_notebook_default_is_not_smoke(self) -> None:
        configuration = next(
            cell.source
            for cell in self.notebook.cells
            if cell.cell_type == "code" and cell.metadata["section_id"] == "02"
        )
        self.assertIn("ACTUATOR_AUDIT_SMOKE_TEST = False", configuration)
        self.assertNotIn("ACTUATOR_AUDIT_SMOKE_TEST = True", configuration)

    def test_04_exact_actuator_columns(self) -> None:
        self.assertEqual(
            audit.ACTUATORS,
            ("pump_state", "fan_state", "grow_light_state"),
        )

    def test_05_binary_actuator_validation_passes(self) -> None:
        audit.validate_binary_actuators(make_frame([0, 1, 0, 1]))

    def test_06_binary_actuator_validation_fails_fast(self) -> None:
        frame = make_frame([0, 1, 2, 0])
        with self.assertRaisesRegex(ValueError, "not binary"):
            audit.validate_binary_actuators(frame)

    def test_07_no_cross_scenario_transition(self) -> None:
        frames = {
            ("TRAIN", "a"): make_frame([0, 0, 0, 0]),
            ("TRAIN", "b"): make_frame([1, 1, 1, 1]),
            ("VALIDATION", "a"): make_frame([0, 0, 0, 0]),
            ("VALIDATION", "b"): make_frame([1, 1, 1, 1]),
        }
        summary = audit.actuator_transition_summary(frames)
        changing = summary.loc[
            (summary["actuator"] == "pump_state")
            & summary["transition"].isin(["01", "10"])
        ]
        self.assertEqual(int(changing["count"].sum()), 0)

    def test_08_no_train_to_validation_transition(self) -> None:
        frames = {
            ("TRAIN", "a"): make_frame([0, 0, 0, 0]),
            ("VALIDATION", "a"): make_frame([1, 1, 1, 1]),
        }
        summary = audit.actuator_transition_summary(frames)
        changing = summary.loc[
            (summary["actuator"] == "pump_state")
            & summary["transition"].isin(["01", "10"])
        ]
        self.assertEqual(int(changing["count"].sum()), 0)

    def test_09_validation_event_cannot_target_2025(self) -> None:
        frame = make_frame(
            [0, 0, 0, 1, 1], start="2024-12-31 19:00"
        )
        events = audit.extract_transition_events(frame, "scenario", "VALIDATION")
        self.assertTrue(events.empty)

    def test_10_off_to_on_detection(self) -> None:
        self.assertEqual(audit.transition_codes([0, 0, 1, 1]).tolist(), ["00", "01", "11"])

    def test_11_on_to_off_detection(self) -> None:
        self.assertEqual(audit.transition_codes([1, 1, 0, 0]).tolist(), ["11", "10", "00"])

    def test_12_dwell_time_run_lengths(self) -> None:
        runs = audit.run_lengths([0, 0, 1, 1, 1, 0])
        self.assertEqual(runs["state"].tolist(), [0, 1, 0])
        self.assertEqual(runs["duration_hours"].tolist(), [2, 3, 1])

    def test_13_joint_action_encoding_order(self) -> None:
        frame = make_frame([1], [0], [1])
        self.assertEqual(audit.encode_joint_actions(frame).iloc[0], "101")

    def test_14_all_joint_codes_are_valid(self) -> None:
        frame = pd.concat(
            [
                make_frame(
                    [(value >> 2) & 1],
                    [(value >> 1) & 1],
                    [value & 1],
                    start=f"2024-06-01 {value:02d}:00",
                )
                for value in range(8)
            ],
            ignore_index=True,
        )
        self.assertEqual(set(audit.encode_joint_actions(frame)), set(audit.JOINT_CODES))

    def test_15_per_scenario_aggregation_is_preserved(self) -> None:
        frames = {
            ("TRAIN", "a"): make_frame([0, 1, 1, 0, 0, 0, 0, 0]),
            ("VALIDATION", "a"): make_frame([0, 1, 1, 0, 0, 0, 0, 0]),
        }
        events = audit.build_transition_events(frames)
        support = audit.support_by_scenario(frames, events)
        pump = support.loc[
            (support["split"] == "TRAIN")
            & (support["scenario_id"] == "a")
            & (support["actuator"] == "pump_state")
        ].iloc[0]
        self.assertEqual(int(pump["off_to_on_events"]), 1)
        self.assertEqual(int(pump["on_to_off_events"]), 1)

    def test_16_plus_1h_alignment(self) -> None:
        frame = make_frame([0, 1, 1, 1, 1, 1])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertEqual(event["target_1h_air_temperature"], frame.at[2, "air_temperature"])
        self.assertEqual(event["delta_1h_air_temperature"], 1.0)

    def test_17_plus_3h_alignment(self) -> None:
        frame = make_frame([0, 1, 1, 1, 1, 1])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertEqual(event["target_3h_air_temperature"], frame.at[4, "air_temperature"])
        self.assertEqual(event["delta_3h_air_temperature"], 3.0)

    def test_18_transition_event_fields(self) -> None:
        frame = make_frame([0, 1, 1, 1, 1, 1])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertEqual(event["scenario_id"], "a")
        self.assertEqual(event["direction"], "01")
        self.assertEqual(event["previous_value"], 0)
        self.assertEqual(event["new_value"], 1)

    def test_19_clean_single_actuator_event(self) -> None:
        frame = make_frame([0, 1, 1, 1, 1, 1])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertTrue(bool(event["clean_1h"]))
        self.assertTrue(bool(event["clean_3h"]))

    def test_20_other_actuator_instability_is_not_clean(self) -> None:
        frame = make_frame(
            [0, 1, 1, 1, 1, 1],
            [0, 0, 1, 1, 1, 1],
        )
        pump_event = audit.extract_transition_events(frame, "a", "TRAIN")
        pump_event = pump_event.loc[pump_event["actuator"] == "pump_state"].iloc[0]
        self.assertFalse(bool(pump_event["clean_1h"]))

    def test_21_short_target_pulse_remains_clean_if_others_stable(self) -> None:
        frame = make_frame([0, 1, 0, 0, 0, 0])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertTrue(bool(event["clean_1h"]))
        self.assertFalse(bool(event["target_stable_1h"]))

    def test_22_no_change_reference_logic(self) -> None:
        frame = make_frame([0, 0, 0, 0, 1, 1, 1, 1, 1])
        references = audit.build_no_change_references(
            frame, "a", "TRAIN", "pump_state", 1
        )
        self.assertTrue(
            all(
                frame.loc[row.position - 1 : row.position + 1, "pump_state"].nunique()
                == 1
                for row in references.itertuples()
            )
        )

    def test_23_current_state_delta_uses_physical_values(self) -> None:
        frame = make_frame([0, 1, 1, 1, 1, 1])
        event = audit.extract_transition_events(frame, "a", "TRAIN").iloc[0]
        self.assertAlmostEqual(event["delta_1h_soil_moisture"], 0.001)

    def test_24_overlap_binning_is_deterministic(self) -> None:
        frames = {
            ("TRAIN", "a"): make_frame([0, 1] * 8),
            ("VALIDATION", "a"): make_frame([1, 0] * 8),
        }
        first = audit.derive_overlap_edges(frames, audit.AuditConfig())
        second = audit.derive_overlap_edges(frames, audit.AuditConfig())
        self.assertEqual(first, second)

    def test_25_overlap_counts_both_actions(self) -> None:
        frame = make_frame([0, 1] * 12)
        for sensor in audit.SENSORS:
            frame[sensor] = 1.0
        frames = {("TRAIN", "a"): frame, ("VALIDATION", "a"): frame.copy()}
        edges = audit.derive_overlap_edges(frames, audit.AuditConfig())
        overlap = audit.state_conditioned_overlap(frames, edges)
        pump = overlap.loc[
            (overlap["split"] == "TRAIN")
            & (overlap["actuator"] == "pump_state")
        ].iloc[0]
        self.assertEqual(int(pump["both_action_cells"]), 1)

    def test_26_train_and_validation_are_reported_separately(self) -> None:
        self.assertEqual(set(self.namespace["usage_summary"]["split"]), set(audit.SPLITS))

    def test_27_held_out_ids_are_not_resolved(self) -> None:
        canonical = pd.DataFrame(
            {
                "parameter_set_id": ["dev", "held"],
                "ml_file": ["dev.csv", "held.csv"],
            }
        )
        calls: list[str] = []

        def fake_resolve(raw_path: str, data_root: Path) -> Path:
            calls.append(raw_path)
            return data_root / raw_path

        with mock.patch.object(audit, "resolve_indexed_path", side_effect=fake_resolve):
            paths = audit.resolve_development_paths(
                canonical, ["dev"], ["held"], ROOT
            )
        self.assertEqual(set(paths), {"dev"})
        self.assertEqual(calls, ["dev.csv"])

    def test_28_held_out_files_are_not_loaded_in_smoke(self) -> None:
        self.assertFalse(self.namespace["HELD_OUT_PATHS_RESOLVED"])
        self.assertFalse(self.namespace["HELD_OUT_CSV_LOADED"])
        self.assertFalse(
            set(self.namespace["active_development_ids"])
            & set(self.namespace["held_out_scenario_ids"])
        )

    def test_29_temporal_semantics_artifact_is_produced(self) -> None:
        path = self.audit_artifact_dir / "actuator_temporal_semantics.json"
        self.assertTrue(path.is_file())
        self.assertTrue(self.namespace["actuator_temporal_semantics"]["verified"])
        self.assertIn("not guaranteed", self.namespace["actuator_temporal_semantics"]["action_timing"])

    def test_30_confounding_diagnostics_are_finite(self) -> None:
        values = self.namespace["confounding_summary"].select_dtypes(
            include=[np.number]
        )
        self.assertTrue(np.isfinite(values.to_numpy()).all())

    def test_31_matching_is_deterministic(self) -> None:
        events = self.namespace["transition_events"]
        frames = self.namespace["audit_frames"]
        mean = self.namespace["matching_sensor_mean"]
        scale = self.namespace["matching_sensor_scale"]
        first = audit.matched_response_diagnostic(events, frames, mean, scale)
        second = audit.matched_response_diagnostic(events, frames, mean, scale)
        pd.testing.assert_frame_equal(first, second)

    def test_32_matching_never_crosses_split_or_scenario(self) -> None:
        source = Path(audit.__file__).read_text(encoding="utf-8")
        self.assertIn("frames[(split, scenario_id)]", source)
        self.assertTrue(
            set(self.namespace["matched_summary"]["split"]).issubset(set(audit.SPLITS))
        )

    def test_33_response_metrics_keep_physical_units(self) -> None:
        response = self.namespace["raw_response_summary"]
        for target, unit in audit.TARGET_UNITS.items():
            self.assertTrue(response.loc[response["target"] == target, "unit"].eq(unit).all())

    def test_34_no_model_optimizer_training_or_llm(self) -> None:
        result = validator.validate_static_protocol(self.notebook)
        self.assertEqual(result["model_classes"], 0)
        self.assertEqual(result["optimizers"], 0)
        self.assertEqual(result["training_loops"], 0)
        self.assertEqual(result["llm_api_clients"], 0)

    def test_35_all_required_artifacts_are_exported(self) -> None:
        for filename in audit.METRIC_FILENAMES:
            self.assertTrue((self.audit_artifact_dir / "metrics" / filename).is_file())
        for filename in audit.PLOT_FILENAMES:
            self.assertTrue((self.audit_artifact_dir / "plots" / filename).is_file())

    def test_36_smoke_readiness_is_not_scientific(self) -> None:
        self.assertEqual(
            self.namespace["ACTION_CONDITIONED_MODEL_READINESS"],
            "REVIEW_REQUIRED",
        )

    def test_37_full_fixed_notebook_is_authoritative(self) -> None:
        self.assertEqual(
            self.namespace["FULL_FIXED_NOTEBOOK"].name,
            "04_operational_lookback_ablation_FULL_FIXED.ipynb",
        )
        self.assertNotIn('"04_operational_lookback_ablation.ipynb"', self.source)

    def test_38_operational_contract_is_locked(self) -> None:
        self.assertEqual(self.namespace["OPERATIONAL_LOOKBACK"], 24)
        self.assertEqual(self.namespace["FORECAST_HORIZONS"], (1, 3))
        self.assertEqual(self.namespace["experiment_summary"]["operational_contract"]["input_shape"], ["B", 24, 8])
        self.assertEqual(self.namespace["experiment_summary"]["operational_contract"]["output_shape"], ["B", 2, 5])

    def test_39_locked_train_validation_ranges(self) -> None:
        split = self.namespace["split_manifest"]
        self.assertEqual(split["train_date_range"], ["2018-01-01 00:00:00", "2023-12-31 23:00:00"])
        self.assertEqual(split["validation_date_range"], ["2024-01-01 00:00:00", "2024-12-31 23:00:00"])

    def test_40_split_is_20_development_4_held_out(self) -> None:
        self.assertEqual(len(self.namespace["development_scenario_ids"]), 20)
        self.assertEqual(len(self.namespace["held_out_scenario_ids"]), 4)

    def test_41_no_final_test_partition_is_constructed(self) -> None:
        for name in ("temporal_test", "scenario_test", "combined_test"):
            self.assertNotIn(name, self.namespace)
        self.assertFalse(self.namespace["experiment_summary"]["final_tests_executed"])

    def test_42_deterministic_spread_sampling_is_bounded(self) -> None:
        first = audit.deterministic_spread_indices(10_000, 24)
        second = audit.deterministic_spread_indices(10_000, 24)
        np.testing.assert_array_equal(first, second)
        self.assertEqual(len(first), 24)
        self.assertEqual(len(np.unique(first)), 24)
        self.assertTrue(np.all(first[1:] > first[:-1]))

    def test_43_smoke_matching_is_explicitly_bounded(self) -> None:
        matched = self.namespace["matched_summary"]
        self.assertTrue(matched["matching_scope"].eq("BOUNDED_SMOKE").all())
        self.assertTrue(
            (matched["sampled_event_rows"] <= matched["available_event_rows"]).all()
        )

    def test_44_smoke_and_full_artifacts_are_isolated(self) -> None:
        self.assertEqual(
            self.namespace["AUDIT_ARTIFACT_DIR"].name,
            "actuator_identifiability_audit_smoke",
        )
        self.assertNotEqual(
            self.namespace["AUDIT_ARTIFACT_DIR"],
            self.namespace["FULL_AUDIT_ARTIFACT_DIR"],
        )
        self.assertEqual(
            self.namespace["audit_manifest"]["artifact_isolation_status"],
            "PASS",
        )


if __name__ == "__main__":
    unittest.main()
