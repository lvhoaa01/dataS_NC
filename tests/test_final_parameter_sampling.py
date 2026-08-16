from __future__ import annotations

import json
import math
from pathlib import Path
import unittest

import generate_final_parameter_sets as sampling
from physics.config import load_parameter_config


ROOT = Path(__file__).resolve().parents[1]


class FinalParameterSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.joint = json.loads(
            (ROOT / "joint_parameter_space.yaml").read_text(encoding="utf-8")
        )
        cls.base = load_parameter_config(
            ROOT / "config" / "greenhouse_parameters.yaml"
        )

    def test_triangular_inverse_cdf(self) -> None:
        self.assertEqual(sampling.triangular_inverse_cdf(0.0, 1.0, 2.0, 4.0), 1.0)
        self.assertEqual(sampling.triangular_inverse_cdf(1.0, 1.0, 2.0, 4.0), 4.0)
        mode_probability = (2.0 - 1.0) / (4.0 - 1.0)
        self.assertAlmostEqual(
            sampling.triangular_inverse_cdf(mode_probability, 1.0, 2.0, 4.0),
            2.0,
        )
        values = [
            sampling.triangular_inverse_cdf(index / 100.0, 0.2, 0.65, 0.65)
            for index in range(101)
        ]
        self.assertTrue(all(left <= right for left, right in zip(values, values[1:])))

    def test_constrained_lhs_deterministic(self) -> None:
        first_attempts, first_retained, first_meta = sampling.generate_sampling_design(
            self.joint, self.base
        )
        second_attempts, second_retained, second_meta = sampling.generate_sampling_design(
            self.joint, self.base
        )
        self.assertEqual(first_attempts, second_attempts)
        self.assertEqual(first_retained, second_retained)
        self.assertEqual(
            {key: value for key, value in first_meta.items() if key != "pending_configs"},
            {key: value for key, value in second_meta.items() if key != "pending_configs"},
        )

    def test_joint_constraint_filter(self) -> None:
        invalid = {
            "C_d": 0.20,
            "eta_s": 0.15,
            "C_s": 75000.0,
            "irrigation_flow_L_h": 10.0,
            "ET_scale": 1.30,
        }
        valid = {**invalid, "C_d": 0.30}
        invalid_pass, violations = sampling.evaluate_joint_constraints(
            invalid, self.joint
        )
        valid_pass, valid_violations = sampling.evaluate_joint_constraints(
            valid, self.joint
        )
        self.assertFalse(invalid_pass)
        self.assertIn("reject_low_cd_high_et_wedge", violations)
        self.assertTrue(valid_pass)
        self.assertEqual(valid_violations, [])

    def test_no_duplicate_parameter_sets_and_exact_counts(self) -> None:
        attempts, retained, metadata = sampling.generate_sampling_design(
            self.joint, self.base
        )
        self.assertEqual(len(retained), 24)
        self.assertEqual(sum(bool(row["is_baseline"]) for row in retained), 1)
        self.assertEqual(metadata["joint_valid_retained"], 23)
        vectors = {
            tuple(
                float(row["C_s_J_K"] if name == "C_s" else row[name])
                for name in sampling.AXES
            )
            for row in retained
        }
        self.assertEqual(len(vectors), len(retained))
        self.assertTrue(
            all(row["joint_constraint_pass"] for row in retained)
        )
        self.assertGreaterEqual(len(attempts), len(retained))

    def test_lhs_coverage_does_not_collapse(self) -> None:
        _, retained, _ = sampling.generate_sampling_design(self.joint, self.base)
        audit = sampling.coverage_audit(retained, self.joint)
        self.assertEqual(audit["status"], "PASS")
        for axis in audit["axes"].values():
            self.assertGreater(axis["normalized_range_coverage"], 0.70)
            self.assertGreaterEqual(axis["unique_lhs_strata"], 20)
            self.assertGreater(axis["std_population"], 0.0)
        for pair in audit["pairwise"].values():
            self.assertTrue(math.isfinite(pair["pearson_correlation"]))
            self.assertEqual(pair["occupied_quadrants"], 4)

    def test_et_scale_preserves_coefficient_ratio(self) -> None:
        _, retained, _ = sampling.generate_sampling_design(self.joint, self.base)
        row = retained[-1]
        values = {
            "C_d": float(row["C_d"]),
            "eta_s": float(row["eta_s"]),
            "C_s": float(row["C_s_J_K"]),
            "irrigation_flow_L_h": float(row["irrigation_flow_L_h"]),
            "ET_scale": float(row["ET_scale"]),
        }
        _, config, _ = sampling.build_parameter_config(
            self.base.raw,
            values,
            str(row["parameter_set_id"]),
            str(row["candidate_id"]),
            int(row["sampling_index"]),
            int(row["raw_candidate_index"]),
        )
        model = config.to_model_parameters()
        baseline = self.base.to_model_parameters()
        self.assertAlmostEqual(
            model.crop.transpiration_radiation_coefficient
            / baseline.crop.transpiration_radiation_coefficient,
            values["ET_scale"],
        )
        self.assertAlmostEqual(
            model.crop.transpiration_vpd_coefficient
            / baseline.crop.transpiration_vpd_coefficient,
            values["ET_scale"],
        )


if __name__ == "__main__":
    unittest.main()
