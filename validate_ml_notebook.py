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
NOTEBOOK_PATH = ROOT / "notebooks" / "01_ml_preprocessing_and_windowing.ipynb"
CONCEPTS_PATH = ROOT / "notebooks" / "01_ml_preprocessing_and_windowing_CONCEPTS.md"
EXPECTED_SECTION_IDS = tuple(f"{index:02d}" for index in range(22))


def load_and_compile_notebook(path: Path = NOTEBOOK_PATH) -> nbformat.NotebookNode:
    """Load a valid v4 notebook and compile every Python code cell."""
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    for cell_index, cell in enumerate(notebook.cells):
        if cell.cell_type == "code":
            compile(cell.source, f"{path}#cell-{cell_index}", "exec")
    return notebook


def notebook_section_ids(notebook: nbformat.NotebookNode) -> tuple[str, ...]:
    """Return first-occurrence logical section IDs from notebook cell metadata."""
    section_ids: list[str] = []
    for cell in notebook.cells:
        section_id = str(cell.metadata.get("section_id", ""))
        if not section_id:
            raise ValueError("Every notebook cell must declare metadata.section_id")
        if section_id not in section_ids:
            section_ids.append(section_id)
    return tuple(section_ids)


def concepts_section_ids(path: Path = CONCEPTS_PATH) -> tuple[str, ...]:
    """Extract ordered logical cell IDs from the concepts document."""
    source = path.read_text(encoding="utf-8")
    return tuple(re.findall(r"^## Cell (\d{2})\b", source, flags=re.MULTILINE))


def validate_concepts_sync(
    notebook: nbformat.NotebookNode,
    concepts_path: Path = CONCEPTS_PATH,
) -> dict[str, Any]:
    """Require a one-to-one ordered mapping between notebook and concepts sections."""
    notebook_ids = notebook_section_ids(notebook)
    concept_ids = concepts_section_ids(concepts_path)
    if notebook_ids != EXPECTED_SECTION_IDS:
        raise AssertionError(f"Unexpected notebook sections: {notebook_ids}")
    if concept_ids != notebook_ids:
        raise AssertionError(
            f"Concept mapping is stale: notebook={notebook_ids}, concepts={concept_ids}"
        )
    return {
        "status": "PASS",
        "logical_sections": len(notebook_ids),
        "notebook_section_ids": list(notebook_ids),
        "concept_section_ids": list(concept_ids),
    }


@contextmanager
def temporary_environment(values: dict[str, str]) -> Iterator[None]:
    """Set environment variables for notebook execution and restore prior values."""
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
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute code cells in smoke mode and return their shared namespace for tests."""
    notebook = notebook or load_and_compile_notebook()
    resolved_artifact_dir = artifact_dir or (
        ROOT / "outputs" / "ml_notebook_smoke" / "artifacts"
    )
    environment = {
        "GREENHOUSE_SMOKE_TEST": "1",
        "GREENHOUSE_DATA_ROOT": str(data_root.resolve()),
        "GREENHOUSE_ARTIFACT_DIR": str(resolved_artifact_dir.resolve()),
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
                compiled = compile(
                    cell.source,
                    f"{NOTEBOOK_PATH}#cell-{cell_index}",
                    "exec",
                )
                exec(compiled, namespace)
    finally:
        os.chdir(previous_cwd)

    pipeline_summary = namespace.get("pipeline_summary")
    if not isinstance(pipeline_summary, dict) or pipeline_summary.get("status") != "PASS":
        raise AssertionError("Notebook did not produce a passing pipeline_summary")
    if namespace.get("SMOKE_TEST") is not True:
        raise AssertionError("Local validation did not execute in smoke mode")
    return namespace


def execute_smoke_notebook(
    notebook: nbformat.NotebookNode | None = None,
    *,
    data_root: Path = ROOT,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute the local CPU smoke workload and return a JSON-serializable audit."""
    resolved_artifact_dir = artifact_dir or (
        ROOT / "outputs" / "ml_notebook_smoke" / "artifacts"
    )
    namespace = execute_smoke_namespace(
        notebook,
        data_root=data_root,
        artifact_dir=resolved_artifact_dir,
    )

    result = {
        "status": "PASS",
        "notebook_json_valid": True,
        "code_cells_compile": True,
        "smoke_test": True,
        "artifact_dir": str(resolved_artifact_dir.resolve()),
        "pipeline_summary": pipeline_summary,
        "smoke_test_result": namespace["smoke_test_result"],
        "development_scenario_ids": namespace["development_scenario_ids"],
        "held_out_scenario_ids": namespace["held_out_scenario_ids"],
        "active_scenario_ids": namespace["active_scenario_ids"],
        "scaler_fit_audit": namespace["scaler_fit_audit"],
        "leakage_audit": namespace["leakage_audit"],
        "sequence_window_counts": {
            name: len(index) for name, index in namespace["sequence_indices"].items()
        },
    }
    return result


def validate_notebook(
    *,
    execute_smoke: bool,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Run structural checks and optionally the local CPU smoke pipeline."""
    notebook = load_and_compile_notebook()
    result: dict[str, Any] = {
        "status": "PASS",
        "notebook": str(NOTEBOOK_PATH),
        "notebook_json_valid": True,
        "code_cells_compile": True,
        "physical_cells": len(notebook.cells),
        "code_cells": sum(cell.cell_type == "code" for cell in notebook.cells),
    }
    if CONCEPTS_PATH.is_file():
        result["concept_sync"] = validate_concepts_sync(notebook)
    elif execute_smoke:
        raise FileNotFoundError(f"Concept document not found: {CONCEPTS_PATH}")

    if execute_smoke:
        result["execution"] = execute_smoke_notebook(
            notebook,
            data_root=ROOT,
            artifact_dir=artifact_dir,
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute-smoke",
        action="store_true",
        help="Execute the notebook against two canonical scenarios and short date ranges.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Optional smoke artifact directory.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        help="Optional JSON path for the validation summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_notebook(
        execute_smoke=args.execute_smoke,
        artifact_dir=args.artifact_dir,
    )
    if args.summary_file:
        args.summary_file.parent.mkdir(parents=True, exist_ok=True)
        args.summary_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
