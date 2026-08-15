"""Separate true-state to observed-sensor architecture for a later calibrated layer."""

from __future__ import annotations

from dataclasses import dataclass

from .greenhouse import GreenhouseState


@dataclass(frozen=True)
class SensorObservation:
    temperature_inside_sensor_c: float
    humidity_inside_sensor_percent: float
    soil_temperature_inside_sensor_c: float
    soil_moisture_inside_sensor_percent: float | None
    light_lux_inside_sensor: float


def observe_without_noise(
    state: GreenhouseState,
    humidity_inside_percent: float,
    light_lux_inside: float,
) -> SensorObservation:
    """Return noiseless observable channels without inventing a soil calibration."""

    return SensorObservation(
        temperature_inside_sensor_c=state.temperature_inside_c,
        humidity_inside_sensor_percent=humidity_inside_percent,
        soil_temperature_inside_sensor_c=state.soil_temperature_c,
        soil_moisture_inside_sensor_percent=None,
        light_lux_inside_sensor=light_lux_inside,
    )
