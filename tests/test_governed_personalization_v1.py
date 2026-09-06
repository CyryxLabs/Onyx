from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.governed_personalization_v1 import (
    GovernedPersonalizationDenied,
    GovernedPersonalizationStoreV1,
    PersonalizationFeatureGateV1,
)
from scripts.onyx_personalization_cli import main


OWNER = "owner-1"
WORKSPACE = "workspace-1"


def store(
    tmp_path: Path, *, clock=lambda: 100.0, sensitive: bool = False
) -> GovernedPersonalizationStoreV1:
    return GovernedPersonalizationStoreV1(
        tmp_path / "personalization.sqlite3",
        owner_profile_id=OWNER,
        workspace_id=WORKSPACE,
        gate=PersonalizationFeatureGateV1(True, sensitive),
        clock=clock,
    )


def test_default_off_and_cross_workspace_are_denied(tmp_path: Path) -> None:
    with pytest.raises(GovernedPersonalizationDenied, match="disabled"):
        GovernedPersonalizationStoreV1(
            tmp_path / "off.sqlite3",
            owner_profile_id=OWNER,
            workspace_id=WORKSPACE,
            gate=PersonalizationFeatureGateV1(False),
        )
    subject = store(tmp_path)
    with pytest.raises(GovernedPersonalizationDenied, match="cross-workspace"):
        subject.create(
            preference_key="interaction.tone",
            value="direct",
            provenance=["owner_observation:1"],
            workspace_id="workspace-2",
        )


def test_inferred_confirm_edit_revoke_export_delete_lifecycle(tmp_path: Path) -> None:
    now = [100.0]
    subject = store(tmp_path, clock=lambda: now[0])
    inferred = subject.create(
        preference_key="interaction.tone",
        value="direct",
        provenance=["conversation:sha256:abc"],
        freshness_seconds=10,
    )
    assert inferred.source == inferred.status == "inferred"
    assert inferred.freshness == "fresh"

    confirmed = subject.confirm(inferred.record_id)
    assert confirmed.source == "owner_confirmed"
    assert confirmed.status == "confirmed"
    edited = subject.edit(
        inferred.record_id,
        value={"style": "warm"},
        provenance=["owner_edit:1"],
        freshness_seconds=10,
    )
    assert edited.value == {"style": "warm"}
    assert edited.revision == 3
    now[0] = 111.0
    assert subject.inspect(inferred.record_id).freshness == "stale"  # type: ignore[union-attr]

    revoked = subject.revoke(inferred.record_id)
    assert revoked.status == revoked.freshness == "revoked"
    exported = subject.export()
    assert exported["records"][0]["provenance"] == ("owner_edit:1",)  # type: ignore[index]
    assert subject.delete(inferred.record_id) == 1
    assert subject.inspect() == ()


@pytest.mark.parametrize(
    "key", ["account.preference", "risk_level", "permission-mode", "authority"]
)
def test_personalization_cannot_change_authority_risk_or_account(
    tmp_path: Path, key: str
) -> None:
    subject = store(tmp_path)
    with pytest.raises(GovernedPersonalizationDenied, match="authority, risk, account"):
        subject.create(
            preference_key=key,
            value=True,
            provenance=["owner:1"],
            inferred=False,
        )


def test_sensitive_records_are_default_off(tmp_path: Path) -> None:
    with pytest.raises(GovernedPersonalizationDenied, match="sensitive"):
        store(tmp_path).create(
            preference_key="interaction.private_note",
            value="private",
            provenance=["owner:1"],
            sensitivity="sensitive",
        )
    allowed = store(tmp_path / "allowed", sensitive=True).create(
        preference_key="interaction.private_note",
        value="private",
        provenance=["owner:1"],
        sensitivity="sensitive",
        inferred=False,
    )
    assert allowed.sensitivity == "sensitive"


def test_cli_emits_json_and_nonzero_on_denial(tmp_path: Path, capsys) -> None:
    database = tmp_path / "cli.sqlite3"
    base = [
        "--database",
        str(database),
        "--owner",
        OWNER,
        "--workspace",
        WORKSPACE,
    ]
    assert main([*base, "inspect"]) == 2
    denied = json.loads(capsys.readouterr().out)
    assert denied["ok"] is False

    assert (
        main(
            [
                *base,
                "--enable",
                "create",
                "--key",
                "interaction.detail",
                "--value",
                '"concise"',
                "--provenance",
                "owner:cli",
            ]
        )
        == 0
    )
    created = json.loads(capsys.readouterr().out)
    assert created["ok"] is True
    assert created["result"]["status"] == "inferred"

    assert main([*base, "--enable", "export"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["result"]["contract"] == "OnyxGovernedPersonalization.v1"
