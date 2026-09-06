@echo off
cd /d "%~dp0.."
set "ONYX_LIVE_ROLLBACK_V10=1"
".venv\Scripts\pythonw.exe" "scripts\launch_onyx_live_v10.pyw"
