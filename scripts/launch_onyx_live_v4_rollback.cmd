@echo off
setlocal
cd /d "%~dp0.."

set "ONYX_LIVE_ROLLBACK_V4=1"
start "" /b ".venv\Scripts\pythonw.exe" "scripts\launch_onyx_live_v4.pyw"
endlocal
