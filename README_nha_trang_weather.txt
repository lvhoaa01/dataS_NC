NHA TRANG RAW HISTORICAL WEATHER DATASET - 2018-2025

Muc tieu:
Tai du lieu thoi tiet lich su theo gio cho Nha Trang tu Open-Meteo
Historical Weather API de lam RAW weather/external driver dataset cho
SmartGarden/greenhouse dynamics workflow.

Day KHONG phai du lieu cam bien greenhouse, KHONG phai du lieu synthetic,
va KHONG mo phong trang thai ben trong nha kinh.

Nguon:
Open-Meteo Historical Weather API.

Endpoint:
https://archive-api.open-meteo.com/v1/archive

Documentation:
https://open-meteo.com/en/docs/historical-weather-api

Model:
era5_seamless

Toa do:
12.24507, 109.19432 (Nha Trang, Vietnam).

Khoang thoi gian:
2018-01-01 den 2025-12-31.

Timezone:
Asia/Ho_Chi_Minh.

Do phan giai:
hourly.

Output production:
- nha_trang_weather_2018_2025.csv
- nha_trang_weather_2018_2025_metadata.txt

Schema CSV:
timestamp
temperature_2m
relative_humidity_2m
shortwave_radiation
wind_speed_10m
surface_pressure
direct_radiation
diffuse_radiation
dew_point_2m
vapour_pressure_deficit
et0_fao_evapotranspiration
soil_temperature_0_to_7cm
soil_moisture_0_to_7cm

Cach chay tren Windows:
- Double-click run_download_nha_trang_weather.bat
- Hoac chay:
    python download_nha_trang_weather_2018_2025.py

Ghi chu provenance:
soil_temperature_0_to_7cm va soil_moisture_0_to_7cm la external
reanalysis land-surface context, khong phai greenhouse pot/root-zone states.
temperature_2m va relative_humidity_2m la bien thoi tiet ngoai troi,
khong phai trang thai ben trong greenhouse.
