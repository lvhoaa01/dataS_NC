from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import generate_pilot_scenarios as pilot
from physics.config import load_parameter_config
from physics.simulator import OUTPUT_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


class PilotUncertaintyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.space = json.loads(
            (ROOT / "scenario_parameter_space.yaml").read_text(encoding="utf-8")
        )
        cls.base_config = load_parameter_config(
            ROOT / "config" / "greenhouse_parameters.yaml"
        )

    def test_all_uncertain_config_records_are_mapped_once(self) -> None:
        uncertain = {
            path
            for path, record in self.base_config.records().items()
            if "TO_" in str(record["status"])
            or "INITIAL_PRIOR" in str(record["status"])
        }
        mapped = [
            path
            for parameter in self.space["parameters"].values()
            for path in parameter["config_paths"]
        ]
        self.assertEqual(uncertain, set(mapped))
        self.assertEqual(len(mapped), len(set(mapped)))

    def test_scenarios_preserve_fixed_design_and_controls(self) -> None:
        forbidden = set(self.space["classifications"]["fixed_design"])
        forbidden.update(
            item
            for item in self.space["classifications"][
                "control_or_time_varying"
            ]
            if "." in item
        )
        scenarios = self.space["pilot_scenarios"]
        self.assertEqual(len(scenarios), 10)
        self.assertEqual(scenarios[0]["scenario_id"], "scenario_000_baseline")
        self.assertEqual(scenarios[0]["changes"], [])
        for scenario in scenarios[1:]:
            axis = self.space["parameters"][scenario["changed_axis"]]
            changed_paths = {
                change["config_path"] for change in scenario["changes"]
            }
            self.assertTrue(changed_paths)
            self.assertTrue(changed_paths.issubset(set(axis["config_paths"])))
            self.assertTrue(changed_paths.isdisjoint(forbidden))

    def test_same_physical_config_has_stable_identity(self) -> None:
        scenario = self.space["pilot_scenarios"][0]
        _, first, first_hash = pilot.build_scenario_config(
            self.base_config.raw, scenario
        )
        _, second, second_hash = pilot.build_scenario_config(
            self.base_config.raw, scenario
        )
        self.assertEqual(first_hash, second_hash)
        self.assertEqual(
            first.to_model_parameters().simulation.parameter_set_id,
            second.to_model_parameters().simulation.parameter_set_id,
        )

    def test_approved_ranges_are_inside_exploratory_ranges(self) -> None:
        approved = self.space["approved_sampling_space"]
        self.assertEqual(set(approved), {
            "passive_discharge_coefficient",
            "soil_solar_coupling",
            "soil_effective_thermal_capacity",
            "irrigation_effective_flow",
            "crop_et_response_scale",
        })
        for name, final_range in approved.items():
            parameter = self.space["parameters"][name]
            self.assertGreaterEqual(final_range["min"], parameter["candidate_min"])
            self.assertLessEqual(final_range["max"], parameter["candidate_max"])

    def test_generated_outputs_and_deployment_contract(self) -> None:
        output_dir = ROOT / "outputs" / "scenario_pilot"
        for scenario in self.space["pilot_scenarios"]:
            path = output_dir / f"{scenario['scenario_id']}.csv"
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(tuple(reader.fieldnames or ()), OUTPUT_COLUMNS)
            self.assertEqual(len(rows), 720)

        with (ROOT / "outputs" / "greenhouse_ml_dataset_30days.csv").open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            ml_reader = csv.DictReader(handle)
            ml_rows = list(ml_reader)
        self.assertEqual(tuple(ml_reader.fieldnames or ()), pilot.ML_COLUMNS)
        self.assertEqual(len(ml_rows), 720)


if __name__ == "__main__":
    unittest.main()
