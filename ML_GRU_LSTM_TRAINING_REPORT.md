# ML GRU/LSTM Training Notebook Report

## STATUS

`SUCCESS` for notebook implementation and local CPU smoke validation.

Full Colab GPU training has not been executed in this milestone.

## NOTEBOOK

- Path: `notebooks/02_gru_lstm_training.ipynb`
- Logical sections: 27 (`00` through `26`)
- Physical cells: 53
- Python code cells: 26
- Stored default: `TRAINING_SMOKE_TEST = False`
- JSON/schema validation: `PASS`
- All code cells compile: `PASS`

## CONCEPT DOCUMENT

- Path: `notebooks/02_gru_lstm_training_CONCEPTS.md`
- Language: Vietnamese with English technical terms
- Ordered mapping `00` through `26`: `PASS`
- Notebook/concepts synchronization: `PASS`

## SOURCE CONTRACT

- Canonical membership: `full_dataset_index.csv` only
- Canonical scenarios: 24 independent trajectories
- Rows per scenario: 70,128
- Total source rows: 1,683,072
- Features: 8
- Targets: 5
- Lookback: 24 hours
- Forecast horizon: 1 hour
- Raw directory glob used for membership: `NO`
- Scenario naming families treated differently: `NO`

## LOCKED SPLIT

The notebook loads split identities from `split_manifest.json`; it does not select held-out scenarios again.

- Development scenarios: 20
- Completely held-out scenarios: 4
- TRAIN: `2018-01-01 00:00` through `2023-12-31 23:00`
- Validation: `2024-01-01 00:00` through `2024-12-31 23:00`
- Test A, temporal: 2025 on development scenarios
- Test B, scenario: held-out scenarios over familiar time
- Test C, combined: 2025 on held-out scenarios

Locked full window counts protected by assertions:

```text
train:          1,051,200
validation:       175,680
temporal_test:    175,200
scenario_test:    245,376
combined_test:     35,040
```

Model/epoch selection uses validation only. Test A/B/C are evaluated after checkpoints are frozen and never feed
back into architecture or hyperparameter selection.

## PREPROCESSING ARTIFACTS

Full notebook mode requires:

```text
artifacts/preprocessing/feature_scaler.pkl
artifacts/preprocessing/target_scaler.pkl
artifacts/preprocessing/split_manifest.json
artifacts/preprocessing/preprocessing_config.json
```

- Feature scaler: loaded, never fit by training notebook
- Target scaler: loaded separately, never fit by training notebook
- Binary actuator policy: 0/1 passthrough
- Scaler refit/partial-fit in training notebook: `NO`
- Full mode rejects preprocessing artifacts marked `smoke_test_execution=true`

The full `artifacts/preprocessing/` directory was not present locally. Local validation therefore loaded a fresh
smoke artifact set produced by notebook 01's smoke path under a temporary/output directory. This validates the
artifact-loading contract without pretending the smoke scaler is the full train-fitted scaler. Colab full mode
will fail fast until the real full preprocessing artifacts are mounted or generated.

## TRAINING DATA PIPELINE

- Source validation: exact 9-column schema, 70,128 rows, hourly continuity, finite values, binary actuators
- Per-scenario optimized arrays: `YES`
- Scaled features: contiguous `float32 [70128, 8]`
- Scaled targets: contiguous `float32 [70128, 5]`
- Sliding windows: lazy/index-based
- Giant `N x 24 x 8` array: not created
- Scenario concatenation into one continuous time series: not performed
- Optimized-vs-direct-scaler numerical equivalence: `PASS`
- Scenario crossing: `PASS`
- Historical split-boundary context: `PASS`
- Train sampler: shuffled windows
- Validation/test samplers: sequential
- Batch shape: `[B, 24, 8]`
- Target shape: `[B, 5]`

## PERSISTENCE BASELINE

- Definition: next state equals last observed raw sensor state
- Trainable parameters: none
- Raw physical-state use: `PASS`
- Shape validation: `[N, 5] PASS`
- Physical-unit evaluation implementation: `PASS`

## GRU BASELINE

```text
input_size = 8
hidden_size = 64
num_layers = 1
output_size = 5
batch_first = True
```

- Forward shape: `[B, 5] PASS`
- One-step backward: `PASS`
- Finite predictions/loss/gradients: `PASS`
- AdamW optimizer step: `PASS`
- Gradient clipping path: `PASS`
- Best checkpoint save: `PASS`
- Fresh-instance reload prediction allclose: `PASS`

## LSTM BASELINE

The LSTM uses the same dimensions and training protocol as GRU.

- Forward shape: `[B, 5] PASS`
- One-step backward: `PASS`
- Finite predictions/loss/gradients: `PASS`
- AdamW optimizer step: `PASS`
- Gradient clipping path: `PASS`
- Best checkpoint save: `PASS`
- Fresh-instance reload prediction allclose: `PASS`

## TRAINING PROTOCOL

- Loss: MSE in standardized target space
- Optimizer: AdamW
- Learning rate: `1e-3`
- Weight decay: `1e-4`
- Maximum epochs: 50
- Early stopping: validation loss, patience 7
- Gradient clip norm: 1.0
- Preferred model criterion: minimum best validation standardized MSE
- Test metrics used for model selection: `NO`
- Recurrent dropout with one layer: not declared

## METRICS AND DIAGNOSTICS

Implemented for Persistence, GRU and LSTM on validation/Test A/Test B/Test C:

- Standardized MSE
- Per-target physical-unit MAE
- Per-target physical-unit RMSE
- Per-target physical-unit R²
- No aggregate MAE across incompatible physical units
- No MAPE primary metric
- No prediction clipping
- GRU train/validation loss curve
- LSTM train/validation loss curve
- Deterministic first-72-validation-window actual/predicted plot

## LOCAL SMOKE RESULT

- Device: CPU
- Canonical source files fully validated: 2
- Development scenario: `pa1_full_002`
- Held-out scenario: `pa1_full_000_baseline`
- Epochs per model: 1
- Maximum train batches per model: 3
- Maximum evaluation batches: 2
- Train windows in smoke: 312
- Validation windows in smoke: 168
- Temporal-test windows in smoke: 168
- Scenario-test windows in smoke: 312
- Combined-test windows in smoke: 168
- Sample `X` shape: `[256, 24, 8]`
- Sample `Y` shape: `[256, 5]`
- Persistence: `PASS`
- GRU forward/backward/optimizer: `PASS`
- LSTM forward/backward/optimizer: `PASS`
- Finite checks: `PASS`
- Physical metric function: `PASS`
- Checkpoint save/load: `PASS`
- Reload inference equivalence: `PASS`
- Plot generation with non-GUI backend: `PASS`

Smoke losses and physical metrics are intentionally not reported as scientific results. One bounded CPU epoch is
only an integration check.

## FULL COLAB TRAINING RESULT

- Full GPU training executed: `NO`
- Scientific Persistence metrics: `PENDING`
- Scientific GRU metrics: `PENDING`
- Scientific LSTM metrics: `PENDING`
- Preferred full-trained baseline: `PENDING`
- Full-trained model checkpoints: `NOT CREATED LOCALLY`

## ARTIFACT STRUCTURE

Full Colab execution writes:

```text
artifacts/model_training/
├── checkpoints/
│   ├── best_gru.pt
│   └── best_lstm.pt
├── histories/
│   ├── gru_training_history.json
│   └── lstm_training_history.json
├── metrics/
│   ├── persistence_metrics.json
│   ├── gru_metrics.json
│   ├── lstm_metrics.json
│   └── model_comparison.csv
├── plots/
│   ├── gru_loss_curve.png
│   ├── lstm_loss_curve.png
│   └── preferred_model_validation_72h.png
├── gru_model_config.json
├── lstm_model_config.json
└── training_run_manifest.json
```

Local checkpoints/plots are isolated under `outputs/ml_training_notebook_smoke/` and ignored by Git.

## VALIDATION

- Focused training-notebook tests: `23/23 PASS`
- Existing tests before this milestone: `92/92 preserved`
- Complete project suite: `115/115 PASS`
- Notebook JSON: `PASS`
- Code-cell compilation: `PASS`
- Concept synchronization: `PASS`
- Full local training: `NO`
- Colab ready: `YES`, once full preprocessing artifacts/data are mounted

Validation command:

```powershell
.\.venv\Scripts\python.exe validate_ml_training_notebook.py --execute-smoke
```
