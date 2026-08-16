# Full Generation Final Report

Status: `PARTIAL_STOPPED_ON_SCIENTIFIC_GUARD`

`FULL_GENERATION_COMPLETE = NO`

## 1. Execution

- Command: `python run_full_generation.py --full`
- Window per parameter set: `2018-01-01T00:00` through `2025-12-31T23:00`.
- Canonical timestep/output: `60 s / 1 h`.
- Final parameter manifest SHA-256: `194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8`.
- Source weather SHA-256: `61bdf841a0f6b7d98bf27951ab3a89e93a4ce13ab48e85acc1b1513e246e0734`.
- The runner stopped normally after the first validation failure. It did not continue into later parameter sets.

## 2. Completion state

| State | Parameter sets | Physics rows | ML rows |
|---|---:|---:|---:|
| `COMPLETE` | 6 | 420,768 | 420,768 |
| `FAILED_VALIDATION` | 1 | 70,128 debug rows | 0 |
| Not started | 17 | 0 | 0 |

Completed sets are `pa1_full_000_baseline` through `pa1_full_005`. Every completed set has:

- exactly `70,128` physics rows and `70,128` ML rows;
- physics and ML SHA-256 values matching `run_state.json`;
- physics validation status `PASS`;
- ML metadata status `PASS`;
- physics/weather model-feature count `0/0`.

## 3. Blocking scenario

Parameter set: `pa1_full_006`

| Parameter | Value |
|---|---:|
| `C_d` | 0.2992743901 |
| `eta_s` | 0.1137516215 |
| `C_s` | 81,160.583 J/K |
| irrigation flow | 13.618053 L/h |
| `ET_scale` | 1.140690919 |

The deterministic simulation completed all `70,128` rows, then the unchanged full-generation validator rejected it:

```text
RH == 100%: 6,571 / 70,128 rows = 9.370009%
locked guard: <= 5%
longest continuous saturation: 11 h
```

No canonical ML file was built for this failed physics trace.

## 4. Root-cause evidence

The June preflight for the same parameter set was already close to the guard:

```text
34 / 720 rows = 4.722222%
```

The full weather horizon exposes a stronger humid-season interaction that the June window did not cover. Saturated rows by month were:

| Month | Rows | Month | Rows |
|---|---:|---|---:|
| Jan | 827 | Jul | 269 |
| Feb | 472 | Aug | 213 |
| Mar | 357 | Sep | 602 |
| Apr | 316 | Oct | 959 |
| May | 305 | Nov | 1,084 |
| Jun | 193 | Dec | 974 |

Every simulated year contained saturation (`595` to `1,040` rows/year). For comparison, the full-horizon baseline saturated for `443` rows (`0.632%`), and `pa1_full_001` saturated for `2,677` rows (`3.817%`).

The failed set combines near-boundary low ventilation with elevated ET and irrigation. Its other inspected states did not explode: root-zone temperature max was `35.619 C`, and soil moisture remained `0.198440..0.429997 m3/m3`. The failure is therefore classified as:

```text
INVALID_FULL_HORIZON_JOINT_REGION
```

This is not an implementation, hash, config, weather, numerical, disk, or atomic-I/O failure. The 30-day June preflight was not sufficient to approve this near-boundary combination for the entire climate horizon.

## 5. Safety and recovery

- Six completed scenarios remain intact and resumable.
- `pa1_full_006` is recorded as `FAILED_VALIDATION` at stage `PHYSICS_VALIDATION`.
- Failed-scenario physics SHA-256: `ef8956ca45a5bf2920d6aba9c8abdc3bbe3cfa0fcfdf9cbcaf072826e63f1da6`.
- Temporary files remaining: `0`.
- Active run lock remaining: `NO`.
- Output hash/schema audit issues on completed sets: `0`.

Running the same command again would retry `pa1_full_006` with the same deterministic result. It must not be resumed until the scientific parameter-space specification and approved manifest are revised through a separate uncertainty/preflight milestone.

## 6. ML contract

The completed ML outputs retain the locked deployment schema:

```text
timestamp
air_temperature
air_humidity
soil_temperature
soil_moisture
light_lux
pump_state
fan_state
grow_light_state
```

Observation mode remains `physics_true_state`; physics-only and weather model-feature counts remain `0/0`.

## 7. Required next decision

Do not train, window, split, or resume full generation from the current 24-set manifest. A follow-up scientific task should:

1. encode the newly observed humid-season joint exclusion around low `C_d` plus elevated ET/irrigation;
2. deterministically replace rejected parameter sets without loosening guards;
3. preflight replacements on climate-stratified humid and hot windows, not June alone;
4. issue a new versioned approved manifest before resuming the retained checkpoint.

No clipping, validator relaxation, physics change, parameter mutation, or ML-contract change was applied during this run.
