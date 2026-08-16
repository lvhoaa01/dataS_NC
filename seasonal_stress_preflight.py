"""Run deterministic multi-window physics preflight for PA1 parameter sets."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any, Sequence

import generate_interaction_scenarios as interaction
import generate_pilot_scenarios as pilot
import preflight_final_parameter_sets as preflight
import select_climate_stress_windows as selector
from physics.config import ParameterConfig, load_parameter_config
from physics.simulator import (
    NumericalSimulationError,
    WeatherForcing,
    load_and_validate_weather_range,
    run_simulation,
)


ROOT = Path(__file__).resolve().parent
V1_MANIFEST_PATH = ROOT / "final_approved_parameter_sets.csv"
WINDOWS_PATH = ROOT / "climate_stress_windows.yaml"
OUTPUT_ROOT = ROOT / "outputs" / "seasonal_stress_preflight"
VALIDATION_DIR = OUTPUT_ROOT / "validation"
SUMMARY_JSON = OUTPUT_ROOT / "v1_candidate_summary.json"
SUMMARY_CSV = ROOT / "seasonal_stress_preflight_summary.csv"
FULL_RUN_STATE_PATH = ROOT / "outputs" / "full_generation" / "state" / "run_state.json"
PREFLIGHT_VERSION = "pa1_multi_season_preflight_v1"
EXPECTED_WINDOW_ROWS = 720


class SeasonalPreflightError(RuntimeError):
    """Raised when a seasonal preflight invariant fails."""


def load_windows(path: Path = WINDOWS_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("weather_hash") != selector.sha256_file(selector.WEATHER_PATH):
        raise SeasonalPreflightError("Stress-window weather hash is stale.")
    types = [item["type"] for item in payload.get("windows", [])]
    expected = [
        "REFERENCE_JUNE",
        "HUMID_STRESS",
        "HOT_SOLAR_STRESS",
        "DRY_VPD_STRESS",
        "TRANSITION_MIXED",
    ]
    if types != expected:
        raise SeasonalPreflightError(f"Unexpected stress-window order: {types}.")
    if payload.get("warmup_days") != 30 or payload.get("window_days") != 30:
        raise SeasonalPreflightError("Seasonal preflight requires 30-day warmup/windows.")
    return payload


def load_v1_rows(path: Path = V1_MANIFEST_PATH) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 24:
        raise SeasonalPreflightError(f"Expected 24 V1 rows, found {len(rows)}.")
    return rows


def load_full_run_state(path: Path = FULL_RUN_STATE_PATH) -> dict[str, Any]:
    if not path.is_file():
        return {"scenarios": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def source_config_for_row(row: dict[str, str]) -> ParameterConfig:
    path = ROOT / row["config_file"].replace("\\", "/")
    config = load_parameter_config(path)
    logical_hash = pilot.canonical_hash(pilot.model_value_payload(config))
    if logical_hash != row["config_hash"]:
        raise SeasonalPreflightError(
            f"{row['parameter_set_id']}: V1 logical config hash mismatch."
        )
    if pilot.sha256_file(path) != row["config_file_sha256"]:
        raise SeasonalPreflightError(
            f"{row['parameter_set_id']}: V1 config file hash mismatch."
        )
    return config


def weather_slices(
    weather: Sequence[WeatherForcing],
    indexes: dict[datetime, int],
    window: dict[str, Any],
    warmup_days: int,
) -> tuple[list[WeatherForcing], list[WeatherForcing], dict[str, Any]]:
    start = datetime.fromisoformat(window["start_timestamp"])
    end = datetime.fromisoformat(window["end_timestamp"])
    warmup_start = start - timedelta(days=warmup_days)
    warmup_index = indexes[warmup_start]
    stress_index = indexes[start]
    warmup = list(weather[warmup_index : stress_index + 1])
    stress_rows = int((end - start).total_seconds() // 3600) + 1
    stress = list(weather[stress_index : stress_index + stress_rows + 1])
    if len(warmup) != warmup_days * 24 + 1:
        raise SeasonalPreflightError(
            f"{window['window_id']}: incomplete warmup forcing."
        )
    if len(stress) != EXPECTED_WINDOW_ROWS + 1:
        raise SeasonalPreflightError(
            f"{window['window_id']}: incomplete scored forcing."
        )
    identity = {
        "warmup_start": warmup_start.isoformat(timespec="minutes"),
        "warmup_end": start.isoformat(timespec="minutes"),
        "stress_start": start.isoformat(timespec="minutes"),
        "stress_end": end.isoformat(timespec="minutes"),
        "warmup_forcing_rows": len(warmup),
        "stress_forcing_rows": len(stress),
    }
    return warmup, stress, identity


def run_window(
    parameter_set_id: str,
    config: ParameterConfig,
    weather: Sequence[WeatherForcing],
    indexes: dict[datetime, int],
    window: dict[str, Any],
    warmup_days: int,
) -> dict[str, Any]:
    parameters = config.to_model_parameters()
    warmup_weather, stress_weather, weather_identity = weather_slices(
        weather, indexes, window, warmup_days
    )
    started = time.perf_counter()
    warmup_result = run_simulation(
        warmup_weather,
        parameters,
        internal_timestep_s=60,
        weather_quality={"status": "PASS", "phase": "warmup"},
    )
    warmup_seconds = time.perf_counter() - started
    scoring_started = time.perf_counter()
    result = run_simulation(
        stress_weather,
        parameters,
        internal_timestep_s=60,
        weather_quality={"status": "PASS", "phase": "stress_scoring"},
        initial_state=warmup_result.final_state,
    )
    scoring_seconds = time.perf_counter() - scoring_started
    output, causal, conservation, framework_pass = preflight.core_validation(
        config, result
    )
    metrics = interaction.scenario_metrics(result, parameters)
    violations = preflight.joint_guard_violations(
        result, metrics, EXPECTED_WINDOW_ROWS
    )
    status = "PASS" if framework_pass and not violations else "FAIL"
    classification = (
        "EXTREME_VALID"
        if status == "PASS"
        and (
            metrics["humidity"]["saturated_fraction"] >= 0.02
            or metrics["states"]["T_soil"]["max"] >= 38.0
            or metrics["soil_water"]["hours_near_wilting"] > 0
        )
        else "VALID"
        if status == "PASS"
        else "INVALID_SEASONAL_REGION"
    )
    handoff = {
        "warmup_final_state": vars(warmup_result.final_state),
        "stress_initial_state": vars(result.initial_state),
        "exact_match": warmup_result.final_state == result.initial_state,
    }
    if not handoff["exact_match"]:
        status = "FAIL"
        classification = "IMPLEMENTATION_FAILURE"
        violations.append("Warmup final state did not equal stress initial state.")
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "parameter_set_id": parameter_set_id,
        "window_id": window["window_id"],
        "window_type": window["type"],
        "status": status,
        "classification": classification,
        "guard_violations": violations,
        "rows": len(result.rows),
        "internal_timestep_s": 60,
        "weather_identity": weather_identity,
        "state_handoff": handoff,
        "metrics": metrics,
        "range_checks": output,
        "causal_tests": causal,
        "mass_and_energy_consistency": conservation,
        "framework_status": "PASS" if framework_pass else "FAIL",
        "runtime_seconds": {
            "warmup": warmup_seconds,
            "scoring": scoring_seconds,
            "total": warmup_seconds + scoring_seconds,
        },
        "warnings": list(warmup_result.warnings) + list(result.warnings),
    }


def validation_identity(
    row: dict[str, str], windows_payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "preflight_version": PREFLIGHT_VERSION,
        "parameter_set_id": row["parameter_set_id"],
        "config_hash": row["config_hash"],
        "weather_hash": windows_payload["weather_hash"],
        "windows_hash": pilot.canonical_hash(windows_payload),
        "simulator_code_hash": interaction.simulator_code_hash(),
    }


def cached_candidate(
    path: Path, identity: dict[str, Any]
) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if payload.get("identity") == identity else None


def full_horizon_status(
    parameter_set_id: str, full_state: dict[str, Any]
) -> str:
    status = full_state.get("scenarios", {}).get(parameter_set_id, {}).get("status")
    if status == "COMPLETE":
        return "FULL_HORIZON_PASS"
    if status == "FAILED_VALIDATION":
        return "FULL_HORIZON_REJECTED"
    return "NOT_RUN"


def run_candidate(
    row: dict[str, str],
    weather: Sequence[WeatherForcing],
    indexes: dict[datetime, int],
    windows_payload: dict[str, Any],
    full_state: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    identifier = row["parameter_set_id"]
    identity = validation_identity(row, windows_payload)
    path = VALIDATION_DIR / f"{identifier}.json"
    if not force:
        cached = cached_candidate(path, identity)
        if cached is not None:
            return cached
    config = source_config_for_row(row)
    started = time.perf_counter()
    window_reports: list[dict[str, Any]] = []
    for index, window in enumerate(windows_payload["windows"], start=1):
        print(
            f"  [{index}/5] {window['type']} {window['start_timestamp']}",
            flush=True,
        )
        try:
            report = run_window(
                identifier,
                config,
                weather,
                indexes,
                window,
                int(windows_payload["warmup_days"]),
            )
        except (NumericalSimulationError, ValueError, OverflowError) as exc:
            report = {
                "preflight_version": PREFLIGHT_VERSION,
                "parameter_set_id": identifier,
                "window_id": window["window_id"],
                "window_type": window["type"],
                "status": "FAIL",
                "classification": "IMPLEMENTATION_FAILURE",
                "guard_violations": [str(exc)],
            }
        window_reports.append(report)
    seasonal_status = (
        "SEASONAL_PREFLIGHT_PASS"
        if all(item["status"] == "PASS" for item in window_reports)
        else "SEASONAL_PREFLIGHT_FAIL"
    )
    horizon_status = full_horizon_status(identifier, full_state)
    if horizon_status == "FULL_HORIZON_PASS":
        classification = "RETAINED_FULL_HORIZON_PASS"
    elif horizon_status == "FULL_HORIZON_REJECTED":
        classification = "REJECTED_FULL_HORIZON_V1"
    else:
        classification = seasonal_status
    payload = {
        "identity": identity,
        "parameters": preflight.row_values(row),
        "seasonal_preflight_status": seasonal_status,
        "full_horizon_status": horizon_status,
        "classification": classification,
        "runtime_seconds": time.perf_counter() - started,
        "windows": window_reports,
    }
    pilot.write_json_atomic(path, payload)
    return payload


def summary_row(report: dict[str, Any]) -> dict[str, Any]:
    by_type = {item["window_type"]: item for item in report["windows"]}
    humid = by_type["HUMID_STRESS"]
    return {
        "parameter_set_id": report["identity"]["parameter_set_id"],
        **report["parameters"],
        "seasonal_preflight_status": report["seasonal_preflight_status"],
        "full_horizon_status": report["full_horizon_status"],
        "classification": report["classification"],
        "reference_june_status": by_type["REFERENCE_JUNE"]["status"],
        "humid_stress_status": humid["status"],
        "hot_solar_status": by_type["HOT_SOLAR_STRESS"]["status"],
        "dry_vpd_status": by_type["DRY_VPD_STRESS"]["status"],
        "transition_status": by_type["TRANSITION_MIXED"]["status"],
        "humid_RH_100_count": humid.get("metrics", {})
        .get("humidity", {})
        .get("saturated_rows", ""),
        "humid_RH_saturation_fraction": humid.get("metrics", {})
        .get("humidity", {})
        .get("saturated_fraction", ""),
        "humid_RH_longest_run": humid.get("metrics", {})
        .get("humidity", {})
        .get("longest_continuous_saturation_hours", ""),
        "runtime_seconds": report["runtime_seconds"],
    }


def write_summary(reports: Sequence[dict[str, Any]]) -> None:
    rows = [summary_row(report) for report in reports]
    pilot.write_json_atomic(SUMMARY_JSON, rows)
    temporary = SUMMARY_CSV.with_suffix(SUMMARY_CSV.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(SUMMARY_CSV)


def execute(
    parameter_sets: Sequence[str] | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    windows_payload = load_windows()
    rows = load_v1_rows()
    if parameter_sets:
        requested = set(parameter_sets)
        rows = [row for row in rows if row["parameter_set_id"] in requested]
        missing = requested - {row["parameter_set_id"] for row in rows}
        if missing:
            raise SeasonalPreflightError(f"Unknown parameter sets: {sorted(missing)}")
    weather, quality = load_and_validate_weather_range(
        selector.WEATHER_PATH,
        selector.FULL_START,
        selector.FULL_END,
        allow_terminal_hold=True,
    )
    indexes = {
        datetime.fromisoformat(row.timestamp): index for index, row in enumerate(weather)
    }
    full_state = load_full_run_state()
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, row in enumerate(rows, start=1):
        print(
            f"[{index:02d}/{len(rows):02d}] {row['parameter_set_id']} SEASONAL_PREFLIGHT",
            flush=True,
        )
        report = run_candidate(
            row,
            weather,
            indexes,
            windows_payload,
            full_state,
            force=force,
        )
        reports.append(report)
        print(
            f"[{index:02d}/{len(rows):02d}] {row['parameter_set_id']} "
            f"{report['seasonal_preflight_status']}",
            flush=True,
        )
    write_summary(reports)
    return {
        "status": "PASS",
        "weather_quality": quality,
        "parameter_sets": len(reports),
        "passed": sum(
            item["seasonal_preflight_status"] == "SEASONAL_PREFLIGHT_PASS"
            for item in reports
        ),
        "failed": sum(
            item["seasonal_preflight_status"] == "SEASONAL_PREFLIGHT_FAIL"
            for item in reports
        ),
        "runtime_seconds": time.perf_counter() - started,
        "reports": reports,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run warm-started multi-season physics preflight."
    )
    parser.add_argument("--parameter-set", action="append", dest="parameter_sets")
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = execute(args.parameter_sets, force=args.force)
    print(f"STATUS: {report['status']}")
    print(f"PARAMETER_SETS: {report['parameter_sets']}")
    print(f"PASSED: {report['passed']}")
    print(f"FAILED: {report['failed']}")
    print(f"RUNTIME_SECONDS: {report['runtime_seconds']:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
