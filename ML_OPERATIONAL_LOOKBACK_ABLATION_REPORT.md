# ML Operational Lookback Ablation Report

## Status

`SUCCESS` cho implementation và local CPU smoke validation.

```text
FULL_LOOKBACK_ABLATION_EXECUTED = NO
FINAL_TESTS_EXECUTED = NO
COLAB_READY = YES
```

Local smoke chỉ xác nhận integration và invariants. Smoke loss, accuracy winner
và practical winner không được công bố như scientific results.

## Implementation

- Notebook: `notebooks/04_operational_lookback_ablation.ipynb`
- Concepts: `notebooks/04_operational_lookback_ablation_CONCEPTS.md`
- Validator: `validate_operational_lookback_notebook.py`
- Logical sections: 32 (`00` đến `31`)
- Physical cells: 62
- Python code cells: 30
- Notebook JSON/schema: `PASS`
- Tất cả code cells compile: `PASS`
- Concepts/notebook synchronization: `PASS`

Notebook 04 là controlled model-development experiment. Nó chỉ thay đổi lookback
length và không train lại GRU, không thêm calendar/weather/future-control features,
không tăng hidden size/layers, và không mở final tests.

## Operational Task

```text
X[t-L+1:t]
    -> [S(t+1), S(t+3)]

L in {24, 48, 72}
```

- Operational horizons: `(1,3)` giờ
- Features/timestep: 8
- Targets/horizon: 5
- Strategy: direct multi-horizon
- Input sizes: `[B,24,8]`, `[B,48,8]`, `[B,72,8]`
- Target/output size: `[B,2,5]`
- Future sensor input: `NO`
- Future actuator input: `NO`
- Future weather input: `NO`
- Calendar/time features: `NO`

Deployment features giữ nguyên:

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

## Locked Data

- Canonical membership: `full_dataset_index.csv` only
- Canonical scenarios: 24
- Development scenarios: 20
- Held-out scenarios: 4, provenance only
- Held-out paths resolved: `NO`
- Held-out CSV loaded: `NO`
- Train: `2018-01-01 00:00` đến `2023-12-31 23:00`
- Validation: `2024-01-01 00:00` đến `2024-12-31 23:00`
- Final-test partitions loaded: `NO`

## Common Target Windows

Một `CommonSequenceIndex` duy nhất được tạo bằng:

```text
MAX_LOOKBACK = 72
MAX_FORECAST_HORIZON = 3
```

Với cùng `(scenario_id,t)`:

```text
24h: X[t-23:t]
48h: X[t-47:t]
72h: X[t-71:t]

all: Y = [S(t+1), S(t+3)]
```

- Common train windows/scenario: 52,510
- Common train windows total: 1,050,200
- Common validation windows/scenario: 8,782
- Common validation windows total: 175,640
- Same scenario codes: `PASS`
- Same input-end positions: `PASS`
- Same target positions/tensors: `PASS`, exact equality
- Cross-scenario windows: `0`
- Giant `N x 72 x 8` tensor: `NO`

Validation boundary cho phép input kết thúc tại `2023-12-31 23:00`, với targets
`2024-01-01 00:00` và `2024-01-01 02:00`. Đây là historical context hợp lệ;
không target nào nằm ngoài validation 2024.

## Scalers

Notebook load-only bốn artifacts từ Notebook 01:

```text
feature_scaler.pkl
target_scaler.pkl
split_manifest.json
preprocessing_config.json
```

- Feature scaler refit/partial-fit: `NO`
- Target scaler refit/partial-fit: `NO`
- Separate scaler per lookback: `NO`
- Same scaler/data arrays for all lookbacks: `YES`
- Binary actuator passthrough: `PASS`
- Full mode rejects smoke-fitted preprocessing artifacts

Full preprocessing artifacts không có trong local workspace. Validator dùng fresh
Notebook 01 smoke artifacts để chứng minh load-only contract. Full Colab run phải
mount hoặc tạo full preprocessing artifacts; Notebook 04 sẽ fail-fast nếu thiếu.

## Fairness Controls

- Experiment axis: lookback length only
- Same targets and scenarios: `YES`
- Same feature/target order: `YES`
- Same scaler: `YES`
- Same LSTM architecture: `YES`
- Same parameter count: `YES`
- Same seed/reset policy: `YES`
- Same optimizer/loss/batch size: `YES`
- Initialization state hash identical: `PASS`
- Architecture comparison: `NO`

## Model

```text
OperationalMultiHorizonLSTM
input_size = 8
hidden_size = 64
num_layers = 1
Linear(64, 10)
reshape -> [B,2,5]
```

- Parameter count: 19,594 for every lookback
- LSTM fixed from Notebook 03 validation selection
- GRU retraining: `NO`
- CNN/Attention/Transformer: `NO`
- Forward shape for 24/48/72: `PASS`
- Backward/finite gradients/optimizer for 24/48/72: `PASS`

Lookback only changes sequence dimension. `input_size` remains 8.

## Training Protocol

- Loss: equal-weight standardized MSE over batch/horizon/target
- Optimizer: AdamW
- Learning rate: `1e-3`
- Weight decay: `1e-4`
- Batch size: 256
- Maximum epochs: 50
- Early stopping: aggregate validation standardized MSE
- Patience: 7
- Gradient clipping: norm 1.0
- Seed: 20260816, reset before each run
- Full mode: CUDA required

## Baselines

### LastValuePersistence

Prediction cho cả `+1h` và `+3h` là `S_t`.

- Common validation computation: once
- Future information: `NO`
- Smoke validation: `PASS`

### DailySeasonalPersistence

Prediction tại horizon `h` là `S(t+h-24)`, luôn không muộn hơn `t` với `h=1,3`.

- Common validation computation: once
- Past-only proof: `PASS`
- Smoke validation: `PASS`

## Metrics and Practicality

Notebook implement cho từng lookback và từng horizon:

- Standardized MSE
- Physical-unit MAE/RMSE/R2 cho từng target
- Aggregate validation MSE
- Relative MSE improvement: 48-vs-24, 72-vs-24, 72-vs-48
- Per-target lookback comparison

Efficiency fields:

- Best epoch và best validation MSE
- Total training duration
- Mean epoch duration
- Validation inference duration
- Mean training samples/second
- Parameter count
- Input elements/sample
- Approximate input bytes/batch

Structural input cost:

| Lookback | Elements/sample | Approx. float32 input/batch |
|---:|---:|---:|
| 24h | 192 | 196,608 bytes |
| 48h | 384 | 393,216 bytes |
| 72h | 576 | 589,824 bytes |

Parameter count không đổi; input tensor cost tăng tuyến tính 1x/2x/3x. Notebook
xuất `BEST_ACCURACY_LOOKBACK` theo minimum full validation MSE và một practical
trade-off table riêng, không dùng arbitrary threshold để ép practical winner.

## Plots

Full execution tạo:

```text
loss_24h.png
loss_48h.png
loss_72h.png
validation_mse_vs_lookback.png
mae_1h_vs_lookback.png
mae_3h_vs_lookback.png
accuracy_runtime_tradeoff.png
```

## Artifact Contract

```text
artifacts/operational_lookback_ablation/
├── checkpoints/
│   ├── best_lstm_lookback24.pt
│   ├── best_lstm_lookback48.pt
│   └── best_lstm_lookback72.pt
├── histories/
│   ├── lookback24_history.json
│   ├── lookback48_history.json
│   └── lookback72_history.json
├── metrics/
│   ├── lookback_summary.csv
│   ├── lookback_validation_by_horizon.csv
│   ├── lookback_target_comparison.csv
│   ├── persistence_baselines.json
│   ├── practical_tradeoff.csv
│   └── practical_analysis.json
├── plots/
└── lookback_ablation_manifest.json
```

Mỗi checkpoint khóa model config, lookback, horizons `[1,3]`, feature/target order,
seed, best validation loss, direct strategy và past-only policy. Fresh-instance
reload/prediction equivalence PASS cho cả 24/48/72.

## Local Smoke

- Device: CPU
- Active scenario: `pa1_full_002`
- Common train windows: 262
- Common validation windows: 166
- Epochs/lookback: 1
- Maximum train batches: 3
- Maximum validation batches: 2
- `X24 [256,24,8]`: `PASS`
- `X48 [256,48,8]`: `PASS`
- `X72 [256,72,8]`: `PASS`
- `Y [256,2,5]`: `PASS`
- Exact same target references: `PASS`
- Finite forward/loss/backward/gradients: `PASS`
- Physical metrics functions: `PASS`
- Runtime/efficiency summary: `PASS`
- Seven required plots: `PASS`
- Checkpoint save/load all three: `PASS`

Smoke loss, smoke best-accuracy lookback và smoke runtime comparison không được
report như scientific results. Chúng chỉ phản ánh bounded integration execution.

## Final-Test Embargo

- Held-out CSV loaded: `NO`
- Temporal test loader: `NO`
- Scenario test loader: `NO`
- Combined test loader: `NO`
- Final-test predictions/metrics/plots: `NO`
- Final tests used for selection: `NO`

## Validation

- Focused operational-lookback tests: `52/52 PASS`
- Previous tests preserved: `159/159 PASS`
- Complete suite: `211/211 PASS`
- Notebook JSON: `PASS`
- All code cells compile: `PASS`
- Concepts synchronization: `PASS`
- Static leakage/protocol audit: `PASS`
- Full local ablation: `NO`

Commands:

```powershell
.\.venv\Scripts\python.exe validate_operational_lookback_notebook.py --execute-smoke
.\.venv\Scripts\python.exe -m unittest tests.test_operational_lookback_notebook -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Colab Readiness

```text
FULL_LOOKBACK_ABLATION_EXECUTED = NO
FINAL_TESTS_EXECUTED = NO
COLAB_READY = YES
```

Notebook 04 có thể chạy full trên Colab GPU sau khi full preprocessing artifacts
được mount. Calendar features, future-control plans và architecture escalation vẫn
nằm ngoài milestone này.
