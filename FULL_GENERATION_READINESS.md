# Full Generation Readiness

Status: `FULL_GENERATION_READY = YES`

## Final parameter sets

- Count: `24` (`1` baseline + `23` constrained-LHS sets).
- Approved CSV: `final_approved_parameter_sets.csv`.
- Machine-readable manifest: `final_approved_parameter_sets.yaml`.
- Manifest SHA-256: `194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8`.

## Sampling

- Method: `constrained_latin_hypercube_sampling`.
- Version: `pa1_constrained_lhs_v1`.
- Seed: `20260816`.
- Raw candidates generated: `23`.
- Joint-constraint rejects: `0`.
- Physics-preflight rejects: `0`.
- All five marginals use inverse triangular CDF mapping from LHS quantiles.

## Joint constraints

- `couple_et_coefficients`: `REQUIRE`; k_R and k_D are one approved coupled uncertainty axis.
- `reject_low_cd_high_et_wedge`: `REJECT_FOR_FULL_GENERATION_V1`; Persistent RH saturation at the adverse corner; both one-axis boundary relaxations passed.
- `reject_low_cd_high_irrigation_region`: `REJECT_FOR_FULL_GENERATION_V1`; High irrigation at the low-Cd boundary exceeded unchanged humidity guards even at baseline ET.
- `reject_moderate_low_cd_wet_high_et_corner`: `REJECT_FOR_FULL_GENERATION_V1`; C_d=0.30 was sufficient for high ET alone but not for simultaneous maximum irrigation and ET.
- `post_sample_physics_gate`: `REQUIRE`; A five-dimensional accepted space can be non-rectangular beyond the structured probes.

## Coverage

| Axis | Min | Max | Mean | Median | Std | Strata |
|---|---:|---:|---:|---:|---:|---:|
| `C_d` | 0.259879 | 0.642608 | 0.498994 | 0.523873 | 0.107686 | 23/23 |
| `eta_s` | 0.113752 | 0.199496 | 0.16669 | 0.170915 | 0.0234418 | 23/23 |
| `C_s` | 64453.5 | 89610.5 | 80047.8 | 81160.6 | 7116.69 | 23/23 |
| `irrigation_flow_L_h` | 5.44929 | 13.6181 | 9.94299 | 9.926 | 2.03518 | 23/23 |
| `ET_scale` | 1.00002 | 1.26104 | 1.09984 | 1.09104 | 0.0718771 | 23/23 |

## 30-day preflight

- Window: `2024-06-01T00:00` through `2024-06-30T23:00`.
- Weather hash: `2d014eb72e33a8686c01be5f0b699b38467158691ac7bc2db166853cb28b46de`.
- Simulator hash: `07b86fd9342a4c4a8fbadd7fd0fbb10b8d31befcf9ae797dd6ff53ce2f171336`.
- Approved: `24`; extreme-valid approved: `2`.
- Every final set passed schema/range, NaN/Inf, causal, root-water balance, indoor-vapour balance, Tsoil<=40 C, and RH saturation<=5% checks.
- Representative dt=60/120/300 stability: `PASS` for `5` sets.
- Reproducibility reruns: `PASS` for `3` sets.

## Full-generation estimate

- Physics rows: `70,128 x 24 = 1,683,072`.
- Estimated uncompressed physics CSV: `0.595 GiB`.
- Estimated uncompressed deployment ML CSV: `0.156 GiB`.
- Final configs: `438.6 KiB`; validation metadata: `180.3 KiB`.

## Remaining calibration caveats

- E8 root-zone solar coupling/capacity remain effective priors pending the fixed-depth soil sensor trajectory.
- E4 ET scale remains a coupled reduced-form axis pending water-loss and T/RH calibration.
- Emitter flow, substrate field capacity/wilting behavior, installed fan flow and soil-sensor percent-to-VWC mapping still require real PA1 measurement.
- Grow-light response is fixed and unidentifiable in the current OFF schedule.

## ML deployment contract

`ML_DATA_CONTRACT.md` is unchanged: five sensor variables plus three Raspberry Pi actuator states; physics/weather feature count remains zero.

## Next command

Proposed next-milestone interface (not executed in this task):

```text
python generate_full_synthetic_dataset.py --manifest final_approved_parameter_sets.yaml --weather nha_trang_weather_2018_2025.csv
```
