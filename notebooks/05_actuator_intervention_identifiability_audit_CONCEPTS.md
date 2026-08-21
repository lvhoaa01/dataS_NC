# Notebook 05 Concepts: Actuator Intervention & Identifiability-Readiness Audit

Tài liệu này ánh xạ đúng 28 logical section của
`05_actuator_intervention_identifiability_audit.ipynb`. Notebook chỉ audit dữ
liệu quan sát do controller tạo ra; không train model và không chứng minh quan hệ
nhân quả.

## Colab bootstrap - trước Cell 00

Hai physical cell đầu tiên là bootstrap riêng cho Google Colab. Khi module
`google.colab` khả dụng, notebook mount `/content/drive`, đặt `DATA_ROOT` thành
`/content/drive/MyDrive/smart_greenhouse_dataset`, cấu hình preprocessing và full
audit artifact directories, rồi ép `GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST=false`
trước khi import helper. Notebook assert file
`DATA_ROOT/actuator_identifiability_audit.py` tồn tại và báo cách khắc phục rõ
ràng nếu Drive thiếu file này. Không có CUDA gate vì audit chỉ dùng CPU.

Ngoài Colab, bootstrap không mount Drive và không sửa environment. Cơ chế locate
helper qua working directory, parent và `GREENHOUSE_DATA_ROOT` vẫn được giữ để
local smoke hoặc execution trong workspace tiếp tục hoạt động.

## Cell 00 - Experiment Overview

Actuator xuất hiện trong history chưa đủ để model trả lời câu hỏi can thiệp. Nếu
controller bật fan khi nóng, tương quan `fan=ON` với nhiệt độ cao có thể phản ánh
rule kích hoạt thay vì response của hệ. Notebook đo support, overlap và response
mô tả trước khi cân nhắc action-conditioned LSTM.

## Cell 01 - Context from Notebook 04 FULL_FIXED

Nguồn chuẩn duy nhất của milestone trước là
`04_operational_lookback_ablation_FULL_FIXED.ipynb`. Contract được khóa ở history
24 giờ, horizon `+1h/+3h`, input `[B,24,8]` và output `[B,2,5]`; Notebook 05 không
mở lại ablation.

## Cell 02 - Configuration

Seed, quantile bins và các audit heuristic được tập trung trong `AuditConfig`.
Chúng là ngưỡng vận hành có khai báo, không phải ngưỡng khoa học phổ quát. Default
smoke luôn `False`; environment chỉ override khi kiểm tra integration.

## Cell 03 - Imports

Notebook dùng Python standard library, NumPy, Pandas, Joblib và Matplotlib trên
CPU. Helper chỉ được import sau Colab bootstrap. Không có PyTorch model,
optimizer, training loop, LLM hay API client.

## Cell 04 - Reproducibility

Binning, matching và mọi tie-break đều deterministic. Seed và phạm vi heuristic
được lưu cùng artifacts để lần chạy sau có thể audit lại.

## Cell 05 - Paths

Ba environment variables tách data root, preprocessing artifacts và audit
artifacts. Execution mode được khóa trước khi resolve path. Smoke chỉ được ghi
vào directory có leaf `actuator_identifiability_audit_smoke`, full chỉ được ghi
vào `actuator_identifiability_audit`; hai path được assert khác nhau. Notebook
locate rồi hash bản `FULL_FIXED`; bản Notebook 04 cũ không được dùng làm authority.

## Cell 06 - Load Locked Split and Canonical Index

Split manifest khóa 20 development và 4 held-out IDs. Canonical membership đến
từ `full_dataset_index.csv`. Notebook kiểm tra lại exact feature/target contract.
Khoảng cách matching được chuẩn hóa bằng thống kê của sensor trên development
TRAIN đang audit; phép chuẩn hóa này chỉ phục vụ diagnostic, không thay đổi ML
feature contract và không fit model.

## Cell 07 - Resolve Development Scenarios Only

Resolver chỉ nhận development IDs. Held-out IDs được giữ làm provenance nhưng
đường dẫn CSV không được resolve và file không được load. Không có temporal,
scenario hay combined final-test partition.

## Cell 08 - Trace Actuator Temporal Semantics

Source trace đi qua `actuator_schedule -> run_simulation -> rk4_step ->
_build_output_row`. Row `t` chứa sensor state và command tại đầu giờ `t`; command
được áp vào substep đầu tiên rồi controller tính lại ở mỗi substep 60 giây. Vì
vậy command trong row không được hiểu là giữ nguyên toàn bộ `[t,t+1h)`. CSV chỉ
lưu command đầu giờ, nên fan nội giờ là giới hạn quan sát quan trọng. Pump là xung
60 giây lúc 06:00/18:00, fan là threshold policy không hysteresis/timer và grow
light baseline cố định OFF. Controller hiện `STATELESS`.

## Cell 09 - Load and Validate Per-Scenario Data

Mỗi scenario được đọc riêng, kiểm tra schema 9 cột, timestamp liên tục, finite
sensor values và actuator nhị phân. TRAIN 2018-2023 và VALIDATION 2024 được cắt
thành frame riêng, ngăn transition hay target vượt boundary.

## Cell 10 - Actuator Usage Coverage

Audit tính OFF/ON count và fraction aggregate, cùng phân phối ON fraction theo
scenario. Điều này phát hiện actuator gần như tĩnh dù số row tổng rất lớn.

## Cell 11 - Transition Detection

Các cặp `00/01/10/11` được đếm bên trong từng scenario và split. Không nối row
cuối scenario này với row đầu scenario khác, cũng không nối TRAIN sang VALIDATION.

## Cell 12 - Dwell-Time Analysis

Run-length encoding đo thời gian OFF/ON liên tục bằng giờ. Mean, median, quantile
và maximum phân biệt switching thường xuyên, sustained run và static behavior.

## Cell 13 - Joint Action Coverage

Joint code dùng thứ tự cố định `pump|fan|grow_light`, tạo tám mã `000` đến `111`.
Count, fraction và số scenario có từng mã được report; combination vắng mặt là
evidence support chứ không tự động là lỗi simulator.

## Cell 14 - State-Conditioned Action Overlap

Quantile edges được derive từ TRAIN rồi reuse cho VALIDATION. Pump condition trên
soil moisture, air temperature/humidity; fan trên air temperature/humidity; grow
light trên lux và hour-of-day. Binning đo empirical support overlap, không phải
causal positivity proof. Hour chỉ là audit variable, không phải deployment feature.

## Cell 15 - Transition Event Construction

Event chứa scenario, timestamp, direction, state hiện tại, các actuator khác và
target sensor `+1h/+3h`. Event cuối split không được dùng nếu target vượt boundary.

## Cell 16 - +1h / +3h Response Semantics

Response vật lý được định nghĩa `Delta Y(h)=Y(t+h)-Y(t)`. Vì row `t` là state đầu
giờ trước interval integration, delta là post-transition association đúng alignment
đã trace, nhưng vẫn không phải causal effect.

## Cell 17 - Raw Transition Response

Notebook tổng hợp count, mean, standard deviation, median và quantiles cho từng
actuator, direction, horizon và sensor trong đơn vị vật lý gốc.

## Cell 18 - Clean Single-Actuator Events

Clean subset yêu cầu hai actuator không phải target giữ nguyên tại transition và
qua response horizon. Notebook report riêng việc target actuator có giữ new state
tới horizon hay không, nhưng không dùng nó để loại pulse ngắn như pump 60 giây.
Nếu clean support nhỏ, kết quả phải được report thay vì silently bỏ qua.

## Cell 19 - No-Change Reference Windows

Reference giữ target actuator ổn định từ trước `t` qua `t+h`. Đây là nhóm so sánh
mô tả, không phải randomized control group.

## Cell 20 - State-Matched Response Diagnostic

Transition được nearest-match với no-change row trong cùng split, cùng scenario,
cùng hour, cùng state của hai actuator khác và cùng target action state. Khoảng
cách dùng năm sensor đã standardize bằng mean/std của development TRAIN. Matching
kém được gắn `LIMITED`, không bị ép thành kết luận. Unmatched fraction được tính
trên từng target và giữ cả event không match trong mẫu số. Engine dùng bounded
`NearestNeighbors`: event và reference được chọn deterministic, trải theo thời
gian, với cap full/smoke tập trung trong `AuditConfig`. Vì vậy matching là
secondary diagnostic có chi phí hữu hạn, không phải brute-force trên mọi cặp row.

## Cell 21 - Confounding Diagnostics

Current-state distribution trước transition được so với stable OFF/ON thật sự:
target action không đổi từ `t-1` tới `t+3h`. Mean, median, quantiles và
standardized mean difference được report cho năm sensor cùng hour-of-day
diagnostic. Fan-hot, pump-moisture và grow-light-time patterns cho thấy policy
confounding lớn hay nhỏ.

## Cell 22 - Scenario-Level Support

ON fraction, transition và clean event được đếm theo scenario. Điều này tránh
aggregate support bị chi phối bởi một hoặc hai parameter sets đặc biệt.

## Cell 23 - Train vs Validation Stability

TRAIN và VALIDATION được giữ riêng khi so ON fraction, transition rate, joint
coverage và response mean. Validation chỉ replication; criteria không được tune
để làm distribution shift trông nhỏ hơn.

## Cell 24 - Plot Diagnostics

Tám plot khoa học tóm tắt usage, transitions, dwell, joint actions, overlap,
response `+1h/+3h` và confounding. Không có plot trang trí.

## Cell 25 - Readiness Assessment

Readiness enum gồm `READY`, `PARTIAL`, `TARGETED_DATA_REQUIRED` và
`REVIEW_REQUIRED`. Quyết định dựa trên nhiều evidence thô; không xuất
`CAUSAL_IDENTIFIABILITY=YES`. Smoke luôn `REVIEW_REQUIRED` vì không đủ bằng chứng
khoa học.

## Cell 26 - Save Artifacts

Notebook ghi 12 metric CSV (gồm summary no-change references), 8 plot và bốn JSON
về semantics, config, manifest và readiness. Không lưu giant event table hay
checkpoint vì milestone không train.

## Cell 27 - Final Audit Summary

Summary ghi execution mode, operational contract, held-out lock, readiness, causal
claim `False`, model training `False`, LLM `False` và final tests `False`.

## Khi nào cần targeted intervention generation?

Nếu một actuator thiếu ON/OFF transitions, clean events hoặc overlap, bước kế tiếp
là thiết kế một số trajectory can thiệp có mục tiêu trong simulator. Không nên
regenerate toàn bộ dataset và không nên train action-conditioned model trên support
không tồn tại. Đặc biệt grow light baseline hiện cố định OFF, nên full audit được
kỳ vọng sẽ nhận diện thiếu support thay vì tự tạo kết luận response.
