from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.automation_adapters_v1 import (
    AutomationAdapterDenied,
    AutomationAdapterFeatureGateV1,
    AutomationAdapterReplay,
    AutomationAdapterStateV1,
    ExplicitTimezoneTriggerV1,
    SignedWebhookAdapterV1,
    WorkspaceFileEventAdapterV1,
)
from core.governed_automation_v1 import GovernedAutomationDenied
from core.native_vault import SecretReference


SECRET = b"webhook-secret-material-at-least-32-bytes"
OWNER = "owner_primary"
WORKSPACE = "workspace_personal"


def _state(tmp_path: Path) -> AutomationAdapterStateV1:
    return AutomationAdapterStateV1(
        tmp_path / "automation-adapters.sqlite3",
        AutomationAdapterFeatureGateV1(True),
    )


def _webhook(tmp_path: Path, now: float = 1_000.0) -> SignedWebhookAdapterV1:
    return SignedWebhookAdapterV1(
        state=_state(tmp_path),
        source_id="webhook_finance",
        secret_reference=SecretReference(
            "Onyx.AutomationWebhook.v1", "finance", "Finance webhook"
        ),
        vault_reader=lambda reference: SECRET if reference.account == "finance" else None,
        clock=lambda: now,
    )


def _signature(body: bytes, timestamp: float) -> str:
    signed = f"{timestamp:.6f}.".encode() + body
    return "sha256=" + hmac.new(SECRET, signed, hashlib.sha256).hexdigest()


def test_feature_defaults_off_and_adapters_have_zero_idle_workers(tmp_path: Path) -> None:
    assert AutomationAdapterFeatureGateV1.from_environ({}).enabled is False
    with pytest.raises(AutomationAdapterDenied, match="disabled"):
        AutomationAdapterStateV1(
            tmp_path / "off.sqlite3", AutomationAdapterFeatureGateV1(False)
        )
    webhook = _webhook(tmp_path)
    file_adapter = WorkspaceFileEventAdapterV1((tmp_path,))
    assert webhook.background_workers == file_adapter.background_workers == 0
    assert webhook.polling_interval is file_adapter.polling_interval is None


def test_authenticated_webhook_emits_metadata_only_event_and_persists_no_body(
    tmp_path: Path,
) -> None:
    body = b'{"invoice_id":"invoice_001","overdue":true}'
    adapter = _webhook(tmp_path)
    event = adapter.ingest(
        body=body,
        signature=_signature(body, 1_000.0),
        timestamp=1_000.0,
        nonce="nonce_001",
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        event_type="finance.invoice.overdue",
    )
    assert dict(event.metadata) == {"invoice_id": "invoice_001", "overdue": "true"}
    database = (tmp_path / "automation-adapters.sqlite3").read_bytes()
    assert SECRET not in database
    assert body not in database
    assert hashlib.sha256(body).hexdigest().encode() in database


def test_webhook_replay_expiry_tampering_and_sensitive_content_fail_closed(
    tmp_path: Path,
) -> None:
    body = b'{"invoice_id":"invoice_001"}'
    adapter = _webhook(tmp_path)
    arguments = {
        "body": body,
        "signature": _signature(body, 1_000.0),
        "timestamp": 1_000.0,
        "nonce": "nonce_001",
        "owner_profile_id": OWNER,
        "workspace_id": WORKSPACE,
        "event_type": "finance.invoice.updated",
    }
    adapter.ingest(**arguments)
    with pytest.raises(AutomationAdapterReplay):
        adapter.ingest(**arguments)

    expired = _webhook(tmp_path / "expired", now=2_000.0)
    with pytest.raises(AutomationAdapterDenied, match="replay window"):
        expired.ingest(**arguments)

    tampered = _webhook(tmp_path / "tampered")
    with pytest.raises(AutomationAdapterDenied, match="authentication"):
        tampered.ingest(**{**arguments, "body": b'{"invoice_id":"changed"}'})

    sensitive_body = b'{"message_body":"must-not-enter-event"}'
    sensitive = _webhook(tmp_path / "sensitive")
    with pytest.raises(GovernedAutomationDenied, match="sensitive"):
        sensitive.ingest(
            **{
                **arguments,
                "body": sensitive_body,
                "signature": _signature(sensitive_body, 1_000.0),
            }
        )


def test_explicit_timezone_trigger_emits_once_per_local_day(tmp_path: Path) -> None:
    trigger = ExplicitTimezoneTriggerV1(_state(tmp_path))
    timestamp = datetime(2026, 8, 3, 9, 30, tzinfo=timezone.utc).timestamp()
    arguments = {
        "schedule_id": "schedule_morning_brief",
        "timezone": "UTC",
        "hour": 9,
        "minute": 30,
        "now": timestamp,
        "owner_profile_id": OWNER,
        "workspace_id": WORKSPACE,
        "event_type": "schedule.morning.brief",
    }
    event = trigger.due_event(**arguments)
    assert event is not None
    assert dict(event.metadata)["local_date"] == "2026-08-03"
    assert trigger.due_event(**arguments) is None
    assert trigger.due_event(**{**arguments, "now": timestamp + 60}) is None


def test_workspace_file_event_is_scoped_and_never_exposes_raw_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "private-plan.md"
    target.write_text("confidential content", encoding="utf-8")
    adapter = WorkspaceFileEventAdapterV1((workspace,))
    event = adapter.from_native_event(
        path=target,
        event_kind="modified",
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        occurred_at=1_000.0,
    )
    metadata = dict(event.metadata)
    assert metadata["extension"] == ".md"
    assert "private-plan" not in repr(event)
    assert "confidential content" not in repr(event)

    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(AutomationAdapterDenied, match="outside controlled"):
        adapter.from_native_event(
            path=outside,
            event_kind="modified",
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
        )

