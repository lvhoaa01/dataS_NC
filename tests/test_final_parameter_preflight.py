from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest

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


if __name__ == "__main__":
    unittest.main()
