"""Run and validate the SmartGarden Physics Simulator V1 for 30 days."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from physics.config import ParameterConfigError, load_parameter_config
from physics.simulator import (
    NumericalSimulationError,
    WeatherDataError,
    load_and_validate_weather_window,
    run_simulation,
    write_simulation_csv,
)
from physics.validation import (
    build_verification_passes,
    conservation_audit,
    initial_state_report,
    run_causal_tests,
    stability_comparison,
    summarize_states,
    validate_output_ranges,
)


CONFIG_PATH = ROOT / "config" / "greenhouse_parameters.yaml"
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
OUTPUT_DIR = ROOT / "outputs"
CSV_OUTPUT = OUTPUT_DIR / "greenhouse_simulation_30days.csv"
REPORT_OUTPUT = OUTPUT_DIR / "greenhouse_simulation_30days_validation.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _calibration_list(records: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    pending: list[dict[str, Any]] = []
    for path, record in records.items():
        status = str(record["status"])
        if "TO_" in status or "INITIAL_PRIOR" in status:
            pending.append(
                {
                    "parameter": path,
                    "value": record["value"],
                    "unit": record["unit"],
                    "provenance": record["provenance"],
                    "status": status,
                    "source": record["source"],
                }
            )
    return pending


def main() -> int:
    overall_started = time.perf_counter()
    try:
        parameter_config = load_parameter_config(CONFIG_PATH)
        parameters = parameter_config.to_model_parameters()
        start = datetime.fromisoformat(parameters.simulation.start_timestamp)
        weather, weather_quality = load_and_validate_weather_window(
            WEATHER_PATH, start, parameters.simulation.duration_days
        )
    except (ParameterConfigError, WeatherDataError, OSError) as exc:
        failure_report = {
            "status": "FAILED",
            "failure_stage": "input_validation",
            "error": str(exc),
            "config_path": str(CONFIG_PATH),
            "weather_path": str(WEATHER_PATH),
        }
        _write_json_atomic(REPORT_OUTPUT, failure_report)
        print(f"STATUS: FAILED\nInput validation error: {exc}")
        return 1

    simulation_results = {}
    stability_errors: dict[int, str] = {}
    for timestep in (60, 120, 300):
        try:
            simulation_results[timestep] = run_simulation(
                weather,
                parameters,
                internal_timestep_s=timestep,
                weather_quality=weather_quality,
            )
        except (NumericalSimulationError, ValueError, OverflowError) as exc:
            stability_errors[timestep] = str(exc)

    selected_dt = parameters.simulation.internal_timestep_s
    selected_result = simulation_results.get(selected_dt)
    stability = stability_comparison(
        simulation_results, stability_errors, parameters
    )
    causal_tests = run_causal_tests(parameters)

    if selected_result is None:
        failure_report = {
            "status": "FAILED",
            "failure_stage": "selected_timestep_simulation",
            "weather_quality": weather_quality,
            "causal_tests": causal_tests,
            "numerical_stability": stability,
            "errors": stability_errors,
            "parameters_still_to_calibrate": _calibration_list(
                parameter_config.records()
            ),
        }
        _write_json_atomic(REPORT_OUTPUT, failure_report)
        print("STATUS: FAILED\nSelected 60 s simulation did not complete.")
        return 1

    output_validation = validate_output_ranges(selected_result, parameters)
    conservation = conservation_audit(selected_result, parameters)
    verification_passes = build_verification_passes(
        parameter_config,
        output_validation,
        causal_tests,
        conservation,
        stability,
    )
    all_passes = all(
        value["status"] == "PASS" for value in verification_passes.values()
    )
    success = (
        weather_quality["status"] == "PASS"
        and output_validation["status"] == "PASS"
        and causal_tests["status"] == "PASS"
        and conservation["status"] == "PASS"
        and stability["status"] == "PASS"
        and all_passes
    )
    status = "SUCCESS" if success else "PARTIAL"

    warnings = list(selected_result.warnings)
    warnings.append(
        "Grow-light radiant/heat/lux values are explicit V1 priors and are not sensor-calibrated."
    )
    warnings.append(
        "External Open-Meteo soil variables are retained only as context; E8/E9 use independent greenhouse states."
    )
    warnings.append(
        "Hourly Open-Meteo solar radiation is treated as an hourly forcing and linearly interpolated with a nonnegative floor."
    )
    state_summary = summarize_states(selected_result.rows)
    if state_summary["soil_temperature_inside_true"]["max"] > 45.0:
        warnings.append(
            "Effective root-zone temperature exceeds 45 degC in this prior-only V1 run; "
            "calibrate soil thermal capacity, solar absorption, and thermal-base loss "
            "before interpreting magnitudes as prototype truth."
        )
    if stability_errors:
        warnings.append(
            f"Rejected stability runs: {stability_errors}"
        )
    for timestep, comparison in stability["comparisons"].items():
        if comparison["status"] == "SENSITIVE_OR_UNSTABLE":
            warnings.append(
                f"dt={timestep}s was sensitive and was not selected."
            )

    report = {
        "status": status,
        "scientific_model": (
            "Reduced-order coupled greenhouse physics E0-E10; equations are mapped "
            "to GREENHOUSE_PHYSICS_DATASET_KNOWLEDGE.md."
        ),
        "simulation": {
            "window_start": selected_result.rows[0]["timestamp"],
            "window_end_inclusive": selected_result.rows[-1]["timestamp"],
            "integration_end_exclusive": weather[-1].timestamp,
            "rows": len(selected_result.rows),
            "internal_timestep_s": selected_result.internal_timestep_s,
            "output_interval_s": parameters.simulation.output_interval_s,
            "runtime_selected_seconds": selected_result.runtime_seconds,
            "runtime_all_validation_seconds": time.perf_counter()
            - overall_started,
            "weather_interpolation": parameters.simulation.weather_interpolation,
            "actuator_interpolation": "piecewise_constant_per_internal_step",
            "simulation_id": parameters.simulation.simulation_id,
            "parameter_set_id": parameters.simulation.parameter_set_id,
        },
        "initial_state": initial_state_report(selected_result, parameters),
        "final_state_at_exclusive_end": asdict(selected_result.final_state),
        "state_summary": state_summary,
        "weather_quality": weather_quality,
        "range_checks": output_validation,
        "causal_tests": causal_tests,
        "mass_and_energy_consistency": conservation,
        "numerical_stability": stability,
        "verification_passes": verification_passes,
        "sensor_model": {
            "noise_enabled": parameters.simulation.sensor_noise_enabled,
            "true_state_mutated_by_sensor_noise": False,
            "soil_sensor_mapping": "NOT_EMITTED_PENDING_CALIBRATION",
        },
        "parameter_config": str(CONFIG_PATH.relative_to(ROOT)),
        "parameter_provenance": parameter_config.records(),
        "parameters_still_to_calibrate": _calibration_list(
            parameter_config.records()
        ),
        "warnings": warnings,
        "output_files": {
            "csv": str(CSV_OUTPUT.relative_to(ROOT)),
            "validation_report": str(REPORT_OUTPUT.relative_to(ROOT)),
        },
    }

    if success:
        write_simulation_csv(CSV_OUTPUT, selected_result.rows)
    _write_json_atomic(REPORT_OUTPUT, report)

    print(f"STATUS: {status}")
    print(
        f"SIMULATION: {report['simulation']['window_start']} through "
        f"{report['simulation']['window_end_inclusive']}, "
        f"{report['simulation']['rows']} rows, dt={selected_dt}s"
    )
    print(
        "VALIDATION: "
        f"ranges={output_validation['status']}, "
        f"causal={causal_tests['status']}, "
        f"balances={conservation['status']}, "
        f"stability={stability['status']}"
    )
    print(f"REPORT: {REPORT_OUTPUT}")
    if success:
        print(f"CSV: {CSV_OUTPUT}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
