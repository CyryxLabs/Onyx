@echo off
setlocal
set "ONYX_LIVE_ROLLBACK_V7=1"
start "Onyx Legacy" /b "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0launch_onyx_live_v7.pyw"
endlocal
