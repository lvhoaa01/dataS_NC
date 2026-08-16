# Full Generation Benchmark

Status: `SUCCESS`

`FULL_GENERATION_READY = YES`

## 1. Input audit

- Final manifest: `24` sets; SHA-256 `194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8`; locked hash match `PASS`.
- Baseline/non-baseline: `1/23`; unique IDs/config hashes: `24/24`.
- Weather: `70128` rows, `2018-01-01T00:00` through `2025-12-31T23:00`, timezone `Asia/Ho_Chi_Minh`; gaps/duplicates/nonfinite `0/0/0`.
- Weather SHA-256: `61bdf841a0f6b7d98bf27951ab3a89e93a4ce13ab48e85acc1b1513e246e0734`; 2024 rows/leap-day rows: `8784/24`.
- Approved simulator hash `07b86fd9342a4c4a8fbadd7fd0fbb10b8d31befcf9ae797dd6ff53ce2f171336` changed to `058bfd097ded4cb91c2098634bedfa28f3160392895cf0c2a48cfc4069ce9771` after generic range/state-handoff APIs. June baseline numerical regression remained exactly `0.0`.

## 2. Runner architecture

`final manifest + weather -> deterministic simulator -> atomic physics master -> locked validator -> atomic ML extraction -> ML validator -> hashes/state`.

One file is produced per parameter set. Full mode uses one continuous 2018-2025 simulator call per set, so state is initialized only at 2018-01-01 and is never reset at year boundaries.

## 3. Checkpoint/resume design

States: `PENDING -> RUNNING -> PHYSICS_DONE -> PHYSICS_VALIDATED -> ML_DONE -> ML_VALIDATED -> COMPLETE`; failures and interrupts remain non-complete. COMPLETE cache entries are skipped only after config/weather identity, files, rows, schemas, hashes and validation metadata are rechecked.

## 4. Atomic-output design

Physics, ML, state, configs, logs and manifests use same-directory `.tmp`, flush/fsync and atomic replace. Bounded retry handles observed transient Windows scanner locks; no benchmark `.tmp` remains.

## 5. Benchmark environment

- Platform: `Windows-11-10.0.26200-SP0`; Python `3.13.13`; logical CPUs `8`.
- Peak process RSS: `92.84 MiB` measured by Windows process peak working set.
- Execution policy: sequential, one worker, canonical `dt=60 s`.

## 6. Benchmark scope

Baseline `pa1_full_000_baseline`, standalone calendar year `2024`, `8784` hourly rows including all 24 leap-day hours, `527,040` one-minute integration intervals.

## 7. Runtime breakdown

| Run | Physics s | Total s | Physics hash | ML hash |
|---|---:|---:|---|---|
| `run_1` | 71.785 | 72.649 | `6979ac51d819` | `d1cc575bfa99` |
| `run_2` | 72.590 | 73.442 | `6979ac51d819` | `d1cc575bfa99` |

Central means: physics `72.188s`; physics write `0.261s`; physics validation `0.119s`; ML extraction `0.195s`; ML write `0.049s`; ML validation `0.078s`; total `73.046s`.

## 8. Throughput

Mean simulation throughput: `121.687` hourly rows/s and `7301.2` one-minute intervals/s.

## 9. Memory

Peak RSS: `97,349,632 bytes` (`92.84 MiB`).

## 10. File sizes

- 2024 physics/ML/validation: `3,368,828` / `869,568` / `10,536` bytes.
- Estimated 8-year per scenario physics/ML: `26,895,397` / `6,942,289` bytes.

## 11. Full runtime estimate

Measured row ratio is `70,128 / 8,784 = 7.983607`; 24-set multiplier `191.606557`.
Sequential estimate: optimistic `3h 52m 0.1s`, central `3h 53m 16.0s`, conservative `4h 29m 42.8s`. These are approximate; scenario paths and machine load may differ.
Recommended default workers: `1`; central estimate remains `3h 53m 16.0s`. Parallelism is deferred until multi-scenario CPU/disk behavior is measured.

## 12. Full storage estimate

Physics `645,489,535` bytes (`0.601 GiB`), ML `166,614,931` bytes (`0.155 GiB`), metadata `1,058,112` bytes; total `0.757 GiB` uncompressed.
Versus readiness estimate: physics `+0.99%`, ML `-0.33%`.

## 13. Reproducibility

Two independent runs produced identical physics SHA-256 `6979ac51d8196224959bfe847817e72770f2d844b67e8c6d720568802637a730` and ML SHA-256 `d1cc575bfa99bff630ff0c43f28624bb7dda785db6696d99c00996efb6e7d37c`: `PASS`.

## 14. Physics validation

Schema/ranges, NaN/Inf, causal tests, balances and joint guards: `PASS`. Tair `20.728..40.096 C`; RH saturation `56/8784` (`0.638%`), longest `4 h`; Tsoil max `38.188 C`; theta `0.191382..0.407949`.

## 15. ML contract validation

`8784` rows x `9` columns, observation mode `physics_true_state`, sensor noise disabled. Five sensor variables + three actuator states; physics/weather feature count `0/0`. Soil moisture remains a VWC-like state requiring a real ES-SM-TH-01 calibration adapter.

## 16. Failure/recovery test

Actual 72-hour run reached COMPLETE and rerun recorded `SKIPPED_COMPLETE`. Unit fixtures verified RUNNING/interrupted, partial `.tmp`, config mismatch and weather mismatch all rerun instead of skip. KeyboardInterrupt marks INTERRUPTED and preserves prior COMPLETE scenarios.

## 17. Full-run readiness

- `manifest_audit`: `PASS`.
- `weather_audit`: `PASS`.
- `physics_validation`: `PASS`.
- `ml_validation`: `PASS`.
- `reproducibility`: `PASS`.
- `resume_complete_skip`: `PASS`.
- `atomic_outputs`: `PASS`.
- `full_mode_not_executed`: `PASS`.

Final gate: `FULL_GENERATION_READY = YES`.

Full `24 x 2018-2025` generation was not started. The next milestone may run `python run_full_generation.py --full` only after user audit of this report.
