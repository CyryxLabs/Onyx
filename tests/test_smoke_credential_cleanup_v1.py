from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import build_release as build
from core.native_vault import SecretReference


def test_smoke_reference_sets_are_exact_and_disposable(tmp_path: Path) -> None:
    data = tmp_path / "data"
    workspace = data / "workspace"
    workspace.mkdir(parents=True)

    governance = build._governance_smoke_credential_references(data)
    founder = build._founder_smoke_credential_references(data, workspace)

    assert len(governance) == 3
    assert {item.account for item in governance} == {
        "ledger-key",
        "ledger-head",
        "ledger-pending",
    }
    assert all(item.service.startswith("Onyx.GovernanceV1.Smoke.") for item in governance)
    assert founder[:3] == governance
    assert {item.service for item in founder[3:]} == {
        "CyryxLabs.Onyx.FounderSnapshot"
    }
    assert {item.account.split("-", 1)[0] for item in founder[3:]} == {
        "integrity",
        "receipt",
    }


def test_packaged_smokes_cleanup_credentials_when_children_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    deleted: list[tuple[object, ...]] = []

    monkeypatch.setattr(build.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        build,
        "_delete_windows_smoke_credentials",
        lambda references: deleted.append(references),
    )

    def timeout(*args: object, **kwargs: object) -> object:
        raise subprocess.TimeoutExpired(args[0] if args else "Onyx.exe", 1)

    monkeypatch.setattr(build.subprocess, "run", timeout)

    with pytest.raises(subprocess.TimeoutExpired):
        build.package_governance_smoke_test(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        build.package_founder_smoke_test(tmp_path)

    assert [len(references) for references in deleted] == [3, 5]


def test_diagnostic_target_parser_accepts_only_disposable_namespaces() -> None:
    governance = build._diagnostic_reference_from_windows_target(
        "Onyx.GovernanceV1.Smoke.0123456789abcdef01234567:ledger-head"
    )
    founder = build._diagnostic_reference_from_windows_target(
        "CyryxLabs.Onyx.FounderSnapshot:receipt-0123456789abcdef01234567"
    )

    assert isinstance(governance, SecretReference)
    assert governance.account == "ledger-head"
    assert isinstance(founder, SecretReference)
    assert founder.account == "receipt-0123456789abcdef01234567"
    assert build._diagnostic_reference_from_windows_target(
        "CyryxLabs.Onyx.FounderSnapshot:receipt-production"
    ) is None
    assert build._diagnostic_reference_from_windows_target(
        "CyryxLabs.Onyx.Gemini:api-key"
    ) is None
    assert build._diagnostic_reference_from_windows_target(None) is None


def test_package_diagnostic_scope_deletes_only_created_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = SecretReference(
        "CyryxLabs.Onyx.FounderSnapshot",
        "receipt-111111111111111111111111",
        "previous",
    )
    created = SecretReference(
        "CyryxLabs.Onyx.FounderSnapshot",
        "receipt-222222222222222222222222",
        "created",
    )
    snapshots = iter(
        (
            frozenset({previous}),
            frozenset({previous, created}),
            frozenset({previous}),
        )
    )
    deleted: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        build,
        "_windows_diagnostic_credential_references",
        lambda: next(snapshots),
    )
    monkeypatch.setattr(
        build,
        "_delete_windows_smoke_credentials",
        lambda references: deleted.append(references),
    )

    with build._windows_package_diagnostic_credential_scope():
        pass

    assert deleted == [(created,)]


def test_package_diagnostic_scope_cleans_delta_when_gate_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = SecretReference(
        "Onyx.GovernanceV1.Smoke.0123456789abcdef01234567",
        "ledger-key",
        "created",
    )
    snapshots = iter(
        (frozenset(), frozenset({created}), frozenset())
    )
    deleted: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        build,
        "_windows_diagnostic_credential_references",
        lambda: next(snapshots),
    )
    monkeypatch.setattr(
        build,
        "_delete_windows_smoke_credentials",
        lambda references: deleted.append(references),
    )

    with pytest.raises(RuntimeError, match="gate failed"):
        with build._windows_package_diagnostic_credential_scope():
            raise RuntimeError("gate failed")

    assert deleted == [(created,)]
