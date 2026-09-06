"""Operator-run Microsoft Graph Calendar V1 live mutation evidence runner.

Not runtime wiring. Runs only when an operator invokes it manually with
``ONYX_PHASE8_MICROSOFT_GRAPH_CALENDAR_V1=true`` plus the secret-free onboarding
environment, after the device sign-in bootstrap has primed the native vault and
the Entra app carries delegated ``Calendars.ReadWrite`` consent. It reads the
calendar to compute availability, picks a free slot, builds one clearly
labelled test-event draft through the frozen read adapter, issues a single
one-shot exact grant and creates exactly one event, then prints the redacted
receipt and reconciliation result. No secret, token or event body is printed.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.control_plane import ControlPlaneStore  # noqa: E402
from core.workspaces import WorkspaceRegistry  # noqa: E402
from core.phase7_workspace_aliases_v1 import (  # noqa: E402
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_calendar_v1 import (  # noqa: E402
    FEATURE_FLAG,
    GraphCalendarFeatureGateV1,
    GraphCalendarV1Uncertain,
    create_microsoft_graph_calendar_v1,
    find_conflicts,
    free_slots,
    issue_event_mutation_grant_v1,
)
from core.phase8_microsoft_graph_device_bootstrap_v2 import (  # noqa: E402
    build_runner_credential_record,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (  # noqa: E402
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (  # noqa: E402
    GraphOAuthFeatureGateV1,
    GraphOAuthV1Denied,
    NativeGraphRefreshTokenVaultV1,
    create_microsoft_graph_oauth_v1,
)


class _BestEffortRotationVault:
    """Wrap the frozen native vault so an oversized rotated refresh token does
    not abort the mutation.

    Defect exposed live 2026-07-24: the write-scoped (`Calendars.ReadWrite`)
    refresh token Microsoft returns exceeds the frozen OAuth V1 vault's
    1800-byte cap, so the frozen `set_refresh_token` raises and Calendar V1's
    `_write_token` fails the whole create. Microsoft does not revoke the prior
    refresh token when issuing a new one, so keeping the stored token is safe.
    This runner-level wrapper preserves the frozen bytes; a corrective Calendar
    successor should make rotation best-effort or a future OAuth successor
    should raise the cap.
    """

    __slots__ = ("_inner", "rotation_skipped")

    def __init__(self, inner: NativeGraphRefreshTokenVaultV1) -> None:
        self._inner = inner
        self.rotation_skipped = False

    def get_refresh_token(self):
        return self._inner.get_refresh_token()

    def set_refresh_token(self, value: str) -> None:
        try:
            self._inner.set_refresh_token(value)
        except GraphOAuthV1Denied:
            self.rotation_skipped = True

    def delete_refresh_token(self) -> bool:
        return self._inner.delete_refresh_token()
from core.phase8_microsoft_graph_read_v1 import (  # noqa: E402
    GraphReadFeatureGateV1,
    create_microsoft_graph_read_adapter_v1,
)

WORKSPACE_ID = "cyryx-live-e2e"
PRINCIPAL_ID = "owner:live-e2e"
ALIAS_NAME = "microsoft-live-e2e"


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _now_epoch_s() -> int:
    return int(time.time())


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build(sandbox: Path, onboarding: MicrosoftGraphLiveOnboardingV1):
    sandbox.mkdir(parents=True, exist_ok=True)
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=sandbox,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        WORKSPACE_ID, display_name="Cyryx Live E2E", workspace_class="cyryx"
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
    return control, catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report-dir",
        default=str(Path.home() / "AppData/Local/Temp/onyx-phase8-calendar-e2e"),
    )
    parser.add_argument("--duration-minutes", type=int, default=30)
    parser.add_argument("--window-hours", type=int, default=48)
    arguments = parser.parse_args()
    if not GraphCalendarFeatureGateV1.from_environ().enabled:
        print(f"Set {FEATURE_FLAG}=true to run the calendar mutation.", file=sys.stderr)
        return 2
    try:
        onboarding = MicrosoftGraphLiveOnboardingV1.from_environ()
    except (PermissionError, ValueError) as exc:
        print(f"Onboarding environment rejected: {exc}", file=sys.stderr)
        return 2

    report_dir = Path(arguments.report_dir)
    sandbox = report_dir / f"control-plane-{_utc_stamp().replace(':', '')}"
    control, catalog = _build(sandbox, onboarding)
    try:
        credential = build_runner_credential_record(
            onboarding=onboarding, now_ms=_now_ms()
        )
        vault = _BestEffortRotationVault(NativeGraphRefreshTokenVaultV1(credential))

        # Read path (frozen OAuth + read adapter) to compute availability.
        oauth = create_microsoft_graph_oauth_v1(
            gate=GraphOAuthFeatureGateV1(True),
            aliases=catalog,
            credential_alias_name=ALIAS_NAME,
            settings=onboarding.settings(),
            http=None,
            vault=vault,
            now_ms=_now_ms(),
            project_root=PROJECT,
        )
        if oauth is None:
            raise RuntimeError("OAuth session unavailable")
        oauth.restore(now_ms=_now_ms(), now_epoch_s=_now_epoch_s())
        read_transport = oauth.create_read_transport(
            clock_epoch_s=_now_epoch_s, clock_ms=_now_ms
        )
        read_adapter = create_microsoft_graph_read_adapter_v1(
            gate=GraphReadFeatureGateV1(True),
            aliases=catalog,
            credential_alias_name=ALIAS_NAME,
            transport=read_transport,
            now_ms=_now_ms(),
            project_root=PROJECT,
        )
        if read_adapter is None:
            raise RuntimeError("read adapter unavailable")

        start = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
        window_start = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        window_end = (
            start + timedelta(hours=arguments.window_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        brief = read_adapter.daily_brief(
            window_start=window_start,
            window_end=window_end,
            outlook_timezone="UTC",
            now_ms=_now_ms(),
            generated_at=_utc_stamp(),
        )
        slots = free_slots(
            brief.events,
            window_start=window_start,
            window_end=window_end,
            duration_minutes=arguments.duration_minutes,
        )
        if not slots:
            print("No free slot found in the window.", file=sys.stderr)
            return 1
        slot_start, slot_end = slots[0]
        conflicts = find_conflicts(
            brief.events, window_start=slot_start, window_end=slot_end
        )
        print(f"Chosen free slot   : {slot_start} .. {slot_end}")
        print(f"Conflicts in slot  : {len(conflicts)} (expected 0)")

        draft = read_adapter.draft_event(
            subject="Onyx Calendar V1 live test — safe to delete",
            start=slot_start,
            end=slot_end,
            timezone_name="UTC",
            body_text=(
                "Created by the Onyx Phase 8 Calendar V1 live evidence runner. "
                "This is a harmless test event; delete it anytime."
            ),
        )

        session = create_microsoft_graph_calendar_v1(
            gate=GraphCalendarFeatureGateV1.from_environ(),
            onboarding=onboarding,
            http=None,
            vault=vault,
            integrity_key=secrets.token_bytes(32),
            clock_ms=_now_ms,
            clock_epoch_s=_now_epoch_s,
            project_root=PROJECT,
        )
        if session is None:
            raise RuntimeError("calendar session gate disabled")
        grant = issue_event_mutation_grant_v1(
            integrity_key=session._integrity_key,
            workspace_id=WORKSPACE_ID,
            principal_id=PRINCIPAL_ID,
            account_id=onboarding.account_id,
            draft=draft,
            nonce=secrets.token_hex(16),
            now_ms=_now_ms(),
        )
        print("Creating one test event via POST /me/events…")
        try:
            receipt = session.create_event(draft=draft, grant=grant)
        except GraphCalendarV1Uncertain:
            print("Outcome uncertain; reconciling against provider state…")
            receipt = session.reconcile_uncertain(draft=draft)
            if receipt is None:
                print("No matching event found; safe to retry with a fresh grant.")
                return 1

        payload = {
            "schema": "OnyxMicrosoftGraphCalendarLiveRun.v1",
            "account_id": receipt.account_id,
            "event_id": receipt.event_id,
            "draft_sha256": receipt.draft_sha256,
            "provider_request_id": receipt.provider_request_id,
            "reconciled": receipt.reconciled,
            "slot_start": slot_start,
            "slot_end": slot_end,
            "conflicts_in_slot": len(conflicts),
            "generated_at": _utc_stamp(),
        }
        report_dir.mkdir(parents=True, exist_ok=True)
        destination = (
            report_dir / f"calendar-run-{_utc_stamp().replace(':', '')}.json"
        )
        destination.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Event created      : {receipt.event_id}")
        print(f"Reconciled         : {receipt.reconciled}")
        print(f"Provider request-id: {receipt.provider_request_id}")
        print(f"Web link           : {receipt.web_link}")
        print(f"Report written     : {destination}")
        return 0
    finally:
        control.close()


if __name__ == "__main__":
    raise SystemExit(main())
