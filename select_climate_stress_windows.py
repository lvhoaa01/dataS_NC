"""Select deterministic weather-only stress windows for seasonal preflight."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Callable, Iterable, Sequence

from physics.simulator import WeatherForcing, load_and_validate_weather_range


ROOT = Path(__file__).resolve().parent
WEATHER_PATH = ROOT / "nha_trang_weather_2018_2025.csv"
OUTPUT_YAML = ROOT / "climate_stress_windows.yaml"
OUTPUT_CSV = ROOT / "climate_stress_windows.csv"
FULL_START = datetime(2018, 1, 1)
FULL_END = datetime(2025, 12, 31, 23)
WINDOW_DAYS = 30
WARMUP_DAYS = 30
MAX_OVERLAP_FRACTION = 0.50
TIMEZONE_NAME = "Asia/Ho_Chi_Minh"
SELECTOR_VERSION = "pa1_climate_stress_windows_v1"


@dataclass(frozen=True)
class WindowCandidate:
    start: datetime
    end: datetime
    metrics: dict[str, float]


WINDOW_SPECS: tuple[tuple[str, str, tuple[tuple[str, float], ...], str], ...] = (
    (
        "HUMID_STRESS",
        "humid_stress",
        (
            ("rh_mean", 0.25),
            ("rh_p95", 0.20),
            ("dew_point_mean", 0.20),
            ("vpd_mean", -0.20),
            ("wind_mean", -0.15),
        ),
        "High outdoor RH/dew point with low VPD and weak wind limits indoor moisture removal.",
    ),
    (
        "HOT_SOLAR_STRESS",
        "hot_solar_stress",
        (
            ("temperature_mean", 0.25),
            ("temperature_max", 0.20),
            ("solar_mean", 0.35),
            ("direct_mean", 0.20),
        ),
        "High ambient temperature and solar burden stress E7 air heat and E8 root-zone heat.",
    ),
    (
        "DRY_VPD_STRESS",
        "dry_vpd_stress",
        (
            ("vpd_mean", 0.30),
            ("vpd_p95", 0.25),
            ("temperature_mean", 0.15),
            ("solar_mean", 0.20),
            ("rh_mean", -0.10),
        ),
        "High VPD, heat and solar with low RH stress ET demand and root-zone water supply.",
    ),
    (
        "TRANSITION_MIXED",
        "transition_mixed",
        (
            ("temperature_std", 0.20),
            ("rh_std", 0.20),
            ("vpd_std", 0.20),
            ("daily_temperature_change", 0.15),
            ("daily_rh_change", 0.15),
            ("daily_solar_change", 0.10),
        ),
        "High within-window and day-to-day forcing variability stresses controller and state inertia transitions.",
    ),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def mean_abs_difference(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.fmean(
        abs(right - left) for left, right in zip(values, values[1:])
    )


def daily_values(
    rows: Sequence[WeatherForcing], getter: Callable[[WeatherForcing], float]
) -> list[float]:
    return [
        statistics.fmean(getter(row) for row in rows[offset : offset + 24])
        for offset in range(0, len(rows), 24)
    ]


def summarize_window(rows: Sequence[WeatherForcing]) -> dict[str, float]:
    temperatures = [row.temperature_outside_c for row in rows]
    humidities = [row.relative_humidity_outside_percent for row in rows]
    vpd = [row.outdoor_vpd_kpa for row in rows]
    solar = [row.shortwave_radiation_w_m2 for row in rows]
    direct = [row.direct_radiation_w_m2 for row in rows]
    dew_point = [row.dew_point_c for row in rows]
    wind = [row.wind_speed_m_s for row in rows]
    daily_temperature = daily_values(rows, lambda row: row.temperature_outside_c)
    daily_rh = daily_values(rows, lambda row: row.relative_humidity_outside_percent)
    daily_solar = [
        sum(row.shortwave_radiation_w_m2 for row in rows[offset : offset + 24])
        for offset in range(0, len(rows), 24)
    ]
    return {
        "temperature_mean": statistics.fmean(temperatures),
        "temperature_max": max(temperatures),
        "temperature_std": statistics.pstdev(temperatures),
        "rh_mean": statistics.fmean(humidities),
        "rh_p95": quantile(humidities, 0.95),
        "rh_std": statistics.pstdev(humidities),
        "dew_point_mean": statistics.fmean(dew_point),
        "vpd_mean": statistics.fmean(vpd),
        "vpd_p95": quantile(vpd, 0.95),
        "vpd_std": statistics.pstdev(vpd),
        "solar_mean": statistics.fmean(solar),
        "solar_integrated_wh_m2": sum(solar),
        "direct_mean": statistics.fmean(direct),
        "wind_mean": statistics.fmean(wind),
        "daily_temperature_change": mean_abs_difference(daily_temperature),
        "daily_rh_change": mean_abs_difference(daily_rh),
        "daily_solar_change": mean_abs_difference(daily_solar),
    }


def build_candidates(weather: Sequence[WeatherForcing]) -> list[WindowCandidate]:
    rows_by_timestamp = {
        datetime.fromisoformat(row.timestamp): index for index, row in enumerate(weather)
    }
    candidates: list[WindowCandidate] = []
    start = FULL_START + timedelta(days=WARMUP_DAYS)
    final_start = FULL_END.replace(hour=0) - timedelta(days=WINDOW_DAYS - 1)
    while start <= final_start:
        index = rows_by_timestamp[start]
        rows = weather[index : index + WINDOW_DAYS * 24]
        if len(rows) != WINDOW_DAYS * 24:
            raise ValueError(f"Incomplete candidate weather window at {start}.")
        candidates.append(
            WindowCandidate(
                start=start,
                end=start + timedelta(days=WINDOW_DAYS, hours=-1),
                metrics=summarize_window(rows),
            )
        )
        start += timedelta(days=1)
    return candidates


def standardizers(
    candidates: Sequence[WindowCandidate],
) -> dict[str, tuple[float, float]]:
    names = candidates[0].metrics
    result: dict[str, tuple[float, float]] = {}
    for name in names:
        values = [candidate.metrics[name] for candidate in candidates]
        result[name] = (statistics.fmean(values), statistics.pstdev(values))
    return result


def score_candidate(
    candidate: WindowCandidate,
    components: Iterable[tuple[str, float]],
    scales: dict[str, tuple[float, float]],
) -> float:
    score = 0.0
    for name, weight in components:
        mean, std = scales[name]
        z_score = 0.0 if std == 0.0 else (candidate.metrics[name] - mean) / std
        score += weight * z_score
    return score


def overlap_fraction(left: WindowCandidate, right: WindowCandidate) -> float:
    overlap_start = max(left.start, right.start)
    overlap_end = min(left.end, right.end)
    if overlap_end < overlap_start:
        return 0.0
    overlap_hours = int((overlap_end - overlap_start).total_seconds() // 3600) + 1
    return overlap_hours / (WINDOW_DAYS * 24)


def select_windows(
    candidates: Sequence[WindowCandidate],
) -> list[dict[str, object]]:
    scales = standardizers(candidates)
    reference_start = datetime(2024, 6, 1)
    reference = next(item for item in candidates if item.start == reference_start)
    selected_candidates = [reference]
    selected: list[dict[str, object]] = [
        window_record(
            "REFERENCE_JUNE",
            "reference_june",
            reference,
            0.0,
            "Validated June 2024 reference window retained as a control, not as the sole gate.",
        )
    ]
    for window_type, identifier, components, reason in WINDOW_SPECS:
        ranked = sorted(
            (
                (score_candidate(candidate, components, scales), candidate)
                for candidate in candidates
            ),
            key=lambda item: (-item[0], item[1].start),
        )
        eligible = [
            (score, candidate)
            for score, candidate in ranked
            if all(
                overlap_fraction(candidate, previous) <= MAX_OVERLAP_FRACTION
                for previous in selected_candidates
            )
        ]
        if not eligible:
            raise ValueError(f"No nonredundant candidate available for {window_type}.")
        score, candidate = eligible[0]
        selected_candidates.append(candidate)
        selected.append(window_record(window_type, identifier, candidate, score, reason))
    return selected


def window_record(
    window_type: str,
    identifier: str,
    candidate: WindowCandidate,
    score: float,
    reason: str,
) -> dict[str, object]:
    metrics = candidate.metrics
    return {
        "window_id": identifier,
        "type": window_type,
        "start_timestamp": candidate.start.isoformat(timespec="minutes"),
        "end_timestamp": candidate.end.isoformat(timespec="minutes"),
        "hours": WINDOW_DAYS * 24,
        "selection_score": score,
        "T_mean": metrics["temperature_mean"],
        "T_max": metrics["temperature_max"],
        "RH_mean": metrics["rh_mean"],
        "RH_p95": metrics["rh_p95"],
        "VPD_mean": metrics["vpd_mean"],
        "VPD_p95": metrics["vpd_p95"],
        "solar_mean": metrics["solar_mean"],
        "solar_integrated_Wh_m2": metrics["solar_integrated_wh_m2"],
        "wind_mean": metrics["wind_mean"],
        "selection_reason": reason,
    }


def write_outputs(
    windows: Sequence[dict[str, object]],
    weather_hash: str,
    yaml_path: Path = OUTPUT_YAML,
    csv_path: Path = OUTPUT_CSV,
) -> None:
    payload = {
        "schema_version": "1.0",
        "selector_version": SELECTOR_VERSION,
        "timezone": TIMEZONE_NAME,
        "weather_file": WEATHER_PATH.name,
        "weather_hash": weather_hash,
        "window_days": WINDOW_DAYS,
        "warmup_days": WARMUP_DAYS,
        "maximum_pairwise_overlap_fraction": MAX_OVERLAP_FRACTION,
        "selection_basis": "weather_forcing_only",
        "windows": list(windows),
    }
    yaml_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(windows[0]))
        writer.writeheader()
        writer.writerows(windows)


def generate() -> dict[str, object]:
    weather_with_endpoint, quality = load_and_validate_weather_range(
        WEATHER_PATH,
        FULL_START,
        FULL_END,
        allow_terminal_hold=True,
    )
    weather = weather_with_endpoint[:-1]
    candidates = build_candidates(weather)
    windows = select_windows(candidates)
    weather_hash = sha256_file(WEATHER_PATH)
    write_outputs(windows, weather_hash)
    return {
        "status": "PASS",
        "weather_quality": quality,
        "candidate_windows": len(candidates),
        "weather_hash": weather_hash,
        "windows": windows,
    }


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(
        description="Select deterministic PA1 seasonal stress windows from weather forcing."
    )


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    report = generate()
    print(f"STATUS: {report['status']}")
    print(f"CANDIDATE_WINDOWS: {report['candidate_windows']}")
    print(f"WEATHER_HASH: {report['weather_hash']}")
    for window in report["windows"]:
        print(
            f"{window['type']}: {window['start_timestamp']} -> "
            f"{window['end_timestamp']} score={window['selection_score']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
