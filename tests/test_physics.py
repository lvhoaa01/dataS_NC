"""Focused unit tests for atmospheric relations and physical bounds."""

from __future__ import annotations

from pathlib import Path
import unittest

from physics.atmosphere import (
    actual_vapor_pressure_kpa,
    saturation_vapor_pressure_kpa,
    vapor_density_kg_m3,
)
from physics.config import load_parameter_config
from physics.crop import water_stress_coefficient
from physics.radiation import greenhouse_solar_radiation


ROOT = Path(__file__).resolve().parents[1]


class AtmosphereTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parameters = load_parameter_config(
            ROOT / "config" / "greenhouse_parameters.yaml"
        ).to_model_parameters()

    def test_rh_boundaries_produce_valid_vapor(self) -> None:
        temperature_c = 25.0
        saturation = saturation_vapor_pressure_kpa(
            temperature_c, self.parameters.atmosphere
        )
        for relative_humidity in (0.0, 50.0, 100.0):
            with self.subTest(relative_humidity=relative_humidity):
                actual = actual_vapor_pressure_kpa(
                    temperature_c,
                    relative_humidity,
                    self.parameters.atmosphere,
                )
                density = vapor_density_kg_m3(
                    temperature_c, actual, self.parameters.atmosphere
                )
                self.assertGreaterEqual(actual, 0.0)
                self.assertLessEqual(actual, saturation)
                self.assertGreaterEqual(density, 0.0)

    def test_actual_pressure_scales_with_rh(self) -> None:
        saturation = saturation_vapor_pressure_kpa(
            25.0, self.parameters.atmosphere
        )
        actual = actual_vapor_pressure_kpa(
            25.0, 50.0, self.parameters.atmosphere
        )
        self.assertAlmostEqual(actual, saturation * 0.5)


class WaterStressTests(unittest.TestCase):
    def test_required_boundaries(self) -> None:
        field_capacity = 0.42
        wilting_point = 0.15
        depletion = 0.4
        threshold = field_capacity - depletion * (
            field_capacity - wilting_point
        )
        self.assertEqual(
            water_stress_coefficient(
                threshold, field_capacity, wilting_point, depletion
            ),
            1.0,
        )
        self.assertEqual(
            water_stress_coefficient(
                wilting_point, field_capacity, wilting_point, depletion
            ),
            0.0,
        )
        self.assertEqual(
            water_stress_coefficient(
                wilting_point - 0.01,
                field_capacity,
                wilting_point,
                depletion,
            ),
            0.0,
        )

    def test_invalid_parameters_do_not_divide_by_zero(self) -> None:
        with self.assertRaises(ValueError):
            water_stress_coefficient(0.2, 0.2, 0.2, 0.4)
        with self.assertRaises(ValueError):
            water_stress_coefficient(0.2, 0.42, 0.15, 1.1)


class RadiationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.parameters = load_parameter_config(
            ROOT / "config" / "greenhouse_parameters.yaml"
        ).to_model_parameters()

    def test_solar_transmission_is_deterministic_and_nonnegative(self) -> None:
        transmitted = greenhouse_solar_radiation(
            500.0, self.parameters.cover
        )
        self.assertAlmostEqual(
            transmitted,
            500.0 * self.parameters.cover.shortwave_transmittance,
        )
        self.assertEqual(
            greenhouse_solar_radiation(-1.0, self.parameters.cover), 0.0
        )


if __name__ == "__main__":
    unittest.main()
