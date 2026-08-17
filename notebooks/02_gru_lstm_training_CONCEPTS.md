# GRU/LSTM Training — Notebook Concepts

## Mục tiêu tài liệu

Tài liệu này giải thích logic khoa học của từng logical cell trong `02_gru_lstm_training.ipynb`.
Notebook chứa implementation; tài liệu này tập trung vào WHY/WHAT và không sao chép source code dài.

## Pipeline tổng thể

```text
24 canonical scenarios
        |
        v
Load locked split + train-fitted scalers
        |
        v
20 development ---------------------- 4 held-out
        |                                  |
        v                                  |
2018-2023 TRAIN                            |
2024 VALIDATION                            |
2025 TEMPORAL TEST                         |
        |                                  |
        v                                  |
Sliding-window references                  |
        |                                  |
        v                                  |
DataLoader                                 |
        |                                  |
        +-------- Persistence              |
        +-------- GRU                      |
        +-------- LSTM                     |
                 |                         |
                 v                         |
        validation-based selection         |
                 |                         |
                 v                         v
              Test A        Test B / Test C
                 |
                 v
        physical-unit metrics
                 |
                 v
          best checkpoints
```

Một model chung học windows của 20 development scenarios để học dynamics tổng quát qua parameter sets. Không
train 24 model riêng, vì cách đó chủ yếu ghi nhớ từng greenhouse. Bốn held-out scenarios không tham gia training,
nhờ vậy scenario generalization có ý nghĩa.

## Cell 00 — Experiment Overview

**Loại cell:** Markdown

### Mục đích
Khóa thứ tự Persistence → GRU → LSTM và validation-before-test.

### Concept
Validation 2024 chọn checkpoint/model; Test A/B/C chỉ đo generalization sau khi lựa chọn đã đóng băng.

### Input
Locked preprocessing artifacts và canonical corpus.

### Output
Ranh giới experiment, chưa gồm CNN/Attention/Transformer.

### Tại sao cần bước này?
Xem test trong lúc thiết kế sẽ biến test thành validation trá hình.

### Liên hệ với cell tiếp theo
Cell 01 tập trung hyperparameters và smoke limits.

## Cell 01 — Environment & Training Configuration

**Loại cell:** Markdown + Code

### Mục đích
Đặt seed, batch, epochs, optimizer, early stopping, gradient clipping và paths tại một nơi.

### Concept
Smoke chỉ giảm epoch/số batch, không đổi architecture hay contract. Default lưu là `TRAINING_SMOKE_TEST=False`.

### Input
Scientific defaults và environment variables portable.

### Output
Một configuration duy nhất.

### Tại sao cần bước này?
Giá trị rải rác làm experiment khó tái lập và dễ dùng nhầm smoke settings.

### Liên hệ với cell tiếp theo
Cell 02 import dependencies.

## Cell 02 — Imports

**Loại cell:** Markdown + Code

### Mục đích
Import pandas, NumPy, PyTorch, joblib và matplotlib.

### Concept
Notebook dùng package phổ biến trên Colab, không force reinstall CUDA và không phụ thuộc package nội bộ.

### Input
Python runtime.

### Output
Data/model/training/serialization APIs.

### Tại sao cần bước này?
Dependency footprint nhỏ tăng portability.

### Liên hệ với cell tiếp theo
Cell 03 khóa random state.

## Cell 03 — Reproducibility Setup

**Loại cell:** Markdown + Code

### Mục đích
Seed Python, NumPy, PyTorch và DataLoader bằng `20260816`.

### Concept
Seed giữ initialization và shuffle windows lặp lại được. CUDA deterministic mode đắt đỏ không bị ép bật.

### Input
Seed.

### Output
Deterministic random generators.

### Tại sao cần bước này?
Không seed thì khác biệt model có thể đến từ sampling không kiểm soát.

### Liên hệ với cell tiếp theo
Cell 04 chọn CPU/GPU.

## Cell 04 — Device / Colab Runtime Detection

**Loại cell:** Markdown + Code

### Mục đích
In runtime/CUDA và chọn `cuda` nếu có.

### Concept
CPU load/scale arrays; model và batch mới chuyển sang GPU trong loop. `pin_memory` bật có điều kiện.

### Input
PyTorch runtime.

### Output
`DEVICE` và environment provenance.

### Tại sao cần bước này?
Hard-code CUDA làm local smoke fail; hard-code CPU lãng phí Colab GPU.

### Liên hệ với cell tiếp theo
Cell 05 xử lý paths đa nền tảng.

## Cell 05 — Dataset and Artifact Path Configuration

**Loại cell:** Markdown + Code

### Mục đích
Normalize Windows/Linux paths từ canonical index.

### Concept
Resolver không glob; fallback chỉ dùng vị trí explicit và phát warning để tránh đọc artifact V1.

### Input
Raw indexed path và `DATA_ROOT`.

### Output
Resolved file path duy nhất.

### Tại sao cần bước này?
Dấu `\` Windows không phải separator trên Colab Linux.

### Liên hệ với cell tiếp theo
Cell 06 load locked artifacts.

## Cell 06 — Load Preprocessing Artifacts

**Loại cell:** Markdown + Code

### Mục đích
Load feature scaler, target scaler, split manifest và preprocessing config.

### Concept
Training không fit/partial-fit scaler. Full mode từ chối smoke-fitted artifact. Binary actuator tiếp tục 0/1.

### Input
`artifacts/preprocessing/*` hoặc explicit smoke directory.

### Output
Train-fitted transformations và locked split/config.

### Tại sao cần bước này?
Refit bằng validation/test gây data leakage.

### Liên hệ với cell tiếp theo
Cell 07 kiểm tra artifact contract.

## Cell 07 — Validate Training Contract

**Loại cell:** Markdown + Code

### Mục đích
Assert 8 features, 5 targets, lookback 24, horizon 1, 20/4 IDs và date ranges.

### Concept
Held-out IDs được load nguyên từ split manifest, không được chọn lại. Feature order sai vẫn có đúng shape nhưng sai nghĩa.

### Input
Preprocessing config và split manifest.

### Output
Locked training/evaluation contract.

### Tại sao cần bước này?
Notebook 02 phải tái dựng đúng experiment notebook 01.

### Liên hệ với cell tiếp theo
Cell 08 load canonical membership.

## Cell 08 — Load Canonical Dataset Index

**Loại cell:** Markdown + Code

### Mục đích
Load đúng 24 scenarios từ `full_dataset_index.csv`.

### Concept
`pa1_full_*` và `pa1_v2_replacement_*` được đối xử như nhau nếu có trong index. Metadata không phải feature.

### Input
Canonical index và locked IDs.

### Output
24 unique scenarios, tổng 1.683.072 rows.

### Tại sao cần bước này?
Glob có thể đưa rejected output vào corpus.

### Liên hệ với cell tiếp theo
Cell 09 resolve indexed files.

## Cell 09 — Resolve Canonical Scenario Files

**Loại cell:** Markdown + Code

### Mục đích
Tạo mapping identity → file một-một.

### Concept
Mỗi file là trajectory 2018–2025 độc lập; hai IDs dùng cùng file là lỗi provenance.

### Input
Index và path resolver.

### Output
24 resolved paths.

### Tại sao cần bước này?
Duplicate file làm lệch trọng số scenario.

### Liên hệ với cell tiếp theo
Cell 10 tạo optimized arrays.

## Cell 10 — Reconstruct Scenario Frames / Efficient Arrays

**Loại cell:** Markdown + Code

### Mục đích
Validate CSV, transform mỗi timestep một lần và cache contiguous `float32` arrays.

### Concept
Mỗi scenario giữ timestamps, scaled features `[70128,8]`, scaled targets `[70128,5]` và raw targets. Đây là
CPU preprocessing; không merge trajectories và không tạo `N×24×8` windows.

### Input
Canonical CSVs và loaded scalers.

### Output
Per-scenario arrays với actuator vẫn 0/1.

### Tại sao cần bước này?
Pre-transform timestep giảm overhead nhưng không đổi scientific behavior.

### Liên hệ với cell tiếp theo
Cell 11 tạo compact references.

## Cell 11 — Reconstruct Locked Sequence Indices

**Loại cell:** Markdown + Code

### Mục đích
Tạo năm sequence indices và bảo vệ full window counts.

### Concept
Target timestamp quyết định split. Historical context trước boundary là quá khứ hợp lệ. Test A là 2025/development;
Test B là held-out/familiar time; Test C là 2025/held-out.

### Input
Arrays, locked IDs/dates, lookback và horizon.

### Output
Full counts: train 1.051.200; validation 175.680; temporal 175.200; scenario 245.376; combined 35.040.

### Tại sao cần bước này?
Count khác báo gap, sai boundary hoặc split khác notebook 01.

### Liên hệ với cell tiếp theo
Cell 12 tạo Dataset/DataLoader.

## Cell 12 — Training DataLoader Construction

**Loại cell:** Markdown + Code

### Mục đích
Tạo lazy Dataset/loaders và kiểm tra numerical equivalence.

### Concept
Dataset định nghĩa sample; DataLoader gom batch. Train shuffle windows sau split, không random split raw time.
Một batch có thể chứa nhiều scenario vì từng sample vẫn không crossing. Optimized slice được so với scaler logic gốc.

### Input
Arrays, indices và batch/device settings.

### Output
`X [B,24,8]`, `Y [B,5]` loaders.

### Tại sao cần bước này?
Equivalence chứng minh optimization không đổi input/target.

### Liên hệ với cell tiếp theo
Cell 13 định nghĩa reference.

## Cell 13 — Persistence Baseline

**Loại cell:** Markdown + Code

### Mục đích
Dự báo next state bằng sensor state cuối input.

### Concept
Persistence là `ŷ(t+1)=y(t)`, không có trainable parameter. Prediction lấy từ raw physical sensor, không nhầm
feature-scaled values với target scaling.

### Input
Sequence index và raw targets.

### Output
Prediction/target `[N,5]` trong physical units.

### Tại sao cần bước này?
Deep model không vượt persistence thì lợi ích forecasting cần được xem xét.

### Liên hệ với cell tiếp theo
Cell 14 định nghĩa recurrent models.

## Cell 14 — Model Architecture Definitions

**Loại cell:** Markdown + Code

### Mục đích
Định nghĩa `GRUForecaster` và `LSTMForecaster` tương đương.

### Concept
Input `[B,24,8]` đi qua recurrent layer; hidden state cuối `[B,64]` tóm tắt lịch sử, Linear map sang `[B,5]`.
LSTM còn có cell state. Một recurrent layer không giả vờ dùng dropout.

### Input
8 inputs, hidden 64, 1 layer.

### Output
Standardized prediction `[B,5]`.

### Tại sao cần bước này?
Architecture nhỏ và cùng capacity giúp comparison dễ audit.

### Liên hệ với cell tiếp theo
Cell 15 định nghĩa protocol chung.

## Cell 15 — Training Utilities

**Loại cell:** Markdown + Code

### Mục đích
Implement generic train/evaluate/fit/checkpoint helpers.

### Concept
MSE tính trong standardized target space. AdamW update; gradient clipping giảm exploding gradients. NaN/Inf fail-fast.
Early stopping chỉ monitor validation. Best checkpoint là epoch validation tốt nhất, không phải last epoch.

### Input
Model, train/validation loaders và config.

### Output
History, best loss/epoch và atomic `.pt`.

### Tại sao cần bước này?
Hai loop copy-paste dễ tạo protocol GRU/LSTM khác nhau.

### Liên hệ với cell tiếp theo
Cell 16 train GRU.

## Cell 16 — GRU Training

**Loại cell:** Markdown + Code

### Mục đích
Train GRU trên TRAIN only.

### Concept
Batch flow: device → forward → MSE → backward → finite gradient → clip → AdamW. Smoke chỉ một epoch/ba batch.

### Input
GRU và train/validation loaders.

### Output
Best GRU checkpoint/history.

### Tại sao cần bước này?
Smoke chứng minh training path trước Colab GPU, không đánh giá accuracy.

### Liên hệ với cell tiếp theo
Cell 17 validate frozen GRU.

## Cell 17 — GRU Validation

**Loại cell:** Markdown + Code

### Mục đích
Đánh giá best GRU trên validation.

### Concept
Validation được phép chọn epoch/model; Test A/B/C chưa được mở.

### Input
Frozen GRU và validation loader.

### Output
Finite standardized MSE.

### Tại sao cần bước này?
Last epoch không nhất thiết là best epoch.

### Liên hệ với cell tiếp theo
Cell 18 train LSTM.

## Cell 18 — LSTM Training

**Loại cell:** Markdown + Code

### Mục đích
Train LSTM bằng cùng protocol.

### Concept
Seed/DataLoader generator được reset để comparison với GRU công bằng tối đa.

### Input
LSTM và locked loaders.

### Output
Best LSTM checkpoint/history.

### Tại sao cần bước này?
So sánh architecture chỉ có ý nghĩa khi data/loss/optimizer giống nhau.

### Liên hệ với cell tiếp theo
Cell 19 validate LSTM.

## Cell 19 — LSTM Validation

**Loại cell:** Markdown + Code

### Mục đích
Đánh giá best LSTM trên cùng validation protocol.

### Concept
Không test metric nào tham gia bước này.

### Input
Frozen LSTM và validation loader.

### Output
Finite standardized MSE.

### Tại sao cần bước này?
Nó đặt hai models trên cùng thước đo trước selection.

### Liên hệ với cell tiếp theo
Cell 20 freeze preferred model.

## Cell 20 — Validation-based Model Comparison

**Loại cell:** Markdown + Code

### Mục đích
Chọn GRU/LSTM bằng minimum validation standardized MSE.

### Concept
Validation quyết định; test chỉ báo cáo. Không đổi architecture/epoch sau khi xem test.

### Input
Hai best validation losses.

### Output
Frozen preferred-model record.

### Tại sao cần bước này?
Tune bằng test làm estimate lạc quan và test không còn locked.

### Liên hệ với cell tiếp theo
Cell 21 mới mở final tests.

## Cell 21 — Locked Final Evaluation

**Loại cell:** Markdown + Code

### Mục đích
Evaluate Persistence, GRU, LSTM trên validation/Test A/B/C.

### Concept
Temporal generalization là 2025/known scenarios; scenario generalization là unseen configs/familiar time; combined
là unseen config + 2025. Predictions được inverse-transform. Metrics không quay lại model selection.

### Input
Frozen models, locked loaders và target scaler.

### Output
Per-model/per-split metrics và deterministic validation predictions.

### Tại sao cần bước này?
Ba tests trả lời ba câu hỏi khoa học khác nhau.

### Liên hệ với cell tiếp theo
Cell 22 trình bày physical metrics.

## Cell 22 — Physical-unit Metrics

**Loại cell:** Markdown + Code

### Mục đích
Tạo standardized MSE và MAE/RMSE/R² riêng từng target.

### Concept
Loss standardized phù hợp optimization, nhưng interpretation cần °C, %RH, VWC, lux. Không average MAE khác đơn vị;
không dùng MAPE chính vì lux có thể bằng 0. Prediction không bị clip.

### Input
Scaled và inverse-transformed arrays.

### Output
Finite comparison table.

### Tại sao cần bước này?
Một aggregate loss không cho biết sai số vật lý từng sensor.

### Liên hệ với cell tiếp theo
Cell 23 tạo diagnostics.

## Cell 23 — Training Curves / Prediction Diagnostics

**Loại cell:** Markdown + Code

### Mục đích
Lưu loss curves và actual-vs-predicted plot.

### Concept
Representative window là 72 validation windows đầu tiên deterministic, không cherry-pick theo performance.

### Input
Histories và preferred-model validation predictions.

### Output
Ba PNG plots trong physical/standardized units phù hợp.

### Tại sao cần bước này?
Curves cho thấy optimization; temporal plot cho thấy behavior metric tổng hợp che mất.

### Liên hệ với cell tiếp theo
Cell 24 lưu experiment artifacts.

## Cell 24 — Save Model Artifacts

**Loại cell:** Markdown + Code

### Mục đích
Lưu histories, metrics, configs, comparison và run manifest.

### Concept
Best checkpoint là weights từ best validation epoch và là inference artifact. Last checkpoint thường dùng resume,
có optimizer state nhưng baseline này không tạo để giữ implementation gọn. Smoke artifacts ở directory riêng.

### Input
Models, histories, metrics và provenance.

### Output
Auditable `artifacts/model_training/` tree trong full Colab run.

### Tại sao cần bước này?
Chỉ có `.pt` không đủ tái hiện split/scaler/config.

### Liên hệ với cell tiếp theo
Cell 25 verify reload.

## Cell 25 — Reload Checkpoint Verification

**Loại cell:** Markdown + Code

### Mục đích
Load checkpoint vào model mới và so prediction cùng validation batch.

### Concept
Checkpoint reload verification bảo vệ architecture identity, weights và serialization. Prediction phải allclose.

### Input
Best GRU/LSTM checkpoints và deterministic batch.

### Output
Hai PASS records, prediction `[B,5]`.

### Tại sao cần bước này?
Save thành công không bảo đảm load đúng hoặc inference tái lập.

### Liên hệ với cell tiếp theo
Cell 26 tổng hợp gate cuối.

## Cell 26 — Final Experiment Summary

**Loại cell:** Markdown + Code

### Mục đích
Xuất structured status machine-readable.

### Concept
Summary phân biệt smoke/full, xác nhận no scaler refit, lazy windows, backward và reload. Smoke metrics chỉ kiểm tra
code path, không được báo như accuracy khoa học.

### Input
Các audit records.

### Output
`experiment_summary`.

### Tại sao cần bước này?
Notebook compile được chưa đủ để gọi là Colab-ready.

### Liên hệ với cell tiếp theo
Đây là cell cuối; chưa bắt đầu Transformer/CNN/Attention.

# Tổng kết

Notebook dùng một model chung cho 20 development trajectories và giữ kín 4 held-out scenarios. Scaler không được
fit lại. Persistence đặt reference; GRU/LSTM dùng cùng protocol. Validation 2024 chọn best epoch/model, sau đó Test
A/B/C mới được đánh giá. Local smoke chỉ chứng minh data → forward → backward → checkpoint → reload, không phải
kết quả accuracy và không phải full training.
