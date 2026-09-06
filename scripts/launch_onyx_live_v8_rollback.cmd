@echo off
setlocal
set "ONYX_LIVE_ROLLBACK_V8=1"
start "Onyx Live V7" /b "%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0launch_onyx_live_v8.pyw"
endlocal
