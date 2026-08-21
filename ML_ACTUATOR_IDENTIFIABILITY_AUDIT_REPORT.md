# ML Actuator Identifiability Audit: Implementation Report

Date: `2026-08-21` (`Asia/Saigon`)

## Execution Mode

This report covers Notebook 05 implementation and a bounded local smoke run only.
It is not a scientific actuator-support result.

```text
FULL_ACTUATOR_AUDIT_EXECUTED = NO
SCIENTIFIC_READINESS_CONCLUSION_AVAILABLE = NO
FINAL_TESTS_EXECUTED = NO
LLM_USED = NO
COLAB_READY = YES
```

The authoritative predecessor is
`notebooks/04_operational_lookback_ablation_FULL_FIXED.ipynb`. It was read and
was not modified. The locked operational contract remains a 24-hour lookback,
forecast horizons `(1, 3)`, 8 input features, and 5 targets.

## Colab Bootstrap

Notebook 05 now has an explicit bootstrap cell before the audit-helper import.
In Google Colab it mounts `/content/drive` and configures:

- `GREENHOUSE_DATA_ROOT=/content/drive/MyDrive/smart_greenhouse_dataset`
- `GREENHOUSE_PREPROCESSING_ARTIFACT_DIR=/content/drive/MyDrive/smart_greenhouse_dataset/artifacts/preprocessing`
- `GREENHOUSE_ACTUATOR_AUDIT_ARTIFACT_DIR=/content/drive/MyDrive/smart_greenhouse_dataset/artifacts/actuator_identifiability_audit`
- `GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST=false`

Before the helper import, it asserts that
`/content/drive/MyDrive/smart_greenhouse_dataset/actuator_identifiability_audit.py`
exists and gives a corrective error if it is missing. The bootstrap has no CUDA
gate. Outside Colab it preserves the existing environment and local helper-path
discovery behavior.

## Temporal Semantics

The audit traces `physics/simulator.py` and
`config/greenhouse_parameters.yaml` instead of inferring timing from column names.
At timestamp `t`, a CSV row stores the state at the start of the hour and the
controller command sampled at that boundary. The controller is evaluated again
at every 60-second integration substep, so `action[t]` is not necessarily held
for the full following hour. A transition is therefore a change in the sampled
boundary command, and `sensor[t+h] - sensor[t]` is a descriptive post-transition
response at `h = 1` or `3` hours. It is not a causal effect estimate.

The controller is stateless. The configured pump command is a 60-second pulse at
06:00 and 18:00, the fan is threshold controlled, and the grow light baseline is
fixed OFF.

## Data Coverage

Full mode is designed to use the 20 locked development scenarios only, with
TRAIN `2018-01-01` through `2023-12-31` and VALIDATION during 2024. Held-out
scenario paths are neither resolved nor loaded, and 2025 final temporal data is
not used.

The local smoke used one development scenario (`pa1_full_002`) and deterministic
bounded windows:

- TRAIN: `2018-06-01 00:00` through `2018-06-21 23:00` (504 rows).
- VALIDATION: `2024-06-01 00:00` through `2024-06-14 23:00` (336 rows).

These rows exercise integration paths only and must not be interpreted as the
full support distribution.

## Audit Implementation

The notebook implements separate TRAIN/VALIDATION diagnostics for:

- Pump, fan, and grow-light ON/OFF coverage by scenario.
- `0->0`, `0->1`, `1->0`, and `1->1` transitions without crossing scenario or
  split boundaries.
- ON/OFF dwell-time distributions.
- All eight joint action codes in `(pump, fan, grow_light)` order.
- Deterministic coarse state-conditioned action overlap.
- Compact transition events with valid `+1h` and `+3h` sensor responses.
- Raw and clean single-actuator descriptive response signatures.
- Stable ON/OFF no-change reference windows.
- State-matched descriptive diagnostics.
- Pre-action confounding summaries and standardized mean differences.
- Scenario-level support and TRAIN/VALIDATION shift summaries.

The matching diagnostic is secondary and explicitly non-causal. It uses bounded,
deterministic sampling and `sklearn.neighbors.NearestNeighbors` with standardized
current sensor state. Matching stays within the same split, scenario, target
action state, hour of day, and other-actuator state. Smoke and full modes use
separate centralized caps, avoiding whole-dataset quadratic work.

## Actuator Sections

### Pump Audit

Usage, transitions, dwell, overlap, clean events, reference windows, response
signatures, matching, confounding, and scenario support are implemented. Smoke
confirmed that each code path executes. No full-data pump readiness conclusion
is available.

### Fan Audit

The same complete diagnostic path is implemented and exercised by smoke. Because
fan commands are state-triggered, all outputs use conditional-association and
descriptive-response wording. No causal or scientific readiness claim is made.

### Grow-Light Audit

The pipeline handles absent transitions and zero support without fabricating
effects. Smoke observed the configured fixed-OFF policy, but this bounded result
is not substituted for the required full audit.

## Joint Support And Overlap

Joint-action coverage, empirical state-conditioned overlap, and sample-weighted
overlap are exported. Hour of day is used only as an audit diagnostic; it is not
added to deployment features. Overlap is labelled empirical support, not proof of
causal positivity.

## Transition, Matching, And Confounding

Event extraction rejects targets outside the active split and never crosses
scenario boundaries. Clean-event filters enforce stability of the two other
actuators over the response horizon. Matching reports matched/unmatched support
and distance distributions rather than forcing unsupported comparisons.
Confounding diagnostics compare the pre-action state distributions of transitions
and stable references.

## Train/Validation Stability

The implementation compares usage, transition rates, joint action coverage,
overlap, and response signatures across TRAIN and VALIDATION. The smoke run only
verified execution and export; it did not establish distributional stability.

## Artifacts

The committed notebook defaults to immutable mode-specific destinations:

- Full: `artifacts/actuator_identifiability_audit/`
- Smoke: `artifacts/actuator_identifiability_audit_smoke/`

The validator used an isolated temporary smoke root at
`outputs/actuator_identifiability_notebook_smoke/actuator_identifiability_audit_smoke/`.
Runtime assertions require the directory leaf to match the immutable execution
mode, so smoke cannot write into the full destination. Smoke exported 12 metric
CSVs, 8 plots, temporal semantics/config/manifest JSON, and readiness metadata.
Runtime artifacts are ignored by Git.

## Validation

- Notebook JSON: PASS (58 physical cells, 29 code cells).
- All code cells compile: PASS.
- Concepts synchronization: PASS (28 logical sections).
- Bounded smoke execution: PASS.
- Focused Notebook 05 tests: 45/45 PASS.
- Complete repository regression suite: 256/256 PASS.
- Model classes, optimizers, and training loops: absent.
- LLM/API clients: absent.
- Held-out paths resolved or loaded: NO.
- Final tests executed: NO.

## Limitations And Readiness

`ACTION_CONDITIONED_MODEL_READINESS` remains `REVIEW_REQUIRED` for smoke mode by
design. Scientific readiness requires execution over all 20 development scenarios
and the complete locked TRAIN/VALIDATION ranges. That full actuator audit was not
run locally, so this report does not classify the dataset as `READY`, `PARTIAL`,
or `TARGETED_DATA_REQUIRED`.

## Next Step

The user may run Notebook 05 full actuator audit separately in Colab or another
managed environment. Only the resulting full artifacts may support a scientific
readiness conclusion. Do not start Notebook 06, model training, targeted synthetic
generation, MPC, or any LLM phase from this smoke report.
