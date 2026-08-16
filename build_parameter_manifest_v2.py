"""Build the seasonal-stress validated V2 parameter manifest."""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import time
from typing import Any, Iterable, Sequence

import build_ml_dataset as ml_builder
import generate_final_parameter_sets as sampling
import generate_interaction_scenarios as interaction
import generate_pilot_scenarios as pilot
import run_full_generation as full_runner
import seasonal_stress_preflight as seasonal
import select_climate_stress_windows as selector
from physics.config import load_parameter_config
from physics.simulator import OUTPUT_COLUMNS, load_and_validate_weather_range


ROOT = Path(__file__).resolve().parent
V1_CSV = ROOT / "final_approved_parameter_sets.csv"
V1_YAML = ROOT / "final_approved_parameter_sets.yaml"
V1_REPORT = ROOT / "FULL_GENERATION_FINAL_REPORT.md"
V2_CSV = ROOT / "final_approved_parameter_sets_v2.csv"
V2_YAML = ROOT / "final_approved_parameter_sets_v2.yaml"
OUTPUT_ROOT = ROOT / "outputs" / "seasonal_stress_preflight"
TRIAL_CONFIG_DIR = OUTPUT_ROOT / "replacement_trial_configs"
FINAL_CONFIG_DIR = OUTPUT_ROOT / "configs"
TRIALS_CSV = OUTPUT_ROOT / "replacement_candidate_attempts.csv"
COVERAGE_PATH = OUTPUT_ROOT / "v2_coverage_audit.json"
V2_VERSION = "2.0"
REPLACEMENT_POLICY = "continue_pa1_constrained_lhs_v1_after_raw_000023"
V1_LOCKED_HASH = "194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8"
V1_COMPLETE_IDS = tuple(
    ["pa1_full_000_baseline"] + [f"pa1_full_{index:03d}" for index in range(1, 6)]
)


V2_COLUMNS = (
    "parameter_set_id",
    "manifest_version",
    "origin",
    "parent_parameter_set_id",
    "source_candidate_id",
    "sampling_index",
    "raw_candidate_index",
    "sampling_seed",
    "C_d",
    "eta_s",
    "C_s_J_K",
    "irrigation_flow_L_h",
    "ET_scale",
    "classification",
    "config_hash",
    "config_file",
    "config_file_sha256",
    "seasonal_preflight_file",
    "seasonal_preflight_file_sha256",
    "seasonal_preflight_status",
    "reference_june_status",
    "humid_stress_status",
    "hot_solar_status",
    "dry_vpd_status",
    "transition_status",
    "full_horizon_status",
    "known_joint_constraint_pass",
    "eligibility_basis",
    "eligibility_status",
)


class ManifestV2Error(RuntimeError):
    """Raised when V2 cannot preserve the scientific eligibility contract."""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_v1_evidence(
    v1_rows: Sequence[dict[str, str]], weather_hash: str
) -> dict[str, Any]:
    errors: list[str] = []
    if pilot.sha256_file(V1_CSV) != V1_LOCKED_HASH:
        errors.append("V1 CSV hash changed.")
    if not V1_YAML.is_file() or not V1_REPORT.is_file():
        errors.append("V1 manifest/report provenance file is missing.")
    state = seasonal.load_full_run_state()
    full_weather, _ = load_and_validate_weather_range(
        selector.WEATHER_PATH,
        selector.FULL_START,
        selector.FULL_END,
        allow_terminal_hold=True,
    )
    forcing_hash = pilot.selected_weather_hash(full_weather)
    by_id = {row["parameter_set_id"]: row for row in v1_rows}
    retained: list[dict[str, Any]] = []
    for identifier in V1_COMPLETE_IDS:
        row = by_id[identifier]
        job = full_runner.GenerationJob(
            identifier,
            row,
            selector.FULL_START,
            selector.FULL_END,
            70_128,
        )
        _, _, source_hash, run_hash = full_runner.derive_run_config(job)
        paths = full_runner.scenario_paths(full_runner.FULL_OUTPUT_ROOT, identifier)
        identity = full_runner.identity_payload(
            job, source_hash, run_hash, forcing_hash
        )
        entry = state.get("scenarios", {}).get(identifier)
        if entry and entry.get("source_weather_sha256") != weather_hash:
            errors.append(f"{identifier}: retained raw weather SHA-256 mismatch.")
        decision, reason = full_runner.cache_decision(entry, identity, paths)
        if (decision, reason) != ("SKIP", "COMPLETE"):
            errors.append(f"{identifier}: retained cache audit returned {decision}/{reason}.")
        retained.append(
            {
                "parameter_set_id": identifier,
                "source_config_hash": source_hash,
                "run_config_hash": run_hash,
                "physics_rows": entry.get("physics_rows") if entry else None,
                "ml_rows": entry.get("ml_rows") if entry else None,
                "physics_hash": entry.get("physics_hash") if entry else None,
                "ml_hash": entry.get("ml_hash") if entry else None,
                "cache_audit": f"{decision}/{reason}",
            }
        )
    failed = state.get("scenarios", {}).get("pa1_full_006", {})
    failed_physics = full_runner.scenario_paths(
        full_runner.FULL_OUTPUT_ROOT, "pa1_full_006"
    )["physics"]
    if failed.get("status") != "FAILED_VALIDATION":
        errors.append("pa1_full_006 is not preserved as FAILED_VALIDATION evidence.")
    if not failed_physics.is_file() or failed.get("physics_rows") != 70_128:
        errors.append("pa1_full_006 full-horizon debug physics is missing/incomplete.")
    if errors:
        raise ManifestV2Error("V1 evidence audit failed: " + " | ".join(errors))
    return {
        "status": "PASS",
        "v1_manifest_sha256": pilot.sha256_file(V1_CSV),
        "raw_weather_sha256": weather_hash,
        "normalized_forcing_hash": forcing_hash,
        "retained": retained,
        "failed_evidence": {
            "parameter_set_id": "pa1_full_006",
            "status": failed.get("status"),
            "physics_rows": failed.get("physics_rows"),
            "physics_hash": failed.get("physics_hash"),
            "failure_stage": failed.get("failure_stage"),
        },
    }


def load_v1_reports(rows: Sequence[dict[str, str]]) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    for row in rows:
        identifier = row["parameter_set_id"]
        path = seasonal.VALIDATION_DIR / f"{identifier}.json"
        if not path.is_file():
            raise ManifestV2Error(f"Missing seasonal report for {identifier}.")
        report = load_json(path)
        expected_identity = seasonal.validation_identity(row, seasonal.load_windows())
        if report.get("identity") != expected_identity:
            raise ManifestV2Error(f"Stale seasonal report for {identifier}.")
        reports[identifier] = report
    return reports


def window_statuses(report: dict[str, Any]) -> dict[str, str]:
    values = {window["window_type"]: window["status"] for window in report["windows"]}
    return {
        "reference_june_status": values["REFERENCE_JUNE"],
        "humid_stress_status": values["HUMID_STRESS"],
        "hot_solar_status": values["HOT_SOLAR_STRESS"],
        "dry_vpd_status": values["DRY_VPD_STRESS"],
        "transition_status": values["TRANSITION_MIXED"],
    }


def v1_v2_row(
    row: dict[str, str], report: dict[str, Any], *, full_pass: bool
) -> dict[str, Any]:
    report_path = seasonal.VALIDATION_DIR / f"{row['parameter_set_id']}.json"
    return {
        "parameter_set_id": row["parameter_set_id"],
        "manifest_version": V2_VERSION,
        "origin": "V1_RETAINED_FULL_PASS" if full_pass else "V1_RETAINED",
        "parent_parameter_set_id": row["parameter_set_id"],
        "source_candidate_id": row["source_candidate_id"],
        "sampling_index": row["sampling_index"],
        "raw_candidate_index": 0 if row["parameter_set_id"].endswith("baseline") else row["sampling_index"],
        "sampling_seed": row["sampling_seed"],
        "C_d": float(row["C_d"]),
        "eta_s": float(row["eta_s"]),
        "C_s_J_K": float(row["C_s_J_K"]),
        "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
        "ET_scale": float(row["ET_scale"]),
        "classification": row["classification"],
        "config_hash": row["config_hash"],
        "config_file": row["config_file"],
        "config_file_sha256": row["config_file_sha256"],
        "seasonal_preflight_file": str(report_path.relative_to(ROOT)),
        "seasonal_preflight_file_sha256": pilot.sha256_file(report_path),
        "seasonal_preflight_status": report["seasonal_preflight_status"],
        **window_statuses(report),
        "full_horizon_status": report["full_horizon_status"],
        "known_joint_constraint_pass": True,
        "eligibility_basis": (
            "FULL_HORIZON_PASS" if full_pass else "SEASONAL_STRESS_PASS"
        ),
        "eligibility_status": "ELIGIBLE_FULL_RUN",
    }


def replacement_trial_row(
    sample: dict[str, Any], raw: dict[str, Any], config_hash: str, config_path: Path
) -> dict[str, Any]:
    values = sample["parameters"]
    raw_index = int(sample["raw_candidate_index"])
    return {
        "parameter_set_id": f"pa1_v2_trial_{raw_index:06d}",
        "source_candidate_id": f"lhs_candidate_{raw_index:06d}",
        "sampling_index": raw_index,
        "raw_candidate_index": raw_index,
        "sampling_seed": sampling.SAMPLING_SEED,
        "C_d": values["C_d"],
        "eta_s": values["eta_s"],
        "C_s_J_K": values["C_s"],
        "irrigation_flow_L_h": values["irrigation_flow_L_h"],
        "ET_scale": values["ET_scale"],
        "classification": "PENDING_SEASONAL_PREFLIGHT",
        "config_hash": config_hash,
        "config_file": str(config_path.relative_to(ROOT)),
        "config_file_sha256": pilot.sha256_file(config_path),
    }


def official_replacement_row(
    slot: int,
    parent_id: str,
    trial_row: dict[str, Any],
    trial_report: dict[str, Any],
    base_raw: dict[str, Any],
) -> dict[str, Any]:
    identifier = f"pa1_v2_replacement_{slot:03d}"
    values = preflight_values(trial_row)
    raw_index = int(trial_row["raw_candidate_index"])
    raw, config, config_hash = sampling.build_parameter_config(
        base_raw,
        values,
        identifier,
        str(trial_row["source_candidate_id"]),
        raw_index,
        raw_index,
    )
    config_path = FINAL_CONFIG_DIR / f"{identifier}.yaml"
    pilot.write_json_atomic(config_path, raw)
    if config_hash != trial_row["config_hash"]:
        raise ManifestV2Error(f"{identifier}: identity changed physical config hash.")
    official_report = deepcopy(trial_report)
    official_report["identity"] = {
        **official_report["identity"],
        "parameter_set_id": identifier,
    }
    official_report["trial_parameter_set_id"] = trial_row["parameter_set_id"]
    official_report["approved_parameter_set_id"] = identifier
    official_report_path = seasonal.VALIDATION_DIR / f"{identifier}.json"
    pilot.write_json_atomic(official_report_path, official_report)
    extreme = any(
        item.get("classification") == "EXTREME_VALID"
        for item in trial_report["windows"]
    )
    return {
        "parameter_set_id": identifier,
        "manifest_version": V2_VERSION,
        "origin": "V2_REPLACEMENT",
        "parent_parameter_set_id": parent_id,
        "source_candidate_id": trial_row["source_candidate_id"],
        "sampling_index": raw_index,
        "raw_candidate_index": raw_index,
        "sampling_seed": sampling.SAMPLING_SEED,
        "C_d": values["C_d"],
        "eta_s": values["eta_s"],
        "C_s_J_K": values["C_s"],
        "irrigation_flow_L_h": values["irrigation_flow_L_h"],
        "ET_scale": values["ET_scale"],
        "classification": (
            "EXTREME_VALID_APPROVED" if extreme else "APPROVED_FULL_RUN"
        ),
        "config_hash": config_hash,
        "config_file": str(config_path.relative_to(ROOT)),
        "config_file_sha256": pilot.sha256_file(config_path),
        "seasonal_preflight_file": str(official_report_path.relative_to(ROOT)),
        "seasonal_preflight_file_sha256": pilot.sha256_file(official_report_path),
        "seasonal_preflight_status": "SEASONAL_PREFLIGHT_PASS",
        **window_statuses(trial_report),
        "full_horizon_status": "NOT_RUN",
        "known_joint_constraint_pass": True,
        "eligibility_basis": "SEASONAL_STRESS_PASS",
        "eligibility_status": "ELIGIBLE_FULL_RUN",
    }


def preflight_values(row: dict[str, Any]) -> dict[str, float]:
    return {
        "C_d": float(row["C_d"]),
        "eta_s": float(row["eta_s"]),
        "C_s": float(row["C_s_J_K"]),
        "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
        "ET_scale": float(row["ET_scale"]),
    }


def generate_replacements(
    rejected_ids: Sequence[str],
    v1_rows: Sequence[dict[str, str]],
    windows_payload: dict[str, Any],
    weather: Sequence[Any],
    indexes: dict[datetime, int],
    full_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    joint_space = load_json(sampling.JOINT_SPACE_PATH)
    base_config = load_parameter_config(sampling.BASE_CONFIG_PATH)
    used_hashes = {row["config_hash"] for row in v1_rows}
    attempts: list[dict[str, Any]] = []
    approved: list[dict[str, Any]] = []
    TRIAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for sample in sampling.iter_lhs_candidates(joint_space):
        raw_index = int(sample["raw_candidate_index"])
        if raw_index <= sampling.REQUESTED_NON_BASELINE:
            continue
        values = sample["parameters"]
        joint_pass, violations = sampling.evaluate_joint_constraints(values, joint_space)
        attempt: dict[str, Any] = {
            "raw_candidate_index": raw_index,
            "C_d": values["C_d"],
            "eta_s": values["eta_s"],
            "C_s_J_K": values["C_s"],
            "irrigation_flow_L_h": values["irrigation_flow_L_h"],
            "ET_scale": values["ET_scale"],
            "known_joint_constraint_pass": joint_pass,
            "violations": ";".join(violations),
            "seasonal_preflight_status": "NOT_RUN",
            "result": "REJECTED_JOINT_CONSTRAINT" if not joint_pass else "PENDING",
        }
        if not joint_pass:
            attempts.append(attempt)
            continue
        trial_id = f"pa1_v2_trial_{raw_index:06d}"
        candidate_id = f"lhs_candidate_{raw_index:06d}"
        raw, _, config_hash = sampling.build_parameter_config(
            base_config.raw,
            values,
            trial_id,
            candidate_id,
            raw_index,
            raw_index,
        )
        if config_hash in used_hashes:
            attempt["result"] = "REJECTED_DUPLICATE_CONFIG"
            attempts.append(attempt)
            continue
        config_path = TRIAL_CONFIG_DIR / f"{trial_id}.yaml"
        pilot.write_json_atomic(config_path, raw)
        trial_row = replacement_trial_row(sample, raw, config_hash, config_path)
        print(
            f"[replacement trial raw={raw_index:06d}] seasonal preflight",
            flush=True,
        )
        report = seasonal.run_candidate(
            trial_row,
            weather,
            indexes,
            windows_payload,
            full_state,
        )
        attempt["seasonal_preflight_status"] = report["seasonal_preflight_status"]
        attempt["result"] = (
            "APPROVED_REPLACEMENT"
            if report["seasonal_preflight_status"] == "SEASONAL_PREFLIGHT_PASS"
            else "REJECTED_SEASONAL_PREFLIGHT"
        )
        attempt["runtime_seconds"] = report["runtime_seconds"]
        attempts.append(attempt)
        if report["seasonal_preflight_status"] != "SEASONAL_PREFLIGHT_PASS":
            continue
        slot = len(approved) + 1
        official = official_replacement_row(
            slot,
            rejected_ids[slot - 1],
            trial_row,
            report,
            base_config.raw,
        )
        approved.append(official)
        used_hashes.add(config_hash)
        print(
            f"[replacement {slot:02d}/{len(rejected_ids):02d}] "
            f"{official['parameter_set_id']} <- raw {raw_index:06d} PASS",
            flush=True,
        )
        if len(approved) == len(rejected_ids):
            break
        if raw_index > 500:
            raise ManifestV2Error("Replacement search exceeded deterministic bound.")
    return approved, attempts


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def coverage(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    axes = {
        "C_d": "C_d",
        "eta_s": "eta_s",
        "C_s": "C_s_J_K",
        "irrigation_flow_L_h": "irrigation_flow_L_h",
        "ET_scale": "ET_scale",
    }
    result: dict[str, Any] = {}
    for name, column in axes.items():
        values = [float(row[column]) for row in rows]
        result[name] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "std": statistics.pstdev(values),
            "p05": quantile(values, 0.05),
            "p25": quantile(values, 0.25),
            "p75": quantile(values, 0.75),
            "p95": quantile(values, 0.95),
        }
    return result


def write_csv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def execute() -> dict[str, Any]:
    started = time.perf_counter()
    v1_rows = seasonal.load_v1_rows()
    windows_payload = seasonal.load_windows()
    evidence = audit_v1_evidence(v1_rows, windows_payload["weather_hash"])
    reports = load_v1_reports(v1_rows)
    retained_full = [row for row in v1_rows if row["parameter_set_id"] in V1_COMPLETE_IDS]
    remaining = [
        row
        for row in v1_rows
        if row["parameter_set_id"] not in V1_COMPLETE_IDS
        and reports[row["parameter_set_id"]]["seasonal_preflight_status"]
        == "SEASONAL_PREFLIGHT_PASS"
    ]
    rejected = [
        row["parameter_set_id"]
        for row in v1_rows
        if row["parameter_set_id"] not in V1_COMPLETE_IDS
        and reports[row["parameter_set_id"]]["seasonal_preflight_status"]
        == "SEASONAL_PREFLIGHT_FAIL"
    ]
    if "pa1_full_006" not in rejected:
        raise ManifestV2Error("Known full-horizon failure 006 was not detected.")

    weather, _ = load_and_validate_weather_range(
        selector.WEATHER_PATH,
        selector.FULL_START,
        selector.FULL_END,
        allow_terminal_hold=True,
    )
    indexes = {
        datetime.fromisoformat(row.timestamp): index for index, row in enumerate(weather)
    }
    full_state = seasonal.load_full_run_state()
    replacements, attempts = generate_replacements(
        rejected,
        v1_rows,
        windows_payload,
        weather,
        indexes,
        full_state,
    )
    final_rows = [
        v1_v2_row(row, reports[row["parameter_set_id"]], full_pass=True)
        for row in retained_full
    ]
    final_rows.extend(
        v1_v2_row(row, reports[row["parameter_set_id"]], full_pass=False)
        for row in remaining
    )
    final_rows.extend(replacements)
    hashes = [row["config_hash"] for row in final_rows]
    if len(final_rows) != 24 or len(set(hashes)) != 24:
        raise ManifestV2Error(
            f"V2 must have 24 unique eligible configs; got {len(final_rows)}/{len(set(hashes))}."
        )
    if any(row["eligibility_status"] != "ELIGIBLE_FULL_RUN" for row in final_rows):
        raise ManifestV2Error("V2 contains an ineligible row.")
    write_csv(V2_CSV, final_rows, V2_COLUMNS)
    write_csv(TRIALS_CSV, attempts, tuple(attempts[0]))
    coverage_payload = {
        "status": "PASS",
        "V1": coverage(v1_rows),
        "V2": coverage(final_rows),
        "retained_full_horizon_pass": len(retained_full),
        "retained_seasonal_pass": len(remaining),
        "replacements": len(replacements),
    }
    pilot.write_json_atomic(COVERAGE_PATH, coverage_payload)
    machine = {
        "schema_version": V2_VERSION,
        "manifest_version": V2_VERSION,
        "status": "APPROVED_FULL_RUN",
        "eligibility_policy": (
            "FULL_HORIZON_PASS OR (known joint constraints PASS AND all seasonal stress windows PASS)"
        ),
        "full_horizon_final_authority": True,
        "source_v1_manifest": V1_CSV.name,
        "source_v1_manifest_sha256": pilot.sha256_file(V1_CSV),
        "companion_csv": V2_CSV.name,
        "companion_csv_sha256": pilot.sha256_file(V2_CSV),
        "sampling_method": sampling.SAMPLING_METHOD,
        "sampling_seed": sampling.SAMPLING_SEED,
        "replacement_policy": REPLACEMENT_POLICY,
        "weather_hash": windows_payload["weather_hash"],
        "stress_windows_hash": pilot.canonical_hash(windows_payload),
        "simulator_code_hash": interaction.simulator_code_hash(),
        "parameter_set_count": len(final_rows),
        "retained_full_horizon_pass": len(retained_full),
        "retained_seasonal_pass": len(remaining),
        "replacement_count": len(replacements),
        "rejected_v1_parameter_sets": rejected,
        "parameter_sets": final_rows,
    }
    pilot.write_json_atomic(V2_YAML, machine)
    return {
        "status": "PASS",
        "v1_evidence": evidence,
        "rejected_v1": rejected,
        "retained_full_horizon_pass": len(retained_full),
        "retained_seasonal_pass": len(remaining),
        "replacement_count": len(replacements),
        "replacement_attempts": len(attempts),
        "replacement_joint_rejects": sum(
            item["result"] == "REJECTED_JOINT_CONSTRAINT" for item in attempts
        ),
        "replacement_seasonal_rejects": sum(
            item["result"] == "REJECTED_SEASONAL_PREFLIGHT" for item in attempts
        ),
        "manifest_rows": len(final_rows),
        "manifest_sha256": pilot.sha256_file(V2_CSV),
        "coverage": coverage_payload,
        "runtime_seconds": time.perf_counter() - started,
    }


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Build deterministic PA1 seasonal-stress manifest V2."
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    report = execute()
    print(f"STATUS: {report['status']}")
    print(f"REJECTED_V1: {len(report['rejected_v1'])}")
    print(f"REPLACEMENT_ATTEMPTS: {report['replacement_attempts']}")
    print(f"REPLACEMENTS: {report['replacement_count']}")
    print(f"MANIFEST_ROWS: {report['manifest_rows']}")
    print(f"MANIFEST_SHA256: {report['manifest_sha256']}")
    print(f"RUNTIME_SECONDS: {report['runtime_seconds']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
