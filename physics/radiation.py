"""E1 cover transmission and E10 indoor illuminance."""

from __future__ import annotations

from .config import CoverParameters, GrowLightParameters, LightParameters


def greenhouse_solar_radiation(
    shortwave_outside_w_m2: float, cover: CoverParameters
) -> float:
    """E1: transmit nonnegative outdoor shortwave radiation through the cover."""

    return cover.shortwave_transmittance * max(shortwave_outside_w_m2, 0.0)


def indoor_illuminance_lux(
    direct_radiation_w_m2: float,
    diffuse_radiation_w_m2: float,
    grow_light_state: int,
    cover: CoverParameters,
    light: LightParameters,
    grow_light: GrowLightParameters,
) -> float:
    """E10: convert direct/diffuse irradiance to indoor lux and add grow light."""

    direct_lux = (
        light.direct_luminous_efficacy_lm_w
        * max(direct_radiation_w_m2, 0.0)
    )
    diffuse_lux = (
        light.diffuse_luminous_efficacy_lm_w
        * max(diffuse_radiation_w_m2, 0.0)
    )
    solar_lux = cover.visible_transmittance * (direct_lux + diffuse_lux)
    return max(solar_lux + grow_light.canopy_lux_gain * int(grow_light_state), 0.0)
