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
NOTEBOOK_PATH = ROOT / "notebooks" / "02_gru_lstm_training.ipynb"
CONCEPTS_PATH = ROOT / "notebooks" / "02_gru_lstm_training_CONCEPTS.md"
LOCAL_PREPROCESSING_ARTIFACT_DIR = ROOT / "outputs" / "ml_notebook_smoke" / "artifacts"
EXPECTED_SECTION_IDS = tuple(f"{index:02d}" for index in range(27))


def load_and_compile_notebook(path: Path = NOTEBOOK_PATH) -> nbformat.NotebookNode:
    """Validate notebook JSON/schema and compile every Python code cell."""
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    for cell_index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{path}#cell-{cell_index}", "exec")
    return notebook


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
    model_artifact_dir: Path,
) -> dict[str, Any]:
    """Execute both recurrent models with bounded CPU batches and return the cell namespace."""
    notebook = notebook or load_and_compile_notebook()
    model_artifact_dir.mkdir(parents=True, exist_ok=True)
    matplotlib_config_dir = model_artifact_dir / "_matplotlib"
    matplotlib_config_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "GREENHOUSE_TRAINING_SMOKE_TEST": "1",
        "GREENHOUSE_DATA_ROOT": str(data_root.resolve()),
        "GREENHOUSE_PREPROCESSING_ARTIFACT_DIR": str(preprocessing_artifact_dir.resolve()),
        "GREENHOUSE_MODEL_ARTIFACT_DIR": str(model_artifact_dir.resolve()),
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
        raise AssertionError("Training notebook did not produce a passing experiment_summary")
    if namespace.get("TRAINING_SMOKE_TEST") is not True:
        raise AssertionError("Local validation did not run in training smoke mode")
    if summary.get("full_gpu_training_executed") is not False:
        raise AssertionError("Smoke validation incorrectly reported full GPU training")
    return namespace


def smoke_summary(namespace: dict[str, Any]) -> dict[str, Any]:
    """Extract a JSON-serializable validation result without reporting smoke accuracy."""
    return {
        "status": "PASS",
        "training_smoke_test": True,
        "active_scenarios": namespace["active_scenario_ids"],
        "actual_window_counts": namespace["actual_window_counts"],
        "locked_window_counts": namespace["LOCKED_WINDOW_COUNTS"],
        "sample_batch_shapes": {
            "features": list(namespace["sample_batch"][0].shape),
            "targets": list(namespace["sample_batch"][1].shape),
        },
        "persistence_shape": list(namespace["persistence_smoke_prediction"].shape),
        "gru": {
            "epochs": len(namespace["gru_result"]["history"]),
            "forward_backward": "PASS",
            "checkpoint_reload": namespace["checkpoint_reload_audit"]["GRU"],
        },
        "lstm": {
            "epochs": len(namespace["lstm_result"]["history"]),
            "forward_backward": "PASS",
            "checkpoint_reload": namespace["checkpoint_reload_audit"]["LSTM"],
        },
        "finite_metrics": bool(
            namespace["np"].isfinite(
                namespace["model_comparison"].select_dtypes(include=[namespace["np"].number]).to_numpy()
            ).all()
        ),
        "scaler_refit_performed": False,
        "full_training_executed": False,
        "model_artifact_dir": str(namespace["MODEL_ARTIFACT_DIR"]),
    }


def validate_notebook(
    *,
    execute_smoke: bool,
    model_artifact_dir: Path | None = None,
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
    }
    if execute_smoke:
        resolved_model_dir = model_artifact_dir or (
            ROOT / "outputs" / "ml_training_notebook_smoke" / "artifacts"
        )
        namespace = execute_smoke_namespace(
            notebook,
            model_artifact_dir=resolved_model_dir,
        )
        result["execution"] = smoke_summary(namespace)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-smoke", action="store_true")
    parser.add_argument("--model-artifact-dir", type=Path)
    parser.add_argument("--summary-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_notebook(
        execute_smoke=args.execute_smoke,
        model_artifact_dir=args.model_artifact_dir,
    )
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        args.summary_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
