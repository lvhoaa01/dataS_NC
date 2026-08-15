"""E0 and E6 atmospheric water-vapour relationships."""

from __future__ import annotations

import math

from .config import AtmosphereParameters


def saturation_vapor_pressure_kpa(
    temperature_c: float, parameters: AtmosphereParameters
) -> float:
    """Return saturation vapour pressure in kPa using the FAO-56 relation."""

    denominator = temperature_c + parameters.svp_temperature_offset_c
    if denominator <= 0.0:
        raise ValueError(
            f"Temperature {temperature_c} degC is outside the FAO-56 formula domain."
        )
    exponent = (
        parameters.svp_exponent_numerator * temperature_c / denominator
    )
    return parameters.svp_coefficient_kpa * math.exp(exponent)


def actual_vapor_pressure_kpa(
    temperature_c: float,
    relative_humidity_percent: float,
    parameters: AtmosphereParameters,
) -> float:
    """Return actual vapour pressure in kPa from temperature and RH."""

    if not 0.0 <= relative_humidity_percent <= 100.0:
        raise ValueError(
            "Relative humidity must be in [0, 100]; "
            f"got {relative_humidity_percent}."
        )
    return (
        relative_humidity_percent
        / 100.0
        * saturation_vapor_pressure_kpa(temperature_c, parameters)
    )


def vapor_density_kg_m3(
    temperature_c: float,
    vapor_pressure_kpa: float,
    parameters: AtmosphereParameters,
) -> float:
    """Convert vapour pressure in kPa to vapour density in kg/m3."""

    if vapor_pressure_kpa < 0.0:
        raise ValueError("Vapour pressure cannot be negative.")
    absolute_temperature_k = temperature_c + parameters.kelvin_offset
    if absolute_temperature_k <= 0.0:
        raise ValueError("Absolute temperature must be positive.")
    return (
        1000.0
        * vapor_pressure_kpa
        / (parameters.vapor_gas_constant * absolute_temperature_k)
    )


def vapor_pressure_from_density_kpa(
    temperature_c: float,
    vapor_density_kg_m3_value: float,
    parameters: AtmosphereParameters,
) -> float:
    """Convert vapour density in kg/m3 to vapour pressure in kPa."""

    if vapor_density_kg_m3_value < 0.0:
        raise ValueError("Vapour density cannot be negative.")
    absolute_temperature_k = temperature_c + parameters.kelvin_offset
    if absolute_temperature_k <= 0.0:
        raise ValueError("Absolute temperature must be positive.")
    return (
        vapor_density_kg_m3_value
        * parameters.vapor_gas_constant
        * absolute_temperature_k
        / 1000.0
    )


def saturation_vapor_density_kg_m3(
    temperature_c: float, parameters: AtmosphereParameters
) -> float:
    """Return saturation vapour density in kg/m3 at a temperature."""

    return vapor_density_kg_m3(
        temperature_c,
        saturation_vapor_pressure_kpa(temperature_c, parameters),
        parameters,
    )


def relative_humidity_from_state(
    temperature_c: float,
    vapor_density_inside_kg_m3: float,
    parameters: AtmosphereParameters,
) -> float:
    """E6: derive indoor RH from air temperature and vapour density state."""

    actual_pressure = vapor_pressure_from_density_kpa(
        temperature_c, vapor_density_inside_kg_m3, parameters
    )
    saturation_pressure = saturation_vapor_pressure_kpa(temperature_c, parameters)
    relative_humidity = 100.0 * actual_pressure / saturation_pressure
    return min(max(relative_humidity, 0.0), 100.0)


def vapor_pressure_deficit_kpa(
    temperature_c: float,
    vapor_density_inside_kg_m3: float,
    parameters: AtmosphereParameters,
) -> float:
    """Return nonnegative indoor vapour-pressure deficit in kPa."""

    actual_pressure = vapor_pressure_from_density_kpa(
        temperature_c, vapor_density_inside_kg_m3, parameters
    )
    return max(
        saturation_vapor_pressure_kpa(temperature_c, parameters) - actual_pressure,
        0.0,
    )


def dry_air_density_kg_m3(
    surface_pressure_pa: float,
    temperature_c: float,
    parameters: AtmosphereParameters,
) -> float:
    """Return dry-air density, requiring pressure at the SI boundary in Pa."""

    if surface_pressure_pa <= 0.0:
        raise ValueError("Surface pressure must be positive in Pa.")
    absolute_temperature_k = temperature_c + parameters.kelvin_offset
    if absolute_temperature_k <= 0.0:
        raise ValueError("Absolute temperature must be positive.")
    return surface_pressure_pa / (
        parameters.dry_air_gas_constant * absolute_temperature_k
    )
