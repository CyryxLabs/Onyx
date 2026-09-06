from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

import core.session_grants_v2 as grants
from core.permission_broker import build_request
from scripts import verify_phase5_grants_r2 as evidence_verifier


NOW = 2_000_000_000_000
SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()
SHA_D = hashlib.sha256(b"d").hexdigest()


def _policy(**overrides: object) -> grants.HostActionPolicy:
    values: dict[str, object] = {
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "risk": "low",
        "always_explicit": False,
        "max_data_class": "internal",
    }
    values.update(overrides)
    return grants.HostActionPolicy(**values)  # type: ignore[arg-type]


def _material(**overrides: object) -> grants.ActionMaterial:
    values: dict[str, object] = {
        "capability": "local-files",
        "tool": "file-controller",
        "operation": "write",
        "mission_id": "mission-one",
        "target_sha256": SHA_A,
        "payload_sha256": SHA_B,
        "data_class": "internal",
        "cost_micro": 3,
        "requested_at_ms": NOW,
    }
    values.update(overrides)
    return grants.ActionMaterial(**values)  # type: ignore[arg-type]


def _spec(**overrides: object) -> grants.GrantApprovalSpec:
    values: dict[str, object] = {
        "approval_id": "approval-one",
        "grant_id": "grant-one",
        "action": _material(),
        "target_sha256": (SHA_A,),
        "max_data_class": "internal",
        "risk_ceiling": "medium",
        "max_cost_per_action_micro": 5,
        "max_cost_aggregate_micro": 20,
        "max_uses": 3,
        "issued_at_ms": NOW - 1_000,
        "not_before_ms": NOW - 500,
        "expires_at_ms": NOW + 10_000,
    }
    values.update(overrides)
    return grants.GrantApprovalSpec(**values)  # type: ignore[arg-type]


def _authority(
    *,
    policies: tuple[grants.HostActionPolicy, ...] | None = None,
) -> grants.TrustedHostGrantAuthority:
    return grants._compose_host_authority_for_testing(
        principal_id="owner-one",
        session_id="session-one",
        workspace_id="workspace-one",
        mission_ids=("mission-one", "mission-two"),
        action_policies=policies or (_policy(),),
        audit_head=SHA_D,
    )


def _approve(authority: grants.TrustedHostGrantAuthority, spec: grants.GrantApprovalSpec) -> None:
    proof = authority._preview_approval_digest_for_testing(spec)
    authority._register_approved_spec(spec, trusted_callback_digest=proof)


def _ready(
    *,
    spec: grants.GrantApprovalSpec | None = None,
    policies: tuple[grants.HostActionPolicy, ...] | None = None,
) -> tuple[grants.TrustedHostGrantAuthority, grants.SessionGrantStore, grants.TypedActionRequest]:
    authority = _authority(policies=policies)
    approved = spec or _spec()
    _approve(authority, approved)
    store = authority.open_session_store()
    store.issue_from_host_approval(approved.approval_id, now_ms=NOW)
    return authority, store, authority.resolve_action(approved.action)


def _evaluate(
    store: grants.SessionGrantStore,
    request: grants.TypedActionRequest,
    *,
    now_ms: int = NOW,
    environ: dict[str, str] | None = None,
) -> grants.ShadowGrantDecision:
    return store.shadow_evaluate(
        request,
        now_ms=now_ms,
        environ=environ or {grants.GRANT_EVALUATOR_FLAG: "true"},
    )


def _tamper_request(
    request: grants.TypedActionRequest, field: str, value: object
) -> grants.TypedActionRequest:
    clone = copy.copy(request)
    object.__setattr__(clone, field, value)
    return clone


def test_permission_digest_retains_exact_stable_core_algorithm() -> None:
    details = {"b": [2, 3], "a": {"x": True}}
    expected = build_request("grant.session", "summary", details)
    assert grants.permission_request_digest("grant.session", "summary", details) == expected["digest"]


@pytest.mark.parametrize("value", ["1", "true", " TRUE "])
def test_default_off_flag_accepts_only_explicit_values(value: str) -> None:
    assert grants.grant_evaluator_enabled({grants.GRANT_EVALUATOR_FLAG: value})
    for disabled in ("", "0", "yes", "on", "enabled", "2"):
        assert not grants.grant_evaluator_enabled({grants.GRANT_EVALUATOR_FLAG: disabled})


def test_raw_authority_store_request_grant_and_record_construction_is_closed() -> None:
    with pytest.raises(grants.GrantV2AuthorityError):
        grants.TrustedHostGrantAuthority(
            object(),
            principal_id="owner-one",
            session_id="session-one",
            workspace_id="workspace-one",
            mission_ids=("mission-one",),
            action_policies=(_policy(),),
            audit_head=SHA_D,
        )
    authority = _authority()
    with pytest.raises(grants.GrantV2AuthorityError):
        grants.SessionGrantStore(object(), authority)
    with pytest.raises(grants.GrantV2AuthorityError):
        grants.TypedActionRequest()  # type: ignore[call-arg]
    with pytest.raises(grants.GrantV2AuthorityError):
        grants.SessionGrant()  # type: ignore[call-arg]
    with pytest.raises(grants.GrantV2AuthorityError):
        grants.HostApprovalRecord()  # type: ignore[call-arg]


def test_store_accepts_only_host_approval_identity_not_raw_grant() -> None:
    authority = _authority()
    store = authority.open_session_store()
    assert not hasattr(store, "issue")
    with pytest.raises(grants.GrantV2AuthorityError, match="unknown or consumed"):
        store.issue_from_host_approval("approval-one", now_ms=NOW)


def test_authority_resolves_identity_workspace_policy_and_risk() -> None:
    authority = _authority(policies=(_policy(risk="medium"),))
    request = authority.resolve_action(_material())
    assert request.principal_id == "owner-one"
    assert request.session_id == "session-one"
    assert request.workspace_id == "workspace-one"
    assert request.risk == "medium"
    assert request.policy_version == grants.GRANT_POLICY_VERSION
    assert request.schema_version == grants.GRANT_SCHEMA_VERSION
    assert request.action_digest == grants.canonical_action_digest(request)


def test_unknown_action_mission_and_overclassified_data_fail_at_authority() -> None:
    authority = _authority()
    with pytest.raises(grants.GrantV2ContractError, match="unknown host action policy"):
        authority.resolve_action(_material(operation="delete"))
    with pytest.raises(grants.GrantV2ContractError, match="mission_id"):
        authority.resolve_action(_material(mission_id="mission-three"))
    with pytest.raises(grants.GrantV2ContractError, match="data class"):
        authority.resolve_action(_material(data_class="restricted"))


def test_exact_callback_digest_is_required_to_register_approval() -> None:
    authority = _authority()
    spec = _spec()
    with pytest.raises(grants.GrantV2AuthorityError, match="exact grant scope"):
        authority._register_approved_spec(spec, trusted_callback_digest=SHA_C)
    _approve(authority, spec)
    store = authority.open_session_store()
    assert store.issue_from_host_approval("approval-one", now_ms=NOW) == "grant-one"


def test_approval_is_single_use_even_across_store_issue_attempts() -> None:
    authority = _authority()
    spec = _spec()
    _approve(authority, spec)
    store = authority.open_session_store()
    store.issue_from_host_approval(spec.approval_id, now_ms=NOW)
    with pytest.raises(grants.GrantV2AuthorityError, match="consumed"):
        store.issue_from_host_approval(spec.approval_id, now_ms=NOW)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 99),
        ("policy_version", "onyx-approval-v3"),
        ("authority_id", SHA_C),
        ("principal_id", "owner-two"),
        ("session_id", "session-two"),
        ("workspace_id", "workspace-two"),
        ("mission_id", "mission-two"),
        ("capability", "calendar-read"),
        ("tool", "calendar-tool"),
        ("operation", "read"),
        ("target_sha256", SHA_C),
        ("payload_sha256", SHA_C),
        ("risk", "medium"),
        ("always_explicit", True),
        ("data_class", "public"),
        ("cost_micro", 4),
        ("requested_at_ms", NOW + 1),
        ("action_digest", SHA_C),
    ],
)
def test_canonical_digest_rejects_every_meaningful_field_tamper(
    field: str, value: object
) -> None:
    _authority_value, store, request = _ready()
    with pytest.raises(grants.GrantV2ContractError):
        _evaluate(store, _tamper_request(request, field, value))


def test_fresh_semantic_target_payload_cost_and_time_drift_recompute_and_deny() -> None:
    authority, store, request = _ready()
    for material in (
        _material(target_sha256=SHA_C),
        _material(payload_sha256=SHA_C),
        _material(cost_micro=4),
        _material(requested_at_ms=NOW + 1),
    ):
        changed = authority.resolve_action(material)
        assert changed.action_digest != request.action_digest
        assert _evaluate(store, changed, now_ms=NOW + 1).outcome == "would_deny"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("record_digest", SHA_C),
        ("scope_digest", SHA_C),
        ("approval_digest", SHA_C),
        ("action_digest", SHA_C),
        ("payload_sha256", SHA_C),
        ("target_sha256", (SHA_C,)),
        ("workspace_id", "workspace-two"),
        ("principal_id", "owner-two"),
        ("max_uses", 99),
        ("expires_at_ms", NOW + 20_000),
    ],
)
def test_approval_record_and_bound_scope_tamper_fail_before_issue(
    field: str, value: object
) -> None:
    authority = _authority()
    spec = _spec()
    _approve(authority, spec)
    record = authority._approval_records[spec.approval_id]
    if field == "record_digest":
        object.__setattr__(record, field, value)
    else:
        object.__setattr__(record.grant, field, value)
    store = authority.open_session_store()
    with pytest.raises(grants.GrantV2AuthorityError, match="verification failed"):
        store.issue_from_host_approval(spec.approval_id, now_ms=NOW)


def test_constant_time_comparison_covers_action_scope_approval_and_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    original = grants.hmac.compare_digest

    def traced(left: str, right: str) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(grants.hmac, "compare_digest", traced)
    authority, store, request = _ready()
    assert _evaluate(store, request).outcome == "would_allow"
    assert any(left == request.action_digest for left, _right in calls)
    record = authority._approval_records["approval-one"]
    assert any(left == record.grant.scope_digest for left, _right in calls)
    assert any(left == record.grant.approval_digest for left, _right in calls)


def test_public_decision_cannot_override_callback_or_authority_flags() -> None:
    decision = grants.ShadowGrantDecision("would_allow", "exact_session_grant", "grant-one", SHA_A)
    assert decision.callback_required is True
    assert decision.authority_granted is False
    with pytest.raises(TypeError):
        grants.ShadowGrantDecision(  # type: ignore[call-arg]
            "would_allow",
            "exact_session_grant",
            "grant-one",
            SHA_A,
            callback_required=False,
            authority_granted=True,
        )
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.authority_granted = True  # type: ignore[misc]


def test_flag_off_is_callback_parity_and_does_not_consume() -> None:
    _authority_value, store, request = _ready(spec=_spec(max_uses=1))
    disabled = store.shadow_evaluate(request, now_ms=NOW, environ={})
    allowed = _evaluate(store, request)
    assert (disabled.outcome, disabled.reason) == ("disabled", "feature_flag_off")
    assert allowed.outcome == "would_allow"
    assert disabled.callback_required and not disabled.authority_granted
    assert allowed.callback_required and not allowed.authority_granted


def test_use_per_action_and_aggregate_limits_are_atomic_shadow_bounds() -> None:
    authority, store, request = _ready(
        spec=_spec(max_uses=2, max_cost_per_action_micro=3, max_cost_aggregate_micro=5)
    )
    assert _evaluate(store, request).outcome == "would_allow"
    assert _evaluate(store, request).reason == "aggregate_cost"
    expensive = authority.resolve_action(_material(cost_micro=4))
    assert _evaluate(store, expensive).reason == "no_exact_unique_grant"


def test_expiry_permanently_revokes_even_after_clock_rollback() -> None:
    _authority_value, store, request = _ready(spec=_spec(expires_at_ms=NOW + 10))
    first = _evaluate(store, request, now_ms=NOW + 10)
    rolled_back = _evaluate(store, request, now_ms=NOW)
    assert (first.outcome, first.reason) == ("would_deny", "expired")
    assert (rolled_back.outcome, rolled_back.reason) == (
        "would_deny",
        "no_exact_unique_grant",
    )


def test_policy_change_permanently_revokes_even_after_version_rollback() -> None:
    authority, store, request = _ready()
    authority._replace_state_for_testing(policy_version="onyx-approval-v3")
    changed = _evaluate(store, request)
    authority._replace_state_for_testing(policy_version=grants.GRANT_POLICY_VERSION)
    rolled_back = _evaluate(store, request)
    assert changed.reason == "policy_changed"
    assert rolled_back.reason == "no_exact_unique_grant"


def test_schema_change_permanently_revokes_even_after_version_rollback() -> None:
    authority, store, request = _ready()
    authority._replace_state_for_testing(schema_version=3)
    changed = _evaluate(store, request)
    authority._replace_state_for_testing(schema_version=grants.GRANT_SCHEMA_VERSION)
    rolled_back = _evaluate(store, request)
    assert changed.reason == "schema_changed"
    assert rolled_back.reason == "no_exact_unique_grant"


def test_audit_head_change_permanently_revokes() -> None:
    authority, store, request = _ready()
    authority._replace_state_for_testing(audit_head=SHA_C)
    assert _evaluate(store, request).reason == "audit_head_changed"
    authority._replace_state_for_testing(audit_head=SHA_D)
    assert _evaluate(store, request).reason == "no_exact_unique_grant"


def test_revoke_kill_audit_unhealthy_and_session_end_deny_immediately() -> None:
    _authority_value, store, request = _ready()
    store.revoke("grant-one", at_ms=NOW)
    assert _evaluate(store, request).outcome == "would_deny"

    _authority_value, store, request = _ready()
    store.kill(at_ms=NOW)
    assert _evaluate(store, request).reason == "kill_switch"

    _authority_value, store, request = _ready()
    store.mark_audit_unhealthy(at_ms=NOW)
    assert _evaluate(store, request).reason == "audit_unhealthy"

    _authority_value, store, request = _ready()
    store.end_session(at_ms=NOW)
    assert _evaluate(store, request).reason == "session_ended"


def test_restart_new_authority_and_store_restore_no_session_grant() -> None:
    _old_authority, old_store, old_request = _ready()
    assert _evaluate(old_store, old_request).outcome == "would_allow"
    restarted = _authority()
    new_store = restarted.open_session_store()
    new_request = restarted.resolve_action(_material())
    assert _evaluate(new_store, new_request).reason == "no_exact_unique_grant"
    assert not hasattr(new_store, "save")
    assert not hasattr(new_store, "load")
    assert not hasattr(new_store, "restore")


@pytest.mark.parametrize(
    "policy",
    [
        _policy(always_explicit=True),
        _policy(risk="high"),
        _policy(risk="critical"),
    ],
)
def test_always_explicit_high_and_critical_cannot_be_registered(
    policy: grants.HostActionPolicy,
) -> None:
    authority = _authority(policies=(policy,))
    with pytest.raises(grants.GrantV2ContractError, match="cannot become a grant"):
        authority._preview_approval_digest_for_testing(_spec())
    store = authority.open_session_store()
    request = authority.resolve_action(_material())
    expected_reason = "always_explicit" if policy.always_explicit else "risk_not_grantable"
    assert _evaluate(store, request).reason == expected_reason


@pytest.mark.parametrize(
    ("factory", "changes"),
    [
        (_authority, {"workspace_id": "../owner"}),
        (_authority, {"workspace_id": "ab"}),
        (_authority, {"workspace_id": "Workspace-One"}),
        (_authority, {"principal_id": "owner/one"}),
        (_authority, {"session_id": "Bearer-abcdef1234567890"}),
    ],
)
def test_path_relative_token_and_invalid_workspace_ids_reject(
    factory, changes: dict[str, object]
) -> None:
    base = {
        "principal_id": "owner-one",
        "session_id": "session-one",
        "workspace_id": "workspace-one",
        "mission_ids": ("mission-one",),
        "action_policies": (_policy(),),
        "audit_head": SHA_D,
    }
    base.update(changes)
    with pytest.raises(grants.GrantV2ContractError):
        grants._compose_host_authority_for_testing(**base)


def test_every_recoverable_string_routes_through_contains_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    original = grants.contains_secret

    def traced(*values: object) -> bool:
        seen.extend(str(value) for value in values if value is not None)
        return original(*values)

    monkeypatch.setattr(grants, "contains_secret", traced)
    authority, store, request = _ready()
    _evaluate(store, request)
    record = authority._approval_records["approval-one"]
    expected = {
        "owner-one",
        "session-one",
        "workspace-one",
        "mission-one",
        "local-files",
        "file-controller",
        "write",
        SHA_A,
        SHA_B,
        SHA_D,
        request.action_digest,
        record.grant.approval_digest,
        record.grant.scope_digest,
    }
    assert expected <= set(seen)


def test_high_confidence_secret_probe_is_rejected_by_project_detector() -> None:
    with pytest.raises(grants.GrantV2ContractError):
        grants._safe_id("sk-proj-abcdefghijklmnop", "principal_id")


def test_no_startup_ui_dashboard_owner_or_provider_wiring_and_v1_is_unchanged() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in ("main.py", "ui.py", "dashboard/server.py"):
        source = (root / relative).read_text(encoding="utf-8")
        assert "session_grants_v2" not in source
        assert "ONYX_GRANT_EVALUATOR" not in source
    assert (root / "core/session_grants_v1.py").is_file()
    assert (root / "tests/test_session_grants_v1.py").is_file()


def _write_manifest(root: Path, relative: str, paths: tuple[str, ...]) -> None:
    lines = []
    for path in paths:
        digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
        lines.append(f"{digest}  {path}\n")
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(lines), encoding="utf-8", newline="\n")


def _evidence_tree(root: Path) -> None:
    leaf_paths = tuple(
        path
        for path in evidence_verifier.ARTIFACT_PATHS
        if path != evidence_verifier.BUNDLE
    )
    for index, relative in enumerate(leaf_paths):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"leaf-{index}\n", encoding="utf-8", newline="\n")
    files = {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in leaf_paths
    }
    bundle = {
        "base_commit": "0" * 40,
        "contract": "Phase5SessionGrantShadowEvidence.v2",
        "counts": {"errors": 0, "failed": 0, "passed": 60, "skipped": 0},
        "dag": {
            "artifact_points_to": list(evidence_verifier.ARTIFACT_PATHS),
            "leaf_hashes_are_only_in_bundle": True,
            "root": evidence_verifier.TOP_MANIFEST,
            "root_points_to": [evidence_verifier.ARTIFACT_MANIFEST],
        },
        "environment": {"python": "3.13.7"},
        "feature_flag": {"default": False, "name": "ONYX_GRANT_EVALUATOR"},
        "files": files,
        "limits": {"lifetime_ms": grants.MAX_SESSION_LIFETIME_MS},
        "status": "candidate-default-off-not-accepted",
        "timestamp": "2026-07-20T00:00:00Z",
    }
    bundle_path = root / evidence_verifier.BUNDLE
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_path.write_text(
        json.dumps(bundle, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    _write_manifest(
        root,
        evidence_verifier.ARTIFACT_MANIFEST,
        evidence_verifier.ARTIFACT_PATHS,
    )
    _write_manifest(root, evidence_verifier.TOP_MANIFEST, evidence_verifier.TOP_PATHS)


def test_evidence_exact_set_and_canonical_dag_pass(tmp_path: Path) -> None:
    _evidence_tree(tmp_path)
    result = evidence_verifier.verify_evidence(tmp_path)
    assert result["root_files"] == 1
    assert result["artifact_files"] == len(evidence_verifier.ARTIFACT_PATHS)


@pytest.mark.parametrize("mutation", ["leaf", "missing", "extra", "order", "crlf"])
def test_evidence_tamper_missing_extra_order_and_noncanonical_fail(
    tmp_path: Path, mutation: str
) -> None:
    _evidence_tree(tmp_path)
    manifest = tmp_path / evidence_verifier.ARTIFACT_MANIFEST
    if mutation == "leaf":
        (tmp_path / evidence_verifier.ARTIFACT_PATHS[0]).write_text("tampered\n")
    elif mutation == "missing":
        lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
        manifest.write_text("".join(lines[:-1]), encoding="utf-8", newline="\n")
    elif mutation == "extra":
        with manifest.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{'0' * 64}  unexpected.txt\n")
    elif mutation == "order":
        lines = manifest.read_text(encoding="utf-8").splitlines(keepends=True)
        manifest.write_text("".join(reversed(lines)), encoding="utf-8", newline="\n")
    else:
        manifest.write_bytes(manifest.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(evidence_verifier.Phase5GrantEvidenceError):
        evidence_verifier.verify_evidence(tmp_path)


def test_bundle_noncanonical_and_manifest_hash_cycle_fields_fail(tmp_path: Path) -> None:
    _evidence_tree(tmp_path)
    bundle_path = tmp_path / evidence_verifier.BUNDLE
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    bundle["root_manifest_sha256"] = SHA_A
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8", newline="\n")
    _write_manifest(
        tmp_path,
        evidence_verifier.ARTIFACT_MANIFEST,
        evidence_verifier.ARTIFACT_PATHS,
    )
    _write_manifest(tmp_path, evidence_verifier.TOP_MANIFEST, evidence_verifier.TOP_PATHS)
    with pytest.raises(evidence_verifier.Phase5GrantEvidenceError):
        evidence_verifier.verify_evidence(tmp_path)
