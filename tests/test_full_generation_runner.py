from __future__ import annotations

import csv
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import build_ml_dataset as ml_builder
import generate_pilot_scenarios as pilot
import run_full_generation as runner
from physics.config import load_parameter_config
from physics.simulator import (
    OUTPUT_COLUMNS,
    load_and_validate_weather_range,
    run_simulation,
)


ROOT = Path(__file__).resolve().parents[1]


def physics_row(timestamp: str) -> dict[str, object]:
    row = {column: 0.0 for column in OUTPUT_COLUMNS}
    row.update(
        {
            "timestamp": timestamp,
            "simulation_id": "test",
            "parameter_set_id": "pa1_full_000_baseline",
        }
    )
    return row


def ml_row(timestamp: str) -> dict[str, object]:
    row = {column: 0.0 for column in ml_builder.CANONICAL_COLUMNS}
    row["timestamp"] = timestamp
    return row


class FullGenerationRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = runner.load_manifest_rows()

    def test_full_runner_dry_run(self) -> None:
        args = runner.build_parser().parse_args(["--dry-run"])
        weather_audit = {
            "status": "PASS",
            "sha256": "weather",
            "rows": 70128,
        }
        with (
            patch.object(runner, "audit_final_manifest", return_value={"status": "PASS"}),
            patch.object(runner, "audit_weather_dataset", return_value=([], weather_audit)),
        ):
            report = runner.execute(args)
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["jobs"], 24)
        self.assertEqual(report["expected_rows_per_job"], 70128)
        self.assertFalse(report["full_mode_executed"])

    def test_full_job_count_and_baseline_once(self) -> None:
        args = runner.build_parser().parse_args(["--full", "--dry-run"])
        jobs = runner.resolve_jobs(args, self.rows)
        identifiers = [job.parameter_set_id for job in jobs]
        self.assertEqual(len(jobs), 24)
        self.assertEqual(identifiers.count("pa1_full_000_baseline"), 1)
        self.assertEqual(sum(job.expected_rows for job in jobs), 1_683_072)
        self.assertTrue(all(job.expected_rows == 70_128 for job in jobs))

    def test_full_weather_row_count_and_leap_days(self) -> None:
        _, audit = runner.audit_weather_dataset()
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["rows"], 70_128)
        self.assertEqual(audit["leap_year_rows"], {"2020": 8784, "2024": 8784})
        self.assertEqual(audit["leap_day_rows"], {"2020": 24, "2024": 24})

    def _cache_fixture(
        self, directory: Path
    ) -> tuple[dict, dict, dict[str, Path]]:
        identifier = "pa1_full_000_baseline"
        paths = runner.scenario_paths(directory, identifier)
        runner.write_csv_atomic(
            paths["physics"], [physics_row("2024-01-01T00:00")], OUTPUT_COLUMNS
        )
        runner.write_csv_atomic(
            paths["ml"], [ml_row("2024-01-01T00:00")], ml_builder.CANONICAL_COLUMNS
        )
        runner.write_json_atomic(paths["config"], {"status": "test"})
        runner.write_json_atomic(paths["validation"], {"status": "PASS"})
        runner.write_json_atomic(paths["ml_metadata"], {"status": "PASS"})
        runner.write_json_atomic(paths["log"], {"status": "PASS"})
        identity = {
            "parameter_set_id": identifier,
            "run_config_hash": "config-a",
            "weather_hash": "weather-a",
            "expected_rows": 1,
        }
        entry = {
            **identity,
            "status": "COMPLETE",
            "physics_hash": runner.sha256_file(paths["physics"]),
            "ml_hash": runner.sha256_file(paths["ml"]),
            "validation_status": "PASS",
        }
        return entry, identity, paths

    def test_resume_complete_skips(self) -> None:
        with TemporaryDirectory() as temporary:
            entry, identity, paths = self._cache_fixture(Path(temporary))
            self.assertEqual(
                runner.cache_decision(entry, identity, paths),
                ("SKIP", "COMPLETE"),
            )

    def test_running_state_not_complete(self) -> None:
        with TemporaryDirectory() as temporary:
            entry, identity, paths = self._cache_fixture(Path(temporary))
            entry["status"] = "RUNNING"
            self.assertEqual(
                runner.cache_decision(entry, identity, paths),
                ("RERUN", "INTERRUPTED"),
            )

    def test_partial_tmp_not_complete(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = runner.scenario_paths(root, "pa1_full_000_baseline")
            paths["physics"].parent.mkdir(parents=True)
            paths["physics"].with_suffix(".csv.tmp").write_text(
                "partial", encoding="utf-8"
            )
            identity = {
                "run_config_hash": "config-a",
                "weather_hash": "weather-a",
                "expected_rows": 1,
            }
            entry = {**identity, "status": "PHYSICS_DONE"}
            self.assertEqual(
                runner.cache_decision(entry, identity, paths),
                ("RERUN", "PARTIAL_TMP"),
            )

    def test_config_hash_mismatch_invalidates_cache(self) -> None:
        with TemporaryDirectory() as temporary:
            entry, identity, paths = self._cache_fixture(Path(temporary))
            identity["run_config_hash"] = "config-b"
            self.assertEqual(
                runner.cache_decision(entry, identity, paths),
                ("RERUN", "CONFIG_MISMATCH"),
            )

    def test_weather_hash_mismatch_invalidates_cache(self) -> None:
        with TemporaryDirectory() as temporary:
            entry, identity, paths = self._cache_fixture(Path(temporary))
            identity["weather_hash"] = "weather-b"
            self.assertEqual(
                runner.cache_decision(entry, identity, paths),
                ("RERUN", "WEATHER_MISMATCH"),
            )

    def test_active_run_lock_refuses_second_process(self) -> None:
        with TemporaryDirectory() as temporary:
            lock_path = Path(temporary) / "run.lock"
            lock_path.write_text(
                json.dumps({"pid": os.getpid()}), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                runner.FullGenerationError, "locked by active PID"
            ):
                with runner.RunLock(lock_path):
                    pass

    def test_atomic_output_commit(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "atomic.csv"
            runner.write_csv_atomic(path, [{"value": "old"}], ("value",))
            runner.write_csv_atomic(path, [{"value": "new"}], ("value",))
            self.assertTrue(path.is_file())
            self.assertFalse(path.with_suffix(".csv.tmp").exists())
            with path.open(encoding="utf-8", newline="") as handle:
                self.assertEqual(list(csv.DictReader(handle)), [{"value": "new"}])

    def test_atomic_output_retries_transient_permission_error(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.tmp"
            destination = root / "destination.json"
            source.write_text("complete", encoding="utf-8")
            real_replace = runner.os.replace
            calls = 0

            def transient_replace(left: Path, right: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise PermissionError("temporary scanner lock")
                real_replace(left, right)

            with (
                patch.object(runner.os, "replace", side_effect=transient_replace),
                patch.object(runner.time, "sleep"),
            ):
                runner.replace_atomic_with_retry(source, destination)
            self.assertEqual(calls, 2)
            self.assertEqual(destination.read_text(encoding="utf-8"), "complete")

    def test_peak_rss_measurement_when_supported(self) -> None:
        measured = runner.peak_rss_bytes()
        if os.name == "nt":
            self.assertIsNotNone(measured)
        if measured is not None:
            self.assertGreater(measured, 0)

    def test_benchmark_2024_row_count(self) -> None:
        args = runner.build_parser().parse_args(["--benchmark", "--dry-run"])
        jobs = runner.resolve_jobs(args, self.rows)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].expected_rows, 8784)
        physics = (
            ROOT
            / "outputs/full_generation_benchmark/run_1/physics"
            / "pa1_full_000_baseline.csv"
        )
        ml_path = (
            ROOT
            / "outputs/full_generation_benchmark/run_1/ml"
            / "pa1_full_000_baseline.csv"
        )
        self.assertEqual(runner.csv_shape(physics), (8784, OUTPUT_COLUMNS))
        self.assertEqual(
            runner.csv_shape(ml_path), (8784, ml_builder.CANONICAL_COLUMNS)
        )

    def test_benchmark_leap_day(self) -> None:
        path = (
            ROOT
            / "outputs/full_generation_benchmark/run_1/physics"
            / "pa1_full_000_baseline.csv"
        )
        with path.open(encoding="utf-8", newline="") as handle:
            saved = list(csv.DictReader(handle))
        leap_day = [row for row in saved if row["timestamp"].startswith("2024-02-29")]
        self.assertEqual(len(saved), 8784)
        self.assertEqual(len(leap_day), 24)

    def test_ml_schema_contract(self) -> None:
        self.assertEqual(
            ml_builder.CANONICAL_COLUMNS,
            (
                "timestamp",
                "air_temperature",
                "air_humidity",
                "soil_temperature",
                "soil_moisture",
                "light_lux",
                "pump_state",
                "fan_state",
                "grow_light_state",
            ),
        )
        path = (
            ROOT
            / "outputs/full_generation_benchmark/run_1/ml"
            / "pa1_full_000_baseline.csv"
        )
        self.assertEqual(runner.csv_shape(path)[1], ml_builder.CANONICAL_COLUMNS)

    def test_physics_features_not_in_ml(self) -> None:
        forbidden = {
            column
            for column in ml_builder.CANONICAL_COLUMNS
            if any(
                fragment in column.lower()
                for fragment in ml_builder.FORBIDDEN_NAME_FRAGMENTS
            )
        }
        self.assertEqual(forbidden, set())

    def test_full_no_llm_dependency(self) -> None:
        forbidden_markers = (
            "import openai",
            "from openai",
            "import anthropic",
            "from anthropic",
            "chat.completions",
            "responses.create",
            "gemini client",
            "llm client",
        )
        execution_files = list(ROOT.glob("*.py")) + list(
            (ROOT / "physics").rglob("*.py")
        )
        findings = []
        for path in execution_files:
            source = path.read_text(encoding="utf-8").lower()
            for marker in forbidden_markers:
                if marker in source:
                    findings.append(f"{path.relative_to(ROOT)}: {marker}")
        self.assertEqual(findings, [])

    def test_benchmark_reproducibility_and_full_stop_gate(self) -> None:
        run_reports = []
        for run_id in ("run_1", "run_2"):
            report = json.loads(
                (
                    ROOT
                    / f"outputs/full_generation_benchmark/{run_id}/validation"
                    / "pa1_full_000_baseline.json"
                ).read_text(encoding="utf-8")
            )
            state = json.loads(
                (
                    ROOT
                    / f"outputs/full_generation_benchmark/{run_id}/state/run_state.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["full_generation_executed"])
            self.assertFalse(state["full_mode_executed"])
            self.assertEqual(
                state["scenarios"]["pa1_full_000_baseline"]["status"],
                "COMPLETE",
            )
            run_reports.append(report)
        self.assertEqual(
            run_reports[0]["files"]["physics_sha256"],
            run_reports[1]["files"]["physics_sha256"],
        )
        self.assertEqual(
            run_reports[0]["files"]["ml_sha256"],
            run_reports[1]["files"]["ml_sha256"],
        )

        summary = json.loads(
            (
                ROOT
                / "outputs/full_generation_benchmark/benchmark_summary.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(summary["full_generation_ready"])
        self.assertFalse(summary["full_generation_executed"])

    def test_continuous_state_chunk_handoff(self) -> None:
        source = load_parameter_config(
            ROOT
            / "outputs/final_parameter_preflight/configs/pa1_full_000_baseline.yaml"
        ).to_model_parameters()
        full_weather, quality = load_and_validate_weather_range(
            ROOT / "nha_trang_weather_2018_2025.csv",
            datetime(2024, 6, 1),
            datetime(2024, 6, 3, 23),
        )
        full_parameters = replace(
            source,
            simulation=replace(
                source.simulation,
                start_timestamp="2024-06-01T00:00",
                duration_days=3,
            ),
        )
        complete = run_simulation(full_weather, full_parameters, weather_quality=quality)

        first_parameters = replace(
            full_parameters,
            simulation=replace(full_parameters.simulation, duration_days=1),
        )
        first = run_simulation(
            full_weather[:25], first_parameters, weather_quality=quality
        )
        second_parameters = replace(
            full_parameters,
            simulation=replace(
                full_parameters.simulation,
                start_timestamp="2024-06-02T00:00",
                duration_days=2,
            ),
        )
        second = run_simulation(
            full_weather[24:],
            second_parameters,
            weather_quality=quality,
            initial_state=first.final_state,
        )
        self.assertEqual(len(first.rows) + len(second.rows), len(complete.rows))
        self.assertEqual(second.initial_state, first.final_state)
        for field in complete.final_state.__dataclass_fields__:
            self.assertAlmostEqual(
                getattr(second.final_state, field),
                getattr(complete.final_state, field),
                places=12,
            )

    def test_full_continuous_state_across_year_boundary(self) -> None:
        source = load_parameter_config(
            ROOT
            / "outputs/final_parameter_preflight/configs/pa1_full_000_baseline.yaml"
        ).to_model_parameters()
        weather, quality = load_and_validate_weather_range(
            ROOT / "nha_trang_weather_2018_2025.csv",
            datetime(2023, 12, 30),
            datetime(2024, 1, 2, 23),
        )
        continuous_parameters = replace(
            source,
            simulation=replace(
                source.simulation,
                start_timestamp="2023-12-30T00:00",
                duration_days=4,
            ),
        )
        continuous = run_simulation(
            weather, continuous_parameters, weather_quality=quality
        )

        first_parameters = replace(
            continuous_parameters,
            simulation=replace(
                continuous_parameters.simulation,
                duration_days=2,
            ),
        )
        first = run_simulation(
            weather[:49], first_parameters, weather_quality=quality
        )
        second_parameters = replace(
            continuous_parameters,
            simulation=replace(
                continuous_parameters.simulation,
                start_timestamp="2024-01-01T00:00",
                duration_days=2,
            ),
        )
        second = run_simulation(
            weather[48:],
            second_parameters,
            weather_quality=quality,
            initial_state=first.final_state,
        )

        self.assertEqual(len(continuous.rows), 96)
        self.assertEqual(continuous.rows, first.rows + second.rows)
        self.assertEqual(second.initial_state, first.final_state)
        self.assertEqual(second.final_state, continuous.final_state)

    def test_june_baseline_numerical_regression(self) -> None:
        config = load_parameter_config(
            ROOT
            / "outputs/final_parameter_preflight/configs/pa1_full_000_baseline.yaml"
        )
        weather, quality = load_and_validate_weather_range(
            ROOT / "nha_trang_weather_2018_2025.csv",
            datetime(2024, 6, 1),
            datetime(2024, 6, 30, 23),
        )
        result = run_simulation(
            weather, config.to_model_parameters(), weather_quality=quality
        )
        with (ROOT / "outputs/greenhouse_simulation_30days.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            reference = list(csv.DictReader(handle))
        comparison = pilot.baseline_reproduction_difference(result.rows, reference)
        self.assertEqual(comparison["status"], "PASS")
        self.assertEqual(comparison["max_absolute_difference"], 0.0)


if __name__ == "__main__":
    unittest.main()
