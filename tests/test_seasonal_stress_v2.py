from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import build_parameter_manifest_v2 as manifest_v2
import generate_final_parameter_sets as sampling
import generate_pilot_scenarios as pilot
import run_full_generation as runner
import seasonal_stress_preflight as seasonal


ROOT = Path(__file__).resolve().parents[1]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class SeasonalStressV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v2_rows = load_csv(manifest_v2.V2_CSV)
        cls.v2_machine = json.loads(manifest_v2.V2_YAML.read_text(encoding="utf-8"))
        cls.baseline = json.loads(
            (seasonal.VALIDATION_DIR / "pa1_full_000_baseline.json").read_text(
                encoding="utf-8"
            )
        )
        cls.failure = json.loads(
            (seasonal.VALIDATION_DIR / "pa1_full_006.json").read_text(
                encoding="utf-8"
            )
        )

    def test_humid_window_detects_known_failure_006(self) -> None:
        humid = next(
            item for item in self.failure["windows"] if item["window_type"] == "HUMID_STRESS"
        )
        self.assertEqual(self.failure["full_horizon_status"], "FULL_HORIZON_REJECTED")
        self.assertEqual(self.failure["seasonal_preflight_status"], "SEASONAL_PREFLIGHT_FAIL")
        self.assertEqual(humid["status"], "FAIL")
        self.assertGreater(humid["metrics"]["humidity"]["saturated_fraction"], 0.05)

    def test_baseline_passes_seasonal_preflight(self) -> None:
        self.assertEqual(self.baseline["seasonal_preflight_status"], "SEASONAL_PREFLIGHT_PASS")
        self.assertTrue(all(item["status"] == "PASS" for item in self.baseline["windows"]))

    def test_warmup_state_continuity(self) -> None:
        for report in (self.baseline, self.failure):
            for window in report["windows"]:
                handoff = window["state_handoff"]
                self.assertTrue(handoff["exact_match"])
                self.assertEqual(
                    handoff["warmup_final_state"], handoff["stress_initial_state"]
                )

    def test_v1_manifest_preserved(self) -> None:
        self.assertEqual(pilot.sha256_file(manifest_v2.V1_CSV), manifest_v2.V1_LOCKED_HASH)
        self.assertTrue(manifest_v2.V1_YAML.is_file())
        self.assertTrue(manifest_v2.V1_REPORT.is_file())

    def test_retained_full_pass_hashes_unchanged(self) -> None:
        windows = seasonal.load_windows()
        audit = manifest_v2.audit_v1_evidence(
            seasonal.load_v1_rows(), windows["weather_hash"]
        )
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(len(audit["retained"]), 6)
        self.assertTrue(
            all(item["cache_audit"] == "SKIP/COMPLETE" for item in audit["retained"])
        )

    def test_rejected_full_horizon_not_eligible(self) -> None:
        identifiers = {row["parameter_set_id"] for row in self.v2_rows}
        self.assertNotIn("pa1_full_006", identifiers)
        self.assertEqual(self.failure["classification"], "REJECTED_FULL_HORIZON_V1")

    def test_replacement_candidate_deterministic(self) -> None:
        replacements = [row for row in self.v2_rows if row["origin"] == "V2_REPLACEMENT"]
        expected_raw = [24, 25, 26, 28, 29, 31, 33, 34, 35, 52]
        self.assertEqual([int(row["raw_candidate_index"]) for row in replacements], expected_raw)
        joint_space = json.loads(sampling.JOINT_SPACE_PATH.read_text(encoding="utf-8"))
        samples = {}
        for item in sampling.iter_lhs_candidates(joint_space):
            raw_index = int(item["raw_candidate_index"])
            if raw_index > max(expected_raw):
                break
            samples[raw_index] = item
        for row in replacements:
            sample = samples[int(row["raw_candidate_index"])]["parameters"]
            self.assertEqual(float(row["C_d"]), sample["C_d"])
            self.assertEqual(float(row["eta_s"]), sample["eta_s"])
            self.assertEqual(float(row["C_s_J_K"]), sample["C_s"])
            self.assertEqual(
                float(row["irrigation_flow_L_h"]), sample["irrigation_flow_L_h"]
            )
            self.assertEqual(float(row["ET_scale"]), sample["ET_scale"])

    def test_v2_has_exactly_24_eligible_sets(self) -> None:
        self.assertEqual(len(self.v2_rows), 24)
        self.assertEqual(
            sum(row["parameter_set_id"] == "pa1_full_000_baseline" for row in self.v2_rows),
            1,
        )
        self.assertTrue(
            all(row["eligibility_status"] == "ELIGIBLE_FULL_RUN" for row in self.v2_rows)
        )
        self.assertEqual(self.v2_machine["parameter_set_count"], 24)
        self.assertEqual(self.v2_machine["companion_csv_sha256"], pilot.sha256_file(manifest_v2.V2_CSV))

    def test_no_duplicate_config_hashes(self) -> None:
        hashes = [row["config_hash"] for row in self.v2_rows]
        self.assertEqual(len(hashes), len(set(hashes)))

    def test_runner_accepts_manifest_v2(self) -> None:
        audit = runner.audit_final_manifest(manifest_v2.V2_YAML)
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["manifest_version"], "2.0")
        self.assertEqual(audit["parameter_sets"], 24)

    def test_runner_reuses_unchanged_complete_sets(self) -> None:
        state = seasonal.load_full_run_state()
        by_id = {row["parameter_set_id"]: row for row in self.v2_rows}
        full_weather, _ = runner.audit_weather_dataset()
        weather_hash = pilot.selected_weather_hash(full_weather)
        for identifier in manifest_v2.V1_COMPLETE_IDS:
            job = runner.GenerationJob(
                identifier,
                by_id[identifier],
                runner.FULL_START,
                runner.FULL_END_INCLUSIVE,
                runner.EXPECTED_FULL_ROWS,
            )
            _, _, source_hash, run_hash = runner.derive_run_config(job)
            identity = runner.identity_payload(
                job, source_hash, run_hash, weather_hash
            )
            decision = runner.cache_decision(
                state["scenarios"][identifier],
                identity,
                runner.scenario_paths(runner.FULL_OUTPUT_ROOT, identifier),
            )
            self.assertEqual(decision, ("SKIP", "COMPLETE"))


if __name__ == "__main__":
    unittest.main()
