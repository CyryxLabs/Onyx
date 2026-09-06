from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from core import phase7_workspace_aliases_v1 as aliases
from core.control_plane import ControlPlaneStore
from core.phase7_workspace_aliases_v1 import (
    ArtifactAliasSpecV1,
    CredentialAliasSpecV1,
    ProfileAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    WorkspaceAliasV1Conflict,
    WorkspaceAliasV1ContractError,
    WorkspaceAliasV1Denied,
    create_workspace_alias_catalog_v1,
)
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(1, 33))
NOW_MS = 1_785_000_000_000
CREATED_AT = "2026-07-23T16:00:00+00:00"


@dataclass
class Fixture:
    control: ControlPlaneStore
    registry: WorkspaceRegistry


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    registry = WorkspaceRegistry(control, enabled=True).initialize()
    registry.register(
        "cyryx-main",
        display_name="Cyryx Main",
        workspace_class="cyryx",
    )
    registry.register(
        "client-one",
        display_name="Client One",
        workspace_class="client",
    )
    value = Fixture(control, registry)
    try:
        yield value
    finally:
        control.close()


def _catalog(
    fixture: Fixture,
    *,
    workspace_id: str = "cyryx-main",
    principal_id: str = "owner:pedro",
    key: bytes = KEY,
):
    catalog = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.registry,
        workspace_id=workspace_id,
        principal_id=principal_id,
        integrity_key=key,
    )
    assert catalog is not None
    return catalog


def _credential(**changes: object) -> CredentialAliasSpecV1:
    values: dict[str, object] = {
        "provider": "google",
        "account_id": "owner@cyryxlabs.com",
        "tenant_id": "cyryx",
        "scopes": ("calendar.readonly", "mail.readonly"),
        "rotate_after_ms": NOW_MS + 50_000,
        "revoke_after_ms": NOW_MS + 100_000,
    }
    values.update(changes)
    return CredentialAliasSpecV1(**values)  # type: ignore[arg-type]


def _profile(**changes: object) -> ProfileAliasSpecV1:
    values: dict[str, object] = {
        "browser": "chrome",
        "profile_id": "company-ops",
        "allowed_domains": ("cyryxlabs.com", "microsoft.com"),
    }
    values.update(changes)
    return ProfileAliasSpecV1(**values)  # type: ignore[arg-type]


def _artifact(
    fixture: Fixture,
    *,
    workspace_id: str = "cyryx-main",
    artifact_id: str = "artifact-founder-brief",
    content: bytes = b"founder brief",
    status: str = "available",
) -> ArtifactAliasSpecV1:
    digest = hashlib.sha256(content).hexdigest()
    fixture.control._require_connection().execute(
        "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
        (
            artifact_id,
            workspace_id,
            1,
            digest,
            f"{digest[:2]}/{digest}",
            "application/pdf",
            status,
            CREATED_AT,
        ),
    )
    return ArtifactAliasSpecV1(
        artifact_id=artifact_id,
        sha256=digest,
        relative_path=f"{digest[:2]}/{digest}",
        media_type="application/pdf",
    )


def _payload(
    fixture: Fixture,
    *,
    kind: str,
    alias_name: str,
    principal_id: str = "owner:pedro",
) -> tuple[str, dict[str, object]]:
    alias_id = aliases.workspace_alias_id_v1(
        workspace_id="cyryx-main",
        principal_id=principal_id,
        kind=kind,
        alias_name=alias_name,
    )
    row = fixture.control._require_connection().execute(
        "SELECT payload_json FROM capability_descriptors WHERE capability_id=?",
        (alias_id,),
    ).fetchone()
    assert row is not None
    return alias_id, json.loads(str(row[0]))


def test_flag_is_exact_and_default_off_returns_before_entry_validation() -> None:
    assert WorkspaceAliasFeatureGateV1.from_environ({}).enabled is False
    assert (
        WorkspaceAliasFeatureGateV1.from_environ(
            {aliases.FEATURE_FLAG: aliases.ENABLED_VALUE}
        ).enabled
        is True
    )
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert (
            WorkspaceAliasFeatureGateV1.from_environ(
                {aliases.FEATURE_FLAG: value}
            ).enabled
            is False
        )
    assert (
        create_workspace_alias_catalog_v1(
            gate=WorkspaceAliasFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_accepted_workspace_memory_is_exact_entry_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aliases._verify_workspace_memory_entry(ROOT)
    changed = list(aliases.WORKSPACE_MEMORY_ENTRY_ROOTS)
    path, _digest = changed[0]
    changed[0] = (path, "0" * 64)
    monkeypatch.setattr(
        aliases,
        "WORKSPACE_MEMORY_ENTRY_ROOTS",
        tuple(changed),
    )
    with pytest.raises(
        WorkspaceAliasV1Denied,
        match="entry evidence drift",
    ):
        aliases._verify_workspace_memory_entry(ROOT)


def test_factory_is_sealed_complete_and_nonlegacy(fixture: Fixture) -> None:
    with pytest.raises(WorkspaceAliasV1ContractError, match="sealed feature gate"):
        create_workspace_alias_catalog_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(
        WorkspaceAliasV1ContractError,
        match="complete host bindings",
    ):
        create_workspace_alias_catalog_v1(
            gate=WorkspaceAliasFeatureGateV1(True),
        )
    with pytest.raises(
        WorkspaceAliasV1ContractError,
        match="non-legacy workspace",
    ):
        create_workspace_alias_catalog_v1(
            gate=WorkspaceAliasFeatureGateV1(True),
            registry=fixture.registry,
            workspace_id="legacy-default",
            principal_id="owner:pedro",
            integrity_key=KEY,
        )


def test_credential_alias_persists_only_locator_identity_and_metadata(
    fixture: Fixture,
) -> None:
    before = fixture.control._require_connection().execute(
        "SELECT count(*) FROM capability_descriptors"
    ).fetchone()[0]
    record = _catalog(fixture).register(
        "google-primary",
        _credential(),
        now_ms=NOW_MS,
    )
    after = fixture.control._require_connection().execute(
        "SELECT count(*) FROM capability_descriptors"
    ).fetchone()[0]

    assert after == before + 1
    assert record.kind == "credential"
    assert record.workspace_id == "cyryx-main"
    assert record.principal_id == "owner:pedro"
    assert record.provider == "google"
    assert record.account_id == "owner@cyryxlabs.com"
    assert record.scopes == ("calendar.readonly", "mail.readonly")
    assert record.locator.startswith("onyx-vault://v1/cyryx-main/google/")
    assert record.vault_service == "CyryxLabs.Onyx.v1.cyryx-main.google"
    assert record.vault_account == "cyryx:owner@cyryxlabs.com"
    _alias_id, payload = _payload(
        fixture,
        kind="credential",
        alias_name="google-primary",
    )
    serialized = json.dumps(payload, sort_keys=True)
    assert "hmac_sha256" in payload
    assert "api_key" not in serialized
    assert "access_token" not in serialized
    assert "refresh_token" not in serialized
    assert "cookie" not in serialized
    assert "private_key" not in serialized


def test_register_is_idempotent_but_immutable_conflicts_fail(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    first = catalog.register("google-primary", _credential(), now_ms=NOW_MS)
    replay = catalog.register(
        "google-primary",
        _credential(),
        now_ms=NOW_MS + 1,
    )
    assert replay == first
    with pytest.raises(WorkspaceAliasV1Conflict, match="different immutable"):
        catalog.register(
            "google-primary",
            _credential(scopes=("calendar.readonly",)),
            now_ms=NOW_MS + 2,
        )


def test_revocation_is_persistent_idempotent_and_cannot_resurrect(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    catalog.register("google-primary", _credential(), now_ms=NOW_MS)
    revoked = catalog.revoke(
        kind="credential",
        alias_name="google-primary",
        now_ms=NOW_MS + 10,
    )
    replay = catalog.revoke(
        kind="credential",
        alias_name="google-primary",
        now_ms=NOW_MS + 20,
    )
    assert revoked.status == "revoked"
    assert revoked.revoked_at_ms == NOW_MS + 10
    assert replay == revoked
    with pytest.raises(WorkspaceAliasV1Denied, match="revoked or expired"):
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS + 30,
        )
    assert (
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS + 30,
            include_revoked=True,
        )
        == revoked
    )
    with pytest.raises(WorkspaceAliasV1Conflict, match="cannot be resurrected"):
        catalog.register(
            "google-primary",
            _credential(),
            now_ms=NOW_MS + 40,
        )


def test_credential_revoke_deadline_denies_locator_without_mutation(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    catalog.register(
        "google-primary",
        _credential(rotate_after_ms=None, revoke_after_ms=NOW_MS + 5),
        now_ms=NOW_MS,
    )
    assert catalog.get(
        kind="credential",
        alias_name="google-primary",
        now_ms=NOW_MS + 4,
    ).status == "active"
    with pytest.raises(WorkspaceAliasV1Denied, match="revoked or expired"):
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS + 5,
        )


def test_profile_alias_is_logical_and_never_accepts_profile_paths(
    fixture: Fixture,
) -> None:
    record = _catalog(fixture).register(
        "company-browser",
        _profile(),
        now_ms=NOW_MS,
    )
    assert record.kind == "profile"
    assert record.locator == (
        "onyx-profile://v1/cyryx-main/chrome/company-ops"
    )
    assert record.allowed_domains == ("cyryxlabs.com", "microsoft.com")
    _alias_id, payload = _payload(
        fixture,
        kind="profile",
        alias_name="company-browser",
    )
    descriptor = payload["descriptor"]
    assert isinstance(descriptor, dict)
    assert set(descriptor) == {
        "browser",
        "profile_id",
        "allowed_domains",
        "dedicated_workspace_profile",
    }
    assert all(
        forbidden not in json.dumps(payload).casefold()
        for forbidden in ("cookies.sqlite", "login data", "password store")
    )
    for profile_id in ("../default", "profile/default", r"profile\default"):
        with pytest.raises(WorkspaceAliasV1ContractError, match="profile_id"):
            _profile(profile_id=profile_id)


@pytest.mark.parametrize(
    "field,value",
    [
        ("account_id", "AIzaSy0123456789abcdefghijklmnop"),
        ("tenant_id", "Bearer abcdefghijklmnopqrstuvwxyz"),
        ("provider", "access-token"),
        ("scopes", ("cookie.read",)),
        ("scopes", ("password.write",)),
        ("account_id", "sk-proj-ABCDEFGHIJKLMNOP1234567890"),
    ],
)
def test_secret_like_supplied_values_are_rejected(field: str, value: object) -> None:
    with pytest.raises(WorkspaceAliasV1ContractError, match="secret-like"):
        _credential(**{field: value})


def test_artifact_alias_requires_exact_authoritative_workspace_binding(
    fixture: Fixture,
) -> None:
    spec = _artifact(fixture)
    record = _catalog(fixture).register(
        "founder-brief",
        spec,
        now_ms=NOW_MS,
    )
    assert record.kind == "artifact"
    assert record.artifact_id == spec.artifact_id
    assert record.sha256 == spec.sha256
    assert record.relative_path == spec.relative_path
    assert record.locator == (
        "onyx-artifact://v1/cyryx-main/artifact-founder-brief"
    )

    fixture.control._require_connection().execute(
        "UPDATE artifact_index SET status='revoked' WHERE artifact_id=?",
        (spec.artifact_id,),
    )
    with pytest.raises(
        WorkspaceAliasV1Denied,
        match="binding or availability drift",
    ):
        _catalog(fixture).get(
            kind="artifact",
            alias_name="founder-brief",
            now_ms=NOW_MS,
        )


def test_artifact_alias_rejects_cross_workspace_and_digest_drift(
    fixture: Fixture,
) -> None:
    other = _artifact(
        fixture,
        workspace_id="client-one",
        artifact_id="artifact-client",
    )
    with pytest.raises(WorkspaceAliasV1Denied, match="binding or availability"):
        _catalog(fixture).register(
            "client-artifact",
            other,
            now_ms=NOW_MS,
        )

    own = _artifact(
        fixture,
        artifact_id="artifact-own",
        content=b"own",
    )
    forged = ArtifactAliasSpecV1(
        artifact_id=own.artifact_id,
        sha256="0" * 64,
        relative_path=f"00/{'0' * 64}",
        media_type=own.media_type,
    )
    with pytest.raises(WorkspaceAliasV1Denied, match="binding or availability"):
        _catalog(fixture).register(
            "forged-artifact",
            forged,
            now_ms=NOW_MS,
        )


def test_workspace_and_principal_isolation_returns_zero_foreign_aliases(
    fixture: Fixture,
) -> None:
    _catalog(fixture).register(
        "google-primary",
        _credential(),
        now_ms=NOW_MS,
    )
    assert _catalog(fixture, workspace_id="client-one").list(
        now_ms=NOW_MS
    ) == ()
    assert _catalog(fixture, principal_id="operator:other").list(
        now_ms=NOW_MS
    ) == ()
    with pytest.raises(WorkspaceAliasV1Denied, match="unavailable"):
        _catalog(fixture, principal_id="operator:other").get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS,
        )


def test_tamper_duplicate_json_and_wrong_integrity_key_fail_closed(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    catalog.register("google-primary", _credential(), now_ms=NOW_MS)
    alias_id, payload = _payload(
        fixture,
        kind="credential",
        alias_name="google-primary",
    )
    payload["locator"] = "onyx-vault://v1/cyryx-main/google/forged/value"
    fixture.control._require_connection().execute(
        "UPDATE capability_descriptors SET payload_json=? WHERE capability_id=?",
        (json.dumps(payload, sort_keys=True), alias_id),
    )
    with pytest.raises(WorkspaceAliasV1Denied, match="authentication drift"):
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS,
        )

    fixture.control._require_connection().execute(
        "UPDATE capability_descriptors SET payload_json=? WHERE capability_id=?",
        ('{"schema":"x","schema":"y"}', alias_id),
    )
    with pytest.raises(WorkspaceAliasV1Denied, match="duplicate alias key"):
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS,
        )

    with pytest.raises(WorkspaceAliasV1Denied):
        _catalog(fixture, key=b"x" * 32).get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS,
        )


def test_forged_profile_descriptor_cannot_add_path_cookie_or_password_fields(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    catalog.register("company-browser", _profile(), now_ms=NOW_MS)
    alias_id, payload = _payload(
        fixture,
        kind="profile",
        alias_name="company-browser",
    )
    descriptor = payload["descriptor"]
    assert isinstance(descriptor, dict)
    descriptor["profile_path"] = r"C:\Users\owner\Chrome\User Data"
    descriptor["cookie_database"] = "Cookies"
    payload["hmac_sha256"] = aliases._payload_mac(payload, KEY)
    fixture.control._require_connection().execute(
        "UPDATE capability_descriptors SET payload_json=? WHERE capability_id=?",
        (json.dumps(payload, sort_keys=True), alias_id),
    )
    with pytest.raises(WorkspaceAliasV1Denied, match="profile alias shape drift"):
        catalog.get(
            kind="profile",
            alias_name="company-browser",
            now_ms=NOW_MS,
        )


def test_list_is_typed_bounded_and_filters_kind_and_lifecycle(
    fixture: Fixture,
) -> None:
    catalog = _catalog(fixture)
    catalog.register("google-primary", _credential(), now_ms=NOW_MS)
    catalog.register("company-browser", _profile(), now_ms=NOW_MS)
    spec = _artifact(fixture)
    catalog.register("founder-brief", spec, now_ms=NOW_MS)
    catalog.revoke(
        kind="profile",
        alias_name="company-browser",
        now_ms=NOW_MS + 1,
    )
    assert [item.kind for item in catalog.list(now_ms=NOW_MS + 2)] == [
        "artifact",
        "credential",
    ]
    assert [
        item.alias_name
        for item in catalog.list(
            now_ms=NOW_MS + 2,
            kind="profile",
            include_revoked=True,
        )
    ] == ["company-browser"]


def test_no_vault_browser_artifact_content_network_process_or_live_calls(
    fixture: Fixture,
) -> None:
    spec = _artifact(fixture)
    with (
        patch("core.credentials.get") as credential_get,
        patch("actions.browser_control.browser_control") as browser_control,
        patch("core.artifact_service.ArtifactService.read") as artifact_read,
    ):
        catalog = _catalog(fixture)
        catalog.register("google-primary", _credential(), now_ms=NOW_MS)
        catalog.register("company-browser", _profile(), now_ms=NOW_MS)
        catalog.register("founder-brief", spec, now_ms=NOW_MS)
        catalog.list(now_ms=NOW_MS)
    credential_get.assert_not_called()
    browser_control.assert_not_called()
    artifact_read.assert_not_called()

    source = (ROOT / "core/phase7_workspace_aliases_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import requests",
        "import subprocess",
        "import socket",
        "core.credentials.get",
        "browser_control(",
        "ArtifactService.read",
    ):
        assert forbidden not in source
    for live_path in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v13.pyw",
    ):
        assert aliases.FEATURE_FLAG not in (
            ROOT / live_path
        ).read_text(encoding="utf-8")


def test_catalog_binding_and_workspace_status_drift_deny(fixture: Fixture) -> None:
    catalog = _catalog(fixture)
    catalog.register("google-primary", _credential(), now_ms=NOW_MS)
    fixture.registry.set_active("cyryx-main", False)
    with pytest.raises(
        WorkspaceAliasV1Denied,
        match="active workspace attestation",
    ):
        catalog.get(
            kind="credential",
            alias_name="google-primary",
            now_ms=NOW_MS,
        )
