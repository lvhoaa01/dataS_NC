from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from typing import Any, Iterator

import nbformat


ROOT = Path(__file__).resolve().parent
NOTEBOOK_PATH = ROOT / "notebooks" / "03_multi_horizon_gru_lstm.ipynb"
CONCEPTS_PATH = ROOT / "notebooks" / "03_multi_horizon_gru_lstm_CONCEPTS.md"
LOCAL_PREPROCESSING_ARTIFACT_DIR = ROOT / "outputs" / "ml_notebook_smoke" / "artifacts"
LOCAL_MULTI_HORIZON_ARTIFACT_DIR = (
    ROOT / "outputs" / "multi_horizon_notebook_smoke" / "artifacts"
)
EXPECTED_SECTION_IDS = tuple(f"{index:02d}" for index in range(31))
FORBIDDEN_FINAL_LOADER_NAMES = (
    "temporal_test_loader",
    "scenario_test_loader",
    "combined_test_loader",
    "final_test_loader",
)


def load_and_compile_notebook(path: Path = NOTEBOOK_PATH) -> nbformat.NotebookNode:
    """Validate notebook JSON/schema and compile every Python cell."""
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    for cell_index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{path}#cell-{cell_index}", "exec")
    return notebook


def notebook_code_source(notebook: nbformat.NotebookNode) -> str:
    return "\n".join(
        cell.source for cell in notebook.cells if cell.cell_type == "code"
    )


def notebook_section_ids(notebook: nbformat.NotebookNode) -> tuple[str, ...]:
    section_ids: list[str] = []
    for cell in notebook.cells:
        section_id = str(cell.metadata.get("section_id", ""))
        if not section_id:
            raise ValueError("Every notebook cell must declare metadata.section_id")
        if section_id not in section_ids:
            section_ids.append(section_id)
    return tuple(section_ids)


def concepts_section_ids(path: Path = CONCEPTS_PATH) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"^## Cell (\d{2})\b",
            path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )


def validate_concepts_sync(
    notebook: nbformat.NotebookNode,
    concepts_path: Path = CONCEPTS_PATH,
) -> dict[str, Any]:
    notebook_ids = notebook_section_ids(notebook)
    concept_ids = concepts_section_ids(concepts_path)
    if notebook_ids != EXPECTED_SECTION_IDS:
        raise AssertionError(f"Unexpected notebook sections: {notebook_ids}")
    if concept_ids != notebook_ids:
        raise AssertionError(
            f"Concept document is stale: notebook={notebook_ids}, concepts={concept_ids}"
        )
    return {"status": "PASS", "logical_sections": len(notebook_ids)}


def validate_static_protocol(notebook: nbformat.NotebookNode) -> dict[str, Any]:
    source = notebook_code_source(notebook)
    for forbidden_name in FORBIDDEN_FINAL_LOADER_NAMES:
        if re.search(rf"\b{re.escape(forbidden_name)}\b", source):
            raise AssertionError(f"Forbidden final-test loader found: {forbidden_name}")
    if "glob(" in source or "rglob(" in source:
        raise AssertionError("Canonical membership must not use filesystem globbing")
    if "feature_scaler.fit" in source or "target_scaler.fit" in source:
        raise AssertionError("Locked scalers must never be refit")
    if "partial_fit" in source or "fit_transform" in source:
        raise AssertionError("Notebook contains a prohibited scaler fitting path")
    required_fragments = (
        "FORECAST_HORIZONS = (1, 3, 6, 12, 24)",
        "EXPECTED_TRAIN_WINDOWS = 1_050_740",
        "EXPECTED_VALIDATION_WINDOWS = 175_220",
        "DirectMultiHorizonGRUForecaster",
        "DirectMultiHorizonLSTMForecaster",
        "future_control_change_labels",
        '"multi_horizon_final_tests_executed": False',
    )
    missing = [fragment for fragment in required_fragments if fragment not in source]
    if missing:
        raise AssertionError(f"Required protocol fragments missing: {missing}")
    return {
        "status": "PASS",
        "final_test_loader_names": 0,
        "scaler_fit_paths": 0,
        "canonical_glob_paths": 0,
    }


@contextmanager
def temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, old_value in previous.items():
            if old_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old_value


def execute_smoke_namespace(
    notebook: nbformat.NotebookNode | None = None,
    *,
    data_root: Path = ROOT,
    preprocessing_artifact_dir: Path = LOCAL_PREPROCESSING_ARTIFACT_DIR,
    multi_horizon_artifact_dir: Path = LOCAL_MULTI_HORIZON_ARTIFACT_DIR,
) -> dict[str, Any]:
    """Run the bounded train/validation-only CPU integration path."""
    notebook = notebook or load_and_compile_notebook()
    multi_horizon_artifact_dir.mkdir(parents=True, exist_ok=True)
    matplotlib_config_dir = multi_horizon_artifact_dir / "_matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "GREENHOUSE_MULTI_HORIZON_SMOKE_TEST": "1",
        "GREENHOUSE_DATA_ROOT": str(data_root.resolve()),
        "GREENHOUSE_PREPROCESSING_ARTIFACT_DIR": str(
            preprocessing_artifact_dir.resolve()
        ),
        "GREENHOUSE_MULTI_HORIZON_ARTIFACT_DIR": str(
            multi_horizon_artifact_dir.resolve()
        ),
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(matplotlib_config_dir.resolve()),
    }
    namespace: dict[str, Any] = {
        "__name__": "__main__",
        "__file__": str(NOTEBOOK_PATH),
    }
    previous_cwd = Path.cwd()
    try:
        os.chdir(data_root)
        with temporary_environment(environment):
            for cell_index, cell in enumerate(notebook.cells):
                if cell.cell_type != "code":
                    continue
                exec(
                    compile(
                        cell.source,
                        f"{NOTEBOOK_PATH}#cell-{cell_index}",
                        "exec",
                    ),
                    namespace,
                )
    finally:
        os.chdir(previous_cwd)

    summary = namespace.get("experiment_summary")
    if not isinstance(summary, dict) or summary.get("status") != "PASS":
        raise AssertionError("Notebook did not produce a passing experiment_summary")
    if namespace.get("MULTI_HORIZON_SMOKE_TEST") is not True:
        raise AssertionError("Local validation did not use smoke mode")
    if summary.get("full_multi_horizon_training_executed") is not False:
        raise AssertionError("Smoke run incorrectly reports full training")
    if summary.get("multi_horizon_final_tests_executed") is not False:
        raise AssertionError("Smoke run touched final tests")
    if summary.get("final_test_loaders_constructed") is not False:
        raise AssertionError("Smoke run constructed final-test loaders")
    return namespace


def smoke_summary(namespace: dict[str, Any]) -> dict[str, Any]:
    """Return integration evidence without presenting smoke losses as science."""
    np = namespace["np"]
    numeric_frames = (
        namespace["validation_by_horizon"],
        namespace["horizon_degradation"],
        namespace["skill_scores"],
        namespace["future_control_audit"],
    )
    finite = all(
        np.isfinite(frame.select_dtypes(include=[np.number]).to_numpy()).all()
        for frame in numeric_frames
    )
    return {
        "status": "PASS",
        "multi_horizon_smoke_test": True,
        "active_development_scenarios": namespace["active_development_ids"],
        "actual_window_counts": namespace["actual_window_counts"],
        "expected_full_window_counts": {
            "train": namespace["EXPECTED_TRAIN_WINDOWS"],
            "validation": namespace["EXPECTED_VALIDATION_WINDOWS"],
        },
        "sample_shapes": {
            "features": list(namespace["sample_features"].shape),
            "targets": list(namespace["sample_targets"].shape),
        },
        "validation_model_names": sorted(
            namespace["validation_by_horizon"]["Model"].unique().tolist()
        ),
        "finite_validation_diagnostics": bool(finite),
        "gru_epochs": len(namespace["gru_result"]["history"]),
        "lstm_epochs": len(namespace["lstm_result"]["history"]),
        "checkpoint_reload": namespace["checkpoint_reload_audit"],
        "scaler_refit_performed": False,
        "held_out_csv_loaded": False,
        "final_test_loaders_constructed": False,
        "multi_horizon_final_tests_executed": False,
        "full_multi_horizon_training_executed": False,
        "artifact_dir": str(namespace["MULTI_HORIZON_ARTIFACT_DIR"]),
    }


def validate_notebook(
    *,
    execute_smoke: bool,
    preprocessing_artifact_dir: Path | None = None,
    multi_horizon_artifact_dir: Path | None = None,
) -> dict[str, Any]:
    notebook = load_and_compile_notebook()
    result: dict[str, Any] = {
        "status": "PASS",
        "notebook": str(NOTEBOOK_PATH),
        "notebook_json_valid": True,
        "code_cells_compile": True,
        "physical_cells": len(notebook.cells),
        "code_cells": sum(cell.cell_type == "code" for cell in notebook.cells),
        "concept_sync": validate_concepts_sync(notebook),
        "static_protocol": validate_static_protocol(notebook),
    }
    if execute_smoke:
        namespace = execute_smoke_namespace(
            notebook,
            preprocessing_artifact_dir=(
                preprocessing_artifact_dir or LOCAL_PREPROCESSING_ARTIFACT_DIR
            ),
            multi_horizon_artifact_dir=(
                multi_horizon_artifact_dir or LOCAL_MULTI_HORIZON_ARTIFACT_DIR
            ),
        )
        result["execution"] = smoke_summary(namespace)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-smoke", action="store_true")
    parser.add_argument("--preprocessing-artifact-dir", type=Path)
    parser.add_argument("--multi-horizon-artifact-dir", type=Path)
    parser.add_argument("--summary-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_notebook(
        execute_smoke=args.execute_smoke,
        preprocessing_artifact_dir=args.preprocessing_artifact_dir,
        multi_horizon_artifact_dir=args.multi_horizon_artifact_dir,
    )
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        args.summary_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
