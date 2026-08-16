# SmartGarden PA1 Parameter Uncertainty

Version: `1.0`

Status: `PILOT_VALIDATED`

This file is the scientific source of truth for physical-parameter variation around the PA1
prototype. It does not authorize arbitrary greenhouse geometries, random controller schedules,
sensor noise, or full-period generation. Machine-readable values and direct config mappings live in
`scenario_parameter_space.yaml`.

## 1. Scope and classification

The uncertainty study preserves three distinct classes:

| Class | Meaning | Policy |
|---|---|---|
| `FIXED_DESIGN` | PA1 geometry, crop count/species, 20 L pot, 18 W lamp, nominal hardware and sensor models | Keep fixed unless the physical prototype design changes |
| `UNCERTAIN_PHYSICAL` | Unmeasured direct properties or effective coefficients in E1-E10 | Vary only inside sourced/constrained ranges and only after pilot validation |
| `CONTROL_TIME_VARYING` | Weather and relay/controller states | Keep the same deterministic trajectory across all pilot scenarios |

Fixed PA1 values include `0.8 x 0.8 x 1.5 m`, `V_g=0.96 m3`, cover area `5.44 m2`, one tomato,
20 L root volume, fan nominal free-air flow `5 m3/h`, grow-light electrical power `18 W`, and the
TH10S-B-PE / ES-SM-TH-01 / ES-ALS-02 models. Derived geometry is recomputed only if design changes;
it is not sampled.

Weather, `pump_state`, `fan_state`, `grow_light_state`, `vent_state`, pump timing and controller
thresholds are controls/disturbances, not static uncertainty parameters. Sensor noise/bias/drift is
excluded because the locked dataset currently uses `physics_true_state` with noise disabled.

## 2. Direct versus effective parameters

`DIRECT_PHYSICAL_PARAMETER` denotes a measurable material/device/installed-system value such as U,
cover transmittance or emitter flow. `EFFECTIVE_MODEL_PARAMETER` denotes a lumped coefficient such
as `C_eff`, `eta_s`, `h_as`, `k_R` or `k_D`; its range describes model uncertainty and must not be
presented as a directly measured material property.

## 3. Complete uncertainty audit

The following 22 axes cover all 29 config records currently labelled `TO_*` or
`INITIAL_PRIOR_*`. Multi-path axes are intentionally coupled.

| Parameter / symbol | Config path(s) | Kind; equations | Baseline; unit | Candidate min-max; distribution | Provenance / range basis / source | Confidence; uncertainty and expected effect | Calibration requirement | Pilot / final status |
|---|---|---|---|---|---|---|---|---|
| Effective air thermal capacity, `C_eff` | `greenhouse.effective_thermal_capacity_j_k` | Effective; E7 | 60,000 J/K | 40,000-90,000 exploratory; fixed for generation | Engineering response-time prior: with baseline UA this spans about 0.32-0.72 h; E7/config | Low; lumped air, frame, crop and internal mass; higher value reduces/retards temperature response | Fit jointly with U from measured cooling/diurnal response | Both bounds PASS but hourly outputs changed negligibly; `LOW_SENSITIVITY` |
| Cover shortwave transmittance, `tau_sw` | `cover.shortwave_transmittance` | Direct optical; E1/E4/E7/E8 | 0.85 | 0.75-0.92; triangular mode 0.85 | Commercial-cover measurement range recorded in hardware knowledge; Baneshi et al. 2020, DOI `10.1016/j.energy.2020.118535` | Medium; actual film unknown; higher value increases solar, ET and thermal forcing | Select and measure actual cover | Not piloted; `FIX_AT_BASELINE` |
| Cover visible transmittance, `tau_vis` | `cover.visible_transmittance` | Direct optical; E10 | 0.88 | 0.75-0.92; triangular mode 0.88 | Same clear-cover optical envelope; hardware knowledge section 5.2 | Low; actual film unknown; higher value raises lux | Fit with installed cover and ES-ALS-02 | Not piloted; `FIX_AT_BASELINE` |
| Cover U-value, `U` | `cover.u_value_w_m2_k` | Direct assembly property; E7 | 6.4 W/(m2 K) | 6.0-7.0; triangular mode 6.4 | UGA single-film R=0.83 implies U about 6.84 SI; project case prior 6.4; UGA B792 and DOI `10.1007/s43621-024-00276-5` | Medium; seams/assembly alter heat loss; higher U pulls air temperature toward outside faster | Fit U and C_eff jointly | Not piloted; `FIX_AT_BASELINE` |
| Effective air solar gain, `eta_a` | `cover.air_solar_absorption_fraction` | Effective; E7 | 0.35 | 0.20-0.50; triangular mode 0.35 | Engineering prior for air-coupled internal absorption; E7/config, not literal cover absorptivity | Low; higher value increases daytime air heating | Joint fit with `tau_sw`, U and `C_eff` | Not piloted; `NEEDS_REAL_CALIBRATION` |
| Passive leakage, `Vdot_leak` | `ventilation.passive_leakage_m3_s` | Effective; E2/E5/E7 | 0 | 0-0.0002667 m3/s; uniform provisional | 0-1 ACH envelope for 0.96 m3; UGA B792 new-plastic infiltration order | Low; enclosure tightness unknown; higher leakage increases T/RH exchange | Fan-off tracer/decay or state fit | Not piloted; `FIX_AT_BASELINE` |
| Passive discharge coefficient, `C_d` | `ventilation.discharge_coefficient` | Effective geometry; E2/E5/E7 | 0.65 | approved 0.20-0.65; triangular mode 0.65 | Greenhouse wind-tunnel openings about 0.1-0.7; screened vent measured near 0.193; DOI `10.2480/agrmet.36.3`, DOI `10.1016/j.biosystemseng.2009.06.013` | Medium-low; opening/mesh not finalized; higher value increases natural cooling/dehumidification | Measure installed opening/mesh | `C_d=0.20` PASS, mean RH +3.536 points; `APPROVED_FOR_SAMPLING` |
| Wind effect coefficient, `C_w` | `ventilation.wind_effect_coefficient` | Effective geometry; E2/E5/E7 | 0.09 | 0.05-0.15; triangular mode 0.09 | Measured greenhouse value 0.066 anchors interval; DOI `10.1016/j.biosystemseng.2009.06.013`; Teitel/Tanny driver form | Low; wind direction/geometry lumped; higher value raises wind-driven flow | Joint flow calibration with `C_d` | Not piloted independently; `FIX_AT_BASELINE` |
| Fan installed-flow factor, `f_fan` | `ventilation.fan_effective_flow_factor` | Effective installation; E2/E5/E7 | 1.0 | 0.50-1.0; triangular mode 0.8 provisional | Nominal 5 m3/h free-air spec is upper bound; 0.5 lower edge is installation-loss engineering prior; hardware knowledge section 10 | Medium-low; grille/path losses unknown; higher factor strengthens fan cooling/vapour removal | Measure installed volumetric flow; nominal flow stays fixed | Not piloted; `NEEDS_REAL_CALIBRATION` |
| Crop effective area, `A_crop` | `crop.effective_area_m2` | Effective; E4 | 0.30 m2 | 0.20-0.50; triangular mode 0.30 | Compact one-tomato PA1 engineering envelope; hardware knowledge sections 3/25 | Low; growth stage/leaf area lumped; higher area scales ET and changes grow-light irradiance | Measure leaf area or hold while fitting ET scale | Not piloted; `FIX_AT_BASELINE` |
| Coupled crop ET response, `f_ET` | `crop.transpiration_radiation_coefficient`, `crop.transpiration_vpd_coefficient` | Coupled effective axis; E4/E5/E7/E9 | scale 1.0; `k_R=1.5e-7`, `k_D=2.0e-6` | approved scale 1.0-1.30; triangular mode 1.0 | 30-day validated water/vapour/latent budget envelope; Boulard/Wang driver structure DOI `10.1016/S0168-1923(99)00082-9` | Low; one window cannot identify `k_R` and `k_D` independently; higher scale raises vapour, latent cooling and root water loss | Fit from water-loss plus T/RH data; preserve ratio until identifiable | `f_ET=1.30` PASS, mean theta -0.01958; `APPROVED_FOR_SAMPLING` |
| Soil effective thermal capacity, `C_s` | `soil_thermal.effective_heat_capacity_j_k` | Effective; E8 | 90,000 J/K | approved 60,000-90,000; triangular mode 90,000 | E8 thermal-lag engineering prior, about 24-47 h with baseline conductance; E8/validation history | Low; root-zone thermal mass lumped; higher value damps/delays temperature | Joint E8 fit from 7 cm sensor phase/amplitude | 60,000 PASS, `delta Tsoil,max=+0.743 C`; `APPROVED_FOR_SAMPLING` |
| Air-soil transfer, `h_as` | `soil_thermal.air_soil_heat_transfer_w_m2_k` | Effective; E7/E8 | 8 W/(m2 K) | 5-12; triangular mode 8 | Natural-convection order-of-magnitude engineering prior in config | Low; pot geometry/convection lumped; higher value couples air and soil more strongly | Joint E8 fit; do not independently sample first release | Not piloted; `FIX_AT_BASELINE` |
| Soil solar coupling, `eta_s` | `soil_thermal.solar_absorption_fraction` | Effective; E8 | 0.20 | approved 0.10-0.20; triangular mode 0.20; exploratory 0.30 rejected | 30-day E8 validation and boundary probing; `eta_s=0.6` produced 48.669 C; tomato root-zone context DOI `10.1016/0304-4238(84)90027-X` | Low; fraction reaching lumped 7 cm state is unmeasured; higher value increases root-zone heating | Fit with fixed ES-SM-TH-01 placement | 0.10 PASS; 0.30 FAIL at 40.340 C; `RANGE_TOO_WIDE` with approved subrange |
| Soil/base loss, `U_s` | `soil_thermal.base_loss_u_w_m2_k` | Effective closure; E8 | 2 W/(m2 K) | 1-4; triangular mode 2 | Engineering prior retained after E8 root-cause audit; E8/validation report | Low; pot/deeper loss lumped; higher value pulls soil toward `T_base` | Joint E8 fit | Not piloted; `FIX_AT_BASELINE` |
| Soil base temperature, `T_base` | `soil_thermal.base_temperature_c` | Effective boundary; E8 | 27 C | 25-29; triangular mode 27 | Warm Nha Trang engineering prior; external reanalysis soil is not substituted | Low; physical boundary unmeasured; higher value warms root-zone baseline | Measure pot/base boundary | Not piloted; `NEEDS_REAL_CALIBRATION` |
| Coupled substrate stress profile, `theta_fc/theta_wp/p` | `soil_water.field_capacity`, `soil_water.wilting_point`, `soil_water.depletion_fraction` | Coupled physical/effective; E3/E4/E9 | 0.42 / 0.15 / 0.40 | exploratory 0.35-0.50 / 0.10-0.20 / 0.30-0.50; constrained provisional | Container capacity depends on substrate and pot geometry and must be measured; Caron 2015 DOI `10.2136/vzj2014.10.0146`; FAO-adapted stress form | Low; substrate not purchased; higher `theta_fc` or `theta_wp` shifts stress/drainage behavior | Saturate/drain, dry-down and calibrate sensor-to-VWC; enforce `residual < wp < fc < saturation` | Not piloted; `NEEDS_REAL_CALIBRATION` |
| Drainage coefficient, `k_d` | `soil_water.drainage_coefficient_s` | Effective; E9 | 4.62963e-5 1/s (6 h) | 2.31481e-5-9.25926e-5 (12-3 h); log-uniform provisional | Engineering excess-water timescale around E9 baseline; container drainage must be measured | Low; active only above field capacity; larger value removes excess faster | Drainage trial in final pot/substrate | Baseline trajectory never exceeds field capacity; provisional `LOW_SENSITIVITY` |
| Soil closure bounds | `soil_water.residual_lower_bound`, `soil_water.saturation_upper_bound` | Physical/numerical closure; E9 | 0.05 / 0.55 m3/m3 | exploratory 0.03-0.08 / 0.50-0.65 but distribution fixed | Configured substrate bounds, not diversity controls | Low; prevent nonphysical integration but must not hide errors | Measure endpoints; keep fixed in pilot/full v1 | `FIX_AT_BASELINE` |
| Effective emitter flow, `q_pump` | `irrigation.effective_flow_m3_s` | Direct installed-system; E9 | 2.7778e-6 m3/s (10 L/h) | approved 1.38889e-6-4.16667e-6 (5-15 L/h); triangular mode 10 L/h | Adjustable emitter capability and 83-250 mL per fixed 60 s pulse; hardware knowledge sections 11-12 | Medium-low; head/tube/emitter setting unknown; higher value increases root water and may activate drainage | Five or more timed 60 s volume tests | Both bounds PASS; mean theta deltas -0.03016/+0.03136; `APPROVED_FOR_SAMPLING` |
| Grow-light response, `eta_rad/eta_heat/Lux_grow` | three `grow_light.*` response paths | Coupled effective/device; E4/E7/E10 | 0.25 / 0.65 / 5000 lux | fixed at baseline in this pilot | Lamp is always OFF, so the present trajectory cannot identify a range; hardware knowledge section 13 | Low; higher values affect ET/heat/lux only when ON | Night lux and thermal/electrical test before sampling | `NEEDS_REAL_CALIBRATION` |
| Luminous-efficacy profile, `K_dir/K_dif` | two `light.*_luminous_efficacy_lm_w` paths | Coupled optical; E10 | 100 / 139.98 lm/W | fixed at baseline in this pilot | Fakra tropical-humid prior DOI `10.1016/j.renene.2010.06.042`; source does not justify arbitrary independent ranges here | Medium-low; sky dependence lumped; changes lux only | Fit profile with ES-ALS-02 and actual cover | `FIX_AT_BASELINE` |

## 4. Coupling and identifiability rules

1. `UA = U * A_cover`; cover area is fixed design. Never sample both U and UA.
2. Air thermal response depends jointly on `C_eff`, U and effective solar gain. The first pilot varies
   only `C_eff`; future joint draws must constrain `C_eff/(U*A_cover)`.
3. Natural flow depends jointly on `C_d`, `C_w`, vent geometry and leakage. The first pilot varies
   only `C_d`; a future generator must constrain effective flow, not draw all coefficients freely.
4. Fan nominal airflow remains fixed at the verified free-air value. Only `f_fan` may represent
   installed losses.
5. `A_crop`, `k_R` and `k_D` are not independently identifiable from one 30-day window. Scenario 009
   uses one `f_ET=1.3` axis and multiplies both coefficients while holding crop area fixed.
6. E8 parameters `C_s`, `h_as`, `eta_s`, `U_s` and `T_base` are correlated. One-factor pilot results
   do not authorize an independent Cartesian product.
7. Soil water draws must enforce `theta_residual < theta_wp < theta_fc < theta_sat`; irrigation,
   drainage and stress-profile parameters are coupled by E3/E9.

## 5. Structured pilot design

All scenarios use the same hourly weather from `2024-06-01T00:00` through
`2024-06-30T23:00`, the same deterministic controller, all three numerical steps 60/120/300 s, and
720 saved rows. Seeds are recorded for framework reproducibility, but no randomness is used.

| Scenario | One uncertainty axis | Change | Purpose |
|---|---|---|---|
| `scenario_000_baseline` | none | V1.1 unchanged | Reproduce validated control |
| `scenario_001_low_air_thermal_inertia` | `C_eff` | 60,000 -> 40,000 J/K | Fast air response boundary |
| `scenario_002_high_air_thermal_inertia` | `C_eff` | 60,000 -> 90,000 J/K | Slow air response boundary |
| `scenario_003_low_passive_ventilation` | `C_d` | 0.65 -> 0.20 | Screen/restricted-opening boundary |
| `scenario_004_high_irrigation_flow` | `q_pump` | 10 -> 15 L/h | Wet boundary |
| `scenario_005_low_soil_solar_coupling` | `eta_s` | 0.20 -> 0.10 | Cool root-zone boundary |
| `scenario_006_high_soil_solar_coupling` | `eta_s` | 0.20 -> 0.30 | Explicit E8 rejection-boundary probe |
| `scenario_007_low_soil_thermal_capacity` | `C_s` | 90,000 -> 60,000 J/K | Faster root-zone response |
| `scenario_008_low_irrigation_flow` | `q_pump` | 10 -> 5 L/h | Dry/stress boundary |
| `scenario_009_high_et_response` | coupled `f_ET` | 1.0 -> 1.3 | Strong vapour/latent/root-water coupling |

## 6. Validation gates

Accepted scenarios must pass the existing schema/range, causal, conservation and numerical-stability
functions without changing their tolerances. Additional guards preserve the baseline deep-validator
policy:

```text
soil temperature > 40 C                  -> invalid parameter region
soil temperature in (35, 40] C           -> extreme/stressful but physically valid
RH=100 rows > 5%                          -> persistent saturation; invalid/review
NaN/Inf, mass residual or causal failure  -> invalid
temperature clipping                     -> forbidden
```

Condition labels are diagnostics only and never ML features.

## 7. Known validation history

### Soil solar coupling

```text
eta_s = 0.60 -> T_soil,max = 48.669 C -> MODEL/PARAMETER ISSUE
eta_s = 0.20 -> T_soil,max = 37.565 C -> PASS, calibration risk retained
```

`eta_s` is the effective fraction coupled into the lumped 7 cm root-zone state, not literal surface
absorptivity. No root-zone temperature clipping is allowed.

### Drainage identifiability

The baseline maximum moisture is `0.407252`, below `theta_fc=0.42`. Therefore the E9 drainage term
is inactive on this window. Changing `k_d` cannot create meaningful sensitivity until a wet-boundary
scenario crosses field capacity; this is a structural identifiability result, not evidence that the
real drainage coefficient is known.

### Grow light

The baseline grow light is always OFF. Its heat/radiation/lux response parameters have exactly zero
trajectory sensitivity in this pilot and must remain fixed pending night calibration.

## 8. Post-pilot summary table

This table records the final one-factor pilot decision. Approved subranges remain conditional on the
coupling rules in section 4.

| parameter | symbol | baseline | candidate_min | candidate_max | distribution | equations | provenance | confidence | pilot_result | final_status |
|---|---|---:|---:|---:|---|---|---|---|---|---|
| Effective air thermal capacity | `C_eff` | 60000 | 40000 | 90000 | fixed after pilot | E7 | engineering model prior | low | both bounds PASS; hourly deltas low | LOW_SENSITIVITY |
| Passive discharge coefficient | `C_d` | 0.65 | 0.20 | 0.65 approved | triangular | E2/E5/E7 | literature + geometry prior | medium-low | 0.20 PASS; RH mean +3.536 points | APPROVED_FOR_SAMPLING |
| Soil solar coupling | `eta_s` | 0.20 | 0.10 | 0.20 approved | triangular | E8 | validation-bounded model prior | low | 0.10 PASS; 0.30 FAIL at 40.340 C | RANGE_TOO_WIDE; APPROVED SUBRANGE |
| Soil thermal capacity | `C_s` | 90000 | 60000 | 90000 approved | triangular | E8 | engineering model prior | low | 60000 PASS; Tsoil max +0.743 C | APPROVED_FOR_SAMPLING |
| Effective irrigation flow | `q_pump` | 2.7778e-6 | 1.38889e-6 | 4.16667e-6 | triangular | E9 | hardware-bounded engineering prior | medium-low | both bounds PASS; material theta effect | APPROVED_FOR_SAMPLING |
| Coupled crop ET response | `f_ET` | 1.0 | 1.0 approved | 1.30 approved | triangular | E4/E5/E7/E9 | reduced-form calibration axis | low | 1.30 PASS; mean theta -0.01958 | APPROVED_FOR_SAMPLING |
| Drainage coefficient | `k_d` | 4.62963e-5 | 2.31481e-5 | 9.25926e-5 | log_uniform provisional | E9 | engineering timescale prior | low | inactive below FC | LOW_SENSITIVITY |
| All other audited uncertainty axes | see section 3 | baseline | documented | documented | fixed/provisional | E1-E10 | documented above | low-medium | not varied in pilot | FIX_AT_BASELINE or NEEDS_REAL_CALIBRATION |

## 9. Full-generation boundary

The one-factor pilot approves only `C_d`, the safe `eta_s` subrange, `C_s`, effective emitter flow,
and the coupled ET scale recorded in `scenario_parameter_space.yaml`. This does not yet authorize a
full 2018-2025 run. First run a small multi-axis interaction pilot inside those subranges. Approved
axes must obey coupled-group constraints; the approved space is not an unrestricted Cartesian
product.
