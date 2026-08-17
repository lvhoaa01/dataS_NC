# ML Preprocessing and Windowing Report

## STATUS

`SUCCESS`

## NOTEBOOK PATH

`notebooks/01_ml_preprocessing_and_windowing.ipynb`

- Logical sections: 22 (`00` through `21`)
- Physical notebook cells: 43
- Python code cells: 21
- Final committed default: `SMOKE_TEST = False`
- Google Colab path configuration: `DATA_ROOT` via `pathlib.Path` or environment override

## CONCEPT DOCUMENT PATH

`notebooks/01_ml_preprocessing_and_windowing_CONCEPTS.md`

- Vietnamese concept documentation: present
- Logical cell mapping `00`-`21`: exact and ordered
- Notebook/concepts synchronization check: `PASS`

## SOURCE DATASET

- Canonical membership source: `full_dataset_index.csv`
- Canonical scenarios: 24
- Rows per scenario: 70,128
- Total raw rows: 1,683,072
- Source period: `2018-01-01 00:00` through `2025-12-31 23:00`
- Membership policy: indexed `ml_file` entries only; no directory glob
- Rejected V1 artifacts: excluded by construction
- Windows/Linux indexed-path normalization: `PASS`

## FEATURE CONTRACT

Input dimension: 8

```text
air_temperature
air_humidity
soil_temperature
soil_moisture
light_lux
pump_state
fan_state
grow_light_state
```

## TARGET CONTRACT

Output dimension: 5

```text
air_temperature
air_humidity
soil_temperature
soil_moisture
light_lux
```

- Baseline lookback: 24 hourly steps
- Forecast horizon: 1 hour
- Sample shape: `X [24, 8]`, `Y [5]`
- Batch shape: `X [B, 24, 8]`, `Y [B, 5]`

## SCENARIO SPLIT

- Selection method: deterministic farthest-point coverage in normalized five-parameter space
- Development scenarios: 20
- Held-out scenarios: 4

Held-out identities:

```text
pa1_full_000_baseline
pa1_full_001
pa1_v2_replacement_003
pa1_v2_replacement_008
```

The held-out identities never contribute rows to scaler fitting or training windows. The complete split is
exported in `split_manifest.json` when the notebook runs.

## TEMPORAL SPLIT

- TRAIN: `2018-01-01 00:00` through `2023-12-31 23:00`
- Validation: `2024-01-01 00:00` through `2024-12-31 23:00`
- Temporal test: `2025-01-01 00:00` through `2025-12-31 23:00`
- Scenario test: held-out scenarios over development-observed time
- Combined test: held-out scenarios over 2025
- Raw-row random split: forbidden and not implemented

## SCALER POLICY

- Continuous feature scaler: `StandardScaler`
- Target scaler: separate `StandardScaler`
- Fit source: development scenarios, TRAIN period only
- Validation/test/held-out behavior: transform only
- Actuator policy: binary 0/1 passthrough
- Target inverse transform: validated against raw physical target

## SLIDING WINDOW

- Strategy: compact index storing scenario code and target position
- Window materialization: lazy in `GreenhouseSequenceDataset.__getitem__`
- Giant `N x 24 x 8` array: not created
- Scenario boundary check: `PASS`
- Temporal target alignment: `PASS`
- Future leakage check: `PASS`
- Split-boundary historical context: `PASS` for validation and temporal-test boundaries

## LOCAL SMOKE TEST

- Execution mode: local CPU, no model training
- Canonical scenarios loaded and fully source-validated: 2
- Development smoke scenario: `pa1_full_002`
- Held-out smoke scenario: `pa1_full_000_baseline`
- TRAIN scored range: `2018-01-01` through `2018-01-14`
- Validation scored range: `2024-01-01` through `2024-01-07`
- Temporal-test scored range: `2025-01-01` through `2025-01-07`
- Lookback context before validation/test boundaries: retained
- Train windows: 312
- Validation windows: 168
- Temporal-test windows: 168
- Scenario-test windows: 480
- Combined-test windows: 168
- Train feature-scaler rows: 336
- Train target-scaler rows: 312
- Smoke `X` batch shape: `[256, 24, 8]`
- Smoke `Y` batch shape: `[256, 5]`
- Dataset construction: `PASS`
- DataLoader fetch across all five subsets: `PASS`
- Tensor dtype `float32`: `PASS`
- Finite values: `PASS`
- Binary actuator passthrough: `PASS`
- Target inverse transform: `PASS`
- Scenario boundary check: `PASS`
- Temporal leakage check: `PASS`

Smoke artifacts were written under `outputs/ml_notebook_smoke/` for local validation only. Full Colab execution
exports to `artifacts/preprocessing/` by default:

```text
feature_scaler.pkl
target_scaler.pkl
split_manifest.json
preprocessing_config.json
```

## NOTEBOOK VALIDATION

- Notebook JSON valid with `nbformat`: `YES`
- Notebook schema validation: `PASS`
- All Python code cells compile: `PASS`
- Imports resolve in local venv: `PASS`
- Concepts/notebook section synchronization: `PASS`
- Focused notebook tests: `15/15 PASS`
- Complete project regression suite: `92/92 PASS`

Validation command:

```powershell
.\.venv\Scripts\python.exe validate_ml_notebook.py --execute-smoke
```

## MILESTONE BOUNDARY

- Persistence model trained: `NO`
- GRU trained: `NO`
- LSTM trained: `NO`
- Transformer trained: `NO`
- Model checkpoint created: `NO`
- Full training executed: `NO`
- DataLoader ready: `YES`
- Colab ready: `YES`

The next milestone may define a persistence baseline, GRU and LSTM using the exported split/scaler artifacts.
This milestone intentionally stops before any model training.
