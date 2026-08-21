# Actuator Audit Implementation Status

Date: `2026-08-21` (`Asia/Saigon`)

```text
FULL_ACTUATOR_AUDIT_EXECUTED = NO
SCIENTIFIC_READINESS_CONCLUSION_AVAILABLE = NO
LOCAL_SMOKE = PASS
NEXT_RESUME_POINT = user-run full Notebook 05 actuator audit separately; do not infer scientific readiness until that execution completes
```

## Files created or updated

- `actuator_identifiability_audit.py`
- `scripts/build_notebook_05.py`
- `notebooks/05_actuator_intervention_identifiability_audit.ipynb`
- `notebooks/05_actuator_intervention_identifiability_audit_CONCEPTS.md`
- `ML_ACTUATOR_IDENTIFIABILITY_AUDIT_REPORT.md`
- `validate_actuator_identifiability_notebook.py`
- `tests/test_actuator_identifiability_notebook.py`
- `.gitignore`

The authoritative `notebooks/04_operational_lookback_ablation_FULL_FIXED.ipynb`
was read but not modified.

## Implemented sections

Notebook 05 contains 28 logical sections / 56 physical cells covering the locked
split and canonical index, source-traced actuator timing, usage, transitions,
dwell time, joint actions, empirical state overlap, `+1h/+3h` transition events,
clean events, no-change references, state matching, confounding, scenario support,
TRAIN/VALIDATION shift, plots, readiness logic and artifact export.

Temporal semantics were traced to `physics/simulator.py`: each CSV row stores the
state and controller command sampled at the hour boundary; the controller is
re-evaluated every 60-second internal step. Pump is a 60-second pulse at 06:00 and
18:00, fan is threshold-controlled, and grow light is fixed OFF.

## Validation completed

- Static notebook validation: `PASS`.
- Notebook JSON/schema and all code-cell compilation: `PASS`.
- Concepts synchronization: `PASS`.
- Local June smoke, one development scenario: `PASS`.
- Smoke outputs: 12 metric CSVs and 8 plots.
- Held-out paths resolved: `NO`.
- Held-out CSV loaded: `NO`.
- Model training / optimizer / LLM API: `NO`.
- State-matched response diagnostic: deterministic bounded 1-nearest-neighbor
  implementation; smoke and full modes have separate event/reference caps.
- Focused Notebook 05 tests: `44/44 PASS`.
- Complete historical project regression suite: `255/255 PASS`.

Smoke readiness remains `REVIEW_REQUIRED` by design and is not a scientific result.

## Prior stopped execution

The full local command was stopped by user request:

```powershell
.\.venv\Scripts\jupyter-nbconvert.exe --to notebook --execute notebooks\05_actuator_intervention_identifiability_audit.ipynb --output 05_actuator_intervention_identifiability_audit.executed.ipynb --output-dir $env:TEMP --ExecutePreprocessor.timeout=1800
```

Execution had reached the expensive Section 20 state-matched nearest-reference
diagnostic. The `jupyter-nbconvert` process and its Python/kernel child processes
were terminated. `artifacts/actuator_identifiability_audit/` was not produced, so
there is no incomplete full artifact set to interpret.

The matching bottleneck has since been replaced without rerunning the full audit.
`ML_ACTUATOR_IDENTIFIABILITY_AUDIT_REPORT.md` now records implementation and smoke
validation only; it intentionally contains no scientific readiness conclusion.
