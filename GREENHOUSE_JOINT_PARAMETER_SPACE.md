# SmartGarden PA1 Joint Parameter Space

Version: `1.0`

Status: `VALIDATED_JOINT_SPACE`

This document locks the interaction-tested uncertainty space for PA1. It supplements, and does not replace, `GREENHOUSE_PARAMETER_UNCERTAINTY.md`.

## 1. Approved individual ranges

| Parameter | Range | Distribution | Config path(s) |
|---|---|---|---|
| `C_d` | `0.2..0.65` | `triangular` | `ventilation.discharge_coefficient` |
| `eta_s` | `0.1..0.2` | `triangular` | `soil_thermal.solar_absorption_fraction` |
| `C_s` | `60000.0..90000.0` | `triangular` | `soil_thermal.effective_heat_capacity_j_k` |
| `irrigation_flow_L_h` | `5.0..15.0` | `triangular` | `irrigation.effective_flow_m3_s` |
| `ET_scale` | `1.0..1.3` | `triangular` | `crop.transpiration_radiation_coefficient`, `crop.transpiration_vpd_coefficient` |

## 2. Interaction scenarios

The pilot executed `12` deterministic 30-day scenarios on one locked weather trajectory. See `interaction_scenarios.yaml` and `interaction_pilot_validation.md`.

## 3. Interaction findings

Humidity, E8 root-zone heat, and soil-water/ET combinations were evaluated against matched single-axis controls where available. Additive, synergistic and antagonistic labels are diagnostics, not ML features.

## 4. Accepted joint regions

- `interaction_000_baseline`: `VALID`.
- `interaction_002_high_soil_coupling_low_inertia`: `EXTREME_VALID`.
- `interaction_003_low_irrigation_high_et`: `VALID`.
- `interaction_005_adverse_thermal_ventilation`: `EXTREME_VALID`.
- `interaction_006_low_stress_reference`: `VALID`.
- `interaction_007_combined_dry_hot_stress`: `EXTREME_VALID`.
- `interaction_009_cd030_high_et_boundary`: `EXTREME_VALID`.
- `interaction_010_low_ventilation_et115_boundary`: `EXTREME_VALID`.

## 5. Rejected joint regions

- `interaction_001_low_ventilation_high_et`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold..
- `interaction_004_wet_humid_boundary`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold..
- `interaction_008_low_ventilation_high_irrigation`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold..
- `interaction_011_cd030_wet_high_et_boundary`: `INVALID_JOINT_REGION`; RH=100% exceeds the unchanged 5% persistent-saturation threshold..

## 6. Extreme-valid regions

- `interaction_002_high_soil_coupling_low_inertia` retained without clipping.
- `interaction_005_adverse_thermal_ventilation` retained without clipping.
- `interaction_007_combined_dry_hot_stress` retained without clipping.
- `interaction_009_cd030_high_et_boundary` retained without clipping.
- `interaction_010_low_ventilation_et115_boundary` retained without clipping.

## 7. Sampling constraints

- `couple_et_coefficients`: `REQUIRE` when `always`; k_R and k_D are one approved coupled uncertainty axis.
- `reject_low_cd_high_et_wedge`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<","value":0.3},{"parameter":"ET_scale","operator":">","value":1.15}]}`; Persistent RH saturation at the adverse corner; both one-axis boundary relaxations passed.
- `reject_low_cd_high_irrigation_region`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<","value":0.3},{"parameter":"irrigation_flow_L_h","operator":">=","value":15.0}]}`; High irrigation at the low-Cd boundary exceeded unchanged humidity guards even at baseline ET.
- `reject_moderate_low_cd_wet_high_et_corner`: `REJECT_FOR_FULL_GENERATION_V1` when `{"all":[{"parameter":"C_d","operator":"<=","value":0.3},{"parameter":"irrigation_flow_L_h","operator":">=","value":15.0},{"parameter":"ET_scale","operator":">=","value":1.3}]}`; C_d=0.30 was sufficient for high ET alone but not for simultaneous maximum irrigation and ET.
- `post_sample_physics_gate`: `REQUIRE` when `every sampled parameter set`; A five-dimensional accepted space can be non-rectangular beyond the structured probes.

## 8. Recommended full-generation method

Use constrained Latin Hypercube Sampling in five dimensions with `24` total parameter sets (1 locked baseline plus 23 constrained LHS parameter sets). Record the seed, apply deterministic constraint filtering, and run the locked June 30-day preflight before any accepted set is expanded to 2018-2025.

Estimated first-release size: `1,683,072` hourly rows. Full generation remains out of scope for this milestone.

## 9. Deployment invariant

`ML_DATA_CONTRACT.md` remains unchanged. Weather is simulation forcing only; baseline ML inputs remain five sensor states plus three Raspberry Pi actuator states, with zero physics-only features.
