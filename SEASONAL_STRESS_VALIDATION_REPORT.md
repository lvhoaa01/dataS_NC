# Seasonal Stress Validation Report

Status: `SUCCESS`

`MANIFEST_V2_READY = YES`

## 1. Why V1 preflight failed

V1 used only the validated June 2024 window as its full-generation eligibility
gate. `pa1_full_006` passed that gate at `34/720 = 4.7222%` RH saturation,
but failed the final 2018-2025 validator at `6,571/70,128 = 9.370009%`.
The implication `June PASS -> full-horizon PASS` is therefore falsified.

No physics equation, timestep, controller, guard, weather record, or ML
contract was changed in response. V1 artifacts remain preserved with CSV SHA-256
`194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8`.

## 2. Full-horizon evidence from set 006

`pa1_full_006` remains `FAILED_VALIDATION` and is classified
`REJECTED_FULL_HORIZON_V1`. Its 70,128-row debug physics trace is retained;
no canonical ML file exists for this failed set.

The failure remains isolated to humidity: longest saturation was 11 hours,
root-zone maximum temperature was 35.619 C, and soil moisture stayed within
0.198440..0.429997 m3/m3. The root cause is an invalid full-horizon joint region,
not an implementation, numerical, hash, weather, or I/O error.

## 3. Weather stress-window methodology

`select_climate_stress_windows.py` evaluates every daily-aligned contiguous
30-day window with 30 days of available lead-in across the 2018-2025 weather
forcing. Selection uses only outdoor weather, never greenhouse physics output.

Each score is a weighted sum of component z-scores calculated over all 2,863
candidate windows:

- Humid: high mean/p95 RH and dew point, low VPD and wind.
- Hot-solar: high mean/max temperature, shortwave and direct radiation.
- Dry-VPD: high mean/p95 VPD, temperature and solar, low RH.
- Transition: high within-window and day-to-day forcing variability.

Ties resolve to the earliest timestamp. Selected windows may overlap by at most
50%, including the June reference. Selection version is
`pa1_climate_stress_windows_v1`; raw weather SHA-256 is
`61bdf841a0f6b7d98bf27951ab3a89e93a4ce13ab48e85acc1b1513e246e0734`.

## 4. Selected windows

| Type | Start | End | Score | T mean/max C | RH mean/p95 % | VPD mean/p95 kPa |
|---|---|---|---:|---:|---:|---:|
| REFERENCE_JUNE | 2024-06-01 | 2024-06-30 | 0.000 | 30.22 / 36.50 | 75.41 / 92 | 1.145 / 2.700 |
| HUMID_STRESS | 2022-11-10 | 2022-12-09 | 1.211 | 25.26 / 28.90 | 89.92 / 99 | 0.342 / 0.850 |
| HOT_SOLAR_STRESS | 2024-04-04 | 2024-05-03 | 1.834 | 29.69 / 36.50 | 72.53 / 91 | 1.251 / 2.891 |
| DRY_VPD_STRESS | 2019-06-17 | 2019-07-16 | 2.172 | 30.66 / 35.90 | 68.89 / 87 | 1.451 / 2.860 |
| TRANSITION_MIXED | 2019-08-27 | 2019-09-25 | 1.578 | 28.04 / 34.60 | 80.11 / 97 | 0.819 / 2.221 |

Machine-readable definitions are in `climate_stress_windows.csv` and
`climate_stress_windows.yaml`.

## 5. Warm-up methodology

Every window uses one continuous 30-day lead-in followed by a 30-day scored
segment. The simulator initializes once at lead-in start. All four dynamic
states (`T_inside`, indoor vapor density, `T_soil`, and theta) are handed to the
scored segment. Saved validation evidence confirms exact equality between every
warm-up final state and scored initial state. The controller is stateless; no
hysteresis timer or previous-actuator state exists to lose at the boundary.

## 6. Positive and negative controls

The negative control baseline passed all five windows. Its humid-window RH
saturation was `24/720 = 3.3333%`, longest 4 hours.

The positive failure control `pa1_full_006` failed the weather-derived humid
window at `188/720 = 26.1111%`, longest 10 hours. It also failed the transition
window at `71/720 = 9.8611%`. It passed June, hot-solar, and dry-VPD windows.
The required known-failure detection therefore passes.

## 7. V1 candidate results

All 24 V1 sets were audited. Ten passed all seasonal windows and 14 failed.
For the required not-yet-accepted group `006-023`, 18 were tested: 8 passed and
10 failed.

The six full-horizon passes `000-005` remain retained. Seasonal screening also
passed `000` and `005`, but flagged `001-004` on the local humid-window 5% guard.
This is a conservative-screening contradiction, not retroactive evidence that
their already validated eight-year trajectories fail: full-horizon aggregate
validation is stronger and remains final authority.

## 8. Humidity interaction findings

The rejected region is not described adequately by a single `C_d` threshold.
V1 humid failures span `C_d=0.2599..0.6426`. Irrigation, ET response, and
ventilation interact materially:

- `006`: C_d 0.2993, irrigation 13.618 L/h, ET 1.1407 -> 26.11% saturation.
- V2 trial raw 46: C_d 0.3976, irrigation 10.095 L/h, ET 1.0065 -> 9.86%, fail.
- V2 raw 52: C_d 0.6378, irrigation 10.036 L/h, ET 1.0035 -> 4.03%, pass.
- V1 `011`: C_d 0.6162, irrigation 9.926 L/h, ET 1.1711 -> 4.44%, pass.
- V1 `019`: C_d 0.6371, irrigation 10.868 L/h, ET 1.0070 -> 5.28%, fail.

These points show a curved/multivariate boundary. They do not justify fitting a
closed-form exclusion from this small deterministic pilot.

## 9. Thermal findings

All eligible V2 sets pass `T_soil <= 40 C` in all five windows. No clipping was
used. Hot-solar and E8 diagnostics remain part of every seasonal report.

## 10. Soil-water findings

Every eligible set passed state bounds, controller-pathology checks, root-water
balance, stress diagnostics, and the existing pump/ET causal checks. No state
collapse, permanent saturation, or arbitrary soil-moisture closure was added.

## 11. New/revised joint constraints

The approved individual parameter ranges and existing machine-readable joint
constraints are unchanged. V2 adds this empirical eligibility constraint:

```text
known individual/joint constraints PASS
AND all five warm-started seasonal stress windows PASS
```

Full-horizon validation remains the final acceptance gate. This policy is
recorded in `final_approved_parameter_sets_v2.yaml`; no unsupported closed-form
humidity boundary was added.

## 12. Rejected V1 candidates

The ten V1 sets removed from V2 are:

```text
pa1_full_006, pa1_full_007, pa1_full_008, pa1_full_013,
pa1_full_014, pa1_full_015, pa1_full_016, pa1_full_019,
pa1_full_020, pa1_full_022
```

`006` is additionally retained as full-horizon rejection evidence. The others
were not run over the full horizon.

## 13. Replacement candidates

The sampler continued `pa1_constrained_lhs_v1`, seed `20260816`, after raw index
23. It evaluated raw candidates 24..52: 10 passed, 18 failed seasonal preflight,
and raw 38 failed the pre-existing low-C_d/high-ET joint constraint.

Accepted raw indices were `24, 25, 26, 28, 29, 31, 33, 34, 35, 52` and map in
order to `pa1_v2_replacement_001..010`. Trial-to-official identity changes were
verified not to alter physical config hashes.

## 14. Coverage V1 vs V2

| Axis | V1 min/max | V2 min/max | V1 mean/std | V2 mean/std |
|---|---:|---:|---:|---:|
| C_d | 0.260 / 0.650 | 0.260 / 0.650 | 0.510 / 0.110 | 0.530 / 0.090 |
| eta_s | 0.114 / 0.200 | 0.114 / 0.200 | 0.170 / 0.020 | 0.170 / 0.020 |
| C_s J/K | 64,453 / 90,000 | 64,453 / 90,000 | 80,462 / 7,245 | 79,960 / 7,372 |
| irrigation L/h | 5.449 / 13.618 | 5.449 / 12.657 | 9.95 / 1.99 | 8.64 / 1.54 |
| ET_scale | 1.000 / 1.261 | 1.000 / 1.252 | 1.10 / 0.07 | 1.09 / 0.07 |

The valid space shifts toward lower irrigation but does not collapse on any
axis. The retained full-pass sets preserve validated low-ventilation and humid
extremes that a conservative local-window gate would otherwise remove.

## 15. Final manifest V2

- CSV: `final_approved_parameter_sets_v2.csv`.
- Machine manifest: `final_approved_parameter_sets_v2.yaml`.
- CSV SHA-256: `b619270408e95eeef350e3a1686d3c8691cf01d5b25428981e5116122f69131a`.
- Rows: 24 unique eligible physical configs.
- Origins: 6 `V1_RETAINED_FULL_PASS`, 8 `V1_RETAINED`, 10 `V2_REPLACEMENT`.
- Full-horizon statuses: 6 `FULL_HORIZON_PASS`, 18 `NOT_RUN`.

V1 files were not overwritten.

## 16. Resume strategy

`run_full_generation.py` accepts the V2 machine manifest explicitly. V2 dry-run
resolves 24 jobs and 1,683,072 expected rows without executing full mode. Strict
cache audit returns `SKIP/COMPLETE` for unchanged sets `000-005`; their config,
weather, physics, ML, validation, and output hashes still match. The absent V1
ID `006` is not retried, and its failed debug artifact remains preserved.

The next milestone command is:

```text
python run_full_generation.py --full --manifest final_approved_parameter_sets_v2.yaml
```

It was not executed in this task.

## 17. Remaining scientific limitations

Seasonal preflight reduces full-run rejection risk but does not prove
full-horizon validity. A candidate passing five stress windows can still fail a
different 2018-2025 sequence, accumulated state, or rare forcing interaction.
Production logic must continue to treat full simulation plus full validation as
the final authority and replace any future full-horizon rejection without
clipping, guard relaxation, or physics-specification mutation.

Seasonal runtime averaged 55.2 seconds per parameter set versus 556.6 seconds
for observed full-horizon sets, approximately a ten-fold screening speedup.
The executed seasonal audit/replacement work totaled about 48.7 minutes.

The deployment ML contract remains unchanged: five PA1 sensor variables plus
three Raspberry Pi actuator states; physics-feature and weather-feature counts
remain `0/0`; observation mode remains `physics_true_state`.
