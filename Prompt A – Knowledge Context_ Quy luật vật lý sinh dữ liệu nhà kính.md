# KNOWLEDGE CONTEXT — GREENHOUSE SYNTHETIC DATASET

Bạn đang tham gia một dự án IoT/AI giám sát và điều khiển môi trường nhà kính tại Nha Trang, Khánh Hòa.

Nhiệm vụ sau này là xây dựng dataset synthetic đại diện cho các giá trị mà nhóm cảm biến trong nhà kính có thể đo:

```text
air_temperature_c
air_humidity_pct
soil_moisture_pct
light_lux
```

Dữ liệu thời tiết lịch sử Nha Trang 2018–2025 từ Open-Meteo / ERA5-Seamless được sử dụng làm **external weather drivers**.

Dataset synthetic KHÔNG phải dữ liệu cảm biến thực tế.

Mọi quá trình mô phỏng phải tuân thủ các nguyên tắc vật lý dưới đây.

---

# 1. NGUYÊN TẮC CỐT LÕI

Không sinh 4 biến cảm biến độc lập.

Toàn bộ hệ phải được xem là một **coupled dynamic system**:

```text
OUTDOOR WEATHER
      │
      ├──── Temperature / Humidity
      │
      ├──── Wind
      │
      ├──── Solar radiation
      │
      └──── Atmospheric demand
                │
                ↓
         GREENHOUSE SYSTEM
                │
        ┌───────┼────────┐
        ↓       ↓        ↓
     Thermal  Vapour   Radiation
     balance  balance   transfer
        │       │        │
        └───┬───┘        │
            ↓            ↓
          Crop        Indoor light
            │
       Transpiration
        ↙          ↘
Indoor humidity   Soil water
        │            │
        └──────┬─────┘
               ↓
       greenhouse state
               ↓
         sensor model
               ↓
       sensor measurements
```

Không được dùng một script random riêng cho từng biến.

---

# 2. PHÂN LOẠI BIẾN

Phải phân biệt 5 nhóm.

## A. External weather drivers

Lấy từ API/reanalysis.

Ví dụ:

```text
temperature_2m
relative_humidity_2m
dew_point_2m
surface_pressure

wind_speed_10m
wind_direction_10m
wind_gusts_10m

precipitation
cloud_cover

shortwave_radiation
direct_radiation
diffuse_radiation
direct_normal_irradiance

vapour_pressure_deficit
et0_fao_evapotranspiration

soil_temperature_0_to_7cm
soil_moisture_0_to_7cm
```

Không tự thay đổi dữ liệu raw.

---

## B. Derived physical variables

Được phép tính từ weather drivers bằng công thức vật lý có căn cứ.

Ví dụ:

```text
saturation vapour pressure
actual vapour pressure
humidity ratio
air density
solar position
day/night
incidence angle
```

Derived variable KHÔNG phải synthetic random.

Mỗi derived variable phải có:

```text
formula
inputs
units
source/reference
```

---

## C. Greenhouse/system parameters

Không có trong weather API.

Ví dụ:

```text
greenhouse length
greenhouse width
greenhouse height

floor area
cover area
greenhouse volume

cover material
solar transmittance
direct transmittance
diffuse transmittance
thermal U-value

vent opening area
vent height
vent orientation
discharge coefficient

substrate type
substrate depth
field capacity
wilting point
drainage characteristics

crop type
growth stage
leaf area index
crop/transpiration parameters

pump flow rate
irrigation duration

sensor accuracy
sensor resolution
sensor range
```

Các tham số này phải đến từ một trong:

```text
1. thông số thiết kế thực tế của dự án;
2. datasheet thiết bị/vật liệu;
3. tài liệu/bài báo khoa học;
4. calibration bằng dữ liệu thực;
5. scenario assumption có ghi rõ nếu 1–4 chưa tồn tại.
```

Không được tự sinh một hệ số chỉ vì nó “có vẻ hợp lý”.

---

## D. Dynamic states

Đây là trạng thái của greenhouse thay đổi theo thời gian:

```text
indoor air temperature
indoor water vapour state
soil/substrate water content
possibly cover/soil thermal state
```

State tại `t+1` phải phụ thuộc state tại `t`.

---

## E. Sensor measurements

Sensor measurement KHÔNG đồng nhất với state vật lý lý tưởng.

Dạng tổng quát:

```text
physical state
      ↓
sensor transfer function
      ↓
measurement error
      ↓
recorded sensor value
```

---

# 3. NHIỆT ĐỘ KHÔNG KHÍ — ENERGY BALANCE

Không mô phỏng indoor temperature bằng:

```python
T_inside = T_outside + random_offset
```

Nhiệt độ trong greenhouse phải dựa trên **bảo toàn năng lượng**.

Dạng tổng quát:

```text
C_eff * dT_inside/dt
=
Q_solar
- Q_cover
- Q_ventilation
- Q_latent
+ Q_other
```

Trong đó:

```text
C_eff
=
effective thermal capacitance
```

đại diện cho thermal inertia của greenhouse.

---

## 3.1 Solar heat gain

Dạng khái niệm:

```text
Q_solar
=
transmitted solar radiation
× effective receiving area
× absorbed fraction
```

Input từ weather:

```text
shortwave_radiation
direct_radiation
diffuse_radiation
direct_normal_irradiance
```

Parameters:

```text
cover geometry
cover transmissivity
orientation
roof angle
absorption properties
```

---

## 3.2 Heat transfer through cover

Dạng:

```text
Q_cover
=
U
× A
× (T_inside - T_outside)
```

Trong đó:

```text
U = thermal transmittance
A = greenhouse cover area
```

`U` phải lấy từ material specification/literature/calibration.

---

## 3.3 Ventilation heat exchange

Không giả định ventilation chỉ bằng một hệ số random.

Natural ventilation chịu ảnh hưởng bởi:

```text
wind effect
+
stack/buoyancy effect
```

Dạng tổng quát:

```text
air_exchange_rate
=
f(
    wind_speed,
    indoor-outdoor temperature difference,
    vent area,
    vent height,
    vent geometry,
    discharge coefficient
)
```

Sau đó heat exchange:

```text
Q_ventilation
=
air mass flow
× cp_air
× (T_inside - T_outside)
```

Weather driver quan trọng:

```text
wind_speed_10m
```

---

## 3.4 Latent heat

Crop transpiration và evaporation sử dụng năng lượng để chuyển nước sang hơi.

Do đó:

```text
transpiration ↑
→ latent heat consumption ↑
→ cooling tendency ↑
```

Temperature model và humidity model vì vậy phải coupling.

---

# 4. KHÔNG DÙNG DAY/NIGHT NHƯ MỘT NHIỆT FORCE RIÊNG

Không làm:

```python
if daytime:
    temperature += constant
```

Chu kỳ ngày/đêm đã phản ánh chủ yếu trong:

```text
solar radiation
solar position
outside temperature
```

`is_day` hoặc timestamp chỉ dùng cho:

```text
validation
solar geometry
control policy
analysis
```

Không double-count solar heating.

---

# 5. ĐỘ ẨM KHÔNG KHÍ — WATER VAPOUR MASS BALANCE

Không ưu tiên mô phỏng trực tiếp:

```text
RH(t+1)
```

Thay vào đó mô phỏng một trạng thái vật lý của hơi nước, ví dụ:

```text
vapour density
vapour pressure
absolute humidity
humidity ratio
```

Sau đó tính RH từ trạng thái hơi nước và temperature.

Dạng tổng quát:

```text
V * d(rho_v_inside)/dt
=
E_crop
+ E_soil
- E_ventilation
- E_condensation
```

Trong đó:

```text
E_crop         = crop transpiration
E_soil         = soil/substrate evaporation
E_ventilation  = water vapour exchanged with outside
E_condensation = condensation on greenhouse surfaces
```

---

# 6. QUAN HỆ TEMPERATURE – RH

Relative humidity phải được tính dựa trên saturation vapour pressure.

Dạng:

```text
RH
=
actual vapour pressure
/
saturation vapour pressure(T)
× 100
```

Do đó nếu lượng hơi nước gần như giữ nguyên:

```text
T ↑
→ saturation vapour pressure ↑
→ RH ↓
```

Không cần ép artificial negative correlation bằng random rule.

---

# 7. CROP TRANSPIRATION

Crop transpiration là một coupling quan trọng giữa:

```text
radiation
temperature
humidity/VPD
air movement
crop state
soil water
```

Dạng khái niệm:

```text
Radiation
   │
   ↓
Crop energy
   │
VPD + aerodynamic resistance
   │
   ↓
Transpiration
```

Transpiration tạo ra:

```text
soil water ↓
indoor water vapour ↑
latent cooling ↑
```

Không được sinh ba hiệu ứng này độc lập.

Nếu sử dụng Penman-Monteith/Stanghellini hoặc model tương tự:

- ghi rõ công thức;
- ghi rõ source;
- ghi rõ parameter nào là crop-specific;
- không tự đặt LAI/crop coefficient mà không có nguồn.

---

# 8. VPD

VPD có thể:

```text
1. lấy trực tiếp từ API;
2. tính lại từ temperature + RH để validation.
```

Không coi VPD là biến hoàn toàn độc lập.

VPD có thể được dùng làm atmospheric demand driver cho transpiration.

---

# 9. ET0

`et0_fao_evapotranspiration` từ Open-Meteo là reference evapotranspiration.

Không được đồng nhất:

```text
ET0 = greenhouse crop transpiration
```

ET0 chỉ là:

```text
external climatic water-demand indicator
```

Nếu dùng cho cây greenhouse phải có một transformation/model có căn cứ.

---

# 10. SOIL/SUBSTRATE MOISTURE — WATER BALANCE

Soil moisture là state có memory.

Dạng:

```text
W(t+1)
=
W(t)
+ irrigation
+ effective water input
- crop uptake/transpiration
- soil evaporation
- drainage
```

Trong greenhouse có mái kín thông thường:

```text
direct rainfall input ≈ 0
```

trừ khi thiết kế cho phép nước mưa đi vào.

---

# 11. API SOIL MOISTURE KHÔNG PHẢI GREENHOUSE SOIL MOISTURE

`soil_moisture_0_to_7cm` của ERA5-Land là outdoor/reanalysis soil state.

Không được làm:

```python
greenhouse_soil_moisture =
    ERA5_soil_moisture + noise
```

Nó chỉ có thể đóng vai trò:

```text
regional soil-climate context
initialization reference
validation context
```

Greenhouse substrate water phải được mô phỏng bằng water balance riêng.

---

# 12. IRRIGATION

Irrigation là actuator/input, không phải weather variable.

Nguồn ưu tiên:

```text
pump flow rate
irrigation duration
actual control policy
```

Nếu chưa tồn tại thì có thể xây:

```text
synthetic irrigation scenario/policy
```

nhưng phải ghi rõ là synthetic control assumption.

Irrigation event phải tạo:

```text
soil water ↑
```

theo dynamics có giới hạn bởi:

```text
field capacity
substrate capacity
drainage
```

---

# 13. DRAINAGE

Không random drainage độc lập.

Drainage phụ thuộc:

```text
soil/substrate type
water content
field capacity
porosity
hydraulic/drainage characteristics
container geometry
```

Baseline đơn giản có thể sử dụng threshold-based/percolation model nếu có nguồn.

---

# 14. ÁNH SÁNG — RADIATIVE TRANSFER, KHÔNG PHẢI FIRST-ORDER DYNAMICS

Natural indoor light không cần một state có thermal inertia tương tự temperature.

Mô hình cơ bản:

```text
outside radiation(t)
        ↓
greenhouse cover
        ↓
indoor radiation(t)
```

Dạng:

```text
I_inside
=
tau_direct(angle) * I_direct
+
tau_diffuse * I_diffuse
```

Có thể cần:

```text
DNI
DHI
solar position
roof orientation
roof tilt
cover optical properties
```

---

# 15. DIRECT VÀ DIFFUSE RADIATION KHÔNG NÊN GỘP VÔ ĐIỀU KIỆN

Cover có thể truyền direct và diffuse radiation khác nhau.

Nếu geometry đủ thông tin, sử dụng:

```text
direct_normal_irradiance
+
solar incidence angle
```

để xác định direct radiation trên surface.

Không chỉ sử dụng:

```text
shortwave_radiation × arbitrary_constant
```

nếu có thể mô hình chi tiết hơn.

---

# 16. W/M² VÀ LUX KHÔNG TƯƠNG ĐƯƠNG

Không áp dụng vô căn cứ:

```python
lux = radiation_wm2 * constant
```

Lux phụ thuộc spectral luminous efficacy.

Pipeline đúng:

```text
solar irradiance
      ↓
greenhouse optical transmission
      ↓
indoor irradiance
      ↓
spectral/luminous-efficacy approximation
      ↓
lux
```

Nếu chưa có spectral data:

- sử dụng approximation có nguồn;
- ghi rõ limitation;
- không gọi lux là physical ground truth.

Ưu tiên calibration bằng sensor thật khi có dữ liệu.

---

# 17. SENSOR MODEL

Phải tách:

```text
PROCESS MODEL
```

và:

```text
MEASUREMENT MODEL
```

Dạng state-space:

```text
x(t+1) = f(x(t), u(t), d(t)) + w(t)
y(t)   = h(x(t)) + v(t)
```

Trong đó:

```text
x = physical state
u = actuator/control
d = external weather disturbance

w = process/model error
v = sensor measurement error
```

---

# 18. SENSOR NOISE

Sensor error phải ưu tiên lấy từ:

```text
datasheet accuracy
datasheet resolution
datasheet measuring range
calibration
```

Không được viết:

```python
noise = normal(0, 0.5)
```

nếu `0.5` không có căn cứ.

Resolution/quantization cũng cần mô phỏng nếu phù hợp.

---

# 19. PROCESS NOISE

Không tự đặt process noise chỉ để dữ liệu nhìn “thật”.

Baseline ưu tiên:

```text
process_noise = 0
```

nếu chưa có dữ liệu thực để calibrate residual.

Sau này:

```text
residual
=
actual measurement
-
model prediction
```

có thể dùng để estimate process uncertainty.

---

# 20. SOURCE HIERARCHY

Mọi parameter phải được gắn source theo thứ tự ưu tiên:

```text
LEVEL 1
Actual project hardware/design specification

LEVEL 2
Manufacturer datasheet

LEVEL 3
Authoritative physical/agricultural standard

LEVEL 4
Peer-reviewed scientific literature

LEVEL 5
Calibration from real experimental data

LEVEL 6
Explicit scenario assumption
```

LEVEL 6 chỉ được dùng khi các level trước không khả dụng.

Mọi Level-6 assumption phải xuất hiện trong metadata.

---

# 21. KHÔNG ĐƯỢC HALLUCINATE PARAMETER

Nếu cần:

```text
cover transmittance
U-value
LAI
field capacity
vent coefficient
pump flow
sensor accuracy
```

mà chưa biết:

KHÔNG được tự invent.

Phải đánh dấu:

```text
REQUIRED_PARAMETER_MISSING
```

và tìm nguồn trước.

---

# 22. DIMENSIONAL CONSISTENCY

Mọi phương trình trước khi chạy phải kiểm tra:

```text
units
dimensions
timestep
```

Không trộn:

```text
hour
second

km/h
m/s

mm/hour
mm/timestep

W/m²
J/m²
```

mà không convert rõ ràng.

Tất cả model nội bộ nên chọn một hệ đơn vị nhất quán.

---

# 23. COUPLING BẮT BUỘC

Các quan hệ sau phải xuất hiện tự nhiên từ model hoặc ít nhất được kiểm tra trong validation.

### Solar

```text
solar radiation ↑
→ indoor irradiance tendency ↑
→ solar heat gain tendency ↑
```

### Wind

```text
wind ↑
→ natural ventilation potential ↑
→ indoor climate tends toward outdoor climate
```

### Temperature/RH

```text
T ↑ while vapour mass unchanged
→ RH ↓
```

### Transpiration

```text
radiation/VPD ↑
→ transpiration demand ↑
```

trong phạm vi cây chưa water-stressed.

### Transpiration effects

```text
transpiration ↑
→ soil water ↓
→ indoor vapour ↑
→ latent cooling ↑
```

### Irrigation

```text
irrigation
→ substrate water ↑
```

### Water stress

```text
soil moisture very low
→ transpiration ability may decrease
```

Không áp dụng relationship đơn giản bên ngoài miền vật lý phù hợp.

---

# 24. KHÔNG DOUBLE-COUNT PHYSICS

Không dùng đồng thời hai term mô tả cùng một hiện tượng nếu chưa chứng minh chúng khác nhau.

Ví dụ không dùng:

```text
exchange_with_outdoor
+
natural_heat_loss
```

nếu cả hai đều thực chất là ventilation/convection loss.

Term phải có tên vật lý rõ:

```text
solar gain
cover conduction/convection
ventilation
latent heat
ground exchange
```

---

# 25. MODEL COMPLEXITY

Không cần xây CFD hoặc greenhouse digital twin cực kỳ phức tạp.

Ưu tiên:

```text
physics-inspired
reduced-order
interpretable
calibratable
```

Mỗi complexity thêm vào phải có lý do.

Nếu một physical mechanism không thể parameterize đáng tin ở hiện tại:

- ghi limitation;
- đơn giản hóa;
- không invent.

---

# 26. FINAL MODEL PHILOSOPHY

Mục tiêu không phải:

> tạo dữ liệu nhìn giống thật.

Mục tiêu là:

> tạo dữ liệu có thể truy ngược từng quy luật và từng parameter về nguồn hoặc assumption rõ ràng.

Dataset tốt phải cho phép trả lời:

```text
Tại sao giá trị này thay đổi?
```

bằng một chuỗi causal/physical rõ ràng.

Không chỉ trả lời:

```text
vì random generator tạo ra như vậy.
```