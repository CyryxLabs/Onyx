#define MyAppVersion GetEnv("ONYX_BUILD_VERSION")
#define MyAppId GetEnv("ONYX_APP_ID")
#define SourceDir GetEnv("ONYX_SOURCE_DIR")
#define OutputDir GetEnv("ONYX_OUTPUT_DIR")
#define SetupBaseName GetEnv("ONYX_SETUP_BASENAME")
#define SetupIcon GetEnv("ONYX_ICON_PATH")
#define LifecycleRecordOverride GetEnv("ONYX_LIFECYCLE_RECORD_PATH")

[Setup]
AppId={#MyAppId}
AppName=Onyx
AppVersion={#MyAppVersion}
AppPublisher=Cyryx Labs
AppPublisherURL=https://cyryxlabs.com
DefaultDirName={localappdata}\Programs\Cyryx Labs\Onyx
DefaultGroupName=Cyryx Labs\Onyx
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename={#SetupBaseName}
SetupIconFile={#SetupIcon}
UninstallDisplayIcon={app}\Onyx.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Never send a synthetic title-bar close: packaged Onyx intentionally treats
; that as "remain resident".  [Code] below uses the authenticated cooperative
; lifecycle client before any installed byte is replaced or removed.
CloseApplications=no
RestartApplications=no
VersionInfoCompany=Cyryx Labs
VersionInfoDescription=Onyx AI Assistant Installer
VersionInfoProductName=Onyx
VersionInfoVersion={#MyAppVersion}
LicenseFile={#SourceDir}\LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
; Owner-controlled and disabled by default. This writes only to the current
; user's Run key, requires no administrator/service account and is removed by
; the uninstaller. Silent installs never opt the owner in implicitly.
Name: "autostart"; Description: "Start Onyx when I sign in"; GroupDescription: "Startup:"; Flags: unchecked

[InstallDelete]
; Delete the exact application-owned desktop shortcut before recreating it.
; Older WScript/Inno candidates left a literal `""` argument in the .lnk;
; merely overwriting the shortcut can preserve that stale field on upgrade.
Type: files; Name: "{autodesktop}\Onyx.lnk"
; PyInstaller's _internal tree is an indivisible, application-owned release
; payload. Remove the previous tree before copying the new one so upgrades
; cannot retain modules, browser engines, tests, or caches that no longer
; exist in the current release. User data lives under
; LocalAppData\Cyryx Labs\Onyx and is intentionally untouched.
Type: filesandordirs; Name: "{app}\_internal"
; Also remove obsolete V14-era top-level source/evidence directories.
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\core"
; Remove the application-owned nested payload produced by an early V15
; packaging candidate that used the bundle parent as SourceDir.
Type: filesandordirs; Name: "{app}\Onyx"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Onyx"; Filename: "{app}\Onyx.exe"
; Always replace a legacy source-checkout/V13 shortcut during install or
; upgrade. The target is the installed executable and never a repository
; virtualenv or versioned bootstrap.
Name: "{autodesktop}\Onyx"; Filename: "{app}\Onyx.exe"; WorkingDir: "{app}"; IconFilename: "{app}\Onyx.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Cyryx Labs Onyx"; ValueData: """{app}\Onyx.exe"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\Onyx.exe"; Description: "Launch Onyx"; Flags: nowait postinstall skipifsilent

[Code]
function LifecycleRecordPath(): String;
begin
#if LifecycleRecordOverride != ""
  Result := '{#LifecycleRecordOverride}';
#else
  Result := ExpandConstant('{localappdata}\Cyryx Labs\Onyx\runtime\installer-lifecycle-v1\resident.json');
#endif
end;

function LegacyOnyxWindowPresent(): Boolean;
begin
  Result :=
    (FindWindowByWindowName('Onyx — Cyryx Labs') <> 0) or
    (FindWindowByWindowName('Onyx') <> 0);
end;

{ Return 0 only when WMI positively proves there is no Onyx.exe process, 1
  when at least one exists, and 2 when inventory is unavailable.  V31 could
  remain alive without a visible window, so title matching is only a secondary
  signal and can never authorize file replacement. }
function GetNamedOnyxProcessState(): Integer;
var
  Locator, Services, Processes: Variant;
begin
  Result := 2;
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Services := Locator.ConnectServer('.', 'root\CIMV2');
    Processes := Services.ExecQuery(
      'SELECT ProcessId FROM Win32_Process WHERE Name = ''Onyx.exe''');
    if Processes.Count > 0 then
      Result := 1
    else
      Result := 0;
  except
    Result := 2;
  end;
end;

function StableOnyxMutexPresent(): Boolean;
begin
  Result := CheckForMutexes('Local\CyryxLabs.Onyx.Live.V15');
end;

function RefuseUnknownOrLegacyResident(): Boolean;
var
  ProcessState: Integer;
begin
  Result := False;
  ProcessState := GetNamedOnyxProcessState();
  if ProcessState = 2 then
  begin
    SuppressibleMsgBox(
      'The Onyx process inventory could not be verified. No application files were changed.' + #13#10 +
      'Close Onyx completely and restore Windows Management Instrumentation, then try again.',
      mbError, MB_OK, IDOK);
    exit;
  end;
  if (ProcessState = 1) or StableOnyxMutexPresent() or LegacyOnyxWindowPresent() then
  begin
    SuppressibleMsgBox(
      'Onyx is still running without a valid cooperative maintenance record.' + #13#10 +
      'Use Exit Onyx, confirm the process has stopped, then run this operation again.',
      mbError, MB_OK, IDOK);
    exit;
  end;
  Result := True;
end;

function RequestCooperativeOnyxShutdown(const Reason: String): Boolean;
var
  ResultCode: Integer;
  Parameters: String;
begin
  Result := True;

  if not FileExists(LifecycleRecordPath()) then
  begin
    { V31 and older do not have the authenticated channel. Process, stable
      mutex and window checks cover hidden/background legacy residents. }
    Result := RefuseUnknownOrLegacyResident();
    exit;
  end;

  if not FileExists(ExpandConstant('{app}\Onyx.exe')) then
  begin
    SuppressibleMsgBox(
      'An Onyx maintenance record exists but the installed control executable is unavailable.' + #13#10 +
      'No application files were changed.',
      mbError, MB_OK, IDOK);
    Result := False;
    exit;
  end;

  Parameters :=
    '--installer-shutdown --maintenance-reason=' + Reason +
    ' --timeout-seconds=75';
  if not Exec(
    ExpandConstant('{app}\Onyx.exe'),
    Parameters,
    ExpandConstant('{app}'),
    SW_HIDE,
    ewWaitUntilTerminated,
    ResultCode) then
  begin
    SuppressibleMsgBox(
      'Onyx maintenance control could not be started. No application files were changed.',
      mbError, MB_OK, IDOK);
    Result := False;
    exit;
  end;
  if ResultCode <> 0 then
  begin
    SuppressibleMsgBox(
      'Onyx refused maintenance shutdown or could not prove complete cleanup.' + #13#10 +
      'No application files were changed. Restore Onyx and use Exit Onyx, then try again.' + #13#10 +
      'Lifecycle exit code: ' + IntToStr(ResultCode),
      mbError, MB_OK, IDOK);
    Result := False;
    exit;
  end;

  { A zero authenticated-client exit is necessary but not sufficient: verify
    independently that no named process, stable mutex, or legacy window remains
    before Inno Setup can enter [InstallDelete] or [Files]. }
  if not RefuseUnknownOrLegacyResident() then
  begin
    Result := False;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not RequestCooperativeOnyxShutdown('upgrade') then
    Result := 'Onyx is still active. Upgrade was stopped before file replacement.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := RequestCooperativeOnyxShutdown('uninstall');
end;
