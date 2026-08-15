"""Typed, provenance-preserving parameter configuration loading."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterator


REQUIRED_RECORD_FIELDS = {"value", "unit", "provenance", "status", "source"}


class ParameterConfigError(ValueError):
    """Raised when the parameter set is incomplete or physically invalid."""


@dataclass(frozen=True)
class AtmosphereParameters:
    svp_coefficient_kpa: float
    svp_exponent_numerator: float
    svp_temperature_offset_c: float
    kelvin_offset: float
    vapor_gas_constant: float
    dry_air_gas_constant: float
    dry_air_heat_capacity: float
    latent_heat_vaporization: float
    water_density: float
    gravity: float


@dataclass(frozen=True)
class GreenhouseParameters:
    volume_m3: float
    floor_area_m2: float
    cover_area_m2: float
    effective_thermal_capacity_j_k: float


@dataclass(frozen=True)
class CoverParameters:
    shortwave_transmittance: float
    visible_transmittance: float
    u_value_w_m2_k: float
    air_solar_absorption_fraction: float


@dataclass(frozen=True)
class VentilationParameters:
    passive_leakage_m3_s: float
    vent_area_m2: float
    vent_height_m: float
    discharge_coefficient: float
    wind_effect_coefficient: float
    fan_nominal_airflow_m3_s: float
    fan_effective_flow_factor: float


@dataclass(frozen=True)
class CropParameters:
    effective_area_m2: float
    transpiration_radiation_coefficient: float
    transpiration_vpd_coefficient: float


@dataclass(frozen=True)
class SoilThermalParameters:
    surface_area_m2: float
    effective_heat_capacity_j_k: float
    air_soil_heat_transfer_w_m2_k: float
    solar_absorption_fraction: float
    base_loss_u_w_m2_k: float
    base_temperature_c: float


@dataclass(frozen=True)
class SoilWaterParameters:
    root_volume_m3: float
    field_capacity: float
    wilting_point: float
    depletion_fraction: float
    drainage_coefficient_s: float
    residual_lower_bound: float
    saturation_upper_bound: float
    initial_theta: float


@dataclass(frozen=True)
class IrrigationParameters:
    effective_flow_m3_s: float


@dataclass(frozen=True)
class GrowLightParameters:
    electrical_power_w: float
    radiant_fraction: float
    heat_fraction: float
    canopy_lux_gain: float


@dataclass(frozen=True)
class LightParameters:
    direct_luminous_efficacy_lm_w: float
    diffuse_luminous_efficacy_lm_w: float


@dataclass(frozen=True)
class ControlParameters:
    pump_pulse_start_seconds: tuple[int, ...]
    pump_pulse_duration_s: int
    fan_on_temperature_c: float
    fan_minimum_cooling_delta_c: float
    grow_light_baseline_state: int
    vent_state: float


@dataclass(frozen=True)
class SimulationParameters:
    parameter_set_id: str
    simulation_id: str
    start_timestamp: str
    duration_days: int
    internal_timestep_s: int
    output_interval_s: int
    weather_interpolation: str
    sensor_noise_enabled: bool


@dataclass(frozen=True)
class ModelParameters:
    atmosphere: AtmosphereParameters
    greenhouse: GreenhouseParameters
    cover: CoverParameters
    ventilation: VentilationParameters
    crop: CropParameters
    soil_thermal: SoilThermalParameters
    soil_water: SoilWaterParameters
    irrigation: IrrigationParameters
    grow_light: GrowLightParameters
    light: LightParameters
    controls: ControlParameters
    simulation: SimulationParameters


class ParameterConfig:
    """Read-only configuration retaining each value's provenance record."""

    def __init__(self, raw: dict[str, Any], source_path: Path) -> None:
        self.raw = raw
        self.source_path = source_path
        self._records = dict(self._walk_records(raw))
        self._validate_record_schema()

    def _walk_records(
        self, node: dict[str, Any], prefix: str = ""
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict) and "value" in value:
                yield path, value
            elif isinstance(value, dict):
                yield from self._walk_records(value, path)
            else:
                raise ParameterConfigError(
                    f"Config leaf {path!r} must be a provenance record."
                )

    def _validate_record_schema(self) -> None:
        if not self._records:
            raise ParameterConfigError("Parameter config contains no records.")
        for path, record in self._records.items():
            missing = REQUIRED_RECORD_FIELDS - record.keys()
            if missing:
                raise ParameterConfigError(
                    f"Parameter {path!r} is missing metadata: {sorted(missing)}"
                )
            for field in ("unit", "provenance", "status", "source"):
                if not str(record[field]).strip():
                    raise ParameterConfigError(
                        f"Parameter {path!r} has empty {field!r}."
                    )

    def value(self, path: str) -> Any:
        try:
            return self._records[path]["value"]
        except KeyError as exc:
            raise ParameterConfigError(f"Missing required parameter {path!r}.") from exc

    def records(self) -> dict[str, dict[str, Any]]:
        return {path: dict(record) for path, record in self._records.items()}

    def to_model_parameters(self) -> ModelParameters:
        f = lambda path: float(self.value(path))
        i = lambda path: int(self.value(path))
        s = lambda path: str(self.value(path))

        model = ModelParameters(
            atmosphere=AtmosphereParameters(
                svp_coefficient_kpa=f("physical_constants.svp_coefficient_kpa"),
                svp_exponent_numerator=f("physical_constants.svp_exponent_numerator"),
                svp_temperature_offset_c=f(
                    "physical_constants.svp_temperature_offset_c"
                ),
                kelvin_offset=f("physical_constants.kelvin_offset"),
                vapor_gas_constant=f(
                    "physical_constants.water_vapor_gas_constant_j_kg_k"
                ),
                dry_air_gas_constant=f(
                    "physical_constants.dry_air_gas_constant_j_kg_k"
                ),
                dry_air_heat_capacity=f(
                    "physical_constants.dry_air_heat_capacity_j_kg_k"
                ),
                latent_heat_vaporization=f(
                    "physical_constants.latent_heat_vaporization_j_kg"
                ),
                water_density=f("physical_constants.water_density_kg_m3"),
                gravity=f("physical_constants.gravity_m_s2"),
            ),
            greenhouse=GreenhouseParameters(
                volume_m3=f("greenhouse.volume_m3"),
                floor_area_m2=f("greenhouse.floor_area_m2"),
                cover_area_m2=f("greenhouse.exposed_cover_area_m2"),
                effective_thermal_capacity_j_k=f(
                    "greenhouse.effective_thermal_capacity_j_k"
                ),
            ),
            cover=CoverParameters(
                shortwave_transmittance=f("cover.shortwave_transmittance"),
                visible_transmittance=f("cover.visible_transmittance"),
                u_value_w_m2_k=f("cover.u_value_w_m2_k"),
                air_solar_absorption_fraction=f(
                    "cover.air_solar_absorption_fraction"
                ),
            ),
            ventilation=VentilationParameters(
                passive_leakage_m3_s=f("ventilation.passive_leakage_m3_s"),
                vent_area_m2=f("ventilation.vent_area_m2"),
                vent_height_m=f("ventilation.vent_height_m"),
                discharge_coefficient=f("ventilation.discharge_coefficient"),
                wind_effect_coefficient=f(
                    "ventilation.wind_effect_coefficient"
                ),
                fan_nominal_airflow_m3_s=f(
                    "ventilation.fan_nominal_airflow_m3_s"
                ),
                fan_effective_flow_factor=f(
                    "ventilation.fan_effective_flow_factor"
                ),
            ),
            crop=CropParameters(
                effective_area_m2=f("crop.effective_area_m2"),
                transpiration_radiation_coefficient=f(
                    "crop.transpiration_radiation_coefficient"
                ),
                transpiration_vpd_coefficient=f(
                    "crop.transpiration_vpd_coefficient"
                ),
            ),
            soil_thermal=SoilThermalParameters(
                surface_area_m2=f("soil_thermal.surface_area_m2"),
                effective_heat_capacity_j_k=f(
                    "soil_thermal.effective_heat_capacity_j_k"
                ),
                air_soil_heat_transfer_w_m2_k=f(
                    "soil_thermal.air_soil_heat_transfer_w_m2_k"
                ),
                solar_absorption_fraction=f(
                    "soil_thermal.solar_absorption_fraction"
                ),
                base_loss_u_w_m2_k=f("soil_thermal.base_loss_u_w_m2_k"),
                base_temperature_c=f("soil_thermal.base_temperature_c"),
            ),
            soil_water=SoilWaterParameters(
                root_volume_m3=f("soil_water.root_volume_m3"),
                field_capacity=f("soil_water.field_capacity"),
                wilting_point=f("soil_water.wilting_point"),
                depletion_fraction=f("soil_water.depletion_fraction"),
                drainage_coefficient_s=f(
                    "soil_water.drainage_coefficient_s"
                ),
                residual_lower_bound=f("soil_water.residual_lower_bound"),
                saturation_upper_bound=f(
                    "soil_water.saturation_upper_bound"
                ),
                initial_theta=f("soil_water.initial_theta"),
            ),
            irrigation=IrrigationParameters(
                effective_flow_m3_s=f("irrigation.effective_flow_m3_s")
            ),
            grow_light=GrowLightParameters(
                electrical_power_w=f("grow_light.electrical_power_w"),
                radiant_fraction=f("grow_light.radiant_fraction"),
                heat_fraction=f("grow_light.heat_fraction"),
                canopy_lux_gain=f("grow_light.canopy_lux_gain"),
            ),
            light=LightParameters(
                direct_luminous_efficacy_lm_w=f(
                    "light.direct_luminous_efficacy_lm_w"
                ),
                diffuse_luminous_efficacy_lm_w=f(
                    "light.diffuse_luminous_efficacy_lm_w"
                ),
            ),
            controls=ControlParameters(
                pump_pulse_start_seconds=tuple(
                    int(v) for v in self.value("controls.pump_pulse_start_seconds")
                ),
                pump_pulse_duration_s=i("controls.pump_pulse_duration_s"),
                fan_on_temperature_c=f("controls.fan_on_temperature_c"),
                fan_minimum_cooling_delta_c=f(
                    "controls.fan_minimum_cooling_delta_c"
                ),
                grow_light_baseline_state=i(
                    "controls.grow_light_baseline_state"
                ),
                vent_state=f("controls.vent_state"),
            ),
            simulation=SimulationParameters(
                parameter_set_id=s("identity.parameter_set_id"),
                simulation_id=s("identity.simulation_id"),
                start_timestamp=s("simulation.start_timestamp"),
                duration_days=i("simulation.duration_days"),
                internal_timestep_s=i("simulation.internal_timestep_s"),
                output_interval_s=i("simulation.output_interval_s"),
                weather_interpolation=s("simulation.weather_interpolation"),
                sensor_noise_enabled=bool(self.value("sensor_model.noise_enabled")),
            ),
        )
        validate_model_parameters(model)
        return model


def validate_model_parameters(model: ModelParameters) -> None:
    """Validate physical and numerical constraints before simulation."""

    positive = {
        "greenhouse volume": model.greenhouse.volume_m3,
        "greenhouse floor area": model.greenhouse.floor_area_m2,
        "greenhouse cover area": model.greenhouse.cover_area_m2,
        "effective air thermal capacity": (
            model.greenhouse.effective_thermal_capacity_j_k
        ),
        "cover U-value": model.cover.u_value_w_m2_k,
        "vent area": model.ventilation.vent_area_m2,
        "vent height": model.ventilation.vent_height_m,
        "crop area": model.crop.effective_area_m2,
        "soil surface area": model.soil_thermal.surface_area_m2,
        "soil thermal capacity": model.soil_thermal.effective_heat_capacity_j_k,
        "root volume": model.soil_water.root_volume_m3,
        "dry-air gas constant": model.atmosphere.dry_air_gas_constant,
        "water-vapor gas constant": model.atmosphere.vapor_gas_constant,
    }
    for name, value in positive.items():
        if value <= 0.0:
            raise ParameterConfigError(f"{name} must be > 0; got {value}.")

    nonnegative = {
        "passive leakage": model.ventilation.passive_leakage_m3_s,
        "fan nominal flow": model.ventilation.fan_nominal_airflow_m3_s,
        "fan effective factor": model.ventilation.fan_effective_flow_factor,
        "irrigation effective flow": model.irrigation.effective_flow_m3_s,
        "drainage coefficient": model.soil_water.drainage_coefficient_s,
        "transpiration radiation coefficient": (
            model.crop.transpiration_radiation_coefficient
        ),
        "transpiration VPD coefficient": model.crop.transpiration_vpd_coefficient,
    }
    for name, value in nonnegative.items():
        if value < 0.0:
            raise ParameterConfigError(f"{name} must be >= 0; got {value}.")

    fractions = {
        "shortwave transmittance": model.cover.shortwave_transmittance,
        "visible transmittance": model.cover.visible_transmittance,
        "air solar absorption": model.cover.air_solar_absorption_fraction,
        "depletion fraction": model.soil_water.depletion_fraction,
        "grow-light radiant fraction": model.grow_light.radiant_fraction,
        "grow-light heat fraction": model.grow_light.heat_fraction,
        "vent state": model.controls.vent_state,
    }
    for name, value in fractions.items():
        if not 0.0 <= value <= 1.0:
            raise ParameterConfigError(f"{name} must be in [0, 1]; got {value}.")

    water = model.soil_water
    if not water.wilting_point < water.field_capacity:
        raise ParameterConfigError("wilting point must be below field capacity.")
    if not water.residual_lower_bound < water.wilting_point:
        raise ParameterConfigError("residual bound must be below wilting point.")
    if not water.field_capacity < water.saturation_upper_bound:
        raise ParameterConfigError("field capacity must be below saturation bound.")
    if not water.residual_lower_bound <= water.initial_theta <= water.saturation_upper_bound:
        raise ParameterConfigError("initial theta is outside configured physical bounds.")

    sim = model.simulation
    if sim.internal_timestep_s <= 0 or sim.output_interval_s <= 0:
        raise ParameterConfigError("Simulation timesteps must be positive.")
    if sim.output_interval_s % sim.internal_timestep_s != 0:
        raise ParameterConfigError(
            "Internal timestep must divide the hourly output interval exactly."
        )
    if sim.duration_days <= 0:
        raise ParameterConfigError("Simulation duration must be positive.")


def load_parameter_config(path: str | Path) -> ParameterConfig:
    """Load JSON-compatible YAML without adding a third-party dependency."""

    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParameterConfigError(f"Cannot load parameter config {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ParameterConfigError("Top-level parameter config must be an object.")
    return ParameterConfig(raw, config_path)
