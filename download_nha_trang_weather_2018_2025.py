#!/usr/bin/env python3
"""
Download and validate the RAW historical weather driver dataset for
Nha Trang, Vietnam (2018-2025) from Open-Meteo Historical Weather API.

This script does not generate greenhouse synthetic data and does not simulate
inside-greenhouse variables. It updates production files only after the full
download and validation pass.

Outputs replaced atomically after validation:
  nha_trang_weather_2018_2025.csv
  nha_trang_weather_2018_2025_metadata.txt

No third-party Python packages are required.
"""

import csv
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path


BASE_URL = "https://archive-api.open-meteo.com/v1/archive"
DOCUMENTATION_URL = "https://open-meteo.com/en/docs/historical-weather-api"

LOCATION_NAME = "Nha Trang, Vietnam"
LATITUDE = 12.24507
LONGITUDE = 109.19432
TIMEZONE = "Asia/Ho_Chi_Minh"

START_YEAR = 2018
END_YEAR = 2025
START_DATE = f"{START_YEAR}-01-01"
END_DATE = f"{END_YEAR}-12-31"
EXPECTED_ROWS = 70128
EXPECTED_FIRST_TIMESTAMP = "2018-01-01T00:00"
EXPECTED_LAST_TIMESTAMP = "2025-12-31T23:00"

MODEL = "era5_seamless"
CELL_SELECTION = "land"
WIND_SPEED_UNIT = "ms"
MAX_RETRIES = 4

HOURLY_VARIABLES = [
    # Core forcing for physics simulator
    "temperature_2m",
    "relative_humidity_2m",
    "shortwave_radiation",
    "wind_speed_10m",
    "surface_pressure",
    # Radiation decomposition / QA
    "direct_radiation",
    "diffuse_radiation",
    # Humidity / evapotranspiration QA
    "dew_point_2m",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
    # External land context only
    "soil_temperature_0_to_7cm",
    "soil_moisture_0_to_7cm",
]

TIME_COLUMN = "timestamp"
CSV_COLUMNS = [TIME_COLUMN] + HOURLY_VARIABLES

OUT_CSV = Path("nha_trang_weather_2018_2025.csv")
OUT_METADATA = Path("nha_trang_weather_2018_2025_metadata.txt")
TEMP_CSV = Path("nha_trang_weather_2018_2025.csv.tmp")
TEMP_METADATA = Path("nha_trang_weather_2018_2025_metadata.txt.tmp")


class ValidationError(RuntimeError):
    pass


def fetch_year(year: int) -> dict:
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": TIMEZONE,
        "models": MODEL,
        "cell_selection": CELL_SELECTION,
        "wind_speed_unit": WIND_SPEED_UNIT,
    }
    url = BASE_URL + "?" + urllib.parse.urlencode(params)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "SmartGardenWeatherDownloader/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))

            if "hourly" not in payload:
                reason = payload.get("reason", payload)
                raise RuntimeError(
                    f"Open-Meteo returned no hourly data for {year}: {reason}"
                )

            return payload
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                wait_seconds = 2 ** attempt
                print(f"  Attempt {attempt} failed: {exc}")
                print(f"  Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)

    raise RuntimeError(f"Failed to download {year} after retries: {last_error}")


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def validate_year_payload(year: int, payload: dict) -> dict:
    hourly = payload["hourly"]
    required_api_columns = ["time"] + HOURLY_VARIABLES
    missing_columns = [column for column in required_api_columns if column not in hourly]
    if missing_columns:
        raise ValidationError(f"Year {year} missing API columns: {missing_columns}")

    lengths = {column: len(hourly[column]) for column in required_api_columns}
    if len(set(lengths.values())) != 1:
        raise ValidationError(f"Year {year} column length mismatch: {lengths}")

    times = hourly["time"]
    missing = {
        variable: sum(value is None for value in hourly[variable])
        for variable in HOURLY_VARIABLES
    }
    report = {
        "year": year,
        "rows": len(times),
        "first_timestamp": times[0] if times else None,
        "last_timestamp": times[-1] if times else None,
        "missing": missing,
        "units": payload.get("hourly_units", {}),
        "api_metadata": {
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "elevation": payload.get("elevation"),
            "timezone": payload.get("timezone"),
            "utc_offset_seconds": payload.get("utc_offset_seconds"),
            "model_requested": MODEL,
        },
    }

    print(f"  year: {year}")
    print(f"  rows: {report['rows']:,}")
    print(f"  first_timestamp: {report['first_timestamp']}")
    print(f"  last_timestamp: {report['last_timestamp']}")
    print(f"  missing_values: {missing}")
    return report


def payload_to_rows(payload: dict) -> list[dict]:
    hourly = payload["hourly"]
    rows = []
    for index, timestamp in enumerate(hourly["time"]):
        row = {TIME_COLUMN: timestamp}
        for variable in HOURLY_VARIABLES:
            row[variable] = hourly[variable][index]
        rows.append(row)
    return rows


def collect_missing(rows: list[dict]) -> dict:
    row_count = len(rows)
    missing = {}
    for column in CSV_COLUMNS:
        count = sum(row[column] is None for row in rows)
        missing[column] = {
            "count": count,
            "percentage": (count / row_count * 100) if row_count else 0.0,
        }
    return missing


def find_timestamp_gaps(rows: list[dict]) -> list[dict]:
    gaps = []
    for previous, current in zip(rows, rows[1:]):
        previous_dt = parse_timestamp(previous[TIME_COLUMN])
        current_dt = parse_timestamp(current[TIME_COLUMN])
        delta_hours = (current_dt - previous_dt).total_seconds() / 3600
        if delta_hours != 1:
            gaps.append(
                {
                    "from": previous[TIME_COLUMN],
                    "to": current[TIME_COLUMN],
                    "delta_hours": delta_hours,
                }
            )
    return gaps


def percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (
        position - lower
    )


def describe(values: list) -> dict:
    numeric_values = [float(value) for value in values if value is not None]
    numeric_values.sort()
    count = len(numeric_values)
    if not numeric_values:
        return {
            "count": 0,
            "mean": None,
            "std": None,
            "min": None,
            "25%": None,
            "50%": None,
            "75%": None,
            "max": None,
        }
    return {
        "count": count,
        "mean": statistics.fmean(numeric_values),
        "std": statistics.stdev(numeric_values) if count > 1 else 0.0,
        "min": numeric_values[0],
        "25%": percentile(numeric_values, 0.25),
        "50%": percentile(numeric_values, 0.50),
        "75%": percentile(numeric_values, 0.75),
        "max": numeric_values[-1],
    }


def check_range(rows: list[dict], column: str, predicate, rule: str) -> dict:
    violations = [
        {"timestamp": row[TIME_COLUMN], "value": row[column]}
        for row in rows
        if row[column] is not None and not predicate(float(row[column]))
    ]
    return {
        "rule": rule,
        "violations": len(violations),
        "examples": violations[:10],
    }


def run_sanity_checks(rows: list[dict]) -> dict:
    return {
        "relative_humidity_2m": check_range(
            rows,
            "relative_humidity_2m",
            lambda value: 0 <= value <= 100,
            "0 <= relative_humidity_2m <= 100",
        ),
        "shortwave_radiation": check_range(
            rows,
            "shortwave_radiation",
            lambda value: value >= 0,
            "shortwave_radiation >= 0",
        ),
        "direct_radiation": check_range(
            rows,
            "direct_radiation",
            lambda value: value >= 0,
            "direct_radiation >= 0",
        ),
        "diffuse_radiation": check_range(
            rows,
            "diffuse_radiation",
            lambda value: value >= 0,
            "diffuse_radiation >= 0",
        ),
        "surface_pressure": check_range(
            rows,
            "surface_pressure",
            lambda value: value > 0,
            "surface_pressure > 0",
        ),
        "wind_speed_10m": check_range(
            rows,
            "wind_speed_10m",
            lambda value: value >= 0,
            "wind_speed_10m >= 0",
        ),
        "soil_moisture_0_to_7cm": check_range(
            rows,
            "soil_moisture_0_to_7cm",
            lambda value: 0 <= value <= 1,
            "0 <= soil_moisture_0_to_7cm <= 1",
        ),
    }


def get_units(units_from_api: dict) -> dict:
    units = {TIME_COLUMN: units_from_api.get("time")}
    units.update({variable: units_from_api.get(variable) for variable in HOURLY_VARIABLES})
    return units


def validate_units(units: dict) -> list[str]:
    expected = {
        "temperature_2m": "°C",
        "relative_humidity_2m": "%",
        "shortwave_radiation": "W/m²",
        "direct_radiation": "W/m²",
        "diffuse_radiation": "W/m²",
        "wind_speed_10m": "m/s",
        "surface_pressure": "hPa",
        "dew_point_2m": "°C",
        "vapour_pressure_deficit": "kPa",
        "et0_fao_evapotranspiration": "mm",
        "soil_temperature_0_to_7cm": "°C",
        "soil_moisture_0_to_7cm": "m³/m³",
    }
    issues = []
    for column, expected_unit in expected.items():
        actual = units.get(column)
        if actual != expected_unit:
            issues.append(f"{column}: expected {expected_unit!r}, got {actual!r}")
    return issues


def build_summary(rows: list[dict], year_reports: list[dict], units: dict) -> dict:
    timestamps = [row[TIME_COLUMN] for row in rows]
    timestamp_counts = Counter(timestamps)
    duplicate_count = sum(count - 1 for count in timestamp_counts.values() if count > 1)
    duplicate_examples = [
        {"timestamp": timestamp, "count": count}
        for timestamp, count in timestamp_counts.items()
        if count > 1
    ][:10]

    missing = collect_missing(rows)
    sanity_checks = run_sanity_checks(rows)
    statistics_summary = {
        variable: describe([row[variable] for row in rows])
        for variable in HOURLY_VARIABLES
    }
    timestamp_gaps = find_timestamp_gaps(rows)
    unit_issues = validate_units(units)
    required_columns_present = all(column in CSV_COLUMNS for column in [TIME_COLUMN] + HOURLY_VARIABLES)

    summary = {
        "source": {
            "name": "Open-Meteo Historical Weather API",
            "endpoint": BASE_URL,
            "documentation": DOCUMENTATION_URL,
            "selected_reanalysis_model": MODEL,
            "cell_selection": CELL_SELECTION,
        },
        "location": {
            "name": LOCATION_NAME,
            "latitude": LATITUDE,
            "longitude": LONGITUDE,
            "timezone": TIMEZONE,
        },
        "period": {
            "start": START_DATE,
            "end": END_DATE,
            "temporal_resolution": "hourly",
        },
        "api_configuration": {
            "model": MODEL,
            "variables": HOURLY_VARIABLES,
            "timezone": TIMEZONE,
            "wind_speed_unit": WIND_SPEED_UNIT,
        },
        "columns": CSV_COLUMNS,
        "units": units,
        "rows": len(rows),
        "expected_rows": EXPECTED_ROWS,
        "first_timestamp": timestamps[0] if timestamps else None,
        "last_timestamp": timestamps[-1] if timestamps else None,
        "timestamp_monotonic_increasing": timestamps == sorted(timestamps),
        "duplicates": duplicate_count,
        "duplicate_examples": duplicate_examples,
        "timestamp_gaps": timestamp_gaps,
        "missing": missing,
        "total_missing_values": sum(item["count"] for item in missing.values()),
        "statistics": statistics_summary,
        "sanity_checks": sanity_checks,
        "unit_issues": unit_issues,
        "required_columns_present": required_columns_present,
        "year_reports": year_reports,
        "api_returned_metadata_by_year": [
            {"year": report["year"], **report["api_metadata"]}
            for report in year_reports
        ],
        "download_update_timestamp": datetime.now().isoformat(timespec="seconds"),
        "notes": [
            "This is raw historical reanalysis/model-based weather data, not greenhouse sensor data.",
            "Open-Meteo soil temperature/moisture represent external reanalysis land-surface conditions and are NOT greenhouse pot/root-zone sensor states.",
            "Open-Meteo hourly solar-radiation values follow Historical Weather API semantics; documentation notes solar radiation is averaged over the past hour, not an instantaneous sensor reading.",
        ],
    }
    summary["validation_errors"] = collect_validation_errors(summary)
    summary["validation_status"] = "PASS" if not summary["validation_errors"] else "FAIL"
    return summary


def collect_validation_errors(summary: dict) -> list[str]:
    errors = []
    if summary["rows"] != EXPECTED_ROWS:
        errors.append(f"row count {summary['rows']} != {EXPECTED_ROWS}")
    if summary["first_timestamp"] != EXPECTED_FIRST_TIMESTAMP:
        errors.append(
            f"first timestamp {summary['first_timestamp']} != {EXPECTED_FIRST_TIMESTAMP}"
        )
    if summary["last_timestamp"] != EXPECTED_LAST_TIMESTAMP:
        errors.append(
            f"last timestamp {summary['last_timestamp']} != {EXPECTED_LAST_TIMESTAMP}"
        )
    if not summary["timestamp_monotonic_increasing"]:
        errors.append("timestamps are not monotonic increasing")
    if summary["duplicates"] != 0:
        errors.append(f"duplicate timestamps: {summary['duplicates']}")
    if summary["timestamp_gaps"]:
        errors.append(f"timestamp gaps: {len(summary['timestamp_gaps'])}")
    if not summary["required_columns_present"]:
        errors.append("not all required columns are present")
    if summary["total_missing_values"] != 0:
        errors.append(f"missing values: {summary['total_missing_values']}")
    for column, result in summary["sanity_checks"].items():
        if result["violations"]:
            errors.append(f"{column} sanity violations: {result['violations']}")
    if summary["unit_issues"]:
        errors.extend(f"unit issue: {issue}" for issue in summary["unit_issues"])
    return errors


def format_number(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def format_table(headers: list[str], rows: list[list]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(format_number(value)))
    lines = []
    lines.append("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    lines.append("  ".join("-" * width for width in widths))
    for row in rows:
        lines.append(
            "  ".join(format_number(value).ljust(widths[index]) for index, value in enumerate(row))
        )
    return "\n".join(lines)


def metadata_text(summary: dict) -> str:
    units_rows = [[column, summary["units"].get(column, "")] for column in CSV_COLUMNS]
    missing_rows = [
        [column, item["count"], item["percentage"]]
        for column, item in summary["missing"].items()
    ]
    stats_rows = [
        [
            column,
            values["count"],
            values["mean"],
            values["std"],
            values["min"],
            values["25%"],
            values["50%"],
            values["75%"],
            values["max"],
        ]
        for column, values in summary["statistics"].items()
    ]
    sanity_rows = [
        [column, result["rule"], result["violations"], json.dumps(result["examples"], ensure_ascii=False)]
        for column, result in summary["sanity_checks"].items()
    ]

    return f"""NHA TRANG RAW HISTORICAL WEATHER DATASET 2018-2025
==================================================

source:
Open-Meteo Historical Weather API

endpoint:
{BASE_URL}

documentation:
{DOCUMENTATION_URL}

location:
{LOCATION_NAME}

latitude:
{LATITUDE}

longitude:
{LONGITUDE}

timezone:
{TIMEZONE}

start:
{START_DATE}

end:
{END_DATE}

selected reanalysis model:
{MODEL}

cell_selection:
{CELL_SELECTION}

wind_speed_unit request:
{WIND_SPEED_UNIT}

temporal resolution:
hourly

variables:
{os.linesep.join("- " + variable for variable in HOURLY_VARIABLES)}

units returned by API:
{format_table(["column", "unit"], units_rows)}

number of rows:
{summary["rows"]}

number of columns:
{len(CSV_COLUMNS)}

first timestamp:
{summary["first_timestamp"]}

last timestamp:
{summary["last_timestamp"]}

duplicate timestamps:
{summary["duplicates"]}

timestamp gaps:
{json.dumps(summary["timestamp_gaps"], ensure_ascii=False, indent=2)}

missing values:
{format_table(["column", "missing_count", "missing_percentage"], missing_rows)}

basic statistics:
{format_table(["column", "count", "mean", "std", "min", "25%", "50%", "75%", "max"], stats_rows)}

physical sanity checks:
{format_table(["column", "rule", "violations", "examples"], sanity_rows)}

unit issues:
{json.dumps(summary["unit_issues"], ensure_ascii=False, indent=2)}

api returned metadata by year:
{json.dumps(summary["api_returned_metadata_by_year"], ensure_ascii=False, indent=2)}

download/update timestamp:
{summary["download_update_timestamp"]}

validation status:
{summary["validation_status"]}

validation errors:
{json.dumps(summary["validation_errors"], ensure_ascii=False, indent=2)}

provenance notes:
- This dataset contains historical reanalysis/model-based weather data retrieved from Open-Meteo.
- It is not greenhouse sensor measurement data.
- Open-Meteo soil temperature/moisture represent external reanalysis land-surface conditions and are NOT greenhouse pot/root-zone sensor states.
- temperature_2m and relative_humidity_2m are outdoor weather variables, not inside-greenhouse state variables.
- Open-Meteo hourly solar-radiation values follow Historical Weather API semantics; documentation notes solar radiation is averaged over the past hour, not an instantaneous sensor reading.
- No filling, interpolation, clipping, radiation-to-lux conversion, greenhouse simulation, or synthetic greenhouse variable generation was performed.
"""


def write_temp_outputs(rows: list[dict], summary: dict) -> None:
    with TEMP_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    TEMP_METADATA.write_text(metadata_text(summary), encoding="utf-8")


def atomic_replace_outputs() -> None:
    TEMP_CSV.replace(OUT_CSV)
    TEMP_METADATA.replace(OUT_METADATA)


def cleanup_temp_outputs() -> None:
    for path in [TEMP_CSV, TEMP_METADATA]:
        if path.exists():
            path.unlink()


def print_summary(summary: dict) -> None:
    print()
    print("Dataset validation")
    print(f"  rows: {summary['rows']:,} / expected {EXPECTED_ROWS:,}")
    print(f"  columns: {len(CSV_COLUMNS)}")
    print(f"  first timestamp: {summary['first_timestamp']}")
    print(f"  last timestamp: {summary['last_timestamp']}")
    print(f"  duplicates: {summary['duplicates']}")
    print(f"  missing values: {summary['total_missing_values']}")
    print(f"  hourly gaps: {len(summary['timestamp_gaps'])}")
    print(f"  validation status: {summary['validation_status']}")

    print()
    print("Units returned by API")
    for column in CSV_COLUMNS:
        print(f"  {column}: {summary['units'].get(column)}")

    print()
    print("Basic statistics")
    stats_rows = [
        [
            column,
            values["count"],
            values["mean"],
            values["std"],
            values["min"],
            values["25%"],
            values["50%"],
            values["75%"],
            values["max"],
        ]
        for column, values in summary["statistics"].items()
    ]
    print(format_table(["column", "count", "mean", "std", "min", "25%", "50%", "75%", "max"], stats_rows))

    if summary["validation_errors"]:
        print()
        print("Validation errors")
        for error in summary["validation_errors"]:
            print(f"  - {error}")


def main() -> int:
    cleanup_temp_outputs()
    all_rows = []
    year_reports = []
    units_by_year = []

    try:
        for year in range(START_YEAR, END_YEAR + 1):
            print(f"Downloading {year}...")
            payload = fetch_year(year)
            report = validate_year_payload(year, payload)
            year_reports.append(report)
            units_by_year.append(report["units"])
            all_rows.extend(payload_to_rows(payload))
            print()

        rows = sorted(all_rows, key=lambda row: row[TIME_COLUMN])
        units = get_units(units_by_year[0] if units_by_year else {})
        for index, yearly_units in enumerate(units_by_year[1:], start=START_YEAR + 1):
            if yearly_units != units_by_year[0]:
                raise ValidationError(f"hourly_units differ in year {index}")

        summary = build_summary(rows, year_reports, units)
        print_summary(summary)

        if summary["validation_status"] != "PASS":
            cleanup_temp_outputs()
            print()
            print("FAILED: validation did not pass; production dataset was not replaced.")
            return 1

        write_temp_outputs(rows, summary)
        atomic_replace_outputs()

        print()
        print("SUCCESS: production dataset safely replaced.")
        print(f"CSV: {OUT_CSV.resolve()}")
        print(f"Metadata: {OUT_METADATA.resolve()}")
        return 0
    except Exception as exc:
        cleanup_temp_outputs()
        print()
        print(f"FAILED: {exc}")
        print("Production dataset was not replaced.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
