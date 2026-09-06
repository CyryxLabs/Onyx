@echo off
cd /d "%~dp0.."
set "ONYX_LIVE_ROLLBACK_V11=1"
".venv\Scripts\pythonw.exe" "scripts\launch_onyx_live_v11.pyw"
