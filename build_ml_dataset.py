"""Build the deployment-aligned 30-day SmartGarden ML dataset.

The builder is deliberately gated by the deep physics validation report. It
never copies weather forcing or internal physics diagnostics into model data.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_VALIDATION_REPORT = (
    ROOT / "outputs" / "physics_master_30days_validation.json"
)
DEFAULT_OUTPUT = ROOT / "outputs" / "greenhouse_ml_dataset_30days.csv"

CANONICAL_COLUMNS = (
    "timestamp",
    "air_temperature",
    "air_humidity",
    "soil_temperature",
    "soil_moisture",
    "light_lux",
    "pump_state",
    "fan_state",
    "grow_light_state",
)
BASELINE_FEATURES = CANONICAL_COLUMNS[1:]
FUTURE_TARGETS = (
    "air_temperature",
    "air_humidity",
    "soil_temperature",
    "soil_moisture",
    "light_lux",
)
SOURCE_CANDIDATES = {
    "air_temperature": (
        "temperature_inside_sensor",
        "temperature_inside_true",
    ),
    "air_humidity": ("humidity_inside_sensor", "humidity_inside_true"),
    "soil_temperature": (
        "soil_temperature_inside_sensor",
        "soil_temperature_inside_true",
    ),
    "soil_moisture": (
        "soil_moisture_inside_sensor",
        "soil_moisture_inside_true",
    ),
    "light_lux": ("light_lux_inside_sensor", "light_lux_inside_true"),
}
FORBIDDEN_NAME_FRAGMENTS = (
    "vpd",
    "vapor_density",
    "evapotranspiration",
    "ventilation_rate",
    "water_stress",
    "condensation",
    "drainage",
    "air_density",
    "solar_inside",
    "surface_pressure",
    "wind_speed",
    "temperature_outside",
    "humidity_outside",
    "radiation",
    "dew_point",
    "et0",
    "external_soil",
)


class DatasetBuildError(RuntimeError):
    """Raised when an input or deployment-contract gate fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_from_root(value: str | Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DatasetBuildError(f"Expected a JSON object: {path}")
    return payload


def verify_hash(path: Path, expected: Any, label: str) -> str:
    if not path.is_file():
        raise DatasetBuildError(f"Missing {label}: {path}")
    actual = sha256_file(path)
    if not isinstance(expected, str) or actual != expected:
        raise DatasetBuildError(
            f"{label} hash no longer matches the PASS validation report."
        )
    return actual


def validate_physics_gate(
    validation_path: Path, master_override: Path | None
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    validation = load_json(validation_path)
    if validation.get("status") != "PASS":
        raise DatasetBuildError("Physics master validation status is not PASS.")

    passes = validation.get("verification_passes")
    if not isinstance(passes, dict) or not passes or any(
        value != "PASS" for value in passes.values()
    ):
        raise DatasetBuildError("One or more required verification passes failed.")

    master_path = master_override or resolve_from_root(
        str(validation.get("master_file", ""))
    )
    verify_hash(master_path, validation.get("master_sha256"), "physics master")

    config_path = resolve_from_root(str(validation.get("config_file", "")))
    verify_hash(config_path, validation.get("config_sha256"), "parameter config")

    simulator_report_path = resolve_from_root(
        str(validation.get("simulator_report_file", ""))
    )
    verify_hash(
        simulator_report_path,
        validation.get("simulator_report_sha256"),
        "simulator validation report",
    )
    simulator_report = load_json(simulator_report_path)
    if simulator_report.get("status") != "SUCCESS":
        raise DatasetBuildError("Simulator validation report is not SUCCESS.")

    return validation, simulator_report, master_path


def resolve_observation_mapping(
    columns: set[str], simulator_report: dict[str, Any]
) -> tuple[str, bool, dict[str, str]]:
    sensor_columns = {
        canonical: candidates[0]
        for canonical, candidates in SOURCE_CANDIDATES.items()
    }
    true_columns = {
        canonical: candidates[1]
        for canonical, candidates in SOURCE_CANDIDATES.items()
    }
    all_sensor_columns_exist = all(
        source in columns for source in sensor_columns.values()
    )
    all_true_columns_exist = all(
        source in columns for source in true_columns.values()
    )
    sensor_model = simulator_report.get("sensor_model", {})
    sensor_model_valid = isinstance(sensor_model, dict) and (
        sensor_model.get("validation_status") == "PASS"
        or sensor_model.get("status") == "PASS"
    )

    if all_sensor_columns_exist and sensor_model_valid:
        return (
            "validated_sensor_observation",
            bool(sensor_model.get("noise_enabled", False)),
            sensor_columns,
        )
    if not all_true_columns_exist:
        missing = sorted(
            source for source in true_columns.values() if source not in columns
        )
        raise DatasetBuildError(
            "No complete validated sensor set and true-state fallback is "
            f"incomplete: {missing}"
        )
    if bool(sensor_model.get("noise_enabled", False)):
        raise DatasetBuildError(
            "True-state fallback cannot claim sensor noise is enabled."
        )
    return "physics_true_state", False, true_columns


def parse_finite(value: str, field: str, row_number: int) -> float:
    if value is None or value.strip() == "":
        raise DatasetBuildError(
            f"Missing {field} at source row {row_number}."
        )
    try:
        number = float(value)
    except ValueError as exc:
        raise DatasetBuildError(
            f"Non-numeric {field} at source row {row_number}: {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise DatasetBuildError(
            f"Non-finite {field} at source row {row_number}."
        )
    return number


def build_rows(
    master_path: Path, simulator_report: dict[str, Any]
) -> tuple[list[dict[str, str]], str, bool, dict[str, str], dict[str, str]]:
    with master_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise DatasetBuildError("Physics master has no CSV header.")
        columns = set(reader.fieldnames)
        for actuator in ("pump_state", "fan_state", "grow_light_state"):
            if actuator not in columns:
                raise DatasetBuildError(f"Missing actuator source: {actuator}")
        mode, sensor_noise, mapping = resolve_observation_mapping(
            columns, simulator_report
        )

        output_rows: list[dict[str, str]] = []
        timestamps: list[datetime] = []
        simulation_ids: set[str] = set()
        parameter_set_ids: set[str] = set()
        for row_number, source in enumerate(reader, start=2):
            timestamp_text = (source.get("timestamp") or "").strip()
            try:
                timestamp = datetime.fromisoformat(timestamp_text)
            except ValueError as exc:
                raise DatasetBuildError(
                    f"Invalid timestamp at source row {row_number}: "
                    f"{timestamp_text!r}"
                ) from exc
            timestamps.append(timestamp)

            output: dict[str, str] = {"timestamp": timestamp_text}
            for canonical, source_name in mapping.items():
                value = parse_finite(
                    source.get(source_name, ""), source_name, row_number
                )
                output[canonical] = format(value, ".15g")
            for actuator in ("pump_state", "fan_state", "grow_light_state"):
                value = parse_finite(
                    source.get(actuator, ""), actuator, row_number
                )
                if value not in (0.0, 1.0):
                    raise DatasetBuildError(
                        f"{actuator} is not binary at source row {row_number}."
                    )
                output[actuator] = str(int(value))
            output_rows.append(output)
            simulation_ids.add((source.get("simulation_id") or "").strip())
            parameter_set_ids.add(
                (source.get("parameter_set_id") or "").strip()
            )

    if len(output_rows) != 720:
        raise DatasetBuildError(
            f"Expected 720 hourly rows, found {len(output_rows)}."
        )
    if len(set(timestamps)) != len(timestamps):
        raise DatasetBuildError("Duplicate timestamps found in physics master.")
    expected_step = timedelta(hours=1)
    for previous, current in zip(timestamps, timestamps[1:]):
        if current - previous != expected_step:
            raise DatasetBuildError(
                f"Timestamp discontinuity: {previous.isoformat()} -> "
                f"{current.isoformat()}"
            )
    if len(simulation_ids) != 1 or "" in simulation_ids:
        raise DatasetBuildError("simulation_id is missing or not constant.")
    if len(parameter_set_ids) != 1 or "" in parameter_set_ids:
        raise DatasetBuildError("parameter_set_id is missing or not constant.")

    identities = {
        "simulation_id": next(iter(simulation_ids)),
        "parameter_set_id": next(iter(parameter_set_ids)),
    }
    return output_rows, mode, sensor_noise, mapping, identities


def validate_canonical_file(path: Path) -> None:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CANONICAL_COLUMNS:
            raise DatasetBuildError("Canonical output columns or order changed.")
        rows = list(reader)
    if len(rows) != 720:
        raise DatasetBuildError("Canonical output row count changed during write.")
    forbidden = [
        column
        for column in (reader.fieldnames or [])
        if any(fragment in column.lower() for fragment in FORBIDDEN_NAME_FRAGMENTS)
    ]
    if forbidden:
        raise DatasetBuildError(
            f"Physics/weather-only fields leaked into canonical output: {forbidden}"
        )
    for row_number, row in enumerate(rows, start=2):
        for field in BASELINE_FEATURES:
            parse_finite(row.get(field, ""), field, row_number)
        for actuator in ("pump_state", "fan_state", "grow_light_state"):
            if row[actuator] not in {"0", "1"}:
                raise DatasetBuildError(
                    f"Invalid canonical actuator at row {row_number}."
                )


def write_csv_atomic(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANONICAL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        validate_canonical_file(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the deployment-aligned 30-day ML dataset."
    )
    parser.add_argument(
        "--validation-report", type=Path, default=DEFAULT_VALIDATION_REPORT
    )
    parser.add_argument(
        "--master",
        type=Path,
        help="Optional master override; its hash must still match the report.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata", type=Path)
    args = parser.parse_args(argv)

    validation_path = args.validation_report.resolve()
    master_override = args.master.resolve() if args.master else None
    output_path = args.output.resolve()
    metadata_path = (
        args.metadata.resolve()
        if args.metadata
        else output_path.with_name(output_path.stem + "_metadata.json")
    )

    try:
        validation, simulator_report, master_path = validate_physics_gate(
            validation_path, master_override
        )
        rows, mode, sensor_noise, mapping, identities = build_rows(
            master_path, simulator_report
        )
        write_csv_atomic(output_path, rows)
        validate_canonical_file(output_path)
        metadata = {
            "status": "PASS",
            "contract": "ML_DATA_CONTRACT.md",
            "contract_version": "1.0",
            "source_type": "synthetic",
            "source_master_file": str(master_path.relative_to(ROOT)),
            "source_master_sha256": sha256_file(master_path),
            "physics_validation_report": str(validation_path.relative_to(ROOT)),
            "physics_validation_report_sha256": sha256_file(validation_path),
            "physics_validation_status": validation["status"],
            "simulation_id": identities["simulation_id"],
            "parameter_set_id": identities["parameter_set_id"],
            "rows": len(rows),
            "columns": len(CANONICAL_COLUMNS),
            "canonical_columns": list(CANONICAL_COLUMNS),
            "baseline_model_features": list(BASELINE_FEATURES),
            "future_target_variables": list(FUTURE_TARGETS),
            "target_columns_materialized": False,
            "observation_mode": mode,
            "sensor_noise_enabled": sensor_noise,
            "source_column_mapping": mapping,
            "metadata_not_model_features": [
                "timestamp",
                "simulation_id",
                "parameter_set_id",
                "source_type",
            ],
            "forbidden_physics_or_weather_columns_present": [],
            "deployment_schema_compatible": True,
            "soil_moisture_real_adapter_status": "TO_CALIBRATE",
            "validation": {
                "expected_rows": 720,
                "timestamp_continuous": True,
                "timestamp_duplicates": 0,
                "missing_or_nonfinite_values": 0,
                "actuator_states_binary": True,
                "exact_column_order": True,
                "physics_only_feature_count": 0,
                "external_weather_feature_count": 0,
            },
        }
        write_json_atomic(metadata_path, metadata)
    except (DatasetBuildError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1

    print("STATUS: SUCCESS")
    print(f"SOURCE: {master_path}")
    print(f"OUTPUT: {output_path}")
    print(f"SHAPE: {len(rows)} rows x {len(CANONICAL_COLUMNS)} columns")
    print(f"OBSERVATION_MODE: {mode}")
    print("DEPLOYMENT_SCHEMA_COMPATIBLE: YES")
    print(f"METADATA: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
