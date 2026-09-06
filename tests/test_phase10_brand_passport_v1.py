"""Focused and adversarial tests for the Phase 10 brand passport inventory V1."""

from __future__ import annotations

from pathlib import Path

import pytest

from core import phase10_brand_passport_v1 as mod

PROJECT = Path(__file__).resolve().parents[1]

GUARDS = set(mod.REQUIRED_POLICY_GUARDS)


def _passport(brand_id="cyryx_labs", *, authorized=True, platforms=("instagram",),
              guards=None, disclosure=True, legal="Cyryx Labs LLC"):
    return {
        "brand_id": brand_id,
        "legal_name": legal,
        "authorized": authorized,
        "allowed_platforms": list(platforms),
        "disclosure_required": disclosure,
        "policy_guards": list(GUARDS if guards is None else guards),
    }


def _account(account_id="acc1", brand_id="cyryx_labs", platform="instagram",
             handle="@cyryx", account_type="brand", authorized=True, scopes=("read",)):
    return {
        "account_id": account_id,
        "brand_id": brand_id,
        "platform": platform,
        "handle": handle,
        "account_type": account_type,
        "authorized": authorized,
        "scopes": list(scopes),
    }


def _registry():
    return mod.create_brand_registry_v1(PROJECT)


# ── feature gate ────────────────────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.BrandPassportFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on_when_flag_set():
    gate = mod.BrandPassportFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}
    )
    assert gate.enabled is True


def test_feature_gate_rejects_non_bool():
    with pytest.raises(mod.BrandPassportV1ContractError):
        mod.BrandPassportFeatureGateV1(enabled="true")  # type: ignore[arg-type]


# ── entry-bind to the accepted Phase 9 exit ─────────────────────────────────

def test_entry_bind_passes_against_real_project():
    # The accepted Phase 9 exit evidence exists byte-exact on disk.
    assert isinstance(_registry(), mod.BrandRegistryV1)


def test_entry_bind_denied_when_evidence_absent(tmp_path):
    with pytest.raises(mod.BrandPassportV1Denied):
        mod.create_brand_registry_v1(tmp_path)


def test_entry_bind_denied_on_drift(tmp_path):
    # Recreate the tuple of paths but with wrong bytes -> hash drift -> denied.
    for relative, _ in mod.ACCEPTED_PHASE9_EXIT_ROOTS:
        p = tmp_path / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("tampered", encoding="utf-8")
    with pytest.raises(mod.BrandPassportV1Denied):
        mod.create_brand_registry_v1(tmp_path)


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.BrandPassportV1ContractError):
        mod.BrandRegistryV1(construction_key=object())


# ── happy path ──────────────────────────────────────────────────────────────

def test_builds_multi_brand_inventory_sorted_and_deterministic():
    inv = _registry().build({
        "passports": [
            _passport("maax_studio", legal="MAAX Studio", platforms=("youtube", "x")),
            _passport("cyryx_labs", legal="Cyryx Labs LLC", platforms=("instagram",)),
            _passport("lyra", legal="Lyra", platforms=("tiktok",)),
        ],
        "accounts": [
            _account("z_acc", "lyra", "tiktok", "@lyra"),
            _account("a_acc", "cyryx_labs", "instagram", "@cyryx"),
            _account("m_acc", "maax_studio", "youtube", "@maax"),
        ],
    })
    assert [p.brand_id for p in inv.passports] == ["cyryx_labs", "lyra", "maax_studio"]
    assert [a.account_id for a in inv.accounts] == ["a_acc", "m_acc", "z_acc"]


def test_can_publish_is_always_false():
    inv = _registry().build({"passports": [_passport()], "accounts": [_account()]})
    assert all(acc.can_publish is False for acc in inv.accounts)


def test_is_usable_requires_both_brand_and_account_authorized():
    reg = _registry()
    reg.build({
        "passports": [
            _passport("cyryx_labs", authorized=True),
            _passport("blocked_brand", authorized=False, platforms=("x",)),
        ],
        "accounts": [
            _account("ok", "cyryx_labs", authorized=True),
            _account("unauth_acc", "cyryx_labs", handle="@cyryx2", authorized=False),
            _account("blocked_acc", "blocked_brand", platform="x", handle="@b"),
        ],
    })
    assert reg.is_usable("ok") is True
    assert reg.is_usable("unauth_acc") is False       # account not authorized
    assert reg.is_usable("blocked_acc") is False       # brand not authorized
    assert reg.is_usable("missing") is False


def test_resolve_returns_owning_brand():
    reg = _registry()
    reg.build({"passports": [_passport()], "accounts": [_account()]})
    assert reg.resolve("instagram", "@cyryx") == "cyryx_labs"
    assert reg.resolve("instagram", "@nobody") is None


def test_accounts_for_filters_by_brand():
    reg = _registry()
    reg.build({
        "passports": [
            _passport("cyryx_labs", platforms=("instagram", "x")),
        ],
        "accounts": [
            _account("a", "cyryx_labs", "instagram", "@cyryx"),
            _account("b", "cyryx_labs", "x", "@cyryxx"),
        ],
    })
    assert [a.account_id for a in reg.accounts_for("cyryx_labs")] == ["a", "b"]
    assert reg.accounts_for("nobody") == ()


# ── strict brand separation ─────────────────────────────────────────────────

def test_same_platform_handle_across_brands_is_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [
                _passport("cyryx_labs", platforms=("instagram",)),
                _passport("maax_studio", platforms=("instagram",)),
            ],
            "accounts": [
                _account("a", "cyryx_labs", "instagram", "@shared"),
                _account("b", "maax_studio", "instagram", "@shared"),
            ],
        })


def test_same_platform_handle_twice_same_brand_rejected():
    # A (platform, handle) identifies one real account, so it cannot be claimed
    # twice even within one brand.
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs", platforms=("instagram",))],
            "accounts": [
                _account("a", "cyryx_labs", "instagram", "@cyryx"),
                _account("b", "cyryx_labs", "instagram", "@cyryx"),
            ],
        })


def test_same_handle_different_platform_is_allowed():
    inv = _registry().build({
        "passports": [_passport("cyryx_labs", platforms=("instagram", "x"))],
        "accounts": [
            _account("a", "cyryx_labs", "instagram", "@cyryx"),
            _account("b", "cyryx_labs", "x", "@cyryx"),
        ],
    })
    assert len(inv.accounts) == 2


# ── contract / adversarial rejections ───────────────────────────────────────

def test_account_platform_outside_brand_allow_list_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs", platforms=("instagram",))],
            "accounts": [_account("a", "cyryx_labs", "youtube", "@cyryx")],
        })


def test_unknown_platform_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs", platforms=("instagram",))],
            "accounts": [_account("a", "cyryx_labs", "myspace", "@cyryx")],
        })


def test_missing_policy_guard_rejected():
    partial = set(GUARDS)
    partial.discard("no_fake_personas")
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport(guards=partial)],
            "accounts": [],
        })


def test_unknown_policy_guard_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport(guards=set(GUARDS) | {"buy_followers"})],
            "accounts": [],
        })


def test_duplicate_brand_id_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs"), _passport("cyryx_labs")],
            "accounts": [],
        })


def test_duplicate_account_id_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs", platforms=("instagram", "x"))],
            "accounts": [
                _account("dup", "cyryx_labs", "instagram", "@a"),
                _account("dup", "cyryx_labs", "x", "@b"),
            ],
        })


def test_account_referencing_unknown_brand_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport("cyryx_labs")],
            "accounts": [_account("a", "ghost_brand", "instagram", "@x")],
        })


def test_unknown_account_type_rejected():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({
            "passports": [_passport()],
            "accounts": [_account(account_type="shadow")],
        })


def test_passport_key_contract_enforced():
    reg = _registry()
    bad = _passport()
    del bad["disclosure_required"]
    with pytest.raises(mod.BrandPassportV1ContractError):
        reg.build({"passports": [bad], "accounts": []})


def test_account_key_contract_enforced():
    reg = _registry()
    bad = _account()
    bad["extra"] = 1
    with pytest.raises(mod.BrandPassportV1ContractError):
        reg.build({"passports": [_passport()], "accounts": [bad]})


def test_inventory_key_contract_enforced():
    with pytest.raises(mod.BrandPassportV1ContractError):
        _registry().build({"passports": []})


@pytest.mark.parametrize("value", ["", "has\x00null", 123, None])
def test_text_field_rejections(value):
    reg = _registry()
    bad = _passport()
    bad["legal_name"] = value
    with pytest.raises(mod.BrandPassportV1ContractError):
        reg.build({"passports": [bad], "accounts": []})


def test_oversize_text_rejected():
    reg = _registry()
    bad = _passport()
    bad["legal_name"] = "x" * (mod.MAX_TEXT_BYTES + 1)
    with pytest.raises(mod.BrandPassportV1ContractError):
        reg.build({"passports": [bad], "accounts": []})


def test_item_cap_enforced():
    reg = _registry()
    too_many = [_passport(f"b{i}") for i in range(mod.MAX_ITEMS + 1)]
    with pytest.raises(mod.BrandPassportV1ContractError):
        reg.build({"passports": too_many, "accounts": []})
