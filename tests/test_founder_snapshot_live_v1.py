from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import subprocess
import shutil
import tempfile
from unittest.mock import patch

import pytest

from core import domain_ledger
from core import native_vault
from core.control_plane import ControlPlaneStore
from core.domain_ledger import DomainLedgerRepository
from core.founder_snapshot_live_v1 import (
    MANIFEST_SCHEMA,
    MAX_MANIFEST_BYTES,
    FounderSnapshotLiveV1,
    FounderSnapshotV1Denied,
    FounderSnapshotV1PlatformDenied,
    _history_namespace,
)
from core import founder_snapshot_live_v1 as snapshot_module
from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.native_vault import NativeSecretVault, SecretReference
from core.phase7_approved_sources_v1 import (
    ApprovedSourceFeatureGateV1,
    ApprovedSourceSpecV1,
    SourceScoresV1,
    create_approved_source_registry_v1,
)
from core.phase7_company_graph_v1 import (
    CompanyGraphAssertionV1,
    CompanyGraphFeatureGateV1,
    GraphEvidenceBindingV1,
    create_company_graph_projector_v1,
)
from core.phase7_founder_command_v1 import (
    FounderCommandGeneratorV1,
    FounderCommandFeatureGateV1,
    create_founder_command_generator_v1,
)
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.workspaces import WorkspaceRegistry


KEY = bytes(range(1, 33))
NOW_MS = 1_785_000_000_000
LEDGER_NOW = "2026-07-01T00:00:00+00:00"
ROOT = Path(__file__).resolve().parents[1]


def _identity(workspace: str = "cyryx-main") -> GovernanceIdentityV1:
    return GovernanceIdentityV1(
        principal_id="owner-pedro",
        workspace_id=workspace,
        account_id="account-founder",
        profile_id="profile-founder",
        workspace_display="Cyryx Main",
    )


@dataclass
class SnapshotFixture:
    control: ControlPlaneStore
    sources: object
    ledger: DomainLedgerRepository
    projector: object
    generator: object
    assertion: CompanyGraphAssertionV1
    source: object
    root: Path
    vault: NativeSecretVault


@pytest.fixture
def fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SnapshotFixture:
    monkeypatch.setattr(domain_ledger, "_now", lambda: LEDGER_NOW)
    vault_state = {"value": KEY}
    monkeypatch.setattr(
        native_vault, "windows_get", lambda _reference, **_kwargs: vault_state["value"]
    )
    monkeypatch.setattr(
        native_vault,
        "windows_set",
        lambda _reference, value, **_kwargs: vault_state.__setitem__(
            "value", bytes(value)
        ),
    )
    with patch("core.control_plane.private_control_plane_runtime_dir", return_value=tmp_path):
        control = ControlPlaneStore(enabled=True).initialize()
    workspaces = WorkspaceRegistry(control, enabled=True).initialize()
    workspaces.register("cyryx-main", display_name="Cyryx Main", workspace_class="cyryx")
    aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=workspaces,
        workspace_id="cyryx-main",
        principal_id="owner-pedro",
        integrity_key=KEY,
    )
    assert aliases is not None
    sources = create_approved_source_registry_v1(
        gate=ApprovedSourceFeatureGateV1(True),
        registry=workspaces,
        aliases=aliases,
        workspace_id="cyryx-main",
        principal_id="owner-pedro",
        integrity_key=KEY,
    )
    assert sources is not None
    source = sources.register(
        "verification-report",
        ApprovedSourceSpecV1(
            source_kind="test_report",
            authority="authoritative_primary",
            rights="owner_created",
            sensitivity="internal",
            locator_kind="https",
            locator="https://evidence.cyryxlabs.com/verification-report",
            citation="https://evidence.cyryxlabs.com/verification-report",
            diversity_group="cyryx-verification",
            scores=SourceScoresV1(
                expertise_bp=9_000,
                primary_evidence_bp=10_000,
                editorial_quality_bp=8_500,
                recency_bp=9_500,
                correction_history_bp=8_000,
                incentive_independence_bp=7_000,
                corroboration_bp=8_000,
                relevance_bp=10_000,
            ),
            valid_from_ms=NOW_MS - 10_000,
            valid_until_ms=NOW_MS + 1_000_000,
            fresh_until_ms=NOW_MS + 1_000_000,
        ),
        now_ms=NOW_MS,
    )
    ledger = DomainLedgerRepository(workspaces, "cyryx-main", enabled=True).initialize()
    projector = create_company_graph_projector_v1(
        gate=CompanyGraphFeatureGateV1(True), sources=sources, ledger=ledger
    )
    assert projector is not None
    generator = create_founder_command_generator_v1(
        gate=FounderCommandFeatureGateV1(True), projector=projector
    )
    assert generator is not None
    excerpt = "Source-grounded evidence for the Onyx delivery state."
    evidence = ledger.record_evidence(
        "evidence-founder",
        "correlation-founder",
        "public_url",
        source.locator,
        excerpt,
        credibility_bp=source.credibility_bp,
        freshness="current",
        validity_seconds=10_000_000,
        access_license_note=source.access_license_note,
    )
    claim_id = domain_ledger._entity_id("claim", ledger.workspace_id, "claim-founder")
    assertion = CompanyGraphAssertionV1(
        claim_id=claim_id,
        semantic="current_status",
        project_id="onyx",
        project_name="Onyx",
        subject_id="founder-snapshot",
        subject_name="Founder Snapshot",
        owner="Pedro",
        status="in_progress",
        blockers=(),
        next_milestone="Generate a verified local Founder Snapshot.",
        definition_of_done="The cited provider-free brief is persisted.",
        last_verified_ms=NOW_MS,
        evidence=(GraphEvidenceBindingV1(evidence.evidence_id, source.source_name, excerpt),),
    )
    claim = ledger.record_claim(
        "claim-founder",
        "correlation-founder",
        assertion.canonical_statement(),
        (evidence.evidence_id,),
        claim_kind="fact",
        confidence_bp=9_000,
        verification_status="supported",
        validity_seconds=10_000_000,
    )
    assert claim.claim_id == assertion.claim_id
    vault = NativeSecretVault(
        SecretReference("CyryxLabs.Onyx.FounderSnapshot", "receipt-key", "Founder key"),
        system="Windows",
    )
    parent = Path(tempfile.mkdtemp(prefix="fs-", dir=ROOT.parent))
    root = parent / "snapshots"
    root.mkdir()
    value = SnapshotFixture(
        control, sources, ledger, projector, generator, assertion, source, root, vault
    )
    try:
        yield value
    finally:
        control.close()
        shutil.rmtree(parent, ignore_errors=True)


def _snapshot(
    fixture: SnapshotFixture,
    *,
    identity: GovernanceIdentityV1 | None = None,
    fault_hook: object | None = None,
) -> FounderSnapshotLiveV1:
    return FounderSnapshotLiveV1(
        identity=identity or _identity(),
        root=fixture.root,
        sources=fixture.sources,  # type: ignore[arg-type]
        projector=fixture.projector,  # type: ignore[arg-type]
        generator=fixture.generator,  # type: ignore[arg-type]
        vault=fixture.vault,
        enabled=True,
        fault_hook=fault_hook,  # type: ignore[arg-type]
    )


def _manifest(fixture: SnapshotFixture, cadence: str, now_ms: int) -> dict[str, object]:
    return {
        "schema": MANIFEST_SCHEMA,
        "cadence": cadence,
        "workspace_id": "cyryx-main",
        "principal_id": "owner-pedro",
        "governance_identity": asdict(_identity()),
        "identity_sha256": snapshot_module._identity_digest(_identity()),
        "generated_at_ms": now_ms,
        "allowed_sensitivities": ["internal"],
        "sources": [
            {
                "source_name": fixture.source.source_name,  # type: ignore[attr-defined]
                "source_id": fixture.source.source_id,  # type: ignore[attr-defined]
                "source_identity_sha256": fixture.source.source_identity_sha256,  # type: ignore[attr-defined]
                "citation": fixture.source.citation,  # type: ignore[attr-defined]
            }
        ],
        "assertions": [asdict(fixture.assertion)],
    }


def test_import_and_default_off_is_inert(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    snapshot = FounderSnapshotLiveV1(identity=_identity(), root=marker)
    assert snapshot.enabled is False
    assert not marker.exists()
    with pytest.raises(FounderSnapshotV1Denied, match="disabled"):
        snapshot.generate("manifest.json")


def test_active_non_windows_is_typed_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(snapshot_module, "_runtime_platform", lambda: "posix")
    with pytest.raises(FounderSnapshotV1PlatformDenied, match="windows_required"):
        FounderSnapshotLiveV1(identity=_identity(), root=tmp_path, enabled=True)


def test_active_non_windows_accepts_only_explicit_trusted_boundary_factory(
    fixture: SnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(snapshot_module, "_runtime_platform", lambda: "posix")
    observed: list[tuple[Path, bool]] = []

    class Boundary:
        path = fixture.root

        def session(self):
            raise AssertionError("constructor must not open a session")

        def close(self) -> None:
            observed.append((self.path, False))

    def factory(*, root: Path, enabled: bool) -> Boundary:
        observed.append((root, enabled))
        return Boundary()

    snapshot = FounderSnapshotLiveV1(
        identity=_identity(),
        root=fixture.root,
        sources=fixture.sources,  # type: ignore[arg-type]
        projector=fixture.projector,  # type: ignore[arg-type]
        generator=fixture.generator,  # type: ignore[arg-type]
        vault=fixture.vault,
        enabled=True,
        trusted_directory_factory=factory,
    )
    assert observed == [(fixture.root, True)]
    snapshot.close()
    assert observed == [(fixture.root, True), (fixture.root, False)]


@pytest.mark.parametrize("cadence", ["daily", "weekly"])
def test_daily_and_weekly_happy_path_are_cited(
    fixture: SnapshotFixture, cadence: str
) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest(f"inbox/{cadence}.json", _manifest(fixture, cadence, NOW_MS))
    result = snapshot.generate(f"inbox/{cadence}.json")
    assert result.cadence == cadence
    assert result.history_sequence == 1
    assert result.brief.delta.baseline is True
    assert all(item.citations for item in result.brief.items)
    snapshot.close()


def test_previous_delta_survives_restart(fixture: SnapshotFixture) -> None:
    first = _snapshot(fixture)
    first.publish_manifest("inbox/one.json", _manifest(fixture, "daily", NOW_MS))
    original = first.generate("inbox/one.json")
    first.close()
    second = _snapshot(fixture)
    second.publish_manifest("inbox/two.json", _manifest(fixture, "daily", NOW_MS + 1))
    current = second.generate("inbox/two.json")
    assert current.history_sequence == 2
    assert current.brief.delta.baseline is False
    assert current.brief.delta.previous_brief_sha256 == original.brief.brief_sha256
    second.close()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "account-other"),
        ("profile_id", "profile-other"),
        ("workspace_display", "Other Workspace"),
    ],
)
def test_full_governance_identity_state_mismatch_is_denied(
    fixture: SnapshotFixture, field: str, value: str
) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest("inbox/one.json", _manifest(fixture, "daily", NOW_MS))
    snapshot.generate("inbox/one.json")
    snapshot.close()
    identity_values = asdict(_identity())
    identity_values[field] = value
    changed = GovernanceIdentityV1(**identity_values)
    with pytest.raises(FounderSnapshotV1Denied, match="vault state denied"):
        _snapshot(fixture, identity=changed)


def test_manifest_full_governance_identity_mismatch_is_denied(
    fixture: SnapshotFixture,
) -> None:
    snapshot = _snapshot(fixture)
    manifest = _manifest(fixture, "daily", NOW_MS)
    altered = dict(manifest["governance_identity"])  # type: ignore[arg-type]
    altered["profile_id"] = "profile-other"
    manifest["governance_identity"] = altered
    snapshot.publish_manifest("inbox/identity.json", manifest)
    with pytest.raises(FounderSnapshotV1Denied, match="identity"):
        snapshot.generate("inbox/identity.json")
    snapshot.close()


@pytest.mark.parametrize("order", [("daily", "weekly"), ("weekly", "daily")])
def test_two_live_instances_merge_daily_and_weekly_heads(
    fixture: SnapshotFixture, order: tuple[str, str]
) -> None:
    daily = _snapshot(fixture)
    weekly = _snapshot(fixture)
    daily.publish_manifest("inbox/daily.json", _manifest(fixture, "daily", NOW_MS))
    weekly.publish_manifest("inbox/weekly.json", _manifest(fixture, "weekly", NOW_MS))
    instances = {
        "daily": (daily, "inbox/daily.json"),
        "weekly": (weekly, "inbox/weekly.json"),
    }
    for cadence in order:
        instance, path = instances[cadence]
        assert instance.generate(path).history_sequence == 1
    daily.close()
    weekly.close()
    restarted = _snapshot(fixture)
    assert set(restarted._heads) == {"daily", "weekly"}
    assert restarted._heads["daily"]["sequence"] == 1
    assert restarted._heads["weekly"]["sequence"] == 1
    restarted.close()


def test_threaded_daily_weekly_stress_preserves_both_heads(
    fixture: SnapshotFixture,
) -> None:
    for offset in range(1, 5):
        daily = _snapshot(fixture)
        weekly = _snapshot(fixture)
        daily_path = f"inbox/daily-{offset}.json"
        weekly_path = f"inbox/weekly-{offset}.json"
        now_ms = NOW_MS + offset
        daily.publish_manifest(daily_path, _manifest(fixture, "daily", now_ms))
        weekly.publish_manifest(weekly_path, _manifest(fixture, "weekly", now_ms))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = tuple(
                pool.map(
                    lambda item: item[0].generate(item[1]).history_sequence,
                    ((daily, daily_path), (weekly, weekly_path)),
                )
            )
        assert results == (offset, offset)
        daily.close()
        weekly.close()
    restarted = _snapshot(fixture)
    assert restarted._heads["daily"]["sequence"] == 4
    assert restarted._heads["weekly"]["sequence"] == 4
    restarted.close()


def test_post_publish_crash_keeps_pending_and_reconciles_without_reexecution(
    fixture: SnapshotFixture,
) -> None:
    def fail_after_publish(point: str) -> None:
        if point == "post_publish":
            raise RuntimeError("simulated_post_publish_crash")

    crashing = _snapshot(fixture, fault_hook=fail_after_publish)
    crashing.publish_manifest("inbox/crash.json", _manifest(fixture, "daily", NOW_MS))
    with pytest.raises(RuntimeError, match="simulated_post_publish_crash"):
        crashing.generate("inbox/crash.json")
    assert crashing._heads["daily"]["pending_sequence"] == 1
    crashing.close()
    restarted = _snapshot(fixture)
    with patch.object(
        FounderCommandGeneratorV1,
        "generate",
        side_effect=AssertionError("must_not_reexecute"),
    ):
        with pytest.raises(FounderSnapshotV1Denied, match="history conflict"):
            restarted.generate("inbox/crash.json")
    assert restarted._heads["daily"]["sequence"] == 1
    assert restarted._heads["daily"]["pending_sequence"] is None
    restarted.close()


def test_post_publish_tamper_never_clears_pending_anchor(
    fixture: SnapshotFixture,
) -> None:
    crashing = _snapshot(
        fixture,
        fault_hook=lambda point: (_ for _ in ()).throw(RuntimeError(point))
        if point == "post_publish"
        else None,
    )
    crashing.publish_manifest("inbox/crash.json", _manifest(fixture, "daily", NOW_MS))
    with pytest.raises(RuntimeError, match="post_publish"):
        crashing.generate("inbox/crash.json")
    crashing.close()
    history = (
        fixture.root
        / _history_namespace(_identity(), "daily")
        / "00000001.json"
    )
    entry = json.loads(history.read_text(encoding="utf-8"))
    entry["previous_entry_sha256"] = "0" * 64
    history.write_text(
        json.dumps(entry, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    restarted = _snapshot(fixture)
    with pytest.raises(FounderSnapshotV1Denied, match="authentication"):
        restarted.generate("inbox/crash.json")
    assert restarted._heads["daily"]["pending_sequence"] == 1
    restarted.close()


def test_non_monotonic_cadence_conflict_is_denied(fixture: SnapshotFixture) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest("inbox/one.json", _manifest(fixture, "daily", NOW_MS))
    snapshot.generate("inbox/one.json")
    snapshot.publish_manifest("inbox/two.json", _manifest(fixture, "daily", NOW_MS))
    with pytest.raises(FounderSnapshotV1Denied, match="history conflict"):
        snapshot.generate("inbox/two.json")
    snapshot.close()


def test_history_tamper_and_replacement_fail_closed(fixture: SnapshotFixture) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest("inbox/one.json", _manifest(fixture, "daily", NOW_MS))
    snapshot.generate("inbox/one.json")
    snapshot.close()
    history = (
        fixture.root
        / _history_namespace(_identity(), "daily")
        / "00000001.json"
    )
    assert history.is_file()
    entry = json.loads(history.read_text(encoding="utf-8"))
    entry["brief_sha256"] = "0" * 64
    history.write_text(
        json.dumps(entry, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest("inbox/two.json", _manifest(fixture, "daily", NOW_MS + 1))
    with pytest.raises(FounderSnapshotV1Denied, match="authentication"):
        snapshot.generate("inbox/two.json")
    snapshot.close()


def test_history_truncation_is_detected_by_native_vault_head(
    fixture: SnapshotFixture,
) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest("inbox/one.json", _manifest(fixture, "daily", NOW_MS))
    snapshot.generate("inbox/one.json")
    snapshot.close()
    history = (
        fixture.root
        / _history_namespace(_identity(), "daily")
        / "00000001.json"
    )
    history.unlink()
    restarted = _snapshot(fixture)
    restarted.publish_manifest(
        "inbox/two.json", _manifest(fixture, "daily", NOW_MS + 1)
    )
    with pytest.raises(FounderSnapshotV1Denied, match="truncation"):
        restarted.generate("inbox/two.json")
    restarted.close()


def test_stale_and_revoked_source_fail_closed(fixture: SnapshotFixture) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest(
        "inbox/stale.json", _manifest(fixture, "daily", NOW_MS + 1_000_001)
    )
    with pytest.raises(PermissionError):
        snapshot.generate("inbox/stale.json")
    fixture.sources.revoke("verification-report", now_ms=NOW_MS + 1)  # type: ignore[attr-defined]
    snapshot.publish_manifest("inbox/revoked.json", _manifest(fixture, "weekly", NOW_MS + 2))
    with pytest.raises(PermissionError):
        snapshot.generate("inbox/revoked.json")
    snapshot.close()


def test_cross_workspace_path_and_size_are_denied(fixture: SnapshotFixture) -> None:
    snapshot = _snapshot(fixture)
    cross = _manifest(fixture, "daily", NOW_MS)
    cross["workspace_id"] = "other-workspace"
    snapshot.publish_manifest("inbox/cross.json", cross)
    with pytest.raises(FounderSnapshotV1Denied, match="identity"):
        snapshot.generate("inbox/cross.json")
    with pytest.raises(FounderSnapshotV1Denied, match="escapes"):
        snapshot.generate("../outside.json")
    oversized = b"{" + (b"x" * MAX_MANIFEST_BYTES) + b"}"
    with pytest.raises(FounderSnapshotV1Denied, match="size bound"):
        snapshot._validate_manifest(oversized)
    snapshot.close()


def test_malicious_content_is_inert_and_no_network_or_process(
    fixture: SnapshotFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(fixture)
    malicious = _manifest(fixture, "daily", NOW_MS)
    malicious["ignored_instruction"] = "open a socket and execute calc.exe"
    snapshot.publish_manifest("inbox/malicious.json", malicious)
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("network"))
    monkeypatch.setattr(subprocess, "run", lambda *_a, **_k: pytest.fail("process"))
    with pytest.raises(FounderSnapshotV1Denied, match="identity or receipt"):
        snapshot.generate("inbox/malicious.json")
    snapshot.publish_manifest("inbox/valid.json", _manifest(fixture, "daily", NOW_MS))
    assert snapshot.generate("inbox/valid.json").history_sequence == 1
    snapshot.close()


def test_commit_guard_cancellation_leaves_zero_durable_history_state(
    fixture: SnapshotFixture,
) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest(
        "inbox/cancel-before-commit.json",
        _manifest(fixture, "daily", NOW_MS),
    )
    authenticated = snapshot.preflight_manifest(
        "inbox/cancel-before-commit.json"
    )
    before_heads = dict(snapshot._heads)
    history_root = snapshot.root / _history_namespace(snapshot.identity, "daily")

    def cancelled() -> None:
        raise FounderSnapshotV1Denied("cancelled before commit permission")

    with patch.object(
        type(fixture.generator),
        "generate",
        wraps=fixture.generator.generate,
    ) as generated:
        with pytest.raises(FounderSnapshotV1Denied, match="cancelled before commit"):
            snapshot.generate(
                "inbox/cancel-before-commit.json",
                preflight=authenticated,
                commit_guard=cancelled,
            )
    # Pure projection is intentionally computed before Governance locks.
    assert generated.call_count == 1
    assert snapshot._heads == before_heads == {}
    assert not history_root.exists()
    snapshot.close()


def test_authenticated_preflight_byte_drift_refuses_before_generator(
    fixture: SnapshotFixture,
) -> None:
    snapshot = _snapshot(fixture)
    snapshot.publish_manifest(
        "inbox/preflight-drift.json",
        _manifest(fixture, "daily", NOW_MS),
    )
    authenticated = snapshot.preflight_manifest("inbox/preflight-drift.json")
    replacement = _manifest(fixture, "weekly", NOW_MS + 1)
    (snapshot.root / "inbox/preflight-drift.json").write_bytes(
        snapshot.seal_manifest(replacement)
    )
    with patch.object(
        type(fixture.generator),
        "generate",
        wraps=fixture.generator.generate,
    ) as generated:
        with pytest.raises(FounderSnapshotV1Denied, match="changed after"):
            snapshot.generate(
                "inbox/preflight-drift.json",
                preflight=authenticated,
            )
    assert generated.call_count == 0
    assert snapshot._heads == {}
    snapshot.close()
