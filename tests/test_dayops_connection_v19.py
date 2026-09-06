from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.dayops_connection_v19 import (
    DayOpsConnectionControllerV19,
    DayOpsConnectionV19ContractError,
)
from core.dayops_graph_factory_v19 import PersistentDayOpsGraphFactoryV19
from core.dayops_identity_provisioning_v19 import DayOpsIdentityProvisionerV19
from core.dayops_live_integration_v1 import (
    DayOpsExecutionV1,
    DayOpsLiveIntegrationV1,
    sanitized_brief_sha256_v1,
)
from core.dayops_live_integration_v2 import FEATURE_FLAG
from core.dayops_profile_v19 import DayOpsProfileStoreV19, DayOpsProfileV19
from core.dayops_provisioning_v14 import (
    DayOpsProvisionerV14,
    DayOpsProvisioningConfigV14,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.workspaces import WorkspaceRegistry


NOW_MS = 1_785_422_800_000
CLIENT_ID = "11111111-2222-4333-8444-555555555555"


class BytesVault:
    def __init__(self, value: bytes | None = None) -> None:
        self.value = value

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


class RefreshVault:
    def __init__(self) -> None:
        self.value: str | None = None

    def get_refresh_token(self) -> str | None:
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _identity() -> GovernanceIdentityV1:
    return GovernanceIdentityV1(
        principal_id="principal-owner",
        workspace_id="workspace-primary",
        account_id="account-owner",
        profile_id="profile-owner",
        workspace_display="Primary Workspace",
    )


def _payload() -> dict[str, object]:
    return {
        "client_id": CLIENT_ID,
        "tenant_id": "common",
        "account_id": "owner@example.com",
        "iana_timezone": "America/New_York",
        "outlook_timezone": "Eastern Standard Time",
    }


def _controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    planner_enabled: bool = False,
):
    if planner_enabled:
        monkeypatch.setenv(FEATURE_FLAG, "true")
    else:
        monkeypatch.delenv(FEATURE_FLAG, raising=False)
    monkeypatch.setattr(
        "core.control_plane.private_control_plane_runtime_dir",
        lambda: tmp_path / "control",
    )
    identity = _identity()
    initial = ControlPlaneStore(enabled=True).initialize()
    WorkspaceRegistry(initial, enabled=True).initialize().register(
        identity.workspace_id,
        display_name=identity.workspace_display,
        workspace_class="personal",
    )
    initial.close()

    profile_key = BytesVault(bytes(range(1, 33)))
    alias_key = BytesVault(bytes(range(33, 65)))
    refresh = RefreshVault()
    profile_store = DayOpsProfileStoreV19(
        identity,
        path=tmp_path / "profile" / "dayops-profile-v19.json",
        key_vault=profile_key,
    )

    def store_factory() -> ControlPlaneStore:
        return ControlPlaneStore(enabled=True)

    identity_provisioner = DayOpsIdentityProvisionerV19(
        identity,
        profile_store,
        store_factory=store_factory,
        integrity_vault_factory=lambda _binding: alias_key,
        project_root=Path(__file__).resolve().parents[1],
    )
    graph_factory = PersistentDayOpsGraphFactoryV19(
        identity,
        profile_store,
        graph_factory_options={
            "store_factory": store_factory,
            "integrity_key_provider": lambda _binding: alias_key.get_bytes(),
            "vault": refresh,
            "clock_ms": lambda: NOW_MS,
            "clock_epoch_s": lambda: NOW_MS // 1_000,
            "sleeper": lambda _seconds: None,
            "project_root": Path(__file__).resolve().parents[1],
        },
    )

    def legacy(profile: DayOpsProfileV19) -> DayOpsProvisionerV14:
        return DayOpsProvisionerV14(
            DayOpsProvisioningConfigV14(
                profile.client_id,
                profile.tenant_id,
                profile.account_id,
                profile.workspace_id,
                profile.principal_id,
                profile.credential_alias_name,
            ),
            store_factory=store_factory,
            integrity_vault_factory=lambda _binding: alias_key,
            refresh_vault_factory=lambda _credential: refresh,
            project_root=Path(__file__).resolve().parents[1],
        )

    return (
        DayOpsConnectionControllerV19(
            identity,
            profile_store,
            identity_provisioner,
            graph_factory,
            provisioner_factory=legacy,
            clock_ms=lambda: NOW_MS,
        ),
        profile_store,
        refresh,
    )


def test_connection_controller_persists_public_profile_and_redacts_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, store, refresh = _controller(tmp_path, monkeypatch)
    assert controller.status()["status"] == "configuration_required"
    result = controller.connect(_payload())
    assert result["status"] == "disconnected"
    assert store.load().account_id == "owner@example.com"
    rendered = repr(result)
    for forbidden in (
        CLIENT_ID,
        "owner@example.com",
        "workspace-primary",
        "principal-owner",
        "refresh_token",
        "device_code",
    ):
        assert forbidden not in rendered

    refresh.value = "vault-only-refresh-token"
    connected = controller.status()
    assert connected["status"] == "connected"
    assert "vault-only-refresh-token" not in repr(connected)
    assert controller.disconnect()["status"] == "disconnected"
    assert refresh.value is None
    controller.close()


def test_connection_controller_rejects_secret_or_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _store, _refresh = _controller(tmp_path, monkeypatch)
    payload = _payload()
    payload["client_secret"] = "forbidden"
    with pytest.raises(DayOpsConnectionV19ContractError):
        controller.connect(payload)
    controller.close()


def test_today_brief_degrades_to_authentication_required_without_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    controller, _store, _refresh = _controller(tmp_path, monkeypatch)
    controller.connect(_payload())
    brief = controller.today_brief()
    assert brief["status"] == "authentication_required"
    assert brief["read_only"] is True
    assert "token" not in repr(brief).casefold()
    controller.close()


def _completed_read() -> DayOpsExecutionV1:
    payload: dict[str, object] = {
        "status": "completed",
        "read_only": True,
        "verification": "provider_response_normalized",
        "source_brief_sha256": "b" * 64,
        "brief_sha256": "",
        "provider_content_untrusted": True,
        "window_start": "2026-07-30T04:00:00Z",
        "window_end": "2026-07-31T04:00:00Z",
        "generated_at": "2026-07-30T14:45:00Z",
        "calendar_has_more": False,
        "mail_has_more": False,
        "events": [],
        "unread_messages": [
            {
                "source_ref": "a" * 64,
                "subject": "Explicit high importance",
                "sender": "owner@example.com",
                "received_at": "2026-07-30T14:40:00Z",
                "importance": "high",
                "has_attachments": False,
            }
        ],
    }
    payload["brief_sha256"] = sanitized_brief_sha256_v1(payload)
    return DayOpsExecutionV1("completed", payload)


def test_v19_operational_path_preserves_default_off_and_exposes_enabled_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _completed_read()
    controller, _store, _refresh = _controller(tmp_path, monkeypatch)
    controller.connect(_payload())
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        off = controller.today_brief()
    assert off["status"] == "completed"
    assert off["read_only"] is True
    assert "planner" not in off
    controller.close()

    controller, _store, _refresh = _controller(
        tmp_path / "enabled", monkeypatch, planner_enabled=True
    )
    controller.connect(_payload())
    with patch.object(DayOpsLiveIntegrationV1, "execute", return_value=original):
        enabled = controller.today_brief()
    assert enabled["status"] == "completed"
    assert enabled["planner_candidate"] is True
    assert enabled["planner"]["important_unread"][0]["subject"] == (
        "Explicit high importance"
    )
    controller.close()
