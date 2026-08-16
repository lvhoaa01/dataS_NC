"""Preflight and approve the final PA1 constrained-LHS parameter sets."""

from __future__ import annotations

import csv
from datetime import datetime
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_final_parameter_sets as sampling
import generate_interaction_scenarios as interaction
import generate_pilot_scenarios as pilot
from physics.config import ParameterConfig, ParameterConfigError, load_parameter_config
from physics.simulator import (
    OUTPUT_COLUMNS,
    NumericalSimulationError,
    SimulationResult,
    WeatherDataError,
    load_and_validate_weather_window,
    run_simulation,
    write_simulation_csv,
)
from physics.validation import (
    build_verification_passes,
    conservation_audit,
    run_causal_tests,
    stability_comparison,
    validate_output_ranges,
)


BASE_CONFIG_PATH = sampling.BASE_CONFIG_PATH
JOINT_SPACE_PATH = sampling.JOINT_SPACE_PATH
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
BASELINE_MASTER_PATH = ROOT / "outputs" / "greenhouse_simulation_30days.csv"
ML_DATASET_PATH = ROOT / "outputs" / "greenhouse_ml_dataset_30days.csv"
OUTPUT_DIR = sampling.OUTPUT_DIR
ATTEMPT_CONFIG_DIR = OUTPUT_DIR / "attempt_configs"
FINAL_CONFIG_DIR = OUTPUT_DIR / "configs"
PHYSICS_DIR = OUTPUT_DIR / "physics"
VALIDATION_DIR = OUTPUT_DIR / "validation"
STABILITY_DIR = OUTPUT_DIR / "stability"
REPRODUCIBILITY_DIR = OUTPUT_DIR / "reproducibility"
PREFLIGHT_SUMMARY_PATH = OUTPUT_DIR / "preflight_summary.json"
FINAL_MANIFEST_CSV_PATH = ROOT / "final_approved_parameter_sets.csv"
FINAL_MANIFEST_YAML_PATH = ROOT / "final_approved_parameter_sets.yaml"
READINESS_PATH = ROOT / "FULL_GENERATION_READINESS.md"

FINAL_COLUMNS = (
    "parameter_set_id",
    "source_candidate_id",
    "sampling_index",
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
    "preflight_hash",
    "preflight_file_sha256",
    "weather_hash",
    "T_air_max",
    "RH_max",
    "RH_saturation_fraction",
    "RH_100_count",
    "RH_longest_saturation_run",
    "T_soil_max",
    "hours_soil_above_38",
    "hours_soil_above_40",
    "soil_moisture_min",
    "soil_moisture_max",
    "stability_status",
)


class PreflightError(RuntimeError):
    """Raised when final approval cannot meet the locked scientific contract."""


def row_values(row: dict[str, Any]) -> dict[str, float]:
    return {
        "C_d": float(row["C_d"]),
        "eta_s": float(row["eta_s"]),
        "C_s": float(row["C_s_J_K"]),
        "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
        "ET_scale": float(row["ET_scale"]),
    }


def identity_independent_output_hash(rows: list[dict[str, Any]]) -> str:
    payload = [
        {
            key: value
            for key, value in row.items()
            if key not in {"simulation_id", "parameter_set_id"}
        }
        for row in rows
    ]
    return pilot.canonical_hash(payload)


def classify_preflight(
    framework_pass: bool,
    guard_violations: list[str],
    metrics: dict[str, Any],
) -> tuple[str, str]:
    if not framework_pass or guard_violations:
        return "REJECTED", "REJECTED_PREFLIGHT"
    if (
        metrics["states"]["T_soil"]["max"] >= 38.0
        or metrics["humidity"]["saturated_fraction"] >= 0.02
        or metrics["soil_water"]["hours_near_wilting"] > 0
    ):
        return "EXTREME_VALID", "EXTREME_VALID_APPROVED"
    return "PASS", "APPROVED_FULL_RUN"


def joint_guard_violations(
    result: SimulationResult,
    metrics: dict[str, Any],
    expected_rows: int,
) -> list[str]:
    violations: list[str] = []
    soil_max = float(metrics["soil_temperature"]["max_c"])
    saturated_fraction = float(metrics["humidity"]["saturated_fraction"])
    saturated_rows = int(metrics["humidity"]["saturated_rows"])
    if soil_max > 40.0:
        violations.append(f"T_soil,max={soil_max:.6f} C exceeds 40 C.")
    if saturated_fraction > 0.05:
        violations.append(
            f"RH=100 for {saturated_rows}/{expected_rows} rows "
            f"({saturated_fraction:.6%}) exceeds 5%."
        )
    pathology = metrics["soil_water"]["controller_pathology"]
    if pathology["status"] != "PASS":
        active = [name for name, value in pathology["flags"].items() if value]
        violations.append("Controller/root-zone pathology: " + ", ".join(active))
    if len(result.rows) != expected_rows:
        violations.append(f"Expected {expected_rows} rows, found {len(result.rows)}.")
    if result.rows and tuple(result.rows[0]) != OUTPUT_COLUMNS:
        violations.append("Physics output schema changed.")
    return violations


def core_validation(
    config: ParameterConfig, result: SimulationResult
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    parameters = config.to_model_parameters()
    output = validate_output_ranges(result, parameters)
    causal = run_causal_tests(parameters)
    conservation = conservation_audit(result, parameters)
    passed = (
        output["status"] == "PASS"
        and causal["status"] == "PASS"
        and conservation["status"] == "PASS"
    )
    return output, causal, conservation, passed


def run_core_preflight(
    row: dict[str, Any],
    base_config: ParameterConfig,
    weather: list[Any],
    weather_quality: dict[str, Any],
    weather_hash: str,
    reference_rows: list[dict[str, str]],
    code_hash: str,
) -> dict[str, Any]:
    values = row_values(row)
    parameter_set_id = str(row["parameter_set_id"])
    candidate_id = str(row["candidate_id"])
    raw, config, config_hash = sampling.build_parameter_config(
        base_config.raw,
        values,
        parameter_set_id,
        candidate_id,
        int(row["sampling_index"]),
        int(row["raw_candidate_index"]),
    )
    config_path = ATTEMPT_CONFIG_DIR / f"{parameter_set_id}.yaml"
    pilot.write_json_atomic(config_path, raw)
    parameters = config.to_model_parameters()
    try:
        result = run_simulation(
            weather,
            parameters,
            internal_timestep_s=60,
            weather_quality=weather_quality,
        )
    except (NumericalSimulationError, ValueError, OverflowError) as exc:
        report = {
            "candidate_id": candidate_id,
            "parameter_set_id": parameter_set_id,
            "parameters": values,
            "config_hash": config_hash,
            "weather_hash": weather_hash,
            "simulator_code_hash": code_hash,
            "preflight_status": "REJECTED",
            "classification": "IMPLEMENTATION_FAILURE",
            "reason": str(exc),
        }
        pilot.write_json_atomic(VALIDATION_DIR / f"{parameter_set_id}.json", report)
        return {"report": report, "result": None, "config": config, "raw": raw}

    output, causal, conservation, framework_pass = core_validation(config, result)
    metrics = interaction.scenario_metrics(result, parameters)
    guards = joint_guard_violations(result, metrics, 720)
    preflight_status, classification = classify_preflight(
        framework_pass, guards, metrics
    )
    baseline_reproduction = None
    if bool(row["is_baseline"]):
        baseline_reproduction = pilot.baseline_reproduction_difference(
            result.rows, reference_rows
        )
        if baseline_reproduction["status"] != "PASS":
            guards.append("Baseline did not reproduce the validated physics master.")
            preflight_status = "REJECTED"
            classification = "IMPLEMENTATION_FAILURE"

    physics_path = PHYSICS_DIR / f"{parameter_set_id}.csv"
    write_simulation_csv(physics_path, result.rows)
    validation_path = VALIDATION_DIR / f"{parameter_set_id}.json"
    report = {
        "candidate_id": candidate_id,
        "parameter_set_id": parameter_set_id,
        "is_baseline": bool(row["is_baseline"]),
        "sampling_index": int(row["sampling_index"]),
        "raw_candidate_index": int(row["raw_candidate_index"]),
        "parameters": values,
        "config_hash": config_hash,
        "config_file": str(config_path.relative_to(ROOT)),
        "config_file_sha256": pilot.sha256_file(config_path),
        "weather_hash": weather_hash,
        "simulator_code_hash": code_hash,
        "internal_timestep_s": 60,
        "rows": len(result.rows),
        "columns": len(OUTPUT_COLUMNS),
        "physics_master_file": str(physics_path.relative_to(ROOT)),
        "physics_master_sha256": pilot.sha256_file(physics_path),
        "physics_numeric_hash": identity_independent_output_hash(result.rows),
        "preflight_status": preflight_status,
        "classification": classification,
        "framework_status": "PASS" if framework_pass else "FAIL",
        "joint_guard_status": "PASS" if not guards else "FAIL",
        "guard_violations": guards,
        "metrics": metrics,
        "range_checks": output,
        "causal_tests": causal,
        "mass_and_energy_consistency": conservation,
        "baseline_reproduction": baseline_reproduction,
        "warnings": list(result.warnings),
    }
    pilot.write_json_atomic(validation_path, report)
    report["validation_file"] = str(validation_path.relative_to(ROOT))
    return {"report": report, "result": result, "config": config, "raw": raw}


def update_candidate_row(row: dict[str, Any], report: dict[str, Any]) -> None:
    row["config_hash"] = report["config_hash"]
    row["preflight_status"] = report["preflight_status"]
    row["classification"] = report["classification"]
    reasons = report.get("guard_violations", [])
    if report.get("framework_status") == "FAIL":
        reasons = ["Core validator failed.", *reasons]
    if report["classification"] == "IMPLEMENTATION_FAILURE":
        reasons = [str(report.get("reason", "Implementation failure."))]
    row["reason"] = " | ".join(reasons)


def next_replacement_row(
    stream: Iterator[dict[str, Any]],
    existing_raw_indices: set[int],
    joint_space: dict[str, Any],
    base_config: ParameterConfig,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rejected_rows: list[dict[str, Any]] = []
    while True:
        sample = next(stream)
        raw_index = int(sample["raw_candidate_index"])
        if raw_index in existing_raw_indices:
            continue
        existing_raw_indices.add(raw_index)
        joint_pass, violations = sampling.evaluate_joint_constraints(
            sample["parameters"], joint_space
        )
        parameter_set_id = f"pa1_candidate_{raw_index:06d}"
        candidate_id = f"lhs_candidate_{raw_index:06d}"
        _, _, config_hash = sampling.build_parameter_config(
            base_config.raw,
            sample["parameters"],
            parameter_set_id,
            candidate_id,
            -1,
            raw_index,
        )
        row = sampling._manifest_row(
            sample, config_hash, joint_pass, violations, -1
        )
        if joint_pass:
            return row, rejected_rows
        rejected_rows.append(row)


def select_stability_representatives(
    approved: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline = next(item for item in approved if item["report"]["is_baseline"])
    nonbaseline = [item for item in approved if not item["report"]["is_baseline"]]
    ordered_groups = [
        sorted(
            nonbaseline,
            key=lambda item: item["report"]["metrics"]["states"]["T_soil"]["max"],
            reverse=True,
        ),
        sorted(
            nonbaseline,
            key=lambda item: item["report"]["metrics"]["humidity"]["saturated_fraction"],
            reverse=True,
        ),
        sorted(
            nonbaseline,
            key=lambda item: item["report"]["metrics"]["states"]["soil_moisture"]["min"],
        ),
        sorted(
            nonbaseline,
            key=lambda item: (
                abs(item["report"]["parameters"]["C_d"] - 0.30) / 0.45
                + abs(item["report"]["parameters"]["ET_scale"] - 1.15) / 0.30
            ),
        ),
    ]
    selected = [baseline]
    selected_ids = {baseline["report"]["candidate_id"]}
    for group in ordered_groups:
        for item in group:
            candidate_id = item["report"]["candidate_id"]
            if candidate_id not in selected_ids:
                selected.append(item)
                selected_ids.add(candidate_id)
                break
    if len(selected) != 5:
        raise PreflightError("Could not select five distinct stability representatives.")
    return selected


def run_stability_audit(
    representatives: list[dict[str, Any]],
    weather: list[Any],
    weather_quality: dict[str, Any],
) -> dict[str, Any]:
    reports: dict[str, Any] = {}
    for item in representatives:
        config: ParameterConfig = item["config"]
        parameters = config.to_model_parameters()
        results = {60: item["result"]}
        errors: dict[int, str] = {}
        for timestep in (120, 300):
            try:
                results[timestep] = run_simulation(
                    weather,
                    parameters,
                    internal_timestep_s=timestep,
                    weather_quality=weather_quality,
                )
            except (NumericalSimulationError, ValueError, OverflowError) as exc:
                errors[timestep] = str(exc)
        comparison = stability_comparison(results, errors, parameters)
        candidate_id = item["report"]["candidate_id"]
        verification = build_verification_passes(
            config,
            item["report"]["range_checks"],
            item["report"]["causal_tests"],
            item["report"]["mass_and_energy_consistency"],
            comparison,
        )
        verification_passed = all(
            section["status"] == "PASS" for section in verification.values()
        )
        payload = {
            "candidate_id": candidate_id,
            "parameter_set_id": item["report"]["parameter_set_id"],
            "selection_roles": [],
            "status": (
                "PASS"
                if comparison["status"] == "PASS" and verification_passed
                else "FAIL"
            ),
            "comparison": comparison,
            "verification_passes": verification,
        }
        pilot.write_json_atomic(STABILITY_DIR / f"{candidate_id}.json", payload)
        reports[candidate_id] = payload
    return {
        "status": "PASS"
        if all(item["status"] == "PASS" for item in reports.values())
        else "FAIL",
        "representative_count": len(reports),
        "representatives": reports,
    }


def assign_stability_roles(
    stability: dict[str, Any], representatives: list[dict[str, Any]]
) -> None:
    role_targets = {
        "baseline": representatives[0]["report"]["candidate_id"],
        "hottest": representatives[1]["report"]["candidate_id"],
        "most_humid": representatives[2]["report"]["candidate_id"],
        "driest": representatives[3]["report"]["candidate_id"],
        "near_joint_boundary": representatives[4]["report"]["candidate_id"],
    }
    for role, candidate_id in role_targets.items():
        stability["representatives"][candidate_id]["selection_roles"].append(role)
    for candidate_id, payload in stability["representatives"].items():
        pilot.write_json_atomic(STABILITY_DIR / f"{candidate_id}.json", payload)


def write_final_configs_and_manifest(
    approved: list[dict[str, Any]],
    base_config: ParameterConfig,
    weather_hash: str,
    stability: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    baseline = [item for item in approved if item["report"]["is_baseline"]]
    nonbaseline = [item for item in approved if not item["report"]["is_baseline"]]
    ordered = baseline + sorted(
        nonbaseline, key=lambda item: int(item["report"]["raw_candidate_index"])
    )
    if len(ordered) != 24 or len(baseline) != 1:
        raise PreflightError("Final approval must contain one baseline and 23 LHS sets.")
    representative_ids = set(stability["representatives"])
    rows: list[dict[str, Any]] = []
    sets: list[dict[str, Any]] = []
    for final_index, item in enumerate(ordered):
        report = item["report"]
        final_id = (
            "pa1_full_000_baseline"
            if final_index == 0
            else f"pa1_full_{final_index:03d}"
        )
        values = report["parameters"]
        raw, _, config_hash = sampling.build_parameter_config(
            base_config.raw,
            values,
            final_id,
            final_id,
            final_index,
            int(report["raw_candidate_index"]),
        )
        if config_hash != report["config_hash"]:
            raise PreflightError("Final identity mutation changed a physical config hash.")
        config_path = FINAL_CONFIG_DIR / f"{final_id}.yaml"
        pilot.write_json_atomic(config_path, raw)
        physics_path = ROOT / report["physics_master_file"]
        stability_status = (
            "PASS"
            if report["candidate_id"] in representative_ids
            else "REPRESENTATIVE_COVERAGE"
        )
        metrics = report["metrics"]
        row = {
            "parameter_set_id": final_id,
            "source_candidate_id": report["candidate_id"],
            "sampling_index": final_index,
            "sampling_seed": sampling.SAMPLING_SEED,
            "C_d": values["C_d"],
            "eta_s": values["eta_s"],
            "C_s_J_K": values["C_s"],
            "irrigation_flow_L_h": values["irrigation_flow_L_h"],
            "ET_scale": values["ET_scale"],
            "classification": report["classification"],
            "config_hash": config_hash,
            "config_file": str(config_path.relative_to(ROOT)),
            "config_file_sha256": pilot.sha256_file(config_path),
            "preflight_hash": report["physics_numeric_hash"],
            "preflight_file_sha256": pilot.sha256_file(physics_path),
            "weather_hash": weather_hash,
            "T_air_max": metrics["states"]["T_air"]["max"],
            "RH_max": metrics["states"]["RH"]["max"],
            "RH_saturation_fraction": metrics["humidity"]["saturated_fraction"],
            "RH_100_count": metrics["humidity"]["saturated_rows"],
            "RH_longest_saturation_run": metrics["humidity"]["longest_continuous_saturation_hours"],
            "T_soil_max": metrics["states"]["T_soil"]["max"],
            "hours_soil_above_38": metrics["soil_temperature"]["hours_above_38_c"],
            "hours_soil_above_40": metrics["soil_temperature"]["hours_above_40_c"],
            "soil_moisture_min": metrics["states"]["soil_moisture"]["min"],
            "soil_moisture_max": metrics["states"]["soil_moisture"]["max"],
            "stability_status": stability_status,
        }
        rows.append(row)
        sets.append(dict(row))
        item["final_parameter_set_id"] = final_id
    manifest = {
        "schema_version": "1.0",
        "status": "APPROVED_FULL_RUN",
        "sampling_method": sampling.SAMPLING_METHOD,
        "sampling_version": sampling.SAMPLING_VERSION,
        "sampling_seed": sampling.SAMPLING_SEED,
        "parameter_set_count": len(sets),
        "baseline_count": 1,
        "non_baseline_count": len(sets) - 1,
        "weather_hash": weather_hash,
        "simulator_code_hash": interaction.simulator_code_hash(),
        "full_generation_executed": False,
        "parameter_sets": sets,
    }
    return rows, manifest


def write_final_csv(rows: list[dict[str, Any]]) -> None:
    FINAL_MANIFEST_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = FINAL_MANIFEST_CSV_PATH.with_suffix(".csv.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FINAL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(FINAL_MANIFEST_CSV_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def select_reproducibility_sets(
    approved: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    baseline = next(item for item in approved if item["report"]["is_baseline"])
    lhs = sorted(
        (item for item in approved if not item["report"]["is_baseline"]),
        key=lambda item: int(item["report"]["raw_candidate_index"]),
    )
    arbitrary = lhs[len(lhs) // 2]
    boundary = min(
        lhs,
        key=lambda item: (
            abs(item["report"]["parameters"]["C_d"] - 0.30) / 0.45
            + abs(item["report"]["parameters"]["ET_scale"] - 1.15) / 0.30
        ),
    )
    selected = [baseline, arbitrary, boundary]
    if len({item["report"]["candidate_id"] for item in selected}) != 3:
        boundary = lhs[-1]
        selected = [baseline, arbitrary, boundary]
    return selected


def reproducibility_audit(
    selected: list[dict[str, Any]],
    base_config: ParameterConfig,
    weather: list[Any],
    weather_quality: dict[str, Any],
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for item in selected:
        final_id = item["final_parameter_set_id"]
        values = item["report"]["parameters"]
        _, config, _ = sampling.build_parameter_config(
            base_config.raw,
            values,
            final_id,
            final_id,
            int(final_id.split("_")[-1]) if final_id[-3:].isdigit() else 0,
            int(item["report"]["raw_candidate_index"]),
        )
        parameters = config.to_model_parameters()
        first = run_simulation(
            weather, parameters, internal_timestep_s=60, weather_quality=weather_quality
        )
        second = run_simulation(
            weather, parameters, internal_timestep_s=60, weather_quality=weather_quality
        )
        first_hash = pilot.canonical_hash(first.rows)
        second_hash = pilot.canonical_hash(second.rows)
        numeric_hash = identity_independent_output_hash(first.rows)
        expected_numeric_hash = item["report"]["physics_numeric_hash"]
        status = (
            "PASS"
            if first_hash == second_hash and numeric_hash == expected_numeric_hash
            else "FAIL"
        )
        checks[final_id] = {
            "status": status,
            "first_output_hash": first_hash,
            "second_output_hash": second_hash,
            "numeric_hash": numeric_hash,
            "expected_preflight_numeric_hash": expected_numeric_hash,
        }
        pilot.write_json_atomic(REPRODUCIBILITY_DIR / f"{final_id}.json", checks[final_id])
    return {
        "status": "PASS"
        if all(item["status"] == "PASS" for item in checks.values())
        else "FAIL",
        "checks": checks,
    }


def storage_estimate(final_count: int) -> dict[str, Any]:
    with BASELINE_MASTER_PATH.open("rb") as handle:
        physics_30day_bytes = len(handle.read())
    with ML_DATASET_PATH.open("rb") as handle:
        ml_30day_bytes = len(handle.read())
    rows_30day = 720
    full_rows_per_set = 70128
    total_rows = full_rows_per_set * final_count
    physics_bytes_per_row = physics_30day_bytes / rows_30day
    ml_bytes_per_row = ml_30day_bytes / rows_30day
    config_sizes = [path.stat().st_size for path in FINAL_CONFIG_DIR.glob("*.yaml")]
    validation_sizes = [path.stat().st_size for path in VALIDATION_DIR.glob("*.json")]
    return {
        "physics_master_bytes_per_row": physics_bytes_per_row,
        "deployment_ml_bytes_per_row": ml_bytes_per_row,
        "estimated_physics_master_bytes": round(total_rows * physics_bytes_per_row),
        "estimated_deployment_ml_bytes": round(total_rows * ml_bytes_per_row),
        "estimated_configs_bytes": sum(config_sizes),
        "estimated_validation_metadata_bytes": sum(validation_sizes),
        "total_rows": total_rows,
        "basis": {
            "physics_30day_file": str(BASELINE_MASTER_PATH.relative_to(ROOT)),
            "physics_30day_bytes": physics_30day_bytes,
            "ml_30day_file": str(ML_DATASET_PATH.relative_to(ROOT)),
            "ml_30day_bytes": ml_30day_bytes,
        },
    }


def format_gib(value: int) -> str:
    return f"{value / (1024 ** 3):.3f} GiB"


def render_readiness(report: dict[str, Any]) -> str:
    storage = report["storage_estimate"]
    coverage = report["coverage"]
    lines = [
        "# Full Generation Readiness",
        "",
        "Status: `FULL_GENERATION_READY = YES`",
        "",
        "## Final parameter sets",
        "",
        f"- Count: `{report['final_approved']}` (`1` baseline + `{report['final_approved'] - 1}` constrained-LHS sets).",
        f"- Approved CSV: `{FINAL_MANIFEST_CSV_PATH.name}`.",
        f"- Machine-readable manifest: `{FINAL_MANIFEST_YAML_PATH.name}`.",
        f"- Manifest SHA-256: `{report['final_manifest_sha256']}`.",
        "",
        "## Sampling",
        "",
        f"- Method: `{sampling.SAMPLING_METHOD}`.",
        f"- Version: `{sampling.SAMPLING_VERSION}`.",
        f"- Seed: `{sampling.SAMPLING_SEED}`.",
        f"- Raw candidates generated: `{report['raw_candidates_generated']}`.",
        f"- Joint-constraint rejects: `{report['joint_constraint_rejects']}`.",
        f"- Physics-preflight rejects: `{report['preflight_rejects']}`.",
        "- All five marginals use inverse triangular CDF mapping from LHS quantiles.",
        "",
        "## Joint constraints",
        "",
    ]
    for constraint in report["joint_constraints"]:
        lines.append(
            f"- `{constraint['constraint_id']}`: `{constraint['status']}`; {constraint.get('reason', constraint.get('rule', ''))}"
        )
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            "| Axis | Min | Max | Mean | Median | Std | Strata |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, values in coverage["axes"].items():
        lines.append(
            f"| `{name}` | {values['min']:.6g} | {values['max']:.6g} | {values['mean']:.6g} | {values['median']:.6g} | {values['std_population']:.6g} | {values['unique_lhs_strata']}/{values['expected_strata']} |"
        )
    lines.extend(
        [
            "",
            "## 30-day preflight",
            "",
            f"- Window: `{report['weather_window'][0]}` through `{report['weather_window'][1]}`.",
            f"- Weather hash: `{report['weather_hash']}`.",
            f"- Simulator hash: `{report['simulator_code_hash']}`.",
            f"- Approved: `{report['final_approved']}`; extreme-valid approved: `{report['extreme_valid_approved']}`.",
            "- Every final set passed schema/range, NaN/Inf, causal, root-water balance, indoor-vapour balance, Tsoil<=40 C, and RH saturation<=5% checks.",
            f"- Representative dt=60/120/300 stability: `{report['stability']['status']}` for `{report['stability']['representative_count']}` sets.",
            f"- Reproducibility reruns: `{report['reproducibility']['status']}` for `{len(report['reproducibility']['checks'])}` sets.",
            "",
            "## Full-generation estimate",
            "",
            f"- Physics rows: `70,128 x {report['final_approved']} = {storage['total_rows']:,}`.",
            f"- Estimated uncompressed physics CSV: `{format_gib(storage['estimated_physics_master_bytes'])}`.",
            f"- Estimated uncompressed deployment ML CSV: `{format_gib(storage['estimated_deployment_ml_bytes'])}`.",
            f"- Final configs: `{storage['estimated_configs_bytes'] / 1024:.1f} KiB`; validation metadata: `{storage['estimated_validation_metadata_bytes'] / 1024:.1f} KiB`.",
            "",
            "## Remaining calibration caveats",
            "",
            "- E8 root-zone solar coupling/capacity remain effective priors pending the fixed-depth soil sensor trajectory.",
            "- E4 ET scale remains a coupled reduced-form axis pending water-loss and T/RH calibration.",
            "- Emitter flow, substrate field capacity/wilting behavior, installed fan flow and soil-sensor percent-to-VWC mapping still require real PA1 measurement.",
            "- Grow-light response is fixed and unidentifiable in the current OFF schedule.",
            "",
            "## ML deployment contract",
            "",
            "`ML_DATA_CONTRACT.md` is unchanged: five sensor variables plus three Raspberry Pi actuator states; physics/weather feature count remains zero.",
            "",
            "## Next command",
            "",
            "Proposed next-milestone interface (not executed in this task):",
            "",
            "```text",
            "python generate_full_synthetic_dataset.py --manifest final_approved_parameter_sets.yaml --weather nha_trang_weather_2018_2025.csv",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def execute_preflight() -> dict[str, Any]:
    joint_space = pilot.load_json(JOINT_SPACE_PATH)
    base_config = load_parameter_config(BASE_CONFIG_PATH)
    attempts, retained, sampling_metadata = sampling.generate_sampling_design(
        joint_space, base_config
    )
    sampling.write_sampling_outputs(
        attempts, retained, sampling_metadata, joint_space
    )

    base_parameters = base_config.to_model_parameters()
    start = datetime.fromisoformat(base_parameters.simulation.start_timestamp)
    weather, weather_quality = load_and_validate_weather_window(
        WEATHER_PATH, start, base_parameters.simulation.duration_days
    )
    weather_hash = pilot.selected_weather_hash(weather)
    if weather_hash != joint_space["weather"]["hash"]:
        raise PreflightError("Weather hash differs from the validated joint-space hash.")
    reference_columns, reference_rows = pilot.read_reference_master(
        BASELINE_MASTER_PATH
    )
    if tuple(reference_columns) != OUTPUT_COLUMNS:
        raise PreflightError("Baseline physics-master schema changed.")
    ml_before = pilot.validate_ml_contract()
    if ml_before["status"] != "PASS":
        raise PreflightError("Canonical ML dataset fails its locked contract.")
    code_hash = interaction.simulator_code_hash()
    if code_hash != joint_space["simulator_code_hash"]:
        raise PreflightError("Simulator code hash differs from the validated joint space.")

    baseline_row = retained[0]
    baseline_item = run_core_preflight(
        baseline_row,
        base_config,
        weather,
        weather_quality,
        weather_hash,
        reference_rows,
        code_hash,
    )
    update_candidate_row(baseline_row, baseline_item["report"])
    sampling.write_csv_atomic(sampling.CANDIDATE_MANIFEST_PATH, attempts)
    if baseline_item["report"]["preflight_status"] not in {"PASS", "EXTREME_VALID"}:
        raise PreflightError("Baseline preflight/reproduction failed; LHS candidates were not run.")

    approved = [baseline_item]
    existing_raw_indices = {int(row["raw_candidate_index"]) for row in attempts}
    stream = sampling.iter_lhs_candidates(joint_space, sampling.SAMPLING_SEED)
    pending = list(retained[1:])
    while len(approved) < 24:
        if not pending:
            replacement, joint_rejects = next_replacement_row(
                stream, existing_raw_indices, joint_space, base_config
            )
            attempts.extend(joint_rejects)
            attempts.append(replacement)
            pending.append(replacement)
        row = pending.pop(0)
        item = run_core_preflight(
            row,
            base_config,
            weather,
            weather_quality,
            weather_hash,
            reference_rows,
            code_hash,
        )
        update_candidate_row(row, item["report"])
        if item["report"]["preflight_status"] in {"PASS", "EXTREME_VALID"}:
            approved.append(item)
        sampling.write_csv_atomic(sampling.CANDIDATE_MANIFEST_PATH, attempts)

    representatives = select_stability_representatives(approved)
    stability = run_stability_audit(representatives, weather, weather_quality)
    assign_stability_roles(stability, representatives)
    if stability["status"] != "PASS":
        raise PreflightError(
            "A representative candidate failed dt stability; final manifests were not written."
        )

    final_rows, final_yaml = write_final_configs_and_manifest(
        approved, base_config, weather_hash, stability
    )
    write_final_csv(final_rows)
    pilot.write_json_atomic(FINAL_MANIFEST_YAML_PATH, final_yaml)
    for item in approved:
        source_id = item["report"]["candidate_id"]
        for row in attempts:
            if row["candidate_id"] == source_id:
                row["final_parameter_set_id"] = item["final_parameter_set_id"]
                row["parameter_set_id"] = item["final_parameter_set_id"]
                break
    sampling.write_csv_atomic(sampling.CANDIDATE_MANIFEST_PATH, attempts)

    reproducibility = reproducibility_audit(
        select_reproducibility_sets(approved),
        base_config,
        weather,
        weather_quality,
    )
    if reproducibility["status"] != "PASS":
        raise PreflightError("Representative reproducibility check failed.")
    ml_after = pilot.validate_ml_contract()
    if ml_before["sha256"] != ml_after["sha256"]:
        raise PreflightError("Preflight changed the canonical ML dataset.")

    final_manifest_hash = pilot.sha256_file(FINAL_MANIFEST_CSV_PATH)
    storage = storage_estimate(len(final_rows))
    approved_candidate_ids = {
        item["report"]["candidate_id"] for item in approved
    }
    approved_sampling_rows = [
        row for row in attempts if row["candidate_id"] in approved_candidate_ids
    ]
    coverage = sampling.coverage_audit(approved_sampling_rows, joint_space)
    summary = {
        "status": "SUCCESS",
        "full_generation_ready": True,
        "sampling_method": sampling.SAMPLING_METHOD,
        "sampling_version": sampling.SAMPLING_VERSION,
        "sampling_seed": sampling.SAMPLING_SEED,
        "dimensions": len(sampling.AXES),
        "requested_non_baseline": sampling.REQUESTED_NON_BASELINE,
        "raw_candidates_generated": len(attempts) - 1,
        "joint_constraint_rejects": sum(
            row["preflight_status"] == "REJECTED_JOINT_CONSTRAINT"
            for row in attempts
        ),
        "preflight_rejects": sum(
            row["preflight_status"] == "REJECTED" for row in attempts
        ),
        "final_approved": len(final_rows),
        "extreme_valid_approved": sum(
            row["classification"] == "EXTREME_VALID_APPROVED"
            for row in final_rows
        ),
        "weather_window": joint_space["weather"]["window"],
        "weather_hash": weather_hash,
        "simulator_code_hash": code_hash,
        "joint_constraints": joint_space["joint_constraints"],
        "coverage": coverage,
        "stability": stability,
        "reproducibility": reproducibility,
        "ml_contract": ml_after,
        "final_manifest_csv": str(FINAL_MANIFEST_CSV_PATH.relative_to(ROOT)),
        "final_manifest_yaml": str(FINAL_MANIFEST_YAML_PATH.relative_to(ROOT)),
        "final_manifest_sha256": final_manifest_hash,
        "storage_estimate": storage,
        "full_generation_executed": False,
    }
    pilot.write_json_atomic(PREFLIGHT_SUMMARY_PATH, summary)
    pilot.write_text_atomic(READINESS_PATH, render_readiness(summary))

    design = pilot.load_json(sampling.SAMPLING_DESIGN_PATH)
    design["preflight_status"] = "PASS"
    design["final_approved"] = len(final_rows)
    design["preflight_summary"] = str(PREFLIGHT_SUMMARY_PATH.relative_to(ROOT))
    pilot.write_json_atomic(sampling.SAMPLING_DESIGN_PATH, design)
    return summary


def main() -> int:
    try:
        summary = execute_preflight()
    except (
        PreflightError,
        sampling.SamplingError,
        pilot.PilotError,
        ParameterConfigError,
        WeatherDataError,
        NumericalSimulationError,
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1
    print("STATUS: SUCCESS")
    print(f"FINAL APPROVED: {summary['final_approved']}")
    print(f"EXTREME VALID: {summary['extreme_valid_approved']}")
    print(f"PREFLIGHT REJECTS: {summary['preflight_rejects']}")
    print(f"MANIFEST: {FINAL_MANIFEST_CSV_PATH}")
    print("FULL GENERATION EXECUTED: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
