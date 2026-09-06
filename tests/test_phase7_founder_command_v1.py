from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from unittest.mock import patch

import pytest

from core import domain_ledger
from core import phase7_founder_command_v1 as founder
from core.control_plane import ControlPlaneStore
from core.domain_ledger import DomainLedgerRepository
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
    FounderActionCandidateV1,
    FounderCommandBriefV1,
    FounderCommandFeatureGateV1,
    FounderCommandV1ContractError,
    FounderCommandV1Denied,
    create_founder_command_generator_v1,
)
from core.phase7_workspace_aliases_v1 import (
    WorkspaceAliasFeatureGateV1,
    create_workspace_alias_catalog_v1,
)
from core.workspaces import WorkspaceRegistry


ROOT = Path(__file__).resolve().parents[1]
KEY = bytes(range(1, 33))
NOW_MS = 1_785_000_000_000
LEDGER_NOW = "2026-07-01T00:00:00+00:00"


@dataclass
class FounderFixture:
    control: ControlPlaneStore
    workspaces: WorkspaceRegistry
    sources: object
    ledger: DomainLedgerRepository
    projector: object
    generator: object


@pytest.fixture
def fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> FounderFixture:
    monkeypatch.setattr(domain_ledger, "_now", lambda: LEDGER_NOW)
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
    aliases = create_workspace_alias_catalog_v1(
        gate=WorkspaceAliasFeatureGateV1(True),
        registry=workspaces,
        workspace_id="cyryx-main",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert aliases is not None
    sources = create_approved_source_registry_v1(
        gate=ApprovedSourceFeatureGateV1(True),
        registry=workspaces,
        aliases=aliases,
        workspace_id="cyryx-main",
        principal_id="owner:pedro",
        integrity_key=KEY,
    )
    assert sources is not None
    sources.register(
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
    ledger = DomainLedgerRepository(
        workspaces,
        "cyryx-main",
        enabled=True,
    ).initialize()
    projector = create_company_graph_projector_v1(
        gate=CompanyGraphFeatureGateV1(True),
        sources=sources,
        ledger=ledger,
    )
    assert projector is not None
    generator = create_founder_command_generator_v1(
        gate=FounderCommandFeatureGateV1(True),
        projector=projector,
    )
    assert generator is not None
    value = FounderFixture(
        control=control,
        workspaces=workspaces,
        sources=sources,
        ledger=ledger,
        projector=projector,
        generator=generator,
    )
    try:
        yield value
    finally:
        control.close()


def _claim_kind(semantic: str) -> str:
    if semantic == "proposed_decision":
        return "recommendation"
    if semantic in {"dependency", "hypothesis", "risk"}:
        return "inference"
    return "fact"


def _assertion(
    fixture: FounderFixture,
    suffix: str,
    *,
    semantic: str = "current_status",
    status: str = "in_progress",
    project_id: str = "onyx",
    project_name: str = "Onyx",
    subject_id: str | None = None,
    subject_name: str | None = None,
    blockers: tuple[str, ...] = (),
    last_verified_ms: int = NOW_MS,
    verification_status: str = "supported",
    confidence_bp: int = 9_000,
    contradiction_claim_ids: tuple[str, ...] = (),
    supersedes_claim_id: str | None = None,
) -> CompanyGraphAssertionV1:
    source = fixture.sources.get(  # type: ignore[union-attr]
        "verification-report",
        now_ms=NOW_MS,
    )
    excerpt = f"Source-grounded evidence for {suffix}."
    evidence = fixture.ledger.record_evidence(
        f"evidence-{suffix}",
        f"correlation-{suffix}",
        "public_url",
        source.locator,
        excerpt,
        credibility_bp=source.credibility_bp,
        freshness="current",
        validity_seconds=10_000_000,
        access_license_note=source.access_license_note,
    )
    claim_key = f"claim-{suffix}"
    claim_id = domain_ledger._entity_id(
        "claim",
        fixture.ledger.workspace_id,
        claim_key,
    )
    assertion = CompanyGraphAssertionV1(
        claim_id=claim_id,
        semantic=semantic,
        project_id=project_id,
        project_name=project_name,
        subject_id=subject_id or f"subject-{suffix}",
        subject_name=subject_name or f"Subject {suffix}",
        owner="Pedro",
        status=status,
        blockers=blockers,
        next_milestone="Reach the next source-verified milestone.",
        definition_of_done="The stated result has independent evidence.",
        last_verified_ms=last_verified_ms,
        evidence=(
            GraphEvidenceBindingV1(
                evidence.evidence_id,
                "verification-report",
                excerpt,
            ),
        ),
    )
    claim = fixture.ledger.record_claim(
        claim_key,
        f"correlation-{suffix}",
        assertion.canonical_statement(),
        (evidence.evidence_id,),
        claim_kind=_claim_kind(semantic),
        confidence_bp=confidence_bp,
        verification_status=verification_status,
        validity_seconds=10_000_000,
        contradiction_claim_ids=contradiction_claim_ids,
        supersedes_claim_id=supersedes_claim_id,
    )
    assert claim.claim_id == assertion.claim_id
    return assertion


def _candidate(
    action_id: str,
    claim_ids: tuple[str, ...],
    *,
    kind: str = "operating_action",
    goal: str = "product_delivery",
    impact_bp: int = 8_000,
    urgency_bp: int = 8_000,
    effort_bp: int = 3_000,
    downside_bp: int = 2_000,
    known_context: str | None = "The linked graph claim is supported.",
    inference: str | None = None,
) -> FounderActionCandidateV1:
    return FounderActionCandidateV1(
        action_id=action_id,
        kind=kind,
        goal=goal,
        title=f"Action {action_id}",
        claim_ids=tuple(sorted(claim_ids)),
        impact_bp=impact_bp,
        urgency_bp=urgency_bp,
        effort_bp=effort_bp,
        downside_bp=downside_bp,
        known_context=known_context,
        inference=inference,
        unknowns=("The final external outcome remains unknown.",),
        alternative_explanations=(
            "The observed signal may change after new evidence.",
        ),
        recommended_action="Run the bounded verification step.",
        verification_method="Observe the named state after the step.",
        completion_evidence="A cited current-status claim records the result.",
        downside="Time may be spent without producing the expected result.",
    )


def _db_sha256(control: ControlPlaneStore) -> str:
    dump = "\n".join(control._require_connection().iterdump())
    return hashlib.sha256(dump.encode("utf-8")).hexdigest()


def test_feature_is_exact_default_off_and_entry_is_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert FounderCommandFeatureGateV1.from_environ({}).enabled is False
    assert (
        FounderCommandFeatureGateV1.from_environ(
            {founder.FEATURE_FLAG: "true"}
        ).enabled
        is True
    )
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert (
            FounderCommandFeatureGateV1.from_environ(
                {founder.FEATURE_FLAG: value}
            ).enabled
            is False
        )
    assert (
        create_founder_command_generator_v1(
            gate=FounderCommandFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )
    founder._verify_graph_entry(ROOT)
    changed = list(founder.ACCEPTED_GRAPH_ENTRY_ROOTS)
    path, _digest = changed[0]
    changed[0] = (path, "0" * 64)
    monkeypatch.setattr(
        founder,
        "ACCEPTED_GRAPH_ENTRY_ROOTS",
        tuple(changed),
    )
    with pytest.raises(FounderCommandV1Denied, match="drift"):
        founder._verify_graph_entry(ROOT)


def test_daily_brief_is_cited_deterministic_and_read_only(
    fixture: FounderFixture,
) -> None:
    status = _assertion(fixture, "status")
    risk = _assertion(
        fixture,
        "risk",
        semantic="risk",
        status="blocked",
        blockers=("A verified mitigation is pending.",),
    )
    assertions = tuple(sorted((status, risk), key=lambda item: item.claim_id))
    before = _db_sha256(fixture.control)
    first = fixture.generator.generate(  # type: ignore[union-attr]
        assertions,
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    second = fixture.generator.generate(  # type: ignore[union-attr]
        assertions,
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    assert type(first) is FounderCommandBriefV1
    assert first == second
    assert before == _db_sha256(fixture.control)
    assert first.read_only is True
    assert first.content_trust == "untrusted_data"
    assert len(first.brief_sha256) == 64
    assert first.graph_sha256
    assert first.known_claim_ids == (status.claim_id,)
    assert first.inferred_claim_ids == (risk.claim_id,)
    assert first.unknown_claim_ids == ()
    assert first.critical_blocker_claim_ids == (risk.claim_id,)
    assert first.risk_register_claim_ids == (risk.claim_id,)
    assert all(item.citations for item in first.items)
    assert any(
        "revenue" in message.casefold()
        for message in first.abstentions
    )


def test_freshness_classifies_current_aging_and_stale(
    fixture: FounderFixture,
) -> None:
    current = _assertion(
        fixture,
        "fresh-current",
        last_verified_ms=NOW_MS - 12 * 60 * 60 * 1_000,
    )
    aging = _assertion(
        fixture,
        "fresh-aging",
        last_verified_ms=NOW_MS - 2 * founder.DAY_MS,
    )
    stale = _assertion(
        fixture,
        "fresh-stale",
        last_verified_ms=NOW_MS - 4 * founder.DAY_MS,
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        tuple(sorted((current, aging, stale), key=lambda item: item.claim_id)),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    states = {item.claim_id: item.state for item in brief.freshness}
    assert states == {
        current.claim_id: "current",
        aging.claim_id: "aging",
        stale.claim_id: "stale",
    }
    assert brief.portfolio[0].stale_claim_ids == (stale.claim_id,)


def test_undeclared_incompatible_status_is_detected(
    fixture: FounderFixture,
) -> None:
    left = _assertion(
        fixture,
        "conflict-left",
        subject_id="runtime-status",
        subject_name="Runtime status",
        status="implemented",
    )
    right = _assertion(
        fixture,
        "conflict-right",
        subject_id="runtime-status",
        subject_name="Runtime status",
        status="blocked",
        blockers=("A regression remains.",),
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        tuple(sorted((left, right), key=lambda item: item.claim_id)),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    assert len(brief.contradictions) == 1
    finding = brief.contradictions[0]
    assert finding.kind == "potential_undeclared"
    assert finding.severity == "high"
    assert finding.claim_ids == tuple(
        sorted((left.claim_id, right.claim_id))
    )
    assert finding.citations == (
        "https://evidence.cyryxlabs.com/verification-report",
    )


def test_declared_contradiction_is_preserved_without_duplicate(
    fixture: FounderFixture,
) -> None:
    left = _assertion(
        fixture,
        "declared-left",
        subject_id="declared-status",
        subject_name="Declared status",
        status="verified_complete",
    )
    right = _assertion(
        fixture,
        "declared-right",
        subject_id="declared-status",
        subject_name="Declared status",
        status="in_progress",
        contradiction_claim_ids=(left.claim_id,),
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        tuple(sorted((left, right), key=lambda item: item.claim_id)),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    assert len(brief.contradictions) == 1
    assert brief.contradictions[0].kind == "declared"
    assert brief.contradictions[0].severity == "critical"


def test_portfolio_blocker_dependency_decision_and_risk_views(
    fixture: FounderFixture,
) -> None:
    dependency = _assertion(
        fixture,
        "dependency",
        semantic="dependency",
        status="blocked",
        blockers=("A vendor dependency is pending.",),
    )
    decision = _assertion(
        fixture,
        "decision",
        semantic="proposed_decision",
        status="proposed",
        verification_status="unverified",
    )
    risk = _assertion(
        fixture,
        "portfolio-risk",
        semantic="risk",
        status="proposed",
        verification_status="unverified",
    )
    assertions = tuple(
        sorted((dependency, decision, risk), key=lambda item: item.claim_id)
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        assertions,
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="weekly",
    )
    assert brief.cadence == "weekly"
    assert brief.dependency_claim_ids == (dependency.claim_id,)
    assert brief.decision_queue_claim_ids == (decision.claim_id,)
    assert brief.risk_register_claim_ids == (risk.claim_id,)
    assert brief.critical_blocker_claim_ids == (dependency.claim_id,)
    project = brief.portfolio[0]
    assert project.dependency_claim_ids == (dependency.claim_id,)
    assert project.decision_claim_ids == (decision.claim_id,)
    assert project.risk_claim_ids == (risk.claim_id,)


def test_revenue_queue_and_top_three_are_evidence_linked_and_ranked(
    fixture: FounderFixture,
) -> None:
    status = _assertion(fixture, "action-status")
    actions = tuple(
        sorted(
            (
                _candidate(
                    "revenue-first",
                    (status.claim_id,),
                    kind="revenue_opportunity",
                    goal="near_term_revenue",
                    impact_bp=9_500,
                    urgency_bp=9_500,
                ),
                _candidate(
                    "delivery-second",
                    (status.claim_id,),
                    impact_bp=8_000,
                    urgency_bp=8_000,
                ),
                _candidate(
                    "risk-third",
                    (status.claim_id,),
                    goal="risk_reduction",
                    impact_bp=7_000,
                    urgency_bp=7_000,
                ),
                _candidate(
                    "learning-fourth",
                    (status.claim_id,),
                    goal="customer_learning",
                    impact_bp=3_000,
                    urgency_bp=3_000,
                ),
            ),
            key=lambda item: item.action_id,
        )
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        (status,),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
        action_candidates=actions,
    )
    assert tuple(
        item.action_id for item in brief.recommended_top_actions
    ) == ("revenue-first", "delivery-second", "risk-third")
    assert tuple(
        item.action_id for item in brief.revenue_opportunities
    ) == ("revenue-first",)
    assert all(
        item.citations
        == ("https://evidence.cyryxlabs.com/verification-report",)
        for item in brief.recommended_top_actions
    )
    revenue = brief.revenue_opportunities[0]
    assert revenue.goal == "near_term_revenue"
    assert revenue.unknowns
    assert revenue.alternative_explanations
    assert revenue.verification_method
    assert revenue.completion_evidence
    assert revenue.downside
    assert not any(
        "No source-grounded revenue opportunity" in message
        for message in brief.abstentions
    )


def test_inference_requires_inferred_graph_evidence(
    fixture: FounderFixture,
) -> None:
    known = _assertion(fixture, "known-action")
    invalid = _candidate(
        "invalid-inference",
        (known.claim_id,),
        known_context=None,
        inference="The supported fact may imply a future outcome.",
    )
    with pytest.raises(FounderCommandV1Denied, match="inference"):
        fixture.generator.generate(  # type: ignore[union-attr]
            (known,),
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
            cadence="daily",
            action_candidates=(invalid,),
        )

    hypothesis = _assertion(
        fixture,
        "hypothesis-action",
        semantic="hypothesis",
        status="proposed",
        verification_status="unverified",
    )
    valid = _candidate(
        "valid-inference",
        (hypothesis.claim_id,),
        known_context=None,
        inference="The hypothesis may support a bounded experiment.",
    )
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        (hypothesis,),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
        action_candidates=(valid,),
    )
    assert brief.recommended_top_actions[0].evidence_class == "inferred"


def test_action_with_missing_graph_evidence_is_denied(
    fixture: FounderFixture,
) -> None:
    status = _assertion(fixture, "missing-evidence")
    missing = replace(
        _candidate("missing-claim", (status.claim_id,)),
        claim_ids=("m2a-claim-" + "f" * 64,),
    )
    with pytest.raises(FounderCommandV1Denied, match="absent"):
        fixture.generator.generate(  # type: ignore[union-attr]
            (status,),
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
            cadence="daily",
            action_candidates=(missing,),
        )


def test_what_changed_delta_is_exact_and_previous_brief_is_authenticated(
    fixture: FounderFixture,
) -> None:
    first_status = _assertion(fixture, "delta-first")
    baseline = fixture.generator.generate(  # type: ignore[union-attr]
        (first_status,),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    assert baseline.delta.baseline is True
    assert baseline.delta.added_claim_ids == ()

    second_status = _assertion(fixture, "delta-second")
    assertions = tuple(
        sorted((first_status, second_status), key=lambda item: item.claim_id)
    )
    updated = fixture.generator.generate(  # type: ignore[union-attr]
        assertions,
        now_ms=NOW_MS + 1_000,
        allowed_sensitivities=("internal",),
        cadence="daily",
        previous_brief=baseline,
    )
    assert updated.delta.baseline is False
    assert updated.delta.previous_brief_sha256 == baseline.brief_sha256
    assert updated.delta.added_claim_ids == (second_status.claim_id,)
    assert updated.delta.removed_claim_ids == ()
    assert updated.delta.changed_subjects == (
        "onyx/subject-delta-second/current_status",
    )

    object.__setattr__(baseline, "brief_sha256", "0" * 64)
    with pytest.raises(FounderCommandV1Denied, match="integrity"):
        fixture.generator.generate(  # type: ignore[union-attr]
            assertions,
            now_ms=NOW_MS + 2_000,
            allowed_sensitivities=("internal",),
            cadence="daily",
            previous_brief=baseline,
        )


def test_previous_brief_scope_and_chronology_fail_closed(
    fixture: FounderFixture,
) -> None:
    status = _assertion(fixture, "chronology")
    baseline = fixture.generator.generate(  # type: ignore[union-attr]
        (status,),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    with pytest.raises(FounderCommandV1Denied, match="chronology"):
        fixture.generator.generate(  # type: ignore[union-attr]
            (status,),
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
            cadence="daily",
            previous_brief=baseline,
        )


def test_generator_invokes_no_network_process_browser_or_artifact_read(
    fixture: FounderFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = _assertion(fixture, "side-effect-free")

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("Founder Command invoked an external side effect")

    monkeypatch.setattr("socket.create_connection", forbidden)
    monkeypatch.setattr("subprocess.Popen", forbidden)
    monkeypatch.setattr("webbrowser.open", forbidden)
    monkeypatch.setattr(Path, "open", forbidden)
    brief = fixture.generator.generate(  # type: ignore[union-attr]
        (status,),
        now_ms=NOW_MS,
        allowed_sensitivities=("internal",),
        cadence="daily",
    )
    assert brief.read_only is True


def test_contracts_reject_unsorted_actions_invalid_cadence_and_secrets(
    fixture: FounderFixture,
) -> None:
    status = _assertion(fixture, "contracts")
    first = _candidate("z-action", (status.claim_id,))
    second = _candidate("a-action", (status.claim_id,))
    with pytest.raises(FounderCommandV1ContractError, match="sorted"):
        fixture.generator.generate(  # type: ignore[union-attr]
            (status,),
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
            cadence="daily",
            action_candidates=(first, second),
        )
    with pytest.raises(FounderCommandV1ContractError, match="cadence"):
        fixture.generator.generate(  # type: ignore[union-attr]
            (status,),
            now_ms=NOW_MS,
            allowed_sensitivities=("internal",),
            cadence="monthly",
        )
    with pytest.raises(FounderCommandV1ContractError, match="secret"):
        replace(
            first,
            recommended_action="api_key=abcdefghijklmnop",
        )


def test_factory_requires_exact_projector_and_policy(
    fixture: FounderFixture,
) -> None:
    with pytest.raises(FounderCommandV1ContractError, match="sealed"):
        create_founder_command_generator_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(FounderCommandV1ContractError, match="projector"):
        create_founder_command_generator_v1(
            gate=FounderCommandFeatureGateV1(True)
        )
    with pytest.raises(FounderCommandV1ContractError, match="exact"):
        create_founder_command_generator_v1(
            gate=FounderCommandFeatureGateV1(True),
            projector=fixture.projector,  # type: ignore[arg-type]
            policy=True,  # type: ignore[arg-type]
        )
