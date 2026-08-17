# Notebook 03 Concepts: Direct Multi-Horizon GRU/LSTM

Tài liệu này giải thích các khái niệm và quyết định khoa học của
`03_multi_horizon_gru_lstm.ipynb`. Mỗi mục ánh xạ đúng một logical section trong
notebook. Notebook này chỉ dùng train/validation để phát triển mô hình; ba final
test partitions bị khóa hoàn toàn cho một milestone đánh giá riêng.

## Cell 00 - Mục tiêu và validation-only protocol

Notebook mở rộng bài toán one-step thành direct multi-horizon forecasting. Một
chuỗi 24 giờ lịch sử được dùng để dự báo trực tiếp trạng thái sensor tại 1, 3, 6,
12 và 24 giờ tới. Mục tiêu của notebook là so sánh hai recurrent baseline với hai
persistence baseline trên validation 2024. Nó không tạo final-test loader, không
đọc dữ liệu held-out và không công bố final-test metric.

## Cell 01 - Cấu hình thí nghiệm

Cấu hình khóa `lookback=24`, năm train 2018-2023, năm validation 2024, năm final
temporal test 2025 và năm quen thuộc 2018-2024. Chỉ hai khoảng đầu được dùng ở
đây. Chế độ mặc định là full Colab/GPU; local smoke phải được bật rõ bằng biến môi
trường, giới hạn còn một scenario, một epoch, ba train batch và hai validation
batch. Smoke không phải kết quả khoa học.

## Cell 02 - Imports

Cell import thư viện chuẩn, NumPy/Pandas, scikit-learn metrics, PyTorch,
Matplotlib và Joblib. Không có thư viện weather API, LLM/API hay framework huấn
luyện ẩn. Điều này làm execution path minh bạch và tái lập được.

## Cell 03 - Reproducibility

Seed được đặt cho Python, NumPy, PyTorch CPU và CUDA. CuDNN deterministic được
bật và benchmark heuristic bị tắt. Generator riêng của DataLoader bảo đảm thứ tự
shuffle train có thể tái lập khi seed và môi trường không đổi.

## Cell 04 - Device gate

Full mode yêu cầu CUDA và fail sớm nếu GPU không tồn tại. Chế độ smoke cho phép
CPU vì chỉ kiểm tra integration. Gate này ngăn một full training lớn vô tình chạy
trên local CPU rồi bị hiểu nhầm là thí nghiệm hoàn chỉnh.

## Cell 05 - Paths và artifact isolation

Notebook nhận data root, preprocessing artifact directory và multi-horizon
artifact directory từ biến môi trường. Full artifacts mặc định nằm ở
`artifacts/multi_horizon_training`; smoke dùng một thư mục tách biệt. Canonical
membership đến từ `full_dataset_index.csv`, không từ việc glob file trong output.

## Cell 06 - Load-only preprocessing artifacts

Feature scaler, target scaler, split manifest và preprocessing config được load
từ notebook 01. Notebook 03 không gọi `fit`, `partial_fit` hay `fit_transform`.
Full mode cũng từ chối artifact mang cờ smoke để tránh dùng scaler được fit trên
một lát dữ liệu ngắn.

## Cell 07 - Locked data contract

Cell xác nhận đúng 8 feature theo deployment, 5 target sensor, 20 development
scenario và 4 held-out scenario. ID split được đọc nguyên trạng từ manifest;
không chạy lại thuật toán chọn split. Held-out IDs chỉ được audit provenance và
không được resolve thành CSV trong notebook này.

## Cell 08 - Canonical index

`full_dataset_index.csv` là source of truth duy nhất cho 24 trajectory. Index
được kiểm tra schema, ID/config hash duy nhất, row count, classification, đường
dẫn và hash. Cách này tránh vô tình đưa file debug hoặc rejected scenario vào
corpus.

## Cell 09 - Chỉ resolve development files

Notebook chỉ ánh xạ 20 development IDs sang ML CSV. Bốn held-out IDs không có
path trong `development_scenario_paths`. Đây là một privacy wall về mặt thí
nghiệm: biết danh tính split để kiểm tra provenance không đồng nghĩa được quyền
đọc dữ liệu split đó.

## Cell 10 - Per-scenario arrays

Mỗi CSV được kiểm tra đúng 70,128 hourly rows, đúng 9 cột, timestamps liên tục,
không NaN/Inf và actuator nhị phân. Sensor columns được scale bằng feature scaler
và target scaler đã khóa; ba actuator giữ nguyên 0/1. Các trajectory vẫn tách
riêng nên window không thể vượt qua biên scenario.

## Cell 11 - Multi-horizon window semantics

Một sample được định danh bằng scenario và vị trí `t`, tức cuối input window.
Input là `X[t-23:t]`; target matrix chứa `S[t+1]`, `S[t+3]`, `S[t+6]`, `S[t+12]`
và `S[t+24]`. Mọi target timestamp phải nằm trong split đang đánh giá. Lịch sử
trước boundary có thể được dùng làm context, nhưng không target nào được nằm
ngoài split.

## Cell 12 - Train/validation indices

Full mode tạo đúng 52,537 train windows và 8,761 validation windows cho mỗi
development scenario, tổng lần lượt 1,050,740 và 175,220. Chênh lệch với one-step
count xuất phát từ target xa nhất `t+24`. Smoke dùng khoảng ngắn nhưng giữ nguyên
semantics. Không có index cho temporal, scenario hoặc combined final tests.

## Cell 13 - Dataset và DataLoader

Dataset dựng window lazily từ index thay vì materialize tensor khổng lồ
`N x 24 x 8`. Train loader shuffle, validation loader tuần tự. Đây là hai loader
duy nhất được tạo. Batch contract là input `[B,24,8]` và target `[B,5,5]`.

## Cell 14 - Shape, boundary và equivalence checks

Cell kiểm tra dtype float32, shape, finite values, không vượt scenario, exact
horizon offsets và validation boundary dùng hoàn toàn lịch sử. Một sample được
đối chiếu với transform trực tiếp của scaler để chứng minh tối ưu per-scenario
array không thay đổi numerical semantics.

## Cell 15 - LastValue persistence

LastValue dùng trạng thái sensor cuối input `S_t` làm dự báo cho mọi horizon.
Baseline không có tham số và không nhìn future. Nó trả tensor `[N,5,5]`, nên
được chấm bằng cùng evaluator với GRU/LSTM.

## Cell 16 - DailySeasonalPersistence

Với horizon `h`, baseline dự báo bằng quan sát tại `t+h-24`. Mọi vị trí này đều
không muộn hơn `t`, nên vẫn past-only. Với `h=24`, chỉ số trở thành `t`, do đó
dự báo đúng bằng trạng thái cuối input. Cell có assertion riêng cho identity này.

## Cell 17 - Direct GRU/LSTM architecture

GRU và LSTM đều nhận 8 feature, hidden size 64, một recurrent layer và lấy hidden
state cuối. Linear head ánh xạ 64 giá trị thành `5 horizons x 5 targets = 25`, sau
đó reshape thành `[B,5,5]`. Đây là direct forecast: mô hình không autoregress qua
các dự báo trung gian và không nhận future actuator/weather.

## Cell 18 - Shared training utilities

Hai mô hình dùng cùng code train/evaluate, MSE chuẩn hóa với equal weighting trên
tất cả horizon-target cells, AdamW `lr=1e-3`, weight decay `1e-4`, gradient clip
1.0, tối đa 50 epoch và early stopping patience 7. Best checkpoint được chọn duy
nhất bằng aggregate validation standardized MSE.

## Cell 19 - Train GRU

GRU được khởi tạo từ scratch, không load one-step checkpoint. Smoke chỉ chạy một
epoch và vài batch để chứng minh forward/backward/optimizer/checkpoint path. Full
mode sẽ dùng toàn bộ train/validation loaders trên CUDA.

## Cell 20 - Train LSTM

LSTM dùng cùng seed, dimensions và protocol với GRU để so sánh công bằng. Nó cũng
được train từ scratch và lưu best validation checkpoint độc lập.

## Cell 21 - Validation-based selection

LastValue, DailySeasonalPersistence, GRU và LSTM được xếp hạng bằng aggregate
validation standardized MSE. Không có final-test metric tham gia lựa chọn. Record
ghi rõ partition, criterion và việc final tests chưa được chạy.

## Cell 22 - Validation predictions

Notebook chỉ infer trên validation loader. Target chuẩn hóa từ DataLoader được
đối chiếu với target raw do baseline collector đọc từ cùng index. Mọi prediction
và target phải finite và có shape `[N,5,5]`.

## Cell 23 - Metrics theo horizon và target

Ở mỗi horizon và sensor, notebook tính MAE, RMSE và R² trong physical units. Nó
cũng tính standardized MSE từng horizon và aggregate. Không lấy mean MAE của các
đại lượng khác đơn vị, không dùng MAPE làm primary metric và không clip prediction.

## Cell 24 - Horizon degradation

Degradation ratio so sánh lỗi tại mỗi horizon với lỗi h=1 của cùng model và cùng
target. Chỉ số này cho thấy forecast mất chất lượng nhanh tới đâu khi tầm nhìn xa
hơn, nhưng không thay thế physical-unit metrics.

## Cell 25 - Skill scores

Skill được định nghĩa từ MSE so với LastValue và DailySeasonalPersistence. Giá trị
dương nghĩa là model tốt hơn baseline tương ứng, zero là ngang bằng, âm là kém
hơn. Skill được báo riêng từng horizon để tránh aggregate che giấu horizon yếu.

## Cell 26 - Future actuator change audit

Future actuator không được đưa vào model. Sau khi prediction đã hoàn tất, cell
dùng actuator trace để gắn nhãn liệu pump/fan/grow-light có thay đổi trong khoảng
`t+1..t+h`, rồi so lỗi giữa nhóm change/no-change. Đây chỉ là diagnostic về giới
hạn của past-only forecast, không phải feature engineering hay model selection.

## Cell 27 - Diagnostic plots

Notebook tạo loss curves, standardized MSE theo horizon cho bốn model, MAE theo
horizon cho từng target và một đoạn validation liên tục của preferred recurrent
model tại h=24. Plot h=24 ghi rõ input kết thúc trước target 24 giờ để tránh cách
diễn giải sai về temporal alignment.

## Cell 28 - Artifact contract

Checkpoints, histories, metrics, plots, model configs và run manifest được ghi vào
artifact directory mới. Manifest khóa feature/target order, horizon order, split
hash, scaler hashes, past-only semantics và cờ final tests chưa chạy. Smoke
artifacts nằm ngoài full artifact directory.

## Cell 29 - Checkpoint reload

Notebook tạo fresh GRU/LSTM instance, load best state dict và so prediction với
model đang giữ trong memory. Checkpoint cũng phải khớp lookback, horizons, feature
order, target order, direct strategy và past-only control policy. Điều này bảo vệ
khả năng tái sử dụng artifact ở milestone sau.

## Cell 30 - Final summary

Summary chỉ xác nhận implementation/smoke integration. Nó ghi rõ scaler không
refit, held-out CSV không load, final-test loaders không được tạo, final tests
không chạy và full training không chạy trong local smoke. Chỉ full Colab execution
sau này mới có quyền tạo scientific validation metrics; final-test evaluation vẫn
là một task tách biệt sau khi mô hình bị đóng băng.
