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
import validate_multi_horizon_notebook as multi_validator


ROOT = Path(__file__).resolve().parents[1]


class MultiHorizonNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(cls.temporary_directory.name)
        cls.preprocessing_artifact_dir = temporary_root / "preprocessing"
        cls.multi_horizon_artifact_dir = temporary_root / "multi_horizon"

        preprocessing_notebook = preprocessing_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            preprocessing_validator.execute_smoke_namespace(
                preprocessing_notebook,
                data_root=ROOT,
                artifact_dir=cls.preprocessing_artifact_dir,
            )

        cls.notebook = multi_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            cls.namespace = multi_validator.execute_smoke_namespace(
                cls.notebook,
                data_root=ROOT,
                preprocessing_artifact_dir=cls.preprocessing_artifact_dir,
                multi_horizon_artifact_dir=cls.multi_horizon_artifact_dir,
            )
        cls.source = multi_validator.notebook_code_source(cls.notebook)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_01_notebook_json_valid_and_cells_compile(self) -> None:
        self.assertEqual(len(self.notebook.cells), 61)
        self.assertEqual(sum(cell.cell_type == "code" for cell in self.notebook.cells), 30)

    def test_02_concepts_are_synchronized(self) -> None:
        result = multi_validator.validate_concepts_sync(self.notebook)
        self.assertEqual(result, {"status": "PASS", "logical_sections": 31})

    def test_03_default_mode_does_not_enable_smoke(self) -> None:
        configuration = next(
            cell.source
            for cell in self.notebook.cells
            if cell.cell_type == "code" and cell.metadata["section_id"] == "01"
        )
        self.assertIn("MULTI_HORIZON_SMOKE_TEST = False", configuration)
        self.assertNotIn("MULTI_HORIZON_SMOKE_TEST = True", configuration)

    def test_04_static_protocol_audit_passes(self) -> None:
        result = multi_validator.validate_static_protocol(self.notebook)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["final_test_loader_names"], 0)

    def test_05_canonical_membership_comes_only_from_index(self) -> None:
        canonical_index = self.namespace["canonical_index"]
        self.assertEqual(len(canonical_index), 24)
        self.assertEqual(canonical_index["config_hash"].nunique(), 24)
        self.assertNotIn("glob(", self.source)
        self.assertNotIn("rglob(", self.source)

    def test_06_locked_split_is_20_development_4_heldout(self) -> None:
        self.assertEqual(len(self.namespace["development_scenario_ids"]), 20)
        self.assertEqual(len(self.namespace["held_out_scenario_ids"]), 4)
        self.assertFalse(
            set(self.namespace["development_scenario_ids"])
            & set(self.namespace["held_out_scenario_ids"])
        )

    def test_07_heldout_csvs_are_not_resolved_or_loaded(self) -> None:
        self.assertEqual(
            set(self.namespace["development_scenario_paths"]),
            set(self.namespace["development_scenario_ids"]),
        )
        self.assertFalse(
            set(self.namespace["development_scenario_paths"])
            & set(self.namespace["held_out_scenario_ids"])
        )
        self.assertFalse(self.namespace["experiment_summary"]["held_out_csv_loaded"])

    def test_08_feature_and_target_contract(self) -> None:
        self.assertEqual(
            self.namespace["FEATURE_COLUMNS"],
            [
                "air_temperature", "air_humidity", "soil_temperature",
                "soil_moisture", "light_lux", "pump_state", "fan_state",
                "grow_light_state",
            ],
        )
        self.assertEqual(len(self.namespace["TARGET_COLUMNS"]), 5)
        self.assertEqual(self.namespace["LOOKBACK_STEPS"], 24)

    def test_09_horizon_order_is_locked(self) -> None:
        self.assertEqual(self.namespace["FORECAST_HORIZONS"], (1, 3, 6, 12, 24))
        self.assertEqual(self.namespace["MAX_FORECAST_HORIZON"], 24)

    def test_10_expected_full_window_counts_are_locked(self) -> None:
        self.assertEqual(self.namespace["EXPECTED_TRAIN_WINDOWS"], 1_050_740)
        self.assertEqual(self.namespace["EXPECTED_VALIDATION_WINDOWS"], 175_220)
        self.assertEqual(self.namespace["derived_train_per_scenario"], 52_537)
        self.assertEqual(self.namespace["derived_validation_per_scenario"], 8_761)

    def test_11_train_and_validation_ranges_are_locked(self) -> None:
        pd = self.namespace["pd"]
        self.assertEqual(self.namespace["train_start"], pd.Timestamp("2018-01-01"))
        self.assertEqual(self.namespace["train_end"], pd.Timestamp("2023-12-31 23:00"))
        self.assertEqual(self.namespace["validation_start"], pd.Timestamp("2024-01-01"))
        self.assertEqual(
            self.namespace["validation_end"], pd.Timestamp("2024-12-31 23:00")
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
        self.assertNotIn("feature_scaler.fit", self.source)
        self.assertNotIn("target_scaler.fit", self.source)
        self.assertNotIn("partial_fit", self.source)
        self.assertNotIn("fit_transform", self.source)

    def test_13_binary_actuators_are_passthrough(self) -> None:
        scenario_id = self.namespace["active_development_ids"][0]
        arrays = self.namespace["scenario_arrays"][scenario_id]
        self.assertTrue(np.isin(arrays.raw_actuators, [0.0, 1.0]).all())
        np.testing.assert_array_equal(arrays.scaled_features[:, -3:], arrays.raw_actuators)

    def test_14_smoke_window_counts_match_direct_semantics(self) -> None:
        self.assertEqual(
            self.namespace["actual_window_counts"], {"train": 289, "validation": 145}
        )

    def test_15_sequence_index_uses_compact_integer_types(self) -> None:
        for index in (
            self.namespace["train_sequence_index"],
            self.namespace["validation_sequence_index"],
        ):
            self.assertEqual(index.scenario_codes.dtype, np.int16)
            self.assertEqual(index.input_end_positions.dtype, np.int32)

    def test_16_sequence_references_never_cross_scenarios(self) -> None:
        for index in (
            self.namespace["train_sequence_index"],
            self.namespace["validation_sequence_index"],
        ):
            for item in (0, len(index) // 2, len(index) - 1):
                scenario_id, input_end = index.resolve(item)
                self.assertIn(scenario_id, index.scenario_ids)
                self.assertGreaterEqual(input_end - 23, 0)

    def test_17_target_offsets_are_exact(self) -> None:
        index = self.namespace["validation_sequence_index"]
        scenario_id, input_end = index.resolve(len(index) // 2)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        positions = input_end + np.asarray((1, 3, 6, 12, 24))
        deltas = arrays.timestamps[positions] - arrays.timestamps[input_end]
        np.testing.assert_array_equal(
            deltas, np.asarray((1, 3, 6, 12, 24), dtype="timedelta64[h]")
        )

    def test_18_validation_boundary_has_historical_input_only(self) -> None:
        index = self.namespace["validation_sequence_index"]
        scenario_id, input_end = index.resolve(0)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        self.assertLess(arrays.timestamps[input_end], np.datetime64(index.target_start))
        self.assertEqual(
            arrays.timestamps[input_end + 1], np.datetime64(index.target_start)
        )

    def test_19_only_train_and_validation_loaders_exist(self) -> None:
        self.assertIsInstance(self.namespace["train_loader"].sampler, RandomSampler)
        self.assertIsInstance(
            self.namespace["validation_loader"].sampler, SequentialSampler
        )
        for name in multi_validator.FORBIDDEN_FINAL_LOADER_NAMES:
            self.assertNotIn(name, self.namespace)
        self.assertNotIn("loaders", self.namespace)

    def test_20_batch_shapes_and_dtypes(self) -> None:
        features = self.namespace["sample_features"]
        targets = self.namespace["sample_targets"]
        self.assertEqual(features.shape, (256, 24, 8))
        self.assertEqual(targets.shape, (256, 5, 5))
        self.assertEqual(features.dtype, torch.float32)
        self.assertEqual(targets.dtype, torch.float32)

    def test_21_dataset_target_matches_direct_scaler_transform(self) -> None:
        index = self.namespace["train_sequence_index"]
        item = len(index) // 3
        scenario_id, input_end = index.resolve(item)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        positions = input_end + np.asarray((1, 3, 6, 12, 24))
        expected = self.namespace["target_scaler"].transform(
            arrays.raw_targets[positions].astype(np.float64)
        ).astype(np.float32)
        _, target = self.namespace["train_dataset"][item]
        np.testing.assert_allclose(target.numpy(), expected, rtol=1e-6, atol=1e-6)

    def test_22_last_value_repeats_last_sensor_state(self) -> None:
        index = self.namespace["validation_sequence_index"]
        scenario_id, input_end = index.resolve(0)
        expected = self.namespace["scenario_arrays"][scenario_id].raw_targets[input_end]
        predictions = self.namespace["last_value_raw"]
        self.assertEqual(predictions.shape, (145, 5, 5))
        for horizon_index in range(5):
            np.testing.assert_array_equal(predictions[0, horizon_index], expected)

    def test_23_daily_seasonal_uses_only_past_observations(self) -> None:
        index = self.namespace["validation_sequence_index"]
        scenario_id, input_end = index.resolve(0)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        for horizon_index, horizon in enumerate((1, 3, 6, 12, 24)):
            expected = arrays.raw_targets[input_end + horizon - 24]
            np.testing.assert_array_equal(
                self.namespace["seasonal_raw"][0, horizon_index], expected
            )
            self.assertLessEqual(input_end + horizon - 24, input_end)

    def test_24_daily_seasonal_h24_equals_last_value(self) -> None:
        np.testing.assert_array_equal(
            self.namespace["seasonal_raw"][:, -1],
            self.namespace["last_value_raw"][:, -1],
        )

    def test_25_model_configuration_is_symmetric(self) -> None:
        config = self.namespace["model_config"]
        self.assertEqual(config.input_size, 8)
        self.assertEqual(config.hidden_size, 64)
        self.assertEqual(config.num_layers, 1)
        self.assertEqual(config.num_horizons, 5)
        self.assertEqual(config.output_size, 5)

    def test_26_gru_and_lstm_forward_shapes(self) -> None:
        features = self.namespace["sample_features"][:8]
        config = self.namespace["model_config"]
        gru = self.namespace["DirectMultiHorizonGRUForecaster"](config)
        lstm = self.namespace["DirectMultiHorizonLSTMForecaster"](config)
        self.assertEqual(gru(features).shape, (8, 5, 5))
        self.assertEqual(lstm(features).shape, (8, 5, 5))

    def _assert_backward(self, model_class_name: str) -> None:
        model = self.namespace[model_class_name](self.namespace["model_config"])
        features = self.namespace["sample_features"][:16]
        targets = self.namespace["sample_targets"][:16]
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-4)
        optimizer.zero_grad(set_to_none=True)
        loss = nn.MSELoss()(model(features), targets)
        loss.backward()
        gradients = [p.grad for p in model.parameters() if p.grad is not None]
        self.assertTrue(gradients)
        self.assertTrue(all(torch.isfinite(gradient).all() for gradient in gradients))
        optimizer.step()

    def test_27_gru_backward_has_finite_gradients(self) -> None:
        self._assert_backward("DirectMultiHorizonGRUForecaster")

    def test_28_lstm_backward_has_finite_gradients(self) -> None:
        self._assert_backward("DirectMultiHorizonLSTMForecaster")

    def test_29_loss_is_equal_weighted_over_horizon_target_tensor(self) -> None:
        predictions = torch.arange(50, dtype=torch.float32).reshape(2, 5, 5)
        targets = torch.zeros_like(predictions)
        self.assertEqual(
            nn.MSELoss()(predictions, targets).item(),
            torch.mean((predictions - targets) ** 2).item(),
        )

    def test_30_smoke_training_is_bounded(self) -> None:
        self.assertEqual(len(self.namespace["gru_result"]["history"]), 1)
        self.assertEqual(len(self.namespace["lstm_result"]["history"]), 1)
        self.assertEqual(self.namespace["SMOKE_MAX_TRAIN_BATCHES"], 3)
        self.assertEqual(self.namespace["SMOKE_MAX_VALIDATION_BATCHES"], 2)

    def test_31_model_selection_is_validation_only(self) -> None:
        record = self.namespace["model_selection_record"]
        self.assertIn("validation", record["criterion"])
        self.assertFalse(record["final_test_metrics_used"])
        self.assertEqual(set(record["validation_losses"]), {"GRU", "LSTM"})

    def test_32_validation_predictions_have_direct_output_shape(self) -> None:
        for predictions in self.namespace["validation_predictions_scaled"].values():
            self.assertEqual(predictions.shape, (145, 5, 5))
            self.assertTrue(np.isfinite(predictions).all())

    def test_33_metrics_cover_four_models_and_five_horizons(self) -> None:
        metrics = self.namespace["validation_by_horizon"]
        self.assertEqual(len(metrics), 20)
        self.assertEqual(metrics["Model"].nunique(), 4)
        self.assertEqual(set(metrics["HorizonHours"]), {1, 3, 6, 12, 24})
        self.assertTrue(np.isfinite(metrics.select_dtypes(include=[np.number])).all().all())

    def test_34_metrics_include_each_physical_target(self) -> None:
        metrics = self.namespace["validation_by_horizon"]
        for target in self.namespace["TARGET_COLUMNS"]:
            for suffix in ("MAE", "RMSE", "R2"):
                self.assertIn(f"{target}_{suffix}", metrics.columns)

    def test_35_horizon_degradation_is_one_at_h1(self) -> None:
        degradation = self.namespace["horizon_degradation"]
        reference = degradation[degradation["HorizonHours"] == 1]
        np.testing.assert_allclose(reference["MAE_ratio_vs_h1"], 1.0)
        np.testing.assert_allclose(reference["RMSE_ratio_vs_h1"], 1.0)

    def test_36_skill_scores_are_finite_and_horizon_specific(self) -> None:
        skill = self.namespace["skill_scores"]
        self.assertEqual(len(skill), 20)
        self.assertIn("Skill_vs_LastValue", skill.columns)
        self.assertIn("Skill_vs_Seasonal", skill.columns)
        self.assertTrue(np.isfinite(skill.select_dtypes(include=[np.number])).all().all())

    def test_37_future_control_labels_are_posthoc_and_shaped(self) -> None:
        labels = self.namespace["control_change_labels"]
        self.assertEqual(labels.shape, (145, 5))
        self.assertEqual(labels.dtype, np.bool_)
        self.assertEqual(
            self.namespace["FEATURE_COLUMNS"][-3:],
            self.namespace["BINARY_FEATURE_COLUMNS"],
        )

    def test_38_future_control_audit_is_finite(self) -> None:
        audit = self.namespace["future_control_audit"]
        self.assertFalse(audit.empty)
        self.assertTrue(
            np.isfinite(audit.select_dtypes(include=[np.number]).to_numpy()).all()
        )
        self.assertTrue(set(audit["HorizonHours"]).issubset({1, 3, 6, 12, 24}))

    def test_39_checkpoint_reload_and_metadata_pass(self) -> None:
        for model_name, filename in (
            ("GRU", "best_gru_multihorizon.pt"),
            ("LSTM", "best_lstm_multihorizon.pt"),
        ):
            path = self.multi_horizon_artifact_dir / "checkpoints" / filename
            self.assertTrue(path.is_file())
            checkpoint = self.namespace["load_checkpoint"](path, "cpu")
            self.assertEqual(checkpoint["forecast_horizons"], [1, 3, 6, 12, 24])
            self.assertEqual(checkpoint["training_mode"], "direct_multi_horizon")
            self.assertEqual(checkpoint["future_control_policy"], "past_only")
            self.assertEqual(
                self.namespace["checkpoint_reload_audit"][model_name]["status"], "PASS"
            )

    def test_40_required_artifacts_and_plots_exist(self) -> None:
        required = (
            "histories/gru_multihorizon_history.json",
            "histories/lstm_multihorizon_history.json",
            "metrics/validation_by_horizon.csv",
            "metrics/horizon_degradation.csv",
            "metrics/skill_scores.csv",
            "metrics/future_control_audit.csv",
            "plots/gru_loss_curve.png",
            "plots/lstm_loss_curve.png",
            "plots/standardized_mse_vs_horizon.png",
            "plots/mae_vs_horizon_by_target.png",
            "plots/preferred_model_24h_validation.png",
            "multi_horizon_run_manifest.json",
        )
        self.assertTrue(
            all((self.multi_horizon_artifact_dir / relative).is_file() for relative in required)
        )

    def test_41_run_manifest_locks_past_only_protocol(self) -> None:
        path = self.multi_horizon_artifact_dir / "multi_horizon_run_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["forecast_horizons"], [1, 3, 6, 12, 24])
        self.assertIn("past_only", manifest["future_control_policy"])
        self.assertFalse(manifest["multi_horizon_final_tests_executed"])
        self.assertTrue(manifest["multi_horizon_smoke_test"])

    def test_42_summary_preserves_final_test_embargo(self) -> None:
        summary = self.namespace["experiment_summary"]
        self.assertFalse(summary["final_test_loaders_constructed"])
        self.assertFalse(summary["multi_horizon_final_tests_executed"])
        self.assertFalse(summary["held_out_csv_loaded"])
        self.assertFalse(summary["scaler_refit_performed"])

    def test_43_local_execution_did_not_run_full_training(self) -> None:
        summary = self.namespace["experiment_summary"]
        self.assertTrue(summary["multi_horizon_smoke_test"])
        self.assertFalse(summary["full_multi_horizon_training_executed"])

    def test_44_no_external_weather_or_physics_features_are_inputs(self) -> None:
        forbidden = {
            "temperature_outside", "humidity_outside", "wind_speed",
            "shortwave_radiation", "vpd_inside", "ventilation_rate",
            "evapotranspiration_rate", "condensation_rate", "drainage_rate",
        }
        self.assertFalse(forbidden & set(self.namespace["FEATURE_COLUMNS"]))


if __name__ == "__main__":
    unittest.main()
