from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import pytest

from scripts import verify_capability_nexus_current_v1 as successor


ROOT = Path(__file__).resolve().parents[1]


def _manifest() -> dict[str, object]:
    return json.loads((ROOT / successor.MANIFEST).read_text(encoding="utf-8"))


def _copy_closure(destination: Path) -> Path:
    manifest = _manifest()
    paths = {
        successor.MANIFEST,
        *successor.PROJECTIONS,
        *(record["path"] for record in manifest["current_inputs"]),
        *(record["path"] for record in manifest["historical_tombstones"]),
    }
    for relative in paths:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    return destination


def test_successor_acceptance_binds_exact_current_and_historical_sets() -> None:
    assert successor.verify(ROOT) == {
        "acceptance_id": successor.ACCEPTANCE_ID,
        "catalog_count": 32,
        "current_inputs": 67,
        "current_root_sha256": successor.CURRENT_ROOT_SHA256,
        "historical_manifests": 32,
        "historical_root_sha256": successor.HISTORY_ROOT_SHA256,
        "historical_status": "superseded-immutable-evidence",
        "runtime_effect": "none",
    }


def test_independent_oracle_recomputes_both_roots_without_verifier_helpers() -> None:
    manifest = _manifest()
    current = hashlib.sha256(b"onyx.capability-nexus.current.v1\0")
    for record in manifest["current_inputs"]:
        current.update(f"{record['path']}\0{record['sha256']}\n".encode())
    history = hashlib.sha256(b"onyx.capability-nexus.history.v1\0")
    for record in manifest["historical_tombstones"]:
        history.update(
            (
                f"{record['version']}\0{record['path']}\0{record['sha256']}\0"
                f"{record['records']}\n"
            ).encode()
        )
    assert current.hexdigest() == manifest["current_root_sha256"]
    assert current.hexdigest() == successor.CURRENT_ROOT_SHA256
    assert history.hexdigest() == manifest["historical_root_sha256"]
    assert history.hexdigest() == successor.HISTORY_ROOT_SHA256


@pytest.mark.parametrize(
    "relative",
    (
        "core/capability_nexus_v1.py",
        "core/capability_nexus_v32.py",
        "core/permission_broker.py",
        "tests/test_capability_nexus_v1.py",
        "tests/test_capability_nexus_v32.py",
        "docs/onyx/adrs/ADR-0003-capability-nexus-and-mcp.md",
        "docs/onyx/acceptance/VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001.md",
    ),
)
def test_current_input_tamper_fails_closed(tmp_path: Path, relative: str) -> None:
    project = _copy_closure(tmp_path)
    with (project / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(successor.CapabilityNexusCurrentV1Error, match="input drifted"):
        successor.verify(project)


@pytest.mark.parametrize("version", (1, 16, 32))
def test_historical_manifest_tamper_fails_closed(tmp_path: Path, version: int) -> None:
    project = _copy_closure(tmp_path)
    relative = (
        f"docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V{version}-001.sha256"
    )
    with (project / relative).open("ab") as handle:
        handle.write(b"tamper")
    with pytest.raises(
        successor.CapabilityNexusCurrentV1Error,
        match="historical manifest drifted",
    ):
        successor.verify(project)


def test_historical_embedded_digests_are_never_rebound_to_live_bytes(
    tmp_path: Path,
) -> None:
    project = _copy_closure(tmp_path)
    historical_live_path = project / "main.py"
    historical_live_path.parent.mkdir(parents=True, exist_ok=True)
    historical_live_path.write_bytes(b"deliberately-not-a-historical-byte-match")
    assert successor.verify(project)["historical_status"] == (
        "superseded-immutable-evidence"
    )


def test_unmanifested_catalog_successor_fails_closed(tmp_path: Path) -> None:
    project = _copy_closure(tmp_path)
    (project / "core/capability_nexus_v33.py").write_text(
        "# unreviewed catalog expansion\n",
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(
        successor.CapabilityNexusCurrentV1Error,
        match="unmanifested current catalog file",
    ):
        successor.verify(project)


@pytest.mark.parametrize("relative", successor.PROJECTIONS)
def test_every_mutable_projection_must_point_to_successor(
    tmp_path: Path,
    relative: str,
) -> None:
    project = _copy_closure(tmp_path)
    (project / relative).write_bytes(b"projection removed\n")
    with pytest.raises(
        successor.CapabilityNexusCurrentV1Error,
        match="omits current successor",
    ):
        successor.verify(project)


def test_frozen_v32_acceptance_is_tombstoned_and_current_gate_is_collected() -> None:
    conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    collection = (ROOT / "scripts/verify_v19_pytest_collection.py").read_text(
        encoding="utf-8"
    )
    assert '"test_capability_nexus_v32_acceptance.py"' in conftest
    assert "_SUPERSEDED_CAPABILITY_NEXUS_ACCEPTANCE_TESTS" in conftest
    assert '"tests/test_capability_nexus_current_v1.py"' in collection


def test_verifier_is_evidence_only_and_no_runtime_source_imports_it() -> None:
    needle = "verify_capability_nexus_current_v1"
    runtime_sources = [
        ROOT / "main.py",
        ROOT / "ui.py",
        *sorted((ROOT / "core").glob("*.py")),
    ]
    assert all(needle not in path.read_text(encoding="utf-8") for path in runtime_sources)
