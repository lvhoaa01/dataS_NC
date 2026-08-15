"""Coupled greenhouse state types plus E5 vapour and E7 air energy balances."""

from __future__ import annotations

from dataclasses import dataclass

from .config import ModelParameters


@dataclass(frozen=True)
class GreenhouseState:
    """Minimum physical state vector with units documented by field names."""

    temperature_inside_c: float
    vapor_density_inside_kg_m3: float
    soil_temperature_c: float
    soil_moisture_theta: float

    def add_scaled(self, derivative: "StateDerivative", scale_s: float) -> "GreenhouseState":
        return GreenhouseState(
            temperature_inside_c=(
                self.temperature_inside_c
                + derivative.temperature_inside_c_s * scale_s
            ),
            vapor_density_inside_kg_m3=(
                self.vapor_density_inside_kg_m3
                + derivative.vapor_density_inside_kg_m3_s * scale_s
            ),
            soil_temperature_c=(
                self.soil_temperature_c
                + derivative.soil_temperature_c_s * scale_s
            ),
            soil_moisture_theta=(
                self.soil_moisture_theta
                + derivative.soil_moisture_theta_s * scale_s
            ),
        )


@dataclass(frozen=True)
class StateDerivative:
    temperature_inside_c_s: float
    vapor_density_inside_kg_m3_s: float
    soil_temperature_c_s: float
    soil_moisture_theta_s: float


@dataclass(frozen=True)
class WeatherForcing:
    timestamp: str
    temperature_outside_c: float
    relative_humidity_outside_percent: float
    shortwave_radiation_w_m2: float
    wind_speed_m_s: float
    surface_pressure_pa: float
    direct_radiation_w_m2: float
    diffuse_radiation_w_m2: float
    dew_point_c: float
    outdoor_vpd_kpa: float
    outdoor_et0_mm: float
    external_soil_temperature_c: float
    external_soil_moisture_m3_m3: float


@dataclass(frozen=True)
class ActuatorState:
    pump_state: int
    fan_state: int
    grow_light_state: int
    vent_state: float


@dataclass(frozen=True)
class PhysicsDiagnostics:
    relative_humidity_inside_percent: float
    vpd_inside_kpa: float
    solar_inside_w_m2: float
    light_lux_inside: float
    ventilation_rate_m3_s: float
    evapotranspiration_rate_kg_s: float
    water_stress_coefficient: float
    drainage_rate_m3_s: float
    air_density_kg_m3: float
    outdoor_vapor_density_kg_m3: float
    vapor_ventilation_exchange_kg_s: float
    q_solar_w: float
    q_cover_w: float
    q_ventilation_w: float
    q_soil_w: float
    q_latent_w: float
    q_grow_w: float
    q_condensation_w: float
    net_air_energy_w: float


def vapor_density_derivative(
    evapotranspiration_rate_kg_s: float,
    ventilation_rate_m3_s: float,
    vapor_density_outside_kg_m3: float,
    vapor_density_inside_kg_m3: float,
    condensation_rate_kg_s: float,
    greenhouse_volume_m3: float,
) -> float:
    """E5: indoor water-vapour mass-balance derivative in kg/m3/s."""

    return (
        evapotranspiration_rate_kg_s
        + ventilation_rate_m3_s
        * (vapor_density_outside_kg_m3 - vapor_density_inside_kg_m3)
        - max(condensation_rate_kg_s, 0.0)
    ) / greenhouse_volume_m3


def indoor_temperature_derivative(
    temperature_inside_c: float,
    temperature_outside_c: float,
    soil_temperature_c: float,
    solar_inside_w_m2: float,
    ventilation_rate_m3_s: float,
    evapotranspiration_rate_kg_s: float,
    air_density_kg_m3: float,
    grow_light_state: int,
    condensation_rate_kg_s: float,
    parameters: ModelParameters,
) -> tuple[float, dict[str, float]]:
    """E7: return indoor temperature derivative and auditable power terms."""

    q_solar = (
        parameters.cover.air_solar_absorption_fraction
        * parameters.greenhouse.floor_area_m2
        * max(solar_inside_w_m2, 0.0)
    )
    cover_ua_w_k = (
        parameters.cover.u_value_w_m2_k * parameters.greenhouse.cover_area_m2
    )
    q_cover = cover_ua_w_k * (temperature_outside_c - temperature_inside_c)
    q_ventilation = (
        air_density_kg_m3
        * parameters.atmosphere.dry_air_heat_capacity
        * ventilation_rate_m3_s
        * (temperature_outside_c - temperature_inside_c)
    )
    q_soil = (
        parameters.soil_thermal.air_soil_heat_transfer_w_m2_k
        * parameters.soil_thermal.surface_area_m2
        * (soil_temperature_c - temperature_inside_c)
    )
    q_latent = (
        parameters.atmosphere.latent_heat_vaporization
        * max(evapotranspiration_rate_kg_s, 0.0)
    )
    q_grow = (
        parameters.grow_light.heat_fraction
        * parameters.grow_light.electrical_power_w
        * int(grow_light_state)
    )
    q_condensation = (
        parameters.atmosphere.latent_heat_vaporization
        * max(condensation_rate_kg_s, 0.0)
    )
    net_power = (
        q_solar
        + q_cover
        + q_ventilation
        + q_soil
        - q_latent
        + q_grow
        + q_condensation
    )
    terms = {
        "q_solar_w": q_solar,
        "q_cover_w": q_cover,
        "q_ventilation_w": q_ventilation,
        "q_soil_w": q_soil,
        "q_latent_w": q_latent,
        "q_grow_w": q_grow,
        "q_condensation_w": q_condensation,
        "net_air_energy_w": net_power,
    }
    return net_power / parameters.greenhouse.effective_thermal_capacity_j_k, terms
