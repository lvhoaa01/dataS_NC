from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import generate_interaction_scenarios as interaction
from physics.config import load_parameter_config
from physics.simulator import OUTPUT_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


class InteractionPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = json.loads(
            (ROOT / "interaction_scenarios.yaml").read_text(encoding="utf-8")
        )
        cls.single_space = json.loads(
            (ROOT / "scenario_parameter_space.yaml").read_text(encoding="utf-8")
        )
        cls.base_config = load_parameter_config(
            ROOT / "config" / "greenhouse_parameters.yaml"
        )

    def test_design_uses_only_approved_axes_and_locked_weather(self) -> None:
        audit = interaction.validate_design(
            self.spec, self.single_space, self.base_config
        )
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(audit["scenario_count"], 12)
        self.assertFalse(audit["fixed_hardware_randomized"])
        self.assertFalse(audit["weather_randomized"])
        self.assertTrue(audit["et_coefficients_coupled"])

    def test_baseline_is_first_and_reproduces_base_values(self) -> None:
        baseline = self.spec["scenarios"][0]
        self.assertEqual(baseline["scenario_id"], "interaction_000_baseline")
        raw, config, _, changes, changed_axes = interaction.build_interaction_config(
            self.base_config.raw, baseline, self.spec
        )
        self.assertEqual(changes, [])
        self.assertEqual(changed_axes, [])
        self.assertEqual(
            interaction.canonical_hash(
                interaction.single_pilot.model_value_payload(config)
            ),
            interaction.canonical_hash(
                interaction.single_pilot.model_value_payload(
                    load_parameter_config(ROOT / "config" / "greenhouse_parameters.yaml")
                )
            ),
        )
        self.assertEqual(raw["sensor_model"]["noise_enabled"]["value"], False)

    def test_et_scale_always_changes_both_coefficients_together(self) -> None:
        base_model = self.base_config.to_model_parameters()
        base_ratio = (
            base_model.crop.transpiration_radiation_coefficient
            / base_model.crop.transpiration_vpd_coefficient
        )
        for scenario in self.spec["scenarios"]:
            _, config, _, _, _ = interaction.build_interaction_config(
                self.base_config.raw, scenario, self.spec
            )
            model = config.to_model_parameters()
            scale = float(scenario["parameters"]["ET_scale"])
            self.assertAlmostEqual(
                model.crop.transpiration_radiation_coefficient,
                base_model.crop.transpiration_radiation_coefficient * scale,
            )
            self.assertAlmostEqual(
                model.crop.transpiration_vpd_coefficient,
                base_model.crop.transpiration_vpd_coefficient * scale,
            )
            self.assertAlmostEqual(
                model.crop.transpiration_radiation_coefficient
                / model.crop.transpiration_vpd_coefficient,
                base_ratio,
            )

    def test_physical_identity_is_deterministic(self) -> None:
        scenario = self.spec["scenarios"][4]
        _, first, first_hash, _, _ = interaction.build_interaction_config(
            self.base_config.raw, scenario, self.spec
        )
        _, second, second_hash, _, _ = interaction.build_interaction_config(
            self.base_config.raw, scenario, self.spec
        )
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(
            first.to_model_parameters().simulation.parameter_set_id,
            second.to_model_parameters().simulation.parameter_set_id,
        )

    def test_generated_artifacts_and_ml_contract(self) -> None:
        output_dir = ROOT / "outputs" / "interaction_pilot"
        for scenario in self.spec["scenarios"]:
            self.assertIsInstance(scenario["parameter_set_id"], str)
            self.assertTrue(scenario["parameter_set_id"].startswith("smartgarden_pa1_joint_"))
            self.assertEqual(len(scenario["config_hash"]), 64)
            self.assertEqual(
                scenario["weather_hash"], self.spec["baseline"]["weather_hash"]
            )
            path = output_dir / f"{scenario['scenario_id']}.csv"
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_COLUMNS)
            self.assertEqual(len(rows), 720)
            self.assertTrue(
                (output_dir / "validation" / f"{scenario['scenario_id']}.json").is_file()
            )
            self.assertTrue(
                (output_dir / "configs" / f"{scenario['scenario_id']}.yaml").is_file()
            )

        joint = json.loads(
            (ROOT / "joint_parameter_space.yaml").read_text(encoding="utf-8")
        )
        self.assertEqual(joint["status"], "VALIDATED_JOINT_SPACE")
        self.assertEqual(set(joint["parameters"]), set(interaction.AXIS_NAMES))
        self.assertTrue(joint["joint_constraints"])
        constraint_ids = {
            item["constraint_id"] for item in joint["joint_constraints"]
        }
        self.assertIn("couple_et_coefficients", constraint_ids)
        self.assertIn("post_sample_physics_gate", constraint_ids)
        self.assertIn("reject_low_cd_high_et_wedge", constraint_ids)
        self.assertEqual(joint["ml_contract"]["physics_or_weather_feature_count"], 0)
        self.assertEqual(joint["ml_contract"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
