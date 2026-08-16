"""Production-style SmartGarden full-generation runner.

The runner is intentionally sequential and scenario-isolated. It supports the
approved 2018-2025 workload, but this module never starts that workload unless
the caller explicitly passes ``--full``.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import time
import traceback
from typing import Any, Iterable, Sequence

import build_ml_dataset as ml_builder
import generate_final_parameter_sets as sampling
import generate_interaction_scenarios as interaction
import generate_pilot_scenarios as pilot
import preflight_final_parameter_sets as preflight
from physics.config import ParameterConfig, load_parameter_config
from physics.simulator import (
    OUTPUT_COLUMNS,
    SimulationResult,
    WeatherDataError,
    WeatherForcing,
    load_and_validate_weather_range,
    run_simulation,
)
from physics.validation import (
    conservation_audit,
    run_causal_tests,
    validate_output_ranges,
)


ROOT = Path(__file__).resolve().parent
FINAL_MANIFEST_CSV = ROOT / "final_approved_parameter_sets.csv"
FINAL_MANIFEST_YAML = ROOT / "final_approved_parameter_sets.yaml"
JOINT_SPACE_PATH = ROOT / "joint_parameter_space.yaml"
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
WEATHER_METADATA_PATH = ROOT / "nha_trang_weather_2018_2025_metadata.txt"
FULL_OUTPUT_ROOT = ROOT / "outputs" / "full_generation"
BENCHMARK_OUTPUT_ROOT = ROOT / "outputs" / "full_generation_benchmark"
KNOWN_FINAL_MANIFEST_SHA256 = (
    "194779c518d07182811449838250b1ce13f62da5634ce50b7b2594fba8ece9b8"
)
RUNNER_VERSION = "pa1_full_generation_runner_v1"
TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
FULL_START = datetime(2018, 1, 1, 0, 0)
FULL_END_INCLUSIVE = datetime(2025, 12, 31, 23, 0)
BENCHMARK_START = datetime(2024, 1, 1, 0, 0)
BENCHMARK_END_INCLUSIVE = datetime(2024, 12, 31, 23, 0)
EXPECTED_FULL_ROWS = 70_128
ACCEPTED_CLASSIFICATIONS = {
    "APPROVED_FULL_RUN",
    "EXTREME_VALID_APPROVED",
}
STATE_VALUES = {
    "PENDING",
    "RUNNING",
    "PHYSICS_DONE",
    "PHYSICS_VALIDATED",
    "ML_DONE",
    "ML_VALIDATED",
    "COMPLETE",
    "FAILED",
    "FAILED_VALIDATION",
    "INTERRUPTED",
    "STALE_OUTPUT",
    "CONFIG_MISMATCH",
    "WEATHER_MISMATCH",
}
MANIFEST_COLUMNS = (
    "parameter_set_id",
    "source_config_hash",
    "run_config_hash",
    "weather_hash",
    "status",
    "start_timestamp",
    "end_timestamp",
    "expected_rows",
    "physics_rows",
    "ml_rows",
    "physics_hash",
    "ml_hash",
    "runtime_seconds",
    "validation_status",
    "error",
)


class FullGenerationError(RuntimeError):
    """Raised when a production generation invariant fails."""


class PhysicsValidationFailure(FullGenerationError):
    """Raised when physics finishes but cannot pass the locked gates."""


@dataclass(frozen=True)
class GenerationJob:
    parameter_set_id: str
    manifest_row: dict[str, str]
    start: datetime
    end_inclusive: datetime
    expected_rows: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def replace_atomic_with_retry(
    temporary: Path,
    destination: Path,
    *,
    attempts: int = 8,
) -> None:
    """Commit an atomic file while tolerating short Windows scanner locks."""

    for attempt in range(attempts):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.025 * (2**attempt))


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_atomic_with_retry(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def write_csv_atomic(
    path: Path,
    rows: Sequence[dict[str, Any]],
    columns: Sequence[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        replace_atomic_with_retry(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def csv_shape(path: Path) -> tuple[int, tuple[str, ...]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = tuple(next(reader))
        except StopIteration:
            return 0, ()
        return sum(1 for _ in reader), header


def peak_rss_bytes() -> int | None:
    """Return process peak RSS using only the standard library when available."""

    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        )
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        success = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        return int(counters.PeakWorkingSetSize) if success else None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(usage if os.uname().sysname == "Darwin" else usage * 1024)
    except (ImportError, AttributeError, OSError):
        return None


def resolve_project_path(value: str) -> Path:
    normalized = value.replace("\\", "/")
    path = Path(normalized)
    return path if path.is_absolute() else ROOT / path


def load_manifest_rows(path: Path = FINAL_MANIFEST_CSV) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def manifest_parameter_values(row: dict[str, str]) -> dict[str, float]:
    return {
        "C_d": float(row["C_d"]),
        "eta_s": float(row["eta_s"]),
        "C_s": float(row["C_s_J_K"]),
        "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
        "ET_scale": float(row["ET_scale"]),
    }


def audit_final_manifest() -> dict[str, Any]:
    rows = load_manifest_rows()
    machine = json.loads(FINAL_MANIFEST_YAML.read_text(encoding="utf-8"))
    joint_space = json.loads(JOINT_SPACE_PATH.read_text(encoding="utf-8"))
    manifest_hash = sha256_file(FINAL_MANIFEST_CSV)
    errors: list[str] = []
    ids = [row["parameter_set_id"] for row in rows]
    config_hashes = [row["config_hash"] for row in rows]
    baseline_count = sum(identifier == "pa1_full_000_baseline" for identifier in ids)
    if len(rows) != 24:
        errors.append(f"Expected 24 parameter sets, found {len(rows)}.")
    if baseline_count != 1:
        errors.append(f"Expected one baseline, found {baseline_count}.")
    if len(set(ids)) != len(ids):
        errors.append("Duplicate parameter_set_id values found.")
    if len(set(config_hashes)) != len(config_hashes):
        errors.append("Duplicate approved config_hash values found.")
    if machine.get("status") != "APPROVED_FULL_RUN":
        errors.append("Machine manifest status is not APPROVED_FULL_RUN.")
    if machine.get("parameter_set_count") != len(rows):
        errors.append("CSV and machine manifest counts disagree.")
    machine_ids = [item["parameter_set_id"] for item in machine.get("parameter_sets", [])]
    if machine_ids != ids:
        errors.append("CSV and machine manifest parameter-set order differs.")
    if manifest_hash != KNOWN_FINAL_MANIFEST_SHA256:
        errors.append(
            "Final manifest hash differs from the locked readiness milestone; "
            "no authorized manifest update was found."
        )

    config_audits: list[dict[str, Any]] = []
    for row in rows:
        identifier = row["parameter_set_id"]
        if row["classification"] not in ACCEPTED_CLASSIFICATIONS:
            errors.append(f"{identifier}: classification is not approved.")
        config_path = resolve_project_path(row["config_file"])
        if not config_path.is_file():
            errors.append(f"{identifier}: approved config file is missing.")
            continue
        config_file_hash = sha256_file(config_path)
        config = load_parameter_config(config_path)
        logical_hash = pilot.canonical_hash(pilot.model_value_payload(config))
        constraint_pass, violations = sampling.evaluate_joint_constraints(
            manifest_parameter_values(row), joint_space
        )
        if config_file_hash != row["config_file_sha256"]:
            errors.append(f"{identifier}: config file SHA-256 mismatch.")
        if logical_hash != row["config_hash"]:
            errors.append(f"{identifier}: logical config hash mismatch.")
        if not constraint_pass:
            errors.append(f"{identifier}: joint constraints violated: {violations}.")
        config_audits.append(
            {
                "parameter_set_id": identifier,
                "classification": row["classification"],
                "config_file": str(config_path.relative_to(ROOT)),
                "config_file_sha256": config_file_hash,
                "config_hash": logical_hash,
                "joint_constraint_pass": constraint_pass,
            }
        )

    audit = {
        "status": "PASS" if not errors else "FAIL",
        "manifest_csv": str(FINAL_MANIFEST_CSV.relative_to(ROOT)),
        "manifest_yaml": str(FINAL_MANIFEST_YAML.relative_to(ROOT)),
        "manifest_sha256": manifest_hash,
        "known_manifest_sha256": KNOWN_FINAL_MANIFEST_SHA256,
        "known_hash_match": manifest_hash == KNOWN_FINAL_MANIFEST_SHA256,
        "parameter_sets": len(rows),
        "baseline_count": baseline_count,
        "non_baseline_count": len(rows) - baseline_count,
        "unique_parameter_set_ids": len(set(ids)),
        "unique_config_hashes": len(set(config_hashes)),
        "accepted_classifications": sorted(
            {row["classification"] for row in rows}
        ),
        "config_audits": config_audits,
        "errors": errors,
    }
    if errors:
        raise FullGenerationError("Final manifest audit failed: " + " | ".join(errors))
    return audit


def audit_weather_dataset() -> tuple[list[WeatherForcing], dict[str, Any]]:
    weather, quality = load_and_validate_weather_range(
        WEATHER_PATH,
        FULL_START,
        FULL_END_INCLUSIVE,
        allow_terminal_hold=True,
    )
    raw_rows = quality["rows_checked"]
    errors: list[str] = []
    if raw_rows != EXPECTED_FULL_ROWS:
        errors.append(f"Expected {EXPECTED_FULL_ROWS} raw rows, found {raw_rows}.")
    if quality["first_timestamp"] != "2018-01-01T00:00":
        errors.append("Weather start timestamp changed.")
    if quality["last_timestamp"] != "2025-12-31T23:00":
        errors.append("Weather end timestamp changed.")
    metadata = WEATHER_METADATA_PATH.read_text(encoding="utf-8-sig")
    if TIMEZONE_NAME not in metadata:
        errors.append(f"Weather metadata does not declare {TIMEZONE_NAME}.")
    raw_weather = weather[:-1]
    leap_2024_rows = sum(
        datetime.fromisoformat(item.timestamp).year == 2024 for item in raw_weather
    )
    leap_day_rows = sum(
        datetime.fromisoformat(item.timestamp).date().isoformat() == "2024-02-29"
        for item in raw_weather
    )
    if leap_2024_rows != 8784 or leap_day_rows != 24:
        errors.append("2024 leap-year coverage is incomplete.")
    audit = {
        "status": "PASS" if not errors else "FAIL",
        "file": str(WEATHER_PATH.relative_to(ROOT)),
        "sha256": sha256_file(WEATHER_PATH),
        "timezone": TIMEZONE_NAME,
        "rows": raw_rows,
        "columns": len(quality["columns"]),
        "start_timestamp": quality["first_timestamp"],
        "end_timestamp": quality["last_timestamp"],
        "duplicates": quality["duplicates"],
        "timestamp_gaps": quality["timestamp_gaps"],
        "nonfinite_core_values": quality["nonfinite_core_values"],
        "leap_2024_rows": leap_2024_rows,
        "leap_day_2024_rows": leap_day_rows,
        "full_run_terminal_endpoint_policy": quality["terminal_endpoint_policy"],
        "raw_dataset_modified": False,
        "errors": errors,
    }
    if errors:
        raise FullGenerationError("Weather audit failed: " + " | ".join(errors))
    return weather, audit


def expected_rows(start: datetime, end_inclusive: datetime) -> int:
    seconds = (end_inclusive - start).total_seconds()
    if seconds < 0 or seconds % 3600:
        raise FullGenerationError("Generation windows must contain aligned hourly rows.")
    rows = int(seconds // 3600) + 1
    if rows % 24:
        raise FullGenerationError(
            "Production runner currently requires whole-day windows ending at 23:00."
        )
    return rows


def parse_start(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(hour=0) if len(value) == 10 else parsed


def parse_end(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed.replace(hour=23) if len(value) == 10 else parsed


def resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.benchmark:
        return BENCHMARK_START, BENCHMARK_END_INCLUSIVE
    if args.full or (args.dry_run and not args.parameter_set):
        return FULL_START, FULL_END_INCLUSIVE
    if args.start_date or args.end_date:
        if not args.start_date or not args.end_date:
            raise FullGenerationError("Both --start-date and --end-date are required.")
        return parse_start(args.start_date), parse_end(args.end_date)
    start_year = args.start_year or 2024
    end_year = args.end_year or start_year
    if end_year < start_year:
        raise FullGenerationError("end-year precedes start-year.")
    return datetime(start_year, 1, 1), datetime(end_year, 12, 31, 23)


def resolve_jobs(args: argparse.Namespace, rows: list[dict[str, str]]) -> list[GenerationJob]:
    start, end = resolve_window(args)
    count = expected_rows(start, end)
    if args.benchmark:
        selected = [row for row in rows if row["parameter_set_id"] == "pa1_full_000_baseline"]
    elif args.full or (args.dry_run and not args.parameter_set):
        selected = rows
    else:
        selected = [row for row in rows if row["parameter_set_id"] == args.parameter_set]
    if not selected:
        raise FullGenerationError("Requested parameter set was not found in the final manifest.")
    return [
        GenerationJob(row["parameter_set_id"], row, start, end, count)
        for row in selected
    ]


def select_weather(
    all_weather: Sequence[WeatherForcing], job: GenerationJob
) -> tuple[list[WeatherForcing], dict[str, Any]]:
    endpoint = job.end_inclusive + timedelta(hours=1)
    selected = [
        item
        for item in all_weather
        if job.start <= datetime.fromisoformat(item.timestamp) <= endpoint
    ]
    if len(selected) != job.expected_rows + 1:
        raise WeatherDataError(
            f"{job.parameter_set_id}: expected {job.expected_rows + 1} forcing rows, "
            f"found {len(selected)}."
        )
    terminal_hold = endpoint > FULL_END_INCLUSIVE
    quality = {
        "status": "PASS",
        "window_output_rows": job.expected_rows,
        "window_forcing_rows_including_endpoint": len(selected),
        "requested_start": job.start.isoformat(timespec="minutes"),
        "requested_end_inclusive": job.end_inclusive.isoformat(timespec="minutes"),
        "terminal_endpoint_policy": (
            "last_value_hold" if terminal_hold else "observed_next_hour"
        ),
        "terminal_hold_applied": terminal_hold,
    }
    return selected, quality


def derive_run_config(
    job: GenerationJob,
) -> tuple[dict[str, Any], ParameterConfig, str, str]:
    source_path = resolve_project_path(job.manifest_row["config_file"])
    source_config = load_parameter_config(source_path)
    source_hash = pilot.canonical_hash(pilot.model_value_payload(source_config))
    if source_hash != job.manifest_row["config_hash"]:
        raise FullGenerationError(
            f"{job.parameter_set_id}: approved source config hash mismatch."
        )
    raw = deepcopy(source_config.raw)
    pilot.set_value(raw, "identity.parameter_set_id", job.parameter_set_id)
    pilot.set_value(
        raw,
        "identity.simulation_id",
        (
            f"{job.parameter_set_id}_{job.start:%Y%m%d}_"
            f"{job.end_inclusive:%Y%m%d}_physics_v1"
        ),
    )
    pilot.set_value(
        raw,
        "simulation.start_timestamp",
        job.start.isoformat(timespec="minutes"),
    )
    pilot.set_value(raw, "simulation.duration_days", job.expected_rows // 24)
    config = ParameterConfig(raw, source_path)
    run_hash = pilot.canonical_hash(pilot.model_value_payload(config))
    return raw, config, source_hash, run_hash


def scenario_paths(output_root: Path, identifier: str) -> dict[str, Path]:
    return {
        "physics": output_root / "physics" / f"{identifier}.csv",
        "ml": output_root / "ml" / f"{identifier}.csv",
        "ml_metadata": output_root / "ml" / f"{identifier}_metadata.json",
        "validation": output_root / "validation" / f"{identifier}.json",
        "config": output_root / "configs" / f"{identifier}.yaml",
        "log": output_root / "logs" / f"{identifier}.json",
    }


def identity_payload(
    job: GenerationJob,
    source_config_hash: str,
    run_config_hash: str,
    weather_hash: str,
) -> dict[str, Any]:
    return {
        "parameter_set_id": job.parameter_set_id,
        "source_config_hash": source_config_hash,
        "run_config_hash": run_config_hash,
        "weather_hash": weather_hash,
        "start_timestamp": job.start.isoformat(timespec="minutes"),
        "end_timestamp": job.end_inclusive.isoformat(timespec="minutes"),
        "expected_rows": job.expected_rows,
        "internal_timestep_s": 60,
        "runner_version": RUNNER_VERSION,
        "simulator_code_hash": interaction.simulator_code_hash(),
    }


def cache_decision(
    entry: dict[str, Any] | None,
    identity: dict[str, Any],
    paths: dict[str, Path],
) -> tuple[str, str]:
    if not entry:
        return "RERUN", "PENDING"
    if entry.get("run_config_hash") != identity["run_config_hash"]:
        return "RERUN", "CONFIG_MISMATCH"
    if entry.get("weather_hash") != identity["weather_hash"]:
        return "RERUN", "WEATHER_MISMATCH"
    if entry.get("status") == "RUNNING":
        return "RERUN", "INTERRUPTED"
    if entry.get("status") != "COMPLETE":
        if any(path.with_suffix(path.suffix + ".tmp").exists() for path in paths.values()):
            return "RERUN", "PARTIAL_TMP"
        return "RERUN", str(entry.get("status", "INCOMPLETE"))
    for name in (
        "physics",
        "ml",
        "ml_metadata",
        "validation",
        "config",
        "log",
    ):
        if not paths[name].is_file():
            return "RERUN", "STALE_OUTPUT"
    physics_rows, physics_columns = csv_shape(paths["physics"])
    ml_rows, ml_columns = csv_shape(paths["ml"])
    if physics_rows != identity["expected_rows"] or physics_columns != OUTPUT_COLUMNS:
        return "RERUN", "STALE_OUTPUT"
    if ml_rows != identity["expected_rows"] or ml_columns != ml_builder.CANONICAL_COLUMNS:
        return "RERUN", "STALE_OUTPUT"
    if sha256_file(paths["physics"]) != entry.get("physics_hash"):
        return "RERUN", "STALE_OUTPUT"
    if sha256_file(paths["ml"]) != entry.get("ml_hash"):
        return "RERUN", "STALE_OUTPUT"
    if entry.get("validation_status") != "PASS":
        return "RERUN", "STALE_OUTPUT"
    try:
        validation = json.loads(paths["validation"].read_text(encoding="utf-8"))
        ml_metadata = json.loads(paths["ml_metadata"].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "RERUN", "STALE_OUTPUT"
    if validation.get("status") != "PASS" or ml_metadata.get("status") != "PASS":
        return "RERUN", "STALE_OUTPUT"
    return "SKIP", "COMPLETE"


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information, False, pid
        )
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return ctypes.windll.kernel32.GetLastError() == 5
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


class RunLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.acquired = False

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
                owner_pid = int(payload.get("pid", -1))
            except (OSError, ValueError, json.JSONDecodeError):
                owner_pid = -1
            if process_alive(owner_pid):
                raise FullGenerationError(
                    f"Output directory is locked by active PID {owner_pid}."
                )
            self.path.unlink(missing_ok=True)
        descriptor = os.open(
            self.path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        )
        try:
            payload = json.dumps(
                {"pid": os.getpid(), "created_at": utc_now()},
                indent=2,
            ).encode("utf-8")
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        self.acquired = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False


def prepare_output_root(output_root: Path) -> None:
    for name in ("physics", "ml", "validation", "configs", "state", "logs"):
        (output_root / name).mkdir(parents=True, exist_ok=True)


def load_run_state(output_root: Path, mode: str) -> dict[str, Any]:
    path = output_root / "state" / "run_state.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise FullGenerationError("Unsupported run-state schema version.")
        return payload
    return {
        "schema_version": "1.0",
        "runner_version": RUNNER_VERSION,
        "mode": mode,
        "full_mode_executed": mode == "full",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "scenarios": {},
    }


def manifest_rows_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for identifier in sorted(state["scenarios"]):
        entry = state["scenarios"][identifier]
        rows.append({column: entry.get(column, "") for column in MANIFEST_COLUMNS})
    return rows


def save_run_state(output_root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    write_json_atomic(output_root / "state" / "run_state.json", state)
    write_csv_atomic(
        output_root / "full_generation_manifest.csv",
        manifest_rows_from_state(state),
        MANIFEST_COLUMNS,
    )


def update_state_entry(
    output_root: Path,
    state: dict[str, Any],
    identifier: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    entry = state["scenarios"].setdefault(identifier, {})
    entry.update(updates)
    status = entry.get("status")
    if status not in STATE_VALUES:
        raise FullGenerationError(f"Unsupported scenario status {status!r}.")
    save_run_state(output_root, state)
    return entry


def validate_physics_result(
    result: SimulationResult,
    config: ParameterConfig,
    expected_row_count: int,
) -> dict[str, Any]:
    parameters = config.to_model_parameters()
    output = validate_output_ranges(result, parameters)
    causal = run_causal_tests(parameters)
    conservation = conservation_audit(result, parameters)
    metrics = interaction.scenario_metrics(result, parameters)
    guards = preflight.joint_guard_violations(
        result, metrics, expected_row_count
    )
    schema_pass = bool(result.rows) and tuple(result.rows[0]) == OUTPUT_COLUMNS
    passed = (
        output["status"] == "PASS"
        and causal["status"] == "PASS"
        and conservation["status"] == "PASS"
        and schema_pass
        and not guards
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "schema_status": "PASS" if schema_pass else "FAIL",
        "output_ranges": output,
        "causal_tests": causal,
        "conservation": conservation,
        "joint_guards": {
            "status": "PASS" if not guards else "FAIL",
            "violations": guards,
            "soil_temperature_max_c": metrics["soil_temperature"]["max_c"],
            "rh_saturation_fraction": metrics["humidity"]["saturated_fraction"],
        },
        "metrics": metrics,
    }


def write_ml_atomic_timed(
    path: Path,
    rows: list[dict[str, str]],
    expected_row_count: int,
) -> tuple[float, float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_started = time.perf_counter()
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=ml_builder.CANONICAL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        write_seconds = time.perf_counter() - write_started
        validation_started = time.perf_counter()
        ml_builder.validate_canonical_file(temporary, expected_row_count)
        validation_seconds = time.perf_counter() - validation_started
        replace_atomic_with_retry(temporary, path)
        _fsync_directory(path.parent)
        return write_seconds, validation_seconds
    finally:
        temporary.unlink(missing_ok=True)


def run_one_job(
    job: GenerationJob,
    output_root: Path,
    state: dict[str, Any],
    all_weather: Sequence[WeatherForcing],
    raw_weather_hash: str,
    *,
    force: bool,
) -> dict[str, Any]:
    identifier = job.parameter_set_id
    paths = scenario_paths(output_root, identifier)
    raw_config, config, source_config_hash, run_config_hash = derive_run_config(job)
    weather, weather_quality = select_weather(all_weather, job)
    weather_hash = pilot.selected_weather_hash(weather)
    identity = identity_payload(
        job, source_config_hash, run_config_hash, weather_hash
    )
    existing = state["scenarios"].get(identifier)
    decision, reason = cache_decision(existing, identity, paths)
    if decision == "SKIP" and not force:
        existing["last_resume_action"] = "SKIPPED_COMPLETE"
        existing["last_checked_at"] = utc_now()
        save_run_state(output_root, state)
        return {"parameter_set_id": identifier, "action": "SKIPPED", **existing}

    started_at = utc_now()
    wall_started = time.perf_counter()
    entry = {
        **identity,
        "source_weather_sha256": raw_weather_hash,
        "status": "RUNNING",
        "resume_reason": "FORCED" if force else reason,
        "start_time_utc": started_at,
        "end_time_utc": "",
        "physics_rows": 0,
        "ml_rows": 0,
        "physics_hash": "",
        "ml_hash": "",
        "runtime_seconds": 0.0,
        "validation_status": "PENDING",
        "error": "",
    }
    update_state_entry(output_root, state, identifier, entry)
    stage = "SIMULATION"
    try:
        write_json_atomic(paths["config"], raw_config)
        config_file_sha256 = sha256_file(paths["config"])

        simulation_started = time.perf_counter()
        result = run_simulation(
            weather,
            config.to_model_parameters(),
            internal_timestep_s=60,
            weather_quality=weather_quality,
        )
        physics_simulation_seconds = time.perf_counter() - simulation_started
        if len(result.rows) != job.expected_rows:
            raise FullGenerationError(
                f"Simulator returned {len(result.rows)} rows; expected {job.expected_rows}."
            )

        stage = "PHYSICS_WRITE"
        write_started = time.perf_counter()
        write_csv_atomic(paths["physics"], result.rows, OUTPUT_COLUMNS)
        physics_write_seconds = time.perf_counter() - write_started
        physics_hash = sha256_file(paths["physics"])
        update_state_entry(
            output_root,
            state,
            identifier,
            {
                "status": "PHYSICS_DONE",
                "physics_rows": len(result.rows),
                "physics_hash": physics_hash,
            },
        )

        stage = "PHYSICS_VALIDATION"
        validation_started = time.perf_counter()
        physics_validation = validate_physics_result(
            result, config, job.expected_rows
        )
        physics_validation_seconds = time.perf_counter() - validation_started
        if physics_validation["status"] != "PASS":
            raise PhysicsValidationFailure(
                "Physics validation failed: "
                + " | ".join(
                    physics_validation["output_ranges"]["violations"]
                    + physics_validation["joint_guards"]["violations"]
                )
            )
        update_state_entry(
            output_root,
            state,
            identifier,
            {"status": "PHYSICS_VALIDATED", "validation_status": "PASS"},
        )

        stage = "ML_EXTRACTION"
        extraction_started = time.perf_counter()
        ml_rows, observation_mode, sensor_noise, mapping, identities = (
            ml_builder.build_rows(
                paths["physics"],
                {"sensor_model": {"noise_enabled": False}},
                job.expected_rows,
            )
        )
        ml_extraction_seconds = time.perf_counter() - extraction_started

        stage = "ML_WRITE"
        ml_write_seconds, ml_validation_seconds = write_ml_atomic_timed(
            paths["ml"], ml_rows, job.expected_rows
        )
        ml_hash = sha256_file(paths["ml"])
        update_state_entry(
            output_root,
            state,
            identifier,
            {"status": "ML_DONE", "ml_rows": len(ml_rows), "ml_hash": ml_hash},
        )
        ml_builder.validate_canonical_file(paths["ml"], job.expected_rows)
        update_state_entry(
            output_root,
            state,
            identifier,
            {"status": "ML_VALIDATED"},
        )

        ml_metadata = {
            "status": "PASS",
            "contract": "ML_DATA_CONTRACT.md",
            "contract_version": "1.0",
            "source_type": "synthetic",
            "parameter_set_id": identifier,
            "simulation_id": identities["simulation_id"],
            "rows": len(ml_rows),
            "columns": list(ml_builder.CANONICAL_COLUMNS),
            "model_features": list(ml_builder.BASELINE_FEATURES),
            "observation_mode": observation_mode,
            "sensor_noise_enabled": sensor_noise,
            "source_column_mapping": mapping,
            "physics_feature_count": 0,
            "weather_feature_count": 0,
            "soil_moisture_real_adapter_status": "TO_CALIBRATE",
        }
        write_json_atomic(paths["ml_metadata"], ml_metadata)

        elapsed = time.perf_counter() - wall_started
        internal_steps = job.expected_rows * 3600 // 60
        timings = {
            "physics_simulation_seconds": physics_simulation_seconds,
            "physics_csv_write_seconds": physics_write_seconds,
            "physics_validation_seconds": physics_validation_seconds,
            "ml_extraction_seconds": ml_extraction_seconds,
            "ml_csv_write_seconds": ml_write_seconds,
            "ml_validation_seconds": ml_validation_seconds,
            "total_wall_seconds": elapsed,
        }
        report = {
            "status": "PASS",
            "classification": (
                "EXTREME_VALID"
                if (
                    physics_validation["metrics"]["states"]["T_soil"]["max"] >= 38.0
                    or physics_validation["metrics"]["humidity"]["saturated_fraction"] >= 0.02
                    or physics_validation["metrics"]["soil_water"]["hours_near_wilting"] > 0
                )
                else "VALID"
            ),
            **identity,
            "source_weather_sha256": raw_weather_hash,
            "weather_quality": weather_quality,
            "initialization": (
                "standalone_window_initialization"
                if job.start != FULL_START
                else "full_run_initial_state_at_2018_start"
            ),
            "full_run_continuity_policy": (
                "One simulator call per parameter set; no annual state reset."
            ),
            "physics": physics_validation,
            "ml": ml_metadata,
            "timings": timings,
            "throughput": {
                "hourly_rows_per_second_simulation": (
                    job.expected_rows / physics_simulation_seconds
                ),
                "internal_steps": internal_steps,
                "internal_steps_per_second": (
                    internal_steps / physics_simulation_seconds
                ),
            },
            "memory": {
                "peak_rss_bytes": peak_rss_bytes(),
                "measurement": "process_peak_working_set",
            },
            "files": {
                "config": str(paths["config"].relative_to(ROOT)),
                "config_sha256": config_file_sha256,
                "physics": str(paths["physics"].relative_to(ROOT)),
                "physics_sha256": physics_hash,
                "physics_bytes": paths["physics"].stat().st_size,
                "ml": str(paths["ml"].relative_to(ROOT)),
                "ml_sha256": ml_hash,
                "ml_bytes": paths["ml"].stat().st_size,
                "ml_metadata": str(paths["ml_metadata"].relative_to(ROOT)),
            },
            "warnings": result.warnings,
            "full_generation_executed": (
                job.start == FULL_START and job.end_inclusive == FULL_END_INCLUSIVE
            ),
        }
        write_json_atomic(paths["validation"], report)
        report["files"]["validation"] = str(paths["validation"].relative_to(ROOT))
        report["files"]["validation_sha256"] = sha256_file(paths["validation"])
        report["files"]["validation_bytes"] = paths["validation"].stat().st_size
        write_json_atomic(paths["log"], report)

        completed = {
            **identity,
            "source_weather_sha256": raw_weather_hash,
            "status": "COMPLETE",
            "start_time_utc": started_at,
            "end_time_utc": utc_now(),
            "physics_rows": len(result.rows),
            "ml_rows": len(ml_rows),
            "physics_hash": physics_hash,
            "ml_hash": ml_hash,
            "runtime_seconds": elapsed,
            "validation_status": "PASS",
            "classification": report["classification"],
            "paths": {
                key: str(path.relative_to(output_root)) for key, path in paths.items()
            },
            "error": "",
        }
        update_state_entry(output_root, state, identifier, completed)
        return {"parameter_set_id": identifier, "action": "COMPLETED", **report}
    except KeyboardInterrupt:
        update_state_entry(
            output_root,
            state,
            identifier,
            {
                **identity,
                "status": "INTERRUPTED",
                "end_time_utc": utc_now(),
                "runtime_seconds": time.perf_counter() - wall_started,
                "validation_status": "INTERRUPTED",
                "error": f"Interrupted during {stage}.",
            },
        )
        raise
    except Exception as exc:
        failed_status = (
            "FAILED_VALIDATION"
            if isinstance(exc, PhysicsValidationFailure)
            else "FAILED"
        )
        failure = {
            **identity,
            "status": failed_status,
            "end_time_utc": utc_now(),
            "runtime_seconds": time.perf_counter() - wall_started,
            "validation_status": "FAIL",
            "error": str(exc),
            "failure_stage": stage,
            "traceback": traceback.format_exc(),
        }
        update_state_entry(output_root, state, identifier, failure)
        write_json_atomic(paths["log"], failure)
        raise


def mode_name(args: argparse.Namespace) -> str:
    if args.benchmark:
        return "benchmark"
    if args.full or (args.dry_run and not args.parameter_set):
        return "full"
    return "single"


def default_output_root(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return args.output_dir.resolve()
    return BENCHMARK_OUTPUT_ROOT if args.benchmark else FULL_OUTPUT_ROOT


def execute(args: argparse.Namespace) -> dict[str, Any]:
    manifest_audit = audit_final_manifest()
    all_weather, weather_audit = audit_weather_dataset()
    manifest_rows = load_manifest_rows()
    jobs = resolve_jobs(args, manifest_rows)
    output_root = default_output_root(args)
    plan = {
        "status": "PASS",
        "mode": mode_name(args),
        "dry_run": bool(args.dry_run),
        "jobs": len(jobs),
        "parameter_set_ids": [job.parameter_set_id for job in jobs],
        "window": [
            jobs[0].start.isoformat(timespec="minutes"),
            jobs[0].end_inclusive.isoformat(timespec="minutes"),
        ],
        "expected_rows_per_job": jobs[0].expected_rows,
        "expected_total_rows": sum(job.expected_rows for job in jobs),
        "output_root": str(output_root),
        "manifest_audit": manifest_audit,
        "weather_audit": weather_audit,
        "full_mode_executed": False,
    }
    if args.dry_run:
        return plan

    prepare_output_root(output_root)
    mode = mode_name(args)
    state = load_run_state(output_root, mode)
    state["manifest_sha256"] = manifest_audit["manifest_sha256"]
    state["source_weather_sha256"] = weather_audit["sha256"]
    state["full_mode_executed"] = mode == "full"
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with RunLock(output_root / "state" / "run.lock"):
        save_run_state(output_root, state)
        for job in jobs:
            try:
                results.append(
                    run_one_job(
                        job,
                        output_root,
                        state,
                        all_weather,
                        weather_audit["sha256"],
                        force=args.force,
                    )
                )
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                errors.append(
                    {"parameter_set_id": job.parameter_set_id, "error": str(exc)}
                )
                if not args.continue_on_error:
                    break
    return {
        **plan,
        "status": "PASS" if not errors else "FAIL",
        "dry_run": False,
        "results": results,
        "errors": errors,
        "completed": sum(item.get("action") == "COMPLETED" for item in results),
        "skipped": sum(item.get("action") == "SKIPPED" for item in results),
        "full_mode_executed": mode == "full",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run resumable SmartGarden physics and deployment-ML generation."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--benchmark",
        action="store_true",
        help="Run only pa1_full_000_baseline for calendar year 2024.",
    )
    mode.add_argument(
        "--full",
        action="store_true",
        help="Run all 24 approved sets continuously over 2018-2025.",
    )
    mode.add_argument("--parameter-set", help="Run one approved parameter set.")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not (args.benchmark or args.full or args.parameter_set or args.dry_run):
        parser.error("choose --benchmark, --full, --parameter-set, or --dry-run")
    try:
        report = execute(args)
    except KeyboardInterrupt:
        print("STATUS: INTERRUPTED")
        return 130
    except (FullGenerationError, WeatherDataError, OSError, ValueError) as exc:
        print("STATUS: FAILED")
        print(str(exc))
        return 1
    print(f"STATUS: {report['status']}")
    print(f"MODE: {report['mode']}")
    print(f"DRY_RUN: {'YES' if report['dry_run'] else 'NO'}")
    print(f"JOBS: {report['jobs']}")
    print(f"EXPECTED_ROWS_PER_JOB: {report['expected_rows_per_job']}")
    if not report["dry_run"]:
        print(f"COMPLETED: {report['completed']}")
        print(f"SKIPPED: {report['skipped']}")
    print(f"FULL_MODE_EXECUTED: {'YES' if report['full_mode_executed'] else 'NO'}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
