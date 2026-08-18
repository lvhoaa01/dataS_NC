from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import joblib
import numpy as np
import torch
from torch import nn
from torch.utils.data import RandomSampler, SequentialSampler

import validate_ml_notebook as preprocessing_validator
import validate_operational_lookback_notebook as lookback_validator


ROOT = Path(__file__).resolve().parents[1]


class OperationalLookbackNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(cls.temporary_directory.name)
        cls.preprocessing_artifact_dir = temporary_root / "preprocessing"
        cls.lookback_artifact_dir = temporary_root / "lookback_ablation"

        preprocessing_notebook = preprocessing_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            preprocessing_validator.execute_smoke_namespace(
                preprocessing_notebook,
                data_root=ROOT,
                artifact_dir=cls.preprocessing_artifact_dir,
            )

        cls.notebook = lookback_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            cls.namespace = lookback_validator.execute_smoke_namespace(
                cls.notebook,
                data_root=ROOT,
                preprocessing_artifact_dir=cls.preprocessing_artifact_dir,
                lookback_artifact_dir=cls.lookback_artifact_dir,
            )
        cls.source = lookback_validator.notebook_code_source(cls.notebook)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_01_notebook_json_valid_and_code_cells_compile(self) -> None:
        self.assertEqual(len(self.notebook.cells), 62)
        self.assertEqual(sum(cell.cell_type == "code" for cell in self.notebook.cells), 30)

    def test_02_concepts_document_is_synchronized(self) -> None:
        result = lookback_validator.validate_concepts_sync(self.notebook)
        self.assertEqual(result, {"status": "PASS", "logical_sections": 32})

    def test_03_final_default_does_not_enable_smoke(self) -> None:
        configuration = next(
            cell.source
            for cell in self.notebook.cells
            if cell.cell_type == "code" and cell.metadata["section_id"] == "02"
        )
        self.assertIn("LOOKBACK_ABLATION_SMOKE_TEST = False", configuration)
        self.assertNotIn("LOOKBACK_ABLATION_SMOKE_TEST = True", configuration)

    def test_04_static_protocol_audit_passes(self) -> None:
        result = lookback_validator.validate_static_protocol(self.notebook)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["architecture_escalations"], 0)

    def test_05_lookback_candidates_are_locked(self) -> None:
        self.assertEqual(self.namespace["LOOKBACK_CANDIDATES"], (24, 48, 72))

    def test_06_operational_horizons_are_locked(self) -> None:
        self.assertEqual(self.namespace["FORECAST_HORIZONS"], (1, 3))

    def test_07_maximum_lookback_and_horizon_are_locked(self) -> None:
        self.assertEqual(self.namespace["MAX_LOOKBACK"], 72)
        self.assertEqual(self.namespace["MAX_FORECAST_HORIZON"], 3)

    def test_08_canonical_membership_uses_index_only(self) -> None:
        index = self.namespace["canonical_index"]
        self.assertEqual(len(index), 24)
        self.assertEqual(index["parameter_set_id"].nunique(), 24)
        self.assertEqual(index["config_hash"].nunique(), 24)
        self.assertNotIn("glob(", self.source)
        self.assertNotIn("rglob(", self.source)

    def test_09_split_remains_20_development_4_heldout(self) -> None:
        self.assertEqual(len(self.namespace["development_scenario_ids"]), 20)
        self.assertEqual(len(self.namespace["held_out_scenario_ids"]), 4)
        self.assertFalse(
            set(self.namespace["development_scenario_ids"])
            & set(self.namespace["held_out_scenario_ids"])
        )

    def test_10_heldout_csvs_are_not_resolved_or_loaded(self) -> None:
        paths = self.namespace["development_scenario_paths"]
        self.assertEqual(set(paths), set(self.namespace["development_scenario_ids"]))
        self.assertFalse(set(paths) & set(self.namespace["held_out_scenario_ids"]))
        self.assertFalse(self.namespace["experiment_summary"]["held_out_csv_loaded"])

    def test_11_feature_and_target_contracts_are_unchanged(self) -> None:
        self.assertEqual(len(self.namespace["FEATURE_COLUMNS"]), 8)
        self.assertEqual(len(self.namespace["TARGET_COLUMNS"]), 5)
        self.assertEqual(
            self.namespace["FEATURE_COLUMNS"][-3:],
            ["pump_state", "fan_state", "grow_light_state"],
        )

    def test_12_scalers_are_loaded_without_refit(self) -> None:
        feature_scaler = joblib.load(self.preprocessing_artifact_dir / "feature_scaler.pkl")
        target_scaler = joblib.load(self.preprocessing_artifact_dir / "target_scaler.pkl")
        np.testing.assert_array_equal(
            self.namespace["feature_scaler"].mean_, feature_scaler.mean_
        )
        np.testing.assert_array_equal(
            self.namespace["target_scaler"].scale_, target_scaler.scale_
        )
        for prohibited in (
            "feature_scaler.fit", "target_scaler.fit", "partial_fit", "fit_transform"
        ):
            self.assertNotIn(prohibited, self.source)

    def test_13_all_lookbacks_share_same_scaler_objects(self) -> None:
        self.assertIs(
            self.namespace["train_datasets"][24].arrays,
            self.namespace["train_datasets"][48].arrays,
        )
        self.assertIs(
            self.namespace["train_datasets"][48].arrays,
            self.namespace["train_datasets"][72].arrays,
        )

    def test_14_binary_actuators_are_passthrough(self) -> None:
        scenario_id = self.namespace["active_development_ids"][0]
        arrays = self.namespace["scenario_arrays"][scenario_id]
        self.assertTrue(np.isin(arrays.raw_actuators, [0.0, 1.0]).all())
        np.testing.assert_array_equal(arrays.scaled_features[:, -3:], arrays.raw_actuators)

    def test_15_expected_common_window_counts_are_locked(self) -> None:
        self.assertEqual(self.namespace["derived_common_train_per_scenario"], 52_510)
        self.assertEqual(self.namespace["derived_common_validation_per_scenario"], 8_782)
        self.assertEqual(self.namespace["EXPECTED_COMMON_TRAIN_WINDOWS"], 1_050_200)
        self.assertEqual(self.namespace["EXPECTED_COMMON_VALIDATION_WINDOWS"], 175_640)

    def test_16_smoke_common_window_counts_follow_same_semantics(self) -> None:
        self.assertEqual(
            self.namespace["actual_common_window_counts"],
            {"train": 262, "validation": 166},
        )

    def test_17_common_train_index_is_shared_by_all_lookbacks(self) -> None:
        common_index = self.namespace["common_train_index"]
        for dataset in self.namespace["train_datasets"].values():
            self.assertIs(dataset.common_index, common_index)

    def test_18_common_validation_index_is_shared_by_all_lookbacks(self) -> None:
        common_index = self.namespace["common_validation_index"]
        for dataset in self.namespace["validation_datasets"].values():
            self.assertIs(dataset.common_index, common_index)

    def test_19_scenario_codes_and_target_positions_are_identical(self) -> None:
        train_index = self.namespace["common_train_index"]
        validation_index = self.namespace["common_validation_index"]
        self.assertEqual(train_index.scenario_codes.dtype, np.int16)
        self.assertEqual(train_index.input_end_positions.dtype, np.int32)
        self.assertEqual(validation_index.scenario_codes.dtype, np.int16)
        self.assertEqual(validation_index.input_end_positions.dtype, np.int32)
        self.assertTrue(self.namespace["fairness_audit"]["same_target_positions"])

    def test_20_target_tensors_are_exactly_identical(self) -> None:
        item = len(self.namespace["common_train_index"]) // 3
        reference = self.namespace["train_datasets"][24][item][1]
        for lookback in (48, 72):
            torch.testing.assert_close(
                self.namespace["train_datasets"][lookback][item][1],
                reference,
                rtol=0,
                atol=0,
            )

    def test_21_shorter_inputs_are_exact_suffixes_of_longer_inputs(self) -> None:
        item = len(self.namespace["common_train_index"]) // 4
        input_24 = self.namespace["train_datasets"][24][item][0]
        input_48 = self.namespace["train_datasets"][48][item][0]
        input_72 = self.namespace["train_datasets"][72][item][0]
        torch.testing.assert_close(input_48[-24:], input_24, rtol=0, atol=0)
        torch.testing.assert_close(input_72[-48:], input_48, rtol=0, atol=0)

    def _assert_sample_shape(self, lookback: int) -> None:
        features, targets = self.namespace["sample_batches"][lookback]
        self.assertEqual(features.shape, (256, lookback, 8))
        self.assertEqual(targets.shape, (256, 2, 5))
        self.assertEqual(features.dtype, torch.float32)
        self.assertEqual(targets.dtype, torch.float32)

    def test_22_x24_shape_is_correct(self) -> None:
        self._assert_sample_shape(24)

    def test_23_x48_shape_is_correct(self) -> None:
        self._assert_sample_shape(48)

    def test_24_x72_shape_is_correct(self) -> None:
        self._assert_sample_shape(72)

    def test_25_target_shape_is_b_2_5_for_all_lookbacks(self) -> None:
        for _, targets in self.namespace["sample_batches"].values():
            self.assertEqual(targets.shape[1:], (2, 5))

    def test_26_no_future_sensor_or_actuator_input(self) -> None:
        index = self.namespace["common_validation_index"]
        scenario_id, input_end = index.resolve(0)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        for lookback in (24, 48, 72):
            features, _ = self.namespace["validation_datasets"][lookback][0]
            expected = arrays.scaled_features[input_end - lookback + 1 : input_end + 1]
            np.testing.assert_array_equal(features.numpy(), expected)
        self.assertGreater(input_end + 1, input_end)

    def test_27_validation_boundary_historical_context_is_legal(self) -> None:
        index = self.namespace["common_validation_index"]
        scenario_id, input_end = index.resolve(0)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        self.assertEqual(
            arrays.timestamps[input_end], np.datetime64("2023-12-31T23:00")
        )
        self.assertEqual(
            arrays.timestamps[input_end + 1], np.datetime64("2024-01-01T00:00")
        )
        self.assertEqual(
            arrays.timestamps[input_end + 3], np.datetime64("2024-01-01T02:00")
        )

    def test_28_sequence_references_never_cross_scenarios(self) -> None:
        for index in (
            self.namespace["common_train_index"],
            self.namespace["common_validation_index"],
        ):
            for item in (0, len(index) // 2, len(index) - 1):
                scenario_id, input_end = index.resolve(item)
                self.assertIn(scenario_id, index.scenario_ids)
                self.assertGreaterEqual(input_end - 71, 0)

    def test_29_only_train_and_validation_loaders_exist(self) -> None:
        self.assertTrue(
            all(isinstance(loader.sampler, RandomSampler) for loader in self.namespace["train_loaders"].values())
        )
        self.assertTrue(
            all(isinstance(loader.sampler, SequentialSampler) for loader in self.namespace["validation_loaders"].values())
        )
        for name in lookback_validator.FORBIDDEN_FINAL_LOADER_NAMES:
            self.assertNotIn(name, self.namespace)

    def test_30_last_value_baseline_is_correct(self) -> None:
        index = self.namespace["common_validation_index"]
        scenario_id, input_end = index.resolve(0)
        expected = self.namespace["scenario_arrays"][scenario_id].raw_targets[input_end]
        for horizon_index in range(2):
            np.testing.assert_array_equal(
                self.namespace["last_value_raw"][0, horizon_index], expected
            )

    def test_31_daily_seasonal_baseline_is_past_only(self) -> None:
        index = self.namespace["common_validation_index"]
        scenario_id, input_end = index.resolve(0)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        for horizon_index, horizon in enumerate((1, 3)):
            expected_position = input_end + horizon - 24
            self.assertLessEqual(expected_position, input_end)
            np.testing.assert_array_equal(
                self.namespace["seasonal_raw"][0, horizon_index],
                arrays.raw_targets[expected_position],
            )

    def test_32_model_architecture_is_fixed(self) -> None:
        config = self.namespace["model_config"]
        self.assertEqual(config.input_size, 8)
        self.assertEqual(config.hidden_size, 64)
        self.assertEqual(config.num_layers, 1)
        self.assertEqual(config.num_horizons, 2)
        self.assertEqual(config.output_size, 5)

    def test_33_parameter_count_is_identical(self) -> None:
        counts = self.namespace["parameter_counts"]
        self.assertEqual(set(counts), {24, 48, 72})
        self.assertEqual(len(set(counts.values())), 1)
        self.assertEqual(next(iter(counts.values())), 19_594)

    def test_34_initialization_hash_is_identical(self) -> None:
        hashes = self.namespace["initialization_hashes"]
        self.assertEqual(len(set(hashes.values())), 1)

    def test_35_lstm_forward_shape_for_every_lookback(self) -> None:
        model_class = self.namespace["OperationalMultiHorizonLSTM"]
        for lookback in (24, 48, 72):
            model = model_class(self.namespace["model_config"])
            features = self.namespace["sample_batches"][lookback][0][:8]
            self.assertEqual(model(features).shape, (8, 2, 5))

    def test_36_backward_gradients_are_finite_for_every_lookback(self) -> None:
        model_class = self.namespace["OperationalMultiHorizonLSTM"]
        for lookback in (24, 48, 72):
            model = model_class(self.namespace["model_config"])
            features, targets = self.namespace["sample_batches"][lookback]
            optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
            optimizer.zero_grad(set_to_none=True)
            loss = nn.MSELoss()(model(features[:8]), targets[:8])
            loss.backward()
            gradients = [p.grad for p in model.parameters() if p.grad is not None]
            self.assertTrue(gradients)
            self.assertTrue(all(torch.isfinite(gradient).all() for gradient in gradients))
            optimizer.step()

    def test_37_loss_is_equal_weighted_standardized_mse(self) -> None:
        predictions = torch.arange(40, dtype=torch.float32).reshape(4, 2, 5)
        targets = torch.zeros_like(predictions)
        self.assertEqual(
            nn.MSELoss()(predictions, targets).item(),
            torch.mean((predictions - targets) ** 2).item(),
        )

    def test_38_smoke_training_is_bounded_for_all_lookbacks(self) -> None:
        for lookback in (24, 48, 72):
            self.assertEqual(len(self.namespace["experiment_results"][lookback]["history"]), 1)
        self.assertEqual(self.namespace["SMOKE_MAX_TRAIN_BATCHES"], 3)
        self.assertEqual(self.namespace["SMOKE_MAX_VALIDATION_BATCHES"], 2)

    def test_39_validation_targets_remain_exactly_identical(self) -> None:
        reference = self.namespace["validation_targets_scaled_by_lookback"][24]
        for lookback in (48, 72):
            np.testing.assert_array_equal(
                self.namespace["validation_targets_scaled_by_lookback"][lookback],
                reference,
            )

    def test_40_physical_metrics_cover_two_horizons(self) -> None:
        metrics = self.namespace["lookback_validation_by_horizon"]
        self.assertEqual(len(metrics), 6)
        self.assertEqual(set(metrics["LookbackHours"]), {24, 48, 72})
        self.assertEqual(set(metrics["HorizonHours"]), {1, 3})
        for target in self.namespace["TARGET_COLUMNS"]:
            for suffix in ("MAE", "RMSE", "R2"):
                self.assertIn(f"{target}_{suffix}", metrics.columns)
        self.assertTrue(np.isfinite(metrics.select_dtypes(include=[np.number])).all().all())

    def test_41_per_target_comparison_has_expected_rows(self) -> None:
        comparison = self.namespace["lookback_target_comparison"]
        self.assertEqual(len(comparison), 30)
        self.assertEqual(comparison["Target"].nunique(), 5)
        self.assertTrue(np.isfinite(comparison.select_dtypes(include=[np.number])).all().all())

    def test_42_relative_improvement_formula_is_correct(self) -> None:
        function = self.namespace["relative_mse_improvement"]
        self.assertAlmostEqual(function(10.0, 8.0), 0.2)
        with self.assertRaises(ValueError):
            function(0.0, 1.0)

    def test_43_runtime_efficiency_summary_is_generated(self) -> None:
        summary = self.namespace["lookback_summary"]
        self.assertEqual(len(summary), 3)
        for column in (
            "TrainDurationSeconds", "MeanEpochSeconds", "ValidationInferenceSeconds",
            "MeanTrainSamplesPerSecond", "ParameterCount",
        ):
            self.assertIn(column, summary.columns)
            self.assertTrue((summary[column] > 0).all())

    def test_44_input_cost_scales_only_with_sequence_length(self) -> None:
        summary = self.namespace["lookback_summary"]
        self.assertEqual(summary["InputElementsPerSample"].tolist(), [192, 384, 576])
        self.assertEqual(summary["ParameterCount"].nunique(), 1)
        bytes_per_batch = summary["ApproxInputBytesPerBatch"].to_numpy()
        np.testing.assert_array_equal(bytes_per_batch / bytes_per_batch[0], [1.0, 2.0, 3.0])

    def test_45_practical_tradeoff_does_not_hardcode_winner(self) -> None:
        analysis = self.namespace["practical_analysis"]
        self.assertIn(analysis["best_accuracy_lookback"], (24, 48, 72))
        self.assertIn("without an arbitrary", analysis["selection_policy"])
        self.assertEqual(analysis["scientific_status"], "SMOKE_INTEGRATION_ONLY")

    def test_46_checkpoints_reload_for_all_lookbacks(self) -> None:
        for lookback in (24, 48, 72):
            audit = self.namespace["checkpoint_reload_audit"][lookback]
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(audit["input_shape"][1:], [lookback, 8])
            self.assertEqual(audit["output_shape"][1:], [2, 5])

    def test_47_checkpoint_contract_is_complete(self) -> None:
        for lookback in (24, 48, 72):
            path = self.lookback_artifact_dir / "checkpoints" / f"best_lstm_lookback{lookback}.pt"
            checkpoint = self.namespace["load_checkpoint"](path, "cpu")
            self.assertEqual(checkpoint["lookback_steps"], lookback)
            self.assertEqual(checkpoint["forecast_horizons"], [1, 3])
            self.assertEqual(checkpoint["operational_horizons"], [1, 3])
            self.assertEqual(checkpoint["strategy"], "direct_multi_horizon")
            self.assertEqual(checkpoint["future_control_policy"], "past_only")

    def test_48_required_metrics_histories_and_plots_exist(self) -> None:
        required = [
            *(f"histories/lookback{lookback}_history.json" for lookback in (24, 48, 72)),
            "metrics/lookback_summary.csv",
            "metrics/lookback_validation_by_horizon.csv",
            "metrics/lookback_target_comparison.csv",
            "metrics/persistence_baselines.json",
            "plots/loss_24h.png",
            "plots/loss_48h.png",
            "plots/loss_72h.png",
            "plots/validation_mse_vs_lookback.png",
            "plots/mae_1h_vs_lookback.png",
            "plots/mae_3h_vs_lookback.png",
            "plots/accuracy_runtime_tradeoff.png",
            "lookback_ablation_manifest.json",
        ]
        self.assertTrue(
            all((self.lookback_artifact_dir / relative).is_file() for relative in required)
        )

    def test_49_manifest_records_common_index_and_final_test_embargo(self) -> None:
        path = self.lookback_artifact_dir / "lookback_ablation_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(manifest["common_target_index"])
        self.assertEqual(manifest["lookback_candidates"], [24, 48, 72])
        self.assertEqual(manifest["forecast_horizons"], [1, 3])
        self.assertFalse(manifest["held_out_csv_loaded"])
        self.assertFalse(manifest["final_test_loaders_constructed"])
        self.assertFalse(manifest["final_tests_executed"])

    def test_50_summary_preserves_controlled_ablation_invariants(self) -> None:
        summary = self.namespace["experiment_summary"]
        for key in (
            "common_target_index", "same_target_references", "same_scenario_references",
            "same_scalers", "same_architecture", "same_parameter_count", "same_seed_policy",
        ):
            self.assertTrue(summary[key])

    def test_51_local_execution_did_not_run_full_or_final_tests(self) -> None:
        summary = self.namespace["experiment_summary"]
        self.assertTrue(summary["lookback_ablation_smoke_test"])
        self.assertFalse(summary["full_lookback_ablation_executed"])
        self.assertFalse(summary["final_test_loaders_constructed"])
        self.assertFalse(summary["final_tests_executed"])

    def test_52_no_external_calendar_weather_or_physics_features(self) -> None:
        forbidden = {
            "hour_of_day", "day_of_year", "temperature_outside", "humidity_outside",
            "wind_speed", "shortwave_radiation", "vpd_inside", "ventilation_rate",
            "evapotranspiration_rate", "scenario_id",
        }
        self.assertFalse(forbidden & set(self.namespace["FEATURE_COLUMNS"]))


if __name__ == "__main__":
    unittest.main()
