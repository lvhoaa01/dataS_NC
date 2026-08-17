from __future__ import annotations

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest
import warnings

import numpy as np
import pandas as pd
import torch

import validate_ml_notebook as notebook_validator


ROOT = Path(__file__).resolve().parents[1]


class MLPreprocessingNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notebook = notebook_validator.load_and_compile_notebook()
        cls.temporary_directory = tempfile.TemporaryDirectory()
        artifact_dir = Path(cls.temporary_directory.name) / "artifacts"
        with redirect_stdout(io.StringIO()):
            cls.namespace = notebook_validator.execute_smoke_namespace(
                cls.notebook,
                data_root=ROOT,
                artifact_dir=artifact_dir,
            )
        cls.artifact_dir = artifact_dir

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_notebook_json_valid_and_code_cells_compile(self) -> None:
        self.assertEqual(len(self.notebook.cells), 43)
        self.assertEqual(sum(cell.cell_type == "code" for cell in self.notebook.cells), 21)

    def test_notebook_final_default_is_not_smoke(self) -> None:
        configuration_source = next(
            cell.source
            for cell in self.notebook.cells
            if cell.cell_type == "code" and cell.metadata["section_id"] == "01"
        )
        self.assertIn("SMOKE_TEST = False", configuration_source)
        self.assertNotIn("SMOKE_TEST = True", configuration_source)

    def test_concepts_document_matches_notebook_sections(self) -> None:
        sync = notebook_validator.validate_concepts_sync(self.notebook)
        self.assertEqual(sync["status"], "PASS")
        self.assertEqual(sync["logical_sections"], 22)

    def test_canonical_membership_comes_from_index(self) -> None:
        namespace = self.namespace
        self.assertEqual(len(namespace["canonical_index"]), 24)
        self.assertEqual(
            set(namespace["canonical_index"]["parameter_set_id"]),
            set(namespace["scenario_paths"]),
        )
        code_source = "\n".join(
            cell.source for cell in self.notebook.cells if cell.cell_type == "code"
        )
        self.assertNotIn("glob(", code_source)
        self.assertNotIn("rglob(", code_source)

    def test_windows_and_linux_paths_are_portable(self) -> None:
        resolver = self.namespace["resolve_scenario_path"]
        resolved = resolver(
            r"outputs\full_generation\ml\pa1_full_000_baseline.csv",
            ROOT,
        )
        self.assertEqual(
            resolved,
            (ROOT / "outputs/full_generation/ml/pa1_full_000_baseline.csv").resolve(),
        )

        with tempfile.TemporaryDirectory() as directory:
            data_root = Path(directory)
            fallback = data_root / "ml" / "scenario.csv"
            fallback.parent.mkdir()
            fallback.write_text("timestamp\n", encoding="utf-8")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                self.assertEqual(resolver(r"old\scenario.csv", data_root), fallback.resolve())
            self.assertTrue(any("explicit fallback" in str(item.message) for item in caught))

    def test_exact_source_feature_and_target_contracts(self) -> None:
        namespace = self.namespace
        self.assertEqual(len(namespace["SOURCE_COLUMNS"]), 9)
        self.assertEqual(len(namespace["FEATURE_COLUMNS"]), 8)
        self.assertEqual(len(namespace["TARGET_COLUMNS"]), 5)
        self.assertNotIn("timestamp", namespace["FEATURE_COLUMNS"])
        self.assertEqual(
            namespace["BINARY_FEATURE_COLUMNS"],
            ["pump_state", "fan_state", "grow_light_state"],
        )

    def test_scenario_split_is_deterministic_and_disjoint(self) -> None:
        selector = self.namespace["select_held_out_scenarios"]
        manifest = self.namespace["parameter_manifest"]
        first = selector(manifest)
        second = selector(manifest.sample(frac=1.0, random_state=12))
        self.assertEqual(first, second)
        self.assertEqual(len(first), 4)
        self.assertTrue(
            set(first).isdisjoint(self.namespace["development_scenario_ids"])
        )

    def test_temporal_split_contract(self) -> None:
        ranges = self.namespace["FULL_SPLIT_RANGES"]
        self.assertEqual(ranges["train"][0], pd.Timestamp("2018-01-01 00:00"))
        self.assertEqual(ranges["train"][1], pd.Timestamp("2023-12-31 23:00"))
        self.assertEqual(ranges["validation"][0], pd.Timestamp("2024-01-01 00:00"))
        self.assertEqual(ranges["validation"][1], pd.Timestamp("2024-12-31 23:00"))
        self.assertEqual(ranges["temporal_test"][0], pd.Timestamp("2025-01-01 00:00"))
        self.assertEqual(ranges["temporal_test"][1], pd.Timestamp("2025-12-31 23:00"))

    def test_scalers_fit_only_supplied_train_rows(self) -> None:
        namespace = self.namespace
        timestamps = pd.date_range("2020-01-01", periods=72, freq="h")
        frame = pd.DataFrame({"timestamp": timestamps})
        for column in namespace["TARGET_COLUMNS"]:
            frame[column] = np.r_[np.ones(48), np.full(24, 999.0)]
        for column in namespace["BINARY_FEATURE_COLUMNS"]:
            frame[column] = 0

        transformer, target_scaler, audit = namespace["fit_train_only_scalers"](
            {"development": frame},
            ["development"],
            timestamps[0],
            timestamps[47],
        )
        np.testing.assert_allclose(transformer.continuous_scaler.mean_, np.ones(5))
        np.testing.assert_allclose(target_scaler.mean_, np.ones(5))
        self.assertEqual(audit["feature_fit_rows"], 48)
        self.assertEqual(audit["target_fit_rows"], 24)

    def test_binary_actuators_are_passthrough(self) -> None:
        dataset = self.namespace["datasets"]["train"]
        features, _ = dataset[0]
        scenario_id, target_position = self.namespace["train_sequence_index"].resolve(0)
        input_end = target_position - self.namespace["FORECAST_HORIZON"]
        input_start = input_end - self.namespace["LOOKBACK_STEPS"] + 1
        raw = self.namespace["scenario_frames"][scenario_id].iloc[
            input_start : input_end + 1
        ][self.namespace["BINARY_FEATURE_COLUMNS"]].to_numpy(np.float32)
        np.testing.assert_array_equal(features.numpy()[:, -3:], raw)

    def test_target_alignment_and_boundary_context(self) -> None:
        index = self.namespace["validation_sequence_index"]
        scenario_id = index.scenario_ids[0]
        frame = self.namespace["scenario_frames"][scenario_id]
        boundary = self.namespace["validation_start"]
        code = index.scenario_ids.index(scenario_id)
        positions = index.target_positions[index.scenario_codes == code]
        boundary_position = next(
            int(position)
            for position in positions
            if frame.iloc[position]["timestamp"] == boundary
        )
        input_end = boundary_position - self.namespace["FORECAST_HORIZON"]
        input_start = input_end - self.namespace["LOOKBACK_STEPS"] + 1
        self.assertLess(frame.iloc[input_end]["timestamp"], boundary)
        self.assertLess(frame.iloc[input_start]["timestamp"], boundary)
        self.assertEqual(
            boundary - frame.iloc[input_end]["timestamp"], pd.Timedelta(hours=1)
        )

    def test_sequence_index_is_compact_and_never_crosses_scenario(self) -> None:
        for index in self.namespace["sequence_indices"].values():
            self.assertEqual(index.scenario_codes.dtype, np.int16)
            self.assertEqual(index.target_positions.dtype, np.int32)
            self.assertEqual(len(index), len(index.scenario_codes))
            for item in (0, len(index) - 1):
                scenario_id, _ = index.resolve(item)
                self.assertIn(scenario_id, index.scenario_ids)

    def test_lazy_dataset_and_dataloader_shapes(self) -> None:
        dataset = self.namespace["datasets"]["train"]
        self.assertFalse(hasattr(dataset, "materialized_windows"))
        features, targets = next(iter(self.namespace["train_loader"]))
        self.assertEqual(features.shape, (256, 24, 8))
        self.assertEqual(targets.shape, (256, 5))
        self.assertEqual(features.dtype, torch.float32)
        self.assertEqual(targets.dtype, torch.float32)

    def test_smoke_pipeline_finite_inverse_and_leakage_checks(self) -> None:
        result = self.namespace["smoke_test_result"]
        self.assertTrue(result["finite"])
        self.assertEqual(result["inverse_transform"], "PASS")
        self.assertEqual(result["binary_passthrough"], "PASS")
        self.assertEqual(
            set(self.namespace["leakage_audit"]),
            {"train", "validation", "temporal_test", "scenario_test", "combined_test"},
        )

    def test_preprocessing_artifacts_exported_without_model_checkpoint(self) -> None:
        expected = {
            "feature_scaler.pkl",
            "target_scaler.pkl",
            "split_manifest.json",
            "preprocessing_config.json",
        }
        self.assertEqual({path.name for path in self.artifact_dir.iterdir()}, expected)
        self.assertFalse(any(path.suffix == ".pt" for path in self.artifact_dir.iterdir()))
        self.assertFalse(self.namespace["pipeline_summary"]["full_training_executed"])


if __name__ == "__main__":
    unittest.main()
