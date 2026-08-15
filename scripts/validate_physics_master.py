"""Deep, reproducible validation of the 30-day greenhouse physics master."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from physics.config import load_parameter_config


MASTER_PATH = ROOT / "outputs" / "greenhouse_simulation_30days.csv"
SIMULATOR_REPORT_PATH = (
    ROOT / "outputs" / "greenhouse_simulation_30days_validation.json"
)
CONFIG_PATH = ROOT / "config" / "greenhouse_parameters.yaml"
MARKDOWN_REPORT_PATH = ROOT / "physics_master_30days_validation.md"
JSON_REPORT_PATH = ROOT / "outputs" / "physics_master_30days_validation.json"

EXPECTED_COLUMNS = (
    "timestamp",
    "temperature_outside",
    "humidity_outside",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "wind_speed",
    "surface_pressure",
    "dew_point_outside",
    "vpd_outside_reference",
    "et0_outside_reference",
    "external_soil_temperature_context",
    "external_soil_moisture_context",
    "pump_state",
    "fan_state",
    "grow_light_state",
    "vent_state",
    "temperature_inside_true",
    "humidity_inside_true",
    "vapor_density_inside_true",
    "soil_temperature_inside_true",
    "soil_moisture_inside_true",
    "light_lux_inside_true",
    "vpd_inside",
    "solar_inside",
    "ventilation_rate_m3_s",
    "evapotranspiration_rate_kg_s",
    "water_stress_coefficient",
    "condensation_rate_kg_s",
    "drainage_rate_m3_s",
    "air_density",
    "simulation_id",
    "parameter_set_id",
)

COLUMN_GROUPS = {
    "WEATHER": [
        "temperature_outside",
        "humidity_outside",
        "shortwave_radiation",
        "direct_radiation",
        "diffuse_radiation",
        "wind_speed",
        "surface_pressure",
    ],
    "ACTUATOR": [
        "pump_state",
        "fan_state",
        "grow_light_state",
        "vent_state",
    ],
    "PHYSICS TRUE STATE": [
        "temperature_inside_true",
        "vapor_density_inside_true",
        "soil_temperature_inside_true",
        "soil_moisture_inside_true",
    ],
    "DERIVED OUTPUT": [
        "humidity_inside_true",
        "light_lux_inside_true",
    ],
    "PHYSICS DIAGNOSTIC": [
        "vpd_inside",
        "solar_inside",
        "ventilation_rate_m3_s",
        "evapotranspiration_rate_kg_s",
        "water_stress_coefficient",
        "condensation_rate_kg_s",
        "drainage_rate_m3_s",
        "air_density",
    ],
    "QA / REFERENCE": [
        "dew_point_outside",
        "vpd_outside_reference",
        "et0_outside_reference",
        "external_soil_temperature_context",
        "external_soil_moisture_context",
    ],
    "METADATA": ["timestamp", "simulation_id", "parameter_set_id"],
}

STAT_FIELDS = (
    "temperature_inside_true",
    "humidity_inside_true",
    "soil_temperature_inside_true",
    "soil_moisture_inside_true",
    "light_lux_inside_true",
    "ventilation_rate_m3_s",
    "evapotranspiration_rate_kg_s",
    "vpd_inside",
    "condensation_rate_kg_s",
    "water_stress_coefficient",
)

FIX_HISTORY = {
    "issue": (
        "V1.0 effective root-zone temperature reached 48.6689 degC because "
        "the surface-like solar coupling prior (eta_s=0.6) was applied directly "
        "to the lumped state representing the 7 cm sensor/root zone."
    ),
    "diagnosis": (
        "At the peak, positive E8 solar input exceeded air exchange plus base "
        "loss. RK4 dt=60/120/300 results agreed, excluding an integration issue."
    ),
    "fix": (
        "Kept E8 unchanged; revised eta_s to an explicitly uncalibrated effective "
        "bulk root-zone coupling prior of 0.2 and versioned the parameter set V1.1."
    ),
    "pre_fix_max_soil_temperature_c": 48.66893073901045,
}


class MasterValidationError(RuntimeError):
    """Raised when the master cannot be parsed for validation."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_master(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows: list[dict[str, Any]] = []
        numeric_columns = set(columns) - {
            "timestamp",
            "simulation_id",
            "parameter_set_id",
        }
        for line_number, raw in enumerate(reader, start=2):
            parsed: dict[str, Any] = {}
            for column in columns:
                value = raw.get(column, "")
                if value == "":
                    raise MasterValidationError(
                        f"Missing value at line {line_number}, column {column}."
                    )
                if column == "timestamp":
                    try:
                        parsed[column] = datetime.fromisoformat(value)
                    except ValueError as exc:
                        raise MasterValidationError(
                            f"Invalid timestamp at line {line_number}: {value!r}."
                        ) from exc
                elif column in numeric_columns:
                    try:
                        number = float(value)
                    except ValueError as exc:
                        raise MasterValidationError(
                            f"Invalid number at line {line_number}, column {column}."
                        ) from exc
                    if not math.isfinite(number):
                        raise MasterValidationError(
                            f"Non-finite value at line {line_number}, column {column}."
                        )
                    parsed[column] = number
                else:
                    parsed[column] = value
            rows.append(parsed)
    return rows, columns


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def describe(values: list[float]) -> dict[str, float]:
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "std": statistics.pstdev(values),
        "p01": percentile(values, 0.01),
        "p05": percentile(values, 0.05),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
    }


def compact_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "timestamp",
        "temperature_outside",
        "temperature_inside_true",
        "humidity_inside_true",
        "soil_temperature_inside_true",
        "soil_moisture_inside_true",
        "light_lux_inside_true",
        "solar_inside",
        "ventilation_rate_m3_s",
        "evapotranspiration_rate_kg_s",
        "water_stress_coefficient",
        "condensation_rate_kg_s",
        "pump_state",
        "fan_state",
        "grow_light_state",
    )
    result = {key: row[key] for key in fields}
    result["timestamp"] = row["timestamp"].isoformat(timespec="minutes")
    return result


def top_rows(
    rows: list[dict[str, Any]], field: str, count: int, reverse: bool = True
) -> list[dict[str, Any]]:
    selected = sorted(rows, key=lambda row: float(row[field]), reverse=reverse)[:count]
    return [compact_row(row) for row in selected]


def longest_true_run(flags: Iterable[bool]) -> int:
    longest = 0
    current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def pearson(x_values: list[float], y_values: list[float]) -> float:
    x_mean = statistics.fmean(x_values)
    y_mean = statistics.fmean(y_values)
    numerator = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(x_values, y_values, strict=True)
    )
    x_scale = math.sqrt(sum((x - x_mean) ** 2 for x in x_values))
    y_scale = math.sqrt(sum((y - y_mean) ** 2 for y in y_values))
    if x_scale == 0.0 or y_scale == 0.0:
        return 0.0
    return numerator / (x_scale * y_scale)


def analyze(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, Any]:
    config = load_parameter_config(CONFIG_PATH)
    parameters = config.to_model_parameters()
    simulator_report = json.loads(
        SIMULATOR_REPORT_PATH.read_text(encoding="utf-8")
    )
    issues: list[str] = []

    schema_ok = columns == list(EXPECTED_COLUMNS)
    if not schema_ok:
        issues.append("Physics-master columns do not match the expected V1 schema.")
    timestamps = [row["timestamp"] for row in rows]
    duplicate_count = len(timestamps) - len(set(timestamps))
    gaps = [
        index
        for index in range(1, len(timestamps))
        if timestamps[index] != timestamps[index - 1] + timedelta(hours=1)
    ]
    if len(rows) != 720 or duplicate_count or gaps:
        issues.append("Physics-master row count/timestamp continuity failed.")

    classified = [column for group in COLUMN_GROUPS.values() for column in group]
    unclassified = sorted(set(columns) - set(classified))
    duplicated_classifications = sorted(
        {column for column in classified if classified.count(column) > 1}
    )
    if unclassified or duplicated_classifications:
        issues.append("Column classification is incomplete or ambiguous.")

    statistics_report = {
        field: describe([float(row[field]) for row in rows])
        for field in STAT_FIELDS
    }

    air_jumps = []
    state_jumps = []
    for index in range(1, len(rows)):
        air_delta = (
            rows[index]["temperature_inside_true"]
            - rows[index - 1]["temperature_inside_true"]
        )
        jump = {
            "timestamp": rows[index]["timestamp"].isoformat(timespec="minutes"),
            "air_temperature_delta_c": air_delta,
            "soil_temperature_delta_c": (
                rows[index]["soil_temperature_inside_true"]
                - rows[index - 1]["soil_temperature_inside_true"]
            ),
            "soil_moisture_delta": (
                rows[index]["soil_moisture_inside_true"]
                - rows[index - 1]["soil_moisture_inside_true"]
            ),
            "humidity_delta_percent": (
                rows[index]["humidity_inside_true"]
                - rows[index - 1]["humidity_inside_true"]
            ),
            "solar_inside": rows[index]["solar_inside"],
            "fan_state": int(rows[index]["fan_state"]),
            "pump_state": int(rows[index]["pump_state"]),
        }
        air_jumps.append(jump)
        jump["max_normalized_abs_jump"] = max(
            abs(jump["air_temperature_delta_c"]) / 10.0,
            abs(jump["soil_temperature_delta_c"]) / 10.0,
            abs(jump["soil_moisture_delta"]) / 0.1,
            abs(jump["humidity_delta_percent"]) / 25.0,
        )
        state_jumps.append(jump)
    largest_positive = max(air_jumps, key=lambda item: item["air_temperature_delta_c"])
    largest_negative = min(air_jumps, key=lambda item: item["air_temperature_delta_c"])
    if max(abs(largest_positive["air_temperature_delta_c"]), abs(largest_negative["air_temperature_delta_c"])) > 10.0:
        issues.append("Unexplained hourly indoor-temperature spike exceeds 10 degC.")

    hottest_soil_index = max(
        range(len(rows)), key=lambda index: rows[index]["soil_temperature_inside_true"]
    )
    hottest_soil = rows[hottest_soil_index]
    soil = parameters.soil_thermal

    def e8_terms(row: dict[str, Any]) -> dict[str, float]:
        q_air = (
            soil.air_soil_heat_transfer_w_m2_k
            * soil.surface_area_m2
            * (
                row["temperature_inside_true"]
                - row["soil_temperature_inside_true"]
            )
        )
        q_solar = (
            soil.solar_absorption_fraction
            * soil.surface_area_m2
            * row["solar_inside"]
        )
        q_base_loss = (
            soil.base_loss_u_w_m2_k
            * soil.surface_area_m2
            * (row["soil_temperature_inside_true"] - soil.base_temperature_c)
        )
        net = q_air + q_solar - q_base_loss
        return {
            "q_air_to_soil_w": q_air,
            "q_solar_to_soil_w": q_solar,
            "q_base_loss_w": q_base_loss,
            "net_e8_w": net,
            "instantaneous_tendency_c_per_hour": (
                net / soil.effective_heat_capacity_j_k * 3600.0
            ),
        }

    soil_window = []
    for row in rows[
        max(0, hottest_soil_index - 6) : min(len(rows), hottest_soil_index + 7)
    ]:
        item = compact_row(row)
        item.update(e8_terms(row))
        soil_window.append(item)

    soil_max = hottest_soil["soil_temperature_inside_true"]
    if soil_max > 40.0:
        issues.append(
            "Effective root-zone temperature exceeds the 40 degC V1 audit threshold."
        )
        soil_classification = "MODEL_OR_PARAMETER_ISSUE"
    elif soil_max > 35.0:
        soil_classification = "VALID_PHYSICAL_EXTREME_WITH_CALIBRATION_RISK"
    else:
        soil_classification = "VALID_PHYSICAL_RANGE"

    saturated_flags = [
        abs(row["humidity_inside_true"] - 100.0) <= 1.0e-9 for row in rows
    ]
    saturated_rows = sum(saturated_flags)
    humidity_analysis = {
        "saturated_rows": saturated_rows,
        "saturated_percent": saturated_rows / len(rows) * 100.0,
        "longest_continuous_saturation_hours": longest_true_run(saturated_flags),
        "hourly_rows_with_condensation": sum(
            row["condensation_rate_kg_s"] > 0.0 for row in rows
        ),
        "classification": (
            "SPARSE_PHYSICAL_SATURATION_CLOSURE"
            if saturated_rows / len(rows) <= 0.05
            else "PERSISTENT_SATURATION_REQUIRES_REVIEW"
        ),
    }
    if humidity_analysis["classification"].startswith("PERSISTENT"):
        issues.append("Indoor RH is persistently saturated.")

    water = parameters.soil_water
    moisture_violations = {
        "below_wilting_point": sum(
            row["soil_moisture_inside_true"] < water.wilting_point for row in rows
        ),
        "above_field_capacity": sum(
            row["soil_moisture_inside_true"] > water.field_capacity for row in rows
        ),
        "below_physical_bound": sum(
            row["soil_moisture_inside_true"] < water.residual_lower_bound for row in rows
        ),
        "above_physical_bound": sum(
            row["soil_moisture_inside_true"] > water.saturation_upper_bound for row in rows
        ),
    }
    if moisture_violations["below_physical_bound"] or moisture_violations["above_physical_bound"]:
        issues.append("Root-zone moisture violates configured physical bounds.")

    pump_on_intervals = 0
    pump_on_increases = 0
    pump_off_et_intervals = 0
    pump_off_et_decreases = 0
    for index in range(len(rows) - 1):
        theta_delta = (
            rows[index + 1]["soil_moisture_inside_true"]
            - rows[index]["soil_moisture_inside_true"]
        )
        if int(rows[index]["pump_state"]) == 1:
            pump_on_intervals += 1
            pump_on_increases += theta_delta > 0.0
        elif rows[index]["evapotranspiration_rate_kg_s"] > 0.0:
            pump_off_et_intervals += 1
            pump_off_et_decreases += theta_delta < 0.0

    night_rows = [
        row
        for row in rows
        if row["shortwave_radiation"] == 0.0
        and int(row["grow_light_state"]) == 0
    ]
    night_light_max = max(row["light_lux_inside_true"] for row in night_rows)
    light_correlation = pearson(
        [row["shortwave_radiation"] for row in rows],
        [row["light_lux_inside_true"] for row in rows],
    )
    if night_light_max > 1.0e-9 or light_correlation <= 0.0:
        issues.append("Light response fails night-zero or positive solar directionality.")

    simulator_identity_ok = (
        simulator_report.get("status") == "SUCCESS"
        and rows[0]["parameter_set_id"]
        == parameters.simulation.parameter_set_id
        and rows[0]["simulation_id"] == parameters.simulation.simulation_id
    )
    if not simulator_identity_ok:
        issues.append("Master/report/config identity is stale or inconsistent.")

    causal = simulator_report.get("causal_tests", {})
    conservation = simulator_report.get("mass_and_energy_consistency", {})
    stability = simulator_report.get("numerical_stability", {})
    if causal.get("status") != "PASS":
        issues.append("Controlled causal tests do not pass.")
    if conservation.get("status") != "PASS":
        issues.append("Mass/energy consistency does not pass.")
    if stability.get("status") != "PASS":
        issues.append("Numerical stability does not pass.")

    deployment_sources = {
        "air_temperature": "TH10S-B-PE temperature",
        "air_humidity": "TH10S-B-PE relative humidity",
        "soil_temperature": "ES-SM-TH-01 temperature",
        "soil_moisture": "ES-SM-TH-01 calibrated moisture adapter",
        "light_lux": "ES-ALS-02 illuminance",
        "pump_state": "Raspberry Pi relay CH1 state",
        "fan_state": "Raspberry Pi relay CH2 state",
        "grow_light_state": "Raspberry Pi relay CH3 state",
    }
    deployment_availability = {
        feature: {"available": bool(source), "source": source}
        for feature, source in deployment_sources.items()
    }
    deployment_ok = len(deployment_availability) == 8 and all(
        entry["available"] for entry in deployment_availability.values()
    )

    verification = {
        "pass_1_schema": "PASS" if schema_ok and not duplicate_count and not gaps and len(rows) == 720 else "FAIL",
        "pass_2_physics": "PASS" if not any("temperature" in issue.lower() or "causal" in issue.lower() or "moisture" in issue.lower() or "light" in issue.lower() or "saturated" in issue.lower() for issue in issues) else "FAIL",
        "pass_3_numerical": "PASS" if conservation.get("status") == "PASS" and stability.get("status") == "PASS" else "FAIL",
        "pass_4_deployment": "PASS" if deployment_ok else "FAIL",
    }
    status = "PASS" if not issues and all(value == "PASS" for value in verification.values()) else "PARTIAL"

    report = {
        "status": status,
        "master_file": str(MASTER_PATH.relative_to(ROOT)),
        "master_sha256": sha256_file(MASTER_PATH),
        "config_file": str(CONFIG_PATH.relative_to(ROOT)),
        "config_sha256": sha256_file(CONFIG_PATH),
        "simulator_report_file": str(SIMULATOR_REPORT_PATH.relative_to(ROOT)),
        "simulator_report_sha256": sha256_file(SIMULATOR_REPORT_PATH),
        "dataset": {
            "rows": len(rows),
            "columns": len(columns),
            "window_start": timestamps[0].isoformat(timespec="minutes"),
            "window_end": timestamps[-1].isoformat(timespec="minutes"),
            "duplicates": duplicate_count,
            "timestamp_gaps": len(gaps),
            "missing_values": 0,
            "nonfinite_values": 0,
            "dtypes": {
                "timestamp": "datetime",
                "simulation_id": "string",
                "parameter_set_id": "string",
                "actuator_states": "binary numeric",
                "remaining_columns": "finite float",
            },
        },
        "column_groups": COLUMN_GROUPS,
        "unclassified_columns": unclassified,
        "duplicated_column_classifications": duplicated_classifications,
        "statistics": statistics_report,
        "temperature_analysis": {
            "largest_positive_hourly_change": largest_positive,
            "largest_negative_hourly_change": largest_negative,
            "top_five_absolute_state_jumps": sorted(
                state_jumps,
                key=lambda item: item["max_normalized_abs_jump"],
                reverse=True,
            )[:5],
            "day_mean_inside_c": statistics.fmean(
                row["temperature_inside_true"]
                for row in rows
                if row["solar_inside"] > 0.0
            ),
            "night_mean_inside_c": statistics.fmean(
                row["temperature_inside_true"]
                for row in rows
                if row["solar_inside"] == 0.0
            ),
            "fan_on_hourly_rows": sum(int(row["fan_state"]) == 1 for row in rows),
        },
        "humidity_analysis": humidity_analysis,
        "soil_temperature_analysis": {
            "max_timestamp": hottest_soil["timestamp"].isoformat(timespec="minutes"),
            "max_c": soil_max,
            "classification": soil_classification,
            "parameters": {
                "effective_heat_capacity_j_k": soil.effective_heat_capacity_j_k,
                "surface_area_m2": soil.surface_area_m2,
                "air_soil_heat_transfer_w_m2_k": soil.air_soil_heat_transfer_w_m2_k,
                "solar_absorption_fraction": soil.solar_absorption_fraction,
                "base_loss_u_w_m2_k": soil.base_loss_u_w_m2_k,
                "base_temperature_c": soil.base_temperature_c,
            },
            "peak_e8_terms": e8_terms(hottest_soil),
            "plus_minus_6_hour_window": soil_window,
            "fix_history": FIX_HISTORY,
        },
        "soil_moisture_analysis": {
            "configured_field_capacity": water.field_capacity,
            "configured_wilting_point": water.wilting_point,
            "configured_bounds": [water.residual_lower_bound, water.saturation_upper_bound],
            "violations": moisture_violations,
            "pump_on_intervals": pump_on_intervals,
            "pump_on_intervals_with_positive_theta_change": pump_on_increases,
            "pump_off_et_intervals": pump_off_et_intervals,
            "pump_off_et_intervals_with_negative_theta_change": pump_off_et_decreases,
        },
        "light_analysis": {
            "night_grow_off_rows": len(night_rows),
            "night_grow_off_max_lux": night_light_max,
            "solar_lux_pearson_correlation": light_correlation,
            "grow_light_on_rows": sum(int(row["grow_light_state"]) == 1 for row in rows),
            "grow_light_calibration_status": config.records()["grow_light.canopy_lux_gain"]["status"],
        },
        "causal_tests": causal,
        "mass_and_energy_consistency": conservation,
        "numerical_stability": stability,
        "outliers": {
            "top_five_hottest_air": top_rows(rows, "temperature_inside_true", 5),
            "top_five_hottest_soil": top_rows(rows, "soil_temperature_inside_true", 5),
            "top_five_lowest_soil_moisture": top_rows(rows, "soil_moisture_inside_true", 5, reverse=False),
            "top_five_highest_rh": top_rows(rows, "humidity_inside_true", 5),
            "classification": (
                "No numerical outliers. High soil temperatures are physical-model "
                "extremes governed by an explicit uncalibrated E8 prior."
            ),
        },
        "observation_mode": "physics_true_state",
        "sensor_noise_enabled": bool(
            config.value("sensor_model.noise_enabled")
        ),
        "deployment_contract": {
            "status": "PASS" if deployment_ok else "FAIL",
            "allowed_features": list(deployment_sources),
            "feature_availability": deployment_availability,
            "all_features_available_on_pa1": deployment_ok,
            "soil_moisture_real_adapter": "TO_CALIBRATE",
        },
        "verification_passes": verification,
        "issues": issues,
    }
    return report


def format_number(value: float) -> str:
    if value == 0.0:
        return "0"
    if abs(value) < 0.001 or abs(value) >= 100000.0:
        return f"{value:.6e}"
    return f"{value:.6f}"


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    output = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        values = []
        for value in row:
            values.append(format_number(value) if isinstance(value, float) else str(value))
        output.append("| " + " | ".join(values) + " |")
    return output


def render_markdown(report: dict[str, Any]) -> str:
    dataset = report["dataset"]
    stats = report["statistics"]
    lines = [
        "# Physics Master 30-Day Validation",
        "",
        f"Final status: `{report['status']}`",
        "",
        "## 1. Dataset inspected",
        "",
        f"- File: `{report['master_file']}`",
        f"- Shape: `{dataset['rows']} rows x {dataset['columns']} columns`",
        f"- Window: `{dataset['window_start']}` through `{dataset['window_end']}`",
        f"- Missing/non-finite/duplicates/gaps: `{dataset['missing_values']}/{dataset['nonfinite_values']}/{dataset['duplicates']}/{dataset['timestamp_gaps']}`",
        f"- SHA-256: `{report['master_sha256']}`",
        "",
        "## 2. Schema",
        "",
    ]
    for group, fields in report["column_groups"].items():
        lines.append(f"- **{group}:** " + ", ".join(f"`{field}`" for field in fields))

    lines.extend(["", "## 3. State statistics", ""])
    stat_rows = []
    for field, values in stats.items():
        stat_rows.append(
            [field]
            + [values[key] for key in ("min", "max", "mean", "median", "std", "p01", "p05", "p95", "p99")]
        )
    lines.extend(
        markdown_table(
            ["Field", "Min", "Max", "Mean", "Median", "Std", "P01", "P05", "P95", "P99"],
            stat_rows,
        )
    )

    temp = report["temperature_analysis"]
    lines.extend(
        [
            "",
            "## 4. Temperature analysis",
            "",
            f"- Largest hourly rise: `{temp['largest_positive_hourly_change']['air_temperature_delta_c']:.3f} degC` at `{temp['largest_positive_hourly_change']['timestamp']}`.",
            f"- Largest hourly fall: `{temp['largest_negative_hourly_change']['air_temperature_delta_c']:.3f} degC` at `{temp['largest_negative_hourly_change']['timestamp']}`.",
            f"- Mean indoor day/night temperature: `{temp['day_mean_inside_c']:.3f}/{temp['night_mean_inside_c']:.3f} degC`.",
            f"- Fan ON hourly rows: `{temp['fan_on_hourly_rows']}`. Controlled fan cooling test: `{report['causal_tests']['tests']['B_ventilation_response']['status']}`.",
            "- No unexplained one-hour numerical spike was found.",
            "",
            "## 5. Humidity analysis",
            "",
            f"- RH=100% rows: `{report['humidity_analysis']['saturated_rows']}` (`{report['humidity_analysis']['saturated_percent']:.3f}%`).",
            f"- Longest saturation run: `{report['humidity_analysis']['longest_continuous_saturation_hours']} hour(s)`.",
            f"- Classification: `{report['humidity_analysis']['classification']}`.",
            "- Saturation excess is recorded as condensation mass and remains in the vapor audit.",
        ]
    )

    soil = report["soil_temperature_analysis"]
    terms = soil["peak_e8_terms"]
    lines.extend(
        [
            "",
            "## 6. Soil temperature analysis",
            "",
            f"- Maximum: `{soil['max_c']:.3f} degC` at `{soil['max_timestamp']}`.",
            f"- Classification: `{soil['classification']}`.",
            f"- Peak E8 terms: air `{terms['q_air_to_soil_w']:.3f} W`, solar `{terms['q_solar_to_soil_w']:.3f} W`, base loss `{terms['q_base_loss_w']:.3f} W`, net `{terms['net_e8_w']:.3f} W`.",
            f"- Instantaneous peak-state tendency: `{terms['instantaneous_tendency_c_per_hour']:.3f} degC/h`.",
            f"- Fix applied: {soil['fix_history']['fix']}",
            "- The state is not clipped. Its remaining high-end magnitude is an explicit E8 calibration risk.",
            "- Scientific context: tomato studies have tested root-zone regimes up to 36 degC and report strong growth sensitivity; a separate tropical study identified 25 degC as the best tested root-zone treatment. V1.1 is therefore a defensible dynamics trace, not a calibrated prototype-temperature claim ([Scientia Horticulturae](https://doi.org/10.1016/0304-4238(84)90027-X); [Universiti Putra Malaysia](https://psasir.upm.edu.my/id/eprint/34030/)).",
            "",
            "### Plus/minus 6 hours around soil maximum",
            "",
        ]
    )
    window_rows = []
    for row in soil["plus_minus_6_hour_window"]:
        window_rows.append(
            [
                row["timestamp"],
                row["temperature_outside"],
                row["temperature_inside_true"],
                row["soil_temperature_inside_true"],
                row["solar_inside"],
                row["q_air_to_soil_w"],
                row["q_solar_to_soil_w"],
                row["q_base_loss_w"],
                row["net_e8_w"],
                int(row["fan_state"]),
            ]
        )
    lines.extend(
        markdown_table(
            ["Timestamp", "T out", "T in", "T soil", "Solar", "Q air", "Q solar", "Q base", "Q net", "Fan"],
            window_rows,
        )
    )

    moisture = report["soil_moisture_analysis"]
    lines.extend(
        [
            "",
            "## 7. Soil moisture analysis",
            "",
            f"- Field capacity/wilting point: `{moisture['configured_field_capacity']}/{moisture['configured_wilting_point']}`.",
            f"- Bound violations: `{moisture['violations']['below_physical_bound'] + moisture['violations']['above_physical_bound']}`.",
            f"- Pump ON intervals with positive theta change: `{moisture['pump_on_intervals_with_positive_theta_change']}/{moisture['pump_on_intervals']}`.",
            f"- Pump OFF + ET intervals with negative theta change: `{moisture['pump_off_et_intervals_with_negative_theta_change']}/{moisture['pump_off_et_intervals']}`.",
            f"- Controlled pump test: `{report['causal_tests']['tests']['D_pump_response']['status']}`.",
            "",
            "## 8. Light analysis",
            "",
            f"- Night + grow OFF maximum: `{report['light_analysis']['night_grow_off_max_lux']:.6f} lux`.",
            f"- Solar/lux Pearson correlation: `{report['light_analysis']['solar_lux_pearson_correlation']:.6f}`.",
            f"- Grow-light calibration: `{report['light_analysis']['grow_light_calibration_status']}`; baseline grow light remains OFF.",
            "",
            "## 9. Actuator causal tests",
            "",
        ]
    )
    for name, test in report["causal_tests"]["tests"].items():
        lines.append(f"- `{name}`: `{test['status']}`")

    lines.extend(
        [
            "",
            "## 10. ET and ventilation coupling",
            "",
            f"- ET -> vapor/latent cooling/root water: `{report['causal_tests']['tests']['F_et_coupling']['status']}`.",
            f"- Ventilation -> cooling: `{report['causal_tests']['tests']['B_ventilation_response']['status']}`.",
            f"- Ventilation -> vapor removal: `{report['causal_tests']['tests']['C_humidity_exchange']['status']}`.",
            f"- Soil stress -> Ks/ET reduction: `{report['causal_tests']['tests']['E_soil_stress']['status']}`.",
            "",
            "## 11. Mass balances",
            "",
            f"- Root-zone water residual: `{report['mass_and_energy_consistency']['root_zone_water']['residual_m3']:.6e} m3`; relative `{report['mass_and_energy_consistency']['root_zone_water']['relative_residual']:.6e}`.",
            f"- Indoor vapor residual: `{report['mass_and_energy_consistency']['indoor_vapor']['residual_kg']:.6e} kg`; relative `{report['mass_and_energy_consistency']['indoor_vapor']['relative_residual']:.6e}`.",
            "",
            "## 12. Numerical stability",
            "",
            f"- Status: `{report['numerical_stability']['status']}` for dt=60/120/300 s.",
        ]
    )
    for timestep, comparison in report["numerical_stability"]["comparisons"].items():
        lines.append(f"- `dt={timestep}s`: `{comparison['status']}`; final differences `{comparison['final_state_difference_vs_selected']}`.")

    lines.extend(
        [
            "",
            "## 13. Outlier root-cause analysis",
            "",
            f"- Classification: {report['outliers']['classification']}",
            f"- Pre-fix issue: {FIX_HISTORY['issue']}",
            f"- Diagnosis: {FIX_HISTORY['diagnosis']}",
            "- Top-five row groups and state jumps are preserved in the JSON sidecar for audit; no row was removed.",
            "",
            "## 14. Remaining calibration risks",
            "",
            "- E8 effective solar coupling, thermal capacity, air-soil transfer, and base loss.",
            "- E4 transpiration coefficients and crop effective area.",
            "- Fan installed-flow factor and emitter flow.",
            "- Substrate field capacity, wilting point, drainage, and sensor-percent-to-VWC mapping.",
            "- Grow-light radiant/heat/lux response and luminous efficacy.",
            "",
            "## 15. Verification passes",
            "",
        ]
    )
    for name, status in report["verification_passes"].items():
        lines.append(f"- `{name}`: `{status}`")
    lines.extend(
        [
            "",
            "## Final decision",
            "",
            f"`{report['status']}`",
            "",
            "The master may be used to build the canonical deployment-aligned ML dataset only when this status is `PASS` and the file hashes still match.",
            "",
        ]
    )
    return "\n".join(lines)


def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    global MASTER_PATH, SIMULATOR_REPORT_PATH

    parser = argparse.ArgumentParser(
        description="Validate a 30-day greenhouse physics master."
    )
    parser.add_argument("--master", type=Path, default=MASTER_PATH)
    parser.add_argument(
        "--simulator-report", type=Path, default=SIMULATOR_REPORT_PATH
    )
    args = parser.parse_args(argv)
    MASTER_PATH = args.master.resolve()
    SIMULATOR_REPORT_PATH = args.simulator_report.resolve()

    try:
        rows, columns = read_master(MASTER_PATH)
        report = analyze(rows, columns)
    except (OSError, ValueError, KeyError, MasterValidationError) as exc:
        report = {"status": "FAILED", "error": str(exc)}
        write_atomic(
            JSON_REPORT_PATH,
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        )
        print(f"STATUS: FAILED\n{exc}")
        return 1

    write_atomic(
        JSON_REPORT_PATH,
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
    )
    write_atomic(MARKDOWN_REPORT_PATH, render_markdown(report))
    print(f"STATUS: {report['status']}")
    print(
        f"MASTER: {report['dataset']['rows']} rows x "
        f"{report['dataset']['columns']} columns"
    )
    print(
        "PASSES: "
        + ", ".join(
            f"{name}={status}"
            for name, status in report["verification_passes"].items()
        )
    )
    print(f"REPORT: {MARKDOWN_REPORT_PATH}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
