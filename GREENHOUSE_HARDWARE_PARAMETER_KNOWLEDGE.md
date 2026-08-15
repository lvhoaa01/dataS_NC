# GREENHOUSE HARDWARE & PARAMETER KNOWLEDGE BASE — PA1

> **Vai trò của tài liệu**
>
> Đây là tài liệu tri thức phần cứng và tham số vật lý cho dự án greenhouse/synthetic dataset.
> Codex/agent MUST đọc tài liệu này cùng với:
>
> `GREENHOUSE_PHYSICS_DATASET_KNOWLEDGE.md`
>
> trước khi implement hoặc sửa physics simulator.
>
> Tài liệu này trả lời câu hỏi:
>
> **Thiết bị thật nào tạo/đo biến nào, thông số số học lấy từ đâu, và parameter nào đi vào E0–E10?**
>
> Nguồn BOM gốc: `Danh sách.xlsx` → sheet `PA 1 - Chính`.
>
> Trạng thái xác minh web: **2026-08-15**.

---

# 1. Quy tắc provenance

Mỗi giá trị trong simulator phải mang một provenance rõ ràng.

| Nhãn | Ý nghĩa |
|---|---|
| `USER_BOM` | Thông tin lấy trực tiếp từ BOM Phương án 1 của dự án |
| `VERIFIED_PRODUCT_SPEC` | Đã đối chiếu với trang hãng/shop/datasheet |
| `PROJECT_DESIGN_ASSUMPTION` | Giá trị do dự án chủ động thiết kế để hoàn thiện prototype |
| `LITERATURE_PRIOR` | Giá trị/miền giá trị lấy từ tài liệu khoa học/kỹ thuật |
| `TO_MEASURE` | Phải đo trên phần cứng thật trước khi coi là ground truth |
| `TO_CALIBRATE` | Phải fit/calibrate bằng sensor data thực |
| `DERIVED` | Tính toán từ các tham số đã biết |

**Codex không được đổi provenance thành `VERIFIED_PRODUCT_SPEC` nếu giá trị chỉ là giả định thiết kế.**

---

# 2. Phạm vi Phương án 1

Hệ thống vật lý được thiết kế cho:

- **01 chậu cà chua**
- 01 Raspberry Pi 5 4 GB
- 01 Camera Module 3
- 03 cảm biến RS485:
  - nhiệt độ + RH không khí
  - nhiệt độ + độ ẩm đất
  - illuminance/lux
- 03 tải điều khiển:
  - bơm tưới
  - quạt thông gió
  - grow light
- 01 relay board 3 kênh
- weather forcing bên ngoài lấy từ Open-Meteo

Đây là prototype nghiên cứu/đồ án, không phải mô hình greenhouse thương mại quy mô lớn.

---

# 3. Thiết kế vật lý greenhouse v1

## 3.1 Crop

```yaml
crop:
  species: Solanum lycopersicum
  common_name: tomato
  count: 1
  preferred_form: compact/determinate or trained single plant
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Lý do chọn giống/cách nuôi compact hoặc có giàn dẫn:
buồng prototype chỉ cao 1.5 m nên không nên giả định một cây indeterminate thương mại phát triển không giới hạn.

---

## 3.2 Kích thước buồng

Chốt baseline:

```yaml
greenhouse:
  internal_length_m: 0.80
  internal_width_m: 0.80
  internal_height_m: 1.50
```

Suy ra:

\[
V_g = 0.8 \times 0.8 \times 1.5 = 0.96\;m^3
\]

\[
A_f = 0.8\times0.8 = 0.64\;m^2
\]

Nếu coi buồng là hộp chữ nhật, không tính đáy vào diện tích cover trao đổi với không khí ngoài:

\[
A_c = 4(0.8\times1.5) + 0.8\times0.8 = 5.44\;m^2
\]

```yaml
greenhouse:
  volume_m3:
    value: 0.96
    provenance: DERIVED

  floor_area_m2:
    value: 0.64
    provenance: DERIVED

  exposed_cover_area_m2:
    value: 5.44
    provenance: DERIVED
```

### E-equation mapping

- \(V_g\) → **E5**
- \(A_f\), \(A_c\) → **E7**
- geometry/height → **E2**

---

# 4. Chậu và substrate cho 1 cây cà chua

## 4.1 Pot volume

Oklahoma State University Extension ghi nhận các cây phổ biến như tomato cần container ít nhất khoảng **5 gallon**.

Nguồn:
https://extension.okstate.edu/fact-sheets/container-gardening

5 US gallon ≈ 18.9 L.

Dự án chốt:

```yaml
pot:
  nominal_volume_L:
    value: 20
    provenance: PROJECT_DESIGN_ASSUMPTION
  nominal_volume_m3:
    value: 0.020
    provenance: DERIVED
```

Một hình học tham khảo phù hợp:

```yaml
pot_geometry:
  top_diameter_m: 0.30
  effective_height_m: 0.28
  shape: approximate cylinder
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Diện tích mặt substrate xấp xỉ:

\[
A_s = \pi(0.15)^2 \approx 0.0707\;m^2
\]

```yaml
root_zone:
  effective_volume_m3:
    value: 0.020
    provenance: PROJECT_DESIGN_ASSUMPTION

  exposed_surface_area_m2:
    value: 0.0707
    provenance: DERIVED
```

### E-equation mapping

- \(V_{root}\) → **E9**
- \(A_s\) → **E7**, **E8**

---

## 4.2 Substrate

Chọn baseline:

```yaml
substrate:
  type: commercial well-drained potting mix
  use_field_garden_soil: false
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Không khóa một recipe coco/perlite cụ thể trước khi mua substrate thật.

### Soil-water parameters

Simulator sử dụng volumetric water content:

\[
\theta \in [0,1]
\]

Các parameter:

```yaml
soil_water:
  theta_field_capacity:
    initial_prior: 0.42
    unit: m3/m3
    provenance: PROJECT_DESIGN_ASSUMPTION
    status: TO_MEASURE

  theta_wilting_point:
    initial_prior: 0.15
    unit: m3/m3
    provenance: PROJECT_DESIGN_ASSUMPTION
    status: TO_CALIBRATE

  readily_available_depletion_fraction_p:
    initial_prior: 0.40
    provenance: LITERATURE_PRIOR
    status: TO_CALIBRATE
```

**Các số 0.42 và 0.15 KHÔNG phải datasheet của cảm biến và không được trình bày như hằng số của mọi potting mix.**

Field capacity thực nên được đo sau khi tưới bão hòa rồi để thoát nước.
University of Minnesota Extension mô tả VWC và gợi ý xác định field capacity bằng giá trị sensor sau khoảng 12–24 giờ sau một lần tưới/rain mạnh.

Nguồn:
https://extension.umn.edu/irrigation/soil-moisture-sensors-irrigation-scheduling

### Rule

Sau khi có hệ thật:

```text
theta_field_capacity = MEASURED
theta_wilting_point / stress threshold = CALIBRATED
```

thay vì tiếp tục dùng initial prior.

---

# 5. Cover / vỏ nhà kính

## 5.1 Vật liệu

Chọn baseline:

```yaml
cover:
  material: clear greenhouse polyethylene film
  layers: 1
  nominal_thickness: 6 mil (~0.15 mm)
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Oklahoma State University Extension ghi nhận 6-mil polyethylene là vật liệu cover rất phổ biến cho high tunnel và single-layer film cho phép truyền sáng tốt.

Nguồn:
https://extension.okstate.edu/fact-sheets/high-tunnels

### Lưu ý BOM

Cover/frame hiện **chưa nằm trong BOM PA1**.
Nếu prototype được lắp thật, đây là `BOM_GAP` phải bổ sung.

---

## 5.2 Solar transmittance

Baseline simulator:

```yaml
cover:
  shortwave_transmittance:
    value: 0.85
    uncertainty_range: [0.75, 0.92]
    provenance: LITERATURE_PRIOR
    status: TO_CALIBRATE

  visible_transmittance:
    value: 0.88
    provenance: PROJECT_DESIGN_ASSUMPTION
    status: TO_CALIBRATE
```

Nghiên cứu đo commercial greenhouse covering plastics cho thấy transmission thay đổi đáng kể theo vật liệu; vì vậy không được random \(\tau\) theo từng giờ.

Nguồn khoa học chính:
Baneshi et al., Energy (2020)
https://doi.org/10.1016/j.energy.2020.118535

### E-equation mapping

- \(\tau_{sw}\) → **E1**
- \(\tau_{vis}\) → **E10**

---

## 5.3 Overall heat-transfer coefficient

Single polyethylene film có U-value cao hơn double-layer cover.

Initial baseline:

```yaml
cover:
  U_W_m2K:
    value: 6.4
    provenance: LITERATURE_PRIOR
    status: TO_CALIBRATE
```

Nguồn kỹ thuật/khoa học:

- UGA Extension mô tả heat loss greenhouse theo cover area, temperature difference và thermal resistance:
  https://extension.uga.edu/publications/detail.html?number=B792

- Một nghiên cứu greenhouse bench-top dùng giá trị khoảng 6.4 W/m²K cho single polyethylene film:
  https://doi.org/10.1007/s43621-024-00276-5

### Project parameter

\[
UA_c = U A_c
\]

Codex nên tính `UA_c` từ `U_W_m2K × exposed_cover_area_m2`, không hard-code riêng.

---

# 6. Passive opening / ventilation geometry

Prototype cần đường khí vào/ra.

Thiết kế baseline:

```yaml
passive_vent:
  effective_open_area_m2:
    value: 0.010
    physical_example: 0.10 m x 0.10 m opening
    provenance: PROJECT_DESIGN_ASSUMPTION

  effective_height_m:
    value: 1.20
    provenance: PROJECT_DESIGN_ASSUMPTION
```

Đây là geometry thiết kế, không phải thông số có sẵn trong BOM.

Các coefficient như:

```text
C_d
C_w
Vdot_leak
```

vẫn thuộc `LITERATURE_PRIOR / TO_CALIBRATE` và được quản lý bởi physics knowledge/config, không giả là hardware datasheet.

### E-equation mapping

- \(A_v, H_v\) → **E2**

---

# 7. Cảm biến nhiệt độ + RH không khí

## Thiết bị

**TH10S-B-PE — SHT30 — RS485 Modbus RTU**

BOM:
```text
Cảm biến nhiệt độ/độ ẩm không khí TH10S-B-PE
```

Trang sản phẩm:
https://epcb.vn/products/cam-bien-rs485-modbus-rtu-th10s-b-pe

Thông số đã xác minh:

```yaml
air_sensor:
  model: TH10S-B-PE
  sensing_chip: SHT30
  supply_VDC: [9, 30]
  interface: RS485 Modbus RTU

  temperature:
    range_C: [-40, 80]
    accuracy_C: ±0.5
    resolution_C: 0.1

  relative_humidity:
    range_percent: [0, 100]
    accuracy_percent_RH: ±3
    resolution_percent_RH: 0.1

  power_consumption_W: "<0.1"
  provenance: VERIFIED_PRODUCT_SPEC
```

### Vai trò trong dataset

Sensor này **không sinh physics state**.

Nó dùng để đo:

```text
temperature_inside_sensor
humidity_inside_sensor
```

để validate:

```text
temperature_inside_true
humidity_inside_true
```

từ E5–E7.

### Sensor-observation layer

Nếu muốn synthetic dataset mô phỏng luôn sai số cảm biến, tách:

```text
*_true
*_sensor
```

Ví dụ:

\[
T_{sensor}=T_{true}+\epsilon_T
\]

với error model được giới hạn theo ±0.5°C.

\[
RH_{sensor}=RH_{true}+\epsilon_{RH}
\]

với error model được giới hạn theo ±3%RH.

**Không thêm sensor noise vào chính state vật lý.**

### E-equation mapping

- validation of **E5, E6, E7**

---

# 8. Cảm biến nhiệt độ + độ ẩm đất

## Thiết bị

**ES-SM-TH-01 — RS485 Modbus RTU**

Trang sản phẩm:
https://epcb.vn/products/cam-bien-do-do-am-nhiet-do-dat-es-sm-th-01

Thông số xác minh:

```yaml
soil_sensor:
  model: ES-SM-TH-01
  supply_VDC: [12, 24]
  interface: RS485 Modbus RTU
  protection: IP68
  response_time_s: "<1"

  moisture:
    output_range_percent: [0, 100]
    accuracy:
      0_to_53_percent: ±3%
      53_to_100_percent: ±5%

  temperature:
    range_C: [-40, 80]
    accuracy_C: ±0.5

  probe_length_mm: 70
  probe_diameter_mm: 3
  probe_material: stainless steel 316
  provenance: VERIFIED_PRODUCT_SPEC
```

### CỰC KỲ QUAN TRỌNG — sensor % ≠ mặc định theta physics

Trang sản phẩm trả một giá trị độ ẩm đất theo %.

Physics simulator E9 sử dụng:

\[
\theta = \text{volumetric water content}
\]

Không được mặc định:

```text
sensor_percent / 100 == theta
```

trước khi xác minh/calibrate trên substrate thật.

Do đó model phải có một lớp mapping:

\[
SensorMoisture = g(\theta; calibration)
\]

ban đầu có thể dùng identity chỉ như một approximation tạm thời, nhưng phải đánh dấu:

```yaml
soil_sensor_mapping:
  status: TO_CALIBRATE
```

### Cách calibration tối thiểu

1. Đặt sensor đúng depth trong chậu.
2. Tưới substrate bão hòa.
3. Để thoát nước 12–24 h.
4. Ghi sensor value làm mốc gần field capacity.
5. Dry-down có kiểm soát để thu mapping sensor% ↔ water content/stress.
6. Không thay đổi vị trí sensor trong quá trình calibration.

### E-equation mapping

- validation of **E8, E9**
- measurement calibration for **E3**

---

# 9. Cảm biến ánh sáng

## Thiết bị

**ES-ALS-02 — RS485 Modbus RTU**

Trang sản phẩm:
https://epcb.vn/products/cam-bien-anh-sang-cong-nghiep-es-als-02-rs485-modbus-rtu

Thông số xác minh:

```yaml
light_sensor:
  model: ES-ALS-02
  supply_VDC: [10, 30]
  interface: RS485 Modbus RTU
  max_power_W: 0.4
  accuracy_at_25C: ±5%
  range_options_lux:
    - [0, 65535]
    - [0, 200000]
  working_temperature_C: [-40, 60]
  working_RH_percent: [0, 95]
  response_time_s: "<=2"
  protection: IP65
  output_resolution_lux: 1
  provenance: VERIFIED_PRODUCT_SPEC
```

### Vai trò

Đo:

```text
light_lux_inside_sensor
```

để calibrate/validate **E10**.

### Grow-light calibration protocol

Để tách ánh sáng đèn khỏi mặt trời:

1. Đo ban đêm hoặc che hoàn toàn nguồn solar.
2. Đặt sensor tại canopy reference point.
3. Grow light OFF → đo baseline.
4. Grow light ON → đo steady reading.
5. Tính:

\[
Lux_{grow,max}
=
Lux_{ON}-Lux_{OFF}
\]

6. Lặp ở nhiều khoảng cách nếu vị trí đèn có thể thay đổi.

### E-equation mapping

- calibration/validation of **E10**

---

# 10. Quạt thông gió

## Thiết bị

**Quạt mini 5 V, 30 × 30 × 7 mm**

Trang sản phẩm:
https://mlab.vn/4397409-quat-tan-nhiet-danh-cho-raspberry-pi.html

Thông số xác minh:

```yaml
fan:
  supply_V: 5
  current_A: 0.2
  speed_RPM: "6000 ±10%"
  nominal_airflow_m3_h: 5.0
  noise_dBA: "18 ±10%"
  provenance: VERIFIED_PRODUCT_SPEC
```

Đổi đơn vị:

\[
5\;m^3/h
=
1.3889\times10^{-3}\;m^3/s
\]

Với greenhouse \(V_g=0.96m^3\):

\[
ACH_{fan,free-air}
=
\frac{5}{0.96}
\approx
5.21\;h^{-1}
\]

```yaml
fan:
  nominal_airflow_m3_s:
    value: 0.0013889
    provenance: DERIVED

  nominal_free_air_ACH:
    value: 5.21
    provenance: DERIVED
```

### Important modelling rule

`5 m3/h` là **free-air nominal flow**.

Sau khi lắp qua:
- lưới,
- opening,
- đường khí,
- cover,
- resistance,

effective airflow có thể thấp hơn.

Do đó:

```yaml
fan:
  effective_airflow_m3_s:
    initial_value: 0.0013889
    provenance: VERIFIED_PRODUCT_SPEC
    status: TO_MEASURE_OR_CALIBRATE
```

Khi có dữ liệu thật, fit lại effective flow.

### E-equation mapping

- \(\dot V_{fan,max}\) → **E2**
- ảnh hưởng **E5**, **E7**

---

# 11. Bơm nước

## Thiết bị

**Bơm chìm mini DC 6–18 V**

Trang sản phẩm:
https://mlab.vn/3748096-bom-nuoc-chim-mini-dc-6v-18v-550l-h.html

Thông số xác minh:

```yaml
pump:
  supply_VDC: [6, 18]
  project_operating_voltage_V: 12
  nominal_flow_L_h: [280, 500]
  power_W: [0.8, 15]
  rated_head_cm: [60, 420]
  dimensions_mm: [45, 43, 30]
  provenance: VERIFIED_PRODUCT_SPEC
```

### Không được đưa 280–500 L/h trực tiếp vào E9

Pump flow là capability của bơm.

Nước thật tới chậu bị giới hạn bởi:
- ống 4 mm,
- head,
- fitting,
- béc,
- độ mở béc.

Physics E9 cần:

```text
q_irrigation_effective
```

không phải `pump_nominal_flow`.

---

# 12. Béc tưới và flow thực tế

BOM:

```text
Đầu béc nhỏ giọt điều chỉnh, chân 4 mm, 0–70 L/h
```

Listing:
https://shopee.vn/S%C3%A9t-10-%C4%90%E1%BA%A7u-B%C3%A9c-Nh%E1%BB%8F-Gi%E1%BB%8Dt-T%C6%B0%E1%BB%9Bi-C%C3%A2y-8-Tia-%C4%90i%E1%BB%81u-Ch%E1%BB%89nh-L%C6%B0u-L%C6%B0%E1%BB%A3ng-0-70L-B%C3%A1n-K%C3%ADnh-T%C6%B0%E1%BB%9Bi-0-30cm-Ch%C3%A2n-N%E1%BB%91i-4mm-i.394697078.25389750925

Baseline thiết kế:

```yaml
irrigation_emitter:
  adjustable_range_L_h: [0, 70]
  design_setting_L_h:
    value: 10
    provenance: PROJECT_DESIGN_ASSUMPTION
    status: TO_MEASURE
```

Đổi đơn vị:

\[
10\;L/h
=
2.7778\times 10^{-6}\;m^3/s
\]

Do đó:

```yaml
irrigation:
  q_irrigation_effective_m3_s:
    initial_value: 0.0000027778
    provenance: PROJECT_DESIGN_ASSUMPTION
    status: TO_MEASURE
```

Với 10 L/h:

```text
30 s pulse ≈ 83 mL
60 s pulse ≈ 167 mL
120 s pulse ≈ 333 mL
```

Đây là mức phù hợp hơn nhiều cho chậu 20 L so với dùng thẳng 280–500 L/h.

### Cách đo q_irrigation_effective

Sau khi lắp đúng hệ thống:

1. Đặt béc vào bình đo.
2. Bật bơm trong 60 s.
3. Đo thể tích nước thu được.
4. Lặp >= 5 lần.
5. Lấy mean và standard deviation.
6. Ghi lại đúng độ cao bơm, chiều dài ống, độ mở béc.

Sau đó thay `PROJECT_DESIGN_ASSUMPTION` bằng:

```text
MEASURED
```

### E-equation mapping

- \(q_{pump}\) thực tế trong **E9** = `q_irrigation_effective`
- không dùng pump nominal flow trực tiếp

---

# 13. Grow light

## Thiết bị

BOM:

```text
Grow-light full-spectrum 18 W E27 có dây/phích
```

Nguồn BOM:
Shopee listing trong `Danh sách.xlsx`.

Baseline đã biết:

```yaml
grow_light:
  type: E27 full-spectrum grow light
  electrical_power_W: 18
  supply: 220VAC mains
  provenance: USER_BOM
```

### Không giả định output photon/lux từ 18 W

Chưa có datasheet đáng tin cậy cho:
- PPFD
- photon efficacy
- lux tại canopy
- heat fraction

Do đó:

```yaml
grow_light:
  canopy_lux_gain:
    value: null
    provenance: TO_MEASURE

  radiant_fraction:
    value: null
    provenance: TO_CALIBRATE

  heat_fraction:
    value: null
    provenance: TO_CALIBRATE
```

### Simulator v1

Electrical power:

\[
P_{LED}=18W
\]

được phép dùng trực tiếp.

Nhưng:

```text
Lux_grow_max
eta_rad_LED
eta_heat_LED
```

không được tự suy ra chỉ từ `18 W`.

### E-equation mapping

- \(P_{LED}\), \(\eta_{rad,LED}\) → **E4**
- \(P_{LED}\), \(\eta_{heat,LED}\) → **E7**
- \(Lux_{grow,max}\) → **E10**

---

# 14. Relay board

## Thiết bị

**Waveshare RPi Relay Board — 3 channels**

Official:
https://www.waveshare.com/rpi-relay-board.htm

Thông số xác minh:

```yaml
relay_board:
  channels: 3
  trigger_logic_V: [3.3, 5]
  contact_rating:
    AC: "5A @ 250VAC"
    DC: "5A @ 30VDC"
  isolation: photo-coupling
  provenance: VERIFIED_PRODUCT_SPEC
```

### Channel map chính thức của project

```yaml
relay_channels:
  CH1: pump
  CH2: ventilation_fan
  CH3: grow_light
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Các trạng thái này tạo:

```text
u_pump
u_fan
u_grow
```

trong simulator.

### E-equation mapping

- CH1 → **E9**
- CH2 → **E2 → E5/E7**
- CH3 → **E4/E7/E10**

---

## 14.1 Safety rule cho grow light AC

Grow light là tải 220 VAC, không phải tải trên rail 12 V.

Relay contact rating của board về mặt danh định hỗ trợ đến 250 VAC/5 A, nhưng **contact rating không tự động làm toàn bộ assembly an toàn với điện lưới**.

Các yêu cầu phần cứng ngoài physics model:
- phần 220 VAC phải nằm trong enclosure thích hợp;
- không đưa mains lên breadboard;
- tách dây mains khỏi dây sensor/logic;
- dùng terminal/ferrule và strain relief phù hợp;
- thao tác AC khi mất điện;
- nên có bảo vệ điện phù hợp (fuse/RCD/ELCB theo hệ điện sử dụng).

Physics simulator chỉ nhìn:

```text
u_grow ∈ {0,1}
```

và không mô hình hóa điện lưới.

---

# 15. Nguồn 12 V

## Thiết bị

BOM:

```text
Adapter 12 V 2 A
```

Trang sản phẩm:
https://epcb.vn/products/nguon-power-ac-adaptor-12v-1-5a-zin

Thông số xác minh:

```yaml
dc_supply:
  output_voltage_V: 12
  max_current_A: 2
  max_nominal_power_W: 24
  input: 100-240VAC 50/60Hz
  provenance: VERIFIED_PRODUCT_SPEC
```

### Vai trò physics

Không trực tiếp vào E0–E10.

Nó là infrastructure để cấp:
- bus RS485 sensor
- pump

và cần kiểm tra power budget khi lắp hệ thật.

---

# 16. Raspberry Pi 5

BOM:

```yaml
controller:
  device: Raspberry Pi 5
  RAM_GB: 4
  provenance: USER_BOM
```

Vai trò:
- đọc RS485
- điều khiển relay
- camera
- log dữ liệu
- chạy edge software

**Không phải parameter của E0–E10.**

---

# 17. Camera Module 3

BOM:

```yaml
camera:
  model: Raspberry Pi Camera Module 3
  sensor: Sony IMX708
  resolution: 12 MP
  autofocus: PDAF
  HDR: true
  field_of_view_variant: visible 75 degree
  provenance: USER_BOM
```

Vai trò:
- plant image
- health/status observation
- dataset multimodal tương lai

**Không đi trực tiếp vào E0–E10.**

---

# 18. USB → RS485 CH340

```yaml
rs485_adapter:
  controller: CH340 + MAX485
  host: Raspberry Pi
  signals: [A, B, GND]
  provenance: USER_BOM
```

Vai trò:
- transport layer cho 3 sensor RS485

Không phải physics parameter.

---

# 19. LCD1602

```yaml
display:
  type: LCD1602
  logic_voltage: 3.3V
  controller_family: HD44780
  provenance: USER_BOM
```

Vai trò:
- local status display

Không phải physics parameter.

---

# 20. Những vật tư phụ có ảnh hưởng gián tiếp

| Thiết bị | Vai trò |
|---|---|
| IP68 electronics box | tách relay/đấu nối khỏi nước/đất |
| terminal block | đấu tải/nguồn chắc chắn hơn breadboard |
| ferrule 0.75 mm² | đầu dây screw terminal |
| dây đôi 2×0.75 mm² | đường tải/nguồn |
| cable gland IP68 PG7 | strain relief + cable entry |
| ống PE 4 mm | irrigation path |
| béc 0–70 L/h | giới hạn flow thực vào E9 |
| VHB / mica / dây rút | gá sensor/camera |

Các vật tư này thường **không trở thành state/parameter trực tiếp**, ngoại trừ đường ống và béc làm thay đổi `q_irrigation_effective`.

---

# 21. Sensor placement v1

Đây là project design, không phải datasheet.

## Air T/RH sensor

```yaml
placement:
  air_sensor:
    height_m: 0.75
    rule: near canopy, shaded from direct grow-light/solar beam, not directly in fan jet
```

Mục tiêu: đọc đại diện microclimate của cây, không phải nhiệt độ bề mặt bị chiếu trực tiếp.

## Soil sensor

```yaml
placement:
  soil_sensor:
    insertion_depth_cm: 7
    radial_position: mid-root-zone
    rule: avoid touching pot wall; keep position fixed
```

Probe dài 70 mm nên insertion ~7 cm là consistent với geometry sensor.

## Light sensor

```yaml
placement:
  light_sensor:
    reference: canopy plane
    rule: face upward, avoid permanent shade from frame/camera
```

## Camera

```yaml
placement:
  camera:
    reference: fixed frontal/oblique view
    rule: fixed pose for longitudinal dataset
```

---

# 22. Sampling design

Sensor response:
- ES-SM-TH-01: <1 s
- ES-ALS-02: ≤2 s
- TH10S-B-PE: no project-verified response-time requirement needed for minute sampling

Do:

```yaml
acquisition:
  raw_sensor_period_s: 60
  actuator_log: event + 60s snapshot
  physics_internal_step_s: 60-300
  ML_master_interval: 1h
  provenance: PROJECT_DESIGN_ASSUMPTION
```

Recommended architecture:

```text
sensor readings every 60 s
        ↓
raw real-data store
        ↓
hourly aggregation / alignment
        ↓
compare with Open-Meteo-driven simulator
```

Do not throw away minute-level real data only because the historical weather dataset is hourly.

---

# 23. True-state vs sensor-observed dataset contract

Physics simulator generates latent/true states:

```text
temperature_inside_true
humidity_inside_true
soil_temperature_inside_true
soil_moisture_inside_true
light_lux_inside_true
```

Sensor model may produce:

```text
temperature_inside_sensor
humidity_inside_sensor
soil_temperature_inside_sensor
soil_moisture_inside_sensor
light_lux_inside_sensor
```

Pipeline:

\[
PhysicsTrueState
\rightarrow
SensorModel
\rightarrow
ObservedValue
\]

Không được:

\[
PhysicsState \leftarrow random\ sensor\ noise
\]

rồi dùng noisy state tiếp tục dynamics, trừ khi cố ý mô phỏng closed-loop controller dùng measurement.

Nếu controller dùng sensor:
- control decision được phép dựa vào `*_sensor`
- physical dynamics vẫn evolve từ `*_true`

---

# 24. Map phần cứng → equations

| E | Physics process | Hardware/design parameters |
|---|---|---|
| **E0** | outdoor vapor | không cần phần cứng; Open-Meteo |
| **E1** | solar transmission | PE cover, `tau_sw` |
| **E2** | ventilation | greenhouse volume, passive vent, 5 m³/h fan |
| **E3** | soil water stress | 20 L substrate, `theta_fc`, `theta_wp`; soil sensor calibration |
| **E4** | crop ET | 1 tomato, crop effective area, grow-light contribution |
| **E5** | vapor mass balance | `V_g=0.96 m³`, ventilation flow |
| **E6** | derive RH | TH10S-B-PE dùng validate |
| **E7** | air energy balance | cover area/U, fan, 18 W light, soil exchange |
| **E8** | pot temperature | 20 L root-zone, pot surface area, soil temp sensor |
| **E9** | soil moisture | 20 L root-zone, pump, 4 mm tube, emitter measured flow |
| **E10** | illuminance | cover visible transmission, 18 W light, ES-ALS-02 calibration |

---

# 25. Parameter table — baseline để Codex dùng

## 25.1 Có thể dùng ngay

```yaml
project_baseline:
  greenhouse:
    length_m: 0.80
    width_m: 0.80
    height_m: 1.50
    volume_m3: 0.96
    floor_area_m2: 0.64
    exposed_cover_area_m2: 5.44

  crop:
    species: tomato
    count: 1

  pot:
    volume_m3: 0.020
    top_surface_area_m2: 0.0707

  cover:
    material: single_clear_PE
    shortwave_transmittance: 0.85
    visible_transmittance: 0.88
    U_W_m2K: 6.4

  passive_vent:
    effective_area_m2: 0.010
    effective_height_m: 1.20

  fan:
    nominal_airflow_m3_h: 5.0
    nominal_airflow_m3_s: 0.0013889

  irrigation:
    pump_nominal_flow_L_h_min: 280
    pump_nominal_flow_L_h_max: 500
    emitter_design_flow_L_h: 10
    emitter_design_flow_m3_s: 0.0000027778

  grow_light:
    electrical_power_W: 18

  soil_water:
    theta_field_capacity_initial: 0.42
    theta_wilting_point_initial: 0.15
    depletion_fraction_p_initial: 0.40
```

---

## 25.2 Phải giữ trạng thái chưa chắc chắn

```yaml
must_not_be_treated_as_measured:
  fan_effective_airflow_m3_s: TO_MEASURE_OR_CALIBRATE
  emitter_actual_flow_m3_s: TO_MEASURE
  theta_field_capacity: TO_MEASURE
  theta_wilting_point: TO_CALIBRATE
  cover_shortwave_transmittance: TO_CALIBRATE_IF_REAL_COVER_DIFFERS
  cover_visible_transmittance: TO_CALIBRATE
  grow_light_canopy_lux_gain: TO_MEASURE
  grow_light_heat_fraction: TO_CALIBRATE
  grow_light_radiant_fraction: TO_CALIBRATE
  effective_thermal_capacity: TO_CALIBRATE
  air_soil_heat_transfer_coefficient: TO_CALIBRATE
  crop_transpiration_coefficients: TO_CALIBRATE
  soil_sensor_percent_to_vwc_mapping: TO_CALIBRATE
```

---

# 26. Initial actuator interpretation

```yaml
controls:
  pump_state:
    values: [0, 1]
    relay: CH1

  fan_state:
    values: [0, 1]
    relay: CH2

  grow_light_state:
    values: [0, 1]
    relay: CH3

  vent_state:
    value: 1
    meaning: passive opening always present
```

Nếu sau này có servo/motorized vent:
`vent_state` có thể đổi thành `[0,1]` hoặc opening fraction `[0,1]`.

---

# 27. Hardware-aware synthetic noise

Tùy chọn v2:

```yaml
measurement_error_bounds:
  air_temperature_C: 0.5
  air_RH_percent: 3
  soil_temperature_C: 0.5
  soil_moisture_percent:
    low_range: 3
    high_range: 5
  lux_percent: 5
```

Đây là **bounds lấy từ accuracy specification**, không có nghĩa noise phải uniform hoặc Gaussian với sigma bằng đúng giá trị đó.

Nếu tạo noise:
- model distribution phải ghi rõ;
- giữ true state riêng;
- validation phải dùng cả true và observed.

---

# 28. BOM gaps phải nhận biết

Những thứ cần cho physical prototype nhưng chưa xuất hiện rõ trong PA1:

```text
greenhouse frame
clear PE cover
20 L pot
potting substrate
tomato seedling
passive vent mesh/opening hardware if needed
water reservoir
plant support/stake
appropriate mains protection/enclosure hardware for 220 VAC branch
```

Không phải tất cả đều cần đưa vào budget simulation,
nhưng Codex không được giả rằng chúng đã mua chỉ vì simulator có parameter.

---

# 29. Những thông số không được Codex tự bịa

Nếu chưa có giá trị từ `GREENHOUSE_PHYSICS_DATASET_KNOWLEDGE.md` hoặc file này:

```text
C_eff
C_d
C_w
h_as
k_R
k_D
k_d
eta_heat_LED
eta_rad_LED
Lux_grow_max
soil calibration curve
```

thì:
1. expose trong config;
2. ghi `LITERATURE_PRIOR` hoặc `TO_CALIBRATE`;
3. không hard-code magic number không nguồn.

---

# 30. Luồng provenance hoàn chỉnh

Ví dụ `temperature_inside`:

```text
Open-Meteo T/Radiation/Wind
        +
greenhouse geometry
        +
cover U/transmittance
        +
fan airflow
        +
grow light power
        ↓
E7
        ↓
temperature_inside_true
        ↓
TH10S-B-PE measurement model
        ↓
temperature_inside_sensor
```

Ví dụ `soil_moisture_inside`:

```text
20 L pot
+
substrate params
+
measured emitter flow
+
ET from E4
        ↓
E9
        ↓
theta_true
        ↓
ES-SM-TH-01 calibration
        ↓
soil_moisture_sensor
```

Ví dụ `light_lux_inside`:

```text
Open-Meteo radiation
+
PE transmittance
+
measured grow-light lux gain
        ↓
E10
        ↓
light_lux_inside_true
        ↓
ES-ALS-02 accuracy model
        ↓
light_lux_inside_sensor
```

---

# 31. Nguồn sản phẩm chính

## TH10S-B-PE
https://epcb.vn/products/cam-bien-rs485-modbus-rtu-th10s-b-pe

## ES-SM-TH-01
https://epcb.vn/products/cam-bien-do-do-am-nhiet-do-dat-es-sm-th-01

## ES-ALS-02
https://epcb.vn/products/cam-bien-anh-sang-cong-nghiep-es-als-02-rs485-modbus-rtu

## Pump
https://mlab.vn/3748096-bom-nuoc-chim-mini-dc-6v-18v-550l-h.html

## Fan
https://mlab.vn/4397409-quat-tan-nhiet-danh-cho-raspberry-pi.html

## Waveshare 3-channel RPi Relay Board
https://www.waveshare.com/rpi-relay-board.htm

## 12 V / 2 A adapter
https://epcb.vn/products/nguon-power-ac-adaptor-12v-1-5a-zin

## Adjustable emitter
https://shopee.vn/S%C3%A9t-10-%C4%90%E1%BA%A7u-B%C3%A9c-Nh%E1%BB%8F-Gi%E1%BB%8Dt-T%C6%B0%E1%BB%9Bi-C%C3%A2y-8-Tia-%C4%90i%E1%BB%81u-Ch%E1%BB%89nh-L%C6%B0u-L%C6%B0%E1%BB%A3ng-0-70L-B%C3%A1n-K%C3%ADnh-T%C6%B0%E1%BB%9Bi-0-30cm-Ch%C3%A2n-N%E1%BB%91i-4mm-i.394697078.25389750925

---

# 32. Nguồn thiết kế/horticulture/thermal

## Tomato container size
Oklahoma State University Extension — Container Gardening  
https://extension.okstate.edu/fact-sheets/container-gardening

## Greenhouse/high-tunnel PE cover
Oklahoma State University Extension — High Tunnels  
https://extension.okstate.edu/fact-sheets/high-tunnels

## Greenhouse heat loss / cover thermal resistance
University of Georgia Cooperative Extension — Greenhouses: Heating, Cooling and Ventilation  
https://extension.uga.edu/publications/detail.html?number=B792

## Soil sensor VWC / field-capacity measurement
University of Minnesota Extension — Soil moisture sensors for irrigation scheduling  
https://extension.umn.edu/irrigation/soil-moisture-sensors-irrigation-scheduling

## Greenhouse-cover transmittance
Baneshi et al. (2020), Energy  
https://doi.org/10.1016/j.energy.2020.118535

## Single-PE U-value reference
Discover Sustainability greenhouse case study  
https://doi.org/10.1007/s43621-024-00276-5

---

# 33. Quy tắc cuối cùng cho Codex

Codex MUST:

1. Load all physical parameters from config, not scatter magic numbers in code.
2. Preserve provenance metadata.
3. Keep pump nominal flow separate from actual emitter flow.
4. Keep `physics true state` separate from `sensor observation`.
5. Treat soil-sensor percentage as calibration-dependent.
6. Treat grow-light `18 W` as electrical input only; do not invent PPFD/lux.
7. Use fan 5 m³/h as nominal free-air spec and allow effective-flow calibration.
8. Use `V_g = 0.96 m³`, `pot = 20 L` as baseline project design until physical design changes.
9. If hardware geometry changes, recompute derived parameters rather than manually editing them.
10. Read `GREENHOUSE_PHYSICS_DATASET_KNOWLEDGE.md` for equation definitions and scientific provenance.

---

# 34. Baseline status

At this stage:

```text
Raw Open-Meteo dataset                  DONE
Physics equations E0–E10               DONE
Hardware BOM PA1                       DONE
Hardware → equation mapping            DONE
Baseline one-tomato greenhouse design  DONE
Parameter provenance framework         DONE

Next:
implement configuration + simulator v1
then run short-horizon physics validation
```
