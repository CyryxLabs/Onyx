@echo off
setlocal
cd /d "%~dp0.."

set "ONYX_LIVE_ACTIVATION_V4=1"
set "ONYX_OWNER_PROFILE_V8_LIVE=1"
set "ONYX_HUD_V5_LIVE=1"
set "ONYX_PHASE5_INTEGRATION_V3=1"
set "ONYX_PHASE5_RUNTIME_V3=1"
set "ONYX_PHASE5_GRANT_SHADOW_V3=1"
set "ONYX_PHASE5_APPROVAL_INBOX_V3=1"
set "ONYX_PHASE5_LOW_RISK_V3=1"
set "ONYX_PHASE5_NEXUS_PROJECTION_V3=1"
set "ONYX_PHASE5_LOCAL_CATALOG_READ_V3=1"
set "ONYX_PHASE5_DASHBOARD_PROJECTION_V3=1"
set "ONYX_PHASE5_PRINCIPAL_ID=onyx-owner"
set "ONYX_PHASE5_WORKSPACE_ID=onyx-local-workspace"
set "ONYX_PHASE5_ACCOUNT_ID=cyryx-local-account"
set "ONYX_PHASE5_PROFILE_ID=onyx-owner-profile"

start "" /b ".venv\Scripts\pythonw.exe" "scripts\launch_onyx_live_v4.pyw"
endlocal
