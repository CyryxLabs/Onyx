"""Focused and adversarial tests for the Phase 10 editorial calendar V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import phase10_editorial_calendar_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]
NOW = 1_000_000


def _post(post_id="p1", account_id="acc1", platform="instagram", scheduled=NOW + 3600,
          status="draft", idem="k1", disclosure=True):
    return {
        "post_id": post_id,
        "account_id": account_id,
        "platform": platform,
        "scheduled_utc": scheduled,
        "status": status,
        "idempotency_key": idem,
        "disclosure_included": disclosure,
    }


def _approval(post_id="p1", approved=True, approver="owner"):
    return {"post_id": post_id, "approved": approved, "approver": approver}


def _plan(posts, approvals=(), authorized=("acc1",), now=NOW):
    return {
        "authorized_account_ids": list(authorized),
        "now_utc": now,
        "posts": list(posts),
        "approvals": list(approvals),
    }


def _cal():
    return mod.create_editorial_calendar_v1(PROJECT)


# ── feature gate ────────────────────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.EditorialCalendarFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on_when_flag_set():
    gate = mod.EditorialCalendarFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}
    )
    assert gate.enabled is True


# ── entry-bind to the accepted brand passport slice ─────────────────────────

def test_entry_bind_passes_against_real_project():
    assert isinstance(_cal(), mod.EditorialCalendarV1)


def test_entry_bind_denied_when_evidence_absent(tmp_path):
    with pytest.raises(mod.EditorialCalendarV1Denied):
        mod.create_editorial_calendar_v1(tmp_path)


def test_entry_bind_denied_on_drift(tmp_path):
    for relative, _ in mod.ACCEPTED_BRAND_PASSPORT_ROOTS:
        p = tmp_path / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("tampered", encoding="utf-8")
    with pytest.raises(mod.EditorialCalendarV1Denied):
        mod.create_editorial_calendar_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        mod.EditorialCalendarV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_builds_sorted_deterministic_snapshot():
    cal = _cal()
    snap = cal.build(_plan(
        posts=[
            _post("z", idem="kz", scheduled=NOW + 10),
            _post("a", idem="ka", scheduled=NOW + 20),
        ],
        authorized=("acc1",),
    ))
    assert [p.post_id for p in snap.posts] == ["a", "z"]


def test_approved_and_scheduled_require_positive_approval():
    cal = _cal()
    snap = cal.build(_plan(
        posts=[_post("p1", status="scheduled")],
        approvals=[_approval("p1", approved=True)],
    ))
    assert snap.posts[0].status == "scheduled"
    assert cal.is_approved("p1") is True


def test_ready_to_publish_predicate_true_only_when_fully_ready():
    cal = _cal()
    cal.build(_plan(
        posts=[_post("p1", status="scheduled", disclosure=True)],
        approvals=[_approval("p1", approved=True)],
    ))
    assert cal.is_ready_to_publish("p1") is True


def test_ready_to_publish_false_without_disclosure():
    cal = _cal()
    # A scheduled+approved post without disclosure is not ready. (Its status is
    # scheduled, which is allowed; readiness simply returns False.)
    cal.build(_plan(
        posts=[_post("p1", status="scheduled", disclosure=False)],
        approvals=[_approval("p1", approved=True)],
    ))
    assert cal.is_ready_to_publish("p1") is False


def test_ready_to_publish_false_when_not_scheduled():
    cal = _cal()
    cal.build(_plan(
        posts=[_post("p1", status="approved")],
        approvals=[_approval("p1", approved=True)],
    ))
    assert cal.is_ready_to_publish("p1") is False
    assert cal.is_ready_to_publish("missing") is False


# ── approval gate ───────────────────────────────────────────────────────────

def test_scheduled_without_approval_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", status="scheduled")], approvals=[]))


def test_approved_status_with_negative_approval_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(
            posts=[_post("p1", status="approved")],
            approvals=[_approval("p1", approved=False)],
        ))


def test_draft_and_pending_need_no_approval():
    cal = _cal()
    snap = cal.build(_plan(posts=[
        _post("d", status="draft", idem="kd"),
        _post("q", status="pending_approval", idem="kq"),
    ]))
    assert {p.status for p in snap.posts} == {"draft", "pending_approval"}


# ── publishing is structurally absent ───────────────────────────────────────

def test_published_is_not_a_valid_status():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", status="published")]))


def test_no_publish_method_exists():
    cal = _cal()
    assert not hasattr(cal, "publish")


# ── adversarial rejections ──────────────────────────────────────────────────

def test_unauthorized_account_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", account_id="ghost")], authorized=("acc1",)))


def test_post_not_in_future_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", scheduled=NOW)]))


def test_scheduled_utc_must_be_exact_int():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", scheduled=True)]))
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", scheduled="123")]))


def test_duplicate_post_id_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[
            _post("dup", idem="k1"),
            _post("dup", idem="k2"),
        ]))


def test_duplicate_idempotency_key_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[
            _post("a", idem="same"),
            _post("b", idem="same"),
        ]))


def test_unknown_platform_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", platform="myspace")]))


def test_unknown_status_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1", status="live")]))


def test_approval_references_unknown_post_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1")], approvals=[_approval("ghost")]))


def test_duplicate_approval_rejected():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(
            posts=[_post("p1", status="approved")],
            approvals=[_approval("p1", approved=True), _approval("p1", approved=True)],
        ))


def test_now_utc_must_be_non_negative_int():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[], now=-1))
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[], now=True))


def test_plan_key_contract_enforced():
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build({"posts": [], "approvals": []})


def test_post_key_contract_enforced():
    bad = _post()
    del bad["status"]
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[bad]))


def test_approval_key_contract_enforced():
    bad = _approval()
    bad["extra"] = 1
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[_post("p1")], approvals=[bad]))


@pytest.mark.parametrize("value", ["", "has\x00null", 123, None])
def test_text_field_rejections(value):
    bad = _post()
    bad["idempotency_key"] = value
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=[bad]))


def test_item_cap_enforced():
    too_many = [_post(f"p{i}", idem=f"k{i}", scheduled=NOW + 1 + i)
                for i in range(mod.MAX_ITEMS + 1)]
    with pytest.raises(mod.EditorialCalendarV1ContractError):
        _cal().build(_plan(posts=too_many))
