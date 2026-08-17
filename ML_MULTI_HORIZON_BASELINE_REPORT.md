# ML Direct Multi-Horizon GRU/LSTM Baseline Report

## Status

`SUCCESS` cho implementation và local CPU smoke validation.

```text
FULL_MULTI_HORIZON_TRAINING_EXECUTED = NO
MULTI_HORIZON_FINAL_TESTS_EXECUTED = NO
COLAB_READY = YES
```

Smoke execution chỉ kiểm tra pipeline. Các loss/metric smoke không phải kết quả
khoa học và không được dùng để chọn architecture cho full experiment.

## Implementation Status

- Notebook: `notebooks/03_multi_horizon_gru_lstm.ipynb`
- Concepts: `notebooks/03_multi_horizon_gru_lstm_CONCEPTS.md`
- Validator: `validate_multi_horizon_notebook.py`
- Logical sections: 31 (`00` đến `30`)
- Physical cells: 61
- Python code cells: 30
- Notebook JSON/schema: `PASS`
- Tất cả code cells compile: `PASS`
- Concepts/notebook synchronization: `PASS`

## Direct Forecast Contract

```text
X[t-23:t]
    -> [S(t+1), S(t+3), S(t+6), S(t+12), S(t+24)]
```

- Lookback: 24 giờ
- Horizons theo thứ tự khóa: `(1, 3, 6, 12, 24)` giờ
- Input tensor: `[B, 24, 8]`
- Target/output tensor: `[B, 5, 5]`
- Strategy: direct multi-horizon, không autoregressive rollout
- Future actuator/weather/sensor input: `NO`
- Future actuator trace: chỉ dùng post-prediction diagnostic
- Prediction clipping: `NO`

Tám deployment features vẫn là:

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

Năm target là năm sensor variables; actuator không nằm trong target.

## Locked Development Data

Notebook load split identities từ `split_manifest.json`; không reselect scenario.
Canonical membership chỉ đến từ `full_dataset_index.csv`.

- Development scenarios: 20
- Held-out scenarios: 4, provenance audit only
- Held-out CSV resolved/loaded: `NO`
- TRAIN: `2018-01-01 00:00` đến `2023-12-31 23:00`
- Validation: `2024-01-01 00:00` đến `2024-12-31 23:00`
- Full train windows/scenario: 52,537
- Full validation windows/scenario: 8,761
- Full train windows: 1,050,740
- Full validation windows: 175,220
- Cross-scenario windows: `0`
- Giant materialized `[N,24,8]` tensor: `NO`

## Preprocessing Artifacts

Notebook load-only:

```text
artifacts/preprocessing/feature_scaler.pkl
artifacts/preprocessing/target_scaler.pkl
artifacts/preprocessing/split_manifest.json
artifacts/preprocessing/preprocessing_config.json
```

- Feature scaler refit/partial-fit: `NO`
- Target scaler refit/partial-fit: `NO`
- Binary actuator policy: 0/1 passthrough
- Full mode từ chối preprocessing artifact mang cờ smoke
- Optimized array vs direct scaler transform: `PASS`

Full preprocessing artifact directory không có trong local workspace. Local
validation dùng artifact từ notebook 01 smoke path để kiểm tra load-only contract.
Khi chạy Colab full, full preprocessing artifacts phải được mount hoặc tạo bởi
Notebook 01 full; notebook sẽ fail-fast nếu chúng thiếu hoặc là smoke artifacts.

## Final-Test Embargo

Notebook 03 chỉ tạo:

```text
train_loader
validation_loader
```

- Temporal test loader constructed: `NO`
- Held-out scenario test loader constructed: `NO`
- Combined test loader constructed: `NO`
- Final-test CSV loaded: `NO`
- Final-test metric/plot produced: `NO`
- Final tests used for model selection: `NO`

Multi-horizon final tests thuộc milestone riêng sau khi architecture/checkpoint đã
được đóng băng.

## Baselines

### LastValuePersistence

Mọi horizon dùng trạng thái sensor cuối input `S_t`.

- Parameters: 0
- Output shape: `[N,5,5] PASS`
- Future information: `NO`
- Smoke validation: `PASS`

### DailySeasonalPersistence

Horizon `h` dùng quan sát `S_(t+h-24)`. Tất cả source positions không muộn hơn
`t`; tại `h=24`, prediction bằng đúng `S_t`.

- Output shape: `[N,5,5] PASS`
- Past-only index proof: `PASS`
- `h=24 == LastValue`: `PASS`
- Smoke validation: `PASS`

## GRU

```text
input_size = 8
hidden_size = 64
num_layers = 1
batch_first = True
Linear(64, 25)
reshape -> [B,5,5]
```

- Train from scratch: `YES`
- One-step checkpoint initialization: `NO`
- Smoke forward: `PASS`
- Smoke backward/finite gradients/optimizer: `PASS`
- Best checkpoint atomic save: `PASS`
- Fresh-instance reload equivalence: `PASS`

## LSTM

LSTM giữ cùng dimensions, direct head và protocol với GRU.

- Train from scratch: `YES`
- One-step checkpoint initialization: `NO`
- Smoke forward: `PASS`
- Smoke backward/finite gradients/optimizer: `PASS`
- Best checkpoint atomic save: `PASS`
- Fresh-instance reload equivalence: `PASS`

## Training Protocol

- Loss: equal-weight MSE trên standardized tensor `[horizon,target]`
- Optimizer: AdamW
- Learning rate: `1e-3`
- Weight decay: `1e-4`
- Maximum epochs: 50
- Early stopping: aggregate validation standardized MSE, patience 7
- Gradient clipping: norm 1.0
- Model selection: minimum aggregate validation standardized MSE
- Final-test feedback: `NO`
- Full mode device gate: CUDA required

## Validation Diagnostics

Đã implement chỉ trên validation partition:

- Standardized MSE theo horizon và aggregate
- Physical-unit MAE/RMSE/R² theo horizon và target
- MAE/RMSE degradation ratio so với h=1
- Skill so với LastValuePersistence
- Skill so với DailySeasonalPersistence
- Future actuator-change error audit cho `t+1..t+h`, post-prediction only
- Finite checks cho predictions, loss, gradients và diagnostics

Không lấy trung bình MAE giữa các đại lượng khác đơn vị và không dùng MAPE làm
primary metric.

## Diagnostic Plots

Full execution xuất:

```text
gru_loss_curve.png
lstm_loss_curve.png
standardized_mse_vs_horizon.png
mae_vs_horizon_by_target.png
preferred_model_24h_validation.png
```

Plot h=24 dùng đoạn validation liên tục, không vượt biên scenario, và ghi rõ input
kết thúc trước target 24 giờ.

## Local Smoke Result

- Device: CPU
- Active development scenario: `pa1_full_002`
- Train interval: 14 ngày đầu 2018
- Validation interval: 7 ngày đầu 2024
- Train windows: 289
- Validation windows: 145
- Epochs/model: 1
- Maximum train batches/model: 3
- Maximum validation batches: 2
- Sample input: `[256,24,8]`
- Sample target: `[256,5,5]`
- LastValuePersistence: `PASS`
- DailySeasonalPersistence: `PASS`
- GRU forward/backward/checkpoint: `PASS`
- LSTM forward/backward/checkpoint: `PASS`
- Four-model horizon metrics finite: `PASS`
- Degradation/skill/control diagnostics finite: `PASS`
- Plot generation với non-GUI backend: `PASS`

Smoke metric values và preferred smoke model không được report vì chúng không có
scientific meaning.

## Full Colab Run

- Full multi-horizon training executed locally: `NO`
- Full scientific validation metrics: `PENDING`
- Preferred full-trained recurrent model: `PENDING`
- Multi-horizon final tests: `LOCKED / NOT EXECUTED`
- Colab GPU pipeline ready: `YES`

## Artifact Structure

Full execution ghi vào thư mục mới:

```text
artifacts/multi_horizon_training/
├── checkpoints/
│   ├── best_gru_multihorizon.pt
│   └── best_lstm_multihorizon.pt
├── histories/
├── metrics/
│   ├── validation_metrics.json
│   ├── validation_by_horizon.csv
│   ├── horizon_degradation.csv
│   ├── skill_scores.csv
│   └── future_control_audit.csv
├── plots/
└── multi_horizon_run_manifest.json
```

Local smoke outputs nằm dưới `outputs/multi_horizon_notebook_smoke/` và bị Git
ignore. Không model checkpoint, plot hay runtime artifact nào được commit.

## Validation

- Multi-horizon focused tests: `44/44 PASS`
- Existing tests preserved: `115/115 PASS`
- Complete project suite: `159/159 PASS`
- Notebook JSON: `PASS`
- Code compilation: `PASS`
- Concept synchronization: `PASS`
- Scaler load-only: `PASS`
- Final-test loader count: `0`
- Held-out CSV load count: `0`
- Local full training: `NO`

Validation commands:

```powershell
.\.venv\Scripts\python.exe validate_multi_horizon_notebook.py --execute-smoke
.\.venv\Scripts\python.exe -m unittest tests.test_multi_horizon_notebook -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Readiness

```text
FULL_MULTI_HORIZON_TRAINING_EXECUTED = NO
MULTI_HORIZON_FINAL_TESTS_EXECUTED = NO
COLAB_READY = YES
```

Notebook 03 có thể chạy full trên Colab GPU sau khi full preprocessing artifacts
đã được mount. Không mở final tests trong lần chạy phát triển này.
