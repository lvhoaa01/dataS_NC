"""Deterministic coupled RK4 simulator driven by hourly Open-Meteo forcing."""

from __future__ import annotations

from dataclasses import dataclass, field
import csv
from datetime import datetime, timedelta
import math
from pathlib import Path
import time
from typing import Any, Callable, Iterable

from .atmosphere import (
    actual_vapor_pressure_kpa,
    dry_air_density_kg_m3,
    relative_humidity_from_state,
    saturation_vapor_density_kg_m3,
    vapor_density_kg_m3,
    vapor_pressure_deficit_kpa,
)
from .config import ModelParameters
from .crop import evapotranspiration_rate, water_stress_coefficient
from .greenhouse import (
    ActuatorState,
    GreenhouseState,
    PhysicsDiagnostics,
    StateDerivative,
    WeatherForcing,
    indoor_temperature_derivative,
    vapor_density_derivative,
)
from .radiation import greenhouse_solar_radiation, indoor_illuminance_lux
from .soil import (
    drainage_rate_m3_s,
    soil_moisture_derivative,
    soil_temperature_derivative,
)
from .ventilation import ventilation_rate_m3_s


RAW_WEATHER_COLUMNS = (
    "timestamp",
    "temperature_2m",
    "relative_humidity_2m",
    "shortwave_radiation",
    "wind_speed_10m",
    "surface_pressure",
    "direct_radiation",
    "diffuse_radiation",
    "dew_point_2m",
    "vapour_pressure_deficit",
    "et0_fao_evapotranspiration",
    "soil_temperature_0_to_7cm",
    "soil_moisture_0_to_7cm",
)

OUTPUT_COLUMNS = (
    "timestamp",
    "temperature_outside",
    "humidity_outside",
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "wind_speed",
    "surface_pressure",
    "dew_point_outside",
    "vpd_outside_reference",
    "et0_outside_reference",
    "external_soil_temperature_context",
    "external_soil_moisture_context",
    "pump_state",
    "fan_state",
    "grow_light_state",
    "vent_state",
    "temperature_inside_true",
    "humidity_inside_true",
    "vapor_density_inside_true",
    "soil_temperature_inside_true",
    "soil_moisture_inside_true",
    "light_lux_inside_true",
    "vpd_inside",
    "solar_inside",
    "ventilation_rate_m3_s",
    "evapotranspiration_rate_kg_s",
    "water_stress_coefficient",
    "condensation_rate_kg_s",
    "drainage_rate_m3_s",
    "air_density",
    "simulation_id",
    "parameter_set_id",
)


class WeatherDataError(ValueError):
    """Raised when raw weather fails schema or quality validation."""


class NumericalSimulationError(RuntimeError):
    """Raised when integration produces a nonphysical numerical state."""


@dataclass
class BalanceTotals:
    irrigation_input_m3: float = 0.0
    evapotranspiration_loss_m3: float = 0.0
    drainage_loss_m3: float = 0.0
    overflow_drainage_m3: float = 0.0
    evapotranspiration_source_kg: float = 0.0
    ventilation_exchange_kg: float = 0.0
    condensation_sink_kg: float = 0.0
    net_air_energy_j: float = 0.0

    def add(self, other: "BalanceTotals") -> None:
        for field_name in self.__dataclass_fields__:
            setattr(
                self,
                field_name,
                getattr(self, field_name) + getattr(other, field_name),
            )


@dataclass
class SimulationResult:
    rows: list[dict[str, Any]]
    initial_state: GreenhouseState
    final_state: GreenhouseState
    balances: BalanceTotals
    weather_quality: dict[str, Any]
    internal_timestep_s: int
    runtime_seconds: float
    warnings: list[str] = field(default_factory=list)


def _parse_float(row: dict[str, str], column: str, line_number: int) -> float:
    raw_value = row.get(column, "")
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise WeatherDataError(
            f"Invalid {column!r} at CSV line {line_number}: {raw_value!r}."
        ) from exc
    if not math.isfinite(value):
        raise WeatherDataError(
            f"Non-finite {column!r} at CSV line {line_number}: {raw_value!r}."
        )
    return value


def _row_to_forcing(
    row: dict[str, str], timestamp: datetime, line_number: int
) -> WeatherForcing:
    temperature = _parse_float(row, "temperature_2m", line_number)
    humidity = _parse_float(row, "relative_humidity_2m", line_number)
    shortwave = _parse_float(row, "shortwave_radiation", line_number)
    wind = _parse_float(row, "wind_speed_10m", line_number)
    pressure_hpa = _parse_float(row, "surface_pressure", line_number)
    direct = _parse_float(row, "direct_radiation", line_number)
    diffuse = _parse_float(row, "diffuse_radiation", line_number)

    if not 0.0 <= humidity <= 100.0:
        raise WeatherDataError(
            f"RH outside [0, 100] at {timestamp.isoformat(timespec='minutes')}."
        )
    if min(shortwave, direct, diffuse) < 0.0:
        raise WeatherDataError(
            f"Negative radiation at {timestamp.isoformat(timespec='minutes')}."
        )
    if wind < 0.0:
        raise WeatherDataError(
            f"Negative wind speed at {timestamp.isoformat(timespec='minutes')}."
        )
    if pressure_hpa <= 0.0:
        raise WeatherDataError(
            f"Nonpositive pressure at {timestamp.isoformat(timespec='minutes')}."
        )

    return WeatherForcing(
        timestamp=timestamp.isoformat(timespec="minutes"),
        temperature_outside_c=temperature,
        relative_humidity_outside_percent=humidity,
        shortwave_radiation_w_m2=shortwave,
        wind_speed_m_s=wind,
        surface_pressure_pa=pressure_hpa * 100.0,
        direct_radiation_w_m2=direct,
        diffuse_radiation_w_m2=diffuse,
        dew_point_c=_parse_float(row, "dew_point_2m", line_number),
        outdoor_vpd_kpa=_parse_float(
            row, "vapour_pressure_deficit", line_number
        ),
        outdoor_et0_mm=_parse_float(
            row, "et0_fao_evapotranspiration", line_number
        ),
        external_soil_temperature_c=_parse_float(
            row, "soil_temperature_0_to_7cm", line_number
        ),
        external_soil_moisture_m3_m3=_parse_float(
            row, "soil_moisture_0_to_7cm", line_number
        ),
    )


def load_and_validate_weather_window(
    csv_path: str | Path, start: datetime, duration_days: int
) -> tuple[list[WeatherForcing], dict[str, Any]]:
    """Validate the entire raw dataset and return 30 days plus one endpoint hour."""

    path = Path(csv_path)
    end = start + timedelta(days=duration_days)
    selected: list[WeatherForcing] = []
    row_count = 0
    previous_timestamp: datetime | None = None
    first_timestamp: datetime | None = None
    last_timestamp: datetime | None = None

    try:
        # utf-8-sig accepts both BOM and BOM-free CSVs without polluting the header.
        handle = path.open("r", encoding="utf-8-sig", newline="")
    except OSError as exc:
        raise WeatherDataError(f"Cannot open raw weather file {path}: {exc}") from exc

    with handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        missing_columns = [c for c in RAW_WEATHER_COLUMNS if c not in columns]
        if missing_columns:
            raise WeatherDataError(
                f"Raw weather is missing required columns: {missing_columns}"
            )

        for line_number, row in enumerate(reader, start=2):
            raw_timestamp = row.get("timestamp", "")
            try:
                timestamp = datetime.fromisoformat(raw_timestamp)
            except ValueError as exc:
                raise WeatherDataError(
                    f"Invalid timestamp at CSV line {line_number}: {raw_timestamp!r}."
                ) from exc
            if previous_timestamp is not None:
                expected = previous_timestamp + timedelta(hours=1)
                if timestamp != expected:
                    raise WeatherDataError(
                        "Raw weather timestamp discontinuity or duplicate: "
                        f"expected {expected.isoformat(timespec='minutes')}, "
                        f"got {timestamp.isoformat(timespec='minutes')}."
                    )
            forcing = _row_to_forcing(row, timestamp, line_number)
            if start <= timestamp <= end:
                selected.append(forcing)
            row_count += 1
            first_timestamp = first_timestamp or timestamp
            last_timestamp = timestamp
            previous_timestamp = timestamp

    expected_selected = duration_days * 24 + 1
    if len(selected) != expected_selected:
        raise WeatherDataError(
            f"Window requires {expected_selected} forcing rows including endpoint; "
            f"found {len(selected)}."
        )
    if datetime.fromisoformat(selected[0].timestamp) != start:
        raise WeatherDataError("Selected weather window does not begin at requested start.")
    if datetime.fromisoformat(selected[-1].timestamp) != end:
        raise WeatherDataError("Selected weather window does not include end endpoint.")

    quality = {
        "status": "PASS",
        "rows_checked": row_count,
        "columns": list(columns),
        "first_timestamp": first_timestamp.isoformat(timespec="minutes")
        if first_timestamp
        else None,
        "last_timestamp": last_timestamp.isoformat(timespec="minutes")
        if last_timestamp
        else None,
        "window_forcing_rows_including_endpoint": len(selected),
        "duplicates": 0,
        "timestamp_gaps": 0,
        "nonfinite_core_values": 0,
    }
    return selected, quality


def interpolate_weather(
    left: WeatherForcing, right: WeatherForcing, fraction: float
) -> WeatherForcing:
    """Linearly interpolate weather and enforce nonnegative radiation/wind."""

    alpha = min(max(fraction, 0.0), 1.0)

    def lerp(a: float, b: float) -> float:
        return a + alpha * (b - a)

    left_time = datetime.fromisoformat(left.timestamp)
    timestamp = left_time + timedelta(hours=alpha)
    return WeatherForcing(
        timestamp=timestamp.isoformat(timespec="seconds"),
        temperature_outside_c=lerp(
            left.temperature_outside_c, right.temperature_outside_c
        ),
        relative_humidity_outside_percent=min(
            max(
                lerp(
                    left.relative_humidity_outside_percent,
                    right.relative_humidity_outside_percent,
                ),
                0.0,
            ),
            100.0,
        ),
        shortwave_radiation_w_m2=max(
            lerp(
                left.shortwave_radiation_w_m2,
                right.shortwave_radiation_w_m2,
            ),
            0.0,
        ),
        wind_speed_m_s=max(lerp(left.wind_speed_m_s, right.wind_speed_m_s), 0.0),
        surface_pressure_pa=lerp(
            left.surface_pressure_pa, right.surface_pressure_pa
        ),
        direct_radiation_w_m2=max(
            lerp(left.direct_radiation_w_m2, right.direct_radiation_w_m2), 0.0
        ),
        diffuse_radiation_w_m2=max(
            lerp(left.diffuse_radiation_w_m2, right.diffuse_radiation_w_m2),
            0.0,
        ),
        dew_point_c=lerp(left.dew_point_c, right.dew_point_c),
        outdoor_vpd_kpa=max(
            lerp(left.outdoor_vpd_kpa, right.outdoor_vpd_kpa), 0.0
        ),
        outdoor_et0_mm=max(
            lerp(left.outdoor_et0_mm, right.outdoor_et0_mm), 0.0
        ),
        external_soil_temperature_c=lerp(
            left.external_soil_temperature_c,
            right.external_soil_temperature_c,
        ),
        external_soil_moisture_m3_m3=lerp(
            left.external_soil_moisture_m3_m3,
            right.external_soil_moisture_m3_m3,
        ),
    )


def actuator_schedule(
    timestamp: datetime,
    state: GreenhouseState,
    weather: WeatherForcing,
    parameters: ModelParameters,
) -> ActuatorState:
    """Return deterministic, piecewise-constant V1 actuator controls."""

    second_of_day = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
    pump_on = any(
        start <= second_of_day < start + parameters.controls.pump_pulse_duration_s
        for start in parameters.controls.pump_pulse_start_seconds
    )
    fan_on = (
        state.temperature_inside_c >= parameters.controls.fan_on_temperature_c
        and state.temperature_inside_c
        >= weather.temperature_outside_c
        + parameters.controls.fan_minimum_cooling_delta_c
    )
    return ActuatorState(
        pump_state=int(pump_on),
        fan_state=int(fan_on),
        grow_light_state=parameters.controls.grow_light_baseline_state,
        vent_state=parameters.controls.vent_state,
    )


def _seconds_to_next_pump_event(
    timestamp: datetime, parameters: ModelParameters
) -> float | None:
    """Return time to the next pump ON/OFF boundary in the local day."""

    second_of_day = (
        timestamp.hour * 3600
        + timestamp.minute * 60
        + timestamp.second
        + timestamp.microsecond / 1_000_000.0
    )
    boundaries: list[float] = []
    for start in parameters.controls.pump_pulse_start_seconds:
        boundaries.append(float(start))
        boundaries.append(
            float(start + parameters.controls.pump_pulse_duration_s)
        )
    future = [boundary - second_of_day for boundary in boundaries if boundary > second_of_day]
    if not future:
        return None
    return min(future)


def evaluate_system(
    state: GreenhouseState,
    weather: WeatherForcing,
    controls: ActuatorState,
    parameters: ModelParameters,
    condensation_rate_kg_s: float = 0.0,
) -> tuple[StateDerivative, PhysicsDiagnostics]:
    """Evaluate the complete coupled E0-E10 derivative and diagnostics."""

    atmosphere = parameters.atmosphere
    outside_vapor_pressure = actual_vapor_pressure_kpa(
        weather.temperature_outside_c,
        weather.relative_humidity_outside_percent,
        atmosphere,
    )
    outside_vapor_density = vapor_density_kg_m3(
        weather.temperature_outside_c, outside_vapor_pressure, atmosphere
    )
    solar_inside = greenhouse_solar_radiation(
        weather.shortwave_radiation_w_m2, parameters.cover
    )
    relative_humidity_inside = relative_humidity_from_state(
        state.temperature_inside_c,
        state.vapor_density_inside_kg_m3,
        atmosphere,
    )
    vpd_inside = vapor_pressure_deficit_kpa(
        state.temperature_inside_c,
        state.vapor_density_inside_kg_m3,
        atmosphere,
    )
    water_stress = water_stress_coefficient(
        state.soil_moisture_theta,
        parameters.soil_water.field_capacity,
        parameters.soil_water.wilting_point,
        parameters.soil_water.depletion_fraction,
    )
    et_rate = evapotranspiration_rate(
        solar_inside,
        vpd_inside,
        state.soil_moisture_theta,
        controls.grow_light_state,
        parameters.crop,
        parameters.soil_water,
        parameters.grow_light,
    )
    ventilation_rate = ventilation_rate_m3_s(
        weather.wind_speed_m_s,
        state.temperature_inside_c,
        weather.temperature_outside_c,
        controls.fan_state,
        controls.vent_state,
        atmosphere,
        parameters.ventilation,
    )
    air_density = dry_air_density_kg_m3(
        weather.surface_pressure_pa, state.temperature_inside_c, atmosphere
    )
    vapor_exchange = ventilation_rate * (
        outside_vapor_density - state.vapor_density_inside_kg_m3
    )
    vapor_derivative = vapor_density_derivative(
        et_rate,
        ventilation_rate,
        outside_vapor_density,
        state.vapor_density_inside_kg_m3,
        condensation_rate_kg_s,
        parameters.greenhouse.volume_m3,
    )
    temperature_derivative, energy_terms = indoor_temperature_derivative(
        state.temperature_inside_c,
        weather.temperature_outside_c,
        state.soil_temperature_c,
        solar_inside,
        ventilation_rate,
        et_rate,
        air_density,
        controls.grow_light_state,
        condensation_rate_kg_s,
        parameters,
    )
    soil_temperature_change = soil_temperature_derivative(
        state.temperature_inside_c,
        state.soil_temperature_c,
        solar_inside,
        parameters.soil_thermal,
    )
    soil_moisture_change = soil_moisture_derivative(
        state.soil_moisture_theta,
        controls.pump_state,
        et_rate,
        parameters.soil_water,
        parameters.irrigation,
        atmosphere,
    )
    drainage = drainage_rate_m3_s(
        state.soil_moisture_theta, parameters.soil_water
    )
    light_lux = indoor_illuminance_lux(
        weather.direct_radiation_w_m2,
        weather.diffuse_radiation_w_m2,
        controls.grow_light_state,
        parameters.cover,
        parameters.light,
        parameters.grow_light,
    )
    derivative = StateDerivative(
        temperature_inside_c_s=temperature_derivative,
        vapor_density_inside_kg_m3_s=vapor_derivative,
        soil_temperature_c_s=soil_temperature_change,
        soil_moisture_theta_s=soil_moisture_change,
    )
    diagnostics = PhysicsDiagnostics(
        relative_humidity_inside_percent=relative_humidity_inside,
        vpd_inside_kpa=vpd_inside,
        solar_inside_w_m2=solar_inside,
        light_lux_inside=light_lux,
        ventilation_rate_m3_s=ventilation_rate,
        evapotranspiration_rate_kg_s=et_rate,
        water_stress_coefficient=water_stress,
        drainage_rate_m3_s=drainage,
        air_density_kg_m3=air_density,
        outdoor_vapor_density_kg_m3=outside_vapor_density,
        vapor_ventilation_exchange_kg_s=vapor_exchange,
        q_solar_w=energy_terms["q_solar_w"],
        q_cover_w=energy_terms["q_cover_w"],
        q_ventilation_w=energy_terms["q_ventilation_w"],
        q_soil_w=energy_terms["q_soil_w"],
        q_latent_w=energy_terms["q_latent_w"],
        q_grow_w=energy_terms["q_grow_w"],
        q_condensation_w=energy_terms["q_condensation_w"],
        net_air_energy_w=energy_terms["net_air_energy_w"],
    )
    return derivative, diagnostics


def _weighted_derivative(
    k1: StateDerivative,
    k2: StateDerivative,
    k3: StateDerivative,
    k4: StateDerivative,
) -> StateDerivative:
    def weighted(attribute: str) -> float:
        return (
            getattr(k1, attribute)
            + 2.0 * getattr(k2, attribute)
            + 2.0 * getattr(k3, attribute)
            + getattr(k4, attribute)
        ) / 6.0

    return StateDerivative(
        temperature_inside_c_s=weighted("temperature_inside_c_s"),
        vapor_density_inside_kg_m3_s=weighted(
            "vapor_density_inside_kg_m3_s"
        ),
        soil_temperature_c_s=weighted("soil_temperature_c_s"),
        soil_moisture_theta_s=weighted("soil_moisture_theta_s"),
    )


def _weighted_diagnostic(
    diagnostics: Iterable[PhysicsDiagnostics], attribute: str
) -> float:
    d1, d2, d3, d4 = diagnostics
    return (
        getattr(d1, attribute)
        + 2.0 * getattr(d2, attribute)
        + 2.0 * getattr(d3, attribute)
        + getattr(d4, attribute)
    ) / 6.0


def rk4_step(
    state: GreenhouseState,
    timestep_s: float,
    weather_at_fraction: Callable[[float], WeatherForcing],
    interval_fraction: float,
    controls: ActuatorState,
    parameters: ModelParameters,
) -> tuple[GreenhouseState, BalanceTotals, float]:
    """Advance one RK4 substep and apply mass-conserving physical closures."""

    half_fraction = interval_fraction / 2.0
    weather_1 = weather_at_fraction(0.0)
    weather_2 = weather_at_fraction(half_fraction)
    weather_4 = weather_at_fraction(interval_fraction)

    k1, d1 = evaluate_system(state, weather_1, controls, parameters)
    state_2 = state.add_scaled(k1, timestep_s / 2.0)
    k2, d2 = evaluate_system(state_2, weather_2, controls, parameters)
    state_3 = state.add_scaled(k2, timestep_s / 2.0)
    k3, d3 = evaluate_system(state_3, weather_2, controls, parameters)
    state_4 = state.add_scaled(k3, timestep_s)
    k4, d4 = evaluate_system(state_4, weather_4, controls, parameters)

    mean_derivative = _weighted_derivative(k1, k2, k3, k4)
    candidate = state.add_scaled(mean_derivative, timestep_s)
    candidate_values = (
        candidate.temperature_inside_c,
        candidate.vapor_density_inside_kg_m3,
        candidate.soil_temperature_c,
        candidate.soil_moisture_theta,
    )
    if not all(math.isfinite(value) for value in candidate_values):
        raise NumericalSimulationError(f"RK4 produced NaN/Inf state: {candidate}")
    if not -50.0 <= candidate.temperature_inside_c <= 100.0:
        raise NumericalSimulationError(
            f"Indoor temperature numerical explosion: {candidate.temperature_inside_c} degC"
        )
    if not -20.0 <= candidate.soil_temperature_c <= 80.0:
        raise NumericalSimulationError(
            f"Soil temperature numerical explosion: {candidate.soil_temperature_c} degC"
        )
    if candidate.vapor_density_inside_kg_m3 < 0.0:
        raise NumericalSimulationError(
            "Negative indoor vapour density after RK4 step: "
            f"{candidate.vapor_density_inside_kg_m3} kg/m3"
        )

    water = parameters.soil_water
    if candidate.soil_moisture_theta < water.residual_lower_bound:
        raise NumericalSimulationError(
            "Root-zone moisture fell below configured residual bound: "
            f"{candidate.soil_moisture_theta} < {water.residual_lower_bound}."
        )
    overflow_m3 = 0.0
    bounded_theta = candidate.soil_moisture_theta
    if candidate.soil_moisture_theta > water.saturation_upper_bound:
        overflow_m3 = (
            candidate.soil_moisture_theta - water.saturation_upper_bound
        ) * water.root_volume_m3
        bounded_theta = water.saturation_upper_bound

    saturation_density = saturation_vapor_density_kg_m3(
        candidate.temperature_inside_c, parameters.atmosphere
    )
    condensation_mass_kg = 0.0
    bounded_vapor_density = candidate.vapor_density_inside_kg_m3
    if candidate.vapor_density_inside_kg_m3 > saturation_density:
        condensation_mass_kg = (
            candidate.vapor_density_inside_kg_m3 - saturation_density
        ) * parameters.greenhouse.volume_m3
        bounded_vapor_density = saturation_density

    bounded_state = GreenhouseState(
        temperature_inside_c=candidate.temperature_inside_c,
        vapor_density_inside_kg_m3=bounded_vapor_density,
        soil_temperature_c=candidate.soil_temperature_c,
        soil_moisture_theta=bounded_theta,
    )
    diagnostics = (d1, d2, d3, d4)
    et_mass = timestep_s * _weighted_diagnostic(
        diagnostics, "evapotranspiration_rate_kg_s"
    )
    drainage_volume = timestep_s * _weighted_diagnostic(
        diagnostics, "drainage_rate_m3_s"
    )
    ventilation_exchange_mass = timestep_s * _weighted_diagnostic(
        diagnostics, "vapor_ventilation_exchange_kg_s"
    )
    net_air_energy = timestep_s * _weighted_diagnostic(
        diagnostics, "net_air_energy_w"
    )
    balances = BalanceTotals(
        irrigation_input_m3=(
            parameters.irrigation.effective_flow_m3_s
            * controls.pump_state
            * timestep_s
        ),
        evapotranspiration_loss_m3=(
            et_mass / parameters.atmosphere.water_density
        ),
        drainage_loss_m3=drainage_volume,
        overflow_drainage_m3=overflow_m3,
        evapotranspiration_source_kg=et_mass,
        ventilation_exchange_kg=ventilation_exchange_mass,
        condensation_sink_kg=condensation_mass_kg,
        net_air_energy_j=net_air_energy,
    )
    return bounded_state, balances, condensation_mass_kg


def create_initial_state(
    first_weather: WeatherForcing, parameters: ModelParameters
) -> GreenhouseState:
    """Build explicit initial state from outdoor T/RH and configured root moisture."""

    initial_vapor_pressure = actual_vapor_pressure_kpa(
        first_weather.temperature_outside_c,
        first_weather.relative_humidity_outside_percent,
        parameters.atmosphere,
    )
    initial_vapor_density = vapor_density_kg_m3(
        first_weather.temperature_outside_c,
        initial_vapor_pressure,
        parameters.atmosphere,
    )
    return GreenhouseState(
        temperature_inside_c=first_weather.temperature_outside_c,
        vapor_density_inside_kg_m3=initial_vapor_density,
        soil_temperature_c=first_weather.temperature_outside_c,
        soil_moisture_theta=parameters.soil_water.initial_theta,
    )


def _build_output_row(
    weather: WeatherForcing,
    state: GreenhouseState,
    controls: ActuatorState,
    diagnostics: PhysicsDiagnostics,
    condensation_rate_kg_s: float,
    parameters: ModelParameters,
) -> dict[str, Any]:
    return {
        "timestamp": weather.timestamp[:16],
        "temperature_outside": weather.temperature_outside_c,
        "humidity_outside": weather.relative_humidity_outside_percent,
        "shortwave_radiation": weather.shortwave_radiation_w_m2,
        "direct_radiation": weather.direct_radiation_w_m2,
        "diffuse_radiation": weather.diffuse_radiation_w_m2,
        "wind_speed": weather.wind_speed_m_s,
        "surface_pressure": weather.surface_pressure_pa,
        "dew_point_outside": weather.dew_point_c,
        "vpd_outside_reference": weather.outdoor_vpd_kpa,
        "et0_outside_reference": weather.outdoor_et0_mm,
        "external_soil_temperature_context": (
            weather.external_soil_temperature_c
        ),
        "external_soil_moisture_context": (
            weather.external_soil_moisture_m3_m3
        ),
        "pump_state": controls.pump_state,
        "fan_state": controls.fan_state,
        "grow_light_state": controls.grow_light_state,
        "vent_state": controls.vent_state,
        "temperature_inside_true": state.temperature_inside_c,
        "humidity_inside_true": diagnostics.relative_humidity_inside_percent,
        "vapor_density_inside_true": state.vapor_density_inside_kg_m3,
        "soil_temperature_inside_true": state.soil_temperature_c,
        "soil_moisture_inside_true": state.soil_moisture_theta,
        "light_lux_inside_true": diagnostics.light_lux_inside,
        "vpd_inside": diagnostics.vpd_inside_kpa,
        "solar_inside": diagnostics.solar_inside_w_m2,
        "ventilation_rate_m3_s": diagnostics.ventilation_rate_m3_s,
        "evapotranspiration_rate_kg_s": (
            diagnostics.evapotranspiration_rate_kg_s
        ),
        "water_stress_coefficient": diagnostics.water_stress_coefficient,
        "condensation_rate_kg_s": condensation_rate_kg_s,
        "drainage_rate_m3_s": diagnostics.drainage_rate_m3_s,
        "air_density": diagnostics.air_density_kg_m3,
        "simulation_id": parameters.simulation.simulation_id,
        "parameter_set_id": parameters.simulation.parameter_set_id,
    }


def run_simulation(
    weather: list[WeatherForcing],
    parameters: ModelParameters,
    internal_timestep_s: int | None = None,
    weather_quality: dict[str, Any] | None = None,
) -> SimulationResult:
    """Run a 30-day hourly-output simulation with internal RK4 substeps."""

    started = time.perf_counter()
    timestep_s = internal_timestep_s or parameters.simulation.internal_timestep_s
    output_interval_s = parameters.simulation.output_interval_s
    if timestep_s <= 0 or output_interval_s % timestep_s != 0:
        raise NumericalSimulationError(
            f"Timestep {timestep_s}s must divide {output_interval_s}s."
        )
    expected_intervals = parameters.simulation.duration_days * 24
    if len(weather) != expected_intervals + 1:
        raise WeatherDataError(
            f"Expected {expected_intervals + 1} weather points, got {len(weather)}."
        )

    state = create_initial_state(weather[0], parameters)
    initial_state = state
    rows: list[dict[str, Any]] = []
    totals = BalanceTotals()
    warnings: list[str] = []
    overflow_events = 0
    condensation_events = 0
    for hour_index in range(expected_intervals):
        left = weather[hour_index]
        right = weather[hour_index + 1]
        hour_start = datetime.fromisoformat(left.timestamp)
        start_controls = actuator_schedule(hour_start, state, left, parameters)
        _, start_diagnostics = evaluate_system(
            state, left, start_controls, parameters
        )
        state_at_hour_start = state
        hourly_condensation_kg = 0.0

        elapsed_s = 0.0
        while elapsed_s < output_interval_s:
            step_timestamp = hour_start + timedelta(seconds=elapsed_s)
            remaining_s = output_interval_s - elapsed_s
            actual_timestep_s = min(float(timestep_s), remaining_s)
            pump_event_s = _seconds_to_next_pump_event(
                step_timestamp, parameters
            )
            if pump_event_s is not None:
                actual_timestep_s = min(actual_timestep_s, pump_event_s)
            if actual_timestep_s <= 0.0:
                raise NumericalSimulationError(
                    f"Nonpositive event-aware timestep at {step_timestamp}."
                )

            step_start_fraction = elapsed_s / output_interval_s
            step_fraction = actual_timestep_s / output_interval_s

            def weather_at(local_fraction: float) -> WeatherForcing:
                return interpolate_weather(
                    left, right, step_start_fraction + local_fraction
                )

            step_weather = weather_at(0.0)
            controls = actuator_schedule(
                step_timestamp, state, step_weather, parameters
            )
            state, step_balances, condensed_kg = rk4_step(
                state,
                actual_timestep_s,
                weather_at,
                step_fraction,
                controls,
                parameters,
            )
            totals.add(step_balances)
            hourly_condensation_kg += condensed_kg
            if step_balances.overflow_drainage_m3 > 0.0:
                overflow_events += 1
            if condensed_kg > 0.0:
                condensation_events += 1
            elapsed_s += actual_timestep_s

        rows.append(
            _build_output_row(
                left,
                state_at_hour_start,
                start_controls,
                start_diagnostics,
                hourly_condensation_kg / output_interval_s,
                parameters,
            )
        )

    if overflow_events:
        warnings.append(
            f"Root-zone saturation closure produced {overflow_events} overflow events; "
            "mass is recorded as drainage."
        )
    if condensation_events:
        warnings.append(
            f"Vapour saturation closure produced {condensation_events} condensation events; "
            "mass is retained in the balance audit."
        )
    return SimulationResult(
        rows=rows,
        initial_state=initial_state,
        final_state=state,
        balances=totals,
        weather_quality=weather_quality or {"status": "NOT_RECHECKED"},
        internal_timestep_s=timestep_s,
        runtime_seconds=time.perf_counter() - started,
        warnings=warnings,
    )


def write_simulation_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    """Write simulation output atomically with a stable schema."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with temporary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temporary_path.replace(output_path)
