from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from core import phase7_approved_sources_v1 as sources
from core.control_plane import ControlPlaneStore
from core.phase7_approved_sources_v1 import (
    ApprovedSourceFeatureGateV1,
    ApprovedSourceSpecV1,
    ApprovedSourceV1Conflict,
    ApprovedSourceV1ContractError,
    ApprovedSourceV1Denied,
    SourceScoresV1,
    create_approved_source_registry_v1,
)
from core.phase7_workspace_aliases_v1 import (
    ArtifactAliasSpecV1,
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(1, 33))
NOW_MS = 1_785_000_000_000


@dataclass
class Fixture:
    control: ControlPlaneStore
    workspaces: WorkspaceRegistry
    aliases: object


@pytest.fixture
def fixture(tmp_path: Path) -> Fixture:
    with patch(
        "core.control_plane.private_control_plane_runtime_dir",
        return_value=tmp_path,
    ):
        control = ControlPlaneStore(enabled=True).initialize()
    workspaces = WorkspaceRegistry(control, enabled=True).initialize()
    workspaces.register(
        "cyryx-main",
        display_name="Cyryx Main",
        workspace_class="cyryx",
    )
    workspaces.register(
        "client-one",
        display_name="Client One",
        workspace_class="client",
    )
    aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=workspaces,
        workspace_id="cyryx-main",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert aliases is not None
    value = Fixture(control, workspaces, aliases)
    try:
        yield value
    finally:
        control.close()


def _scores(**changes: int) -> SourceScoresV1:
    values = {
        "expertise_bp": 9_000,
        "primary_evidence_bp": 10_000,
        "editorial_quality_bp": 8_500,
        "recency_bp": 9_500,
        "correction_history_bp": 8_000,
        "incentive_independence_bp": 7_000,
        "corroboration_bp": 8_000,
        "relevance_bp": 10_000,
    }
    values.update(changes)
    return SourceScoresV1(**values)


def _https_spec(**changes: object) -> ApprovedSourceSpecV1:
    values: dict[str, object] = {
        "source_kind": "company_strategy",
        "authority": "authoritative_primary",
        "rights": "owner_created",
        "sensitivity": "internal",
        "locator_kind": "https",
        "locator": "https://docs.cyryxlabs.com/strategy",
        "citation": "https://docs.cyryxlabs.com/strategy",
        "diversity_group": "cyryx-governance",
        "scores": _scores(),
        "valid_from_ms": NOW_MS - 1_000,
        "valid_until_ms": NOW_MS + 100_000,
        "fresh_until_ms": NOW_MS + 50_000,
        "artifact_alias_name": None,
    }
    values.update(changes)
    return ApprovedSourceSpecV1(**values)  # type: ignore[arg-type]


def _registry(
    fixture: Fixture,
    *,
    workspace_id: str = "cyryx-main",
    principal_id: str = "owner:pedro",
    aliases: object | None = None,
):
    alias_catalog = fixture.aliases if aliases is None else aliases
    registry = create_approved_source_registry_v1(
        gate=ApprovedSourceFeatureGateV1(True),
        registry=fixture.workspaces,
        aliases=alias_catalog,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        principal_id=principal_id,
        integrity_key=KEY,
    )
    assert registry is not None
    return registry


def _artifact_alias(fixture: Fixture):
    digest = hashlib.sha256(b"strategy artifact").hexdigest()
    fixture.control._require_connection().execute(
        "INSERT INTO artifact_index VALUES(?,?,?,?,?,?,?,?)",
        (
            "artifact-strategy",
            "cyryx-main",
            1,
            digest,
            f"{digest[:2]}/{digest}",
            "application/pdf",
            "available",
            "2026-07-23T16:00:00+00:00",
        ),
    )
    return fixture.aliases.register(  # type: ignore[union-attr]
        "strategy-artifact",
        ArtifactAliasSpecV1(
            artifact_id="artifact-strategy",
            sha256=digest,
            relative_path=f"{digest[:2]}/{digest}",
            media_type="application/pdf",
        ),
        now_ms=NOW_MS,
    )


def test_flag_is_exact_and_default_off_returns_before_entry() -> None:
    assert ApprovedSourceFeatureGateV1.from_environ({}).enabled is False
    assert (
        ApprovedSourceFeatureGateV1.from_environ(
            {sources.FEATURE_FLAG: "true"}
        ).enabled
        is True
    )
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert (
            ApprovedSourceFeatureGateV1.from_environ(
                {sources.FEATURE_FLAG: value}
            ).enabled
            is False
        )
    assert (
        create_approved_source_registry_v1(
            gate=ApprovedSourceFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_accepted_aliases_are_exact_entry_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources._verify_aliases_entry(ROOT)
    changed = list(sources.ALIASES_ENTRY_ROOTS)
    path, _digest = changed[0]
    changed[0] = (path, "0" * 64)
    monkeypatch.setattr(sources, "ALIASES_ENTRY_ROOTS", tuple(changed))
    with pytest.raises(ApprovedSourceV1Denied, match="evidence drift"):
        sources._verify_aliases_entry(ROOT)


def test_factory_is_sealed_and_requires_matching_alias_binding(
    fixture: Fixture,
) -> None:
    with pytest.raises(ApprovedSourceV1ContractError, match="sealed feature"):
        create_approved_source_registry_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(ApprovedSourceV1ContractError, match="complete host"):
        create_approved_source_registry_v1(
            gate=ApprovedSourceFeatureGateV1(True),
        )
    other_aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.workspaces,
        workspace_id="client-one",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert other_aliases is not None
    with pytest.raises(ApprovedSourceV1Denied, match="alias catalog binding"):
        _registry(fixture, aliases=other_aliases)


def test_https_source_is_signed_scored_and_instruction_free(
    fixture: Fixture,
) -> None:
    record = _registry(fixture).register(
        "company-strategy",
        _https_spec(),
        now_ms=NOW_MS,
    )
    assert record.status == "approved"
    assert record.workspace_id == "cyryx-main"
    assert record.principal_id == "owner:pedro"
    assert record.locator == "https://docs.cyryxlabs.com/strategy"
    assert record.source_identity_sha256 == sources.domain_material_sha256_v1(
        record.locator
    )
    assert record.credibility_bp == _scores().credibility_bp
    assert record.content_trust == "untrusted_data"
    assert record.instructions_authority is False
    row = fixture.control._require_connection().execute(
        "SELECT payload_json FROM capability_descriptors "
        "WHERE capability_id=?",
        (record.source_id,),
    ).fetchone()
    payload = json.loads(str(row[0]))
    assert len(payload["hmac_sha256"]) == 64
    assert payload["instructions_authority"] is False
    assert payload["content_trust"] == "untrusted_data"


def test_https_locator_rejects_insecure_ambiguous_or_secret_urls() -> None:
    invalid = (
        "http://docs.cyryxlabs.com/strategy",
        "https://user:pass@docs.cyryxlabs.com/strategy",
        "https://docs.cyryxlabs.com/strategy#fragment",
        "https://docs.cyryxlabs.com:8443/strategy",
        "https://DOCS.cyryxlabs.com/strategy",
        "https://docs.cyryxlabs.com/strategy?access_token=abc",
    )
    for locator in invalid:
        with pytest.raises(ApprovedSourceV1ContractError):
            _https_spec(locator=locator, citation=locator)


def test_artifact_source_reuses_accepted_alias_without_reading_bytes(
    fixture: Fixture,
) -> None:
    artifact = _artifact_alias(fixture)
    spec = _https_spec(
        locator_kind="artifact_alias",
        locator=artifact.locator,
        citation=artifact.locator,
        artifact_alias_name="strategy-artifact",
        source_kind="company_strategy",
    )
    with patch(
        "core.artifact_service.ArtifactService.read"
    ) as artifact_read:
        record = _registry(fixture).register(
            "strategy-artifact-source",
            spec,
            now_ms=NOW_MS,
        )
    artifact_read.assert_not_called()
    assert record.artifact_alias_name == "strategy-artifact"
    assert record.artifact_id == artifact.artifact_id
    assert record.artifact_sha256 == artifact.sha256
    assert record.locator == artifact.locator


def test_artifact_source_denies_alias_or_index_drift(fixture: Fixture) -> None:
    artifact = _artifact_alias(fixture)
    spec = _https_spec(
        locator_kind="artifact_alias",
        locator=artifact.locator,
        citation=artifact.locator,
        artifact_alias_name="strategy-artifact",
    )
    registry = _registry(fixture)
    registry.register(
        "strategy-artifact-source",
        spec,
        now_ms=NOW_MS,
    )
    fixture.control._require_connection().execute(
        "UPDATE artifact_index SET status='revoked' "
        "WHERE artifact_id='artifact-strategy'"
    )
    with pytest.raises(ApprovedSourceV1Denied, match="artifact binding drift"):
        registry.get(
            "strategy-artifact-source",
            now_ms=NOW_MS,
        )


def test_register_is_idempotent_immutable_and_nonresurrecting(
    fixture: Fixture,
) -> None:
    registry = _registry(fixture)
    first = registry.register(
        "company-strategy",
        _https_spec(),
        now_ms=NOW_MS,
    )
    assert (
        registry.register(
            "company-strategy",
            _https_spec(),
            now_ms=NOW_MS + 1,
        )
        == first
    )
    with pytest.raises(ApprovedSourceV1Conflict, match="different immutable"):
        registry.register(
            "company-strategy",
            _https_spec(authority="secondary"),
            now_ms=NOW_MS + 2,
        )
    revoked = registry.revoke(
        "company-strategy",
        now_ms=NOW_MS + 3,
    )
    assert revoked.status == "revoked"
    assert (
        registry.revoke("company-strategy", now_ms=NOW_MS + 4)
        == revoked
    )
    with pytest.raises(ApprovedSourceV1Conflict, match="cannot be resurrected"):
        registry.register(
            "company-strategy",
            _https_spec(),
            now_ms=NOW_MS + 5,
        )


def test_validity_freshness_and_sensitivity_filter_before_return(
    fixture: Fixture,
) -> None:
    registry = _registry(fixture)
    registry.register(
        "company-strategy",
        _https_spec(fresh_until_ms=NOW_MS + 5),
        now_ms=NOW_MS,
    )
    registry.register(
        "public-brand",
        _https_spec(
            source_kind="brand_system",
            sensitivity="public",
            locator="https://cyryxlabs.com/brand",
            citation="https://cyryxlabs.com/brand",
            diversity_group="cyryx-brand",
        ),
        now_ms=NOW_MS,
    )
    assert [item.source_name for item in registry.list(
        now_ms=NOW_MS + 4,
        allowed_sensitivities=("internal",),
    )] == ["company-strategy"]
    assert [item.source_name for item in registry.list(
        now_ms=NOW_MS + 6,
        allowed_sensitivities=("public", "internal"),
    )] == ["public-brand"]
    stale = registry.get(
        "company-strategy",
        now_ms=NOW_MS + 6,
        require_fresh=False,
    )
    assert stale.source_name == "company-strategy"
    with pytest.raises(ApprovedSourceV1Denied, match="stale"):
        registry.get("company-strategy", now_ms=NOW_MS + 6)


def test_cross_workspace_and_principal_sources_are_not_returned(
    fixture: Fixture,
) -> None:
    _registry(fixture).register(
        "company-strategy",
        _https_spec(),
        now_ms=NOW_MS,
    )
    other_aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.workspaces,
        workspace_id="client-one",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert other_aliases is not None
    assert _registry(
        fixture,
        workspace_id="client-one",
        aliases=other_aliases,
    ).list(
        now_ms=NOW_MS,
        allowed_sensitivities=("public", "internal"),
    ) == ()
    other_principal_aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=fixture.workspaces,
        workspace_id="cyryx-main",
        principal_id="operator:other",
        integrity_key=KEY,
    )
    assert other_principal_aliases is not None
    assert _registry(
        fixture,
        principal_id="operator:other",
        aliases=other_principal_aliases,
    ).list(
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
    ) == ()


def test_tamper_duplicate_json_and_wrong_key_fail_closed(
    fixture: Fixture,
) -> None:
    registry = _registry(fixture)
    record = registry.register(
        "company-strategy",
        _https_spec(),
        now_ms=NOW_MS,
    )
    connection = fixture.control._require_connection()
    payload = json.loads(
        str(
            connection.execute(
                "SELECT payload_json FROM capability_descriptors "
                "WHERE capability_id=?",
                (record.source_id,),
            ).fetchone()[0]
        )
    )
    payload["authority"] = "secondary"
    connection.execute(
        "UPDATE capability_descriptors SET payload_json=? "
        "WHERE capability_id=?",
        (json.dumps(payload, sort_keys=True), record.source_id),
    )
    with pytest.raises(ApprovedSourceV1Denied, match="authentication drift"):
        registry.get("company-strategy", now_ms=NOW_MS)
    connection.execute(
        "UPDATE capability_descriptors SET payload_json=? "
        "WHERE capability_id=?",
        ('{"schema":"x","schema":"y"}', record.source_id),
    )
    with pytest.raises(ApprovedSourceV1Denied, match="duplicate source key"):
        registry.get("company-strategy", now_ms=NOW_MS)


def test_secret_like_source_metadata_is_rejected() -> None:
    with pytest.raises(ApprovedSourceV1ContractError, match="secret-like"):
        _https_spec(
            citation=(
                "https://docs.cyryxlabs.com/strategy?"
                "key=sk-proj-ABCDEFGHIJKLMNOP1234567890"
            )
        )
    with pytest.raises(ApprovedSourceV1ContractError):
        SourceScoresV1(
            expertise_bp=True,  # type: ignore[arg-type]
            primary_evidence_bp=1,
            editorial_quality_bp=1,
            recency_bp=1,
            correction_history_bp=1,
            incentive_independence_bp=1,
            corroboration_bp=1,
            relevance_bp=1,
        )


def test_no_network_provider_process_browser_or_artifact_content_calls(
    fixture: Fixture,
) -> None:
    with patch(
        "core.artifact_service.ArtifactService.read"
    ) as artifact_read:
        registry = _registry(fixture)
        registry.register(
            "company-strategy",
            _https_spec(),
            now_ms=NOW_MS,
        )
        registry.list(
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
        )
    artifact_read.assert_not_called()
    source = (ROOT / "core/phase7_approved_sources_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import requests",
        "import subprocess",
        "import socket",
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
        assert sources.FEATURE_FLAG not in (
            ROOT / live_path
        ).read_text(encoding="utf-8")
