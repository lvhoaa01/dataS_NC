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
import validate_ml_training_notebook as training_validator


ROOT = Path(__file__).resolve().parents[1]


class MLTrainingNotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(cls.temporary_directory.name)
        cls.preprocessing_artifact_dir = temporary_root / "preprocessing"
        cls.model_artifact_dir = temporary_root / "model_training_smoke"

        preprocessing_notebook = preprocessing_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            preprocessing_validator.execute_smoke_namespace(
                preprocessing_notebook,
                data_root=ROOT,
                artifact_dir=cls.preprocessing_artifact_dir,
            )

        cls.notebook = training_validator.load_and_compile_notebook()
        with redirect_stdout(io.StringIO()):
            cls.namespace = training_validator.execute_smoke_namespace(
                cls.notebook,
                data_root=ROOT,
                preprocessing_artifact_dir=cls.preprocessing_artifact_dir,
                model_artifact_dir=cls.model_artifact_dir,
            )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary_directory.cleanup()

    def test_notebook_json_valid_and_code_cells_compile(self) -> None:
        self.assertEqual(len(self.notebook.cells), 53)
        self.assertEqual(sum(cell.cell_type == "code" for cell in self.notebook.cells), 26)

    def test_concepts_document_is_synchronized(self) -> None:
        sync = training_validator.validate_concepts_sync(self.notebook)
        self.assertEqual(sync["status"], "PASS")
        self.assertEqual(sync["logical_sections"], 27)

    def test_final_default_does_not_enable_smoke(self) -> None:
        configuration_source = next(
            cell.source
            for cell in self.notebook.cells
            if cell.cell_type == "code" and cell.metadata["section_id"] == "01"
        )
        self.assertIn("TRAINING_SMOKE_TEST = False", configuration_source)
        self.assertNotIn("TRAINING_SMOKE_TEST = True", configuration_source)

    def test_canonical_membership_comes_only_from_index(self) -> None:
        self.assertEqual(len(self.namespace["canonical_index"]), 24)
        self.assertEqual(
            set(self.namespace["canonical_index"]["parameter_set_id"]),
            set(self.namespace["scenario_paths"]),
        )
        source = "\n".join(
            cell.source for cell in self.notebook.cells if cell.cell_type == "code"
        )
        self.assertNotIn("glob(", source)
        self.assertNotIn("rglob(", source)

    def test_locked_split_ids_are_loaded_not_reselected(self) -> None:
        split_path = self.preprocessing_artifact_dir / "split_manifest.json"
        split_manifest = json.loads(split_path.read_text(encoding="utf-8"))
        self.assertEqual(
            self.namespace["development_scenario_ids"],
            split_manifest["development_scenario_ids"],
        )
        self.assertEqual(
            self.namespace["held_out_scenario_ids"],
            split_manifest["held_out_scenario_ids"],
        )
        source = "\n".join(
            cell.source for cell in self.notebook.cells if cell.cell_type == "code"
        )
        self.assertNotIn("select_held_out_scenarios", source)

    def test_feature_target_and_window_contracts(self) -> None:
        self.assertEqual(len(self.namespace["FEATURE_COLUMNS"]), 8)
        self.assertEqual(len(self.namespace["TARGET_COLUMNS"]), 5)
        self.assertEqual(self.namespace["LOOKBACK_STEPS"], 24)
        self.assertEqual(self.namespace["FORECAST_HORIZON"], 1)

    def test_locked_full_window_counts_are_protected(self) -> None:
        self.assertEqual(
            self.namespace["LOCKED_WINDOW_COUNTS"],
            {
                "train": 1_051_200,
                "validation": 175_680,
                "temporal_test": 175_200,
                "scenario_test": 245_376,
                "combined_test": 35_040,
            },
        )

    def test_scaler_artifacts_are_loaded_without_refit(self) -> None:
        feature_scaler = joblib.load(self.preprocessing_artifact_dir / "feature_scaler.pkl")
        target_scaler = joblib.load(self.preprocessing_artifact_dir / "target_scaler.pkl")
        np.testing.assert_array_equal(
            self.namespace["feature_scaler"].mean_, feature_scaler.mean_
        )
        np.testing.assert_array_equal(
            self.namespace["target_scaler"].mean_, target_scaler.mean_
        )
        source = "\n".join(
            cell.source for cell in self.notebook.cells if cell.cell_type == "code"
        )
        self.assertNotIn("partial_fit", source)
        self.assertNotIn("feature_scaler.fit", source)
        self.assertNotIn("target_scaler.fit", source)
        self.assertFalse(self.namespace["experiment_summary"]["scaler_refit_performed"])

    def test_binary_actuator_passthrough(self) -> None:
        arrays = self.namespace["scenario_arrays"][self.namespace["active_development_ids"][0]]
        self.assertTrue(np.isin(arrays.scaled_features[:, -3:], [0.0, 1.0]).all())

    def test_optimized_dataset_matches_direct_scaler_logic(self) -> None:
        index = self.namespace["sequence_indices"]["train"]
        item = len(index) // 3
        scenario_id, target_position = index.resolve(item)
        arrays = self.namespace["scenario_arrays"][scenario_id]
        input_end = target_position - 1
        input_start = input_end - 23
        expected_continuous = self.namespace["feature_scaler"].transform(
            arrays.raw_targets[input_start : input_end + 1].astype(np.float64)
        ).astype(np.float32)
        expected = np.column_stack(
            [expected_continuous, arrays.scaled_features[input_start : input_end + 1, -3:]]
        ).astype(np.float32)
        features, target = self.namespace["datasets"]["train"][item]
        np.testing.assert_allclose(features.numpy(), expected, rtol=1e-6, atol=1e-6)
        expected_target = self.namespace["target_scaler"].transform(
            arrays.raw_targets[[target_position]].astype(np.float64)
        ).astype(np.float32)[0]
        np.testing.assert_allclose(target.numpy(), expected_target, rtol=1e-6, atol=1e-6)

    def test_sequence_references_never_cross_scenario(self) -> None:
        for index in self.namespace["sequence_indices"].values():
            self.assertEqual(index.scenario_codes.dtype, np.int16)
            self.assertEqual(index.target_positions.dtype, np.int32)
            for item in (0, len(index) - 1):
                scenario_id, position = index.resolve(item)
                self.assertIn(scenario_id, index.scenario_ids)
                self.assertGreaterEqual(position - 1 - 23, 0)

    def test_validation_boundary_uses_only_historical_context(self) -> None:
        index = self.namespace["sequence_indices"]["validation"]
        scenario_id = index.scenario_ids[0]
        arrays = self.namespace["scenario_arrays"][scenario_id]
        boundary = np.datetime64(self.namespace["active_validation_start"])
        code = index.scenario_ids.index(scenario_id)
        positions = index.target_positions[index.scenario_codes == code]
        boundary_position = next(int(position) for position in positions if arrays.timestamps[position] == boundary)
        input_end = boundary_position - 1
        input_start = input_end - 23
        self.assertLess(arrays.timestamps[input_end], boundary)
        self.assertEqual(boundary - arrays.timestamps[input_end], np.timedelta64(1, "h"))
        self.assertEqual(
            arrays.timestamps[input_end] - arrays.timestamps[input_start],
            np.timedelta64(23, "h"),
        )

    def test_loader_sampling_policy(self) -> None:
        self.assertIsInstance(self.namespace["train_loader"].sampler, RandomSampler)
        for name in ("validation", "temporal_test", "scenario_test", "combined_test"):
            self.assertIsInstance(self.namespace["loaders"][name].sampler, SequentialSampler)

    def test_batch_shapes_and_dtype(self) -> None:
        features, targets = self.namespace["sample_batch"]
        self.assertEqual(features.shape, (256, 24, 8))
        self.assertEqual(targets.shape, (256, 5))
        self.assertEqual(features.dtype, torch.float32)
        self.assertEqual(targets.dtype, torch.float32)

    def test_persistence_output_is_last_observed_raw_state(self) -> None:
        index = self.namespace["sequence_indices"]["validation"]
        prediction, target = self.namespace["persistence_arrays"](
            index, self.namespace["scenario_arrays"], max_samples=5
        )
        self.assertEqual(prediction.shape, (5, 5))
        self.assertEqual(target.shape, (5, 5))
        scenario_id, target_position = index.resolve(0)
        expected = self.namespace["scenario_arrays"][scenario_id].raw_targets[target_position - 1]
        np.testing.assert_array_equal(prediction[0], expected)

    def test_gru_and_lstm_forward_shapes(self) -> None:
        features = self.namespace["sample_batch"][0][:8]
        gru = self.namespace["GRUForecaster"](self.namespace["model_config"])
        lstm = self.namespace["LSTMForecaster"](self.namespace["model_config"])
        self.assertEqual(gru(features).shape, (8, 5))
        self.assertEqual(lstm(features).shape, (8, 5))

    def _assert_one_step_backward(self, model_class_name: str) -> None:
        features, targets = self.namespace["sample_batch"]
        model = self.namespace[model_class_name](self.namespace["model_config"])
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        optimizer.zero_grad(set_to_none=True)
        predictions = model(features[:16])
        loss = nn.MSELoss()(predictions, targets[:16])
        loss.backward()
        gradients = [parameter.grad for parameter in model.parameters() if parameter.grad is not None]
        self.assertTrue(gradients)
        self.assertTrue(all(torch.isfinite(gradient).all() for gradient in gradients))
        optimizer.step()

    def test_gru_one_step_backward_has_finite_gradients(self) -> None:
        self._assert_one_step_backward("GRUForecaster")

    def test_lstm_one_step_backward_has_finite_gradients(self) -> None:
        self._assert_one_step_backward("LSTMForecaster")

    def test_checkpoint_save_load_and_prediction_equivalence(self) -> None:
        for model_name, filename in (("GRU", "best_gru.pt"), ("LSTM", "best_lstm.pt")):
            checkpoint_path = self.model_artifact_dir / "checkpoints" / filename
            self.assertTrue(checkpoint_path.is_file())
            self.assertEqual(self.namespace["checkpoint_reload_audit"][model_name]["status"], "PASS")
            self.assertEqual(
                self.namespace["checkpoint_reload_audit"][model_name]["prediction_shape"][1],
                5,
            )

    def test_inverse_transform_and_metric_functions_are_finite(self) -> None:
        comparison = self.namespace["model_comparison"]
        numeric = comparison.select_dtypes(include=[np.number]).to_numpy()
        self.assertTrue(np.isfinite(numeric).all())
        scaled = self.namespace["sample_batch"][1].numpy()
        physical = self.namespace["target_scaler"].inverse_transform(scaled)
        self.assertTrue(np.isfinite(physical).all())

    def test_model_selection_uses_validation_not_tests(self) -> None:
        record = self.namespace["model_selection_record"]
        self.assertEqual(record["criterion"], "minimum validation standardized MSE")
        self.assertFalse(record["test_metrics_used_for_selection"])
        self.assertEqual(set(record["validation_losses"]), {"GRU", "LSTM"})

    def test_artifact_structure_and_smoke_isolation(self) -> None:
        required = [
            "checkpoints/best_gru.pt",
            "checkpoints/best_lstm.pt",
            "histories/gru_training_history.json",
            "histories/lstm_training_history.json",
            "metrics/model_comparison.csv",
            "plots/gru_loss_curve.png",
            "plots/lstm_loss_curve.png",
            "training_run_manifest.json",
        ]
        self.assertTrue(all((self.model_artifact_dir / path).is_file() for path in required))
        manifest = json.loads(
            (self.model_artifact_dir / "training_run_manifest.json").read_text(encoding="utf-8")
        )
        self.assertTrue(manifest["training_smoke_test"])

    def test_local_execution_did_not_run_full_training(self) -> None:
        summary = self.namespace["experiment_summary"]
        self.assertTrue(summary["training_smoke_test"])
        self.assertFalse(summary["full_gpu_training_executed"])
        self.assertEqual(len(self.namespace["gru_result"]["history"]), 1)
        self.assertEqual(len(self.namespace["lstm_result"]["history"]), 1)


if __name__ == "__main__":
    unittest.main()
