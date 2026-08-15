# SmartGarden ML Data Contract

Version: `1.0`

Status: `LOCKED_BASELINE`

This document is the source of truth for all future preprocessing and model-training code. It
defines the baseline feature set that is available both in synthetic training data and on the PA1
Raspberry Pi deployment. Changing this contract requires an explicit version change and a new
deployment-availability audit.

## 1. Non-negotiable invariant

```text
training features subset-of features available at deployment
```

For the baseline model:

```text
SyntheticInputSchema == RealDeploymentInputSchema
```

Weather API fields and internal physics diagnostics are not baseline model inputs.

## 2. Data-layer separation

### Physics master

The physics master is a simulation trace. It may contain 30 or more columns covering:

```text
weather forcing
actuator controls
physics true states
derived outputs
intermediate diagnostics
QA/reference fields
scientific provenance
```

It exists for validation, debugging, equation auditing, conservation checks, and provenance. It is
not passed directly to a GRU or LSTM.

### Canonical ML dataset

The canonical ML dataset contains only the five PA1 sensor channels, three actuator states, and a
timestamp. It exists for sequence preprocessing, synthetic pretraining, later real-data fine-tuning,
and deployment inference.

## 3. Baseline vectors

Sensor state at time `t`:

```text
S_t = [
  air_temperature,
  air_humidity,
  soil_temperature,
  soil_moisture,
  light_lux
]
```

Actuator vector at time `t`:

```text
U_t = [
  pump_state,
  fan_state,
  grow_light_state
]
```

Baseline model input:

```text
X_t = [S_t, U_t]
```

There are exactly eight numerical model features per timestep.

## 4. Baseline transition target

The intended supervised transition is:

```text
X_(t-k+1:t) -> S_(t+1)
```

The five target variables are:

```text
air_temperature_(t+1)
air_humidity_(t+1)
soil_temperature_(t+1)
soil_moisture_(t+1)
light_lux_(t+1)
```

Actuator states are inputs, never targets. The canonical time-series CSV does not contain prefixed
`target_*` columns. Temporal shifting and sequence windows belong to the future training pipeline.

## 5. Canonical storage schema

The canonical CSV column order is fixed:

| Column | Unit/encoding | Model role | PA1 deployment source |
|---|---|---|---|
| `timestamp` | local ISO-8601, Asia/Ho_Chi_Minh | metadata/index | Raspberry Pi clock |
| `air_temperature` | degC | feature and future target | TH10S-B-PE temperature |
| `air_humidity` | percent RH | feature and future target | TH10S-B-PE RH |
| `soil_temperature` | degC | feature and future target | ES-SM-TH-01 temperature |
| `soil_moisture` | m3/m3 VWC | feature and future target | calibrated ES-SM-TH-01 moisture mapping |
| `light_lux` | lux | feature and future target | ES-ALS-02 illuminance |
| `pump_state` | binary 0/1 | feature | RPi relay CH1 state |
| `fan_state` | binary 0/1 | feature | RPi relay CH2 state |
| `grow_light_state` | binary 0/1 | feature | RPi relay CH3 state |

The 30-day canonical artifact has exactly 720 rows and 9 columns.

Optional fields such as `simulation_id`, `parameter_set_id`, and `source_type` belong in a sidecar
manifest or a separately versioned extended dataset. They are never model features.

## 6. Current synthetic column mapping

The builder resolves each sensor channel semantically. It prefers a validated sensor observation,
then falls back to its physics true-state counterpart:

| Canonical field | Preferred source | Current fallback |
|---|---|---|
| `air_temperature` | `temperature_inside_sensor` | `temperature_inside_true` |
| `air_humidity` | `humidity_inside_sensor` | `humidity_inside_true` |
| `soil_temperature` | `soil_temperature_inside_sensor` | `soil_temperature_inside_true` |
| `soil_moisture` | `soil_moisture_inside_sensor` | `soil_moisture_inside_true` |
| `light_lux` | `light_lux_inside_sensor` | `light_lux_inside_true` |

Sensor columns may be selected only when all five exist and the sensor-model validation status is
`PASS`. A mixture of sensor and true-state channels is forbidden.

The current V1 master has no validated five-channel sensor representation. Therefore:

```text
observation_mode = physics_true_state
sensor_noise_enabled = false
```

These synthetic values are latent physics states/outputs, not claims of measured sensor data.

## 7. Real soil-moisture adapter requirement

The ES-SM-TH-01 product returns a moisture percentage, while E9 uses volumetric water content. The
following shortcut is forbidden before substrate calibration:

```text
sensor_percent / 100 == soil_moisture_vwc
```

Real deployment ingestion must apply a calibrated mapping at the fixed probe position:

```text
ES-SM-TH moisture percent -> calibrated substrate mapping -> soil_moisture in m3/m3
```

Until this mapping is measured, the baseline schema is deployment-available and structurally
compatible, but real/synthetic numerical equivalence for `soil_moisture` remains `TO_CALIBRATE`.

## 8. Feature policy

### Allowed baseline model features

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

### Metadata: never a model feature

```text
timestamp
simulation_id
parameter_set_id
source_type
```

### Physics-only: forbidden baseline model features

```text
vapor_density_inside
vpd_inside
evapotranspiration_rate
ventilation_rate
water_stress_coefficient
condensation_rate
drainage_rate
air_density
solar_inside
internal heat fluxes
```

These fields remain in the physics master for scientific audit only.

### External weather: not baseline

```text
temperature_outside
humidity_outside
shortwave_radiation
direct_radiation
diffuse_radiation
wind_speed
surface_pressure
dew_point_outside
vpd_outside_reference
et0_outside_reference
external_soil_temperature_context
external_soil_moisture_context
```

An experimental weather-assisted model requires a separate contract and proof that the same weather
service is available and reliable at inference time.

## 9. Synthetic-to-real mapping

| ML feature | Synthetic representation | Real PA1 representation |
|---|---|---|
| `air_temperature` | E7 true state, later TH10S sensor model | TH10S-B-PE temperature |
| `air_humidity` | E6 derived true output, later TH10S sensor model | TH10S-B-PE RH |
| `soil_temperature` | E8 true state, later ES-SM-TH sensor model | ES-SM-TH-01 temperature |
| `soil_moisture` | E9 VWC true state, later calibrated sensor model | calibrated ES-SM-TH-01 moisture |
| `light_lux` | E10 true output, later ES-ALS sensor model | ES-ALS-02 lux |
| `pump_state` | deterministic control state | RPi relay CH1 state |
| `fan_state` | deterministic control state | RPi relay CH2 state |
| `grow_light_state` | deterministic control state | RPi relay CH3 state |

## 10. Architecture lock

```text
TRAINING DATA GENERATION
========================

Open-Meteo
    -> Physics Simulator E0-E10
    -> Physics Master
    -> Sensor Representation
    -> Deployment-aligned ML Dataset
    -> GRU / LSTM
```

```text
REAL DEPLOYMENT
===============

TH10S-B-PE
ES-SM-TH-01
ES-ALS-02
RPi actuator states
    -> SAME 8 FEATURES
    -> GRU / LSTM
```

## 11. Builder acceptance checks

The canonical builder must fail without writing/replacing its output unless all checks pass:

```text
physics-master validation status == PASS
rows == 720
timestamps continuous and unique
no missing/non-finite canonical values
exact canonical column order
actuator states in {0, 1}
one consistent observation mode across all five sensor channels
no physics-only feature
no external-weather feature
```

The builder writes atomically. A validation failure must not leave a partially updated canonical CSV.

## 12. Out-of-scope operations

This contract does not authorize model training, sequence-window creation, scaling, normalization,
train/test splitting, full-period generation, Monte Carlo scenarios, or real-data fine-tuning.
