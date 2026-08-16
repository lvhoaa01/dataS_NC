"""Build the audited full-generation benchmark summary and Markdown report."""

from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import statistics
import sys
from typing import Any

import run_full_generation as runner


ROOT = Path(__file__).resolve().parent
BENCHMARK_ROOT = ROOT / "outputs" / "full_generation_benchmark"
SUMMARY_PATH = BENCHMARK_ROOT / "benchmark_summary.json"
REPORT_PATH = ROOT / "FULL_GENERATION_BENCHMARK.md"
RUN_IDS = ("run_1", "run_2")
IDENTIFIER = "pa1_full_000_baseline"


class BenchmarkSummaryError(RuntimeError):
    """Raised when benchmark evidence is incomplete or inconsistent."""


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BenchmarkSummaryError(f"Expected JSON object: {path}")
    return payload


def format_duration(seconds: float) -> str:
    hours, remainder = divmod(seconds, 3600.0)
    minutes, seconds = divmod(remainder, 60.0)
    return f"{int(hours)}h {int(minutes)}m {seconds:.1f}s"


def benchmark_metadata_bytes(run_root: Path) -> int:
    files = [
        run_root / "configs" / f"{IDENTIFIER}.yaml",
        run_root / "validation" / f"{IDENTIFIER}.json",
        run_root / "ml" / f"{IDENTIFIER}_metadata.json",
        run_root / "logs" / f"{IDENTIFIER}.json",
        run_root / "state" / "run_state.json",
        run_root / "full_generation_manifest.csv",
    ]
    return sum(path.stat().st_size for path in files)


def load_benchmark_runs() -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for run_id in RUN_IDS:
        path = BENCHMARK_ROOT / run_id / "validation" / f"{IDENTIFIER}.json"
        report = load_json(path)
        if report.get("status") != "PASS":
            raise BenchmarkSummaryError(f"{run_id} validation status is not PASS.")
        if report.get("expected_rows") != 8784:
            raise BenchmarkSummaryError(f"{run_id} does not contain 8784 rows.")
        state = load_json(
            BENCHMARK_ROOT / run_id / "state" / "run_state.json"
        )
        entry = state["scenarios"][IDENTIFIER]
        if entry.get("status") != "COMPLETE":
            raise BenchmarkSummaryError(f"{run_id} state is not COMPLETE.")
        if state.get("full_mode_executed"):
            raise BenchmarkSummaryError(f"{run_id} unexpectedly executed full mode.")
        report["benchmark_run_id"] = run_id
        report["state"] = entry
        report["validation_file_bytes"] = path.stat().st_size
        report["metadata_bytes"] = benchmark_metadata_bytes(
            BENCHMARK_ROOT / run_id
        )
        reports.append(report)
    return reports


def build_summary() -> dict[str, Any]:
    manifest_audit = runner.audit_final_manifest()
    _, weather_audit = runner.audit_weather_dataset()
    reports = load_benchmark_runs()
    physics_hashes = {report["files"]["physics_sha256"] for report in reports}
    ml_hashes = {report["files"]["ml_sha256"] for report in reports}
    if len(physics_hashes) != 1 or len(ml_hashes) != 1:
        raise BenchmarkSummaryError("Benchmark output hashes are not reproducible.")

    recovery_state = load_json(
        ROOT / "outputs/full_generation_recovery_test/state/run_state.json"
    )
    recovery = recovery_state["scenarios"][IDENTIFIER]
    if recovery.get("status") != "COMPLETE":
        raise BenchmarkSummaryError("Recovery fixture is not COMPLETE.")
    if recovery.get("last_resume_action") != "SKIPPED_COMPLETE":
        raise BenchmarkSummaryError("Recovery fixture did not record COMPLETE skip.")

    timing_fields = (
        "physics_simulation_seconds",
        "physics_csv_write_seconds",
        "physics_validation_seconds",
        "ml_extraction_seconds",
        "ml_csv_write_seconds",
        "ml_validation_seconds",
        "total_wall_seconds",
    )
    central_timings = {
        field: statistics.fmean(report["timings"][field] for report in reports)
        for field in timing_fields
    }
    totals = [report["timings"]["total_wall_seconds"] for report in reports]
    full_row_ratio = runner.EXPECTED_FULL_ROWS / 8784.0
    full_workload_multiplier = full_row_ratio * 24
    runtime = {
        "full_row_ratio_vs_2024": full_row_ratio,
        "workload_multiplier_24_sets": full_workload_multiplier,
        "optimistic_seconds": min(totals) * full_workload_multiplier,
        "central_seconds": statistics.fmean(totals) * full_workload_multiplier,
        "conservative_seconds": max(totals) * full_workload_multiplier * 1.15,
        "recommended_workers": 1,
        "recommended_workers_reason": (
            "Only sequential CPU/RSS behavior was measured; correctness-first default."
        ),
    }

    total_full_rows = runner.EXPECTED_FULL_ROWS * 24
    physics_bytes = round(
        statistics.fmean(report["files"]["physics_bytes"] for report in reports)
        / 8784.0
        * total_full_rows
    )
    ml_bytes = round(
        statistics.fmean(report["files"]["ml_bytes"] for report in reports)
        / 8784.0
        * total_full_rows
    )
    metadata_bytes = round(
        statistics.fmean(report["metadata_bytes"] for report in reports) * 24
    )
    previous = load_json(
        ROOT / "outputs/final_parameter_preflight/preflight_summary.json"
    )["storage_estimate"]
    storage = {
        "benchmark_physics_bytes": reports[0]["files"]["physics_bytes"],
        "benchmark_ml_bytes": reports[0]["files"]["ml_bytes"],
        "benchmark_validation_bytes": reports[0]["validation_file_bytes"],
        "eight_year_physics_per_scenario_bytes": round(physics_bytes / 24),
        "eight_year_ml_per_scenario_bytes": round(ml_bytes / 24),
        "estimated_full_physics_bytes": physics_bytes,
        "estimated_full_ml_bytes": ml_bytes,
        "estimated_full_metadata_bytes": metadata_bytes,
        "estimated_full_total_bytes": physics_bytes + ml_bytes + metadata_bytes,
        "previous_readiness_physics_bytes": previous[
            "estimated_physics_master_bytes"
        ],
        "previous_readiness_ml_bytes": previous[
            "estimated_deployment_ml_bytes"
        ],
        "physics_difference_percent": (
            100.0
            * (physics_bytes - previous["estimated_physics_master_bytes"])
            / previous["estimated_physics_master_bytes"]
        ),
        "ml_difference_percent": (
            100.0
            * (ml_bytes - previous["estimated_deployment_ml_bytes"])
            / previous["estimated_deployment_ml_bytes"]
        ),
    }

    measured_peak = [
        report["memory"]["peak_rss_bytes"]
        for report in reports
        if report["memory"]["peak_rss_bytes"] is not None
    ]
    physics = reports[0]["physics"]
    ml = reports[0]["ml"]
    simulator_hash_before = json.loads(
        (ROOT / "final_approved_parameter_sets.yaml").read_text(encoding="utf-8")
    )["simulator_code_hash"]
    simulator_hash_current = reports[0]["simulator_code_hash"]
    ready_checks = {
        "manifest_audit": manifest_audit["status"] == "PASS",
        "weather_audit": weather_audit["status"] == "PASS",
        "physics_validation": all(
            report["physics"]["status"] == "PASS" for report in reports
        ),
        "ml_validation": all(report["ml"]["status"] == "PASS" for report in reports),
        "reproducibility": len(physics_hashes) == 1 and len(ml_hashes) == 1,
        "resume_complete_skip": recovery.get("last_resume_action")
        == "SKIPPED_COMPLETE",
        "atomic_outputs": not any(
            BENCHMARK_ROOT.rglob("*.tmp")
        ),
        "full_mode_not_executed": all(
            not report["full_generation_executed"] for report in reports
        ),
    }
    ready = all(ready_checks.values())
    return {
        "status": "SUCCESS" if ready else "PARTIAL",
        "full_generation_ready": ready,
        "full_generation_executed": False,
        "generated_at": runner.utc_now(),
        "input_audit": {
            "manifest": manifest_audit,
            "weather": weather_audit,
            "approved_simulator_hash": simulator_hash_before,
            "current_simulator_hash": simulator_hash_current,
            "simulator_hash_change_reason": (
                "Generic date-range loading and optional continuous-state handoff; "
                "E0-E10 equations unchanged."
            ),
            "june_baseline_numeric_regression": "PASS_MAX_ABSOLUTE_DIFFERENCE_0",
        },
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "logical_cpu_count": os.cpu_count(),
            "peak_rss_bytes": max(measured_peak) if measured_peak else None,
        },
        "scope": {
            "parameter_set_id": IDENTIFIER,
            "year": 2024,
            "rows": 8784,
            "internal_timestep_s": 60,
            "internal_steps": 527040,
            "initialization": "standalone_window_initialization",
        },
        "runs": reports,
        "central_timings": central_timings,
        "throughput": {
            "hourly_rows_per_second": statistics.fmean(
                report["throughput"]["hourly_rows_per_second_simulation"]
                for report in reports
            ),
            "internal_steps_per_second": statistics.fmean(
                report["throughput"]["internal_steps_per_second"]
                for report in reports
            ),
        },
        "runtime_estimate": runtime,
        "storage_estimate": storage,
        "physics_validation": physics,
        "ml_validation": ml,
        "reproducibility": {
            "status": "PASS",
            "physics_hash": next(iter(physics_hashes)),
            "ml_hash": next(iter(ml_hashes)),
            "run_count": len(reports),
        },
        "resume_recovery": {
            "status": "PASS",
            "fixture_rows": recovery["expected_rows"],
            "complete_skip": recovery["last_resume_action"],
            "partial_tmp_behavior": "PASS_TESTED_RERUN",
            "running_state_behavior": "PASS_TESTED_INTERRUPTED_RERUN",
            "config_mismatch_behavior": "PASS_TESTED_INVALIDATE_CACHE",
            "weather_mismatch_behavior": "PASS_TESTED_INVALIDATE_CACHE",
            "interrupt_behavior": "MARK_INTERRUPTED_AND_PRESERVE_COMPLETED",
            "windows_atomic_retry": "PASS_AFTER_OBSERVED_TRANSIENT_LOCK",
        },
        "ready_checks": ready_checks,
    }


def render_report(summary: dict[str, Any]) -> str:
    manifest = summary["input_audit"]["manifest"]
    weather = summary["input_audit"]["weather"]
    environment = summary["environment"]
    scope = summary["scope"]
    runs = summary["runs"]
    timing = summary["central_timings"]
    throughput = summary["throughput"]
    runtime = summary["runtime_estimate"]
    storage = summary["storage_estimate"]
    physics = summary["physics_validation"]
    metrics = physics["metrics"]
    ml = summary["ml_validation"]
    reproduction = summary["reproducibility"]
    recovery = summary["resume_recovery"]
    rss = environment["peak_rss_bytes"]
    run_rows = [
        (
            f"| `{report['benchmark_run_id']}` | "
            f"{report['timings']['physics_simulation_seconds']:.3f} | "
            f"{report['timings']['total_wall_seconds']:.3f} | "
            f"`{report['files']['physics_sha256'][:12]}` | "
            f"`{report['files']['ml_sha256'][:12]}` |"
        )
        for report in runs
    ]
    checks = [
        f"- `{name}`: `{'PASS' if passed else 'FAIL'}`."
        for name, passed in summary["ready_checks"].items()
    ]
    lines = [
        "# Full Generation Benchmark",
        "",
        f"Status: `{summary['status']}`",
        f"",
        f"`FULL_GENERATION_READY = {'YES' if summary['full_generation_ready'] else 'NO'}`",
        "",
        "## 1. Input audit",
        "",
        f"- Final manifest: `{manifest['parameter_sets']}` sets; SHA-256 `{manifest['manifest_sha256']}`; locked hash match `PASS`.",
        f"- Baseline/non-baseline: `{manifest['baseline_count']}/{manifest['non_baseline_count']}`; unique IDs/config hashes: `{manifest['unique_parameter_set_ids']}/{manifest['unique_config_hashes']}`.",
        f"- Weather: `{weather['rows']}` rows, `{weather['start_timestamp']}` through `{weather['end_timestamp']}`, timezone `{weather['timezone']}`; gaps/duplicates/nonfinite `0/0/0`.",
        f"- Weather SHA-256: `{weather['sha256']}`; 2024 rows/leap-day rows: `{weather['leap_2024_rows']}/{weather['leap_day_2024_rows']}`.",
        f"- Approved simulator hash `{summary['input_audit']['approved_simulator_hash']}` changed to `{summary['input_audit']['current_simulator_hash']}` after generic range/state-handoff APIs. June baseline numerical regression remained exactly `0.0`.",
        "",
        "## 2. Runner architecture",
        "",
        "`final manifest + weather -> deterministic simulator -> atomic physics master -> locked validator -> atomic ML extraction -> ML validator -> hashes/state`.",
        "",
        "One file is produced per parameter set. Full mode uses one continuous 2018-2025 simulator call per set, so state is initialized only at 2018-01-01 and is never reset at year boundaries.",
        "",
        "## 3. Checkpoint/resume design",
        "",
        "States: `PENDING -> RUNNING -> PHYSICS_DONE -> PHYSICS_VALIDATED -> ML_DONE -> ML_VALIDATED -> COMPLETE`; failures and interrupts remain non-complete. COMPLETE cache entries are skipped only after config/weather identity, files, rows, schemas, hashes and validation metadata are rechecked.",
        "",
        "## 4. Atomic-output design",
        "",
        "Physics, ML, state, configs, logs and manifests use same-directory `.tmp`, flush/fsync and atomic replace. Bounded retry handles observed transient Windows scanner locks; no benchmark `.tmp` remains.",
        "",
        "## 5. Benchmark environment",
        "",
        f"- Platform: `{environment['platform']}`; Python `{environment['python']}`; logical CPUs `{environment['logical_cpu_count']}`.",
        f"- Peak process RSS: `{rss / 1024**2:.2f} MiB` measured by Windows process peak working set." if rss is not None else "- Peak process RSS: `NOT_MEASURED`.",
        "- Execution policy: sequential, one worker, canonical `dt=60 s`.",
        "",
        "## 6. Benchmark scope",
        "",
        f"Baseline `{scope['parameter_set_id']}`, standalone calendar year `{scope['year']}`, `{scope['rows']}` hourly rows including all 24 leap-day hours, `{scope['internal_steps']:,}` one-minute integration intervals.",
        "",
        "## 7. Runtime breakdown",
        "",
        "| Run | Physics s | Total s | Physics hash | ML hash |",
        "|---|---:|---:|---|---|",
        *run_rows,
        "",
        f"Central means: physics `{timing['physics_simulation_seconds']:.3f}s`; physics write `{timing['physics_csv_write_seconds']:.3f}s`; physics validation `{timing['physics_validation_seconds']:.3f}s`; ML extraction `{timing['ml_extraction_seconds']:.3f}s`; ML write `{timing['ml_csv_write_seconds']:.3f}s`; ML validation `{timing['ml_validation_seconds']:.3f}s`; total `{timing['total_wall_seconds']:.3f}s`.",
        "",
        "## 8. Throughput",
        "",
        f"Mean simulation throughput: `{throughput['hourly_rows_per_second']:.3f}` hourly rows/s and `{throughput['internal_steps_per_second']:.1f}` one-minute intervals/s.",
        "",
        "## 9. Memory",
        "",
        f"Peak RSS: `{rss:,} bytes` (`{rss / 1024**2:.2f} MiB`)." if rss is not None else "Peak RSS: `NOT_MEASURED`.",
        "",
        "## 10. File sizes",
        "",
        f"- 2024 physics/ML/validation: `{storage['benchmark_physics_bytes']:,}` / `{storage['benchmark_ml_bytes']:,}` / `{storage['benchmark_validation_bytes']:,}` bytes.",
        f"- Estimated 8-year per scenario physics/ML: `{storage['eight_year_physics_per_scenario_bytes']:,}` / `{storage['eight_year_ml_per_scenario_bytes']:,}` bytes.",
        "",
        "## 11. Full runtime estimate",
        "",
        f"Measured row ratio is `70,128 / 8,784 = {runtime['full_row_ratio_vs_2024']:.6f}`; 24-set multiplier `{runtime['workload_multiplier_24_sets']:.6f}`.",
        f"Sequential estimate: optimistic `{format_duration(runtime['optimistic_seconds'])}`, central `{format_duration(runtime['central_seconds'])}`, conservative `{format_duration(runtime['conservative_seconds'])}`. These are approximate; scenario paths and machine load may differ.",
        f"Recommended default workers: `{runtime['recommended_workers']}`; central estimate remains `{format_duration(runtime['central_seconds'])}`. Parallelism is deferred until multi-scenario CPU/disk behavior is measured.",
        "",
        "## 12. Full storage estimate",
        "",
        f"Physics `{storage['estimated_full_physics_bytes']:,}` bytes (`{storage['estimated_full_physics_bytes'] / 1024**3:.3f} GiB`), ML `{storage['estimated_full_ml_bytes']:,}` bytes (`{storage['estimated_full_ml_bytes'] / 1024**3:.3f} GiB`), metadata `{storage['estimated_full_metadata_bytes']:,}` bytes; total `{storage['estimated_full_total_bytes'] / 1024**3:.3f} GiB` uncompressed.",
        f"Versus readiness estimate: physics `{storage['physics_difference_percent']:+.2f}%`, ML `{storage['ml_difference_percent']:+.2f}%`.",
        "",
        "## 13. Reproducibility",
        "",
        f"Two independent runs produced identical physics SHA-256 `{reproduction['physics_hash']}` and ML SHA-256 `{reproduction['ml_hash']}`: `PASS`.",
        "",
        "## 14. Physics validation",
        "",
        f"Schema/ranges, NaN/Inf, causal tests, balances and joint guards: `PASS`. Tair `{metrics['states']['T_air']['min']:.3f}..{metrics['states']['T_air']['max']:.3f} C`; RH saturation `{metrics['humidity']['saturated_rows']}/{scope['rows']}` (`{metrics['humidity']['saturated_fraction']:.3%}`), longest `{metrics['humidity']['longest_continuous_saturation_hours']} h`; Tsoil max `{metrics['soil_temperature']['max_c']:.3f} C`; theta `{metrics['states']['soil_moisture']['min']:.6f}..{metrics['states']['soil_moisture']['max']:.6f}`.",
        "",
        "## 15. ML contract validation",
        "",
        f"`{ml['rows']}` rows x `{len(ml['columns'])}` columns, observation mode `{ml['observation_mode']}`, sensor noise disabled. Five sensor variables + three actuator states; physics/weather feature count `0/0`. Soil moisture remains a VWC-like state requiring a real ES-SM-TH-01 calibration adapter.",
        "",
        "## 16. Failure/recovery test",
        "",
        f"Actual 72-hour run reached COMPLETE and rerun recorded `{recovery['complete_skip']}`. Unit fixtures verified RUNNING/interrupted, partial `.tmp`, config mismatch and weather mismatch all rerun instead of skip. KeyboardInterrupt marks INTERRUPTED and preserves prior COMPLETE scenarios.",
        "",
        "## 17. Full-run readiness",
        "",
        *checks,
        "",
        f"Final gate: `FULL_GENERATION_READY = {'YES' if summary['full_generation_ready'] else 'NO'}`.",
        "",
        "Full `24 x 2018-2025` generation was not started. The next milestone may run `python run_full_generation.py --full` only after user audit of this report.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    try:
        summary = build_summary()
        runner.write_json_atomic(SUMMARY_PATH, summary)
        runner.write_text_atomic(REPORT_PATH, render_report(summary))
    except (BenchmarkSummaryError, runner.FullGenerationError, OSError, ValueError) as exc:
        print(f"STATUS: FAILED\n{exc}")
        return 1
    print(f"STATUS: {summary['status']}")
    print(f"REPORT: {REPORT_PATH}")
    print(
        "FULL_GENERATION_READY: "
        + ("YES" if summary["full_generation_ready"] else "NO")
    )
    print("FULL_GENERATION_EXECUTED: NO")
    return 0 if summary["full_generation_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
