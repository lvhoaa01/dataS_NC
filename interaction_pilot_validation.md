# Interaction Pilot Validation

Final status: `PASS`

## 1. Purpose

Validate structured joint combinations of the five approved PA1 uncertainty axes without changing weather, controller, hardware, sensor layer, simulator equations, or validator thresholds.

## 2. Baseline reproduction

- Status: `PASS`.
- Maximum non-identity difference: `0.000e+00`.
- Weather hash: `2d014eb72e33a8686c01be5f0b699b38467158691ac7bc2db166853cb28b46de`.
- Simulator code hash: `07b86fd9342a4c4a8fbadd7fd0fbb10b8d31befcf9ae797dd6ff53ce2f171336`.

## 3. Approved individual ranges

| Parameter | Min | Max | Distribution | Mode |
|---|---:|---:|---|---:|
| `C_d` | 0.2 | 0.65 | `triangular` | 0.65 |
| `eta_s` | 0.1 | 0.2 | `triangular` | 0.2 |
| `C_s` | 60000.0 | 90000.0 | `triangular` | 90000.0 |
| `irrigation_flow_L_h` | 5.0 | 15.0 | `triangular` | 10.0 |
| `ET_scale` | 1.0 | 1.3 | `triangular` | 1.0 |

`ET_scale` multiplies `k_R` and `k_D` together; the coefficients were never sampled independently.

## 4. Interaction scenarios

| Scenario | Changed axes | Validation | Classification |
|---|---|---|---|
| `interaction_000_baseline` | none | `PASS` | `VALID` |
| `interaction_001_low_ventilation_high_et` | C_d, ET_scale | `FAIL` | `INVALID_JOINT_REGION` |
| `interaction_002_high_soil_coupling_low_inertia` | C_s | `PASS` | `EXTREME_VALID` |
| `interaction_003_low_irrigation_high_et` | irrigation_flow_L_h, ET_scale | `PASS` | `VALID` |
| `interaction_004_wet_humid_boundary` | C_d, irrigation_flow_L_h, ET_scale | `FAIL` | `INVALID_JOINT_REGION` |
| `interaction_005_adverse_thermal_ventilation` | C_d, C_s | `PASS` | `EXTREME_VALID` |
| `interaction_006_low_stress_reference` | eta_s | `PASS` | `VALID` |
| `interaction_007_combined_dry_hot_stress` | C_s, irrigation_flow_L_h, ET_scale | `PASS` | `EXTREME_VALID` |
| `interaction_008_low_ventilation_high_irrigation` | C_d, irrigation_flow_L_h | `FAIL` | `INVALID_JOINT_REGION` |
| `interaction_009_cd030_high_et_boundary` | C_d, ET_scale | `PASS` | `EXTREME_VALID` |
| `interaction_010_low_ventilation_et115_boundary` | C_d, ET_scale | `PASS` | `EXTREME_VALID` |
| `interaction_011_cd030_wet_high_et_boundary` | C_d, irrigation_flow_L_h, ET_scale | `FAIL` | `INVALID_JOINT_REGION` |

## 5. Humidity interactions

| Scenario | RH mean/max % | RH=100 rows | Longest h | Condensation kg |
|---|---:|---:|---:|---:|
| `interaction_000_baseline` | 76.502 / 100.000 | 1 | 1 | 0.00855107 |
| `interaction_001_low_ventilation_high_et` | 80.279 / 100.000 | 37 | 5 | 0.689124 |
| `interaction_004_wet_humid_boundary` | 82.992 / 100.000 | 63 | 5 | 1.21855 |
| `interaction_008_low_ventilation_high_irrigation` | 82.649 / 100.000 | 54 | 4 | 0.777203 |
| `interaction_009_cd030_high_et_boundary` | 79.004 / 100.000 | 20 | 4 | 0.43634 |
| `interaction_010_low_ventilation_et115_boundary` | 80.187 / 100.000 | 32 | 4 | 0.461886 |
| `interaction_011_cd030_wet_high_et_boundary` | 81.460 / 100.000 | 46 | 4 | 0.803141 |

The `C_d=0.20, ET_scale=1.30` corner reached 37 saturated rows (5.139%) and failed only the locked saturation guard. Its two bracket points passed: `C_d=0.30, ET_scale=1.30` had 20 rows, while `C_d=0.20, ET_scale=1.15` had 32 rows. High irrigation was more restrictive: 54 saturated rows at low Cd and baseline ET, and 46 rows at `C_d=0.30` with maximum irrigation and ET.

## 6. Root-zone thermal interactions

| Scenario | Tsoil max/p95/p99 C | h >36 | h >38 | h >40 |
|---|---:|---:|---:|---:|
| `interaction_000_baseline` | 37.565 / 36.624 / 37.288 | 116 | 0 | 0 |
| `interaction_001_low_ventilation_high_et` | 37.651 / 36.703 / 37.372 | 118 | 0 | 0 |
| `interaction_002_high_soil_coupling_low_inertia` | 38.307 / 37.260 / 38.060 | 149 | 9 | 0 |
| `interaction_003_low_irrigation_high_et` | 37.691 / 36.737 / 37.410 | 121 | 0 | 0 |
| `interaction_004_wet_humid_boundary` | 37.528 / 36.586 / 37.253 | 109 | 0 | 0 |
| `interaction_005_adverse_thermal_ventilation` | 38.381 / 37.328 / 38.122 | 152 | 11 | 0 |
| `interaction_006_low_stress_reference` | 34.797 / 34.086 / 34.631 | 0 | 0 | 0 |
| `interaction_007_combined_dry_hot_stress` | 38.441 / 37.380 / 38.204 | 155 | 12 | 0 |
| `interaction_008_low_ventilation_high_irrigation` | 37.509 / 36.571 / 37.234 | 107 | 0 | 0 |
| `interaction_009_cd030_high_et_boundary` | 37.634 / 36.687 / 37.355 | 117 | 0 | 0 |
| `interaction_010_low_ventilation_et115_boundary` | 37.643 / 36.697 / 37.365 | 119 | 0 | 0 |
| `interaction_011_cd030_wet_high_et_boundary` | 37.514 / 36.575 / 37.239 | 104 | 0 | 0 |

The hottest accepted interaction was `interaction_007_combined_dry_hot_stress` at 38.441 C, with 12 hours above 38 C and zero above 40 C. All dt=60/120/300 comparisons passed, so the retained E8 extremes are not integration artifacts.

## 7. Soil-water / ET interactions

| Scenario | theta min/max | Stress h | Near-wilting h | ET kg | Irrigation L | Drainage L |
|---|---:|---:|---:|---:|---:|---:|
| `interaction_000_baseline` | 0.201686 / 0.407252 | 637 | 0 | 13.6555 | 10.0001 | 0.0000 |
| `interaction_001_low_ventilation_high_et` | 0.186701 / 0.407026 | 660 | 0 | 13.9810 | 10.0001 | 0.0000 |
| `interaction_002_high_soil_coupling_low_inertia` | 0.201686 / 0.407252 | 637 | 0 | 13.6555 | 10.0001 | 0.0000 |
| `interaction_003_low_irrigation_high_et` | 0.168543 / 0.402778 | 668 | 0 | 9.4990 | 5.0000 | 0.0000 |
| `interaction_004_wet_humid_boundary` | 0.205229 / 0.411192 | 654 | 0 | 18.4537 | 15.0000 | 0.0000 |
| `interaction_005_adverse_thermal_ventilation` | 0.202219 / 0.407308 | 636 | 0 | 13.6423 | 10.0001 | 0.0000 |
| `interaction_006_low_stress_reference` | 0.201719 / 0.407252 | 637 | 0 | 13.6548 | 10.0001 | 0.0000 |
| `interaction_007_combined_dry_hot_stress` | 0.168542 / 0.402778 | 669 | 0 | 9.4990 | 5.0000 | 0.0000 |
| `interaction_008_low_ventilation_high_irrigation` | 0.228522 / 0.411475 | 612 | 0 | 17.9408 | 15.0000 | 0.0000 |
| `interaction_009_cd030_high_et_boundary` | 0.186543 / 0.406996 | 660 | 0 | 13.9847 | 10.0001 | 0.0000 |
| `interaction_010_low_ventilation_et115_boundary` | 0.193480 / 0.407166 | 658 | 0 | 13.8341 | 10.0001 | 0.0000 |
| `interaction_011_cd030_wet_high_et_boundary` | 0.204919 / 0.411163 | 654 | 0 | 18.4610 | 15.0000 | 0.0000 |

The dry/hot minimum was 0.168542 m3/m3, above the 0.15 wilting prior and outside the near-wilting diagnostic band. Soil-stress feedback reduced ET enough that low irrigation + high ET was antagonistic rather than a state collapse. No scenario crossed field capacity, so drainage remained structurally inactive on this window.

## 8. Nonlinear interaction findings

- `interaction_001_low_ventilation_high_et`: `ROUGHLY_ADDITIVE` on `delta_RH_mean`; combined=3.77725, additive=3.78797, residual=-0.0107177.
- `interaction_002_high_soil_coupling_low_inertia`: `SINGLE_AXIS_REFERENCE` (REFERENCE).
- `interaction_003_low_irrigation_high_et`: `ANTAGONISTIC_INTERACTION` on `delta_soil_moisture_min`; combined=-0.0331434, additive=-0.0405988, residual=0.00745538.
- `interaction_004_wet_humid_boundary`: `SYNERGISTIC_INTERACTION` on `delta_RH_mean`; combined=6.49059, additive=5.50548, residual=0.98511.
- `interaction_005_adverse_thermal_ventilation`: `ROUGHLY_ADDITIVE` on `delta_T_soil_max`; combined=0.816452, additive=0.811575, residual=0.00487738.
- `interaction_006_low_stress_reference`: `SINGLE_AXIS_REFERENCE` (REFERENCE).
- `interaction_007_combined_dry_hot_stress`: `ANTAGONISTIC_INTERACTION` on `delta_soil_moisture_min`; combined=-0.0331444, additive=-0.0405989, residual=0.00745448.
- `interaction_008_low_ventilation_high_irrigation`: `SYNERGISTIC_INTERACTION` on `delta_RH_mean`; combined=6.14748, additive=5.25333, residual=0.894154.
- `interaction_009_cd030_high_et_boundary`: `NO_MATCHED_SINGLE_AXIS_CONTROL` (NOT_ESTIMABLE).
- `interaction_010_low_ventilation_et115_boundary`: `NO_MATCHED_SINGLE_AXIS_CONTROL` (NOT_ESTIMABLE).
- `interaction_011_cd030_wet_high_et_boundary`: `NO_MATCHED_SINGLE_AXIS_CONTROL` (NOT_ESTIMABLE).

## 9. Invalid joint regions

- `interaction_001_low_ventilation_high_et`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold. Framework/causal/balance/stability remained `PASS`/`PASS`/`PASS`/`PASS`.
- `interaction_004_wet_humid_boundary`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold. Framework/causal/balance/stability remained `PASS`/`PASS`/`PASS`/`PASS`.
- `interaction_008_low_ventilation_high_irrigation`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold. Framework/causal/balance/stability remained `PASS`/`PASS`/`PASS`/`PASS`.
- `interaction_011_cd030_wet_high_et_boundary`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold. Framework/causal/balance/stability remained `PASS`/`PASS`/`PASS`/`PASS`.

## 10. Extreme-but-valid regions

- `interaction_002_high_soil_coupling_low_inertia`: Tsoil,max=38.307 C; RH=100 for 1 rows; theta,min=0.201686.
- `interaction_005_adverse_thermal_ventilation`: Tsoil,max=38.381 C; RH=100 for 28 rows; theta,min=0.202219.
- `interaction_007_combined_dry_hot_stress`: Tsoil,max=38.441 C; RH=100 for 5 rows; theta,min=0.168542.
- `interaction_009_cd030_high_et_boundary`: Tsoil,max=37.634 C; RH=100 for 20 rows; theta,min=0.186543.
- `interaction_010_low_ventilation_et115_boundary`: Tsoil,max=37.643 C; RH=100 for 32 rows; theta,min=0.193480.

## 11. Final joint constraints

- `couple_et_coefficients`: `REQUIRE` when `always`; k_R and k_D are one approved coupled uncertainty axis.
- `reject_low_cd_high_et_wedge`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<","value":0.3},{"parameter":"ET_scale","operator":">","value":1.15}]}`; Persistent RH saturation at the adverse corner; both one-axis boundary relaxations passed.
- `reject_low_cd_high_irrigation_region`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<","value":0.3},{"parameter":"irrigation_flow_L_h","operator":">=","value":15.0}]}`; High irrigation at the low-Cd boundary exceeded unchanged humidity guards even at baseline ET.
- `reject_moderate_low_cd_wet_high_et_corner`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<=","value":0.3},{"parameter":"irrigation_flow_L_h","operator":">=","value":15.0},{"parameter":"ET_scale","operator":">=","value":1.3}]}`; C_d=0.30 was sufficient for high ET alone but not for simultaneous maximum irrigation and ET.
- `post_sample_physics_gate`: `REQUIRE` when `every sampled parameter set`; A five-dimensional accepted space can be non-rectangular beyond the structured probes.

## 12. Recommended sampling method

Use constrained Latin Hypercube Sampling over the five triangular marginals. Apply machine-readable joint constraints and the same 30-day June physics preflight before full-period generation.

## 13. Recommended number of full scenarios

Recommend `24` total parameter sets: 1 locked baseline plus 23 constrained LHS parameter sets. This covers five dimensions with a manageable first-release compute and validation burden.

## 14. Estimated full dataset size

`70,128 x 24 = 1,683,072` hourly rows. This is an estimate only; full generation was not run.

## 15. Full-generation readiness

- Accepted probes: `8`; extreme-valid: `5`; rejected: `4`.
- Same weather/controller/initial-state method: `PASS`.
- Existing validator reused unchanged: `PASS`.
- ML contract: `PASS`; physics/weather feature count `0`.
- Full 2018-2025 generation executed: `NO`.

## Verification passes

- Pass 1 baseline reproducibility: `PASS`.
- Pass 2 interaction design: `PASS`.
- Pass 3 physics validation: `PASS` for accepted probes; rejected regions retained explicitly.
- Pass 4 joint-boundary analysis: `PASS`.
- Pass 5 full-generation readiness: `PASS` for specification; generation not executed.
