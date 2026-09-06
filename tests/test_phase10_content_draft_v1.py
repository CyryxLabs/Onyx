"""Focused and adversarial tests for the Phase 10 content draft V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import phase10_content_draft_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]


def _asset(asset_id="a1", kind="image", source="original", rights=None, alt="a cat"):
    return {"asset_id": asset_id, "kind": kind, "source": source,
            "rights_ref": rights, "alt_text": alt}


def _claim(claim_id="c1", text="we grew", validated=True, evidence="report#1"):
    return {"claim_id": claim_id, "claim_text": text, "validated": validated,
            "evidence_ref": evidence}


def _draft(draft_id="d1", brand="cyryx_labs", platform="instagram", body="hello",
           status="draft", disclosure=True, assets=None, claims=None):
    return {
        "draft_id": draft_id, "brand_id": brand, "platform": platform,
        "body_text": body, "status": status, "disclosure_included": disclosure,
        "assets": [_asset()] if assets is None else assets,
        "claims": [_claim()] if claims is None else claims,
    }


def _review(draft_id="d1", approved=True, reviewer="owner"):
    return {"draft_id": draft_id, "approved": approved, "reviewer": reviewer}


def _plan(drafts, reviews=()):
    return {"drafts": list(drafts), "reviews": list(reviews)}


def _set():
    return mod.create_content_draft_set_v1(PROJECT)


# ── feature gate + entry-bind ───────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.ContentDraftFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.ContentDraftFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_entry_bind_passes_real_project():
    assert isinstance(_set(), mod.ContentDraftSetV1)


def test_entry_bind_denied_when_absent(tmp_path):
    with pytest.raises(mod.ContentDraftV1Denied):
        mod.create_content_draft_set_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.ContentDraftV1ContractError):
        mod.ContentDraftSetV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_builds_sorted_snapshot():
    snap = _set().build(_plan([_draft("z"), _draft("a")]))
    assert [d.draft_id for d in snap.drafts] == ["a", "z"]


def test_approved_requires_review_and_validated_claims_and_is_ready():
    s = _set()
    s.build(_plan(
        drafts=[_draft("d1", status="approved",
                       assets=[_asset(kind="image", alt="chart")],
                       claims=[_claim(validated=True, evidence="e1")])],
        reviews=[_review("d1", approved=True)],
    ))
    assert s.is_policy_approved("d1") is True
    assert s.is_ready_for_calendar("d1") is True


def test_draft_and_in_review_need_no_review():
    snap = _set().build(_plan([
        _draft("a", status="draft"),
        _draft("b", status="in_review"),
    ]))
    assert {d.status for d in snap.drafts} == {"draft", "in_review"}


# ── policy-review + anti-fabrication gate ───────────────────────────────────

def test_approved_without_review_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", status="approved")], reviews=[]))


def test_approved_with_negative_review_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan(
            [_draft("d1", status="approved")],
            reviews=[_review("d1", approved=False)],
        ))


def test_approved_with_unvalidated_claim_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan(
            [_draft("d1", status="approved",
                    claims=[_claim(validated=False, evidence=None)])],
            reviews=[_review("d1", approved=True)],
        ))


def test_validated_claim_requires_evidence():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1",
                     claims=[_claim(validated=True, evidence=None)])]))


# ── asset provenance ────────────────────────────────────────────────────────

def test_licensed_asset_requires_rights_ref():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1",
                     assets=[_asset(source="licensed", rights=None)])]))


def test_authorized_asset_requires_rights_ref():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1",
                     assets=[_asset(source="authorized", rights=None)])]))


def test_original_asset_needs_no_rights_ref():
    snap = _set().build(_plan([_draft("d1",
                       assets=[_asset(source="original", rights=None, alt="x")])]))
    assert snap.drafts[0].assets[0].source == "original"


def test_unknown_asset_source_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", assets=[_asset(source="stolen")])]))


def test_unknown_asset_kind_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", assets=[_asset(kind="hologram")])]))


# ── accessibility ───────────────────────────────────────────────────────────

def test_visual_asset_requires_alt_text():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", assets=[_asset(kind="video", alt=None)])]))


def test_text_asset_needs_no_alt_text():
    snap = _set().build(_plan([_draft("d1",
                       assets=[_asset(kind="text", source="original", alt=None)])]))
    assert snap.drafts[0].assets[0].alt_text is None


def test_ready_false_when_visual_missing_alt_is_impossible_but_unvalidated_blocks():
    # A draft cannot even build a visual without alt; readiness also blocks on an
    # unvalidated claim (checked before approval via a non-approved status).
    s = _set()
    s.build(_plan([_draft("d1", status="in_review",
                   claims=[_claim(validated=False, evidence=None)])]))
    assert s.is_ready_for_calendar("d1") is False  # not approved


# ── publishing is structurally absent ───────────────────────────────────────

def test_published_is_not_a_valid_status():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", status="published")]))


def test_no_publish_method():
    s = _set()
    assert not hasattr(s, "publish")
    assert not hasattr(s, "post")
    assert not hasattr(s, "schedule")


def test_ready_false_for_non_approved_and_missing():
    s = _set()
    s.build(_plan([_draft("d1", status="in_review")]))
    assert s.is_ready_for_calendar("d1") is False
    assert s.is_ready_for_calendar("missing") is False


def test_ready_false_without_disclosure():
    s = _set()
    s.build(_plan(
        [_draft("d1", status="approved", disclosure=False)],
        reviews=[_review("d1", approved=True)],
    ))
    assert s.is_ready_for_calendar("d1") is False


# ── adversarial rejections ──────────────────────────────────────────────────

def test_duplicate_draft_id_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("dup"), _draft("dup")]))


def test_duplicate_asset_id_within_draft_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1",
                     assets=[_asset("x"), _asset("x")])]))


def test_duplicate_claim_id_within_draft_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1",
                     claims=[_claim("x"), _claim("x")])]))


def test_review_references_unknown_draft_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1")], reviews=[_review("ghost")]))


def test_duplicate_review_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan(
            [_draft("d1", status="approved")],
            reviews=[_review("d1", approved=True), _review("d1", approved=True)],
        ))


def test_unknown_platform_rejected():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([_draft("d1", platform="myspace")]))


def test_draft_key_contract_enforced():
    bad = _draft(); del bad["status"]
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([bad]))


def test_plan_key_contract_enforced():
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build({"drafts": []})


@pytest.mark.parametrize("value", ["", "a\x00b", 5, None])
def test_body_text_rejections(value):
    bad = _draft(); bad["body_text"] = value
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan([bad]))


def test_item_cap_enforced():
    too_many = [_draft(f"d{i}") for i in range(mod.MAX_ITEMS + 1)]
    with pytest.raises(mod.ContentDraftV1ContractError):
        _set().build(_plan(too_many))
