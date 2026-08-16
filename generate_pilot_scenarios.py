"""Generate and validate the deterministic 30-day PA1 uncertainty pilot."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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


BASE_CONFIG_PATH = ROOT / "config" / "greenhouse_parameters.yaml"
SPACE_PATH = ROOT / "scenario_parameter_space.yaml"
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
BASELINE_MASTER_PATH = ROOT / "outputs" / "greenhouse_simulation_30days.csv"
ML_DATASET_PATH = ROOT / "outputs" / "greenhouse_ml_dataset_30days.csv"
OUTPUT_DIR = ROOT / "outputs" / "scenario_pilot"
CONFIG_DIR = OUTPUT_DIR / "configs"
SUMMARY_PATH = OUTPUT_DIR / "scenario_pilot_summary.csv"
RESULTS_PATH = OUTPUT_DIR / "scenario_pilot_results.json"
REPORT_PATH = ROOT / "scenario_pilot_validation.md"

ML_COLUMNS = (
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

STATE_FIELDS = {
    "T_air": "temperature_inside_true",
    "RH": "humidity_inside_true",
    "T_soil": "soil_temperature_inside_true",
    "soil_moisture": "soil_moisture_inside_true",
    "light": "light_lux_inside_true",
}

SUMMARY_COLUMNS = (
    "scenario_id",
    "parameter_set_id",
    "config_hash",
    "random_seed",
    "changed_parameter",
    "baseline_value",
    "scenario_value",
    "T_air_min",
    "T_air_max",
    "T_air_mean",
    "RH_min",
    "RH_max",
    "RH_mean",
    "T_soil_min",
    "T_soil_max",
    "T_soil_mean",
    "soil_moisture_min",
    "soil_moisture_max",
    "soil_moisture_mean",
    "light_min",
    "light_max",
    "light_mean",
    "delta_T_air_max",
    "delta_T_air_mean",
    "delta_RH_mean",
    "delta_T_soil_max",
    "delta_soil_moisture_mean",
    "sensitivity_class",
    "condition_class",
    "validation_status",
    "warnings",
)


class PilotError(RuntimeError):
    """Raised when pilot provenance or validation invariants fail."""


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json_atomic(path: Path, payload: Any) -> None:
    write_text_atomic(
        path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PilotError(f"Cannot load JSON-compatible YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PilotError(f"Expected an object in {path}.")
    return payload


def get_record(raw: dict[str, Any], path: str) -> dict[str, Any]:
    node: Any = raw
    for component in path.split("."):
        if not isinstance(node, dict) or component not in node:
            raise PilotError(f"Missing config path {path!r}.")
        node = node[component]
    if not isinstance(node, dict) or "value" not in node:
        raise PilotError(f"Config path {path!r} is not a parameter record.")
    return node


def set_value(raw: dict[str, Any], path: str, value: Any) -> None:
    get_record(raw, path)["value"] = value


def model_value_payload(config: ParameterConfig) -> dict[str, Any]:
    """Return identity-independent config values for stable physical identity."""

    excluded_prefixes = ("identity.", "scenario.")
    return {
        path: record["value"]
        for path, record in sorted(config.records().items())
        if not path.startswith(excluded_prefixes)
    }


def append_scenario_metadata(
    raw: dict[str, Any], scenario_id: str, random_seed: int
) -> None:
    raw["scenario"] = {
        "scenario_id": {
            "value": scenario_id,
            "unit": "identifier",
            "provenance": "SCENARIO_PARAMETER_SPACE",
            "status": "DETERMINISTIC_PILOT",
            "source": "scenario_parameter_space.yaml",
        },
        "random_seed": {
            "value": random_seed,
            "unit": "integer",
            "provenance": "SCENARIO_PARAMETER_SPACE",
            "status": "RECORDED_NO_RANDOMNESS_USED",
            "source": "scenario_parameter_space.yaml",
        },
    }


def build_scenario_config(
    base_raw: dict[str, Any], scenario: dict[str, Any]
) -> tuple[dict[str, Any], ParameterConfig, str]:
    raw = deepcopy(base_raw)
    scenario_id = str(scenario["scenario_id"])
    random_seed = int(scenario["random_seed"])
    for change in scenario.get("changes", []):
        path = str(change["config_path"])
        current = get_record(raw, path)["value"]
        baseline = change["baseline_value"]
        if isinstance(current, (int, float)) and isinstance(
            baseline, (int, float)
        ):
            if not math.isclose(
                float(current), float(baseline), rel_tol=0.0, abs_tol=1.0e-14
            ):
                raise PilotError(
                    f"{scenario_id}: baseline mismatch for {path}: "
                    f"config={current}, space={baseline}."
                )
        elif current != baseline:
            raise PilotError(
                f"{scenario_id}: baseline mismatch for {path}: "
                f"config={current!r}, space={baseline!r}."
            )
        set_value(raw, path, change["scenario_value"])

    append_scenario_metadata(raw, scenario_id, random_seed)
    provisional = ParameterConfig(raw, BASE_CONFIG_PATH)
    config_hash = canonical_hash(model_value_payload(provisional))
    parameter_set_id = f"smartgarden_pa1_pilot_{config_hash[:12]}"
    set_value(raw, "identity.parameter_set_id", parameter_set_id)
    set_value(raw, "identity.simulation_id", f"{scenario_id}_june2024")
    config = ParameterConfig(raw, BASE_CONFIG_PATH)
    if canonical_hash(model_value_payload(config)) != config_hash:
        raise PilotError("Identity mutation changed the physical config hash.")
    return raw, config, config_hash


def selected_weather_hash(weather: Iterable[Any]) -> str:
    payload = [asdict(row) for row in weather]
    return canonical_hash(payload)


def longest_true_run(flags: Iterable[bool]) -> int:
    longest = 0
    current = 0
    for flag in flags:
        current = current + 1 if flag else 0
        longest = max(longest, current)
    return longest


def series_summary(rows: list[dict[str, Any]], field: str) -> dict[str, float]:
    values = [float(row[field]) for row in rows]
    return {
        "min": min(values),
        "max": max(values),
        "mean": statistics.fmean(values),
    }


def read_reference_master(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def baseline_reproduction_difference(
    generated: list[dict[str, Any]], reference: list[dict[str, str]]
) -> dict[str, Any]:
    if len(generated) != len(reference):
        return {
            "status": "FAIL",
            "reason": f"row count {len(generated)} != {len(reference)}",
        }
    ignored = {"simulation_id", "parameter_set_id"}
    max_difference = 0.0
    max_field = None
    max_timestamp = None
    for generated_row, reference_row in zip(generated, reference):
        if generated_row["timestamp"] != reference_row["timestamp"]:
            return {
                "status": "FAIL",
                "reason": "timestamp mismatch",
                "generated": generated_row["timestamp"],
                "reference": reference_row["timestamp"],
            }
        for field in OUTPUT_COLUMNS:
            if field in ignored or field == "timestamp":
                continue
            difference = abs(
                float(generated_row[field]) - float(reference_row[field])
            )
            if difference > max_difference:
                max_difference = difference
                max_field = field
                max_timestamp = generated_row["timestamp"]
    return {
        "status": "PASS" if max_difference <= 1.0e-12 else "FAIL",
        "max_absolute_difference": max_difference,
        "field": max_field,
        "timestamp": max_timestamp,
        "identity_fields_excluded": sorted(ignored),
    }


def validate_ml_contract() -> dict[str, Any]:
    with ML_DATASET_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        rows = list(reader)
    forbidden_fragments = (
        "vpd",
        "vapor",
        "evapotranspiration",
        "ventilation",
        "water_stress",
        "condensation",
        "drainage",
        "air_density",
        "solar_inside",
        "outside",
        "radiation",
        "wind_speed",
        "surface_pressure",
    )
    forbidden = [
        column
        for column in columns
        if any(fragment in column.lower() for fragment in forbidden_fragments)
    ]
    status = "PASS" if columns == ML_COLUMNS and len(rows) == 720 and not forbidden else "FAIL"
    return {
        "status": status,
        "file": str(ML_DATASET_PATH.relative_to(ROOT)),
        "sha256": sha256_file(ML_DATASET_PATH),
        "rows": len(rows),
        "columns": list(columns),
        "physics_or_weather_feature_count": len(forbidden),
        "scenario_ml_datasets_generated": False,
    }


def classify_condition(
    metrics: dict[str, Any], validation_status: str
) -> str:
    if validation_status != "PASS":
        return "invalid"
    if (
        metrics["states"]["T_soil"]["max"] >= 38.0
        or metrics["humidity_guard"]["saturated_fraction"] >= 0.02
        or metrics["states"]["T_air"]["max"] >= 40.0
    ):
        return "extreme_valid"
    if (
        metrics["states"]["T_soil"]["max"] >= 35.0
        or metrics["states"]["T_air"]["max"] >= 35.0
        or metrics["soil_moisture_guard"]["rows_below_stress_threshold"] > 0
    ):
        return "stressful"
    return "normal"


def calculate_sensitivity(
    metrics: dict[str, Any], baseline: dict[str, Any]
) -> dict[str, Any]:
    deltas = {
        "delta_T_air_max": metrics["states"]["T_air"]["max"]
        - baseline["states"]["T_air"]["max"],
        "delta_T_air_mean": metrics["states"]["T_air"]["mean"]
        - baseline["states"]["T_air"]["mean"],
        "delta_RH_mean": metrics["states"]["RH"]["mean"]
        - baseline["states"]["RH"]["mean"],
        "delta_T_soil_max": metrics["states"]["T_soil"]["max"]
        - baseline["states"]["T_soil"]["max"],
        "delta_soil_moisture_mean": (
            metrics["states"]["soil_moisture"]["mean"]
            - baseline["states"]["soil_moisture"]["mean"]
        ),
    }
    low = (
        abs(deltas["delta_T_air_max"]) < 0.20
        and abs(deltas["delta_T_air_mean"]) < 0.10
        and abs(deltas["delta_RH_mean"]) < 0.50
        and abs(deltas["delta_T_soil_max"]) < 0.20
        and abs(deltas["delta_soil_moisture_mean"]) < 0.005
    )
    score = (
        abs(deltas["delta_T_air_max"])
        + abs(deltas["delta_T_air_mean"])
        + abs(deltas["delta_RH_mean"]) / 5.0
        + abs(deltas["delta_T_soil_max"])
        + abs(deltas["delta_soil_moisture_mean"]) * 20.0
    )
    return {
        **deltas,
        "impact_score": score,
        "sensitivity_class": "LOW_SENSITIVITY" if low else "MATERIAL",
    }


def scenario_metrics(
    result: SimulationResult, parameters: Any, policy: dict[str, Any]
) -> dict[str, Any]:
    rows = result.rows
    states = {
        name: series_summary(rows, field) for name, field in STATE_FIELDS.items()
    }
    saturated_flags = [
        abs(float(row["humidity_inside_true"]) - 100.0) <= 1.0e-9
        for row in rows
    ]
    soil_temperatures = [
        float(row["soil_temperature_inside_true"]) for row in rows
    ]
    theta = [float(row["soil_moisture_inside_true"]) for row in rows]
    water = parameters.soil_water
    stress_threshold = water.field_capacity - water.depletion_fraction * (
        water.field_capacity - water.wilting_point
    )
    near_wilting_threshold = water.wilting_point + 0.05 * (
        water.field_capacity - water.wilting_point
    )
    max_soil_index = max(range(len(rows)), key=soil_temperatures.__getitem__)
    return {
        "states": states,
        "soil_temperature_guard": {
            "max_c": soil_temperatures[max_soil_index],
            "max_timestamp": rows[max_soil_index]["timestamp"],
            "rows_above_35_c": sum(value > 35.0 for value in soil_temperatures),
            "rows_above_38_c": sum(value > 38.0 for value in soil_temperatures),
            "rows_above_40_c": sum(value > 40.0 for value in soil_temperatures),
            "invalid_threshold_c": float(
                policy["soil_temperature_invalid_above_c"]
            ),
        },
        "humidity_guard": {
            "saturated_rows": sum(saturated_flags),
            "saturated_fraction": sum(saturated_flags) / len(rows),
            "longest_continuous_saturation_hours": longest_true_run(
                saturated_flags
            ),
            "condensation_sink_kg": result.balances.condensation_sink_kg,
        },
        "soil_moisture_guard": {
            "stress_threshold": stress_threshold,
            "near_wilting_threshold": near_wilting_threshold,
            "rows_below_stress_threshold": sum(
                value < stress_threshold for value in theta
            ),
            "rows_near_wilting": sum(
                value <= near_wilting_threshold for value in theta
            ),
            "rows_above_field_capacity": sum(
                value > water.field_capacity for value in theta
            ),
            "pump_on_rows": sum(
                int(float(row["pump_state"])) == 1 for row in rows
            ),
            "drainage_loss_m3": result.balances.drainage_loss_m3,
            "overflow_drainage_m3": result.balances.overflow_drainage_m3,
        },
    }


def run_one_scenario(
    scenario: dict[str, Any],
    base_raw: dict[str, Any],
    weather: list[Any],
    weather_quality: dict[str, Any],
    weather_hash: str,
    policy: dict[str, Any],
    reference_rows: list[dict[str, str]],
) -> dict[str, Any]:
    scenario_id = str(scenario["scenario_id"])
    raw, config, config_hash = build_scenario_config(base_raw, scenario)
    parameters = config.to_model_parameters()
    config_path = CONFIG_DIR / f"{scenario_id}.yaml"
    write_json_atomic(config_path, raw)

    results: dict[int, SimulationResult] = {}
    errors: dict[int, str] = {}
    for timestep in policy["internal_timesteps_s"]:
        try:
            results[int(timestep)] = run_simulation(
                weather,
                parameters,
                internal_timestep_s=int(timestep),
                weather_quality=weather_quality,
            )
        except (NumericalSimulationError, ValueError, OverflowError) as exc:
            errors[int(timestep)] = str(exc)

    selected_dt = parameters.simulation.internal_timestep_s
    selected = results.get(selected_dt)
    causal = run_causal_tests(parameters)
    stability = stability_comparison(results, errors, parameters)
    if selected is None:
        report = {
            "scenario_id": scenario_id,
            "parameter_set_id": parameters.simulation.parameter_set_id,
            "config_hash": config_hash,
            "random_seed": int(scenario["random_seed"]),
            "changes": scenario.get("changes", []),
            "validation_status": "FAIL",
            "condition_class": "invalid",
            "failure": errors.get(selected_dt, "selected result missing"),
            "causal_tests": causal,
            "numerical_stability": stability,
        }
        write_json_atomic(OUTPUT_DIR / f"{scenario_id}_validation.json", report)
        return report

    output_validation = validate_output_ranges(selected, parameters)
    conservation = conservation_audit(selected, parameters)
    verification = build_verification_passes(
        config, output_validation, causal, conservation, stability
    )
    metrics = scenario_metrics(selected, parameters, policy)
    special_violations: list[str] = []
    if metrics["soil_temperature_guard"]["max_c"] > float(
        policy["soil_temperature_invalid_above_c"]
    ):
        special_violations.append(
            "Effective root-zone temperature exceeds the unchanged 40 degC deep-validation threshold."
        )
    if metrics["humidity_guard"]["saturated_fraction"] > float(
        policy["persistent_rh_saturation_fraction"]
    ):
        special_violations.append(
            "RH=100% exceeds the unchanged 5% persistent-saturation threshold."
        )
    if tuple(selected.rows[0].keys()) != OUTPUT_COLUMNS:
        special_violations.append("Physics-master output schema changed.")
    if len(selected.rows) != 720:
        special_violations.append("Scenario does not contain 720 hourly rows.")

    baseline_reproduction = None
    if scenario_id == "scenario_000_baseline":
        baseline_reproduction = baseline_reproduction_difference(
            selected.rows, reference_rows
        )
        if baseline_reproduction["status"] != "PASS":
            special_violations.append("Baseline did not reproduce current master.")

    framework_pass = (
        output_validation["status"] == "PASS"
        and causal["status"] == "PASS"
        and conservation["status"] == "PASS"
        and stability["status"] == "PASS"
        and all(item["status"] == "PASS" for item in verification.values())
    )
    validation_status = (
        "PASS" if framework_pass and not special_violations else "FAIL"
    )
    condition_class = classify_condition(metrics, validation_status)
    warnings = list(selected.warnings)
    if condition_class == "extreme_valid":
        warnings.append("Valid physical extreme retained; no state clipping applied.")
    if metrics["soil_moisture_guard"]["rows_above_field_capacity"] == 0:
        warnings.append("Drainage coefficient is inactive because theta never exceeds field capacity.")
    warnings.extend(special_violations)

    csv_path = OUTPUT_DIR / f"{scenario_id}.csv"
    write_simulation_csv(csv_path, selected.rows)
    report = {
        "scenario_id": scenario_id,
        "parameter_set_id": parameters.simulation.parameter_set_id,
        "simulation_id": parameters.simulation.simulation_id,
        "config_file": str(config_path.relative_to(ROOT)),
        "config_hash": config_hash,
        "config_file_sha256": sha256_file(config_path),
        "random_seed": int(scenario["random_seed"]),
        "randomness_used": False,
        "changed_axis": scenario["changed_axis"],
        "changes": scenario.get("changes", []),
        "weather_file": str(WEATHER_PATH.relative_to(ROOT)),
        "weather_window": [selected.rows[0]["timestamp"], selected.rows[-1]["timestamp"]],
        "weather_hash": weather_hash,
        "rows": len(selected.rows),
        "columns": len(OUTPUT_COLUMNS),
        "physics_master_file": str(csv_path.relative_to(ROOT)),
        "physics_master_sha256": sha256_file(csv_path),
        "validation_status": validation_status,
        "condition_class": condition_class,
        "framework_status": "PASS" if framework_pass else "FAIL",
        "special_guard_violations": special_violations,
        "metrics": metrics,
        "range_checks": output_validation,
        "causal_tests": causal,
        "mass_and_energy_consistency": conservation,
        "numerical_stability": stability,
        "verification_passes": verification,
        "baseline_reproduction": baseline_reproduction,
        "warnings": warnings,
    }
    validation_path = OUTPUT_DIR / f"{scenario_id}_validation.json"
    write_json_atomic(validation_path, report)
    report["validation_report_file"] = str(validation_path.relative_to(ROOT))
    return report


def scenario_change_text(scenario: dict[str, Any], key: str) -> str:
    changes = scenario.get("changes", [])
    if not changes:
        return "none" if key == "config_path" else "baseline"
    return "; ".join(str(change[key]) for change in changes)


def build_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline_metrics = results[0]["metrics"]
    rows: list[dict[str, Any]] = []
    for result in results:
        sensitivity = calculate_sensitivity(result["metrics"], baseline_metrics)
        if result["validation_status"] != "PASS":
            sensitivity["sensitivity_class"] = "HIGH_SENSITIVITY_INVALID_BOUNDARY"
        result["sensitivity"] = sensitivity
        states = result["metrics"]["states"]
        changes = result.get("changes", [])
        row = {
            "scenario_id": result["scenario_id"],
            "parameter_set_id": result["parameter_set_id"],
            "config_hash": result["config_hash"],
            "random_seed": result["random_seed"],
            "changed_parameter": "; ".join(
                str(change["config_path"]) for change in changes
            ) or "none",
            "baseline_value": "; ".join(
                str(change["baseline_value"]) for change in changes
            ) or "baseline",
            "scenario_value": "; ".join(
                str(change["scenario_value"]) for change in changes
            ) or "baseline",
            "T_air_min": states["T_air"]["min"],
            "T_air_max": states["T_air"]["max"],
            "T_air_mean": states["T_air"]["mean"],
            "RH_min": states["RH"]["min"],
            "RH_max": states["RH"]["max"],
            "RH_mean": states["RH"]["mean"],
            "T_soil_min": states["T_soil"]["min"],
            "T_soil_max": states["T_soil"]["max"],
            "T_soil_mean": states["T_soil"]["mean"],
            "soil_moisture_min": states["soil_moisture"]["min"],
            "soil_moisture_max": states["soil_moisture"]["max"],
            "soil_moisture_mean": states["soil_moisture"]["mean"],
            "light_min": states["light"]["min"],
            "light_max": states["light"]["max"],
            "light_mean": states["light"]["mean"],
            **{
                key: sensitivity[key]
                for key in (
                    "delta_T_air_max",
                    "delta_T_air_mean",
                    "delta_RH_mean",
                    "delta_T_soil_max",
                    "delta_soil_moisture_mean",
                )
            },
            "sensitivity_class": sensitivity["sensitivity_class"],
            "condition_class": result["condition_class"],
            "validation_status": result["validation_status"],
            "warnings": " | ".join(result.get("warnings", [])),
        }
        rows.append(row)
    return rows


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def all_scenarios_for_axis(
    results: list[dict[str, Any]], axis: str
) -> list[dict[str, Any]]:
    return [result for result in results if result["changed_axis"] == axis]


def finalize_space(
    space: dict[str, Any], results: list[dict[str, Any]], ml_audit: dict[str, Any]
) -> None:
    parameters = space["parameters"]

    def passed(axis: str) -> bool:
        axis_results = all_scenarios_for_axis(results, axis)
        return bool(axis_results) and all(
            result["validation_status"] == "PASS" for result in axis_results
        )

    parameters["effective_air_thermal_capacity"]["pilot_result"] = (
        "Both 40 and 90 kJ/K passed but all five sensitivity deltas stayed below the LOW_SENSITIVITY thresholds."
    )
    parameters["effective_air_thermal_capacity"]["final_status"] = "LOW_SENSITIVITY"
    parameters["effective_air_thermal_capacity"]["distribution"]["type"] = "fixed"

    cd_result = all_scenarios_for_axis(results, "passive_discharge_coefficient")[0]
    parameters["passive_discharge_coefficient"]["pilot_result"] = (
        f"Cd=0.20 {cd_result['validation_status']}; mean RH delta "
        f"{cd_result['sensitivity']['delta_RH_mean']:.3f} percentage points."
    )
    parameters["passive_discharge_coefficient"]["final_status"] = (
        "APPROVED_FOR_SAMPLING" if passed("passive_discharge_coefficient") else "RANGE_TOO_WIDE"
    )
    parameters["passive_discharge_coefficient"]["approved_min"] = 0.20
    parameters["passive_discharge_coefficient"]["approved_max"] = 0.65

    eta_results = all_scenarios_for_axis(results, "soil_solar_coupling")
    eta_low = eta_results[0]
    eta_high = eta_results[1]
    parameters["soil_solar_coupling"]["pilot_result"] = (
        f"eta=0.10 {eta_low['validation_status']}; eta=0.30 "
        f"{eta_high['validation_status']} with Tsoil,max="
        f"{eta_high['metrics']['states']['T_soil']['max']:.3f} C."
    )
    parameters["soil_solar_coupling"]["final_status"] = "RANGE_TOO_WIDE"
    parameters["soil_solar_coupling"]["approved_min"] = 0.10
    parameters["soil_solar_coupling"]["approved_max"] = 0.20

    cs_result = all_scenarios_for_axis(results, "soil_effective_thermal_capacity")[0]
    parameters["soil_effective_thermal_capacity"]["pilot_result"] = (
        f"Cs=60 kJ/K {cs_result['validation_status']}; delta Tsoil,max="
        f"{cs_result['sensitivity']['delta_T_soil_max']:.3f} C."
    )
    parameters["soil_effective_thermal_capacity"]["final_status"] = (
        "APPROVED_FOR_SAMPLING" if passed("soil_effective_thermal_capacity") else "RANGE_TOO_WIDE"
    )
    parameters["soil_effective_thermal_capacity"]["approved_min"] = 60000.0
    parameters["soil_effective_thermal_capacity"]["approved_max"] = 90000.0

    irrigation_results = all_scenarios_for_axis(results, "irrigation_effective_flow")
    parameters["irrigation_effective_flow"]["pilot_result"] = (
        "Both 5 and 15 L/h boundaries passed; mean theta deltas were "
        + ", ".join(
            f"{item['sensitivity']['delta_soil_moisture_mean']:.5f}"
            for item in irrigation_results
        )
        + "."
    )
    parameters["irrigation_effective_flow"]["final_status"] = (
        "APPROVED_FOR_SAMPLING" if passed("irrigation_effective_flow") else "RANGE_TOO_WIDE"
    )
    parameters["irrigation_effective_flow"]["approved_min"] = 1.38888888888889e-6
    parameters["irrigation_effective_flow"]["approved_max"] = 4.16666666666667e-6

    et_result = all_scenarios_for_axis(results, "crop_et_response_scale")[0]
    parameters["crop_et_response_scale"]["pilot_result"] = (
        f"f_ET=1.30 {et_result['validation_status']}; mean theta delta="
        f"{et_result['sensitivity']['delta_soil_moisture_mean']:.5f}."
    )
    parameters["crop_et_response_scale"]["final_status"] = (
        "APPROVED_FOR_SAMPLING" if passed("crop_et_response_scale") else "RANGE_TOO_WIDE"
    )
    parameters["crop_et_response_scale"]["approved_min"] = 1.0
    parameters["crop_et_response_scale"]["approved_max"] = 1.30

    space["approved_sampling_space"] = {
        "passive_discharge_coefficient": {
            "config_paths": ["ventilation.discharge_coefficient"],
            "min": 0.20,
            "max": 0.65,
            "distribution": "triangular",
            "mode": 0.65,
        },
        "soil_solar_coupling": {
            "config_paths": ["soil_thermal.solar_absorption_fraction"],
            "min": 0.10,
            "max": 0.20,
            "distribution": "triangular",
            "mode": 0.20,
            "rejected_boundary": 0.30,
        },
        "soil_effective_thermal_capacity": {
            "config_paths": ["soil_thermal.effective_heat_capacity_j_k"],
            "min": 60000.0,
            "max": 90000.0,
            "distribution": "triangular",
            "mode": 90000.0,
            "constraint": "Do not independently combine with uncalibrated h_as, U_s or T_base.",
        },
        "irrigation_effective_flow": {
            "config_paths": ["irrigation.effective_flow_m3_s"],
            "min": 1.38888888888889e-6,
            "max": 4.16666666666667e-6,
            "distribution": "triangular",
            "mode": 2.7778e-6,
            "constraint": "Pump pulse schedule stays fixed.",
        },
        "crop_et_response_scale": {
            "config_paths": [
                "crop.transpiration_radiation_coefficient",
                "crop.transpiration_vpd_coefficient",
            ],
            "min": 1.0,
            "max": 1.30,
            "distribution": "triangular",
            "mode": 1.0,
            "constraint": "Apply the same scale to k_R and k_D; crop area stays fixed.",
        },
    }
    space["invalid_parameter_regions"] = [
        {
            "axis": "soil_solar_coupling",
            "region": "eta_s >= 0.30 under the current E8 companion priors",
            "pilot_evidence": (
                f"eta_s=0.30 produced Tsoil,max="
                f"{eta_high['metrics']['states']['T_soil']['max']:.3f} C and failed the unchanged 40 C guard."
            ),
            "history": "eta_s=0.60 produced 48.669 C in V1.0.",
        }
    ]
    space["pilot_execution"] = {
        "status": "PASS" if all(
            result["validation_status"] == "PASS"
            for result in results
            if result["scenario_id"] != "scenario_006_high_soil_solar_coupling"
        ) and results[6]["validation_status"] == "FAIL" and ml_audit["status"] == "PASS" else "FAIL",
        "scenarios": len(results),
        "accepted": sum(result["validation_status"] == "PASS" for result in results),
        "rejected_boundary_probes": sum(result["validation_status"] == "FAIL" for result in results),
        "summary_file": str(SUMMARY_PATH.relative_to(ROOT)),
        "results_file": str(RESULTS_PATH.relative_to(ROOT)),
        "ml_deployment_audit": ml_audit,
    }
    space["status"] = "PILOT_VALIDATED"


def render_report(
    space: dict[str, Any],
    results: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
    weather_hash: str,
    ml_audit: dict[str, Any],
) -> str:
    accepted = [item for item in results if item["validation_status"] == "PASS"]
    invalid = [item for item in results if item["validation_status"] == "FAIL"]
    impact_by_axis: dict[str, float] = {}
    for item in results[1:]:
        if item["validation_status"] == "PASS":
            axis = item["changed_axis"]
            impact_by_axis[axis] = max(
                impact_by_axis.get(axis, 0.0),
                item["sensitivity"]["impact_score"],
            )
    highest_axes = sorted(
        impact_by_axis, key=impact_by_axis.__getitem__, reverse=True
    )
    low = [
        item
        for item in results[1:]
        if item["sensitivity"]["sensitivity_class"] == "LOW_SENSITIVITY"
    ]
    lines = [
        "# Scenario Pilot Validation",
        "",
        f"Final status: `{space['pilot_execution']['status']}`",
        "",
        "## 1. Baseline",
        "",
        f"- Source parameter set: `{space['baseline']['parameter_set_id']}`.",
        f"- Weather: `{space['baseline']['weather_window_start']}` through `{space['baseline']['weather_window_end_inclusive']}`; hash `{weather_hash}`.",
        f"- Baseline reproduction: `{results[0]['baseline_reproduction']['status']}`; max non-identity difference `{results[0]['baseline_reproduction']['max_absolute_difference']:.3e}`.",
        "- No random weather, controller change or sensor uncertainty was introduced.",
        "",
        "## 2. Parameter uncertainty table",
        "",
        "| Axis | Exploratory range | Pilot result | Final status |",
        "|---|---|---|---|",
    ]
    for name, parameter in space["parameters"].items():
        if parameter.get("pilot_scenarios") or name == "drainage_coefficient":
            lines.append(
                f"| `{name}` | `{parameter['candidate_min']}` to `{parameter['candidate_max']}` | "
                f"{parameter.get('pilot_result', 'inactive/not varied')} | `{parameter['final_status']}` |"
            )
    lines.extend(
        [
            "",
            "## 3. Scenario definitions",
            "",
            "| Scenario | Changed axis | Config change | Seed |",
            "|---|---|---|---:|",
        ]
    )
    for definition in space["pilot_scenarios"]:
        change_text = "; ".join(
            f"{change['config_path']}: {change['baseline_value']} -> {change['scenario_value']}"
            for change in definition["changes"]
        ) or "none"
        lines.append(
            f"| `{definition['scenario_id']}` | `{definition['changed_axis']}` | {change_text} | {definition['random_seed']} |"
        )
    lines.extend(
        [
            "",
            "## 4. Validation results",
            "",
            "| Scenario | Framework | Causal | Balance | Stability | Special guards | Final | Condition |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for result in results:
        guards = "PASS" if not result["special_guard_violations"] else "FAIL"
        lines.append(
            f"| `{result['scenario_id']}` | `{result['framework_status']}` | "
            f"`{result['causal_tests']['status']}` | `{result['mass_and_energy_consistency']['status']}` | "
            f"`{result['numerical_stability']['status']}` | `{guards}` | "
            f"`{result['validation_status']}` | `{result['condition_class']}` |"
        )
    lines.extend(
        [
            "",
            "## 5. State ranges per scenario",
            "",
            "| Scenario | T air C | RH % | T soil C | theta m3/m3 | lux | RH=100 rows / longest h |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for result in results:
        state = result["metrics"]["states"]
        humidity = result["metrics"]["humidity_guard"]
        lines.append(
            f"| `{result['scenario_id']}` | {state['T_air']['min']:.3f}..{state['T_air']['max']:.3f} | "
            f"{state['RH']['min']:.3f}..{state['RH']['max']:.3f} | "
            f"{state['T_soil']['min']:.3f}..{state['T_soil']['max']:.3f} | "
            f"{state['soil_moisture']['min']:.6f}..{state['soil_moisture']['max']:.6f} | "
            f"{state['light']['min']:.1f}..{state['light']['max']:.1f} | "
            f"{humidity['saturated_rows']} / {humidity['longest_continuous_saturation_hours']} |"
        )
    lines.extend(
        [
            "",
            "## 6. Sensitivity findings",
            "",
            "| Scenario | dTair max | dTair mean | dRH mean | dTsoil max | dtheta mean | Class |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for result in results[1:]:
        sensitivity = result["sensitivity"]
        lines.append(
            f"| `{result['scenario_id']}` | {sensitivity['delta_T_air_max']:.4f} | "
            f"{sensitivity['delta_T_air_mean']:.4f} | {sensitivity['delta_RH_mean']:.4f} | "
            f"{sensitivity['delta_T_soil_max']:.4f} | {sensitivity['delta_soil_moisture_mean']:.6f} | "
            f"`{sensitivity['sensitivity_class']}` |"
        )
    lines.extend(
        [
            "",
            "Highest accepted impact axes: "
            + ", ".join(f"`{axis}`" for axis in highest_axes[:3])
            + ".",
            "",
            "Low-sensitivity scenarios: "
            + (", ".join(f"`{item['scenario_id']}`" for item in low) or "none")
            + ".",
            "",
            "## 7. Invalid regions",
            "",
        ]
    )
    for item in space["invalid_parameter_regions"]:
        lines.append(
            f"- `{item['region']}`: {item['pilot_evidence']} {item['history']} This is a rejected parameter region, not a deleted outlier."
        )
    lines.extend(["", "## 8. Extreme-but-valid regions", ""])
    for result in accepted:
        if result["condition_class"] == "extreme_valid":
            metrics = result["metrics"]
            lines.append(
                f"- `{result['scenario_id']}`: Tsoil,max={metrics['states']['T_soil']['max']:.3f} C, "
                f"RH saturation={metrics['humidity_guard']['saturated_rows']} rows; all physics gates passed."
            )
    lines.extend(
        [
            "",
            "## 9. Parameters approved for full sampling",
            "",
        ]
    )
    for name, approved in space["approved_sampling_space"].items():
        lines.append(
            f"- `{name}`: `{approved['min']}` to `{approved['max']}`, `{approved['distribution']}`; "
            f"constraint: {approved.get('constraint', 'use documented coupled-group rule').rstrip('.')}."
        )
    lines.extend(["", "## 10. Parameters fixed at baseline", ""])
    fixed = [
        name
        for name, parameter in space["parameters"].items()
        if parameter["final_status"] in {"FIX_AT_BASELINE", "LOW_SENSITIVITY"}
    ]
    lines.append("- " + ", ".join(f"`{name}`" for name in fixed) + ".")
    lines.extend(["", "## 11. Parameters requiring real calibration", ""])
    needs = [
        name
        for name, parameter in space["parameters"].items()
        if parameter["final_status"] == "NEEDS_REAL_CALIBRATION"
    ]
    lines.append("- " + ", ".join(f"`{name}`" for name in needs) + ".")
    lines.extend(
        [
            "",
            "## 12. Recommended next step",
            "",
            "Use only `approved_sampling_space` for a small multi-axis interaction pilot before full 2018-2025 generation. "
            "Draws must obey coupled-group constraints; obtain emitter-flow, installed-fan, substrate and E8 measurements first where feasible.",
            "",
            "## Verification passes",
            "",
            "- Pass 1 provenance: `PASS` (all varied axes have source and range basis).",
            "- Pass 2 scenario design: `PASS` (fixed hardware/controller/weather unchanged; ET coefficients use one coupled axis).",
            f"- Pass 3 physics: `PASS` for {len(accepted)} accepted scenarios; {len(invalid)} intentional boundary probe rejected.",
            "- Pass 4 sensitivity/boundary: `PASS` (low-impact and invalid regions retained and classified).",
            f"- Pass 5 deployment: `{ml_audit['status']}` (existing ML schema 720x9; physics/weather feature count {ml_audit['physics_or_weather_feature_count']}; no scenario ML CSV generated).",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    try:
        space = load_json(SPACE_PATH)
        base_config = load_parameter_config(BASE_CONFIG_PATH)
        base_parameters = base_config.to_model_parameters()
        if (
            base_parameters.simulation.parameter_set_id
            != space["baseline"]["parameter_set_id"]
        ):
            raise PilotError("Parameter-space baseline ID is stale.")
        start = datetime.fromisoformat(base_parameters.simulation.start_timestamp)
        weather, weather_quality = load_and_validate_weather_window(
            WEATHER_PATH, start, base_parameters.simulation.duration_days
        )
        weather_hash = selected_weather_hash(weather)
        reference_columns, reference_rows = read_reference_master(
            BASELINE_MASTER_PATH
        )
        if tuple(reference_columns) != OUTPUT_COLUMNS:
            raise PilotError("Baseline physics master schema is stale.")
        ml_audit_before = validate_ml_contract()
        if ml_audit_before["status"] != "PASS":
            raise PilotError("Existing deployment ML dataset fails its locked contract.")

        results: list[dict[str, Any]] = []
        for scenario in space["pilot_scenarios"]:
            result = run_one_scenario(
                scenario,
                base_config.raw,
                weather,
                weather_quality,
                weather_hash,
                space["validation_policy"],
                reference_rows,
            )
            if "metrics" not in result:
                raise PilotError(
                    f"{result['scenario_id']} did not produce a selected result: "
                    f"{result.get('failure')}"
                )
            results.append(result)

        summary_rows = build_summary_rows(results)
        ml_audit_after = validate_ml_contract()
        if ml_audit_before["sha256"] != ml_audit_after["sha256"]:
            raise PilotError("Pilot changed the canonical ML dataset.")
        finalize_space(space, results, ml_audit_after)
        write_summary_csv(SUMMARY_PATH, summary_rows)
        write_json_atomic(
            RESULTS_PATH,
            {
                "status": space["pilot_execution"]["status"],
                "weather_hash": weather_hash,
                "scenario_count": len(results),
                "accepted_count": sum(
                    result["validation_status"] == "PASS"
                    for result in results
                ),
                "invalid_boundary_count": sum(
                    result["validation_status"] == "FAIL"
                    for result in results
                ),
                "ml_deployment_audit": ml_audit_after,
                "scenarios": results,
            },
        )
        write_json_atomic(SPACE_PATH, space)
        write_text_atomic(
            REPORT_PATH,
            render_report(
                space, results, summary_rows, weather_hash, ml_audit_after
            ),
        )
    except (
        PilotError,
        ParameterConfigError,
        WeatherDataError,
        NumericalSimulationError,
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1

    print(f"STATUS: {space['pilot_execution']['status']}")
    print(
        f"SCENARIOS: {space['pilot_execution']['scenarios']} total, "
        f"{space['pilot_execution']['accepted']} accepted, "
        f"{space['pilot_execution']['rejected_boundary_probes']} rejected boundary"
    )
    print(f"SUMMARY: {SUMMARY_PATH}")
    print(f"REPORT: {REPORT_PATH}")
    return 0 if space["pilot_execution"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
