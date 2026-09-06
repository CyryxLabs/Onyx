from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import runpy
import sys
from typing import Iterable
from unittest.mock import patch

import pytest

from core.control_plane import ControlPlaneStore
from core.dayops_provisioning_v14 import (
    DayOpsProvisionerV14,
    DayOpsProvisioningConfigV14,
    DayOpsProvisioningStatusV14,
    DayOpsProvisioningV14Cancelled,
    DayOpsProvisioningV14Mismatch,
    DayOpsProvisioningV14Timeout,
    READ_ONLY_SCOPES,
)
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.workspaces import WorkspaceRegistry
from scripts.provision_dayops_v14 import build_parser, main as cli_main


ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"


class FakeBytesVault:
    def __init__(self) -> None:
        self.value: bytes | None = None
        self.writes: list[bytes] = []

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        self.value = bytes(secret)
        self.writes.append(self.value)


class FakeRefreshVault:
    def __init__(self) -> None:
        self.value: str | None = None
        self.writes: list[str] = []
        self.deletes = 0

    def get_refresh_token(self) -> str | None:
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        self.deletes += 1
        existed = self.value is not None
        self.value = None
        return existed


@dataclass(frozen=True)
class Queued:
    method: str
    response: JsonHttpResponseV1


class FakeHttp:
    def __init__(self, responses: Iterable[Queued] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def _next(self, method: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {method} request")
        queued = self.responses.pop(0)
        assert queued.method == method
        return queued.response

    def post_form(self, *, url, fields, timeout_seconds):
        self.calls.append(("POST", url))
        return self._next("POST")

    def get_json(self, *, url, query, headers, timeout_seconds):
        self.calls.append(("GET", url))
        return self._next("GET")


def _config(*, account_id: str = ACCOUNT_ID) -> DayOpsProvisioningConfigV14:
    return DayOpsProvisioningConfigV14(
        CLIENT_ID,
        TENANT_ID,
        account_id,
        "cyryx-main",
        "owner:pedro",
        "microsoft-primary",
    )


@pytest.fixture
def isolated_runtime(tmp_path: Path):
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        yield


def _provisioner(
    config: DayOpsProvisioningConfigV14,
    integrity: FakeBytesVault,
    refresh: FakeRefreshVault,
    http: FakeHttp,
    **options,
) -> DayOpsProvisionerV14:
    return DayOpsProvisionerV14(
        config,
        store_factory=lambda: ControlPlaneStore(enabled=True),
        integrity_vault_factory=lambda _binding: integrity,
        refresh_vault_factory=lambda _credential: refresh,
        http=http,
        sleeper=options.pop("sleeper", lambda _seconds: None),
        clock_epoch_s=options.pop("clock_epoch_s", lambda: 1_785_000_000),
        monotonic=options.pop("monotonic", lambda: 0.0),
        project_root=ROOT,
        **options,
    )


def _device_response() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "device_code": "device-secret-1",
            "user_code": "ABCD-EFGH",
            "verification_uri": "https://login.microsoft.com/device",
            "expires_in": 900,
            "interval": 5,
        },
    )


def _token_response() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "token_type": "Bearer",
            "access_token": "access-secret-1",
            "refresh_token": "refresh-secret-1",
            "expires_in": 3_600,
            "scope": "User.Read Calendars.Read Mail.Read",
        },
    )


def _profile() -> JsonHttpResponseV1:
    return JsonHttpResponseV1(
        200,
        {
            "id": "object-1",
            "mail": ACCOUNT_ID,
            "userPrincipalName": ACCOUNT_ID,
        },
    )


def test_prepare_is_idempotent_and_status_is_zero_network(
    isolated_runtime,
) -> None:
    integrity = FakeBytesVault()
    refresh = FakeRefreshVault()
    http = FakeHttp()
    provisioner = _provisioner(_config(), integrity, refresh, http)

    first = provisioner.prepare(now_ms=NOW_MS)
    second = provisioner.prepare(now_ms=NOW_MS + 1)
    status = provisioner.status(now_ms=NOW_MS + 2)

    assert first == second == status
    assert status.as_dict() == {
        "schema": "OnyxDayOpsProvisioning.v14",
        "workspace": "ready",
        "integrity_key": "ready",
        "credential_alias": "ready",
        "microsoft_sign_in": "disconnected",
    }
    assert len(integrity.writes) == 1
    assert len(integrity.writes[0]) == 32
    assert http.calls == []


def test_prepare_rejects_existing_identity_mismatch(isolated_runtime) -> None:
    integrity = FakeBytesVault()
    refresh = FakeRefreshVault()
    http = FakeHttp()
    _provisioner(_config(), integrity, refresh, http).prepare(now_ms=NOW_MS)

    mismatched = _provisioner(
        _config(account_id="other@cyryxlabs.com"),
        integrity,
        refresh,
        http,
    )
    with pytest.raises(DayOpsProvisioningV14Mismatch, match="does not match"):
        mismatched.prepare(now_ms=NOW_MS + 1)
    assert http.calls == []


def test_sign_in_uses_device_bootstrap_and_never_echoes_tokens(
    isolated_runtime,
) -> None:
    integrity = FakeBytesVault()
    refresh = FakeRefreshVault()
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    provisioner = _provisioner(_config(), integrity, refresh, http)
    provisioner.prepare(now_ms=NOW_MS)
    output: list[str] = []

    result = provisioner.sign_in(echo=output.append, now_ms=NOW_MS + 1)

    assert result.refresh_token_stored is True
    assert refresh.value == "refresh-secret-1"
    assert output == [
        "Verification URL : https://login.microsoft.com/device",
        "User code        : ABCD-EFGH",
    ]
    rendered = "\n".join(output)
    assert "device-secret-1" not in rendered
    assert "access-secret-1" not in rendered
    assert "refresh-secret-1" not in rendered


def test_disconnect_removes_only_refresh_token(isolated_runtime) -> None:
    integrity = FakeBytesVault()
    refresh = FakeRefreshVault()
    http = FakeHttp(
        [
            Queued("POST", _device_response()),
            Queued("POST", _token_response()),
            Queued("GET", _profile()),
        ]
    )
    provisioner = _provisioner(_config(), integrity, refresh, http)
    provisioner.prepare(now_ms=NOW_MS)
    provisioner.sign_in(echo=lambda _line: None, now_ms=NOW_MS + 1)

    disconnected = provisioner.disconnect(now_ms=NOW_MS + 2)

    assert disconnected.microsoft_sign_in == "disconnected"
    assert refresh.value is None
    assert refresh.deletes == 1
    control = ControlPlaneStore(enabled=True).initialize()
    try:
        registry = WorkspaceRegistry(control, enabled=True).initialize()
        registry.require_active("cyryx-main")
        catalog = create_workspace_alias_catalog_v1(
            gate=WorkspaceAliasFeatureGateV1(True),
            registry=registry,
            workspace_id="cyryx-main",
            principal_id="owner:pedro",
            integrity_key=integrity.value,
            project_root=ROOT,
        )
        assert catalog is not None
        credential = catalog.get(
            kind="credential",
            alias_name="microsoft-primary",
            now_ms=NOW_MS + 3,
        )
        assert credential.scopes == READ_ONLY_SCOPES
    finally:
        control.close()


def test_sign_in_supports_cancel_and_local_timeout(isolated_runtime) -> None:
    integrity = FakeBytesVault()
    refresh = FakeRefreshVault()
    provisioner = _provisioner(
        _config(), integrity, refresh, FakeHttp([Queued("POST", _device_response())])
    )
    provisioner.prepare(now_ms=NOW_MS)
    with pytest.raises(DayOpsProvisioningV14Cancelled):
        provisioner.sign_in(
            echo=lambda _line: None,
            now_ms=NOW_MS + 1,
            cancel_requested=lambda: True,
        )

    ticks = iter((0.0, 2.0))
    timed = _provisioner(
        _config(),
        integrity,
        refresh,
        FakeHttp([Queued("POST", _device_response())]),
        monotonic=lambda: next(ticks),
    )
    with pytest.raises(DayOpsProvisioningV14Timeout):
        timed.sign_in(
            echo=lambda _line: None,
            now_ms=NOW_MS + 2,
            timeout_seconds=1,
        )


def test_cli_rejects_secret_arguments_without_echoing_values(capsys) -> None:
    secret = "super-secret-value-should-never-appear"
    exit_code = cli_main(["prepare", "--client-secret", secret])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert secret not in captured.out
    assert secret not in captured.err
    assert captured.out == ""
    assert captured.err == "DayOps provisioning failed closed.\n"


def test_cli_outputs_only_redacted_status(capsys) -> None:
    captured_config: list[DayOpsProvisioningConfigV14] = []

    class FakeProvisioner:
        def __init__(self, config) -> None:
            captured_config.append(config)

        def status(self, *, now_ms):
            return DayOpsProvisioningStatusV14(
                "ready", "ready", "ready", "disconnected"
            )

    args = [
        "status",
        "--client-id",
        CLIENT_ID,
        "--tenant-id",
        TENANT_ID,
        "--account-id",
        ACCOUNT_ID,
        "--workspace-id",
        "cyryx-main",
        "--principal-id",
        "owner:pedro",
        "--alias",
        "microsoft-primary",
    ]
    assert cli_main(args, provisioner_factory=FakeProvisioner) == 0
    rendered = capsys.readouterr().out
    assert '"result":"ok"' in rendered
    assert CLIENT_ID not in rendered
    assert TENANT_ID not in rendered
    assert ACCOUNT_ID not in rendered
    assert captured_config == [_config()]


def test_windowed_packaged_preflight_accepts_absent_streams(monkeypatch) -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "bootstrap_onyx.pyw"))
    run = namespace["run"]
    exits: list[int] = []
    monkeypatch.setattr(run.__globals__["runpy"], "run_path", lambda *_a, **_k: None)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "argv", ["Onyx.exe", "--preflight-only"])
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(run.__globals__["os"], "_exit", exits.append)

    run()

    assert exits == [0]


def test_frozen_console_wrapper_uses_installed_product_name(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert build_parser().prog == "Onyx-DayOps"
