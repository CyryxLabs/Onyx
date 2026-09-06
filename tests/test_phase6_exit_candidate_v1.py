from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from core import phase6_exit_candidate_v1 as candidate


ROOT = Path(__file__).resolve().parents[1]


def _metadata(component: str) -> tuple[dict[str, object], str, str]:
    path, acceptance_id, manifest_sha256 = candidate.ACCEPTANCE_METADATA[component]
    data = candidate._strict_json(ROOT, path)
    return data, acceptance_id, manifest_sha256


def test_flag_is_exact_and_default_off() -> None:
    assert candidate.Phase6ExitFeatureGateV1.from_environ({}).enabled is False
    assert (
        candidate.Phase6ExitFeatureGateV1.from_environ(
            {candidate.FEATURE_FLAG: "true"}
        ).enabled
        is True
    )
    for value in ("1", "TRUE", "True", " true", "true ", "yes"):
        assert (
            candidate.Phase6ExitFeatureGateV1.from_environ(
                {candidate.FEATURE_FLAG: value}
            ).enabled
            is False
        )


def test_default_off_returns_before_project_or_filesystem_validation() -> None:
    missing = ROOT / "this-path-does-not-exist"
    assert (
        candidate.create_phase6_exit_candidate_v1(
            gate=candidate.Phase6ExitFeatureGateV1(False),
            project_root=missing,
        )
        is None
    )


def test_factory_requires_the_sealed_gate() -> None:
    with pytest.raises(
        candidate.Phase6ExitCandidateV1ContractError,
        match="sealed feature gate",
    ):
        candidate.create_phase6_exit_candidate_v1(gate=True)  # type: ignore[arg-type]


def test_current_e1_e5_closure_is_ready_only_for_external_gate() -> None:
    report = candidate.create_phase6_exit_candidate_v1(
        gate=candidate.Phase6ExitFeatureGateV1(True),
        project_root=ROOT,
    )
    assert report is not None
    assert report.candidate == candidate.CANDIDATE
    assert report.component_acceptances == 8
    assert report.evidence_roots == 34
    assert report.e1_e5_ready is True
    assert report.ready_for_external_gate is True
    assert report.external_e6_accepted is False
    assert report.phase6_exit is False
    assert report.phase7_unlocked is False
    assert report.runtime_authority_added is False
    assert report.live_observation_only is True
    assert report.permanent_provider_availability is False
    assert report.external_agent_authority is False
    assert report.cross_route_authority is False
    assert report.additional_provider_authority is False
    assert (
        report.network_calls,
        report.provider_calls,
        report.process_calls,
        report.live_calls,
    ) == (0, 0, 0, 0)


def test_every_evidence_root_is_unique_and_rehashes() -> None:
    observed = candidate._verify_root_hashes(ROOT)
    assert len(observed) == len(candidate.EVIDENCE_ROOTS) == 34
    assert len({root.role for root in candidate.EVIDENCE_ROOTS}) == 34
    for root in candidate.EVIDENCE_ROOTS:
        assert (
            hashlib.sha256((ROOT / root.path).read_bytes()).hexdigest() == root.sha256
        )


def test_one_tampered_evidence_byte_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = candidate.EVIDENCE_ROOTS[0].path
    original = candidate._regular_bytes

    def tampered(project: Path, relative: str) -> bytes:
        payload = original(project, relative)
        return payload + b"x" if relative == target else payload

    monkeypatch.setattr(candidate, "_regular_bytes", tampered)
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="evidence root hash drift",
    ):
        candidate._verify_root_hashes(ROOT)


def test_duplicate_json_keys_are_rejected() -> None:
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="duplicate JSON key",
    ):
        candidate._strict_json_bytes(
            b'{"decision":"accepted","decision":"rejected"}',
            "adversarial.json",
        )


def test_acceptance_decision_or_findings_drift_is_rejected() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("gemini_live")
    for key, value in (
        ("decision", "rejected"),
        ("findings", {"P0": 0, "P1": 1, "P2": 0, "P3": 0}),
    ):
        changed = copy.deepcopy(data)
        changed[key] = value
        with pytest.raises(
            candidate.Phase6ExitCandidateV1Error,
            match="acceptance contract drift",
        ):
            candidate._validate_acceptance_metadata(
                "gemini_live",
                changed,
                acceptance_id,
                manifest_sha256,
            )


def test_missing_modality_or_component_acceptance_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    incomplete = dict(candidate.ACCEPTANCE_METADATA)
    incomplete.pop("local_text")
    monkeypatch.setattr(candidate, "ACCEPTANCE_METADATA", incomplete)
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="component set is incomplete",
    ):
        candidate._verify_acceptances(ROOT)


def test_local_text_cannot_silently_retry_or_cross_route() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("local_text")
    for field in ("silent_retry", "silent_cross_routing"):
        changed = copy.deepcopy(data)
        changed["contracts"][field] = True  # type: ignore[index]
        with pytest.raises(
            candidate.Phase6ExitCandidateV1Error,
            match="local/text compatibility drift",
        ):
            candidate._validate_acceptance_metadata(
                "local_text",
                changed,
                acceptance_id,
                manifest_sha256,
            )


def test_privacy_constraint_cannot_be_replaced_by_remote_fallback() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("provider_registry")
    changed = copy.deepcopy(data)
    changed["contracts"]["sensitive_remote_fallback"] = True  # type: ignore[index]
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="provider registry privacy drift",
    ):
        candidate._validate_acceptance_metadata(
            "provider_registry",
            changed,
            acceptance_id,
            manifest_sha256,
        )


def test_research_cell_cannot_self_certify() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("research_cells")
    changed = copy.deepcopy(data)
    changed["contracts"]["research_self_certifies"] = True  # type: ignore[index]
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="research/verifier contract drift",
    ):
        candidate._validate_acceptance_metadata(
            "research_cells",
            changed,
            acceptance_id,
            manifest_sha256,
        )


def test_router_side_effect_or_live_call_is_rejected() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("unified_router")
    for key in candidate.CALL_COUNTER_KEYS:
        changed = copy.deepcopy(data)
        changed[key] = 1
        with pytest.raises(
            candidate.Phase6ExitCandidateV1Error,
            match="unified router authority drift",
        ):
            candidate._validate_acceptance_metadata(
                "unified_router",
                changed,
                acceptance_id,
                manifest_sha256,
            )


def test_external_agent_must_remain_blocked_without_authority() -> None:
    data, acceptance_id, manifest_sha256 = _metadata("external_agent")
    changed = copy.deepcopy(data)
    changed["authority_granted"] = True
    with pytest.raises(
        candidate.Phase6ExitCandidateV1Error,
        match="external agent must remain blocked",
    ):
        candidate._validate_acceptance_metadata(
            "external_agent",
            changed,
            acceptance_id,
            manifest_sha256,
        )


def test_local_mcp_dependency_rebind_is_current_and_non_live() -> None:
    candidate._verify_local_mcp_reacceptance(ROOT)


def test_v13_is_point_in_time_observation_not_availability_claim() -> None:
    candidate._verify_v13_observation(ROOT)
    record = (
        ROOT / "docs/onyx/operations/ONYX_V13_LIVE_PROMOTION_2026-07-23.md"
    ).read_text(encoding="utf-8")
    assert "It does not establish permanent provider availability." in record
    assert "This promotion is not Phase 6 exit" in record


def test_matrix_delta_is_required_but_cannot_accept_e6() -> None:
    candidate._verify_matrix_delta(ROOT)
    matrix = (ROOT / "docs/onyx/CAPABILITY_MATRIX.md").read_text(encoding="utf-8")
    section = matrix.split(candidate.MATRIX_MARKER, 1)[1].split(
        "## Matrix governance", 1
    )[0]
    assert "E6 pending" in section
    assert "does not\nunlock Phase 7" in section


def test_candidate_verification_is_read_only() -> None:
    paths = [ROOT / root.path for root in candidate.EVIDENCE_ROOTS]
    paths.append(ROOT / "docs/onyx/CAPABILITY_MATRIX.md")
    before = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
    }
    candidate.create_phase6_exit_candidate_v1(
        gate=candidate.Phase6ExitFeatureGateV1(True),
        project_root=ROOT,
    )
    after = {
        path: (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in paths
    }
    assert after == before


def test_candidate_source_has_no_network_process_or_live_dispatch_surface() -> None:
    source = (ROOT / "core/phase6_exit_candidate_v1.py").read_text(encoding="utf-8")
    forbidden = (
        "import socket",
        "import subprocess",
        "import requests",
        "import urllib",
        "Popen(",
        "create_connection(",
    )
    assert all(value not in source for value in forbidden)
    for relative in (
        "main.py",
        "ui.py",
        "dashboard/server.py",
        "scripts/launch_onyx_live_v13.pyw",
    ):
        assert candidate.FEATURE_FLAG not in (ROOT / relative).read_text(
            encoding="utf-8"
        )


def test_report_constructor_rejects_any_overclaim() -> None:
    values = {
        "candidate": candidate.CANDIDATE,
        "component_acceptances": 8,
        "evidence_roots": 34,
        "e1_e5_ready": True,
        "ready_for_external_gate": True,
        "external_e6_accepted": False,
        "phase6_exit": False,
        "phase7_unlocked": False,
        "runtime_authority_added": False,
        "live_observation_only": True,
        "permanent_provider_availability": False,
        "external_agent_authority": False,
        "cross_route_authority": False,
        "additional_provider_authority": False,
        "network_calls": 0,
        "provider_calls": 0,
        "process_calls": 0,
        "live_calls": 0,
    }
    for field in (
        "external_e6_accepted",
        "phase6_exit",
        "phase7_unlocked",
        "runtime_authority_added",
        "permanent_provider_availability",
        "external_agent_authority",
        "cross_route_authority",
        "additional_provider_authority",
    ):
        changed = dict(values)
        changed[field] = True
        with pytest.raises(candidate.Phase6ExitCandidateV1ContractError):
            candidate.Phase6ExitCandidateReportV1(**changed)  # type: ignore[arg-type]
