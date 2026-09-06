@echo off
setlocal
set "ONYX_LIVE_ROLLBACK_V9=1"
start "Onyx Live V8" /b "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0launch_onyx_live_v9.pyw"
endlocal
