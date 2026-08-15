"""E2 natural, leakage, and forced greenhouse ventilation."""

from __future__ import annotations

import math

from .config import AtmosphereParameters, VentilationParameters


def ventilation_rate_m3_s(
    wind_speed_m_s: float,
    temperature_inside_c: float,
    temperature_outside_c: float,
    fan_state: int,
    vent_state: float,
    atmosphere: AtmosphereParameters,
    ventilation: VentilationParameters,
) -> float:
    """E2: compute nonnegative passive plus forced volumetric airflow."""

    wind_speed = max(wind_speed_m_s, 0.0)
    absolute_inside_k = temperature_inside_c + atmosphere.kelvin_offset
    if absolute_inside_k <= 0.0:
        raise ValueError("Indoor absolute temperature must be positive.")
    driving_term = (
        ventilation.wind_effect_coefficient * wind_speed * wind_speed
        + 2.0
        * atmosphere.gravity
        * ventilation.vent_height_m
        * abs(temperature_inside_c - temperature_outside_c)
        / absolute_inside_k
    )
    natural_flow = (
        ventilation.discharge_coefficient
        * ventilation.vent_area_m2
        * min(max(vent_state, 0.0), 1.0)
        * math.sqrt(max(driving_term, 0.0))
    )
    forced_flow = (
        ventilation.fan_nominal_airflow_m3_s
        * ventilation.fan_effective_flow_factor
        * int(fan_state)
    )
    return max(
        ventilation.passive_leakage_m3_s + natural_flow + forced_flow,
        0.0,
    )
