"""Generate deterministic constrained-LHS PA1 parameter candidates.

This module owns parameter-space sampling and config derivation only. Physics
preflight is intentionally handled by ``preflight_final_parameter_sets.py``.
"""

from __future__ import annotations

import csv
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import generate_interaction_scenarios as interaction
import generate_pilot_scenarios as pilot
from physics.config import ParameterConfig, ParameterConfigError, load_parameter_config


BASE_CONFIG_PATH = ROOT / "config" / "greenhouse_parameters.yaml"
JOINT_SPACE_PATH = ROOT / "joint_parameter_space.yaml"
OUTPUT_DIR = ROOT / "outputs" / "final_parameter_preflight"
PENDING_CONFIG_DIR = OUTPUT_DIR / "pending_configs"
CANDIDATE_MANIFEST_PATH = ROOT / "final_parameter_candidates.csv"
SAMPLING_DESIGN_PATH = OUTPUT_DIR / "sampling_design.json"
COVERAGE_PATH = OUTPUT_DIR / "sampling_coverage.json"

SAMPLING_METHOD = "constrained_latin_hypercube_sampling"
SAMPLING_VERSION = "pa1_constrained_lhs_v1"
SAMPLING_SEED = 20260816
LHS_BATCH_SIZE = 23
REQUESTED_NON_BASELINE = 23

AXES = ("C_d", "eta_s", "C_s", "irrigation_flow_L_h", "ET_scale")
CONFIG_PATHS = {
    "C_d": ("ventilation.discharge_coefficient",),
    "eta_s": ("soil_thermal.solar_absorption_fraction",),
    "C_s": ("soil_thermal.effective_heat_capacity_j_k",),
    "irrigation_flow_L_h": ("irrigation.effective_flow_m3_s",),
    "ET_scale": (
        "crop.transpiration_radiation_coefficient",
        "crop.transpiration_vpd_coefficient",
    ),
}

CANDIDATE_COLUMNS = (
    "candidate_id",
    "parameter_set_id",
    "final_parameter_set_id",
    "sampling_index",
    "raw_candidate_index",
    "lhs_batch",
    "lhs_row",
    "sampling_seed",
    "sampling_method",
    "sampling_version",
    "is_baseline",
    "C_d",
    "eta_s",
    "C_s_J_K",
    "irrigation_flow_L_h",
    "ET_scale",
    "u_C_d",
    "u_eta_s",
    "u_C_s",
    "u_irrigation_flow_L_h",
    "u_ET_scale",
    "stratum_C_d",
    "stratum_eta_s",
    "stratum_C_s",
    "stratum_irrigation_flow_L_h",
    "stratum_ET_scale",
    "config_hash",
    "joint_constraint_pass",
    "violated_constraints",
    "preflight_status",
    "classification",
    "reason",
)


class SamplingError(RuntimeError):
    """Raised when parameter-space or deterministic-sampling invariants fail."""


def triangular_inverse_cdf(
    probability: float, minimum: float, mode: float, maximum: float
) -> float:
    """Map a unit quantile to a triangular distribution without dependencies."""

    if not 0.0 <= probability <= 1.0:
        raise ValueError("Triangular probability must be in [0, 1].")
    if not minimum <= mode <= maximum or minimum == maximum:
        raise ValueError("Triangular bounds must satisfy min <= mode <= max.")
    if probability == 0.0:
        return minimum
    if probability == 1.0:
        return maximum
    width = maximum - minimum
    mode_fraction = (mode - minimum) / width
    if probability < mode_fraction:
        return minimum + math.sqrt(
            probability * width * (mode - minimum)
        )
    return maximum - math.sqrt(
        (1.0 - probability) * width * (maximum - mode)
    )


def _batch_seed(seed: int, batch_index: int) -> int:
    payload = f"{SAMPLING_VERSION}:{seed}:{batch_index}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def validate_joint_space(joint_space: dict[str, Any]) -> None:
    if joint_space.get("status") != "VALIDATED_JOINT_SPACE":
        raise SamplingError("Joint parameter space is not validated.")
    parameters = joint_space.get("parameters")
    if not isinstance(parameters, dict) or tuple(parameters) != AXES:
        raise SamplingError("Joint space must expose the five locked axes in order.")
    for name in AXES:
        axis = parameters[name]
        if axis.get("distribution") != "triangular":
            raise SamplingError(f"{name} is not configured as triangular.")
        minimum = float(axis["min"])
        mode = float(axis["mode"])
        maximum = float(axis["max"])
        if not minimum <= mode <= maximum or minimum == maximum:
            raise SamplingError(f"{name} has invalid triangular bounds.")
        if tuple(axis["config_paths"]) != CONFIG_PATHS[name]:
            raise SamplingError(f"{name} config mapping differs from the locked mapping.")


def _lhs_batch(
    joint_space: dict[str, Any], seed: int, batch_index: int
) -> list[dict[str, Any]]:
    rng = random.Random(_batch_seed(seed, batch_index))
    quantiles: dict[str, list[float]] = {}
    strata: dict[str, list[int]] = {}
    for name in AXES:
        permutation = list(range(LHS_BATCH_SIZE))
        rng.shuffle(permutation)
        strata[name] = permutation
        quantiles[name] = [
            (stratum + rng.random()) / LHS_BATCH_SIZE
            for stratum in permutation
        ]

    rows: list[dict[str, Any]] = []
    for row_index in range(LHS_BATCH_SIZE):
        parameters: dict[str, float] = {}
        row_quantiles: dict[str, float] = {}
        row_strata: dict[str, int] = {}
        for name in AXES:
            axis = joint_space["parameters"][name]
            probability = quantiles[name][row_index]
            parameters[name] = triangular_inverse_cdf(
                probability,
                float(axis["min"]),
                float(axis["mode"]),
                float(axis["max"]),
            )
            row_quantiles[name] = probability
            row_strata[name] = strata[name][row_index]
        rows.append(
            {
                "raw_candidate_index": batch_index * LHS_BATCH_SIZE + row_index + 1,
                "lhs_batch": batch_index,
                "lhs_row": row_index,
                "parameters": parameters,
                "quantiles": row_quantiles,
                "strata": row_strata,
            }
        )
    return rows


def iter_lhs_candidates(
    joint_space: dict[str, Any], seed: int = SAMPLING_SEED
) -> Iterator[dict[str, Any]]:
    validate_joint_space(joint_space)
    batch_index = 0
    while True:
        yield from _lhs_batch(joint_space, seed, batch_index)
        batch_index += 1


def _comparison(left: float, operator: str, right: float) -> bool:
    if operator == "<":
        return left < right
    if operator == "<=":
        return left <= right
    if operator == ">":
        return left > right
    if operator == ">=":
        return left >= right
    if operator == "==":
        return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-12)
    raise SamplingError(f"Unsupported joint-constraint operator: {operator!r}")


def condition_matches(condition: Any, parameters: dict[str, float]) -> bool:
    if isinstance(condition, dict) and "all" in condition:
        return all(condition_matches(item, parameters) for item in condition["all"])
    if isinstance(condition, dict) and "any" in condition:
        return any(condition_matches(item, parameters) for item in condition["any"])
    if not isinstance(condition, dict):
        raise SamplingError(f"Unsupported machine constraint: {condition!r}")
    name = str(condition["parameter"])
    if name not in parameters:
        raise SamplingError(f"Constraint references unknown parameter {name!r}.")
    return _comparison(
        float(parameters[name]),
        str(condition["operator"]),
        float(condition["value"]),
    )


def evaluate_joint_constraints(
    parameters: dict[str, float], joint_space: dict[str, Any]
) -> tuple[bool, list[str]]:
    violations: list[str] = []
    for constraint in joint_space["joint_constraints"]:
        if not str(constraint.get("status", "")).startswith("REJECT"):
            continue
        if condition_matches(constraint["condition"], parameters):
            violations.append(str(constraint["constraint_id"]))
    return not violations, violations


def official_baseline_values(
    base_config: ParameterConfig, joint_space: dict[str, Any]
) -> dict[str, float]:
    model = base_config.to_model_parameters()
    values = {
        "C_d": model.ventilation.discharge_coefficient,
        "eta_s": model.soil_thermal.solar_absorption_fraction,
        "C_s": model.soil_thermal.effective_heat_capacity_j_k,
        "irrigation_flow_L_h": 10.0,
        "ET_scale": 1.0,
    }
    for name, value in values.items():
        expected = float(joint_space["parameters"][name]["baseline"])
        if not math.isclose(value, expected, rel_tol=0.0, abs_tol=1e-12):
            raise SamplingError(
                f"Baseline config and joint space disagree for {name}: {value} != {expected}."
            )
    return values


def build_parameter_config(
    base_raw: dict[str, Any],
    values: dict[str, float],
    parameter_set_id: str,
    candidate_id: str,
    sampling_index: int,
    raw_candidate_index: int,
    seed: int = SAMPLING_SEED,
) -> tuple[dict[str, Any], ParameterConfig, str]:
    """Derive one simulator config while preserving every non-approved value."""

    raw = deepcopy(base_raw)

    def apply(path: str, value: float) -> None:
        pilot.set_value(raw, path, float(value))

    apply(CONFIG_PATHS["C_d"][0], values["C_d"])
    apply(CONFIG_PATHS["eta_s"][0], values["eta_s"])
    apply(CONFIG_PATHS["C_s"][0], values["C_s"])
    if math.isclose(values["irrigation_flow_L_h"], 10.0, abs_tol=1e-12):
        irrigation_m3_s = float(
            pilot.get_record(base_raw, CONFIG_PATHS["irrigation_flow_L_h"][0])["value"]
        )
    else:
        irrigation_m3_s = values["irrigation_flow_L_h"] / 3_600_000.0
    apply(CONFIG_PATHS["irrigation_flow_L_h"][0], irrigation_m3_s)
    for path in CONFIG_PATHS["ET_scale"]:
        baseline = float(pilot.get_record(base_raw, path)["value"])
        apply(path, baseline * values["ET_scale"])

    raw["scenario"] = {
        "candidate_id": {
            "value": candidate_id,
            "unit": "identifier",
            "provenance": "CONSTRAINED_LHS",
            "status": "DETERMINISTIC_FINAL_PREFLIGHT",
            "source": "joint_parameter_space.yaml",
        },
        "sampling_index": {
            "value": sampling_index,
            "unit": "integer",
            "provenance": "CONSTRAINED_LHS",
            "status": "RECORDED",
            "source": SAMPLING_VERSION,
        },
        "raw_candidate_index": {
            "value": raw_candidate_index,
            "unit": "integer",
            "provenance": "CONSTRAINED_LHS",
            "status": "RECORDED",
            "source": SAMPLING_VERSION,
        },
        "sampling_seed": {
            "value": seed,
            "unit": "integer",
            "provenance": "CONSTRAINED_LHS",
            "status": "FIXED_REPRODUCIBILITY_SEED",
            "source": SAMPLING_VERSION,
        },
    }
    pilot.set_value(raw, "identity.parameter_set_id", parameter_set_id)
    pilot.set_value(raw, "identity.simulation_id", f"{candidate_id}_june2024_preflight")
    config = ParameterConfig(raw, BASE_CONFIG_PATH)
    config_hash = pilot.canonical_hash(pilot.model_value_payload(config))
    return raw, config, config_hash


def _manifest_row(
    sample: dict[str, Any],
    config_hash: str,
    joint_pass: bool,
    violations: list[str],
    sampling_index: int,
) -> dict[str, Any]:
    parameters = sample["parameters"]
    raw_index = int(sample["raw_candidate_index"])
    candidate_id = f"lhs_candidate_{raw_index:06d}"
    return {
        "candidate_id": candidate_id,
        "parameter_set_id": f"pa1_candidate_{raw_index:06d}",
        "final_parameter_set_id": "",
        "sampling_index": sampling_index,
        "raw_candidate_index": raw_index,
        "lhs_batch": sample["lhs_batch"],
        "lhs_row": sample["lhs_row"],
        "sampling_seed": SAMPLING_SEED,
        "sampling_method": SAMPLING_METHOD,
        "sampling_version": SAMPLING_VERSION,
        "is_baseline": False,
        "C_d": parameters["C_d"],
        "eta_s": parameters["eta_s"],
        "C_s_J_K": parameters["C_s"],
        "irrigation_flow_L_h": parameters["irrigation_flow_L_h"],
        "ET_scale": parameters["ET_scale"],
        **{f"u_{name}": sample["quantiles"][name] for name in AXES},
        **{f"stratum_{name}": sample["strata"][name] for name in AXES},
        "config_hash": config_hash,
        "joint_constraint_pass": joint_pass,
        "violated_constraints": " | ".join(violations),
        "preflight_status": "PENDING" if joint_pass else "REJECTED_JOINT_CONSTRAINT",
        "classification": "PENDING" if joint_pass else "REJECTED_JOINT_CONSTRAINT",
        "reason": "" if joint_pass else "Known machine-readable joint constraint matched.",
    }


def baseline_manifest_row(
    values: dict[str, float], config_hash: str
) -> dict[str, Any]:
    row = {column: "" for column in CANDIDATE_COLUMNS}
    row.update(
        {
            "candidate_id": "parameter_set_000_baseline",
            "parameter_set_id": "pa1_full_000_baseline",
            "final_parameter_set_id": "pa1_full_000_baseline",
            "sampling_index": 0,
            "raw_candidate_index": 0,
            "lhs_batch": -1,
            "lhs_row": -1,
            "sampling_seed": SAMPLING_SEED,
            "sampling_method": SAMPLING_METHOD,
            "sampling_version": SAMPLING_VERSION,
            "is_baseline": True,
            "C_d": values["C_d"],
            "eta_s": values["eta_s"],
            "C_s_J_K": values["C_s"],
            "irrigation_flow_L_h": values["irrigation_flow_L_h"],
            "ET_scale": values["ET_scale"],
            "config_hash": config_hash,
            "joint_constraint_pass": True,
            "preflight_status": "PENDING",
            "classification": "PENDING",
        }
    )
    return row


def generate_sampling_design(
    joint_space: dict[str, Any], base_config: ParameterConfig
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Return baseline + attempts, retained pending rows, and sampler metadata."""

    validate_joint_space(joint_space)
    baseline_values = official_baseline_values(base_config, joint_space)
    baseline_raw, _, baseline_hash = build_parameter_config(
        base_config.raw,
        baseline_values,
        "pa1_full_000_baseline",
        "parameter_set_000_baseline",
        0,
        0,
    )
    attempts = [baseline_manifest_row(baseline_values, baseline_hash)]
    retained = [attempts[0]]
    pending_configs: dict[str, dict[str, Any]] = {
        "pa1_full_000_baseline": baseline_raw
    }

    sampling_index = 0
    stream = iter_lhs_candidates(joint_space, SAMPLING_SEED)
    while sampling_index < REQUESTED_NON_BASELINE:
        sample = next(stream)
        joint_pass, violations = evaluate_joint_constraints(
            sample["parameters"], joint_space
        )
        raw_index = int(sample["raw_candidate_index"])
        parameter_set_id = f"pa1_candidate_{raw_index:06d}"
        candidate_id = f"lhs_candidate_{raw_index:06d}"
        raw, _, config_hash = build_parameter_config(
            base_config.raw,
            sample["parameters"],
            parameter_set_id,
            candidate_id,
            sampling_index + 1 if joint_pass else -1,
            raw_index,
        )
        row = _manifest_row(
            sample,
            config_hash,
            joint_pass,
            violations,
            sampling_index + 1 if joint_pass else -1,
        )
        attempts.append(row)
        if joint_pass:
            sampling_index += 1
            retained.append(row)
            pending_configs[parameter_set_id] = raw

    metadata = {
        "sampling_method": SAMPLING_METHOD,
        "sampling_version": SAMPLING_VERSION,
        "sampling_seed": SAMPLING_SEED,
        "dimensions": len(AXES),
        "lhs_batch_size": LHS_BATCH_SIZE,
        "requested_non_baseline": REQUESTED_NON_BASELINE,
        "raw_candidates_generated": len(attempts) - 1,
        "joint_constraint_rejects": sum(
            row["preflight_status"] == "REJECTED_JOINT_CONSTRAINT"
            for row in attempts
        ),
        "joint_valid_retained": len(retained) - 1,
        "next_raw_candidate_index": max(
            int(row["raw_candidate_index"]) for row in attempts
        )
        + 1,
        "pending_configs": pending_configs,
    }
    return attempts, retained, metadata


def _percentile(values: list[float], probability: float) -> float:
    return interaction.percentile(values, probability)


def _correlation(left: list[float], right: list[float]) -> float:
    left_mean = statistics.fmean(left)
    right_mean = statistics.fmean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    denominator = math.sqrt(
        sum((value - left_mean) ** 2 for value in left)
        * sum((value - right_mean) ** 2 for value in right)
    )
    return numerator / denominator if denominator else 0.0


def coverage_audit(
    retained: list[dict[str, Any]], joint_space: dict[str, Any]
) -> dict[str, Any]:
    lhs_rows = [row for row in retained if not row["is_baseline"]]
    if len(lhs_rows) != REQUESTED_NON_BASELINE:
        raise SamplingError("Coverage audit requires exactly 23 LHS candidates.")
    statistics_by_axis: dict[str, Any] = {}
    for name in AXES:
        column = "C_s_J_K" if name == "C_s" else name
        values = [float(row[column]) for row in lhs_rows]
        axis = joint_space["parameters"][name]
        unique_strata = len({int(row[f"stratum_{name}"]) for row in lhs_rows})
        statistics_by_axis[name] = {
            "min": min(values),
            "max": max(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "std_population": statistics.pstdev(values),
            "p05": _percentile(values, 0.05),
            "p25": _percentile(values, 0.25),
            "p75": _percentile(values, 0.75),
            "p95": _percentile(values, 0.95),
            "normalized_range_coverage": (
                max(values) - min(values)
            )
            / (float(axis["max"]) - float(axis["min"])),
            "unique_lhs_strata": unique_strata,
            "expected_strata": LHS_BATCH_SIZE,
        }

    pairs = (
        ("C_d", "ET_scale"),
        ("C_d", "irrigation_flow_L_h"),
        ("eta_s", "C_s"),
        ("irrigation_flow_L_h", "ET_scale"),
    )
    pairwise: dict[str, Any] = {}
    for left_name, right_name in pairs:
        left_column = "C_s_J_K" if left_name == "C_s" else left_name
        right_column = "C_s_J_K" if right_name == "C_s" else right_name
        left = [float(row[left_column]) for row in lhs_rows]
        right = [float(row[right_column]) for row in lhs_rows]
        left_median = statistics.median(left)
        right_median = statistics.median(right)
        quadrants = {
            "low_low": sum(a <= left_median and b <= right_median for a, b in zip(left, right)),
            "low_high": sum(a <= left_median and b > right_median for a, b in zip(left, right)),
            "high_low": sum(a > left_median and b <= right_median for a, b in zip(left, right)),
            "high_high": sum(a > left_median and b > right_median for a, b in zip(left, right)),
        }
        pairwise[f"{left_name}_x_{right_name}"] = {
            "pearson_correlation": _correlation(left, right),
            "median_quadrant_occupancy": quadrants,
            "occupied_quadrants": sum(value > 0 for value in quadrants.values()),
        }
    return {
        "status": "PASS",
        "candidate_count": len(lhs_rows),
        "axes": statistics_by_axis,
        "pairwise": pairwise,
    }


def write_csv_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CANDIDATE_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_sampling_outputs(
    attempts: list[dict[str, Any]],
    retained: list[dict[str, Any]],
    metadata: dict[str, Any],
    joint_space: dict[str, Any],
) -> None:
    write_csv_atomic(CANDIDATE_MANIFEST_PATH, attempts)
    for parameter_set_id, raw in metadata["pending_configs"].items():
        pilot.write_json_atomic(PENDING_CONFIG_DIR / f"{parameter_set_id}.yaml", raw)
    coverage = coverage_audit(retained, joint_space)
    design = {
        key: value for key, value in metadata.items() if key != "pending_configs"
    }
    design.update(
        {
            "joint_space_file": str(JOINT_SPACE_PATH.relative_to(ROOT)),
            "joint_space_sha256": pilot.sha256_file(JOINT_SPACE_PATH),
            "baseline_config_file": str(BASE_CONFIG_PATH.relative_to(ROOT)),
            "baseline_config_sha256": pilot.sha256_file(BASE_CONFIG_PATH),
            "candidate_manifest": str(CANDIDATE_MANIFEST_PATH.relative_to(ROOT)),
            "candidate_manifest_sha256": pilot.sha256_file(CANDIDATE_MANIFEST_PATH),
            "coverage_file": str(COVERAGE_PATH.relative_to(ROOT)),
            "preflight_status": "PENDING",
        }
    )
    pilot.write_json_atomic(COVERAGE_PATH, coverage)
    pilot.write_json_atomic(SAMPLING_DESIGN_PATH, design)


def main() -> int:
    try:
        joint_space = pilot.load_json(JOINT_SPACE_PATH)
        base_config = load_parameter_config(BASE_CONFIG_PATH)
        attempts, retained, metadata = generate_sampling_design(
            joint_space, base_config
        )
        write_sampling_outputs(attempts, retained, metadata, joint_space)
    except (
        SamplingError,
        pilot.PilotError,
        ParameterConfigError,
        OSError,
        ValueError,
        KeyError,
    ) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1

    print("STATUS: PENDING_PREFLIGHT")
    print(f"RAW CANDIDATES: {metadata['raw_candidates_generated']}")
    print(f"JOINT REJECTS: {metadata['joint_constraint_rejects']}")
    print(f"RETAINED: {metadata['joint_valid_retained']} non-baseline + 1 baseline")
    print(f"MANIFEST: {CANDIDATE_MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
