@echo off
setlocal
set "ONYX_LIVE_ROLLBACK_V5=1"
start "Onyx Legacy" /b "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0launch_onyx_live_v5.pyw"
endlocal
