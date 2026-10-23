@echo off
rem Double-click: finds the LMS Pis (same Wi-Fi or a LAN cable) and shows their IP addresses.
rem "find_pi.cmd update" also points .env and the Pis at the new addresses.
cd /d "%~dp0"
if /i "%1"=="update" (
  .venv\Scripts\python.exe infra\find_pi.py --update
) else (
  .venv\Scripts\python.exe infra\find_pi.py
)
echo.
pause
