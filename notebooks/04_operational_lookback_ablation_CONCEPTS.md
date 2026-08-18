# Notebook 04 Concepts: Operational Lookback Ablation

Tài liệu này ánh xạ đúng các logical section của
`04_operational_lookback_ablation.ipynb`. Notebook là một controlled experiment
chỉ thay đổi độ dài lịch sử, không mở final tests và không tăng model capacity.

## Cell 00 - Experiment Overview

Notebook trả lời câu hỏi: để dự báo vận hành `+1h` và `+3h`, LSTM cần 24, 48 hay
72 giờ lịch sử? Mọi yếu tố khác được giữ cố định. Đây là model-development
experiment trên train/validation, chưa phải đánh giá cuối cùng.

## Cell 01 - Operational Forecasting Decision

Notebook 03 cho thấy forecast `+1h` có độ chính xác và giá trị điều khiển cao,
còn `+3h` vẫn đủ hữu ích cho cảnh báo xu hướng. Các horizon 6/12/24 giờ vẫn có
giá trị nghiên cứu nhưng chịu ảnh hưởng ngày càng lớn của future controls và
external forcing không biết trước, nên không còn là requirement vận hành chính.

## Cell 02 - Configuration

Cell khóa lookbacks `(24,48,72)`, horizons `(1,3)`, batch size, optimizer, seed và
early-stopping protocol. Full mode yêu cầu full preprocessing artifacts và GPU;
smoke mode chỉ chạy một scenario, một epoch và vài batch. Expected common-window
counts được khai báo để fail-fast nếu semantics thay đổi.

## Cell 03 - Imports

Các dependency gồm Python standard library, NumPy/Pandas, Joblib, Matplotlib và
PyTorch. Không có calendar feature package, weather API, future control planner
hay architecture framework khác.

## Cell 04 - Reproducibility

Cùng seed được đặt lại cho Python, NumPy, PyTorch và DataLoader generator trước
mỗi lookback run. CuDNN dùng deterministic policy. Sequence length khác nhau vẫn
có thể tạo training trajectory khác, nhưng model initialization và shuffle policy
bắt đầu từ cùng điều kiện tái lập.

## Cell 05 - Device Gate

Full ablation fail sớm nếu không có CUDA; local CPU chỉ được phép trong smoke.
Điều này ngăn full training vô tình chạy chậm trên local rồi bị hiểu nhầm là kết
quả Colab hoàn chỉnh.

## Cell 06 - Paths

Data root, preprocessing artifacts và output directory nhận environment override
để chạy được trên Windows lẫn Colab. Scenario path được resolve từ canonical
index bằng các fallback tường minh; filesystem glob không quyết định membership.

## Cell 07 - Load Preprocessing Artifacts

Feature scaler, target scaler, split manifest và preprocessing config được load
nguyên trạng từ Notebook 01. Notebook 04 không gọi fit/partial-fit/fit-transform,
không tạo scaler riêng cho từng lookback và full mode từ chối smoke scaler.

## Cell 08 - Validate Locked Contract

Feature order vẫn là 5 sensor + 3 actuator; target vẫn là 5 sensor. Split giữ 20
development và 4 held-out scenarios, train 2018-2023, validation 2024. Calendar,
weather, scenario ID và physics-only states không được thêm vào model input.

## Cell 09 - Load Canonical Index

`full_dataset_index.csv` là source of truth cho đúng 24 full-valid trajectories.
Cell kiểm tra unique IDs/config hashes, row count và PASS status để rejected/debug
outputs không lọt vào experiment.

## Cell 10 - Resolve Development Files

Chỉ 20 development IDs được ánh xạ thành CSV paths. Bốn held-out IDs chỉ được đọc
từ split manifest để audit provenance; notebook không resolve hay load held-out
CSV và không tạo final-test data.

## Cell 11 - Build Per-Scenario Arrays

Mỗi trajectory được kiểm tra schema 9 cột, 70,128 giờ liên tục, finite values và
actuator nhị phân. Sensor được transform bằng scaler đã khóa, actuator giữ 0/1.
Arrays được giữ riêng theo scenario để window không thể nối qua scenario boundary.

## Cell 12 - Common Target Window Semantics

`CommonSequenceIndex` dùng `MAX_LOOKBACK=72` và `MAX_HORIZON=3` để xác định một
tập `(scenario_id,input_end)` duy nhất. Targets luôn là `S[t+1]` và `S[t+3]`.
Index chỉ giữ reference, không materialize tensor `N x 72 x 8`.

## Cell 13 - Build Common Train/Validation Index

Train có 52,584 giờ/scenario. Sau constraint 72-hour context và `+3h` target,
còn 52,510 common windows/scenario, tổng 1,050,200. Validation 2024 cho phép
historical context từ cuối 2023 và có 8,782 windows/scenario, tổng 175,640.
Counts được derive và assert, không điều chỉnh để làm test pass.

## Cell 14 - Lookback-Aware Dataset

Một Dataset class nhận `lookback_steps`. Với cùng input end `t`, nó slice
`t-23:t`, `t-47:t` hoặc `t-71:t`, nhưng lấy cùng target positions `t+1,t+3`.
Ba train loaders shuffle bằng generator riêng cùng seed; ba validation loaders
tuần tự. Không có temporal/scenario/combined final-test loader.

## Cell 15 - Shape and Fairness Audit

Cell kiểm tra `X24=[B,24,8]`, `X48=[B,48,8]`, `X72=[B,72,8]`, và
`Y=[B,2,5]`. Cả ba Dataset phải giữ cùng object index; targets exact-equal và 24
giờ cuối của input dài hơn phải bằng input 24h. Validation target đầu tiên nằm ở
2024 trong khi input được phép kết thúc ở 2023-12-31 23:00.

## Cell 16 - Persistence Baselines

LastValue dự báo `S_t` cho cả hai horizons. DailySeasonal dùng `S[t+h-24]`, tức
vẫn chỉ dùng quá khứ vì `h` là 1 hoặc 3. Baselines được tính một lần trên common
validation targets vì prediction không phụ thuộc lookback khi lookback >=24.

## Cell 17 - LSTM Architecture

Architecture cố định là LSTM input size 8, hidden 64, một layer và Linear(64,10),
reshape thành `[B,2,5]`. Lookback là sequence dimension, không phải input size.
Parameter count và initialization hash phải giống nhau cho 24/48/72, chứng minh
capacity không thay đổi. LSTM được cố định theo kết quả selection của Notebook 03;
không train lại GRU.

## Cell 18 - Shared Training Utilities

Ba run dùng equal-weight standardized MSE, AdamW `lr=1e-3`, weight decay `1e-4`,
gradient clip 1.0, tối đa 50 epochs và patience 7. Utility đo epoch duration,
training duration và samples/second, lưu best validation checkpoint atomically,
và kiểm tra finite predictions/loss/gradients.

## Cell 19 - Train Lookback 24h

Run 24h cho model thấy một daily cycle và tạo reference accuracy/cost. Seed được
reset trước model construction và loader shuffle. Smoke chỉ chạy integration path,
không cung cấp scientific metric.

## Cell 20 - Train Lookback 48h

Run 48h cho model thấy hai daily cycles, có thể so sánh hôm nay với hôm qua và
nhận ra trend liên ngày. Architecture, targets, scaler và optimizer không đổi.

## Cell 21 - Train Lookback 72h

Run 72h cung cấp ba daily cycles và context dài hơn cho thermal/soil-water inertia,
nhưng có thể dư thừa. Sau run, parameter count của cả ba model được assert bằng
nhau; notebook không mặc định 72h phải tốt hơn.

## Cell 22 - Validation Predictions

Mỗi best checkpoint chỉ predict trên validation loader tương ứng. Target tensors
của 24/48/72 được so exact-equality, sau đó đối chiếu với raw target transform.
Inference duration được đo riêng. Không prediction nào được tạo cho final tests.

## Cell 23 - Metrics by Lookback and Horizon

Với mỗi lookback và horizon, notebook tính standardized MSE cùng MAE/RMSE/R2 theo
physical unit cho từng sensor. Không average MAE giữa các unit. Persistence metrics
được lưu như operational references, không nhân bản giả thành ba baseline models.

## Cell 24 - Per-Target Lookback Analysis

Metrics được chuyển thành long table theo lookback, horizon và target. Bảng này
cho biết context dài hơn giúp air temperature, humidity, soil states hay light,
thay vì chỉ nhìn aggregate score.

## Cell 25 - Accuracy Improvement Analysis

Notebook tính aggregate validation MSE và relative improvements 48-vs-24,
72-vs-24, 72-vs-48 bằng công thức có denominator rõ ràng. Best-accuracy lookback
là minimum validation MSE, không hard-code theo sequence length.

## Cell 26 - Runtime / Efficiency Analysis

Summary ghi best epoch/MSE, total và mean epoch time, inference time, throughput,
parameter count, input elements và approximate input bytes/batch. Input elements
lần lượt là 192, 384, 576; đây là context cost dù model parameters không đổi.

## Cell 27 - Practical Trade-off Summary

Best accuracy và practical trade-off là hai kết luận khác nhau. Notebook báo
accuracy gain cùng sequence/runtime/memory multipliers mà không đặt threshold tùy
ý. Full validation data sẽ cho phép nhận diện practical sweet spot; smoke chỉ xác
nhận calculation path.

## Cell 28 - Diagnostic Plots

Notebook tạo ba loss curves, aggregate validation MSE theo lookback, MAE theo
lookback cho `+1h` và `+3h`, cùng accuracy-runtime scatter. Plots ưu tiên cách đọc
khoa học và không chứa final-test results.

## Cell 29 - Save Artifacts

Checkpoints, histories, metrics tables, persistence references, practical summary
và manifest được ghi vào artifact directory riêng. Manifest khóa common-index,
feature/target order, horizons, model config và các cờ held-out/final tests false.
Smoke outputs ở directory riêng và bị Git ignore.

## Cell 30 - Checkpoint Reload Verification

Mỗi lookback tạo đúng deterministic validation batch, instantiate fresh LSTM,
load checkpoint rồi assert prediction equivalence. Checkpoint phải khớp lookback,
horizons, direct strategy và output `[B,2,5]`.

## Cell 31 - Final Summary

Summary ghi fairness, scaler load-only, checkpoint/metrics/efficiency status và
final-test embargo. Local smoke phải ghi full lookback ablation chưa chạy và không
đưa ra scientific winner. Full experiment sau này chạy trên Colab GPU; calendar,
future controls, CNN/Attention/Transformer vẫn là axes khác chưa được mở.
