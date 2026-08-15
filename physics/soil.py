"""E8 root-zone thermal state and E9 root-zone water balance."""

from __future__ import annotations

from .config import (
    AtmosphereParameters,
    IrrigationParameters,
    SoilThermalParameters,
    SoilWaterParameters,
)


def soil_temperature_derivative(
    temperature_inside_c: float,
    soil_temperature_c: float,
    solar_inside_w_m2: float,
    soil_thermal: SoilThermalParameters,
) -> float:
    """E8: return effective pot/root-zone temperature derivative in degC/s."""

    air_exchange_w = (
        soil_thermal.air_soil_heat_transfer_w_m2_k
        * soil_thermal.surface_area_m2
        * (temperature_inside_c - soil_temperature_c)
    )
    solar_heating_w = (
        soil_thermal.solar_absorption_fraction
        * soil_thermal.surface_area_m2
        * max(solar_inside_w_m2, 0.0)
    )
    base_loss_w = (
        soil_thermal.base_loss_u_w_m2_k
        * soil_thermal.surface_area_m2
        * (soil_temperature_c - soil_thermal.base_temperature_c)
    )
    return (
        air_exchange_w + solar_heating_w - base_loss_w
    ) / soil_thermal.effective_heat_capacity_j_k


def drainage_rate_m3_s(
    soil_moisture_theta: float, soil_water: SoilWaterParameters
) -> float:
    """Return E9 gravitational drainage volume flow in m3/s."""

    return (
        soil_water.root_volume_m3
        * soil_water.drainage_coefficient_s
        * max(soil_moisture_theta - soil_water.field_capacity, 0.0)
    )


def soil_moisture_derivative(
    soil_moisture_theta: float,
    pump_state: int,
    evapotranspiration_rate_kg_s: float,
    soil_water: SoilWaterParameters,
    irrigation: IrrigationParameters,
    atmosphere: AtmosphereParameters,
) -> float:
    """E9: return volumetric root-zone water-content derivative in 1/s."""

    irrigation_flow = irrigation.effective_flow_m3_s * int(pump_state)
    et_water_flow = max(evapotranspiration_rate_kg_s, 0.0) / (
        atmosphere.water_density
    )
    drainage_flow = drainage_rate_m3_s(soil_moisture_theta, soil_water)
    return (
        irrigation_flow - et_water_flow - drainage_flow
    ) / soil_water.root_volume_m3
