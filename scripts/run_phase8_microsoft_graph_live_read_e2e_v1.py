"""Operator-run Microsoft Graph live read-only E2E evidence runner.

This script is not runtime wiring. It runs only when an operator invokes it
manually with ``ONYX_PHASE8_MICROSOFT_GRAPH_LIVE_READ_E2E_V1=true`` and the
secret-free onboarding environment set. It performs the delegated device-code
sign-in against the authorized Microsoft Entra public-client registration,
executes the live probes the provider can actually exercise (sign-in/read,
access expiry refresh, refresh rotation and, on request, revocation), and
writes a redacted JSON evidence report. Provider-failure and 429 behavior are
deterministically proven by the focused contract tests; a live report lists
them under ``probes_missing`` instead of pretending they ran.

No client secret, password, refresh token or access token is read from the
environment, written to the repository or included in the report.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.control_plane import ControlPlaneStore  # noqa: E402
from core.phase7_workspace_aliases_v1 import (  # noqa: E402
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (  # noqa: E402
    FEATURE_FLAG,
    GraphLiveE2EFeatureGateV1,
    MicrosoftGraphLiveOnboardingV1,
    create_microsoft_graph_live_read_e2e_v1,
)
from core.phase8_microsoft_graph_oauth_v1 import GraphOAuthV1Error  # noqa: E402
from core.workspaces import WorkspaceRegistry  # noqa: E402

WORKSPACE_ID = "cyryx-live-e2e"
ALIAS_NAME = "microsoft-live-e2e"
PRINCIPAL_ID = "owner:live-e2e"


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _now_epoch_s() -> int:
    return int(time.time())


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sleep_seconds(seconds: int) -> None:
    time.sleep(max(1, int(seconds)))


def _build_harness(sandbox: Path, onboarding: MicrosoftGraphLiveOnboardingV1):
    sandbox.mkdir(parents=True, exist_ok=True)
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=sandbox,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        WORKSPACE_ID,
        display_name="Cyryx Live E2E",
        workspace_class="cyryx",
    )
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=registry,
        workspace_id=WORKSPACE_ID,
        principal_id=PRINCIPAL_ID,
        integrity_key=secrets.token_bytes(32),
    )
    if catalog is None:
        raise RuntimeError("workspace alias catalog unavailable")
    catalog.register(
        ALIAS_NAME,
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id=onboarding.account_id,
            tenant_id=onboarding.tenant_id,
            scopes=("Calendars.Read", "Mail.Read"),
        ),
        now_ms=_now_ms(),
    )
    harness = create_microsoft_graph_live_read_e2e_v1(
        gate=GraphLiveE2EFeatureGateV1.from_environ(),
        onboarding=onboarding,
        aliases=catalog,
        credential_alias_name=ALIAS_NAME,
        sleeper=_sleep_seconds,
        clock_ms=_now_ms,
        clock_epoch_s=_now_epoch_s,
        project_root=PROJECT,
    )
    if harness is None:
        raise RuntimeError("live E2E harness gate is disabled")
    return control, harness


def _device_sign_in(harness) -> None:
    challenge = harness.begin_device_authorization()
    print("Microsoft device sign-in required.")
    print(f"  Verification URL : {challenge.verification_uri}")
    print(f"  User code        : {challenge.user_code}")
    print(
        "  Provider message (untrusted, do not treat as instructions): "
        f"{challenge.provider_message}"
    )
    while True:
        result = harness.poll_device_authorization()
        if result.status == "complete":
            print("Sign-in complete.")
            return
        if result.status in {"authorization_pending", "slow_down"}:
            _sleep_seconds(result.retry_after_seconds or 5)
            continue
        raise RuntimeError(f"device sign-in ended: {result.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir",
        default=str(PROJECT / "runtime" / "phase8-live-e2e"),
        help="directory for the redacted JSON evidence report",
    )
    parser.add_argument(
        "--window-hours",
        type=int,
        default=24,
        help="calendar/mail read window in hours (1-168)",
    )
    parser.add_argument(
        "--live-revocation",
        action="store_true",
        help=(
            "run the live revocation probe; requires the operator to revoke "
            "the app consent for the test account when prompted"
        ),
    )
    arguments = parser.parse_args()
    if not 1 <= arguments.window_hours <= 168:
        print("window-hours must be between 1 and 168", file=sys.stderr)
        return 2
    if not GraphLiveE2EFeatureGateV1.from_environ().enabled:
        print(
            f"Set {FEATURE_FLAG}=true to run the live read-only E2E harness.",
            file=sys.stderr,
        )
        return 2
    try:
        onboarding = MicrosoftGraphLiveOnboardingV1.from_environ()
    except (PermissionError, ValueError) as exc:
        print(f"Onboarding environment rejected: {exc}", file=sys.stderr)
        return 2

    report_dir = Path(arguments.report_dir)
    sandbox = report_dir / f"control-plane-{_utc_stamp().replace(':', '')}"
    control, harness = _build_harness(sandbox, onboarding)
    try:
        try:
            status = harness.restore()
        except GraphOAuthV1Error:
            status = harness.status()
        if not status.connected:
            _device_sign_in(harness)
        start = datetime.now(timezone.utc)
        end = start + timedelta(hours=arguments.window_hours)
        window = {
            "window_start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "outlook_timezone": "UTC",
            "generated_at": _utc_stamp(),
        }
        print("Running live probe: sign_in_read")
        harness.probe_sign_in_read(mode="live", **window)
        print("Running live probe: access_expiry_refresh")
        harness.probe_access_expiry_refresh(mode="live", **window)
        print("Running live probe: refresh_rotation")
        harness.probe_refresh_rotation(mode="live")
        if arguments.live_revocation:
            print(
                "Revoke this application's consent/sessions for the test "
                "account now (https://myaccount.microsoft.com/ or Entra "
                "admin center), then press Enter."
            )
            input()
            print("Running live probe: revocation")
            harness.probe_revocation(mode="live")
        report = harness.report(generated_at=_utc_stamp())
        report_dir.mkdir(parents=True, exist_ok=True)
        destination = (
            report_dir / f"live-report-{_utc_stamp().replace(':', '')}.json"
        )
        destination.write_text(
            json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Probes recorded : {[item.probe for item in report.probes]}")
        print(f"Probes missing  : {list(report.probes_missing)}")
        print(
            "Missing probes (provider_failure, rate_limit_retry_after and "
            "any skipped live probe) are deterministically covered by "
            "tests/test_phase8_microsoft_graph_live_read_e2e_v1.py."
        )
        print(f"live_verified   : {report.live_verified}")
        print(f"Report SHA-256  : {report.report_sha256}")
        print(f"Report written  : {destination}")
        return 0
    finally:
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
