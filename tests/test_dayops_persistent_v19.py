from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.control_plane import ControlPlaneStore
from core.dayops_graph_factory_v19 import (
    DayOpsGraphFactoryV19ContractError,
    PersistentDayOpsGraphFactoryV19,
)
from core.dayops_identity_provisioning_v19 import DayOpsIdentityProvisionerV19
from core.dayops_live_integration_v1 import (
    DayOpsAuthenticationRequiredV1,
    DayOpsConfigurationRequiredV1,
)
from core.dayops_profile_v19 import (
    SCHEMA,
    DayOpsProfileStoreV19,
    DayOpsProfileV19,
    DayOpsProfileV19IdentityMismatch,
    DayOpsProfileV19Tamper,
)
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.phase7_workspace_aliases_v1 import (
    CredentialAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    ENV_ACCOUNT_ID,
    ENV_CLIENT_ID,
    ENV_TENANT_ID,
    LIVE_SCOPES,
)
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_422_800_000
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
KEY = bytes(range(1, 33))


class BytesVault:
    def __init__(self, value: bytes | None = None) -> None:
        self.value = value
        self.writes: list[bytes] = []

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, secret: bytes | bytearray) -> None:
        self.value = bytes(secret)
        self.writes.append(self.value)


class RefreshVault:
    def __init__(self, value: str | None) -> None:
        self.value = value

    def get_refresh_token(self) -> str | None:
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


@dataclass
class CapturingDelegate:
    calls: list[int]
    closes: int = 0

    def __call__(self, now_ms: int):
        self.calls.append(now_ms)
        return None

    def close(self) -> None:
        self.closes += 1


def _identity(
    workspace_id: str = "cyryx-main",
    principal_id: str = "owner-primary",
) -> GovernanceIdentityV1:
    return GovernanceIdentityV1(
        principal_id=principal_id,
        workspace_id=workspace_id,
        account_id="account-primary",
        profile_id="profile-primary",
        workspace_display="Cyryx Labs",
    )


def _profile(identity: GovernanceIdentityV1 | None = None) -> DayOpsProfileV19:
    return DayOpsProfileV19.create(
        _identity() if identity is None else identity,
        client_id=CLIENT_ID,
        tenant_id=TENANT_ID,
        account_id=ACCOUNT_ID,
        iana_timezone="America/New_York",
        outlook_timezone="Eastern Standard Time",
    )


def _store(
    tmp_path: Path,
    *,
    identity: GovernanceIdentityV1 | None = None,
    vault: BytesVault | None = None,
) -> DayOpsProfileStoreV19:
    return DayOpsProfileStoreV19(
        _identity() if identity is None else identity,
        path=tmp_path / "dayops-profile-v19.json",
        key_vault=BytesVault() if vault is None else vault,
    )


def test_profile_roundtrip_is_public_atomic_and_restart_safe(tmp_path: Path) -> None:
    vault = BytesVault()
    first = _store(tmp_path, vault=vault)
    profile = _profile()
    first.save(profile)

    raw = first.path.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert set(envelope) == {"schema", "payload", "mac"}
    assert envelope["schema"] == SCHEMA
    assert set(envelope["payload"]) == {
        "client_id",
        "tenant_id",
        "account_id",
        "iana_timezone",
        "outlook_timezone",
        "workspace_id",
        "principal_id",
        "credential_alias_name",
    }
    assert len(vault.writes) == 1
    assert vault.writes[0].hex() not in raw
    assert "token" not in raw.casefold()
    assert "secret" not in raw.casefold()
    assert "password" not in raw.casefold()
    assert _store(tmp_path, vault=vault).load() == profile


@pytest.mark.parametrize("field", ["client_id", "mac"])
def test_profile_rejects_payload_or_mac_tampering(tmp_path: Path, field: str) -> None:
    vault = BytesVault(KEY)
    store = _store(tmp_path, vault=vault)
    store.save(_profile())
    envelope = json.loads(store.path.read_text(encoding="utf-8"))
    if field == "client_id":
        envelope["payload"][field] = "99999999-2222-4333-8444-555555555555"
    else:
        envelope[field] = "0" * 64
    store.path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(DayOpsProfileV19Tamper):
        store.load()


def test_profile_rejects_valid_mac_bound_to_another_identity(tmp_path: Path) -> None:
    vault = BytesVault(KEY)
    original = _store(tmp_path, vault=vault)
    original.save(_profile())

    other = _identity("cyryx-secondary", "owner-secondary")
    with pytest.raises(DayOpsProfileV19IdentityMismatch):
        _store(tmp_path, identity=other, vault=vault).load()


def test_profile_rejects_secret_field_even_with_valid_mac(tmp_path: Path) -> None:
    vault = BytesVault(KEY)
    store = _store(tmp_path, vault=vault)
    store.save(_profile())
    envelope = json.loads(store.path.read_text(encoding="utf-8"))
    envelope["payload"]["refresh_token"] = "must-never-persist"
    canonical = json.dumps(
        {"schema": SCHEMA, "payload": envelope["payload"]},
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    envelope["mac"] = hmac.new(KEY, canonical, hashlib.sha256).hexdigest()
    store.path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(DayOpsProfileV19Tamper):
        store.load()
    assert "must-never-persist" not in repr(_profile())


def test_persistent_factory_ignores_process_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, vault=BytesVault(KEY))
    profile = _profile()
    store.save(profile)
    for name in (
        "ONYX_DAYOPS_WORKSPACE_ID",
        "ONYX_DAYOPS_PRINCIPAL_ID",
        "ONYX_DAYOPS_CREDENTIAL_ALIAS",
        ENV_CLIENT_ID,
        ENV_TENANT_ID,
        ENV_ACCOUNT_ID,
        "ONYX_DAYOPS_IANA_TIMEZONE",
        "ONYX_DAYOPS_OUTLOOK_TIMEZONE",
    ):
        monkeypatch.setenv(name, "hostile-environment-value")

    captured: list[dict[str, str]] = []
    delegate = CapturingDelegate([])

    def builder(*, environ, **_options):
        captured.append(dict(environ))
        return delegate

    factory = PersistentDayOpsGraphFactoryV19(
        _identity(), store, graph_factory_builder=builder
    )
    assert factory(NOW_MS) is None
    assert captured == [profile.public_environment()]
    assert all(value != "hostile-environment-value" for value in captured[0].values())
    assert delegate.calls == [NOW_MS]


def test_persistent_factory_missing_profile_is_configuration_required(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path, vault=BytesVault(KEY))
    factory = PersistentDayOpsGraphFactoryV19(_identity(), store)
    with pytest.raises(DayOpsConfigurationRequiredV1):
        factory(NOW_MS)


@pytest.mark.parametrize("valid_mac", [False, True])
def test_persistent_factory_maps_tamper_or_identity_drift_to_configuration_required(
    tmp_path: Path,
    valid_mac: bool,
) -> None:
    store = _store(tmp_path, vault=BytesVault(KEY))
    store.save(_profile())
    envelope = json.loads(store.path.read_text(encoding="utf-8"))
    envelope["payload"]["workspace_id"] = "cyryx-secondary"
    if valid_mac:
        canonical = json.dumps(
            {"schema": SCHEMA, "payload": envelope["payload"]},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        envelope["mac"] = hmac.new(KEY, canonical, hashlib.sha256).hexdigest()
    store.path.write_text(json.dumps(envelope), encoding="utf-8")

    factory = PersistentDayOpsGraphFactoryV19(_identity(), store)
    with pytest.raises(DayOpsConfigurationRequiredV1):
        factory(NOW_MS)


def test_persistent_factory_rejects_environment_override(tmp_path: Path) -> None:
    store = _store(tmp_path, vault=BytesVault(KEY))
    with pytest.raises(DayOpsGraphFactoryV19ContractError):
        PersistentDayOpsGraphFactoryV19(
            _identity(), store, graph_factory_options={"environ": {}}
        )


def test_persistent_factory_propagates_disconnected_authentication_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    profile_store = _store(tmp_path, identity=identity, vault=BytesVault(KEY))
    profile = _profile(identity)
    profile_store.save(profile)

    monkeypatch.setattr(
        "core.control_plane.private_control_plane_runtime_dir",
        lambda: tmp_path / "control",
    )
    control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        identity.workspace_id,
        display_name=identity.workspace_display,
        workspace_class="personal",
    )
    aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=registry,
        workspace_id=identity.workspace_id,
        principal_id=identity.principal_id,
        integrity_key=KEY,
        project_root=ROOT,
    )
    assert aliases is not None
    aliases.register(
        profile.credential_alias_name,
        CredentialAliasSpecV1(
            provider="microsoft-graph",
            account_id=profile.account_id,
            tenant_id=profile.tenant_id,
            scopes=LIVE_SCOPES,
        ),
        now_ms=NOW_MS,
    )
    factory = PersistentDayOpsGraphFactoryV19(
        identity,
        profile_store,
        graph_factory_options={
            "store_factory": lambda: control,
            "integrity_key_provider": lambda _binding: KEY,
            "vault": RefreshVault(None),
            "clock_ms": lambda: NOW_MS,
            "clock_epoch_s": lambda: NOW_MS // 1_000,
            "sleeper": lambda _seconds: None,
            "project_root": ROOT,
        },
    )
    try:
        with pytest.raises(DayOpsAuthenticationRequiredV1):
            factory(NOW_MS)
    finally:
        factory.close()
        control.close()


@pytest.mark.parametrize(
    ("workspace_class", "refresh_value", "sign_in_state"),
    [
        ("personal", None, "disconnected"),
        ("professional", "must-never-leak", "connected"),
    ],
)
def test_v19_provisioner_reuses_active_governance_workspace_without_reclassifying(
    tmp_path: Path,
    workspace_class: str,
    refresh_value: str | None,
    sign_in_state: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    profile_store = _store(tmp_path, identity=identity, vault=BytesVault(KEY))
    profile = _profile(identity)
    alias_key_vault = BytesVault()
    monkeypatch.setattr(
        "core.control_plane.private_control_plane_runtime_dir",
        lambda: tmp_path / "identity",
    )
    control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    before = registry.register(
        identity.workspace_id,
        display_name=identity.workspace_display,
        workspace_class=workspace_class,
    )
    control.close()
    provisioner = DayOpsIdentityProvisionerV19(
        identity,
        profile_store,
        store_factory=lambda: ControlPlaneStore(enabled=True),
        integrity_vault_factory=lambda _binding: alias_key_vault,
        refresh_vault_factory=lambda _credential: RefreshVault(refresh_value),
        project_root=ROOT,
    )
    status = provisioner.prepare(profile, now_ms=NOW_MS)

    assert status.workspace == "ready"
    assert status.integrity_key == "ready"
    assert status.credential_alias == "ready"
    assert status.microsoft_sign_in == sign_in_state
    assert "must-never-leak" not in repr(status)
    assert profile_store.load() == profile
    assert provisioner.status(now_ms=NOW_MS) == status
    audit = ControlPlaneStore(enabled=True).initialize()
    try:
        assert (
            WorkspaceRegistry(audit, enabled=True)
            .initialize()
            .get(identity.workspace_id)
            == before
        )
    finally:
        audit.close()
