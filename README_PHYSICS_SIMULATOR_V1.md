# SmartGarden Physics Simulator V1

This workspace contains a deterministic reduced-order greenhouse simulator implementing E0-E10
from `GREENHOUSE_PHYSICS_DATASET_KNOWLEDGE.md`. Hardware baselines and parameter provenance come
from `GREENHOUSE_HARDWARE_PARAMETER_KNOWLEDGE.md`.

Run the complete 30-day simulation and validation with:

```powershell
python .\scripts\run_simulator_test.py
```

The command validates the full raw-weather file, runs the June 2024 simulation at 60-second internal
resolution, compares 60/120/300-second integration, executes controlled causal tests, and audits
root-zone water, indoor vapour, and indoor-air energy balances.

Production artifacts are written only when all required checks pass:

```text
outputs/greenhouse_simulation_30days.csv
outputs/greenhouse_simulation_30days_validation.json
```

`config/greenhouse_parameters.yaml` is JSON-compatible YAML so the simulator remains standard-library
only. Every parameter record includes `value`, `unit`, `provenance`, `status`, and `source`. Parameters
marked `TO_MEASURE`, `TO_CALIBRATE`, or `INITIAL_PRIOR_*` are executable V1 priors, not measured truth.

Sensor noise is disabled. Open-Meteo soil temperature and moisture remain context columns and never
replace the independent E8/E9 greenhouse pot/root-zone states.
