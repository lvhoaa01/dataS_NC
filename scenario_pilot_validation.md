# Scenario Pilot Validation

Final status: `PASS`

## 1. Baseline

- Source parameter set: `smartgarden_pa1_v1_1_rootzone_prior`.
- Weather: `2024-06-01T00:00` through `2024-06-30T23:00`; hash `2d014eb72e33a8686c01be5f0b699b38467158691ac7bc2db166853cb28b46de`.
- Baseline reproduction: `PASS`; max non-identity difference `0.000e+00`.
- No random weather, controller change or sensor uncertainty was introduced.

## 2. Parameter uncertainty table

| Axis | Exploratory range | Pilot result | Final status |
|---|---|---|---|
| `effective_air_thermal_capacity` | `40000.0` to `90000.0` | Both 40 and 90 kJ/K passed but all five sensitivity deltas stayed below the LOW_SENSITIVITY thresholds. | `LOW_SENSITIVITY` |
| `passive_discharge_coefficient` | `0.2` to `0.7` | Cd=0.20 PASS; mean RH delta 3.536 percentage points. | `APPROVED_FOR_SAMPLING` |
| `crop_et_response_scale` | `0.7` to `1.3` | f_ET=1.30 PASS; mean theta delta=-0.01958. | `APPROVED_FOR_SAMPLING` |
| `soil_effective_thermal_capacity` | `60000.0` to `120000.0` | Cs=60 kJ/K PASS; delta Tsoil,max=0.743 C. | `APPROVED_FOR_SAMPLING` |
| `soil_solar_coupling` | `0.1` to `0.3` | eta=0.10 PASS; eta=0.30 FAIL with Tsoil,max=40.340 C. | `RANGE_TOO_WIDE` |
| `drainage_coefficient` | `2.31481481481481e-05` to `9.25925925925926e-05` | inactive/not varied | `LOW_SENSITIVITY` |
| `irrigation_effective_flow` | `1.38888888888889e-06` to `4.16666666666667e-06` | Both 5 and 15 L/h boundaries passed; mean theta deltas were 0.03136, -0.03016. | `APPROVED_FOR_SAMPLING` |

## 3. Scenario definitions

| Scenario | Changed axis | Config change | Seed |
|---|---|---|---:|
| `scenario_000_baseline` | `none` | none | 20240600 |
| `scenario_001_low_air_thermal_inertia` | `effective_air_thermal_capacity` | greenhouse.effective_thermal_capacity_j_k: 60000.0 -> 40000.0 | 20240601 |
| `scenario_002_high_air_thermal_inertia` | `effective_air_thermal_capacity` | greenhouse.effective_thermal_capacity_j_k: 60000.0 -> 90000.0 | 20240602 |
| `scenario_003_low_passive_ventilation` | `passive_discharge_coefficient` | ventilation.discharge_coefficient: 0.65 -> 0.2 | 20240603 |
| `scenario_004_high_irrigation_flow` | `irrigation_effective_flow` | irrigation.effective_flow_m3_s: 2.7778e-06 -> 4.16666666666667e-06 | 20240604 |
| `scenario_005_low_soil_solar_coupling` | `soil_solar_coupling` | soil_thermal.solar_absorption_fraction: 0.2 -> 0.1 | 20240605 |
| `scenario_006_high_soil_solar_coupling` | `soil_solar_coupling` | soil_thermal.solar_absorption_fraction: 0.2 -> 0.3 | 20240606 |
| `scenario_007_low_soil_thermal_capacity` | `soil_effective_thermal_capacity` | soil_thermal.effective_heat_capacity_j_k: 90000.0 -> 60000.0 | 20240607 |
| `scenario_008_low_irrigation_flow` | `irrigation_effective_flow` | irrigation.effective_flow_m3_s: 2.7778e-06 -> 1.38888888888889e-06 | 20240608 |
| `scenario_009_high_et_response` | `crop_et_response_scale` | crop.transpiration_radiation_coefficient: 1.5e-07 -> 1.95e-07; crop.transpiration_vpd_coefficient: 2e-06 -> 2.6e-06 | 20240609 |

## 4. Validation results

| Scenario | Framework | Causal | Balance | Stability | Special guards | Final | Condition |
|---|---|---|---|---|---|---|---|
| `scenario_000_baseline` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_001_low_air_thermal_inertia` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_002_high_air_thermal_inertia` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_003_low_passive_ventilation` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `extreme_valid` |
| `scenario_004_high_irrigation_flow` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_005_low_soil_solar_coupling` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_006_high_soil_solar_coupling` | `PASS` | `PASS` | `PASS` | `PASS` | `FAIL` | `FAIL` | `invalid` |
| `scenario_007_low_soil_thermal_capacity` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `extreme_valid` |
| `scenario_008_low_irrigation_flow` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |
| `scenario_009_high_et_response` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `PASS` | `stressful` |

## 5. State ranges per scenario

| Scenario | T air C | RH % | T soil C | theta m3/m3 | lux | RH=100 rows / longest h |
|---|---|---|---|---|---|---|
| `scenario_000_baseline` | 25.103..39.600 | 45.733..100.000 | 29.440..37.565 | 0.201686..0.407252 | 0.0..89564.3 | 1 / 1 |
| `scenario_001_low_air_thermal_inertia` | 25.074..39.648 | 45.519..98.187 | 29.437..37.570 | 0.201656..0.407254 | 0.0..89564.3 | 0 / 0 |
| `scenario_002_high_air_thermal_inertia` | 25.220..39.492 | 45.979..100.000 | 29.444..37.559 | 0.201744..0.407248 | 0.0..89564.3 | 4 / 1 |
| `scenario_003_low_passive_ventilation` | 25.119..39.797 | 50.088..100.000 | 29.440..37.634 | 0.202219..0.407308 | 0.0..89564.3 | 27 / 3 |
| `scenario_004_high_irrigation_flow` | 25.094..39.229 | 48.932..100.000 | 29.440..37.451 | 0.227216..0.411419 | 0.0..89564.3 | 5 / 2 |
| `scenario_005_low_soil_solar_coupling` | 25.083..39.567 | 45.814..100.000 | 29.345..34.797 | 0.201719..0.407252 | 0.0..89564.3 | 2 / 1 |
| `scenario_006_high_soil_solar_coupling` | 25.123..39.633 | 45.653..100.000 | 29.442..40.340 | 0.201653..0.407252 | 0.0..89564.3 | 1 / 1 |
| `scenario_007_low_soil_thermal_capacity` | 25.098..39.607 | 45.726..100.000 | 29.368..38.307 | 0.201686..0.407252 | 0.0..89564.3 | 1 / 1 |
| `scenario_008_low_irrigation_flow` | 25.113..39.962 | 42.723..100.000 | 29.440..37.676 | 0.176475..0.403086 | 0.0..89564.3 | 1 / 1 |
| `scenario_009_high_et_response` | 25.103..39.664 | 45.314..100.000 | 29.439..37.580 | 0.186299..0.406945 | 0.0..89564.3 | 6 / 2 |

## 6. Sensitivity findings

| Scenario | dTair max | dTair mean | dRH mean | dTsoil max | dtheta mean | Class |
|---|---:|---:|---:|---:|---:|---|
| `scenario_001_low_air_thermal_inertia` | 0.0478 | -0.0003 | -0.1552 | 0.0057 | -0.000056 | `LOW_SENSITIVITY` |
| `scenario_002_high_air_thermal_inertia` | -0.1085 | -0.0000 | 0.2157 | -0.0063 | 0.000091 | `LOW_SENSITIVITY` |
| `scenario_003_low_passive_ventilation` | 0.1970 | 0.0563 | 3.5358 | 0.0690 | 0.001078 | `MATERIAL` |
| `scenario_004_high_irrigation_flow` | -0.3716 | -0.0991 | 1.7175 | -0.1138 | 0.031363 | `MATERIAL` |
| `scenario_005_low_soil_solar_coupling` | -0.0329 | -0.0270 | 0.1391 | -2.7677 | 0.000042 | `MATERIAL` |
| `scenario_006_high_soil_solar_coupling` | 0.0328 | 0.0270 | -0.1331 | 2.7749 | -0.000042 | `HIGH_SENSITIVITY_INVALID_BOUNDARY` |
| `scenario_007_low_soil_thermal_capacity` | 0.0064 | 0.0008 | 0.0015 | 0.7426 | -0.000004 | `MATERIAL` |
| `scenario_008_low_irrigation_flow` | 0.3612 | 0.0988 | -1.5925 | 0.1112 | -0.030163 | `MATERIAL` |
| `scenario_009_high_et_response` | 0.0636 | -0.0082 | 0.2521 | 0.0149 | -0.019580 | `MATERIAL` |

Highest accepted impact axes: `soil_solar_coupling`, `irrigation_effective_flow`, `passive_discharge_coefficient`.

Low-sensitivity scenarios: `scenario_001_low_air_thermal_inertia`, `scenario_002_high_air_thermal_inertia`.

## 7. Invalid regions

- `eta_s >= 0.30 under the current E8 companion priors`: eta_s=0.30 produced Tsoil,max=40.340 C and failed the unchanged 40 C guard. eta_s=0.60 produced 48.669 C in V1.0. This is a rejected parameter region, not a deleted outlier.

## 8. Extreme-but-valid regions

- `scenario_003_low_passive_ventilation`: Tsoil,max=37.634 C, RH saturation=27 rows; all physics gates passed.
- `scenario_007_low_soil_thermal_capacity`: Tsoil,max=38.307 C, RH saturation=1 rows; all physics gates passed.

## 9. Parameters approved for full sampling

- `passive_discharge_coefficient`: `0.2` to `0.65`, `triangular`; constraint: use documented coupled-group rule.
- `soil_solar_coupling`: `0.1` to `0.2`, `triangular`; constraint: use documented coupled-group rule.
- `soil_effective_thermal_capacity`: `60000.0` to `90000.0`, `triangular`; constraint: Do not independently combine with uncalibrated h_as, U_s or T_base.
- `irrigation_effective_flow`: `1.38888888888889e-06` to `4.16666666666667e-06`, `triangular`; constraint: Pump pulse schedule stays fixed.
- `crop_et_response_scale`: `1.0` to `1.3`, `triangular`; constraint: Apply the same scale to k_R and k_D; crop area stays fixed.

## 10. Parameters fixed at baseline

- `effective_air_thermal_capacity`, `cover_shortwave_transmittance`, `cover_visible_transmittance`, `cover_u_value`, `passive_leakage`, `wind_effect_coefficient`, `crop_effective_area`, `air_soil_heat_transfer`, `soil_base_loss`, `drainage_coefficient`, `soil_moisture_closure_bounds`, `luminous_efficacy_profile`.

## 11. Parameters requiring real calibration

- `air_solar_absorption_fraction`, `fan_effective_flow_factor`, `soil_base_temperature`, `soil_stress_profile`, `grow_light_response`.

## 12. Recommended next step

Use only `approved_sampling_space` for a small multi-axis interaction pilot before full 2018-2025 generation. Draws must obey coupled-group constraints; obtain emitter-flow, installed-fan, substrate and E8 measurements first where feasible.

## Verification passes

- Pass 1 provenance: `PASS` (all varied axes have source and range basis).
- Pass 2 scenario design: `PASS` (fixed hardware/controller/weather unchanged; ET coefficients use one coupled axis).
- Pass 3 physics: `PASS` for 9 accepted scenarios; 1 intentional boundary probe rejected.
- Pass 4 sensitivity/boundary: `PASS` (low-impact and invalid regions retained and classified).
- Pass 5 deployment: `PASS` (existing ML schema 720x9; physics/weather feature count 0; no scenario ML CSV generated).
