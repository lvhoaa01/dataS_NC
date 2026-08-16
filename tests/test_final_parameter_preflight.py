from __future__ import annotations

import csv
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import generate_final_parameter_sets as sampling
import generate_pilot_scenarios as pilot
import preflight_final_parameter_sets as preflight
from physics.simulator import OUTPUT_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


def fake_metrics(saturated_rows: int, soil_max: float = 38.0) -> dict:
    return {
        "states": {
            "T_soil": {"max": soil_max},
            "soil_moisture": {"min": 0.20, "max": 0.40},
        },
        "humidity": {
            "saturated_rows": saturated_rows,
            "saturated_fraction": saturated_rows / 720,
        },
        "soil_temperature": {"max_c": soil_max},
        "soil_water": {
            "hours_near_wilting": 0,
            "controller_pathology": {"status": "PASS", "flags": {}},
        },
    }


class FinalParameterPreflightUnitTests(unittest.TestCase):
    def test_rh_guard_accepts_36_and_rejects_37_rows(self) -> None:
        result = SimpleNamespace(
            rows=[dict.fromkeys(OUTPUT_COLUMNS, 0.0) for _ in range(720)]
        )
        accepted = preflight.joint_guard_violations(
            result, fake_metrics(36, soil_max=39.0), 720
        )
        rejected = preflight.joint_guard_violations(
            result, fake_metrics(37, soil_max=39.0), 720
        )
        self.assertEqual(accepted, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn("exceeds 5%", rejected[0])

    def test_soil_guard_is_accept_reject_not_clipping(self) -> None:
        result = SimpleNamespace(
            rows=[dict.fromkeys(OUTPUT_COLUMNS, 0.0) for _ in range(720)]
        )
        metrics = fake_metrics(0, soil_max=40.01)
        original = deepcopy(metrics)
        violations = preflight.joint_guard_violations(result, metrics, 720)
        self.assertEqual(metrics, original)
        self.assertIn("exceeds 40 C", violations[0])

    def test_identity_independent_output_hash(self) -> None:
        first = [
            {
                "timestamp": "2024-06-01T00:00",
                "temperature_inside_true": 30.0,
                "simulation_id": "one",
                "parameter_set_id": "one",
            }
        ]
        second = deepcopy(first)
        second[0]["simulation_id"] = "two"
        second[0]["parameter_set_id"] = "two"
        self.assertEqual(
            preflight.identity_independent_output_hash(first),
            preflight.identity_independent_output_hash(second),
        )

    def test_classification_preserves_valid_extremes(self) -> None:
        normal = fake_metrics(1, soil_max=37.9)
        extreme = fake_metrics(20, soil_max=38.1)
        self.assertEqual(
            preflight.classify_preflight(True, [], normal),
            ("PASS", "APPROVED_FULL_RUN"),
        )
        self.assertEqual(
            preflight.classify_preflight(True, [], extreme),
            ("EXTREME_VALID", "EXTREME_VALID_APPROVED"),
        )
        self.assertEqual(
            preflight.classify_preflight(True, ["guard"], normal),
            ("REJECTED", "REJECTED_PREFLIGHT"),
        )


class FinalParameterPreflightIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.summary = json.loads(
            (ROOT / "outputs/final_parameter_preflight/preflight_summary.json").read_text(
                encoding="utf-8"
            )
        )
        cls.joint = json.loads(
            (ROOT / "joint_parameter_space.yaml").read_text(encoding="utf-8")
        )
        with (ROOT / "final_approved_parameter_sets.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            cls.approved = list(csv.DictReader(handle))
        cls.machine_manifest = json.loads(
            (ROOT / "final_approved_parameter_sets.yaml").read_text(encoding="utf-8")
        )
        cls.validations = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(
                (ROOT / "outputs/final_parameter_preflight/validation").glob("*.json")
            )
        ]

    def test_exact_24_approved_sets(self) -> None:
        self.assertEqual(len(self.approved), 24)
        self.assertEqual(self.summary["final_approved"], 24)
        self.assertEqual(self.machine_manifest["parameter_set_count"], 24)
        self.assertEqual(self.machine_manifest["baseline_count"], 1)
        self.assertEqual(self.machine_manifest["non_baseline_count"], 23)
        self.assertEqual(
            [row["parameter_set_id"] for row in self.approved],
            ["pa1_full_000_baseline"]
            + [f"pa1_full_{index:03d}" for index in range(1, 24)],
        )

    def test_all_approved_preflight_pass(self) -> None:
        self.assertEqual(len(self.validations), 24)
        for report in self.validations:
            self.assertIn(report["preflight_status"], {"PASS", "EXTREME_VALID"})
            self.assertEqual(report["framework_status"], "PASS")
            self.assertEqual(report["joint_guard_status"], "PASS")
            self.assertEqual(report["rows"], 720)
            self.assertEqual(report["columns"], 33)
            self.assertLessEqual(report["metrics"]["soil_temperature"]["max_c"], 40.0)
            self.assertLessEqual(
                report["metrics"]["humidity"]["saturated_fraction"], 0.05
            )

    def test_final_sets_respect_joint_constraints(self) -> None:
        for row in self.approved:
            values = {
                "C_d": float(row["C_d"]),
                "eta_s": float(row["eta_s"]),
                "C_s": float(row["C_s_J_K"]),
                "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
                "ET_scale": float(row["ET_scale"]),
            }
            passed, violations = sampling.evaluate_joint_constraints(
                values, self.joint
            )
            self.assertTrue(passed, (row["parameter_set_id"], violations))

    def test_physics_outputs_are_720_by_33(self) -> None:
        physics_files = sorted(
            (ROOT / "outputs/final_parameter_preflight/physics").glob("*.csv")
        )
        self.assertEqual(len(physics_files), 24)
        for path in physics_files:
            with path.open(encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader)
                row_count = sum(1 for _ in reader)
            self.assertEqual(header, list(OUTPUT_COLUMNS))
            self.assertEqual(row_count, 720)

    def test_representative_stability_and_reproducibility_pass(self) -> None:
        stability = self.summary["stability"]
        reproducibility = self.summary["reproducibility"]
        self.assertEqual(stability["status"], "PASS")
        self.assertEqual(stability["representative_count"], 5)
        self.assertTrue(
            all(
                report["status"] == "PASS"
                for report in stability["representatives"].values()
            )
        )
        self.assertEqual(reproducibility["status"], "PASS")
        self.assertEqual(len(reproducibility["checks"]), 3)
        for report in reproducibility["checks"].values():
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(
                report["first_output_hash"], report["second_output_hash"]
            )
            self.assertEqual(
                report["numeric_hash"], report["expected_preflight_numeric_hash"]
            )

    def test_ml_contract_unchanged(self) -> None:
        audit = pilot.validate_ml_contract()
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["physics_or_weather_feature_count"], 0)
        self.assertEqual(audit["columns"], list(pilot.ML_COLUMNS))
        self.assertEqual(audit["sha256"], self.summary["ml_contract"]["sha256"])
        self.assertFalse(audit["scenario_ml_datasets_generated"])


if __name__ == "__main__":
    unittest.main()
