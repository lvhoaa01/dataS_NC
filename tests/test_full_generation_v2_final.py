from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import audit_full_generation_v2 as final_audit
import build_ml_dataset as ml_builder
import generate_pilot_scenarios as pilot


ROOT = Path(__file__).resolve().parents[1]


class FullGenerationV2FinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.audit = json.loads(final_audit.AUDIT_PATH.read_text(encoding="utf-8"))
        with final_audit.INDEX_PATH.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            cls.index = list(csv.DictReader(handle))

    def test_final_manifest_v2_24_sets(self) -> None:
        self.assertEqual(self.audit["valid_parameter_sets"], 24)
        self.assertEqual(self.audit["unique_config_hashes"], 24)
        self.assertEqual(len(self.index), 24)

    def test_all_final_physics_files_exist(self) -> None:
        self.assertTrue(all((ROOT / row["physics_file"]).is_file() for row in self.index))

    def test_all_final_ml_files_exist(self) -> None:
        self.assertTrue(all((ROOT / row["ml_file"]).is_file() for row in self.index))

    def test_each_final_file_70128_rows(self) -> None:
        self.assertTrue(
            all(
                int(row["physics_rows"]) == 70_128 and int(row["ml_rows"]) == 70_128
                for row in self.index
            )
        )

    def test_total_final_rows_1683072(self) -> None:
        self.assertEqual(self.audit["physics_rows"], 1_683_072)
        self.assertEqual(self.audit["ml_rows"], 1_683_072)

    def test_no_rejected_v1_set_in_final_index(self) -> None:
        self.assertNotIn("pa1_full_006", {row["parameter_set_id"] for row in self.index})
        self.assertFalse(self.audit["rejected_v1_included"])

    def test_ml_schema_contract(self) -> None:
        self.assertEqual(
            tuple(self.audit["ml_contract"]["columns"]), ml_builder.CANONICAL_COLUMNS
        )
        self.assertEqual(self.audit["ml_contract"]["sensor_variables"], 5)
        self.assertEqual(self.audit["ml_contract"]["actuator_states"], 3)

    def test_no_physics_or_weather_features_in_ml(self) -> None:
        self.assertEqual(self.audit["ml_contract"]["physics_feature_count"], 0)
        self.assertEqual(self.audit["ml_contract"]["weather_feature_count"], 0)

    def test_all_final_hashes_match(self) -> None:
        for row in self.index:
            self.assertEqual(pilot.sha256_file(ROOT / row["physics_file"]), row["physics_hash"])
            self.assertEqual(pilot.sha256_file(ROOT / row["ml_file"]), row["ml_hash"])

    def test_all_final_validations_pass(self) -> None:
        self.assertEqual(self.audit["status"], "PASS")
        self.assertEqual(self.audit["nan_count"], 0)
        self.assertEqual(self.audit["inf_count"], 0)
        self.assertTrue(all(row["validation_status"] == "PASS" for row in self.index))


if __name__ == "__main__":
    unittest.main()
