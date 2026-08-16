# Full Generation V2 Final Report

Status: `SUCCESS`

`FULL_SYNTHETIC_GENERATION_COMPLETE = YES`

## 1. V1 and V2 provenance

V1 completed six full-horizon sets (`pa1_full_000_baseline` through
`pa1_full_005`) and rejected `pa1_full_006` after its eight-year RH saturation
fraction reached `6,571/70,128 = 9.370009%`. The V1 manifest, reports, and the
70,128-row `006` debug physics trace remain preserved. No canonical ML output
exists for `006`, and it is not part of the final dataset.

V2 added weather-derived seasonal screening, retained the six V1 full passes,
retained eight V1 seasonal-pass candidates, and introduced ten deterministic
replacement sets. V2 CSV SHA-256 is
`b619270408e95eeef350e3a1686d3c8691cf01d5b25428981e5116122f69131a`.

## 2. Resume execution

Command:

```text
python run_full_generation.py --full --manifest final_approved_parameter_sets_v2.yaml
```

- Weather window: `2018-01-01T00:00` through `2025-12-31T23:00`.
- Weather rows per scenario: `70,128`.
- Canonical integration timestep: `60 s`.
- Worker count: `1`.
- Strict-cache skips: `6`.
- Newly executed full trajectories: `18`.
- Resume wall time: `10,317.9 s` (`2 h 51 m 57.9 s`).
- Sum of the 18 scenario runtimes: `10,283.067 s`.
- Mean newly executed scenario runtime: `571.282 s` (`9 m 31.3 s`).
- Sum of all 24 valid scenario runtimes, including retained work: `13,637.372 s`.

No candidate failed, and the runner did not relax a guard, alter physics,
change weather, increase timestep, or parallelize.

## 3. Final completion state

For the 24 V2 manifest identities:

| State | Count |
|---|---:|
| `COMPLETE` | 24 |
| `FAILED*` | 0 |
| `INTERRUPTED` | 0 |
| `RUNNING` | 0 |

Every set has one continuous 2018-2025 trajectory. State is initialized once
per set and is not reset at year boundaries.

## 4. Physics corpus

- Valid parameter sets: `24`.
- Physics files: `24`.
- Rows per file: `70,128`.
- Total valid physics rows: `1,683,072`.
- Total physics size: `631,755,543 bytes` (`0.588 GiB`).
- Schema, timestamp continuity, parameter identity, actuator states: `PASS`.
- NaN / Inf / invalid numeric values: `0 / 0 / 0`.
- Full validator, causal tests, root-water balance, indoor-vapor balance: `PASS`.
- RH saturation and `Tsoil <= 40 C` guards: `PASS` for all final sets.

## 5. Deployment-aligned ML corpus

- Valid parameter sets: `24`.
- ML files: `24`.
- Rows per file: `70,128`.
- Total valid ML rows: `1,683,072`.
- Total ML size: `166,549,514 bytes` (`0.155 GiB`).
- Exact canonical columns: `9`.
- Sensor variables: `5`.
- Actuator states: `3`.
- Physics/weather feature count: `0/0`.
- Observation mode: `physics_true_state`.
- NaN / Inf / invalid actuator values: `0 / 0 / 0`.

Canonical model data remains:

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

## 6. Final parameter coverage

| Axis | Min | Max | Mean | Median | Std |
|---|---:|---:|---:|---:|---:|
| `C_d` | 0.260 | 0.650 | 0.530 | 0.540 | 0.090 |
| `eta_s` | 0.114 | 0.200 | 0.170 | 0.170 | 0.020 |
| `C_s` J/K | 64,453.45 | 90,000.00 | 79,959.90 | 81,636.77 | 7,372.08 |
| irrigation L/h | 5.449 | 12.657 | 8.640 | 8.660 | 1.540 |
| `ET_scale` | 1.000 | 1.252 | 1.090 | 1.070 | 0.070 |

The full-valid corpus exactly matches the 24 V2 config hashes; no resampling was
performed during full generation.

## 7. Integrity and indexing

`full_dataset_index.csv` contains exactly one row per valid V2 identity with
physics/ML paths, row counts, hashes, classification, config hash, and validation
status. Index SHA-256 is
`815d8ec699ffb6a10cf48099af7686e18182778101d1087fe4fb4a4f890ef500`.

- Physics output hashes matching checkpoint: `24/24`.
- ML output hashes matching checkpoint: `24/24`.
- Physics validation status PASS: `24/24`.
- ML validation status PASS: `24/24`.
- Manifest rows missing output: `0`.
- Final output identities absent from manifest: `0`.
- Duplicate config hashes: `0`.
- Remaining `.tmp` files: `0`.
- Remaining run lock: `NO`.
- Total uncompressed physics + ML size: `798,305,057 bytes` (`0.743 GiB`).

The extra physics file `outputs/full_generation/physics/pa1_full_006.csv` is an
explicitly excluded V1 scientific debug artifact, not an orphan final output.

## 8. Tests

The complete regression and final-integrity suite passed:

```text
77 tests
77 PASS
0 FAIL
```

Coverage includes V2 manifest identity, all final file existence/row counts,
global totals, rejected-set exclusion, schema contract, forbidden-feature audit,
hash verification, finite values, and validation status.

## 9. Final gate

All success criteria are satisfied:

```text
24/24 V2 parameter sets -> full 2018-2025 PASS
1,683,072 valid physics rows
1,683,072 deployment-aligned ML rows
```

No training, sequence windowing, normalization, split, GRU, or LSTM work was
started in this milestone.
