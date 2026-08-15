@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "SCRIPT=download_nha_trang_weather_2018_2025.py"
set "OUT_CSV=nha_trang_weather_2018_2025.csv"
set "RUNNER="

py -3 --version >nul 2>nul
if not errorlevel 1 set "RUNNER=py -3"

if not defined RUNNER (
  python --version >nul 2>nul
  if not errorlevel 1 set "RUNNER=python"
)

if not defined RUNNER (
  echo ERROR: Khong tim thay Python runner hop le.
  echo Vui long cai Python hoac dam bao lenh "py -3" / "python" co trong PATH.
  call :finish 1
  exit /b 1
)

echo Running: %RUNNER% %SCRIPT%
echo.
%RUNNER% "%SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo ERROR: Downloader hoac validation failed. Production CSV cu da duoc giu lai neu validation khong PASS.
  call :finish %EXIT_CODE%
  exit /b %EXIT_CODE%
)

echo.
echo SUCCESS: Downloader completed and validation passed.
echo CSV:
echo %CD%\%OUT_CSV%
call :finish 0
exit /b 0

:finish
if not defined NO_PAUSE (
  echo.
  pause
)
exit /b %1
