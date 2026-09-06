@echo off
cd /d "%~dp0.."
set "ONYX_LIVE_ACTIVATION_V10=1"
set "ONYX_PHASE6_LIVE_WIRING_V1=true"
set "ONYX_HUD_V7_LIVE=1"
".venv\Scripts\pythonw.exe" "scripts\bootstrap_onyx_live_v10.pyw"
