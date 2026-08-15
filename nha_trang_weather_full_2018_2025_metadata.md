# Nha Trang Full Historical Weather Driver Dataset

## Dataset

- Dataset name: Nha Trang full historical weather driver dataset, 2018-2025
- Location: Nha Trang, Khanh Hoa, Vietnam
- Latitude: 12.24507
- Longitude: 109.19432
- Timezone: Asia/Ho_Chi_Minh
- Source: Open-Meteo Historical Weather API
- Endpoint: https://archive-api.open-meteo.com/v1/archive
- Model: ERA5-Seamless (`era5_seamless`)
- Cell selection: `land`
- Start date: 2018-01-01
- End date: 2025-12-31
- Temporal resolution: Hourly
- Number of rows: 70128
- Number of columns: 17
- Generation date: 2026-08-15T10:21:55
- Validation status: PASS

## Data Provenance

This dataset contains historical reanalysis/model-based weather data retrieved from Open-Meteo. It is not greenhouse sensor measurement data.

`soil_moisture_0_to_7cm` is reanalysis/weather-grid soil moisture and must not be interpreted as actual pot, substrate, or greenhouse soil moisture.

`temperature_2m` and `relative_humidity_2m` are outdoor environmental weather variables, not inside-greenhouse state variables.

## Requested Variables

| Column | API unit |
| --- | --- |
| timestamp | iso8601 |
| temperature_2m | °C |
| relative_humidity_2m | % |
| dew_point_2m | °C |
| surface_pressure | hPa |
| wind_speed_10m | km/h |
| wind_direction_10m | ° |
| wind_gusts_10m | km/h |
| precipitation | mm |
| cloud_cover | % |
| shortwave_radiation | W/m² |
| direct_radiation | W/m² |
| diffuse_radiation | W/m² |
| vapour_pressure_deficit | kPa |
| et0_fao_evapotranspiration | mm |
| soil_temperature_0_to_7cm | °C |
| soil_moisture_0_to_7cm | m³/m³ |

## Dataset Summary

- First timestamp: 2018-01-01T00:00
- Last timestamp: 2025-12-31T23:00
- Expected rows: 70128
- Actual rows: 70128
- Duplicate timestamps: 0
- Total missing values: 0
- Timestamp sorted ascending: True

## Missing Values

| Column | Missing count | Missing percent |
| --- | --- | --- |
| timestamp | 0 | 0 |
| temperature_2m | 0 | 0 |
| relative_humidity_2m | 0 | 0 |
| dew_point_2m | 0 | 0 |
| surface_pressure | 0 | 0 |
| wind_speed_10m | 0 | 0 |
| wind_direction_10m | 0 | 0 |
| wind_gusts_10m | 0 | 0 |
| precipitation | 0 | 0 |
| cloud_cover | 0 | 0 |
| shortwave_radiation | 0 | 0 |
| direct_radiation | 0 | 0 |
| diffuse_radiation | 0 | 0 |
| vapour_pressure_deficit | 0 | 0 |
| et0_fao_evapotranspiration | 0 | 0 |
| soil_temperature_0_to_7cm | 0 | 0 |
| soil_moisture_0_to_7cm | 0 | 0 |

## Timestamp Gaps

```text
No timestamp gaps detected.
```

## Basic Statistics

| Column | count | mean | std | min | 25% | 50% | 75% | max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| temperature_2m | 70128 | 26.8351 | 2.91716 | 18.4 | 24.6 | 26.7 | 28.7 | 36.7 |
| relative_humidity_2m | 70128 | 80.8989 | 10.8478 | 41 | 74 | 83 | 89 | 100 |
| dew_point_2m | 70128 | 23.1024 | 2.15885 | 14.2 | 21.9 | 23.5 | 24.7 | 28.3 |
| surface_pressure | 70128 | 1009.8 | 3.63901 | 997 | 1007.2 | 1009.8 | 1012.5 | 1021.9 |
| wind_speed_10m | 70128 | 4.67372 | 2.65401 | 0 | 2.9 | 4 | 5.8 | 19.6 |
| wind_direction_10m | 70128 | 190.472 | 116.115 | 1 | 72 | 225 | 293 | 360 |
| wind_gusts_10m | 70128 | 19.3243 | 9.23188 | 3.2 | 12.2 | 17.6 | 24.8 | 97.2 |
| precipitation | 70128 | 0.251328 | 0.796249 | 0 | 0 | 0 | 0.1 | 17.7 |
| cloud_cover | 70128 | 72.3052 | 31.1091 | 0 | 49 | 87 | 99 | 100 |
| shortwave_radiation | 70128 | 206.173 | 281.835 | 0 | 0 | 9 | 396 | 1038 |
| direct_radiation | 70128 | 138.15 | 214.576 | 0 | 0 | 1 | 227 | 916 |
| diffuse_radiation | 70128 | 68.0229 | 87.9359 | 0 | 0 | 6 | 130 | 449 |
| vapour_pressure_deficit | 70128 | 0.729327 | 0.535437 | 0.01 | 0.37 | 0.57 | 0.96 | 3.58 |
| et0_fao_evapotranspiration | 70128 | 0.153247 | 0.208272 | 0 | 0 | 0.02 | 0.29 | 0.84 |
| soil_temperature_0_to_7cm | 70128 | 27.5096 | 3.12994 | 19.4 | 25.2 | 27.2 | 29.5 | 38.7 |
| soil_moisture_0_to_7cm | 70128 | 0.294134 | 0.0965932 | 0.107 | 0.209 | 0.307 | 0.383 | 0.43 |

## Physical Sanity Checks

| Column | Rule | Violations | Examples |
| --- | --- | --- | --- |
| relative_humidity_2m | 0 <= relative_humidity_2m <= 100 | 0 | [] |
| cloud_cover | 0 <= cloud_cover <= 100 | 0 | [] |
| soil_moisture_0_to_7cm | soil_moisture_0_to_7cm >= 0 | 0 | [] |
| shortwave_radiation | shortwave_radiation >= 0 | 0 | [] |
| direct_radiation | direct_radiation >= 0 | 0 | [] |
| diffuse_radiation | diffuse_radiation >= 0 | 0 | [] |
| vapour_pressure_deficit | vapour_pressure_deficit >= 0 | 0 | [] |
| precipitation | precipitation >= 0 | 0 | [] |
| et0_fao_evapotranspiration | et0_fao_evapotranspiration >= 0 | 0 | [] |
| dew_point_2m | dew_point_2m <= temperature_2m | 0 | [] |

## Radiation Checks

```json
{
  "correlation": {
    "shortwave_radiation_vs_direct_radiation": 0.9734683865666764,
    "shortwave_radiation_vs_diffuse_radiation": 0.8296004855400456,
    "direct_radiation_vs_diffuse_radiation": 0.6798256322383289
  },
  "range": {
    "shortwave_radiation": {
      "min": 0.0,
      "max": 1038.0
    },
    "direct_radiation": {
      "min": 0.0,
      "max": 916.0
    },
    "diffuse_radiation": {
      "min": 0.0,
      "max": 449.0
    }
  },
  "nighttime_definition": "local hour < 06:00 or >= 18:00",
  "nighttime_rows": 35064,
  "nighttime_positive_counts": {
    "shortwave_radiation": 3136,
    "direct_radiation": 2363,
    "diffuse_radiation": 3136
  },
  "negative_counts": {
    "shortwave_radiation": 0,
    "direct_radiation": 0,
    "diffuse_radiation": 0
  },
  "note": "shortwave_radiation is not forcibly checked as direct_radiation + diffuse_radiation because API variable definitions may differ."
}
```

## API Returned Metadata By Year

```json
[
  {
    "year": 2018,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2019,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2020,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2021,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2022,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2023,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2024,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  },
  {
    "year": 2025,
    "latitude": 12.200005,
    "longitude": 109.20001,
    "elevation": 10.0,
    "timezone": "Asia/Ho_Chi_Minh",
    "utc_offset_seconds": 25200
  }
]
```

## Notes

- Raw API missing values are preserved.
- No fill, interpolation, clipping, greenhouse simulation, sensor-noise simulation, actuator simulation, or radiation-to-lux conversion was performed.
- Dew point, vapour pressure deficit, and ET0 were retrieved from the API directly instead of being recalculated locally.
