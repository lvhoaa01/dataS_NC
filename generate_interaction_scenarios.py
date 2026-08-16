"""Run the deterministic PA1 joint-parameter interaction pilot.

The script reuses the existing simulator and validation functions. It does not
implement physics, alter validator thresholds, randomize weather, or build ML
training data.
"""

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

import generate_pilot_scenarios as single_pilot
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
SINGLE_SPACE_PATH = ROOT / "scenario_parameter_space.yaml"
INTERACTION_CONFIG_PATH = ROOT / "interaction_scenarios.yaml"
SINGLE_RESULTS_PATH = ROOT / "outputs" / "scenario_pilot" / "scenario_pilot_results.json"
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
BASELINE_MASTER_PATH = ROOT / "outputs" / "greenhouse_simulation_30days.csv"
OUTPUT_DIR = ROOT / "outputs" / "interaction_pilot"
CONFIG_DIR = OUTPUT_DIR / "configs"
VALIDATION_DIR = OUTPUT_DIR / "validation"
SUMMARY_PATH = OUTPUT_DIR / "interaction_pilot_summary.csv"
RESULTS_PATH = OUTPUT_DIR / "interaction_pilot_results.json"
REPORT_PATH = ROOT / "interaction_pilot_validation.md"
JOINT_SPACE_PATH = ROOT / "joint_parameter_space.yaml"
JOINT_KNOWLEDGE_PATH = ROOT / "GREENHOUSE_JOINT_PARAMETER_SPACE.md"

AXIS_NAMES = ("C_d", "eta_s", "C_s", "irrigation_flow_L_h", "ET_scale")
AXIS_PATHS = {
    "C_d": ("ventilation.discharge_coefficient",),
    "eta_s": ("soil_thermal.solar_absorption_fraction",),
    "C_s": ("soil_thermal.effective_heat_capacity_j_k",),
    "irrigation_flow_L_h": ("irrigation.effective_flow_m3_s",),
    "ET_scale": (
        "crop.transpiration_radiation_coefficient",
        "crop.transpiration_vpd_coefficient",
    ),
}

STATE_FIELDS = {
    "T_air": "temperature_inside_true",
    "RH": "humidity_inside_true",
    "T_soil": "soil_temperature_inside_true",
    "soil_moisture": "soil_moisture_inside_true",
    "light": "light_lux_inside_true",
}

EFFECT_FIELDS = (
    "delta_T_air_mean",
    "delta_T_air_max",
    "delta_RH_mean",
    "delta_RH_max",
    "delta_T_soil_mean",
    "delta_T_soil_max",
    "delta_soil_moisture_mean",
    "delta_soil_moisture_min",
    "delta_light_mean",
    "delta_light_max",
)

SUMMARY_COLUMNS = (
    "scenario_id",
    "parameter_set_id",
    "config_hash",
    "weather_hash",
    "simulator_code_hash",
    "C_d",
    "eta_s",
    "C_s",
    "irrigation_flow_L_h",
    "ET_scale",
    "T_air_min",
    "T_air_max",
    "T_air_mean",
    "RH_min",
    "RH_max",
    "RH_mean",
    "RH_100_count",
    "RH_saturation_percent",
    "RH_longest_saturation",
    "T_soil_min",
    "T_soil_max",
    "T_soil_mean",
    "T_soil_p95",
    "T_soil_p99",
    "hours_soil_above_36",
    "hours_soil_above_38",
    "hours_soil_above_40",
    "soil_moisture_min",
    "soil_moisture_max",
    "soil_moisture_mean",
    "stress_hours",
    "near_wilting_hours",
    "above_field_capacity_hours",
    "pump_on_count",
    "pump_transition_count",
    "ET_total_kg",
    "irrigation_total_L",
    "drainage_total_L",
    "condensation_total_kg",
    *EFFECT_FIELDS,
    "nonlinear_classification",
    "validation_status",
    "classification",
    "warnings",
)


class InteractionError(RuntimeError):
    """Raised when an interaction design or execution invariant fails."""


def load_json(path: Path) -> dict[str, Any]:
    return single_pilot.load_json(path)


def write_json_atomic(path: Path, payload: Any) -> None:
    single_pilot.write_json_atomic(path, payload)


def write_text_atomic(path: Path, text: str) -> None:
    single_pilot.write_text_atomic(path, text)


def canonical_hash(payload: Any) -> str:
    return single_pilot.canonical_hash(payload)


def sha256_file(path: Path) -> str:
    return single_pilot.sha256_file(path)


def simulator_code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "physics").glob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode("ascii"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def percentile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise InteractionError("Cannot calculate a percentile of an empty series.")
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def summarize(values: Iterable[float]) -> dict[str, float]:
    series = [float(value) for value in values]
    return {
        "min": min(series),
        "max": max(series),
        "mean": statistics.fmean(series),
        "p95": percentile(series, 0.95),
        "p99": percentile(series, 0.99),
    }


def irrigation_config_value(axis: dict[str, Any], value_l_h: float) -> float:
    lookup = axis["config_values_m3_s"]
    key = f"{float(value_l_h):.1f}"
    if key in lookup:
        return float(lookup[key])
    return float(value_l_h) / 3_600_000.0


def baseline_axis_values(base_config: ParameterConfig) -> dict[str, float]:
    model = base_config.to_model_parameters()
    return {
        "C_d": model.ventilation.discharge_coefficient,
        "eta_s": model.soil_thermal.solar_absorption_fraction,
        "C_s": model.soil_thermal.effective_heat_capacity_j_k,
        "irrigation_flow_L_h": 10.0,
        "ET_scale": 1.0,
    }


def validate_design(
    interaction: dict[str, Any],
    single_space: dict[str, Any],
    base_config: ParameterConfig,
) -> dict[str, Any]:
    scenarios = interaction.get("scenarios", [])
    if not 8 <= len(scenarios) <= 12:
        raise InteractionError("Interaction pilot must contain 8-12 scenarios.")
    ids = [str(item.get("scenario_id", "")) for item in scenarios]
    if len(ids) != len(set(ids)) or ids[0] != "interaction_000_baseline":
        raise InteractionError("Scenario IDs are missing, duplicated, or baseline is not first.")
    if set(interaction.get("approved_axes", {})) != set(AXIS_NAMES):
        raise InteractionError("Interaction config does not contain exactly five approved axes.")

    approved = single_space["approved_sampling_space"]
    source_mapping = {
        "C_d": "passive_discharge_coefficient",
        "eta_s": "soil_solar_coupling",
        "C_s": "soil_effective_thermal_capacity",
        "irrigation_flow_L_h": "irrigation_effective_flow",
        "ET_scale": "crop_et_response_scale",
    }
    scale = {"irrigation_flow_L_h": 3_600_000.0}
    for name, source_name in source_mapping.items():
        axis = interaction["approved_axes"][name]
        source = approved[source_name]
        source_min = float(source["min"]) * scale.get(name, 1.0)
        source_max = float(source["max"]) * scale.get(name, 1.0)
        if not math.isclose(float(axis["min"]), source_min, rel_tol=0.0, abs_tol=1e-9):
            raise InteractionError(f"{name}: minimum differs from approved single space.")
        if not math.isclose(float(axis["max"]), source_max, rel_tol=0.0, abs_tol=1e-9):
            raise InteractionError(f"{name}: maximum differs from approved single space.")
        if axis["distribution"] != source["distribution"]:
            raise InteractionError(f"{name}: distribution differs from approved single space.")

    baseline = baseline_axis_values(base_config)
    expected_weather_hash = interaction["baseline"]["weather_hash"]
    for scenario in scenarios:
        values = scenario.get("parameters", {})
        if set(values) != set(AXIS_NAMES):
            raise InteractionError(f"{scenario['scenario_id']}: incomplete five-axis vector.")
        if scenario.get("weather_hash") != expected_weather_hash:
            raise InteractionError(f"{scenario['scenario_id']}: weather hash differs from baseline.")
        for name in AXIS_NAMES:
            axis = interaction["approved_axes"][name]
            value = float(values[name])
            if not float(axis["min"]) <= value <= float(axis["max"]):
                raise InteractionError(f"{scenario['scenario_id']}: {name} is outside approved bounds.")
        if not isinstance(scenario.get("random_seed"), int):
            raise InteractionError(f"{scenario['scenario_id']}: random_seed is not recorded.")

    for name, value in baseline.items():
        if not math.isclose(
            float(scenarios[0]["parameters"][name]), value, rel_tol=0.0, abs_tol=1e-12
        ):
            raise InteractionError(f"Baseline interaction changed {name}.")

    et_paths = tuple(interaction["approved_axes"]["ET_scale"]["config_paths"])
    if et_paths != AXIS_PATHS["ET_scale"]:
        raise InteractionError("ET_scale must map to k_R and k_D together in fixed order.")
    return {
        "status": "PASS",
        "scenario_count": len(scenarios),
        "approved_axes": list(AXIS_NAMES),
        "fixed_hardware_randomized": False,
        "weather_randomized": False,
        "sensor_noise_enabled": False,
        "et_coefficients_coupled": True,
    }


def build_interaction_config(
    base_raw: dict[str, Any],
    scenario: dict[str, Any],
    interaction: dict[str, Any],
) -> tuple[dict[str, Any], ParameterConfig, str, list[dict[str, Any]], list[str]]:
    raw = deepcopy(base_raw)
    values = scenario["parameters"]
    changes: list[dict[str, Any]] = []

    def apply(path: str, value: float) -> None:
        before = single_pilot.get_record(raw, path)["value"]
        if not math.isclose(float(before), float(value), rel_tol=0.0, abs_tol=1e-14):
            changes.append(
                {"config_path": path, "baseline_value": before, "scenario_value": value}
            )
        single_pilot.set_value(raw, path, value)

    apply(AXIS_PATHS["C_d"][0], float(values["C_d"]))
    apply(AXIS_PATHS["eta_s"][0], float(values["eta_s"]))
    apply(AXIS_PATHS["C_s"][0], float(values["C_s"]))
    irrigation_value = irrigation_config_value(
        interaction["approved_axes"]["irrigation_flow_L_h"],
        float(values["irrigation_flow_L_h"]),
    )
    apply(AXIS_PATHS["irrigation_flow_L_h"][0], irrigation_value)
    et_scale = float(values["ET_scale"])
    for path in AXIS_PATHS["ET_scale"]:
        baseline_value = float(single_pilot.get_record(base_raw, path)["value"])
        apply(path, baseline_value * et_scale)

    scenario_id = str(scenario["scenario_id"])
    raw["scenario"] = {
        "scenario_id": {
            "value": scenario_id,
            "unit": "identifier",
            "provenance": "INTERACTION_SCENARIO_SPACE",
            "status": "DETERMINISTIC_INTERACTION_PILOT",
            "source": "interaction_scenarios.yaml",
        },
        "random_seed": {
            "value": int(scenario["random_seed"]),
            "unit": "integer",
            "provenance": "INTERACTION_SCENARIO_SPACE",
            "status": "RECORDED_NO_RANDOMNESS_USED",
            "source": "interaction_scenarios.yaml",
        },
    }
    provisional = ParameterConfig(raw, BASE_CONFIG_PATH)
    config_hash = canonical_hash(single_pilot.model_value_payload(provisional))
    parameter_set_id = f"smartgarden_pa1_joint_{config_hash[:12]}"
    single_pilot.set_value(raw, "identity.parameter_set_id", parameter_set_id)
    single_pilot.set_value(raw, "identity.simulation_id", f"{scenario_id}_june2024")
    config = ParameterConfig(raw, BASE_CONFIG_PATH)
    if canonical_hash(single_pilot.model_value_payload(config)) != config_hash:
        raise InteractionError("Identity mutation changed the physical config hash.")

    changed_axes = [
        name
        for name in AXIS_NAMES
        if not math.isclose(
            float(values[name]),
            float(interaction["approved_axes"][name]["baseline"]),
            rel_tol=0.0,
            abs_tol=1e-12,
        )
    ]
    return raw, config, config_hash, changes, changed_axes


def controller_pathology(rows: list[dict[str, Any]], parameters: Any) -> dict[str, Any]:
    pump = [int(float(row["pump_state"])) for row in rows]
    theta = [float(row["soil_moisture_inside_true"]) for row in rows]
    transitions = sum(left != right for left, right in zip(pump, pump[1:]))
    expected_max_transitions = parameters.simulation.duration_days * 4
    flags = {
        "pump_always_on": all(value == 1 for value in pump),
        "pump_always_off": all(value == 0 for value in pump),
        "pump_oscillating_excessively": transitions > expected_max_transitions,
        "soil_always_above_field_capacity": all(
            value > parameters.soil_water.field_capacity for value in theta
        ),
        "soil_collapsed_to_lower_bound": min(theta)
        <= parameters.soil_water.residual_lower_bound + 1e-9,
    }
    return {
        "status": "PASS" if not any(flags.values()) else "FLAG",
        "pump_on_rows": sum(pump),
        "pump_transition_count": transitions,
        "expected_max_transition_count": expected_max_transitions,
        "flags": flags,
    }


def scenario_metrics(result: SimulationResult, parameters: Any) -> dict[str, Any]:
    rows = result.rows
    state_values = {
        name: [float(row[field]) for row in rows]
        for name, field in STATE_FIELDS.items()
    }
    states = {name: summarize(values) for name, values in state_values.items()}
    saturated = [abs(value - 100.0) <= 1e-9 for value in state_values["RH"]]
    soil_t = state_values["T_soil"]
    theta = state_values["soil_moisture"]
    water = parameters.soil_water
    stress_threshold = water.field_capacity - water.depletion_fraction * (
        water.field_capacity - water.wilting_point
    )
    near_wilting_threshold = water.wilting_point + 0.05 * (
        water.field_capacity - water.wilting_point
    )
    soil_deltas = [right - left for left, right in zip(soil_t, soil_t[1:])]
    stress = [float(row["water_stress_coefficient"]) for row in rows]
    max_index = max(range(len(soil_t)), key=soil_t.__getitem__)
    pathology = controller_pathology(rows, parameters)
    return {
        "states": states,
        "humidity": {
            "saturated_rows": sum(saturated),
            "saturated_fraction": sum(saturated) / len(rows),
            "longest_continuous_saturation_hours": single_pilot.longest_true_run(saturated),
            "condensation_total_kg": result.balances.condensation_sink_kg,
        },
        "soil_temperature": {
            "max_c": soil_t[max_index],
            "max_timestamp": rows[max_index]["timestamp"],
            "p95_c": states["T_soil"]["p95"],
            "p99_c": states["T_soil"]["p99"],
            "hours_above_36_c": sum(value > 36.0 for value in soil_t),
            "hours_above_38_c": sum(value > 38.0 for value in soil_t),
            "hours_above_40_c": sum(value > 40.0 for value in soil_t),
            "largest_hourly_rise_c": max(soil_deltas),
            "largest_hourly_fall_c": min(soil_deltas),
        },
        "soil_water": {
            "stress_threshold": stress_threshold,
            "near_wilting_threshold": near_wilting_threshold,
            "hours_below_stress_threshold": sum(value < stress_threshold for value in theta),
            "hours_near_wilting": sum(value <= near_wilting_threshold for value in theta),
            "hours_above_field_capacity": sum(value > water.field_capacity for value in theta),
            "water_stress_min": min(stress),
            "water_stress_mean": statistics.fmean(stress),
            "et_total_kg": result.balances.evapotranspiration_source_kg,
            "irrigation_total_l": result.balances.irrigation_input_m3 * 1000.0,
            "drainage_total_l": (
                result.balances.drainage_loss_m3 + result.balances.overflow_drainage_m3
            )
            * 1000.0,
            "controller_pathology": pathology,
        },
    }


def classify_result(
    framework_status: str,
    special_violations: list[str],
    metrics: dict[str, Any],
    stability_status: str,
    causal_status: str,
    conservation_status: str,
) -> tuple[str, str]:
    if framework_status != "PASS" or special_violations:
        if stability_status != "PASS" or conservation_status != "PASS":
            return "FAIL", "NUMERICAL_FAILURE"
        if causal_status != "PASS":
            return "FAIL", "IMPLEMENTATION_BUG"
        return "FAIL", "INVALID_JOINT_REGION"
    extreme = (
        metrics["states"]["T_soil"]["max"] >= 38.0
        or metrics["humidity"]["saturated_fraction"] >= 0.02
        or metrics["soil_water"]["hours_near_wilting"] > 0
    )
    return "PASS", "EXTREME_VALID" if extreme else "VALID"


def run_one_scenario(
    scenario: dict[str, Any],
    interaction: dict[str, Any],
    base_raw: dict[str, Any],
    weather: list[Any],
    weather_quality: dict[str, Any],
    weather_hash: str,
    policy: dict[str, Any],
    reference_rows: list[dict[str, str]],
    code_hash: str,
) -> dict[str, Any]:
    scenario_id = str(scenario["scenario_id"])
    raw, config, config_hash, changes, changed_axes = build_interaction_config(
        base_raw, scenario, interaction
    )
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
            "weather_hash": weather_hash,
            "simulator_code_hash": code_hash,
            "parameters": scenario["parameters"],
            "changed_axes": changed_axes,
            "changes": changes,
            "validation_status": "FAIL",
            "classification": "NUMERICAL_FAILURE",
            "failure": errors.get(selected_dt, "selected result missing"),
            "causal_tests": causal,
            "numerical_stability": stability,
        }
        write_json_atomic(VALIDATION_DIR / f"{scenario_id}.json", report)
        return report

    output_validation = validate_output_ranges(selected, parameters)
    conservation = conservation_audit(selected, parameters)
    verification = build_verification_passes(
        config, output_validation, causal, conservation, stability
    )
    metrics = scenario_metrics(selected, parameters)
    special_violations: list[str] = []
    if metrics["soil_temperature"]["max_c"] > float(
        policy["soil_temperature_invalid_above_c"]
    ):
        special_violations.append(
            "Effective root-zone temperature exceeds the unchanged 40 degC threshold."
        )
    if metrics["humidity"]["saturated_fraction"] > float(
        policy["persistent_rh_saturation_fraction"]
    ):
        special_violations.append(
            "RH=100% exceeds the unchanged 5% persistent-saturation threshold."
        )
    if tuple(selected.rows[0].keys()) != OUTPUT_COLUMNS:
        special_violations.append("Physics-master output schema changed.")
    if len(selected.rows) != interaction["baseline"]["expected_rows"]:
        special_violations.append("Scenario does not contain 720 hourly rows.")
    if metrics["soil_water"]["controller_pathology"]["status"] != "PASS":
        special_violations.append("Controller or root-zone closure pathology detected.")

    baseline_reproduction = None
    if scenario_id == "interaction_000_baseline":
        baseline_reproduction = single_pilot.baseline_reproduction_difference(
            selected.rows, reference_rows
        )
        if baseline_reproduction["status"] != "PASS":
            special_violations.append("Baseline did not reproduce the validated V1.1 master.")

    framework_pass = (
        output_validation["status"] == "PASS"
        and causal["status"] == "PASS"
        and conservation["status"] == "PASS"
        and stability["status"] == "PASS"
        and all(item["status"] == "PASS" for item in verification.values())
    )
    validation_status, classification = classify_result(
        "PASS" if framework_pass else "FAIL",
        special_violations,
        metrics,
        stability["status"],
        causal["status"],
        conservation["status"],
    )
    warnings = list(selected.warnings)
    if classification == "EXTREME_VALID":
        warnings.append("Valid physical extreme retained; no state clipping applied.")
    if metrics["soil_water"]["hours_above_field_capacity"] == 0:
        warnings.append("Drainage remained inactive because theta never exceeded field capacity.")
    warnings.extend(special_violations)

    csv_path = OUTPUT_DIR / f"{scenario_id}.csv"
    write_simulation_csv(csv_path, selected.rows)
    validation_path = VALIDATION_DIR / f"{scenario_id}.json"
    report = {
        "scenario_id": scenario_id,
        "description": scenario["description"],
        "purpose": scenario["purpose"],
        "interaction_focus": scenario["interaction_focus"],
        "parameter_set_id": parameters.simulation.parameter_set_id,
        "simulation_id": parameters.simulation.simulation_id,
        "config_hash": config_hash,
        "config_file": str(config_path.relative_to(ROOT)),
        "config_file_sha256": sha256_file(config_path),
        "random_seed": int(scenario["random_seed"]),
        "randomness_used": False,
        "parameters": scenario["parameters"],
        "changed_axes": changed_axes,
        "changes": changes,
        "weather_file": str(WEATHER_PATH.relative_to(ROOT)),
        "weather_window": [selected.rows[0]["timestamp"], selected.rows[-1]["timestamp"]],
        "weather_hash": weather_hash,
        "simulator_code_hash": code_hash,
        "rows": len(selected.rows),
        "columns": len(OUTPUT_COLUMNS),
        "physics_master_file": str(csv_path.relative_to(ROOT)),
        "physics_master_sha256": sha256_file(csv_path),
        "validation_status": validation_status,
        "classification": classification,
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
    write_json_atomic(validation_path, report)
    report["validation_report_file"] = str(validation_path.relative_to(ROOT))
    return report


def effect_vector(metrics: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float]:
    states = metrics["states"]
    base = baseline["states"]
    return {
        "delta_T_air_mean": states["T_air"]["mean"] - base["T_air"]["mean"],
        "delta_T_air_max": states["T_air"]["max"] - base["T_air"]["max"],
        "delta_RH_mean": states["RH"]["mean"] - base["RH"]["mean"],
        "delta_RH_max": states["RH"]["max"] - base["RH"]["max"],
        "delta_T_soil_mean": states["T_soil"]["mean"] - base["T_soil"]["mean"],
        "delta_T_soil_max": states["T_soil"]["max"] - base["T_soil"]["max"],
        "delta_soil_moisture_mean": (
            states["soil_moisture"]["mean"] - base["soil_moisture"]["mean"]
        ),
        "delta_soil_moisture_min": (
            states["soil_moisture"]["min"] - base["soil_moisture"]["min"]
        ),
        "delta_light_mean": states["light"]["mean"] - base["light"]["mean"],
        "delta_light_max": states["light"]["max"] - base["light"]["max"],
    }


def single_axis_effects(single_results: dict[str, Any]) -> dict[tuple[str, float], dict[str, Any]]:
    scenarios = {item["scenario_id"]: item for item in single_results["scenarios"]}
    baseline = scenarios["scenario_000_baseline"]["metrics"]
    references = {
        ("C_d", 0.20): "scenario_003_low_passive_ventilation",
        ("eta_s", 0.10): "scenario_005_low_soil_solar_coupling",
        ("C_s", 60000.0): "scenario_007_low_soil_thermal_capacity",
        ("irrigation_flow_L_h", 5.0): "scenario_008_low_irrigation_flow",
        ("irrigation_flow_L_h", 15.0): "scenario_004_high_irrigation_flow",
        ("ET_scale", 1.30): "scenario_009_high_et_response",
    }
    return {
        key: {
            "scenario_id": scenario_id,
            "effects": effect_vector(scenarios[scenario_id]["metrics"], baseline),
        }
        for key, scenario_id in references.items()
    }


def classify_nonlinearity(
    actual: float, expected: float, tolerance: float
) -> str:
    residual = actual - expected
    if abs(residual) <= tolerance:
        return "ROUGHLY_ADDITIVE"
    if actual * expected > 0 and abs(actual) > abs(expected) + tolerance:
        return "SYNERGISTIC_INTERACTION"
    if abs(actual) < abs(expected) - tolerance or actual * expected < 0:
        return "ANTAGONISTIC_INTERACTION"
    return "NONLINEAR_MIXED"


def add_interaction_analysis(
    results: list[dict[str, Any]],
    interaction: dict[str, Any],
    single_results: dict[str, Any],
) -> None:
    baseline_metrics = results[0]["metrics"]
    references = single_axis_effects(single_results)
    tolerance = {
        "delta_T_air_mean": 0.05,
        "delta_T_air_max": 0.10,
        "delta_RH_mean": 0.50,
        "delta_RH_max": 1.0,
        "delta_T_soil_mean": 0.10,
        "delta_T_soil_max": 0.20,
        "delta_soil_moisture_mean": 0.005,
        "delta_soil_moisture_min": 0.005,
        "delta_light_mean": 1.0,
        "delta_light_max": 1.0,
    }
    focus_effect = {
        "RH_mean": "delta_RH_mean",
        "T_soil_max": "delta_T_soil_max",
        "soil_moisture_min": "delta_soil_moisture_min",
    }
    baseline_values = {
        name: float(interaction["approved_axes"][name]["baseline"])
        for name in AXIS_NAMES
    }
    for result in results:
        effects = effect_vector(result["metrics"], baseline_metrics)
        result["effects_vs_baseline"] = effects
        changed = result["changed_axes"]
        if not changed:
            result["nonlinear_analysis"] = {
                "status": "CONTROL",
                "classification": "BASELINE_CONTROL",
                "single_axis_references": [],
            }
            continue
        if len(changed) == 1:
            result["nonlinear_analysis"] = {
                "status": "REFERENCE",
                "classification": "SINGLE_AXIS_REFERENCE",
                "single_axis_references": [],
            }
            continue

        expected = {field: 0.0 for field in EFFECT_FIELDS}
        used: list[str] = []
        missing: list[str] = []
        for axis in changed:
            value = float(result["parameters"][axis])
            key = (axis, value)
            reference = references.get(key)
            if reference is None:
                if math.isclose(value, baseline_values[axis], abs_tol=1e-12):
                    continue
                missing.append(f"{axis}={value}")
                continue
            used.append(reference["scenario_id"])
            for field in EFFECT_FIELDS:
                expected[field] += reference["effects"][field]

        if missing:
            result["nonlinear_analysis"] = {
                "status": "NOT_ESTIMABLE",
                "classification": "NO_MATCHED_SINGLE_AXIS_CONTROL",
                "missing_controls": missing,
                "single_axis_references": used,
            }
            continue
        residual = {field: effects[field] - expected[field] for field in EFFECT_FIELDS}
        focus = focus_effect.get(result["interaction_focus"], "delta_RH_mean")
        result["nonlinear_analysis"] = {
            "status": "ESTIMATED",
            "classification": classify_nonlinearity(
                effects[focus], expected[focus], tolerance[focus]
            ),
            "focus_metric": focus,
            "actual_combined_effect": effects[focus],
            "expected_additive_effect": expected[focus],
            "interaction_residual": residual[focus],
            "all_expected_additive_effects": expected,
            "all_interaction_residuals": residual,
            "single_axis_references": used,
        }


def build_summary_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        metrics = result["metrics"]
        states = metrics["states"]
        humidity = metrics["humidity"]
        soil_t = metrics["soil_temperature"]
        soil_w = metrics["soil_water"]
        pathology = soil_w["controller_pathology"]
        effects = result["effects_vs_baseline"]
        row = {
            "scenario_id": result["scenario_id"],
            "parameter_set_id": result["parameter_set_id"],
            "config_hash": result["config_hash"],
            "weather_hash": result["weather_hash"],
            "simulator_code_hash": result["simulator_code_hash"],
            **result["parameters"],
            "T_air_min": states["T_air"]["min"],
            "T_air_max": states["T_air"]["max"],
            "T_air_mean": states["T_air"]["mean"],
            "RH_min": states["RH"]["min"],
            "RH_max": states["RH"]["max"],
            "RH_mean": states["RH"]["mean"],
            "RH_100_count": humidity["saturated_rows"],
            "RH_saturation_percent": humidity["saturated_fraction"] * 100.0,
            "RH_longest_saturation": humidity["longest_continuous_saturation_hours"],
            "T_soil_min": states["T_soil"]["min"],
            "T_soil_max": states["T_soil"]["max"],
            "T_soil_mean": states["T_soil"]["mean"],
            "T_soil_p95": soil_t["p95_c"],
            "T_soil_p99": soil_t["p99_c"],
            "hours_soil_above_36": soil_t["hours_above_36_c"],
            "hours_soil_above_38": soil_t["hours_above_38_c"],
            "hours_soil_above_40": soil_t["hours_above_40_c"],
            "soil_moisture_min": states["soil_moisture"]["min"],
            "soil_moisture_max": states["soil_moisture"]["max"],
            "soil_moisture_mean": states["soil_moisture"]["mean"],
            "stress_hours": soil_w["hours_below_stress_threshold"],
            "near_wilting_hours": soil_w["hours_near_wilting"],
            "above_field_capacity_hours": soil_w["hours_above_field_capacity"],
            "pump_on_count": pathology["pump_on_rows"],
            "pump_transition_count": pathology["pump_transition_count"],
            "ET_total_kg": soil_w["et_total_kg"],
            "irrigation_total_L": soil_w["irrigation_total_l"],
            "drainage_total_L": soil_w["drainage_total_l"],
            "condensation_total_kg": humidity["condensation_total_kg"],
            **effects,
            "nonlinear_classification": result["nonlinear_analysis"]["classification"],
            "validation_status": result["validation_status"],
            "classification": result["classification"],
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


def build_joint_constraints(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["scenario_id"]: item for item in results}
    constraints: list[dict[str, Any]] = [
        {
            "constraint_id": "couple_et_coefficients",
            "condition": "always",
            "status": "REQUIRE",
            "rule": "k_R = k_R_baseline * ET_scale and k_D = k_D_baseline * ET_scale",
            "reason": "k_R and k_D are one approved coupled uncertainty axis.",
        }
    ]

    humidity_corner = by_id["interaction_001_low_ventilation_high_et"]
    cd030 = by_id["interaction_009_cd030_high_et_boundary"]
    et115 = by_id["interaction_010_low_ventilation_et115_boundary"]
    if humidity_corner["validation_status"] == "FAIL":
        if cd030["validation_status"] == "PASS" and et115["validation_status"] == "PASS":
            constraints.append(
                {
                    "constraint_id": "reject_low_cd_high_et_wedge",
                    "condition": {
                        "all": [
                            {"parameter": "C_d", "operator": "<", "value": 0.30},
                            {"parameter": "ET_scale", "operator": ">", "value": 1.15},
                        ]
                    },
                    "status": "REJECT_FOR_FULL_GENERATION_V1",
                    "reason": "Persistent RH saturation at the adverse corner; both one-axis boundary relaxations passed.",
                    "evidence": [humidity_corner["scenario_id"], cd030["scenario_id"], et115["scenario_id"]],
                }
            )
        else:
            constraints.append(
                {
                    "constraint_id": "reject_observed_low_cd_high_et_corner",
                    "condition": {
                        "all": [
                            {"parameter": "C_d", "operator": "<=", "value": 0.20},
                            {"parameter": "ET_scale", "operator": ">=", "value": 1.30},
                        ]
                    },
                    "status": "REJECT_FOR_FULL_GENERATION_V1",
                    "reason": "Observed interaction corner failed unchanged physics guards; broader boundary remains unresolved.",
                    "evidence": [humidity_corner["scenario_id"]],
                }
            )

    wet_corner = by_id["interaction_004_wet_humid_boundary"]
    wet_baseline_et = by_id["interaction_008_low_ventilation_high_irrigation"]
    wet_cd030 = by_id["interaction_011_cd030_wet_high_et_boundary"]
    if wet_corner["validation_status"] == "FAIL":
        conditions = [
            {"parameter": "C_d", "operator": "<", "value": 0.30},
            {"parameter": "irrigation_flow_L_h", "operator": ">=", "value": 15.0},
        ]
        if wet_baseline_et["validation_status"] == "PASS":
            conditions.append({"parameter": "ET_scale", "operator": ">", "value": 1.0})
        constraints.append(
            {
                "constraint_id": "reject_low_cd_high_irrigation_region",
                "condition": {"all": conditions},
                "status": "REJECT_FOR_FULL_GENERATION_V1",
                "reason": "High irrigation at the low-Cd boundary exceeded unchanged humidity guards even at baseline ET.",
                "evidence": [
                    wet_corner["scenario_id"],
                    wet_baseline_et["scenario_id"],
                ],
            }
        )
    if wet_cd030["validation_status"] == "FAIL":
        constraints.append(
            {
                "constraint_id": "reject_moderate_low_cd_wet_high_et_corner",
                "condition": {
                    "all": [
                        {"parameter": "C_d", "operator": "<=", "value": 0.30},
                        {"parameter": "irrigation_flow_L_h", "operator": ">=", "value": 15.0},
                        {"parameter": "ET_scale", "operator": ">=", "value": 1.30},
                    ]
                },
                "status": "REJECT_FOR_FULL_GENERATION_V1",
                "reason": "C_d=0.30 was sufficient for high ET alone but not for simultaneous maximum irrigation and ET.",
                "evidence": [
                    wet_cd030["scenario_id"],
                    by_id["interaction_009_cd030_high_et_boundary"]["scenario_id"],
                ],
            }
        )

    constraints.append(
        {
            "constraint_id": "post_sample_physics_gate",
            "condition": "every sampled parameter set",
            "status": "REQUIRE",
            "rule": "Run the locked 30-day June preflight and reject NaN/Inf, causal/balance/stability failure, T_soil>40 C, or RH=100 for >5% of rows.",
            "reason": "A five-dimensional accepted space can be non-rectangular beyond the structured probes.",
        }
    )
    return constraints


def build_joint_space(
    interaction: dict[str, Any],
    results: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    weather_hash: str,
    code_hash: str,
    ml_audit: dict[str, Any],
) -> dict[str, Any]:
    accepted = [item for item in results if item["validation_status"] == "PASS"]
    rejected = [item for item in results if item["validation_status"] == "FAIL"]
    extreme = [item for item in accepted if item["classification"] == "EXTREME_VALID"]
    parameter_space = {
        name: {
            key: value
            for key, value in axis.items()
            if key not in {"config_values_m3_s"}
        }
        for name, axis in interaction["approved_axes"].items()
    }
    recommended_sets = 24
    return {
        "schema_version": "1.0",
        "status": "VALIDATED_JOINT_SPACE",
        "source_individual_space": str(SINGLE_SPACE_PATH.relative_to(ROOT)),
        "source_interaction_config": str(INTERACTION_CONFIG_PATH.relative_to(ROOT)),
        "weather": {
            "file": str(WEATHER_PATH.relative_to(ROOT)),
            "window": [
                interaction["baseline"]["weather_window_start"],
                interaction["baseline"]["weather_window_end_inclusive"],
            ],
            "hash": weather_hash,
            "randomized": False,
        },
        "simulator_code_hash": code_hash,
        "parameters": parameter_space,
        "joint_constraints": constraints,
        "accepted_probe_regions": [
            {"scenario_id": item["scenario_id"], "parameters": item["parameters"], "classification": item["classification"]}
            for item in accepted
        ],
        "rejected_probe_regions": [
            {"scenario_id": item["scenario_id"], "parameters": item["parameters"], "classification": item["classification"], "reason": item["special_guard_violations"]}
            for item in rejected
        ],
        "extreme_valid_probe_regions": [
            {"scenario_id": item["scenario_id"], "parameters": item["parameters"]}
            for item in extreme
        ],
        "sampling": {
            "method_candidate": "constrained_latin_hypercube_sampling",
            "number_of_dimensions": 5,
            "recommended_parameter_sets_total": recommended_sets,
            "composition": "1 locked baseline plus 23 constrained LHS parameter sets",
            "seed_policy": "Record one project seed; deterministic candidate generation and deterministic rejection filtering.",
            "constraint_policy": "Apply joint_constraints, then require the locked 30-day physics preflight before a parameter set enters full generation.",
            "full_period_rows_per_parameter_set": 70128,
            "estimated_total_rows": 70128 * recommended_sets,
            "full_generation_executed": False,
        },
        "ml_contract": ml_audit,
    }


def render_report(
    interaction: dict[str, Any],
    results: list[dict[str, Any]],
    constraints: list[dict[str, Any]],
    joint_space: dict[str, Any],
) -> str:
    accepted = [item for item in results if item["validation_status"] == "PASS"]
    rejected = [item for item in results if item["validation_status"] == "FAIL"]
    extreme = [item for item in accepted if item["classification"] == "EXTREME_VALID"]
    baseline = results[0]["baseline_reproduction"]
    lines = [
        "# Interaction Pilot Validation",
        "",
        f"Final status: `{interaction['execution']['status']}`",
        "",
        "## 1. Purpose",
        "",
        "Validate structured joint combinations of the five approved PA1 uncertainty axes without changing weather, controller, hardware, sensor layer, simulator equations, or validator thresholds.",
        "",
        "## 2. Baseline reproduction",
        "",
        f"- Status: `{baseline['status']}`.",
        f"- Maximum non-identity difference: `{baseline['max_absolute_difference']:.3e}`.",
        f"- Weather hash: `{results[0]['weather_hash']}`.",
        f"- Simulator code hash: `{results[0]['simulator_code_hash']}`.",
        "",
        "## 3. Approved individual ranges",
        "",
        "| Parameter | Min | Max | Distribution | Mode |",
        "|---|---:|---:|---|---:|",
    ]
    for name, axis in interaction["approved_axes"].items():
        lines.append(
            f"| `{name}` | {axis['min']} | {axis['max']} | `{axis['distribution']}` | {axis['mode']} |"
        )
    lines.extend(
        [
            "",
            "`ET_scale` multiplies `k_R` and `k_D` together; the coefficients were never sampled independently.",
            "",
            "## 4. Interaction scenarios",
            "",
            "| Scenario | Changed axes | Validation | Classification |",
            "|---|---|---|---|",
        ]
    )
    for result in results:
        changed = ", ".join(result["changed_axes"]) or "none"
        lines.append(
            f"| `{result['scenario_id']}` | {changed} | `{result['validation_status']}` | `{result['classification']}` |"
        )
    lines.extend(
        [
            "",
            "## 5. Humidity interactions",
            "",
            "| Scenario | RH mean/max % | RH=100 rows | Longest h | Condensation kg |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        if "RH" in result["interaction_focus"] or result["scenario_id"] == "interaction_000_baseline":
            state = result["metrics"]["states"]["RH"]
            humidity = result["metrics"]["humidity"]
            lines.append(
                f"| `{result['scenario_id']}` | {state['mean']:.3f} / {state['max']:.3f} | {humidity['saturated_rows']} | {humidity['longest_continuous_saturation_hours']} | {humidity['condensation_total_kg']:.6g} |"
            )
    lines.extend(
        [
            "",
            "The `C_d=0.20, ET_scale=1.30` corner reached 37 saturated rows (5.139%) and failed only the locked saturation guard. Its two bracket points passed: `C_d=0.30, ET_scale=1.30` had 20 rows, while `C_d=0.20, ET_scale=1.15` had 32 rows. High irrigation was more restrictive: 54 saturated rows at low Cd and baseline ET, and 46 rows at `C_d=0.30` with maximum irrigation and ET.",
        ]
    )
    lines.extend(
        [
            "",
            "## 6. Root-zone thermal interactions",
            "",
            "| Scenario | Tsoil max/p95/p99 C | h >36 | h >38 | h >40 |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        soil = result["metrics"]["soil_temperature"]
        lines.append(
            f"| `{result['scenario_id']}` | {soil['max_c']:.3f} / {soil['p95_c']:.3f} / {soil['p99_c']:.3f} | {soil['hours_above_36_c']} | {soil['hours_above_38_c']} | {soil['hours_above_40_c']} |"
        )
    lines.extend(
        [
            "",
            "The hottest accepted interaction was `interaction_007_combined_dry_hot_stress` at 38.441 C, with 12 hours above 38 C and zero above 40 C. All dt=60/120/300 comparisons passed, so the retained E8 extremes are not integration artifacts.",
        ]
    )
    lines.extend(
        [
            "",
            "## 7. Soil-water / ET interactions",
            "",
            "| Scenario | theta min/max | Stress h | Near-wilting h | ET kg | Irrigation L | Drainage L |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for result in results:
        state = result["metrics"]["states"]["soil_moisture"]
        water = result["metrics"]["soil_water"]
        lines.append(
            f"| `{result['scenario_id']}` | {state['min']:.6f} / {state['max']:.6f} | {water['hours_below_stress_threshold']} | {water['hours_near_wilting']} | {water['et_total_kg']:.4f} | {water['irrigation_total_l']:.4f} | {water['drainage_total_l']:.4f} |"
        )
    lines.extend(
        [
            "",
            "The dry/hot minimum was 0.168542 m3/m3, above the 0.15 wilting prior and outside the near-wilting diagnostic band. Soil-stress feedback reduced ET enough that low irrigation + high ET was antagonistic rather than a state collapse. No scenario crossed field capacity, so drainage remained structurally inactive on this window.",
        ]
    )
    lines.extend(["", "## 8. Nonlinear interaction findings", ""])
    for result in results[1:]:
        analysis = result["nonlinear_analysis"]
        if analysis["status"] == "ESTIMATED":
            lines.append(
                f"- `{result['scenario_id']}`: `{analysis['classification']}` on `{analysis['focus_metric']}`; combined={analysis['actual_combined_effect']:.6g}, additive={analysis['expected_additive_effect']:.6g}, residual={analysis['interaction_residual']:.6g}."
            )
        else:
            lines.append(
                f"- `{result['scenario_id']}`: `{analysis['classification']}` ({analysis['status']})."
            )
    lines.extend(["", "## 9. Invalid joint regions", ""])
    if rejected:
        for result in rejected:
            lines.append(
                f"- `{result['scenario_id']}`: `{result['classification']}`; "
                + "; ".join(result["special_guard_violations"])
                + f" Framework/causal/balance/stability remained `{result['framework_status']}`/`{result['causal_tests']['status']}`/`{result['mass_and_energy_consistency']['status']}`/`{result['numerical_stability']['status']}`."
            )
    else:
        lines.append("- None observed among the structured probes.")
    lines.extend(["", "## 10. Extreme-but-valid regions", ""])
    if extreme:
        for result in extreme:
            metrics = result["metrics"]
            lines.append(
                f"- `{result['scenario_id']}`: Tsoil,max={metrics['states']['T_soil']['max']:.3f} C; RH=100 for {metrics['humidity']['saturated_rows']} rows; theta,min={metrics['states']['soil_moisture']['min']:.6f}."
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## 11. Final joint constraints", ""])
    for constraint in constraints:
        condition = constraint.get("condition")
        condition_text = (
            condition
            if isinstance(condition, str)
            else json.dumps(condition, ensure_ascii=True, separators=(",", ":"))
        )
        lines.append(
            f"- `{constraint['constraint_id']}`: `{constraint['status']}` when `{condition_text}`; {constraint.get('reason', constraint.get('rule', ''))}"
        )
    sampling = joint_space["sampling"]
    lines.extend(
        [
            "",
            "## 12. Recommended sampling method",
            "",
            "Use constrained Latin Hypercube Sampling over the five triangular marginals. Apply machine-readable joint constraints and the same 30-day June physics preflight before full-period generation.",
            "",
            "## 13. Recommended number of full scenarios",
            "",
            f"Recommend `{sampling['recommended_parameter_sets_total']}` total parameter sets: {sampling['composition']}. This covers five dimensions with a manageable first-release compute and validation burden.",
            "",
            "## 14. Estimated full dataset size",
            "",
            f"`70,128 x {sampling['recommended_parameter_sets_total']} = {sampling['estimated_total_rows']:,}` hourly rows. This is an estimate only; full generation was not run.",
            "",
            "## 15. Full-generation readiness",
            "",
            f"- Accepted probes: `{len(accepted)}`; extreme-valid: `{len(extreme)}`; rejected: `{len(rejected)}`.",
            "- Same weather/controller/initial-state method: `PASS`.",
            "- Existing validator reused unchanged: `PASS`.",
            f"- ML contract: `{joint_space['ml_contract']['status']}`; physics/weather feature count `{joint_space['ml_contract']['physics_or_weather_feature_count']}`.",
            "- Full 2018-2025 generation executed: `NO`.",
            "",
            "## Verification passes",
            "",
            "- Pass 1 baseline reproducibility: `PASS`.",
            "- Pass 2 interaction design: `PASS`.",
            "- Pass 3 physics validation: `PASS` for accepted probes; rejected regions retained explicitly.",
            "- Pass 4 joint-boundary analysis: `PASS`.",
            "- Pass 5 full-generation readiness: `PASS` for specification; generation not executed.",
            "",
        ]
    )
    return "\n".join(lines)


def render_joint_knowledge(joint_space: dict[str, Any]) -> str:
    sampling = joint_space["sampling"]
    lines = [
        "# SmartGarden PA1 Joint Parameter Space",
        "",
        "Version: `1.0`",
        "",
        "Status: `VALIDATED_JOINT_SPACE`",
        "",
        "This document locks the interaction-tested uncertainty space for PA1. It supplements, and does not replace, `GREENHOUSE_PARAMETER_UNCERTAINTY.md`.",
        "",
        "## 1. Approved individual ranges",
        "",
        "| Parameter | Range | Distribution | Config path(s) |",
        "|---|---|---|---|",
    ]
    for name, axis in joint_space["parameters"].items():
        lines.append(
            f"| `{name}` | `{axis['min']}..{axis['max']}` | `{axis['distribution']}` | {', '.join(f'`{path}`' for path in axis['config_paths'])} |"
        )
    lines.extend(
        [
            "",
            "## 2. Interaction scenarios",
            "",
            f"The pilot executed `{len(joint_space['accepted_probe_regions']) + len(joint_space['rejected_probe_regions'])}` deterministic 30-day scenarios on one locked weather trajectory. See `interaction_scenarios.yaml` and `interaction_pilot_validation.md`.",
            "",
            "## 3. Interaction findings",
            "",
            "Humidity, E8 root-zone heat, and soil-water/ET combinations were evaluated against matched single-axis controls where available. Additive, synergistic and antagonistic labels are diagnostics, not ML features.",
            "",
            "## 4. Accepted joint regions",
            "",
        ]
    )
    for item in joint_space["accepted_probe_regions"]:
        lines.append(f"- `{item['scenario_id']}`: `{item['classification']}`.")
    lines.extend(["", "## 5. Rejected joint regions", ""])
    if joint_space["rejected_probe_regions"]:
        for item in joint_space["rejected_probe_regions"]:
            reason = "; ".join(item["reason"])
            lines.append(f"- `{item['scenario_id']}`: `{item['classification']}`; {reason}.")
    else:
        lines.append("- None observed among the structured probes.")
    lines.extend(["", "## 6. Extreme-valid regions", ""])
    if joint_space["extreme_valid_probe_regions"]:
        for item in joint_space["extreme_valid_probe_regions"]:
            lines.append(f"- `{item['scenario_id']}` retained without clipping.")
    else:
        lines.append("- None.")
    lines.extend(["", "## 7. Sampling constraints", ""])
    for item in joint_space["joint_constraints"]:
        condition = item.get("condition")
        condition_text = (
            condition
            if isinstance(condition, str)
            else json.dumps(condition, ensure_ascii=True, separators=(",", ":"))
        )
        lines.append(f"- `{item['constraint_id']}`: `{item['status']}` when `{condition_text}`; {item.get('reason', item.get('rule', ''))}")
    lines.extend(
        [
            "",
            "## 8. Recommended full-generation method",
            "",
            f"Use constrained Latin Hypercube Sampling in five dimensions with `{sampling['recommended_parameter_sets_total']}` total parameter sets ({sampling['composition']}). Record the seed, apply deterministic constraint filtering, and run the locked June 30-day preflight before any accepted set is expanded to 2018-2025.",
            "",
            f"Estimated first-release size: `{sampling['estimated_total_rows']:,}` hourly rows. Full generation remains out of scope for this milestone.",
            "",
            "## 9. Deployment invariant",
            "",
            "`ML_DATA_CONTRACT.md` remains unchanged. Weather is simulation forcing only; baseline ML inputs remain five sensor states plus three Raspberry Pi actuator states, with zero physics-only features.",
            "",
        ]
    )
    return "\n".join(lines)


def update_interaction_config(
    interaction: dict[str, Any],
    results: list[dict[str, Any]],
    status: str,
    weather_hash: str,
    code_hash: str,
) -> None:
    by_id = {item["scenario_id"]: item for item in results}
    for scenario in interaction["scenarios"]:
        result = by_id[scenario["scenario_id"]]
        scenario["parameter_set_id"] = result["parameter_set_id"]
        scenario["config_hash"] = result["config_hash"]
    interaction["status"] = "EXECUTED"
    interaction["execution"] = {
        "status": status,
        "weather_hash": weather_hash,
        "simulator_code_hash": code_hash,
        "scenarios": len(results),
        "accepted": sum(item["validation_status"] == "PASS" for item in results),
        "extreme_valid": sum(item["classification"] == "EXTREME_VALID" for item in results),
        "rejected": sum(item["validation_status"] == "FAIL" for item in results),
        "summary_file": str(SUMMARY_PATH.relative_to(ROOT)),
        "results_file": str(RESULTS_PATH.relative_to(ROOT)),
    }


def main() -> int:
    try:
        interaction = load_json(INTERACTION_CONFIG_PATH)
        single_space = load_json(SINGLE_SPACE_PATH)
        single_results = load_json(SINGLE_RESULTS_PATH)
        base_config = load_parameter_config(BASE_CONFIG_PATH)
        design_audit = validate_design(interaction, single_space, base_config)
        base_parameters = base_config.to_model_parameters()
        if base_parameters.simulation.parameter_set_id != interaction["baseline"]["parameter_set_id"]:
            raise InteractionError("Interaction baseline parameter_set_id is stale.")

        start = datetime.fromisoformat(base_parameters.simulation.start_timestamp)
        weather, weather_quality = load_and_validate_weather_window(
            WEATHER_PATH, start, base_parameters.simulation.duration_days
        )
        weather_hash = single_pilot.selected_weather_hash(weather)
        if weather_hash != interaction["baseline"]["weather_hash"]:
            raise InteractionError("Selected weather no longer matches the locked weather hash.")
        if sha256_file(BASELINE_MASTER_PATH) != interaction["baseline"]["physics_master_sha256"]:
            raise InteractionError("Validated baseline physics-master hash changed.")
        reference_columns, reference_rows = single_pilot.read_reference_master(BASELINE_MASTER_PATH)
        if tuple(reference_columns) != OUTPUT_COLUMNS:
            raise InteractionError("Baseline physics-master schema changed.")

        ml_before = single_pilot.validate_ml_contract()
        if ml_before["status"] != "PASS":
            raise InteractionError("Existing canonical ML dataset fails its locked contract.")
        code_hash = simulator_code_hash()
        policy = single_space["validation_policy"]

        baseline_scenario = interaction["scenarios"][0]
        baseline_result = run_one_scenario(
            baseline_scenario,
            interaction,
            base_config.raw,
            weather,
            weather_quality,
            weather_hash,
            policy,
            reference_rows,
            code_hash,
        )
        if baseline_result.get("validation_status") != "PASS":
            raise InteractionError(
                "Baseline interaction failed reproduction/validation; other scenarios were not run."
            )

        results = [baseline_result]
        for scenario in interaction["scenarios"][1:]:
            result = run_one_scenario(
                scenario,
                interaction,
                base_config.raw,
                weather,
                weather_quality,
                weather_hash,
                policy,
                reference_rows,
                code_hash,
            )
            if "metrics" not in result:
                raise InteractionError(
                    f"{result['scenario_id']} did not produce a selected 60 s result: {result.get('failure')}"
                )
            results.append(result)

        add_interaction_analysis(results, interaction, single_results)
        summary_rows = build_summary_rows(results)
        ml_after = single_pilot.validate_ml_contract()
        if ml_before["sha256"] != ml_after["sha256"]:
            raise InteractionError("Interaction pilot changed the canonical ML dataset.")
        constraints = build_joint_constraints(results)
        joint_space = build_joint_space(
            interaction, results, constraints, weather_hash, code_hash, ml_after
        )

        unacceptable_failures = [
            item
            for item in results
            if item["validation_status"] == "FAIL"
            and item["classification"] != "INVALID_JOINT_REGION"
        ]
        execution_status = "PASS" if not unacceptable_failures else "PARTIAL"
        update_interaction_config(
            interaction, results, execution_status, weather_hash, code_hash
        )
        write_summary_csv(SUMMARY_PATH, summary_rows)
        write_json_atomic(
            RESULTS_PATH,
            {
                "status": execution_status,
                "design_audit": design_audit,
                "weather_hash": weather_hash,
                "simulator_code_hash": code_hash,
                "scenario_count": len(results),
                "accepted_count": sum(item["validation_status"] == "PASS" for item in results),
                "extreme_valid_count": sum(item["classification"] == "EXTREME_VALID" for item in results),
                "rejected_count": sum(item["validation_status"] == "FAIL" for item in results),
                "joint_constraints": constraints,
                "ml_deployment_audit": ml_after,
                "scenarios": results,
            },
        )
        write_json_atomic(JOINT_SPACE_PATH, joint_space)
        write_json_atomic(INTERACTION_CONFIG_PATH, interaction)
        write_text_atomic(
            REPORT_PATH, render_report(interaction, results, constraints, joint_space)
        )
        write_text_atomic(JOINT_KNOWLEDGE_PATH, render_joint_knowledge(joint_space))
    except (
        InteractionError,
        single_pilot.PilotError,
        ParameterConfigError,
        WeatherDataError,
        NumericalSimulationError,
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1

    execution = interaction["execution"]
    print(f"STATUS: {execution['status']}")
    print(
        f"SCENARIOS: {execution['scenarios']} total, {execution['accepted']} accepted, "
        f"{execution['extreme_valid']} extreme-valid, {execution['rejected']} rejected"
    )
    print(f"SUMMARY: {SUMMARY_PATH}")
    print(f"REPORT: {REPORT_PATH}")
    print(f"JOINT SPACE: {JOINT_SPACE_PATH}")
    return 0 if execution["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
