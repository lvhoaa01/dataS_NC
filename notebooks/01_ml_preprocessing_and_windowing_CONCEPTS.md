# ML Preprocessing and Windowing — Notebook Concepts

## Mục tiêu tài liệu

Tài liệu này giải thích logic, giả định khoa học và vai trò của từng section trong
`01_ml_preprocessing_and_windowing.ipynb`. Notebook là phần implementation có thể chạy; file này tập
trung vào **WHY/WHAT**, không sao chép các function hay class dài từ notebook.

## Pipeline tổng thể

```text
24 canonical trajectories
        |
        v
Integrity Validation
        |
        v
Scenario Split
        |
        +---- Development Scenarios
        |
        +---- Held-out Scenarios
        |
        v
Temporal Split
        |
        +---- Train 2018-2023
        +---- Validation 2024
        +---- Test 2025
        |
        v
Train-only Scaling
        |
        v
Sliding-window Index
        |
        v
Lazy GreenhouseSequenceDataset
        |
        v
DataLoader
        |
        v
X_batch [B, 24, 8]
Y_batch [B, 5]
```

24 scenario là 24 trajectory vật lý độc lập, mỗi trajectory chạy liên tục từ 2018 đến 2025. Chúng
không phải 24 đoạn liên tiếp của một time series, vì vậy mọi window phải thuộc đúng một scenario.

## Cell 00 — Experiment Overview

**Loại cell:** Markdown

### Mục đích

Khóa phạm vi notebook ở preprocessing và DataLoader, đồng thời mô tả input/output của milestone.

### Concept

Một research notebook cần nói rõ câu hỏi nó giải quyết trước khi chạy code. Ở đây câu hỏi là cách biến
trajectory hourly đã validate thành supervised samples có thể audit, chưa phải cách tối ưu model.

### Input

Canonical index, 24 ML trajectory và parameter manifest V2.

### Output

Định nghĩa ranh giới công việc: pipeline sẵn sàng cho training notebook kế tiếp.

### Tại sao cần bước này?

Nếu không khóa scope, preprocessing và training dễ bị trộn, làm khó truy nguyên leakage hoặc lỗi data.

### Liên hệ với cell tiếp theo

Cell 01 tập trung toàn bộ lựa chọn có thể cấu hình cho pipeline này.

## Cell 01 — Environment & Configuration

**Loại cell:** Markdown + Code

### Mục đích

Đặt seed, lookback, forecast horizon, batch size, đường dẫn và smoke mode tại một nơi.

### Concept

Configuration tường minh là một phần của reproducibility. `LOOKBACK_STEPS` có thể đổi từ 24 sang 48,
72 hoặc 168 mà không viết lại logic window. Notebook lưu `SMOKE_TEST=False`; local validator chỉ override
bằng biến môi trường.

### Input

Giá trị mặc định và tùy chọn `GREENHOUSE_DATA_ROOT`, `GREENHOUSE_SMOKE_TEST`,
`GREENHOUSE_ARTIFACT_DIR`.

### Output

Một contract cấu hình duy nhất được các section sau sử dụng.

### Tại sao cần bước này?

Hard-code rải rác dễ tạo notebook chạy khác nhau giữa Windows và Colab.

### Liên hệ với cell tiếp theo

Cell 02 import đúng các dependency cần cho cấu hình đó.

## Cell 02 — Imports

**Loại cell:** Markdown + Code

### Mục đích

Import NumPy, pandas, scikit-learn, PyTorch, joblib và in version môi trường.

### Concept

Preprocessing không cần GPU. Version được in để một kết quả bất thường có thể gắn với environment cụ thể,
nhưng notebook không force cài lại CUDA/PyTorch trên Colab.

### Input

Python environment hiện tại.

### Output

Các API cần thiết và thông tin version có thể audit.

### Tại sao cần bước này?

Thiếu provenance môi trường làm lỗi portability khó tái hiện.

### Liên hệ với cell tiếp theo

Cell 03 seed các random generator của các thư viện vừa import.

## Cell 03 — Reproducibility Setup

**Loại cell:** Markdown + Code

### Mục đích

Đặt seed `20260816` cho Python, NumPy, PyTorch và DataLoader generator.

### Concept

Scenario holdout là deterministic; seed chủ yếu bảo đảm thứ tự shuffle training windows có thể lặp lại.
Chưa training GPU nên chưa cần bật deterministic CUDA mode có chi phí cao.

### Input

`SEED`.

### Output

Random state ổn định và seeded DataLoader generator.

### Tại sao cần bước này?

Hai lần chạy cùng config phải tạo cùng split và cùng sampling order.

### Liên hệ với cell tiếp theo

Cell 04 giải quyết portability của các path trong canonical index.

## Cell 04 — Dataset Location / Path Configuration

**Loại cell:** Markdown + Code

### Mục đích

Normalize path Windows/Linux và resolve file tương đối với `DATA_ROOT`.

### Concept

Index sinh trên Windows có thể chứa `outputs\full_generation\ml\...`; dấu `\` không phải separator trên
Linux. Resolver chuyển nó thành `/`, thử path canonical trước, rồi chỉ dùng các fallback đã liệt kê rõ và
phát warning. Nó không glob và không âm thầm chọn một file cùng tên không rõ nguồn.

### Input

Raw path từ index và `DATA_ROOT`.

### Output

Một `Path` tồn tại, duy nhất cho mỗi scenario.

### Tại sao cần bước này?

Không normalize sẽ làm notebook Colab thất bại hoặc tệ hơn là đọc nhầm artifact.

### Liên hệ với cell tiếp theo

Cell 05 đọc danh sách membership canonical chứa các raw path này.

## Cell 05 — Load Canonical Dataset Index

**Loại cell:** Markdown + Code

### Mục đích

Đọc `full_dataset_index.csv` và kiểm tra 24 identity, row count, hash/config uniqueness và validation status.

### Concept

**Canonical dataset membership** phải đến từ index, không phải `glob("ml/*.csv")`. Directory còn có thể
chứa output V1 bị reject, trong khi index là tập 24 trajectory V2 đã audit.

### Input

`full_dataset_index.csv` và `final_approved_parameter_sets_v2.csv`.

### Output

DataFrame index canonical và parameter manifest phục vụ split.

### Tại sao cần bước này?

Glob có thể đưa scenario bị reject trở lại training corpus, phá provenance khoa học.

### Liên hệ với cell tiếp theo

Cell 06 biến 24 indexed paths thành file local/Colab cụ thể.

## Cell 06 — Resolve Canonical Scenario Files

**Loại cell:** Markdown + Code

### Mục đích

Resolve đúng 24 file và xác nhận index/manifest có cùng tập `parameter_set_id`.

### Concept

Membership và parameter metadata là hai nguồn bổ sung nhau: index quyết định file nào thuộc corpus; manifest
cung cấp tọa độ vật lý để chọn held-out. Không nguồn nào được tự thêm identity ngoài nguồn kia.

### Input

Canonical index, parameter manifest và path resolver.

### Output

Mapping `parameter_set_id -> resolved ML path` một-một.

### Tại sao cần bước này?

Một identity trùng file hoặc thiếu trong manifest sẽ làm split và provenance sai.

### Liên hệ với cell tiếp theo

Cell 07 kiểm tra nội dung từng source trajectory được chọn.

## Cell 07 — Dataset Integrity Validation

**Loại cell:** Markdown + Code

### Mục đích

Fail-fast nếu schema, timestamp, row count, leap day, finite value hoặc actuator state sai.

### Concept

Validation đứng trước preprocessing để scaler/window không che lỗi nguồn. Pipeline không `dropna`, `fillna`,
clip hay interpolate; mọi invariant fail phải có lỗi rõ ràng. Full mode validate đủ 24 file. Smoke mode validate
đầy đủ hai source file canonical trước khi cắt các đoạn nhỏ.

### Input

CSV source có 9 cột canonical.

### Output

DataFrame timestamp-parsed đã chứng minh: 70.128 rows, hourly continuous, NaN/Inf bằng 0 và actuator thuộc
`{0,1}`.

### Tại sao cần bước này?

Một timestamp thiếu có thể tạo window nhìn có vẻ đúng shape nhưng sai khoảng thời gian vật lý.

### Liên hệ với cell tiếp theo

Cell 08 quyết định trajectory nào dùng để phát triển model và trajectory nào giữ kín.

## Cell 08 — Scenario Split Design

**Loại cell:** Markdown + Code

### Mục đích

Chia 20 development scenario và 4 held-out scenario một cách deterministic.

### Concept

**Scenario holdout** đo khả năng tổng quát hóa (scenario generalization) sang dynamics/configuration chưa thấy.
Năm parameter được min-max normalize; deterministic farthest-point selection chọn bốn điểm phủ không gian
parameter, thay vì random bốn ID. Tie-break theo ID làm kết quả tái lập.

### Input

Năm cột `C_d`, `eta_s`, `C_s_J_K`, `irrigation_flow_L_h`, `ET_scale` từ manifest V2.

### Output

Danh sách 20 development ID và 4 held-out ID. Smoke mode chỉ load một ID từ mỗi nhóm nhưng không thay danh
sách split chính thức.

### Tại sao cần bước này?

Nếu cùng scenario xuất hiện trong train và test, đánh giá chỉ phản ánh thời gian mới chứ chưa phản ánh hệ vật lý mới.

### Liên hệ với cell tiếp theo

Cell 09 tiếp tục tách theo thời gian bên trong development trajectories.

## Cell 09 — Temporal Split Design

**Loại cell:** Markdown + Code

### Mục đích

Định nghĩa TRAIN 2018-2023, validation 2024 và temporal test 2025.

### Concept

**Temporal generalization** yêu cầu model dự báo tương lai chưa thấy. Random raw-row split sẽ đặt các giờ kề
nhau vào train/test, làm thông tin gần như trùng lặp và gây rò rỉ dữ liệu (data leakage). Smoke mode dùng đoạn
ngắn ở từng period và giữ đủ context trước boundary.

### Input

Validated scenario frames và date ranges.

### Output

Ba temporal boundaries; full mode giữ toàn trajectory, smoke mode giữ các đoạn có chủ đích.

### Tại sao cần bước này?

Chronology là cấu trúc của bài toán forecasting, không phải metadata tùy chọn.

### Liên hệ với cell tiếp theo

Cell 10 khóa feature và target được phép dùng sau split.

## Cell 10 — Feature / Target Contract

**Loại cell:** Markdown + Code

### Mục đích

Khóa tám input feature và năm output target deployment-aligned.

### Concept

Mỗi timestep có:

\[
x_t \in \mathbb{R}^{8}
\]

gồm 5 sensor + 3 actuator. Target tương lai chỉ là 5 sensor states. Timestamp, parameter, hash và physics/weather
variables chỉ là metadata hoặc diagnostics, không phải model input.

### Input

Contract `ML_DATA_CONTRACT.md`.

### Output

`FEATURE_COLUMNS` dài 8 và `TARGET_COLUMNS` dài 5.

### Tại sao cần bước này?

Feature không có trên Raspberry Pi lúc inference sẽ làm model synthetic không deploy được.

### Liên hệ với cell tiếp theo

Cell 11 định nghĩa transformation riêng cho continuous sensor và binary actuator.

## Cell 11 — Scaling Policy

**Loại cell:** Markdown + Code

### Mục đích

Dùng StandardScaler cho 5 continuous variables và passthrough actuator 0/1.

### Concept

Continuous sensor có đơn vị và độ lớn rất khác nhau, đặc biệt lux so với VWC. Standardization giúp training sau
ổn định hơn. Binary actuator đã có encoding có ý nghĩa nên giữ 0/1. Feature scaler và target scaler tách riêng:

```text
model output scaled
        -> target_scaler.inverse_transform(...)
        -> physical units
```

Cell cũng định nghĩa điều kiện để một target có đủ lookback liên tục trong quá khứ.

### Input

Feature/target contract và timestamp của một scenario.

### Output

Feature transformer và helper tìm target positions hợp lệ.

### Tại sao cần bước này?

Standardize actuator sẽ làm mất cách diễn giải trực tiếp; không kiểm tra continuity có thể nối qua gap smoke/split.

### Liên hệ với cell tiếp theo

Cell 12 fit statistics trên đúng TRAIN subset.

## Cell 12 — Fit Train-only Scalers

**Loại cell:** Markdown + Code

### Mục đích

Fit feature scaler và target scaler chỉ từ development TRAIN.

### Concept

Quy tắc chống leakage là:

```text
fit(train)
transform(validation)
transform(test)
transform(held-out)
```

Target scaler học từ các target TRAIN có window hợp lệ. Validation, 2025 và held-out không ảnh hưởng mean/scale.
`partial_fit` theo scenario tránh concat một DataFrame lớn mà vẫn cho cùng train statistics.

### Input

Development frames, TRAIN date range và valid target positions.

### Output

Train-fitted scalers cùng số row đã dùng để audit.

### Tại sao cần bước này?

Fit scaler trên toàn corpus đưa distribution của tương lai/test vào training pipeline dù chưa train model.

### Liên hệ với cell tiếp theo

Cell 13 biểu diễn supervised windows mà không materialize chúng.

## Cell 13 — Sliding Window Definition

**Loại cell:** Markdown + Code

### Mục đích

Định nghĩa compact sequence index cho cửa sổ trượt (sliding window).

### Concept

Với baseline:

\[
X_t = [x_{t-23}, \ldots, x_t] \in \mathbb{R}^{24 \times 8}
\]

\[
y_{t+1} \in \mathbb{R}^{5}
\]

`LOOKBACK_STEPS=24` mô tả lượng lịch sử; 48/72/168 là các experiment sau. `FORECAST_HORIZON=1` là one-step
forecast; multi-step forecasting sẽ cần target contract khác. Index chỉ lưu scenario code và target position,
không lưu `N x 24 x 8` values.

### Input

Scenario frames, date range, lookback và horizon.

### Output

Compact `SequenceIndex`.

### Tại sao cần bước này?

Materialize toàn bộ 1,68 triệu windows sẽ nhân RAM theo lookback và gây lãng phí lớn.

### Liên hệ với cell tiếp theo

Cell 14 tạo index riêng cho năm loại evaluation subset.

## Cell 14 — Sequence Index Generation

**Loại cell:** Markdown + Code

### Mục đích

Tạo train, validation, temporal test, scenario test và combined scenario-temporal test indices.

### Concept

Ba loại generalization được chuẩn bị:

1. **Temporal:** 2025 trên development scenarios.
2. **Scenario:** held-out scenarios trong thời gian đã xuất hiện ở development period.
3. **Combined:** 2025 trên held-out scenarios.

Split được quyết định bởi **target timestamp**. Target `2024-01-01 00:00` được phép dùng 24 giờ cuối 2023 vì
đó là historical context có thật tại inference time, không phải future leakage. Scaler vẫn chỉ học TRAIN.

### Input

Scenario identities, split boundaries và compact index builder.

### Output

Năm non-empty sequence indices không crossing scenario.

### Tại sao cần bước này?

Nếu cấm context trước boundary, ta bỏ một cách không cần thiết target đầu split; nếu cho context sau target, ta leak.

### Liên hệ với cell tiếp theo

Cell 15 dùng index để định nghĩa chính xác “một sample là gì”.

## Cell 15 — Lazy GreenhouseSequenceDataset

**Loại cell:** Markdown + Code

### Mục đích

Implement `GreenhouseSequenceDataset` lazy/index-based.

### Concept

PyTorch Dataset định nghĩa **một sample là gì**. Chỉ khi `__getitem__` được gọi, Dataset mới resolve scenario,
slice 24 timestep, transform continuous feature, giữ actuator 0/1 và transform target. Tensor là CPU
`float32`; device transfer thuộc training loop sau.

### Input

Frames, sequence index và train-fitted scalers.

### Output

Một sample `X [24, 8]`, `Y [5]`.

### Tại sao cần bước này?

Lazy loading giữ RAM theo raw frames + compact index, không theo số window nhân lookback.

### Liên hệ với cell tiếp theo

Cell 16 gom các sample thành mini-batch.

## Cell 16 — DataLoader Construction

**Loại cell:** Markdown + Code

### Mục đích

Tạo DataLoader cho train, validation và ba test concepts.

### Concept

Dataset định nghĩa sample; DataLoader định nghĩa cách lấy sample thành batch. `train_loader shuffle=True` chỉ
shuffle **windows sau khi split đúng**, giúp SGD sau này. Nó khác hoàn toàn với random split raw rows. Validation
và test không shuffle để audit thứ tự ổn định.

### Input

Năm lazy Dataset, batch size, worker count và seeded generator.

### Output

Năm DataLoader CPU-ready.

### Tại sao cần bước này?

Training notebook cần batching thống nhất và không nên tự viết lại sampling policy.

### Liên hệ với cell tiếp theo

Cell 17 chứng minh mọi reference giữ đúng boundary và chronology.

## Cell 17 — Boundary & Leakage Checks

**Loại cell:** Markdown + Code

### Mục đích

Audit toàn bộ compact indices về split membership, continuity, target alignment và historical context.

### Concept

Rò rỉ dữ liệu time-series xảy ra khi input dùng thời điểm bằng/sau target, scaler học test distribution, hoặc
sequence nối các trajectory/gap. Check vectorized xác nhận input end luôn trước target đúng `FORECAST_HORIZON`,
lookback có spacing hourly, và target nằm trong đúng split. Mỗi reference chỉ resolve bên trong một frame nên
không thể cross scenario.

### Input

Năm sequence indices và timestamps của scenario frames.

### Output

Số windows đã kiểm tra và PASS cho boundary context 2024/2025.

### Tại sao cần bước này?

Shape đúng không đủ chứng minh sample đúng về thời gian.

### Liên hệ với cell tiếp theo

Cell 18 lấy batch thật để smoke-test toàn pipeline.

## Cell 18 — Smoke Test

**Loại cell:** Markdown + Code

### Mục đích

Fetch nhiều batch và assert dtype, shape, finite values, actuator passthrough và inverse transform.

### Concept

Smoke test không đánh giá accuracy. Nó chỉ hỏi pipeline có chạy end-to-end đúng contract hay không. Batch shape:

```text
X: [B, 24, 8]
Y: [B, 5]
```

`B` là số sample trong batch; 24 là time; 8 là feature; 5 là output state. Inverse transform được so với target
raw để bảo đảm sau này prediction có thể trở về °C, %RH, VWC và lux.

### Input

DataLoaders, Dataset và scaler.

### Output

Smoke summary PASS, không có model hay loss.

### Tại sao cần bước này?

Unit nhỏ có thể PASS riêng lẻ nhưng integration vẫn sai shape hoặc dtype.

### Liên hệ với cell tiếp theo

Cell 19 tổng hợp counts/statistics phục vụ audit.

## Cell 19 — Dataset / Window Statistics

**Loại cell:** Markdown + Code

### Mục đích

Hiển thị scenario split, window counts và train-fitted feature statistics.

### Concept

Diagnostics nhẹ cho biết pipeline đã tạo bao nhiêu sample và scaler học distribution nào mà không cần plot phức
tạp hoặc duplicate dữ liệu.

### Input

Split IDs, sequence indices và feature scaler.

### Output

Ba bảng audit nhỏ.

### Tại sao cần bước này?

Counts bất thường thường phát hiện boundary/range sai sớm hơn training.

### Liên hệ với cell tiếp theo

Cell 20 lưu chính sách và scalers để notebook sau dùng lại.

## Cell 20 — Export Preprocessing Artifacts

**Loại cell:** Markdown + Code

### Mục đích

Export `feature_scaler.pkl`, `target_scaler.pkl`, `split_manifest.json` và `preprocessing_config.json`.

### Concept

Artifact tách data transformation khỏi model checkpoint. Split manifest giữ scenario IDs, dates, seed và chiến
lược selection; preprocessing config giữ columns, scaling và window contract. Feature scaler file chứa scaler
của continuous sensors; binary passthrough được ghi rõ trong config.

### Input

Train-fitted scalers và toàn bộ contract/split metadata.

### Output

Các artifact dưới `artifacts/preprocessing/` khi full notebook chạy trên Colab. Smoke execution dùng directory
riêng để không giả làm full artifact.

### Tại sao cần bước này?

Training/inference phải dùng đúng scaler đã fit TRAIN và cùng feature order.

### Liên hệ với cell tiếp theo

Cell 21 khóa trạng thái cuối milestone.

## Cell 21 — Final Pipeline Summary

**Loại cell:** Markdown + Code

### Mục đích

Tổng hợp canonical rows, split, dimensions, counts, leakage checks và trạng thái training.

### Concept

Một structured summary giúp validator/test đọc kết quả bằng object thay vì suy luận từ log. `full_training_executed`
luôn là `False` trong milestone này.

### Input

Mọi audit result đã tạo ở các cell trước.

### Output

`pipeline_summary` với status PASS nếu toàn bộ assertions trước đã qua.

### Tại sao cần bước này?

Notebook chỉ được coi là Colab-ready khi có bằng chứng end-to-end, không chỉ vì code compile.

### Liên hệ với cell tiếp theo

Đây là cell cuối. Milestone kế tiếp có thể đọc artifact để xây persistence baseline, GRU và LSTM.

# Tổng kết pipeline

1. **Dữ liệu đầu vào là gì?** 24 file ML canonical được liệt kê duy nhất trong `full_dataset_index.csv`.
2. **Vì sao có 24 scenario?** Chúng đại diện 24 parameter sets vật lý hợp lệ và là 24 trajectory 2018-2025 độc lập.
3. **Dataset được split thế nào?** 20 development/4 held-out, rồi development được chia 2018-2023/2024/2025.
4. **Vì sao không random row split?** Raw rows kề nhau có temporal dependence; random split sẽ leak chronology.
5. **Scaler học từ đâu?** Chỉ development scenarios trong TRAIN 2018-2023.
6. **Sliding window tạo sample thế nào?** 24 timestep input liên tục dự báo 5 state ở một giờ tiếp theo.
7. **Một sample có shape gì?** `X [24, 8]`, `Y [5]`.
8. **Một batch có shape gì?** `X [B, 24, 8]`, `Y [B, 5]`.
9. **Dataset và DataLoader khác nhau thế nào?** Dataset định nghĩa sample; DataLoader gom/shuffle sample thành batch.
10. **Milestone này đã làm gì?** Validation, split, train-only scaling, lazy indexing, Dataset, DataLoader và smoke audit.
11. **Milestone này chưa làm gì?** Chưa train persistence model, GRU, LSTM, CNN-GRU, Attention-LSTM hay Transformer.

**CHƯA TRAIN GRU/LSTM/TRANSFORMER.**
