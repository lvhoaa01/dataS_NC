"""Build the source-controlled Notebook 05 JSON deterministically."""

from __future__ import annotations

from pathlib import Path
import textwrap

import nbformat


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "notebooks" / "05_actuator_intervention_identifiability_audit.ipynb"


COLAB_BOOTSTRAP = """import os
from pathlib import Path

try:
    from google.colab import drive as colab_drive
except ImportError:
    colab_drive = None

IN_GOOGLE_COLAB = colab_drive is not None
if IN_GOOGLE_COLAB:
    colab_drive.mount("/content/drive")

    DATA_ROOT = Path("/content/drive/MyDrive/smart_greenhouse_dataset")
    COLAB_FULL_AUDIT_ARTIFACT_DIR = (
        DATA_ROOT / "artifacts" / "actuator_identifiability_audit"
    )

    os.environ["GREENHOUSE_DATA_ROOT"] = str(DATA_ROOT)
    os.environ["GREENHOUSE_PREPROCESSING_ARTIFACT_DIR"] = str(
        DATA_ROOT / "artifacts" / "preprocessing"
    )
    os.environ["GREENHOUSE_ACTUATOR_AUDIT_ARTIFACT_DIR"] = str(
        COLAB_FULL_AUDIT_ARTIFACT_DIR
    )
    os.environ["GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST"] = "false"

    HELPER_MODULE_PATH = DATA_ROOT / "actuator_identifiability_audit.py"
    assert HELPER_MODULE_PATH.is_file(), (
        "Notebook 05 Colab bootstrap cannot find the audit helper at "
        f"{HELPER_MODULE_PATH}. Place actuator_identifiability_audit.py in "
        f"{DATA_ROOT} on Google Drive, then restart and run the notebook from "
        "the first cell."
    )

    print("Notebook 05 Colab bootstrap PASS")
    print("DATA_ROOT =", DATA_ROOT)
    print("FULL_AUDIT_ARTIFACT_DIR =", COLAB_FULL_AUDIT_ARTIFACT_DIR)
else:
    print("Local runtime detected; preserving existing path/environment settings.")
"""


SECTIONS: list[tuple[str, str, str]] = [
    (
        "00",
        "Experiment Overview",
        """EXPERIMENT_SCOPE = (
    "Actuator coverage and descriptive intervention support audit; "
    "no model training and no causal-identification claim."
)""",
    ),
    (
        "01",
        "Context from Notebook 04 FULL_FIXED",
        """AUTHORITATIVE_NOTEBOOK_04_NAME = "04_operational_lookback_ablation_FULL_FIXED.ipynb"
OPERATIONAL_LOOKBACK = 24
FORECAST_HORIZONS = (1, 3)
EXPECTED_FULL_TRAIN_WINDOWS = 1_050_200
EXPECTED_FULL_VALIDATION_WINDOWS = 175_640""",
    ),
    (
        "02",
        "Configuration",
        """ACTUATOR_AUDIT_SMOKE_TEST = False
ACTUATOR_AUDIT_SMOKE_TEST = parse_bool(
    os.getenv("GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST"),
    ACTUATOR_AUDIT_SMOKE_TEST,
)
AUDIT_CONFIG = AuditConfig()
EXECUTION_MODE = "SMOKE_ONLY_NOT_SCIENTIFIC" if ACTUATOR_AUDIT_SMOKE_TEST else "FULL"
np.random.seed(AUDIT_CONFIG.seed)
print(f"Execution mode: {EXECUTION_MODE}")""",
    ),
    (
        "03",
        "Imports",
        """# Imports are intentionally CPU-only data-analysis dependencies.
assert tuple(ACTUATORS) == ("pump_state", "fan_state", "grow_light_state")
assert tuple(HORIZONS) == FORECAST_HORIZONS""",
    ),
    (
        "04",
        "Reproducibility",
        """REPRODUCIBILITY = {
    "seed": AUDIT_CONFIG.seed,
    "deterministic_binning": True,
    "deterministic_matching": True,
    "threshold_scope": "AUDIT_HEURISTIC_NOT_UNIVERSAL_THRESHOLD",
}""",
    ),
    (
        "05",
        "Paths",
        """DATA_ROOT = Path(os.getenv("GREENHOUSE_DATA_ROOT", str(Path.cwd()))).expanduser().resolve()
PREPROCESSING_ARTIFACT_DIR = Path(os.getenv(
    "GREENHOUSE_PREPROCESSING_ARTIFACT_DIR",
    str(DATA_ROOT / "artifacts" / "preprocessing"),
)).expanduser().resolve()
FULL_AUDIT_ARTIFACT_DIR = (DATA_ROOT / "artifacts" / "actuator_identifiability_audit").resolve()
SMOKE_AUDIT_ARTIFACT_DIR = (DATA_ROOT / "artifacts" / "actuator_identifiability_audit_smoke").resolve()
default_audit_artifact_dir = (
    SMOKE_AUDIT_ARTIFACT_DIR if ACTUATOR_AUDIT_SMOKE_TEST else FULL_AUDIT_ARTIFACT_DIR
)
AUDIT_ARTIFACT_DIR = Path(os.getenv(
    "GREENHOUSE_ACTUATOR_AUDIT_ARTIFACT_DIR",
    str(default_audit_artifact_dir),
)).expanduser().resolve()
expected_artifact_leaf = (
    "actuator_identifiability_audit_smoke"
    if ACTUATOR_AUDIT_SMOKE_TEST
    else "actuator_identifiability_audit"
)
assert AUDIT_ARTIFACT_DIR.name == expected_artifact_leaf, (
    f"{EXECUTION_MODE} must write to a {expected_artifact_leaf!r} directory, "
    f"not {AUDIT_ARTIFACT_DIR}"
)
assert FULL_AUDIT_ARTIFACT_DIR != SMOKE_AUDIT_ARTIFACT_DIR
METRICS_DIR = AUDIT_ARTIFACT_DIR / "metrics"
PLOTS_DIR = AUDIT_ARTIFACT_DIR / "plots"
INDEX_FILE = DATA_ROOT / "full_dataset_index.csv"
FULL_FIXED_NOTEBOOK = DATA_ROOT / "notebooks" / AUTHORITATIVE_NOTEBOOK_04_NAME
SIMULATOR_SOURCE = DATA_ROOT / "physics" / "simulator.py"
PARAMETER_CONFIG_SOURCE = DATA_ROOT / "config" / "greenhouse_parameters.yaml"
assert FULL_FIXED_NOTEBOOK.is_file(), f"Missing authoritative Notebook 04: {FULL_FIXED_NOTEBOOK}"
full_fixed_text = FULL_FIXED_NOTEBOOK.read_text(encoding="utf-8")
for required in ('LOOKBACK_CANDIDATES = (24, 48, 72)', 'FORECAST_HORIZONS = (1, 3)', 'FULL_FIXED'):
    assert required in full_fixed_text, f"Authoritative Notebook 04 contract missing: {required}"
AUTHORITATIVE_NOTEBOOK_04_HASH = sha256_file(FULL_FIXED_NOTEBOOK)
print(f"Authoritative Notebook 04: {FULL_FIXED_NOTEBOOK}")""",
    ),
    (
        "06",
        "Load Locked Split and Canonical Index",
        """split_manifest, preprocessing_config = load_locked_split(
    PREPROCESSING_ARTIFACT_DIR / "split_manifest.json",
    PREPROCESSING_ARTIFACT_DIR / "preprocessing_config.json",
)
canonical_index = load_canonical_index(INDEX_FILE)
development_scenario_ids = list(split_manifest["development_scenario_ids"])
held_out_scenario_ids = list(split_manifest["held_out_scenario_ids"])
assert len(development_scenario_ids) == 20 and len(held_out_scenario_ids) == 4
assert not set(development_scenario_ids) & set(held_out_scenario_ids)
assert tuple(preprocessing_config["feature_columns"]) == tuple(FEATURES)
assert tuple(preprocessing_config["target_columns"]) == tuple(SENSORS)""",
    ),
    (
        "07",
        "Resolve Development Scenarios Only",
        """active_development_ids = development_scenario_ids[:1] if ACTUATOR_AUDIT_SMOKE_TEST else development_scenario_ids
development_scenario_paths = resolve_development_paths(
    canonical_index,
    active_development_ids,
    held_out_scenario_ids,
    DATA_ROOT,
)
assert set(development_scenario_paths) == set(active_development_ids)
assert not set(development_scenario_paths) & set(held_out_scenario_ids)
HELD_OUT_PATHS_RESOLVED = False
HELD_OUT_CSV_LOADED = False""",
    ),
    (
        "08",
        "Trace Actuator Temporal Semantics",
        """actuator_temporal_semantics = trace_actuator_temporal_semantics(
    SIMULATOR_SOURCE,
    PARAMETER_CONFIG_SOURCE,
)
TEMPORAL_SEMANTICS_VERIFIED = actuator_temporal_semantics["verified"]
if not TEMPORAL_SEMANTICS_VERIFIED:
    print("WARNING: temporal semantics markers were not all verified; readiness will be REVIEW_REQUIRED")""",
    ),
    (
        "09",
        "Load and Validate Per-Scenario Data",
        """audit_frames = load_audit_frames(
    development_scenario_paths,
    split_manifest["train_date_range"],
    split_manifest["validation_date_range"],
    smoke_test=ACTUATOR_AUDIT_SMOKE_TEST,
    config=AUDIT_CONFIG,
)
for (split, scenario_id), frame in audit_frames.items():
    validate_binary_actuators(frame)
    assert split in SPLITS and scenario_id in active_development_ids
matching_sensor_mean, matching_sensor_scale = derive_train_sensor_standardization(audit_frames)
print({key: len(value) for key, value in audit_frames.items()})""",
    ),
    (
        "10",
        "Actuator Usage Coverage",
        """usage_summary = actuator_usage_summary(audit_frames)
assert len(usage_summary) == len(SPLITS) * len(ACTUATORS)
display(usage_summary)""",
    ),
    (
        "11",
        "Transition Detection",
        """transition_summary = actuator_transition_summary(audit_frames)
assert set(transition_summary["transition"]) == {"00", "01", "10", "11"}
display(transition_summary.loc[transition_summary["transition"].isin(["01", "10"])])""",
    ),
    (
        "12",
        "Dwell-Time Analysis",
        """dwell_summary, raw_dwell_runs = actuator_dwell_summary(audit_frames)
assert set(dwell_summary["state"]).issubset({0, 1})
display(dwell_summary)""",
    ),
    (
        "13",
        "Joint Action Coverage",
        """joint_summary = joint_action_coverage(audit_frames)
assert set(joint_summary["joint_action"]) == set(JOINT_CODES)
assert joint_summary["actuator_order"].eq("pump|fan|grow_light").all()
display(joint_summary)""",
    ),
    (
        "14",
        "State-Conditioned Action Overlap",
        """overlap_edges = derive_overlap_edges(audit_frames, AUDIT_CONFIG)
overlap_summary = state_conditioned_overlap(audit_frames, overlap_edges)
assert overlap_summary["sample_weighted_overlap_fraction"].between(0, 1).all()
display(overlap_summary)""",
    ),
    (
        "15",
        "Transition Event Construction",
        """transition_events = build_transition_events(audit_frames)
if not transition_events.empty:
    assert transition_events["scenario_id"].isin(active_development_ids).all()
    assert transition_events["split"].isin(SPLITS).all()
print(f"Compact transition events in active audit: {len(transition_events):,}")""",
    ),
    (
        "16",
        "+1h / +3h Response Semantics",
        """RESPONSE_DEFINITION = "delta_Y_h = sensor[t+h] - sensor[t]"
RESPONSE_ALIGNMENT = {
    "horizons": list(HORIZONS),
    "action_row": "action[t] is the start-of-hour command",
    "target_bounds": "same scenario and same TRAIN/VALIDATION frame",
    "units": TARGET_UNITS,
    "interpretation": "descriptive post-transition association; not a causal effect",
}
assert HORIZONS == (1, 3)""",
    ),
    (
        "17",
        "Raw Transition Response",
        """raw_response_summary = aggregate_response(transition_events, clean=False)
if not raw_response_summary.empty:
    assert set(raw_response_summary["horizon_h"]) == set(HORIZONS)
display(raw_response_summary.head(12))""",
    ),
    (
        "18",
        "Clean Single-Actuator Events",
        """clean_response_summary = aggregate_response(transition_events, clean=True)
clean_event_counts = (
    transition_events.groupby(["split", "actuator", "direction"])[["clean_1h", "clean_3h"]].sum().reset_index()
    if not transition_events.empty else pd.DataFrame()
)
display(clean_event_counts)""",
    ),
    (
        "19",
        "No-Change Reference Windows",
        """no_change_reference_summary = summarize_no_change_references(audit_frames)
assert (no_change_reference_summary["count"] >= 0).all()""",
    ),
    (
        "20",
        "State-Matched Response Diagnostic",
        """matched_summary = matched_response_diagnostic(
    transition_events,
    audit_frames,
    matching_sensor_mean,
    matching_sensor_scale,
    config=AUDIT_CONFIG,
    smoke_test=ACTUATOR_AUDIT_SMOKE_TEST,
)
MATCHING_SUPPORT = (
    "LIMITED"
    if matched_summary.empty
    or float(matched_summary["unmatched_fraction"].mean()) > 0.25
    else "OBSERVED"
)
display(matched_summary.head(12))""",
    ),
    (
        "21",
        "Confounding Diagnostics",
        """confounding_summary = confounding_diagnostics(transition_events, audit_frames)
assert np.isfinite(confounding_summary.select_dtypes(include=[np.number]).to_numpy()).all()
display(confounding_summary.head(12))""",
    ),
    (
        "22",
        "Scenario-Level Support",
        """scenario_support_summary = support_by_scenario(audit_frames, transition_events)
assert set(scenario_support_summary["scenario_id"]) == set(active_development_ids)
display(scenario_support_summary.head(12))""",
    ),
    (
        "23",
        "Train vs Validation Stability",
        """shift_summary = train_validation_shift(usage_summary, transition_summary, joint_summary, raw_response_summary)
assert set(shift_summary.columns) == {"metric", "key", "train_value", "validation_value", "validation_minus_train"}
display(shift_summary.head(12))""",
    ),
    (
        "24",
        "Plot Diagnostics",
        """PLOTS_DIR.mkdir(parents=True, exist_ok=True)

def save_plot(filename, draw):
    fig, axis = plt.subplots(figsize=(8, 4.5))
    draw(axis)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / filename, dpi=140)
    plt.close(fig)

save_plot("actuator_on_fraction.png", lambda ax: usage_summary.pivot(index="actuator", columns="split", values="on_fraction").plot.bar(ax=ax, ylabel="ON fraction"))
save_plot("actuator_transition_counts.png", lambda ax: transition_summary.loc[transition_summary.transition.isin(["01", "10"])].pivot_table(index="actuator", columns=["split", "transition"], values="count").plot.bar(ax=ax, ylabel="count"))
save_plot("actuator_dwell_times.png", lambda ax: raw_dwell_runs.loc[raw_dwell_runs.state == 1].boxplot(column="duration_hours", by="actuator", ax=ax))
save_plot("joint_action_coverage.png", lambda ax: joint_summary.pivot(index="joint_action", columns="split", values="fraction").plot.bar(ax=ax, ylabel="fraction"))
save_plot("state_overlap_summary.png", lambda ax: overlap_summary.pivot(index="actuator", columns="split", values="sample_weighted_overlap_fraction").plot.bar(ax=ax, ylabel="sample-weighted overlap"))

def draw_response(axis, horizon):
    selected = raw_response_summary.loc[(raw_response_summary.horizon_h == horizon) & (raw_response_summary.target.isin(["air_temperature", "soil_moisture", "light_lux"]))]
    if selected.empty:
        axis.text(0.5, 0.5, "No transition support", ha="center")
    else:
        selected.assign(key=selected.actuator + ":" + selected.direction + ":" + selected.target).plot.bar(x="key", y="mean", ax=axis, legend=False, ylabel="mean physical-unit delta")

save_plot("transition_response_1h.png", lambda ax: draw_response(ax, 1))
save_plot("transition_response_3h.png", lambda ax: draw_response(ax, 3))
save_plot("confounding_diagnostics.png", lambda ax: confounding_summary.loc[confounding_summary.sensor.isin(["air_temperature", "soil_moisture", "light_lux"])].groupby(["actuator", "group"])["standardized_mean_difference_vs_reference"].mean().unstack(fill_value=0).plot.bar(ax=ax, ylabel="mean SMD"))
assert all((PLOTS_DIR / name).is_file() for name in PLOT_FILENAMES)""",
    ),
    (
        "25",
        "Readiness Assessment",
        """readiness = assess_readiness(
    usage_summary,
    transition_summary,
    overlap_summary,
    transition_events,
    temporal_semantics_verified=TEMPORAL_SEMANTICS_VERIFIED,
    smoke_test=ACTUATOR_AUDIT_SMOKE_TEST,
    config=AUDIT_CONFIG,
)
ACTION_CONDITIONED_MODEL_READINESS = readiness["status"]
print(json.dumps(readiness, indent=2))""",
    ),
    (
        "26",
        "Save Artifacts",
        """metric_frames = {
    "actuator_usage_summary.csv": usage_summary,
    "actuator_transition_summary.csv": transition_summary,
    "actuator_dwell_time_summary.csv": dwell_summary,
    "joint_action_coverage.csv": joint_summary,
    "state_conditioned_action_overlap.csv": overlap_summary,
    "actuator_transition_response.csv": raw_response_summary,
    "clean_transition_response.csv": clean_response_summary,
    "matched_response_diagnostic.csv": matched_summary,
    "actuator_confounding_diagnostics.csv": confounding_summary,
    "actuator_support_by_scenario.csv": scenario_support_summary,
    "no_change_reference_summary.csv": no_change_reference_summary,
    "train_validation_actuator_shift.csv": shift_summary,
}
save_metric_frames(metric_frames, METRICS_DIR)
save_json_atomic(actuator_temporal_semantics, AUDIT_ARTIFACT_DIR / "actuator_temporal_semantics.json")
save_json_atomic({
    **AUDIT_CONFIG.as_dict(),
    "smoke_test": ACTUATOR_AUDIT_SMOKE_TEST,
    "operational_lookback": OPERATIONAL_LOOKBACK,
    "forecast_horizons": list(FORECAST_HORIZONS),
    "overlap_variables": OVERLAP_VARIABLES,
    "overlap_train_edges": overlap_edges,
    "matching_standardization": {
        "source": "active development TRAIN sensor rows",
        "mean": matching_sensor_mean.tolist(),
        "scale": matching_sensor_scale.tolist(),
    },
}, AUDIT_ARTIFACT_DIR / "actuator_audit_config.json")
audit_manifest = {
    "execution_mode": EXECUTION_MODE,
    "artifact_isolation_status": "PASS",
    "full_artifact_dir": str(FULL_AUDIT_ARTIFACT_DIR),
    "smoke_artifact_dir": str(SMOKE_AUDIT_ARTIFACT_DIR),
    "authoritative_notebook_04": str(FULL_FIXED_NOTEBOOK),
    "authoritative_notebook_04_sha256": AUTHORITATIVE_NOTEBOOK_04_HASH,
    "canonical_index": str(INDEX_FILE),
    "canonical_index_sha256": sha256_file(INDEX_FILE),
    "split_manifest": str(PREPROCESSING_ARTIFACT_DIR / "split_manifest.json"),
    "split_manifest_sha256": sha256_file(PREPROCESSING_ARTIFACT_DIR / "split_manifest.json"),
    "preprocessing_source_was_smoke": bool(preprocessing_config.get("smoke_test_execution", False)),
    "canonical_scenarios": len(canonical_index),
    "development_scenario_ids": development_scenario_ids,
    "active_development_scenario_ids": active_development_ids,
    "held_out_scenario_ids_provenance_only": held_out_scenario_ids,
    "held_out_paths_resolved": HELD_OUT_PATHS_RESOLVED,
    "held_out_csv_loaded": HELD_OUT_CSV_LOADED,
    "train_range": split_manifest["train_date_range"],
    "validation_range": split_manifest["validation_date_range"],
    "final_tests_executed": False,
    "model_training_executed": False,
    "causal_claim_made": False,
}
save_json_atomic(audit_manifest, AUDIT_ARTIFACT_DIR / "actuator_audit_manifest.json")
save_json_atomic(readiness, AUDIT_ARTIFACT_DIR / "actuator_readiness.json")""",
    ),
    (
        "27",
        "Final Audit Summary",
        """experiment_summary = {
    "status": "PASS",
    "execution_mode": audit_manifest["execution_mode"],
    "temporal_semantics_verified": TEMPORAL_SEMANTICS_VERIFIED,
    "development_scenarios": len(development_scenario_ids),
    "active_development_scenarios": len(active_development_ids),
    "held_out_csv_loaded": HELD_OUT_CSV_LOADED,
    "operational_contract": {"lookback": 24, "horizons": [1, 3], "input_shape": ["B", 24, 8], "output_shape": ["B", 2, 5]},
    "action_conditioned_model_readiness": ACTION_CONDITIONED_MODEL_READINESS,
    "causal_claim_made": False,
    "model_training_executed": False,
    "llm_used": False,
    "final_tests_executed": False,
    "artifacts": str(AUDIT_ARTIFACT_DIR),
}
print(json.dumps(experiment_summary, indent=2))""",
    ),
]


PREAMBLE = """from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

module_root_candidates = [Path.cwd(), Path.cwd().parent]
configured_data_root = os.getenv("GREENHOUSE_DATA_ROOT")
if configured_data_root:
    module_root_candidates.append(Path(configured_data_root).expanduser())
for module_root in dict.fromkeys(path.resolve() for path in module_root_candidates):
    if (module_root / "actuator_identifiability_audit.py").is_file():
        sys.path.insert(0, str(module_root))
        break
else:
    raise FileNotFoundError(
        "Cannot locate actuator_identifiability_audit.py from cwd, parent, "
        "or GREENHOUSE_DATA_ROOT"
    )

from actuator_identifiability_audit import (
    ACTUATORS, FEATURES, HORIZONS, JOINT_CODES, METRIC_FILENAMES,
    OVERLAP_VARIABLES, PLOT_FILENAMES, SENSORS, SPLITS, TARGET_UNITS,
    AuditConfig, actuator_dwell_summary, actuator_transition_summary,
    actuator_usage_summary, aggregate_response, assess_readiness,
    build_no_change_references, build_transition_events, confounding_diagnostics,
    derive_overlap_edges, derive_train_sensor_standardization, joint_action_coverage,
    load_audit_frames,
    load_canonical_index, load_locked_split, matched_response_diagnostic,
    parse_bool, resolve_development_paths, save_json_atomic, save_metric_frames,
    sha256_file, state_conditioned_overlap, summarize_no_change_references,
    support_by_scenario, trace_actuator_temporal_semantics,
    train_validation_shift, validate_binary_actuators,
)

try:
    from IPython.display import display
except ImportError:
    display = print"""


def main() -> None:
    cells = [
        nbformat.v4.new_markdown_cell(
            "## Colab Bootstrap\n\n"
            "Mount Google Drive and configure full-audit paths before importing "
            "the project helper. This cell is CPU-compatible and has no CUDA gate.",
            metadata={"section_id": "00", "cell_role": "colab_bootstrap"},
        ),
        nbformat.v4.new_code_cell(
            textwrap.dedent(COLAB_BOOTSTRAP).strip() + "\n",
            metadata={"section_id": "00", "cell_role": "colab_bootstrap"},
        ),
    ]
    for section_id, title, code in SECTIONS:
        markdown = nbformat.v4.new_markdown_cell(
            f"## {section_id} - {title}",
            metadata={"section_id": section_id},
        )
        if section_id == "00":
            code = PREAMBLE + "\n\n" + code
        code_cell = nbformat.v4.new_code_cell(
            textwrap.dedent(code).strip() + "\n",
            metadata={"section_id": section_id},
        )
        cells.extend([markdown, code_cell])
    notebook = nbformat.v4.new_notebook(
        cells=cells,
        metadata={
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3"},
        },
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(notebook, OUTPUT)


if __name__ == "__main__":
    main()
