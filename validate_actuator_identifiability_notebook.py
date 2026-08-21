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
NOTEBOOK_PATH = ROOT / "notebooks" / "05_actuator_intervention_identifiability_audit.ipynb"
CONCEPTS_PATH = ROOT / "notebooks" / "05_actuator_intervention_identifiability_audit_CONCEPTS.md"
FULL_FIXED_NOTEBOOK_PATH = (
    ROOT / "notebooks" / "04_operational_lookback_ablation_FULL_FIXED.ipynb"
)
LOCAL_PREPROCESSING_ARTIFACT_DIR = (
    ROOT / "outputs" / "ml_notebook_smoke" / "artifacts"
)
LOCAL_AUDIT_ARTIFACT_DIR = (
    ROOT
    / "outputs"
    / "actuator_identifiability_notebook_smoke"
    / "actuator_identifiability_audit_smoke"
)
EXPECTED_SECTION_IDS = tuple(f"{index:02d}" for index in range(28))


def load_and_compile_notebook(
    path: Path = NOTEBOOK_PATH,
) -> nbformat.NotebookNode:
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
    ordered: list[str] = []
    for cell in notebook.cells:
        section_id = str(cell.metadata.get("section_id", ""))
        if not section_id:
            raise ValueError("Every notebook cell must declare metadata.section_id")
        if section_id not in ordered:
            ordered.append(section_id)
    return tuple(ordered)


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
    helper_source = (ROOT / "actuator_identifiability_audit.py").read_text(
        encoding="utf-8"
    )
    combined = source + "\n" + helper_source
    required = (
        'AUTHORITATIVE_NOTEBOOK_04_NAME = "04_operational_lookback_ablation_FULL_FIXED.ipynb"',
        'colab_drive.mount("/content/drive")',
        'DATA_ROOT = Path("/content/drive/MyDrive/smart_greenhouse_dataset")',
        'os.environ["GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST"] = "false"',
        'HELPER_MODULE_PATH = DATA_ROOT / "actuator_identifiability_audit.py"',
        "assert HELPER_MODULE_PATH.is_file()",
        "OPERATIONAL_LOOKBACK = 24",
        "FORECAST_HORIZONS = (1, 3)",
        "resolve_development_paths(",
        "trace_actuator_temporal_semantics(",
        "build_transition_events(",
        "matched_response_diagnostic(",
        "SMOKE_AUDIT_ARTIFACT_DIR",
        "FULL_AUDIT_ARTIFACT_DIR",
        "expected_artifact_leaf",
        '"model_training_executed": False',
        '"causal_claim_made": False',
        '"final_tests_executed": False',
    )
    missing = [fragment for fragment in required if fragment not in source]
    if missing:
        raise AssertionError(f"Required audit fragments missing: {missing}")
    forbidden = (
        "import torch",
        "from torch",
        "tensorflow",
        "keras",
        "nn.LSTM",
        "nn.GRU",
        "optimizer.step",
        "loss.backward",
        "model.fit(",
        "openai",
        "chat." + "completions",
        "responses." + "create",
        "anthropic",
        "google.generativeai",
        "transformers",
        "LangChain",
    )
    found = [fragment for fragment in forbidden if fragment.lower() in combined.lower()]
    if found:
        raise AssertionError(f"Forbidden model/API implementation found: {found}")
    if "glob(" in source or "rglob(" in source:
        raise AssertionError("Canonical membership must not use filesystem globbing")
    if "04_operational_lookback_ablation.ipynb" in source:
        raise AssertionError("Old Notebook 04 was referenced as an authority")
    return {
        "status": "PASS",
        "model_classes": 0,
        "optimizers": 0,
        "training_loops": 0,
        "llm_api_clients": 0,
        "canonical_glob_paths": 0,
        "authoritative_notebook_04": str(FULL_FIXED_NOTEBOOK_PATH),
    }


@contextmanager
def temporary_environment(values: dict[str, str]) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, previous_value in previous.items():
            if previous_value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous_value


def execute_smoke_namespace(
    notebook: nbformat.NotebookNode | None = None,
    *,
    data_root: Path = ROOT,
    preprocessing_artifact_dir: Path = LOCAL_PREPROCESSING_ARTIFACT_DIR,
    audit_artifact_dir: Path = LOCAL_AUDIT_ARTIFACT_DIR,
) -> dict[str, Any]:
    notebook = notebook or load_and_compile_notebook()
    audit_artifact_dir.mkdir(parents=True, exist_ok=True)
    matplotlib_dir = audit_artifact_dir / "_matplotlib"
    matplotlib_dir.mkdir(parents=True, exist_ok=True)
    environment = {
        "GREENHOUSE_DATA_ROOT": str(data_root.resolve()),
        "GREENHOUSE_PREPROCESSING_ARTIFACT_DIR": str(
            preprocessing_artifact_dir.resolve()
        ),
        "GREENHOUSE_ACTUATOR_AUDIT_ARTIFACT_DIR": str(
            audit_artifact_dir.resolve()
        ),
        "GREENHOUSE_ACTUATOR_AUDIT_SMOKE_TEST": "true",
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(matplotlib_dir.resolve()),
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
        raise AssertionError("Notebook did not produce a passing experiment summary")
    if namespace.get("ACTUATOR_AUDIT_SMOKE_TEST") is not True:
        raise AssertionError("Local integration run did not use smoke mode")
    if summary.get("execution_mode") != "SMOKE_ONLY_NOT_SCIENTIFIC":
        raise AssertionError("Smoke run was mislabeled as a scientific full audit")
    if summary.get("model_training_executed") is not False:
        raise AssertionError("Notebook reported model training")
    if summary.get("final_tests_executed") is not False:
        raise AssertionError("Notebook touched final-test partitions")
    if Path(namespace["AUDIT_ARTIFACT_DIR"]).name != (
        "actuator_identifiability_audit_smoke"
    ):
        raise AssertionError("Smoke execution wrote outside the isolated smoke path")
    if namespace["AUDIT_ARTIFACT_DIR"] == namespace["FULL_AUDIT_ARTIFACT_DIR"]:
        raise AssertionError("Smoke and full artifact paths are not isolated")
    return namespace


def smoke_summary(namespace: dict[str, Any]) -> dict[str, Any]:
    artifact_dir = Path(namespace["AUDIT_ARTIFACT_DIR"])
    return {
        "status": "PASS",
        "execution_mode": namespace["experiment_summary"]["execution_mode"],
        "active_development_scenarios": namespace["active_development_ids"],
        "train_rows": int(
            sum(
                len(frame)
                for (split, _), frame in namespace["audit_frames"].items()
                if split == "TRAIN"
            )
        ),
        "validation_rows": int(
            sum(
                len(frame)
                for (split, _), frame in namespace["audit_frames"].items()
                if split == "VALIDATION"
            )
        ),
        "temporal_semantics_verified": bool(
            namespace["TEMPORAL_SEMANTICS_VERIFIED"]
        ),
        "held_out_paths_resolved": bool(namespace["HELD_OUT_PATHS_RESOLVED"]),
        "held_out_csv_loaded": bool(namespace["HELD_OUT_CSV_LOADED"]),
        "required_metrics": int(
            sum((artifact_dir / "metrics" / name).is_file() for name in namespace["METRIC_FILENAMES"])
        ),
        "required_plots": int(
            sum((artifact_dir / "plots" / name).is_file() for name in namespace["PLOT_FILENAMES"])
        ),
        "readiness": namespace["ACTION_CONDITIONED_MODEL_READINESS"],
        "smoke_readiness_is_scientific": False,
        "model_training_executed": False,
        "llm_used": False,
        "final_tests_executed": False,
        "artifact_dir": str(artifact_dir),
    }


def validate_notebook(
    *,
    execute_smoke: bool,
    preprocessing_artifact_dir: Path | None = None,
    audit_artifact_dir: Path | None = None,
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
            audit_artifact_dir=(
                audit_artifact_dir or LOCAL_AUDIT_ARTIFACT_DIR
            ),
        )
        result["execution"] = smoke_summary(namespace)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Notebook 05 and optionally execute its bounded CPU smoke path."
    )
    parser.add_argument("--execute-smoke", action="store_true")
    parser.add_argument("--preprocessing-artifact-dir", type=Path)
    parser.add_argument("--audit-artifact-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = validate_notebook(
            execute_smoke=args.execute_smoke,
            preprocessing_artifact_dir=args.preprocessing_artifact_dir,
            audit_artifact_dir=args.audit_artifact_dir,
        )
    except Exception as exc:  # pragma: no cover - CLI reporting path
        print(f"STATUS: FAILED\nERROR: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
