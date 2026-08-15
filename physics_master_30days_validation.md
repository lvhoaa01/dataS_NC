# Physics Master 30-Day Validation

Final status: `PASS`

## 1. Dataset inspected

- File: `outputs\greenhouse_simulation_30days.csv`
- Shape: `720 rows x 33 columns`
- Window: `2024-06-01T00:00` through `2024-06-30T23:00`
- Missing/non-finite/duplicates/gaps: `0/0/0/0`
- SHA-256: `4a5fef1181266f150a18a9b6bf81eafcc447c830bfc99ad4b7fba8b54596ab07`

## 2. Schema

- **WEATHER:** `temperature_outside`, `humidity_outside`, `shortwave_radiation`, `direct_radiation`, `diffuse_radiation`, `wind_speed`, `surface_pressure`
- **ACTUATOR:** `pump_state`, `fan_state`, `grow_light_state`, `vent_state`
- **PHYSICS TRUE STATE:** `temperature_inside_true`, `vapor_density_inside_true`, `soil_temperature_inside_true`, `soil_moisture_inside_true`
- **DERIVED OUTPUT:** `humidity_inside_true`, `light_lux_inside_true`
- **PHYSICS DIAGNOSTIC:** `vpd_inside`, `solar_inside`, `ventilation_rate_m3_s`, `evapotranspiration_rate_kg_s`, `water_stress_coefficient`, `condensation_rate_kg_s`, `drainage_rate_m3_s`, `air_density`
- **QA / REFERENCE:** `dew_point_outside`, `vpd_outside_reference`, `et0_outside_reference`, `external_soil_temperature_context`, `external_soil_moisture_context`
- **METADATA:** `timestamp`, `simulation_id`, `parameter_set_id`

## 3. State statistics

| Field | Min | Max | Mean | Median | Std | P01 | P05 | P95 | P99 |
|---|---|---|---|---|---|---|---|---|---|
| temperature_inside_true | 25.103054 | 39.600353 | 31.051457 | 30.108020 | 3.261178 | 26.233071 | 26.986528 | 37.510358 | 38.774258 |
| humidity_inside_true | 45.733457 | 100.000000 | 76.501764 | 79.514273 | 12.838820 | 47.800997 | 51.218828 | 92.855916 | 96.843042 |
| soil_temperature_inside_true | 29.439865 | 37.564821 | 33.979937 | 34.280040 | 1.864017 | 29.586717 | 30.932717 | 36.624290 | 37.287696 |
| soil_moisture_inside_true | 0.201686 | 0.407252 | 0.243136 | 0.226797 | 0.046311 | 0.202806 | 0.208216 | 0.366567 | 0.399730 |
| light_lux_inside_true | 0 | 89564.340800 | 23220.416364 | 2648.553600 | 29279.974331 | 0 | 0 | 81116.993760 | 86934.950784 |
| ventilation_rate_m3_s | 7.230421e-04 | 0.008036 | 0.003003 | 0.002362 | 0.001425 | 0.001110 | 0.001450 | 0.005556 | 0.006977 |
| evapotranspiration_rate_kg_s | 2.443761e-08 | 3.759856e-05 | 5.264770e-06 | 8.784226e-07 | 7.407549e-06 | 3.387585e-08 | 1.042516e-07 | 2.060071e-05 | 3.365791e-05 |
| vpd_inside | 0 | 3.837910 | 1.181488 | 0.882859 | 0.878297 | 0.109010 | 0.268038 | 3.079875 | 3.596566 |
| condensation_rate_kg_s | 0 | 1.253006e-06 | 3.299024e-09 | 0 | 5.406040e-08 | 0 | 0 | 0 | 0 |
| water_stress_coefficient | 0.319051 | 1.000000 | 0.542022 | 0.474055 | 0.199306 | 0.325962 | 0.359358 | 1.000000 | 1.000000 |

## 4. Temperature analysis

- Largest hourly rise: `2.642 degC` at `2024-06-16T10:00`.
- Largest hourly fall: `-3.068 degC` at `2024-06-21T14:00`.
- Mean indoor day/night temperature: `32.834/28.861 degC`.
- Fan ON hourly rows: `281`. Controlled fan cooling test: `PASS`.
- No unexplained one-hour numerical spike was found.

## 5. Humidity analysis

- RH=100% rows: `1` (`0.139%`).
- Longest saturation run: `1 hour(s)`.
- Classification: `SPARSE_PHYSICAL_SATURATION_CLOSURE`.
- Saturation excess is recorded as condensation mass and remains in the vapor audit.

## 6. Soil temperature analysis

- Maximum: `37.565 degC` at `2024-06-15T17:00`.
- Classification: `VALID_PHYSICAL_EXTREME_WITH_CALIBRATION_RISK`.
- Peak E8 terms: air `-2.271 W`, solar `2.163 W`, base loss `1.494 W`, net `-1.602 W`.
- Instantaneous peak-state tendency: `-0.064 degC/h`.
- Fix applied: Kept E8 unchanged; revised eta_s to an explicitly uncalibrated effective bulk root-zone coupling prior of 0.2 and versioned the parameter set V1.1.
- The state is not clipped. Its remaining high-end magnitude is an explicit E8 calibration risk.
- Scientific context: tomato studies have tested root-zone regimes up to 36 degC and report strong growth sensitivity; a separate tropical study identified 25 degC as the best tested root-zone treatment. V1.1 is therefore a defensible dynamics trace, not a calibrated prototype-temperature claim ([Scientia Horticulturae](https://doi.org/10.1016/0304-4238(84)90027-X); [Universiti Putra Malaysia](https://psasir.upm.edu.my/id/eprint/34030/)).

### Plus/minus 6 hours around soil maximum

| Timestamp | T out | T in | T soil | Solar | Q air | Q solar | Q base | Q net | Fan |
|---|---|---|---|---|---|---|---|---|---|
| 2024-06-15T11:00 | 35.100000 | 37.777665 | 35.837763 | 700.400000 | 1.097208 | 9.903656 | 1.249660 | 9.751205 | 1 |
| 2024-06-15T12:00 | 35.800000 | 38.775185 | 36.250548 | 760.750000 | 1.427934 | 10.757005 | 1.308028 | 10.876912 | 1 |
| 2024-06-15T13:00 | 36.200000 | 39.222501 | 36.669888 | 703.800000 | 1.443758 | 9.951732 | 1.367322 | 10.028167 | 1 |
| 2024-06-15T14:00 | 36.000000 | 39.198722 | 37.069266 | 716.550000 | 1.204420 | 10.132017 | 1.423794 | 9.912643 | 1 |
| 2024-06-15T15:00 | 33.900000 | 37.376693 | 37.399840 | 559.300000 | -0.013092 | 7.908502 | 1.470537 | 6.424873 | 1 |
| 2024-06-15T16:00 | 32.600000 | 35.020114 | 37.563236 | 334.050000 | -1.438389 | 4.723467 | 1.493642 | 1.791436 | 1 |
| 2024-06-15T17:00 | 32.300000 | 33.548955 | 37.564821 | 153.000000 | -2.271374 | 2.163420 | 1.493866 | -1.601820 | 1 |
| 2024-06-15T18:00 | 31.600000 | 32.399839 | 37.460443 | 51.850000 | -2.862277 | 0.733159 | 1.479107 | -3.608225 | 1 |
| 2024-06-15T19:00 | 30.800000 | 31.310284 | 37.291180 | 0 | -3.382795 | 0 | 1.455173 | -4.837968 | 1 |
| 2024-06-15T20:00 | 30.100000 | 30.500627 | 37.090811 | 0 | -3.727408 | 0 | 1.426841 | -5.154249 | 0 |
| 2024-06-15T21:00 | 29.800000 | 30.038216 | 36.881698 | 0 | -3.870674 | 0 | 1.397272 | -5.267946 | 0 |
| 2024-06-15T22:00 | 29.400000 | 29.664183 | 36.669827 | 0 | -3.962392 | 0 | 1.367313 | -5.329705 | 0 |
| 2024-06-15T23:00 | 29.100000 | 29.329790 | 36.455736 | 0 | -4.030435 | 0 | 1.337041 | -5.367476 | 0 |

## 7. Soil moisture analysis

- Field capacity/wilting point: `0.42/0.15`.
- Bound violations: `0`.
- Pump ON intervals with positive theta change: `60/60`.
- Pump OFF + ET intervals with negative theta change: `659/659`.
- Controlled pump test: `PASS`.

## 8. Light analysis

- Night + grow OFF maximum: `0.000000 lux`.
- Solar/lux Pearson correlation: `0.997266`.
- Grow-light calibration: `INITIAL_PRIOR_TO_MEASURE`; baseline grow light remains OFF.

## 9. Actuator causal tests

- `A_solar_response`: `PASS`
- `B_ventilation_response`: `PASS`
- `C_humidity_exchange`: `PASS`
- `D_pump_response`: `PASS`
- `E_soil_stress`: `PASS`
- `F_et_coupling`: `PASS`
- `G_grow_light`: `PASS`
- `E0_atmospheric_boundaries`: `PASS`

## 10. ET and ventilation coupling

- ET -> vapor/latent cooling/root water: `PASS`.
- Ventilation -> cooling: `PASS`.
- Ventilation -> vapor removal: `PASS`.
- Soil stress -> Ks/ET reduction: `PASS`.

## 11. Mass balances

- Root-zone water residual: `1.262011e-16 m3`; relative `1.726224e-14`.
- Indoor vapor residual: `-1.226392e-13 kg`; relative `8.510336e-09`.

## 12. Numerical stability

- Status: `PASS` for dt=60/120/300 s.
- `dt=60s`: `ACCEPTED`; final differences `{'temperature_inside_c': 0.0, 'humidity_inside_percent': 0.0, 'soil_temperature_c': 0.0, 'soil_moisture_theta': 0.0}`.
- `dt=120s`: `ACCEPTED`; final differences `{'temperature_inside_c': 5.5470049886707784e-08, 'humidity_inside_percent': 6.355057138307529e-07, 'soil_temperature_c': 2.4772574604980946e-06, 'soil_moisture_theta': 1.5530448441158917e-07}`.
- `dt=300s`: `ACCEPTED`; final differences `{'temperature_inside_c': 1.2936013149555947e-07, 'humidity_inside_percent': 1.7637589735386427e-06, 'soil_temperature_c': 3.1014102361837104e-06, 'soil_moisture_theta': 1.2443796015004782e-06}`.

## 13. Outlier root-cause analysis

- Classification: No numerical outliers. High soil temperatures are physical-model extremes governed by an explicit uncalibrated E8 prior.
- Pre-fix issue: V1.0 effective root-zone temperature reached 48.6689 degC because the surface-like solar coupling prior (eta_s=0.6) was applied directly to the lumped state representing the 7 cm sensor/root zone.
- Diagnosis: At the peak, positive E8 solar input exceeded air exchange plus base loss. RK4 dt=60/120/300 results agreed, excluding an integration issue.
- Top-five row groups and state jumps are preserved in the JSON sidecar for audit; no row was removed.

## 14. Remaining calibration risks

- E8 effective solar coupling, thermal capacity, air-soil transfer, and base loss.
- E4 transpiration coefficients and crop effective area.
- Fan installed-flow factor and emitter flow.
- Substrate field capacity, wilting point, drainage, and sensor-percent-to-VWC mapping.
- Grow-light radiant/heat/lux response and luminous efficacy.

## 15. Verification passes

- `pass_1_schema`: `PASS`
- `pass_2_physics`: `PASS`
- `pass_3_numerical`: `PASS`
- `pass_4_deployment`: `PASS`

## Final decision

`PASS`

The master may be used to build the canonical deployment-aligned ML dataset only when this status is `PASS` and the file hashes still match.
