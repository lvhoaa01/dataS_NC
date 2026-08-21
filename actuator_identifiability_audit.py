"""Deterministic actuator-support diagnostics for the greenhouse ML dataset.

This module performs descriptive data auditing only.  It deliberately contains
no forecasting model, optimizer, training loop, or causal-effect estimator.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


ACTUATORS = ("pump_state", "fan_state", "grow_light_state")
SENSORS = (
    "air_temperature",
    "air_humidity",
    "soil_temperature",
    "soil_moisture",
    "light_lux",
)
FEATURES = SENSORS + ACTUATORS
HORIZONS = (1, 3)
SPLITS = ("TRAIN", "VALIDATION")
JOINT_CODES = tuple(f"{value:03b}" for value in range(8))

METRIC_FILENAMES = (
    "actuator_usage_summary.csv",
    "actuator_transition_summary.csv",
    "actuator_dwell_time_summary.csv",
    "joint_action_coverage.csv",
    "state_conditioned_action_overlap.csv",
    "actuator_transition_response.csv",
    "clean_transition_response.csv",
    "matched_response_diagnostic.csv",
    "actuator_confounding_diagnostics.csv",
    "actuator_support_by_scenario.csv",
    "no_change_reference_summary.csv",
    "train_validation_actuator_shift.csv",
)

PLOT_FILENAMES = (
    "actuator_on_fraction.png",
    "actuator_transition_counts.png",
    "actuator_dwell_times.png",
    "joint_action_coverage.png",
    "state_overlap_summary.png",
    "transition_response_1h.png",
    "transition_response_3h.png",
    "confounding_diagnostics.png",
)

RESPONSE_COLUMNS = (
    "split",
    "actuator",
    "direction",
    "horizon_h",
    "target",
    "count",
    "mean",
    "std",
    "median",
    "p10",
    "p25",
    "p75",
    "p90",
    "unit",
)

TARGET_UNITS = {
    "air_temperature": "degC",
    "air_humidity": "percent_RH",
    "soil_temperature": "degC",
    "soil_moisture": "m3_m3",
    "light_lux": "lux",
}

OVERLAP_VARIABLES = {
    "pump_state": ("soil_moisture", "air_temperature", "air_humidity"),
    "fan_state": ("air_temperature", "air_humidity"),
    "grow_light_state": ("light_lux", "hour_of_day"),
}


@dataclass(frozen=True)
class AuditConfig:
    """Centralized, explicitly non-universal audit heuristics."""

    seed: int = 20_260_816
    quantile_bins: int = 4
    rare_on_fraction: float = 0.01
    minimum_transition_events: int = 20
    minimum_clean_events: int = 10
    minimum_sample_weighted_overlap: float = 0.10
    smoke_train_hours: int = 24 * 21
    smoke_validation_hours: int = 24 * 14
    matching_max_events_per_group_full: int = 500
    matching_max_references_per_stratum_full: int = 1_000
    matching_max_events_per_group_smoke: int = 24
    matching_max_references_per_stratum_smoke: int = 96

    def as_dict(self) -> dict[str, Any]:
        result = dict(self.__dict__)
        result["heuristic_scope"] = "AUDIT_HEURISTIC_NOT_UNIVERSAL_THRESHOLD"
        return result


def parse_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Cannot parse boolean value: {value!r}")


def sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_binary_actuators(frame: pd.DataFrame) -> None:
    missing = set(ACTUATORS).difference(frame.columns)
    if missing:
        raise ValueError(f"Missing actuator columns: {sorted(missing)}")
    for actuator in ACTUATORS:
        values = set(pd.unique(frame[actuator].dropna()))
        if not values.issubset({0, 1, 0.0, 1.0}):
            raise ValueError(f"{actuator} is not binary: {sorted(values)}")
        if frame[actuator].isna().any():
            raise ValueError(f"{actuator} contains missing values")


def validate_scenario_frame(frame: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    if tuple(frame.columns) != ("timestamp",) + FEATURES:
        raise ValueError(
            f"{scenario_id}: canonical ML schema mismatch: {tuple(frame.columns)}"
        )
    result = frame.copy()
    result["timestamp"] = pd.to_datetime(result["timestamp"], errors="raise")
    if result["timestamp"].duplicated().any():
        raise ValueError(f"{scenario_id}: duplicate timestamps")
    differences = result["timestamp"].diff().dropna()
    if not differences.eq(pd.Timedelta(hours=1)).all():
        raise ValueError(f"{scenario_id}: timestamps are not continuous hourly")
    numeric = result.loc[:, FEATURES].to_numpy(dtype=np.float64)
    if not np.isfinite(numeric).all():
        raise ValueError(f"{scenario_id}: NaN/Inf in canonical ML values")
    validate_binary_actuators(result)
    result.loc[:, ACTUATORS] = result.loc[:, ACTUATORS].astype(np.int8)
    return result


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_locked_split(
    split_manifest_path: Path,
    preprocessing_config_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    split_manifest = load_json(split_manifest_path)
    preprocessing_config = load_json(preprocessing_config_path)
    development = split_manifest.get("development_scenario_ids", [])
    held_out = split_manifest.get("held_out_scenario_ids", [])
    if len(development) != 20 or len(held_out) != 4:
        raise ValueError("Locked split must contain 20 development and 4 held-out IDs")
    if set(development) & set(held_out):
        raise ValueError("Development and held-out scenario IDs overlap")
    if tuple(preprocessing_config.get("feature_columns", [])) != FEATURES:
        raise ValueError("Preprocessing feature contract is not the canonical 8-vector")
    if tuple(preprocessing_config.get("target_columns", [])) != SENSORS:
        raise ValueError("Preprocessing target contract is not the canonical 5-vector")
    if tuple(split_manifest.get("train_date_range", [])) != (
        "2018-01-01 00:00:00",
        "2023-12-31 23:00:00",
    ):
        raise ValueError("Locked TRAIN range changed")
    if tuple(split_manifest.get("validation_date_range", [])) != (
        "2024-01-01 00:00:00",
        "2024-12-31 23:00:00",
    ):
        raise ValueError("Locked VALIDATION range changed")
    return split_manifest, preprocessing_config


def trace_actuator_temporal_semantics(
    simulator_path: Path,
    parameter_config_path: Path,
) -> dict[str, Any]:
    """Trace the sampled-control timing contract from source and configuration."""

    simulator_text = simulator_path.read_text(encoding="utf-8")
    raw_config = json.loads(parameter_config_path.read_text(encoding="utf-8"))
    required_markers = (
        "start_controls = actuator_schedule(hour_start, state, left, parameters)",
        "state_at_hour_start = state",
        "controls = actuator_schedule(",
        "state, step_balances, condensed_kg = rk4_step(",
        "state_at_hour_start,",
        "start_controls,",
    )
    controls = raw_config["controls"]
    pump_starts = list(controls["pump_pulse_start_seconds"]["value"])
    pump_duration = int(controls["pump_pulse_duration_s"]["value"])
    fan_on_temperature = float(controls["fan_on_temperature_c"]["value"])
    fan_minimum_delta = float(
        controls["fan_minimum_cooling_delta_c"]["value"]
    )
    grow_light_state = int(controls["grow_light_baseline_state"]["value"])
    verified = all(marker in simulator_text for marker in required_markers)
    verified = verified and pump_duration > 0 and grow_light_state in {0, 1}
    return {
        "verified": bool(verified),
        "source_file": str(simulator_path),
        "source_sha256": sha256_file(simulator_path),
        "parameter_config": str(parameter_config_path),
        "parameter_config_sha256": sha256_file(parameter_config_path),
        "functions": [
            "actuator_schedule",
            "run_simulation",
            "rk4_step",
            "_build_output_row",
        ],
        "update_order": (
            "evaluate controller and diagnostics from state[t] at the hour boundary; "
            "save those boundary values; integrate the following hour with controls "
            "re-evaluated at every internal substep; emit the saved boundary row"
        ),
        "action_timing": (
            "action[t] is the controller command sampled exactly at timestamp t and "
            "is applied to the first internal substep. It is not guaranteed to remain "
            "constant over [t,t+1h), because the controller is re-evaluated every 60 s."
        ),
        "sensor_timing": (
            "sensor-like physics true states in row t describe the state at the start "
            "of hour t, before integration of [t,t+1h)"
        ),
        "transition_interpretation": (
            "action[t-1] != action[t] is a change in the hourly sampled boundary "
            "command; sensor[t+h]-sensor[t] is a descriptive post-transition response"
        ),
        "pump_policy": {
            "pulse_start_seconds": pump_starts,
            "pulse_duration_s": pump_duration,
            "hourly_sampling_caveat": (
                "an ON row at 06:00 or 18:00 represents a 60 s pulse, not one hour "
                "of continuous pumping"
            ),
        },
        "fan_policy": {
            "on_temperature_c": fan_on_temperature,
            "minimum_cooling_delta_c": fan_minimum_delta,
            "hourly_sampling_caveat": "fan command can change inside the saved hour",
        },
        "grow_light_policy": {
            "baseline_state": grow_light_state,
            "time_varying": False,
        },
        "controller_state": "STATELESS",
        "causal_claim": False,
    }


def load_canonical_index(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"parameter_set_id", "ml_file", "ml_rows", "config_hash"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Canonical index missing columns: {sorted(missing)}")
    if len(frame) != 24 or frame["parameter_set_id"].nunique() != 24:
        raise ValueError("Canonical index must contain 24 unique scenarios")
    if frame["config_hash"].nunique() != 24:
        raise ValueError("Canonical index contains duplicate parameter configs")
    if not frame["ml_rows"].astype(int).eq(70_128).all():
        raise ValueError("Canonical scenarios must each contain 70,128 ML rows")
    return frame


def resolve_indexed_path(raw_path: str, data_root: Path) -> Path:
    raw = Path(str(raw_path).replace("\\", "/"))
    candidates = (raw, data_root / raw, data_root / "outputs" / "full_generation" / "ml" / raw.name)
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Cannot resolve indexed ML file {raw_path!r}")


def resolve_development_paths(
    canonical_index: pd.DataFrame,
    development_ids: Sequence[str],
    held_out_ids: Sequence[str],
    data_root: Path,
) -> dict[str, Path]:
    """Resolve only development files; held-out paths are never inspected."""

    index_by_id = canonical_index.set_index("parameter_set_id", drop=False)
    if not set(development_ids).issubset(index_by_id.index):
        raise ValueError("Development IDs are not all present in canonical index")
    if set(development_ids) & set(held_out_ids):
        raise ValueError("Held-out IDs reached development resolver")
    return {
        scenario_id: resolve_indexed_path(
            str(index_by_id.loc[scenario_id, "ml_file"]), data_root
        )
        for scenario_id in development_ids
    }


def slice_split(
    frame: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    limit_hours: int | None = None,
) -> pd.DataFrame:
    selected = frame.loc[frame["timestamp"].between(start, end)].copy()
    if limit_hours is not None:
        selected = selected.iloc[:limit_hours].copy()
    if selected.empty:
        raise ValueError(f"No rows in requested split {start} through {end}")
    selected.reset_index(drop=True, inplace=True)
    return selected


def load_audit_frames(
    scenario_paths: Mapping[str, Path],
    train_range: Sequence[str],
    validation_range: Sequence[str],
    *,
    smoke_test: bool,
    config: AuditConfig,
) -> dict[tuple[str, str], pd.DataFrame]:
    frames: dict[tuple[str, str], pd.DataFrame] = {}
    train_start = pd.Timestamp(train_range[0])
    train_end = pd.Timestamp(train_range[1])
    validation_start = pd.Timestamp(validation_range[0])
    validation_end = pd.Timestamp(validation_range[1])
    if smoke_test:
        train_start = pd.Timestamp(year=train_start.year, month=6, day=1)
        train_end = train_start + pd.Timedelta(hours=config.smoke_train_hours - 1)
        validation_start = pd.Timestamp(
            year=validation_start.year, month=6, day=1
        )
        validation_end = validation_start + pd.Timedelta(
            hours=config.smoke_validation_hours - 1
        )
    for scenario_id, path in scenario_paths.items():
        frame = validate_scenario_frame(pd.read_csv(path), scenario_id)
        frames[("TRAIN", scenario_id)] = slice_split(
            frame,
            train_start,
            train_end,
        )
        frames[("VALIDATION", scenario_id)] = slice_split(
            frame,
            validation_start,
            validation_end,
        )
    return frames


def derive_train_sensor_standardization(
    frames: Mapping[tuple[str, str], pd.DataFrame],
) -> tuple[np.ndarray, np.ndarray]:
    """Derive matching-only sensor scaling from development TRAIN rows."""

    train_frames = [
        frame.loc[:, SENSORS]
        for (split, _), frame in frames.items()
        if split == "TRAIN"
    ]
    if not train_frames:
        raise ValueError("No TRAIN frames are available for matching standardization")
    values = pd.concat(train_frames, ignore_index=True).to_numpy(dtype=np.float64)
    mean = values.mean(axis=0)
    scale = values.std(axis=0, ddof=0)
    scale = np.where(scale == 0.0, 1.0, scale)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise FloatingPointError("Matching standardization contains NaN/Inf")
    return mean, scale


def transition_codes(values: Sequence[int] | np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=np.int8)
    if len(array) < 2:
        return np.empty(0, dtype="U2")
    return np.char.add(array[:-1].astype(str), array[1:].astype(str))


def run_lengths(values: Sequence[int] | np.ndarray) -> pd.DataFrame:
    array = np.asarray(values, dtype=np.int8)
    if len(array) == 0:
        return pd.DataFrame(columns=["state", "duration_hours"])
    starts = np.r_[0, np.flatnonzero(array[1:] != array[:-1]) + 1]
    ends = np.r_[starts[1:], len(array)]
    return pd.DataFrame(
        {"state": array[starts], "duration_hours": ends - starts}
    )


def encode_joint_actions(frame: pd.DataFrame) -> pd.Series:
    validate_binary_actuators(frame)
    return (
        frame["pump_state"].astype(str)
        + frame["fan_state"].astype(str)
        + frame["grow_light_state"].astype(str)
    )


def _describe(values: pd.Series, quantiles: Sequence[float]) -> dict[str, float]:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return {
            "count": 0,
            "mean": 0.0,
            "std": 0.0,
            "median": 0.0,
            **{f"p{int(q * 100):02d}": 0.0 for q in quantiles},
            "max": 0.0,
            "min": 0.0,
        }
    result = {
        "count": int(len(numeric)),
        "mean": float(numeric.mean()),
        "std": float(numeric.std(ddof=0)),
        "median": float(numeric.median()),
        "max": float(numeric.max()),
        "min": float(numeric.min()),
    }
    result.update({f"p{int(q * 100):02d}": float(numeric.quantile(q)) for q in quantiles})
    return result


def actuator_usage_summary(
    frames: Mapping[tuple[str, str], pd.DataFrame]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_frames = [(sid, frame) for (name, sid), frame in frames.items() if name == split]
        for actuator in ACTUATORS:
            counts = np.array([len(frame) for _, frame in split_frames], dtype=np.int64)
            on_counts = np.array([int(frame[actuator].sum()) for _, frame in split_frames])
            fractions = on_counts / counts
            rows.append(
                {
                    "split": split,
                    "actuator": actuator,
                    "total_timesteps": int(counts.sum()),
                    "off_count": int(counts.sum() - on_counts.sum()),
                    "on_count": int(on_counts.sum()),
                    "off_fraction": float(1.0 - on_counts.sum() / counts.sum()),
                    "on_fraction": float(on_counts.sum() / counts.sum()),
                    "scenario_on_fraction_mean": float(fractions.mean()),
                    "scenario_on_fraction_std": float(fractions.std(ddof=0)),
                    "scenario_on_fraction_min": float(fractions.min()),
                    "scenario_on_fraction_p25": float(np.quantile(fractions, 0.25)),
                    "scenario_on_fraction_median": float(np.median(fractions)),
                    "scenario_on_fraction_p75": float(np.quantile(fractions, 0.75)),
                    "scenario_on_fraction_max": float(fractions.max()),
                }
            )
    return pd.DataFrame(rows)


def actuator_transition_summary(
    frames: Mapping[tuple[str, str], pd.DataFrame]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_frames = [(sid, frame) for (name, sid), frame in frames.items() if name == split]
        for actuator in ACTUATORS:
            per_scenario = {sid: transition_codes(frame[actuator].to_numpy()) for sid, frame in split_frames}
            total_pairs = sum(len(codes) for codes in per_scenario.values())
            for code in ("00", "01", "10", "11"):
                counts = np.array([int(np.sum(codes == code)) for codes in per_scenario.values()])
                changing = code in {"01", "10"}
                rows.append(
                    {
                        "split": split,
                        "actuator": actuator,
                        "transition": code,
                        "count": int(counts.sum()),
                        "fraction_of_pairs": float(counts.sum() / total_pairs) if total_pairs else 0.0,
                        "transition_rate": float(counts.sum() / total_pairs) if changing and total_pairs else 0.0,
                        "per_scenario_mean": float(counts.mean()),
                        "per_scenario_std": float(counts.std(ddof=0)),
                        "per_scenario_min": int(counts.min()) if len(counts) else 0,
                        "per_scenario_max": int(counts.max()) if len(counts) else 0,
                        "scenarios_with_event": int(np.sum(counts > 0)),
                    }
                )
    return pd.DataFrame(rows)


def actuator_dwell_summary(
    frames: Mapping[tuple[str, str], pd.DataFrame]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    raw_rows: list[pd.DataFrame] = []
    for (split, scenario_id), frame in frames.items():
        for actuator in ACTUATORS:
            runs = run_lengths(frame[actuator].to_numpy())
            runs["split"] = split
            runs["scenario_id"] = scenario_id
            runs["actuator"] = actuator
            raw_rows.append(runs)
    raw = pd.concat(raw_rows, ignore_index=True)
    rows: list[dict[str, Any]] = []
    for (split, actuator, state), group in raw.groupby(["split", "actuator", "state"], sort=True):
        stats = _describe(group["duration_hours"], (0.25, 0.75, 0.90, 0.95))
        rows.append({"split": split, "actuator": actuator, "state": int(state), **stats})
    return pd.DataFrame(rows), raw


def joint_action_coverage(
    frames: Mapping[tuple[str, str], pd.DataFrame]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_frames = [(sid, frame) for (name, sid), frame in frames.items() if name == split]
        codes = {sid: encode_joint_actions(frame) for sid, frame in split_frames}
        total = sum(len(values) for values in codes.values())
        for code in JOINT_CODES:
            counts = np.array([int((values == code).sum()) for values in codes.values()])
            rows.append(
                {
                    "split": split,
                    "joint_action": code,
                    "actuator_order": "pump|fan|grow_light",
                    "count": int(counts.sum()),
                    "fraction": float(counts.sum() / total),
                    "scenarios_containing": int(np.sum(counts > 0)),
                    "per_scenario_fraction_mean": float(np.mean(counts / np.array([len(frame) for _, frame in split_frames]))),
                    "support_status": "ABSENT" if counts.sum() == 0 else "OBSERVED",
                }
            )
    return pd.DataFrame(rows)


def quantile_edges(values: np.ndarray, bins: int) -> np.ndarray:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        raise ValueError("Cannot derive quantile edges from empty values")
    raw = np.quantile(finite, np.linspace(0.0, 1.0, bins + 1)[1:-1])
    return np.unique(raw)


def assign_bins(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    return np.searchsorted(np.asarray(edges, dtype=float), np.asarray(values, dtype=float), side="right")


def derive_overlap_edges(
    frames: Mapping[tuple[str, str], pd.DataFrame], config: AuditConfig
) -> dict[str, dict[str, list[float]]]:
    train_frames = [frame for (split, _), frame in frames.items() if split == "TRAIN"]
    result: dict[str, dict[str, list[float]]] = {}
    for actuator, variables in OVERLAP_VARIABLES.items():
        result[actuator] = {}
        for variable in variables:
            if variable == "hour_of_day":
                edges = np.asarray([6.0, 12.0, 18.0])
            else:
                values = np.concatenate([frame[variable].to_numpy(dtype=float) for frame in train_frames])
                edges = quantile_edges(values, config.quantile_bins)
            result[actuator][variable] = [float(value) for value in edges]
    return result


def state_conditioned_overlap(
    frames: Mapping[tuple[str, str], pd.DataFrame],
    edges: Mapping[str, Mapping[str, Sequence[float]]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        split_frames = [frame for (name, _), frame in frames.items() if name == split]
        for actuator, variables in OVERLAP_VARIABLES.items():
            cell_parts: list[pd.DataFrame] = []
            for frame in split_frames:
                binned: dict[str, np.ndarray] = {}
                for variable in variables:
                    values = (
                        frame["timestamp"].dt.hour.to_numpy(dtype=float)
                        if variable == "hour_of_day"
                        else frame[variable].to_numpy(dtype=float)
                    )
                    binned[variable] = assign_bins(values, np.asarray(edges[actuator][variable]))
                cells = pd.DataFrame(binned)
                cells["action"] = frame[actuator].to_numpy(dtype=np.int8)
                cell_parts.append(cells)
            combined = pd.concat(cell_parts, ignore_index=True)
            counts = combined.groupby(list(variables) + ["action"], sort=True).size().unstack(fill_value=0)
            if 0 not in counts:
                counts[0] = 0
            if 1 not in counts:
                counts[1] = 0
            both = (counts[0] > 0) & (counts[1] > 0)
            only_off = (counts[0] > 0) & (counts[1] == 0)
            only_on = (counts[0] == 0) & (counts[1] > 0)
            total_samples = int(counts[[0, 1]].to_numpy().sum())
            both_samples = int(counts.loc[both, [0, 1]].to_numpy().sum())
            rows.append(
                {
                    "split": split,
                    "actuator": actuator,
                    "conditioning_variables": "|".join(variables),
                    "occupied_cells": int(len(counts)),
                    "only_off_cells": int(only_off.sum()),
                    "only_on_cells": int(only_on.sum()),
                    "both_action_cells": int(both.sum()),
                    "overlap_fraction": float(both.mean()) if len(counts) else 0.0,
                    "sample_weighted_overlap_fraction": float(both_samples / total_samples) if total_samples else 0.0,
                    "diagnostic_scope": "EMPIRICAL_SUPPORT_NOT_CAUSAL_POSITIVITY_PROOF",
                }
            )
    return pd.DataFrame(rows)


def extract_transition_events(
    frame: pd.DataFrame,
    scenario_id: str,
    split: str,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Construct event rows without crossing the supplied scenario/split frame."""

    records: list[dict[str, Any]] = []
    maximum_horizon = max(horizons)
    n_rows = len(frame)
    for actuator in ACTUATORS:
        values = frame[actuator].to_numpy(dtype=np.int8)
        event_positions = np.flatnonzero(values[1:] != values[:-1]) + 1
        for position in event_positions:
            if position + maximum_horizon >= n_rows:
                continue
            previous = int(values[position - 1])
            current = int(values[position])
            record: dict[str, Any] = {
                "split": split,
                "scenario_id": scenario_id,
                "event_position": int(position),
                "event_timestamp": frame.at[position, "timestamp"],
                "actuator": actuator,
                "previous_value": previous,
                "new_value": current,
                "direction": f"{previous}{current}",
                "hour_of_day": int(frame.at[position, "timestamp"].hour),
            }
            for column in ACTUATORS:
                record[f"current_{column}"] = int(frame.at[position, column])
                record[f"previous_{column}"] = int(frame.at[position - 1, column])
            for sensor in SENSORS:
                current_value = float(frame.at[position, sensor])
                record[f"current_{sensor}"] = current_value
                for horizon in horizons:
                    future = float(frame.at[position + horizon, sensor])
                    record[f"target_{horizon}h_{sensor}"] = future
                    record[f"delta_{horizon}h_{sensor}"] = future - current_value
            for horizon in horizons:
                other_actuators = [name for name in ACTUATORS if name != actuator]
                other_stable_at_transition = all(
                    frame.at[position - 1, name] == frame.at[position, name]
                    for name in other_actuators
                )
                other_stable_through_horizon = all(
                    frame.loc[position - 1 : position + horizon, name].nunique() == 1
                    for name in other_actuators
                )
                target_stable_through_horizon = (
                    frame.loc[position : position + horizon, actuator].nunique() == 1
                )
                record[f"other_stable_{horizon}h"] = bool(
                    other_stable_at_transition and other_stable_through_horizon
                )
                record[f"target_stable_{horizon}h"] = bool(
                    target_stable_through_horizon
                )
                record[f"clean_{horizon}h"] = bool(
                    other_stable_at_transition
                    and other_stable_through_horizon
                )
            records.append(record)
    return pd.DataFrame(records)


def build_transition_events(
    frames: Mapping[tuple[str, str], pd.DataFrame]
) -> pd.DataFrame:
    parts = [
        extract_transition_events(frame, scenario_id, split)
        for (split, scenario_id), frame in frames.items()
    ]
    nonempty = [part for part in parts if not part.empty]
    return pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame()


def aggregate_response(events: pd.DataFrame, *, clean: bool = False) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if events.empty:
        return pd.DataFrame(columns=RESPONSE_COLUMNS)
    for horizon in HORIZONS:
        selected = events.loc[events[f"clean_{horizon}h"]].copy() if clean else events
        for keys, group in selected.groupby(["split", "actuator", "direction"], sort=True):
            for target in SENSORS:
                stats = _describe(group[f"delta_{horizon}h_{target}"], (0.10, 0.25, 0.75, 0.90))
                rows.append(
                    {
                        "split": keys[0],
                        "actuator": keys[1],
                        "direction": keys[2],
                        "horizon_h": horizon,
                        "target": target,
                        "count": stats["count"],
                        "mean": stats["mean"],
                        "std": stats["std"],
                        "median": stats["median"],
                        "p10": stats["p10"],
                        "p25": stats["p25"],
                        "p75": stats["p75"],
                        "p90": stats["p90"],
                        "unit": TARGET_UNITS[target],
                    }
                )
    return pd.DataFrame(rows, columns=RESPONSE_COLUMNS)


def build_no_change_references(
    frame: pd.DataFrame,
    scenario_id: str,
    split: str,
    actuator: str,
    horizon: int,
) -> pd.DataFrame:
    if actuator not in ACTUATORS or horizon not in HORIZONS:
        raise ValueError("Unsupported actuator or horizon")
    values = frame[actuator].to_numpy(dtype=np.int8)
    if len(frame) <= horizon + 1:
        return pd.DataFrame()
    positions = np.arange(1, len(frame) - horizon, dtype=np.int64)
    stable = np.ones(len(positions), dtype=bool)
    for offset in range(-1, horizon + 1):
        stable &= values[positions + offset] == values[positions]
    positions = positions[stable]
    records: list[dict[str, Any]] = []
    for position in positions:
        record: dict[str, Any] = {
            "split": split,
            "scenario_id": scenario_id,
            "position": int(position),
            "timestamp": frame.at[position, "timestamp"],
            "actuator": actuator,
            "state": int(values[position]),
            "horizon_h": horizon,
            "hour_of_day": int(frame.at[position, "timestamp"].hour),
        }
        other = [name for name in ACTUATORS if name != actuator]
        record["other_action_code"] = "".join(str(int(frame.at[position, name])) for name in other)
        for sensor in SENSORS:
            current = float(frame.at[position, sensor])
            record[f"current_{sensor}"] = current
            record[f"delta_{sensor}"] = float(frame.at[position + horizon, sensor]) - current
        records.append(record)
    return pd.DataFrame(records)


def _standardize(values: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    safe_scale = np.where(np.asarray(scale, dtype=float) == 0.0, 1.0, scale)
    return (np.asarray(values, dtype=float) - np.asarray(mean, dtype=float)) / safe_scale


def deterministic_spread_indices(length: int, maximum: int) -> np.ndarray:
    """Select a deterministic, time-spread subset without replacement."""

    if length < 0 or maximum <= 0:
        raise ValueError("length must be nonnegative and maximum must be positive")
    if length <= maximum:
        return np.arange(length, dtype=np.int64)
    return np.floor(np.arange(maximum, dtype=float) * length / maximum).astype(
        np.int64
    )


def matched_response_diagnostic(
    events: pd.DataFrame,
    frames: Mapping[tuple[str, str], pd.DataFrame],
    scaler_mean: Sequence[float],
    scaler_scale: Sequence[float],
    *,
    config: AuditConfig | None = None,
    smoke_test: bool = False,
) -> pd.DataFrame:
    """Bounded 1-NN descriptive matching, always within split and scenario."""

    from sklearn.neighbors import NearestNeighbors

    output_rows: list[dict[str, Any]] = []
    if events.empty:
        return pd.DataFrame()
    config = config or AuditConfig()
    maximum_events = (
        config.matching_max_events_per_group_smoke
        if smoke_test
        else config.matching_max_events_per_group_full
    )
    maximum_references = (
        config.matching_max_references_per_stratum_smoke
        if smoke_test
        else config.matching_max_references_per_stratum_full
    )
    matching_scope = "BOUNDED_SMOKE" if smoke_test else "BOUNDED_FULL"
    mean = np.asarray(scaler_mean, dtype=float)
    scale = np.asarray(scaler_scale, dtype=float)
    reference_cache: dict[tuple[str, str, str, int], pd.DataFrame] = {}
    for horizon in HORIZONS:
        for (split, scenario_id, actuator, direction), group in events.groupby(
            ["split", "scenario_id", "actuator", "direction"], sort=True
        ):
            group = group.sort_values(
                ["event_timestamp", "event_position"], kind="stable"
            )
            available_event_rows = int(len(group))
            group = group.iloc[
                deterministic_spread_indices(available_event_rows, maximum_events)
            ].copy()
            reference_key = (split, scenario_id, actuator, horizon)
            if reference_key not in reference_cache:
                reference_cache[reference_key] = build_no_change_references(
                    frames[(split, scenario_id)],
                    scenario_id,
                    split,
                    actuator,
                    horizon,
                )
            reference = reference_cache[reference_key]
            new_state = int(direction[-1])
            other = [name for name in ACTUATORS if name != actuator]
            group["other_action_code"] = (
                group[f"current_{other[0]}"].astype(np.int8).astype(str)
                + group[f"current_{other[1]}"].astype(np.int8).astype(str)
            )
            reference_groups = (
                {
                    (int(key[1]), str(key[2])): values.sort_values(
                        ["timestamp", "position"], kind="stable"
                    ).reset_index(drop=True)
                    for key, values in reference.loc[
                        reference["state"] == new_state
                    ].groupby(
                        ["state", "hour_of_day", "other_action_code"], sort=True
                    )
                }
                if not reference.empty
                else {}
            )
            for stratum, event_group in group.groupby(
                ["hour_of_day", "other_action_code"], sort=True
            ):
                stratum_key = (int(stratum[0]), str(stratum[1]))
                candidates = reference_groups.get(stratum_key)
                matched_rows: dict[int, tuple[float, pd.Series]] = {}
                if candidates is not None and not candidates.empty:
                    candidates = candidates.iloc[
                        deterministic_spread_indices(
                            len(candidates), maximum_references
                        )
                    ].reset_index(drop=True)
                    candidate_matrix = candidates[
                        [f"current_{sensor}" for sensor in SENSORS]
                    ].to_numpy(dtype=float)
                    event_matrix = event_group[
                        [f"current_{sensor}" for sensor in SENSORS]
                    ].to_numpy(dtype=float)
                    neighbor_index = NearestNeighbors(
                        n_neighbors=1,
                        algorithm="auto",
                        metric="euclidean",
                    ).fit(_standardize(candidate_matrix, mean, scale))
                    distances, indices = neighbor_index.kneighbors(
                        _standardize(event_matrix, mean, scale),
                        return_distance=True,
                    )
                    for offset, event_index in enumerate(event_group.index):
                        matched_rows[int(event_index)] = (
                            float(distances[offset, 0]),
                            candidates.iloc[int(indices[offset, 0])],
                        )
                for event_index, event in event_group.iterrows():
                    match = matched_rows.get(int(event_index))
                    for target in SENSORS:
                        transition_delta = float(
                            event[f"delta_{horizon}h_{target}"]
                        )
                        reference_delta = (
                            float(match[1][f"delta_{target}"])
                            if match is not None
                            else np.nan
                        )
                        output_rows.append(
                            {
                                "split": split,
                                "scenario_id": scenario_id,
                                "event_index": int(event_index),
                                "actuator": actuator,
                                "direction": direction,
                                "horizon_h": horizon,
                                "matched": match is not None,
                                "match_distance": (
                                    match[0] if match is not None else np.nan
                                ),
                                "target": target,
                                "transition_delta": transition_delta,
                                "reference_delta": reference_delta,
                                "response_difference": (
                                    transition_delta - reference_delta
                                    if match is not None
                                    else np.nan
                                ),
                                "available_event_rows": available_event_rows,
                                "matching_scope": matching_scope,
                            }
                        )
    raw = pd.DataFrame(output_rows)
    rows: list[dict[str, Any]] = []
    if raw.empty:
        return raw
    for keys, group in raw.groupby(["split", "actuator", "direction", "horizon_h", "target"], sort=True):
        event_count = int(len(group))
        matched = group.loc[group["matched"]]
        distances = matched["match_distance"].dropna()
        rows.append(
            {
                "split": keys[0],
                "actuator": keys[1],
                "direction": keys[2],
                "horizon_h": int(keys[3]),
                "target": keys[4],
                "available_event_rows": int(
                    group.groupby("scenario_id")["available_event_rows"].first().sum()
                ),
                "sampled_event_rows": event_count,
                "event_rows": event_count,
                "matched_count": int(len(matched)),
                "unmatched_fraction": float(1.0 - len(matched) / event_count),
                "match_distance_mean": float(distances.mean()) if len(distances) else 0.0,
                "match_distance_median": float(distances.median()) if len(distances) else 0.0,
                "match_distance_p95": float(distances.quantile(0.95)) if len(distances) else 0.0,
                "transition_delta_mean": float(matched["transition_delta"].mean()) if len(matched) else 0.0,
                "reference_delta_mean": float(matched["reference_delta"].mean()) if len(matched) else 0.0,
                "response_difference_mean": float(matched["response_difference"].mean()) if len(matched) else 0.0,
                "interpretation": "DESCRIPTIVE_MATCH_NOT_CAUSAL_EFFECT",
                "matching_scope": matching_scope,
            }
        )
    return pd.DataFrame(rows)


def standardized_mean_difference(first: np.ndarray, second: np.ndarray) -> float:
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    if not len(first) or not len(second):
        return 0.0
    pooled = np.sqrt((np.var(first) + np.var(second)) / 2.0)
    return float((np.mean(first) - np.mean(second)) / pooled) if pooled > 0 else 0.0


def summarize_no_change_references(
    frames: Mapping[tuple[str, str], pd.DataFrame],
) -> pd.DataFrame:
    """Count stable-action reference support without saving row-level references."""

    rows: list[dict[str, Any]] = []
    for (split, scenario_id), frame in frames.items():
        for actuator in ACTUATORS:
            for horizon in HORIZONS:
                references = build_no_change_references(
                    frame, scenario_id, split, actuator, horizon
                )
                for state in (0, 1):
                    count = (
                        int((references["state"] == state).sum())
                        if not references.empty
                        else 0
                    )
                    rows.append(
                        {
                            "split": split,
                            "scenario_id": scenario_id,
                            "actuator": actuator,
                            "horizon_h": horizon,
                            "state": state,
                            "count": count,
                            "reference_scope": (
                                "target actuator stable from t-1 through t+h"
                            ),
                        }
                    )
    return pd.DataFrame(rows)


def confounding_diagnostics(
    events: pd.DataFrame,
    frames: Mapping[tuple[str, str], pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for split in SPLITS:
        for actuator in ACTUATORS:
            reference_parts = [
                build_no_change_references(frame, scenario_id, split, actuator, 3)
                for (name, scenario_id), frame in frames.items()
                if name == split
            ]
            reference_parts = [part for part in reference_parts if not part.empty]
            references = (
                pd.concat(reference_parts, ignore_index=True)
                if reference_parts
                else pd.DataFrame()
            )
            stable_off = (
                references.loc[references["state"] == 0]
                if not references.empty
                else references
            )
            stable_on = (
                references.loc[references["state"] == 1]
                if not references.empty
                else references
            )
            event_subset = events.loc[(events["split"] == split) & (events["actuator"] == actuator)] if not events.empty else pd.DataFrame()
            groups: dict[str, pd.DataFrame] = {
                "stable_off": stable_off,
                "stable_on": stable_on,
                "transition_on": event_subset.loc[event_subset["direction"] == "01"] if not event_subset.empty else event_subset,
                "transition_off": event_subset.loc[event_subset["direction"] == "10"] if not event_subset.empty else event_subset,
            }
            for sensor in (*SENSORS, "hour_of_day"):
                stable_column = (
                    f"current_{sensor}" if sensor in SENSORS else "hour_of_day"
                )
                event_column = (
                    f"current_{sensor}" if sensor in SENSORS else "hour_of_day"
                )
                baseline_off = (
                    stable_off[stable_column].to_numpy(dtype=float)
                    if stable_column in stable_off
                    else np.empty(0)
                )
                baseline_on = (
                    stable_on[stable_column].to_numpy(dtype=float)
                    if stable_column in stable_on
                    else np.empty(0)
                )
                for group_name, group in groups.items():
                    column = event_column if group_name.startswith("transition") else stable_column
                    values = group[column].to_numpy(dtype=float) if column in group else np.empty(0)
                    reference = baseline_off if group_name in {"stable_off", "transition_on"} else baseline_on
                    rows.append(
                        {
                            "split": split,
                            "actuator": actuator,
                            "group": group_name,
                            "sensor": sensor,
                            "count": int(len(values)),
                            "mean": float(np.mean(values)) if len(values) else 0.0,
                            "median": float(np.median(values)) if len(values) else 0.0,
                            "p25": float(np.quantile(values, 0.25)) if len(values) else 0.0,
                            "p75": float(np.quantile(values, 0.75)) if len(values) else 0.0,
                            "standardized_mean_difference_vs_reference": standardized_mean_difference(values, reference),
                            "reference_group": "stable_off" if group_name in {"stable_off", "transition_on"} else "stable_on",
                            "stable_definition": "target action unchanged from t-1 through t+3h",
                        }
                    )
    return pd.DataFrame(rows)


def support_by_scenario(
    frames: Mapping[tuple[str, str], pd.DataFrame], events: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (split, scenario_id), frame in frames.items():
        for actuator in ACTUATORS:
            subset = events.loc[
                (events["split"] == split)
                & (events["scenario_id"] == scenario_id)
                & (events["actuator"] == actuator)
            ] if not events.empty else pd.DataFrame()
            rows.append(
                {
                    "split": split,
                    "scenario_id": scenario_id,
                    "actuator": actuator,
                    "timesteps": int(len(frame)),
                    "on_count": int(frame[actuator].sum()),
                    "on_fraction": float(frame[actuator].mean()),
                    "off_to_on_events": int((subset["direction"] == "01").sum()) if not subset.empty else 0,
                    "on_to_off_events": int((subset["direction"] == "10").sum()) if not subset.empty else 0,
                    "clean_1h_events": int(subset["clean_1h"].sum()) if not subset.empty else 0,
                    "clean_3h_events": int(subset["clean_3h"].sum()) if not subset.empty else 0,
                }
            )
    return pd.DataFrame(rows)


def train_validation_shift(
    usage: pd.DataFrame,
    transitions: pd.DataFrame,
    joint: pd.DataFrame,
    responses: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    def append_metric(metric: str, key: str, train_value: float, validation_value: float) -> None:
        rows.append(
            {
                "metric": metric,
                "key": key,
                "train_value": float(train_value),
                "validation_value": float(validation_value),
                "validation_minus_train": float(validation_value - train_value),
            }
        )

    for actuator in ACTUATORS:
        subset = usage.loc[usage["actuator"] == actuator].set_index("split")
        append_metric("on_fraction", actuator, subset.at["TRAIN", "on_fraction"], subset.at["VALIDATION", "on_fraction"])
        for direction in ("01", "10"):
            transition = transitions.loc[
                (transitions["actuator"] == actuator) & (transitions["transition"] == direction)
            ].set_index("split")
            append_metric("transition_rate", f"{actuator}:{direction}", transition.at["TRAIN", "transition_rate"], transition.at["VALIDATION", "transition_rate"])
    for code in JOINT_CODES:
        subset = joint.loc[joint["joint_action"] == code].set_index("split")
        append_metric("joint_action_fraction", code, subset.at["TRAIN", "fraction"], subset.at["VALIDATION", "fraction"])
    if not responses.empty:
        for keys, group in responses.groupby(["actuator", "direction", "horizon_h", "target"]):
            indexed = group.set_index("split")
            if set(SPLITS).issubset(indexed.index):
                append_metric("response_mean", ":".join(map(str, keys)), indexed.at["TRAIN", "mean"], indexed.at["VALIDATION", "mean"])
    return pd.DataFrame(rows)


def assess_readiness(
    usage: pd.DataFrame,
    transitions: pd.DataFrame,
    overlap: pd.DataFrame,
    events: pd.DataFrame,
    *,
    temporal_semantics_verified: bool,
    smoke_test: bool,
    config: AuditConfig,
) -> dict[str, Any]:
    if smoke_test:
        return {
            "status": "REVIEW_REQUIRED",
            "execution_scope": "SMOKE_ONLY_NOT_SCIENTIFIC",
            "reason": "Smoke execution validates code paths only; scientific readiness requires the full 20-scenario audit.",
            "per_actuator": {},
        }
    if not temporal_semantics_verified:
        return {
            "status": "REVIEW_REQUIRED",
            "execution_scope": "FULL",
            "reason": "Actuator temporal semantics were not verified from source.",
            "per_actuator": {},
        }
    evidence: dict[str, Any] = {}
    unsupported: list[str] = []
    partial: list[str] = []
    for actuator in ACTUATORS:
        usage_row = usage.loc[(usage["split"] == "TRAIN") & (usage["actuator"] == actuator)].iloc[0]
        transition_rows = transitions.loc[
            (transitions["split"] == "TRAIN")
            & (transitions["actuator"] == actuator)
            & (transitions["transition"].isin(["01", "10"]))
        ]
        transition_min = int(transition_rows["count"].min())
        overlap_row = overlap.loc[(overlap["split"] == "TRAIN") & (overlap["actuator"] == actuator)].iloc[0]
        event_subset = events.loc[(events["split"] == "TRAIN") & (events["actuator"] == actuator)]
        clean_count = int(event_subset["clean_3h"].sum()) if not event_subset.empty else 0
        actuator_status = "SUPPORTED"
        if usage_row["on_fraction"] == 0.0 or transition_min == 0:
            actuator_status = "TARGETED_DATA_REQUIRED"
            unsupported.append(actuator)
        elif (
            transition_min < config.minimum_transition_events
            or clean_count < config.minimum_clean_events
            or overlap_row["sample_weighted_overlap_fraction"] < config.minimum_sample_weighted_overlap
        ):
            actuator_status = "PARTIAL"
            partial.append(actuator)
        evidence[actuator] = {
            "status": actuator_status,
            "on_fraction": float(usage_row["on_fraction"]),
            "minimum_direction_transition_count": transition_min,
            "clean_3h_event_count": clean_count,
            "sample_weighted_overlap_fraction": float(overlap_row["sample_weighted_overlap_fraction"]),
        }
    if unsupported:
        status = "TARGETED_DATA_REQUIRED"
        reason = f"Critical intervention support is absent for: {unsupported}."
    elif partial:
        status = "PARTIAL"
        reason = f"Some actuator support diagnostics are limited: {partial}."
    else:
        status = "READY"
        reason = "All actuators meet the predeclared descriptive support heuristics."
    return {"status": status, "execution_scope": "FULL", "reason": reason, "per_actuator": evidence}


def save_metric_frames(metrics: Mapping[str, pd.DataFrame], metrics_dir: Path) -> None:
    metrics_dir.mkdir(parents=True, exist_ok=True)
    for filename in METRIC_FILENAMES:
        frame = metrics.get(filename)
        if frame is None:
            raise ValueError(f"Required metric was not produced: {filename}")
        frame.to_csv(metrics_dir / filename, index=False)


def save_json_atomic(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    temporary.replace(path)
