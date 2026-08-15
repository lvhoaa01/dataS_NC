"""E3 root-zone water stress and E4 reduced evapotranspiration."""

from __future__ import annotations

from .config import CropParameters, GrowLightParameters, SoilWaterParameters


def water_stress_coefficient(
    theta: float, theta_fc: float, theta_wp: float, depletion_fraction_p: float
) -> float:
    """E3: return FAO-adapted water-stress factor Ks in [0, 1]."""

    if not theta_wp < theta_fc:
        raise ValueError("theta_wp must be below theta_fc.")
    if not 0.0 <= depletion_fraction_p <= 1.0:
        raise ValueError("depletion_fraction_p must be in [0, 1].")
    threshold = theta_fc - depletion_fraction_p * (theta_fc - theta_wp)
    if theta >= threshold:
        return 1.0
    if theta <= theta_wp:
        return 0.0
    denominator = (1.0 - depletion_fraction_p) * (theta_fc - theta_wp)
    if denominator <= 0.0:
        raise ValueError("Water-stress denominator must be positive.")
    return min(max((theta - theta_wp) / denominator, 0.0), 1.0)


def evapotranspiration_rate(
    solar_inside_w_m2: float,
    vpd_inside_kpa: float,
    soil_moisture_theta: float,
    grow_light_state: int,
    crop: CropParameters,
    soil_water: SoilWaterParameters,
    grow_light: GrowLightParameters,
) -> float:
    """E4: return greenhouse crop/pot evapotranspiration mass flow in kg/s."""

    stress = water_stress_coefficient(
        soil_moisture_theta,
        soil_water.field_capacity,
        soil_water.wilting_point,
        soil_water.depletion_fraction,
    )
    grow_radiation_w_m2 = (
        grow_light.radiant_fraction
        * grow_light.electrical_power_w
        * int(grow_light_state)
        / crop.effective_area_m2
    )
    crop_radiation = max(solar_inside_w_m2 + grow_radiation_w_m2, 0.0)
    mass_flux_kg_m2_s = (
        crop.transpiration_radiation_coefficient * crop_radiation
        + crop.transpiration_vpd_coefficient * max(vpd_inside_kpa, 0.0)
    )
    return max(crop.effective_area_m2 * stress * mass_flux_kg_m2_s, 0.0)
