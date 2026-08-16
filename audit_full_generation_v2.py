"""Audit the completed V2 full-generation corpus and write its dataset index."""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import statistics
from typing import Any, Sequence

import build_ml_dataset as ml_builder
import generate_pilot_scenarios as pilot
import run_full_generation as runner


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "final_approved_parameter_sets_v2.yaml"
INDEX_PATH = ROOT / "full_dataset_index.csv"
AUDIT_PATH = runner.FULL_OUTPUT_ROOT / "final_audit_v2.json"
MANIFEST_VERSION = "2.0"
EXPECTED_ROWS = 70_128
EXPECTED_TOTAL_ROWS = 1_683_072

INDEX_COLUMNS = (
    "parameter_set_id",
    "physics_file",
    "ml_file",
    "physics_rows",
    "ml_rows",
    "physics_hash",
    "ml_hash",
    "classification",
    "manifest_version",
    "config_hash",
    "validation_status",
)


class FinalAuditError(RuntimeError):
    """Raised when the completed corpus violates a final invariant."""


def scan_csv(
    path: Path,
    expected_columns: Sequence[str],
    expected_parameter_set_id: str,
    *,
    physics: bool,
) -> dict[str, Any]:
    rows = 0
    nan_count = 0
    inf_count = 0
    invalid_numeric_count = 0
    invalid_actuator_count = 0
    parameter_id_mismatch_count = 0
    timestamp_errors = 0
    first_timestamp = ""
    last_timestamp = ""
    previous: datetime | None = None
    text_columns = {"timestamp", "simulation_id", "parameter_set_id"}
    actuator_columns = {"pump_state", "fan_state", "grow_light_state"}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        for row in reader:
            rows += 1
            timestamp_text = row.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(timestamp_text)
            except ValueError:
                timestamp_errors += 1
                timestamp = None
            if timestamp is not None:
                if previous is not None and timestamp != previous + timedelta(hours=1):
                    timestamp_errors += 1
                previous = timestamp
            first_timestamp = first_timestamp or timestamp_text
            last_timestamp = timestamp_text
            if physics and row.get("parameter_set_id") != expected_parameter_set_id:
                parameter_id_mismatch_count += 1
            for name, raw_value in row.items():
                if name in text_columns:
                    continue
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    invalid_numeric_count += 1
                    continue
                if math.isnan(value):
                    nan_count += 1
                elif math.isinf(value):
                    inf_count += 1
                if name in actuator_columns and value not in (0.0, 1.0):
                    invalid_actuator_count += 1
    return {
        "file": str(path.relative_to(ROOT)),
        "rows": rows,
        "columns": list(columns),
        "schema_pass": columns == tuple(expected_columns),
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "timestamp_errors": timestamp_errors,
        "nan_count": nan_count,
        "inf_count": inf_count,
        "invalid_numeric_count": invalid_numeric_count,
        "invalid_actuator_count": invalid_actuator_count,
        "parameter_id_mismatch_count": parameter_id_mismatch_count,
        "size_bytes": path.stat().st_size,
    }


def coverage(rows: Sequence[dict[str, str]]) -> dict[str, dict[str, float]]:
    columns = {
        "C_d": "C_d",
        "eta_s": "eta_s",
        "C_s": "C_s_J_K",
        "irrigation": "irrigation_flow_L_h",
        "ET_scale": "ET_scale",
    }
    result: dict[str, dict[str, float]] = {}
    for name, column in columns.items():
        values = [float(row[column]) for row in rows]
        result[name] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "std": statistics.pstdev(values),
        }
    return result


def execute() -> dict[str, Any]:
    manifest_audit = runner.audit_final_manifest(MANIFEST_PATH)
    manifest_csv, _ = runner.resolve_manifest_paths(MANIFEST_PATH)
    rows = runner.load_manifest_rows(manifest_csv)
    state = json.loads(
        (runner.FULL_OUTPUT_ROOT / "state" / "run_state.json").read_text(
            encoding="utf-8"
        )
    )
    weather, weather_audit = runner.audit_weather_dataset()
    forcing_hash = pilot.selected_weather_hash(weather)
    errors: list[str] = []
    index_rows: list[dict[str, Any]] = []
    scenario_audits: list[dict[str, Any]] = []

    for row in rows:
        identifier = row["parameter_set_id"]
        job = runner.GenerationJob(
            identifier,
            row,
            runner.FULL_START,
            runner.FULL_END_INCLUSIVE,
            runner.EXPECTED_FULL_ROWS,
        )
        _, _, source_hash, run_hash = runner.derive_run_config(job)
        identity = runner.identity_payload(job, source_hash, run_hash, forcing_hash)
        paths = runner.scenario_paths(runner.FULL_OUTPUT_ROOT, identifier)
        entry = state.get("scenarios", {}).get(identifier)
        decision = runner.cache_decision(entry, identity, paths)
        if decision != ("SKIP", "COMPLETE"):
            errors.append(f"{identifier}: strict cache audit returned {decision}.")
            continue
        physics_scan = scan_csv(
            paths["physics"],
            runner.OUTPUT_COLUMNS,
            identifier,
            physics=True,
        )
        ml_scan = scan_csv(
            paths["ml"],
            ml_builder.CANONICAL_COLUMNS,
            identifier,
            physics=False,
        )
        validation = json.loads(paths["validation"].read_text(encoding="utf-8"))
        ml_metadata = json.loads(paths["ml_metadata"].read_text(encoding="utf-8"))
        checks = {
            "strict_cache": decision == ("SKIP", "COMPLETE"),
            "physics_rows": physics_scan["rows"] == EXPECTED_ROWS,
            "ml_rows": ml_scan["rows"] == EXPECTED_ROWS,
            "physics_schema": physics_scan["schema_pass"],
            "ml_schema": ml_scan["schema_pass"],
            "physics_finite": physics_scan["nan_count"] == 0
            and physics_scan["inf_count"] == 0
            and physics_scan["invalid_numeric_count"] == 0,
            "ml_finite": ml_scan["nan_count"] == 0
            and ml_scan["inf_count"] == 0
            and ml_scan["invalid_numeric_count"] == 0,
            "timestamps": physics_scan["timestamp_errors"] == 0
            and ml_scan["timestamp_errors"] == 0,
            "parameter_identity": physics_scan["parameter_id_mismatch_count"] == 0,
            "actuators": physics_scan["invalid_actuator_count"] == 0
            and ml_scan["invalid_actuator_count"] == 0,
            "physics_validation": validation.get("status") == "PASS",
            "ml_validation": ml_metadata.get("status") == "PASS",
            "physics_hash": pilot.sha256_file(paths["physics"])
            == entry.get("physics_hash"),
            "ml_hash": pilot.sha256_file(paths["ml"]) == entry.get("ml_hash"),
        }
        if not all(checks.values()):
            errors.append(
                f"{identifier}: final checks failed: "
                + ", ".join(name for name, passed in checks.items() if not passed)
            )
        scenario_audits.append(
            {
                "parameter_set_id": identifier,
                "checks": checks,
                "physics": physics_scan,
                "ml": ml_scan,
            }
        )
        index_rows.append(
            {
                "parameter_set_id": identifier,
                "physics_file": str(paths["physics"].relative_to(ROOT)),
                "ml_file": str(paths["ml"].relative_to(ROOT)),
                "physics_rows": physics_scan["rows"],
                "ml_rows": ml_scan["rows"],
                "physics_hash": entry["physics_hash"],
                "ml_hash": entry["ml_hash"],
                "classification": row["classification"],
                "manifest_version": MANIFEST_VERSION,
                "config_hash": row["config_hash"],
                "validation_status": validation.get("status"),
            }
        )

    manifest_ids = {row["parameter_set_id"] for row in rows}
    index_ids = {row["parameter_set_id"] for row in index_rows}
    rejected_included = "pa1_full_006" in index_ids
    if index_ids != manifest_ids:
        errors.append("Final index IDs differ from the V2 manifest.")
    if rejected_included:
        errors.append("Rejected V1 set 006 appears in the final index.")
    physics_rows = sum(item["physics"]["rows"] for item in scenario_audits)
    ml_rows = sum(item["ml"]["rows"] for item in scenario_audits)
    if physics_rows != EXPECTED_TOTAL_ROWS or ml_rows != EXPECTED_TOTAL_ROWS:
        errors.append(f"Unexpected global row totals: physics={physics_rows}, ml={ml_rows}.")
    temporary_files = list(runner.FULL_OUTPUT_ROOT.rglob("*.tmp"))
    lock_exists = (runner.FULL_OUTPUT_ROOT / "state" / "run.lock").exists()
    if temporary_files:
        errors.append("Temporary files remain after generation.")
    if lock_exists:
        errors.append("Run lock remains after generation.")

    runner.write_csv_atomic(INDEX_PATH, index_rows, INDEX_COLUMNS)
    audit = {
        "status": "PASS" if not errors else "FAIL",
        "manifest": manifest_audit,
        "weather": weather_audit,
        "valid_parameter_sets": len(index_rows),
        "unique_config_hashes": len({row["config_hash"] for row in index_rows}),
        "physics_files": len(index_rows),
        "ml_files": len(index_rows),
        "physics_rows": physics_rows,
        "ml_rows": ml_rows,
        "physics_size_bytes": sum(
            item["physics"]["size_bytes"] for item in scenario_audits
        ),
        "ml_size_bytes": sum(item["ml"]["size_bytes"] for item in scenario_audits),
        "nan_count": sum(
            item["physics"]["nan_count"] + item["ml"]["nan_count"]
            for item in scenario_audits
        ),
        "inf_count": sum(
            item["physics"]["inf_count"] + item["ml"]["inf_count"]
            for item in scenario_audits
        ),
        "parameter_coverage": coverage(rows),
        "final_index": str(INDEX_PATH.relative_to(ROOT)),
        "final_index_sha256": pilot.sha256_file(INDEX_PATH),
        "rejected_v1_included": rejected_included,
        "excluded_debug_artifacts": [
            "outputs/full_generation/physics/pa1_full_006.csv"
        ],
        "orphan_final_outputs": sorted(manifest_ids.symmetric_difference(index_ids)),
        "temporary_files": [str(path.relative_to(ROOT)) for path in temporary_files],
        "run_lock_exists": lock_exists,
        "ml_contract": {
            "columns": list(ml_builder.CANONICAL_COLUMNS),
            "sensor_variables": 5,
            "actuator_states": 3,
            "physics_feature_count": 0,
            "weather_feature_count": 0,
            "sensor_mode": "physics_true_state",
        },
        "scenarios": scenario_audits,
        "errors": errors,
    }
    runner.write_json_atomic(AUDIT_PATH, audit)
    if errors:
        raise FinalAuditError(" | ".join(errors))
    return audit


def main() -> int:
    audit = execute()
    print(f"STATUS: {audit['status']}")
    print(f"VALID_PARAMETER_SETS: {audit['valid_parameter_sets']}")
    print(f"PHYSICS_ROWS: {audit['physics_rows']}")
    print(f"ML_ROWS: {audit['ml_rows']}")
    print(f"NAN_COUNT: {audit['nan_count']}")
    print(f"INF_COUNT: {audit['inf_count']}")
    print(f"INDEX_SHA256: {audit['final_index_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
