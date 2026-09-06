from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_source_freeze_v1 import (
    AGGREGATE_CONTRACT,
    SourceFreezeVerificationError,
    verify_source_freeze,
)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "candidate"
    root.mkdir(parents=True)
    phase_path = root / "tests/fixtures/phase5_current_successor_transition_v51.json"
    release_path = root / "tests/fixtures/release_workflow_transition_v53.json"
    _write(
        phase_path,
        {
            "schema": "onyx.phase5-current-successor-transition.v51",
            "current_root_sha256": "a" * 64,
        },
    )
    _write(
        release_path,
        {
            "schema": "onyx.release-workflow-transition.v53",
            "current_root_sha256": "b" * 64,
        },
    )
    (root / "main.py").write_bytes(b"print('Onyx')\n")
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": _sha(path),
            }
        )
    aggregate = hashlib.sha256()
    for record in records:
        encoded = record["path"].encode()
        aggregate.update(len(encoded).to_bytes(8, "big"))
        aggregate.update(encoded)
        aggregate.update(record["size"].to_bytes(8, "big"))
        aggregate.update(bytes.fromhex(record["sha256"]))
    manifest = tmp_path / "freeze.json"
    _write(
        manifest,
        {
            "schema": "onyx.source-freeze.v1",
            "candidate": "ONYX-TEST-V53",
            "source_root": "C:\\source",
            "candidate_root": str(root.resolve()),
            "allowlist": {
                "directories": ["tests"],
                "files": ["main.py"],
                "excluded_segments": [],
                "excluded_prefixes": [],
                "secret_suffixes": [],
            },
            "git_state": {
                "head": "c" * 40,
                "branch": "master",
                "porcelain_v1_z_bytes": 0,
                "porcelain_v1_z_sha256": hashlib.sha256(b"").hexdigest(),
                "nul_record_count": 0,
                "clean": True,
            },
            "authority": {
                "phase5_v51": {
                    "path": phase_path.relative_to(root).as_posix(),
                    "sha256": _sha(phase_path),
                    "schema": "onyx.phase5-current-successor-transition.v51",
                    "current_root_sha256": "a" * 64,
                },
                "release_v53": {
                    "path": release_path.relative_to(root).as_posix(),
                    "sha256": _sha(release_path),
                    "schema": "onyx.release-workflow-transition.v53",
                    "current_root_sha256": "b" * 64,
                },
            },
            "file_count": len(records),
            "total_bytes": sum(record["size"] for record in records),
            "aggregate_contract": AGGREGATE_CONTRACT,
            "root_sha256": aggregate.hexdigest(),
            "files": records,
        },
    )
    return manifest, root


def test_verifier_authenticates_exact_freeze(tmp_path: Path) -> None:
    manifest, root = _fixture(tmp_path)
    result = verify_source_freeze(
        manifest_path=manifest,
        candidate_root=root,
        candidate_label="ONYX-TEST-V53",
    )
    assert result["verified"] is True
    assert result["file_count"] == 3


def test_verifier_rejects_tamper_and_extra_membership(tmp_path: Path) -> None:
    manifest, root = _fixture(tmp_path)
    (root / "main.py").write_bytes(b"tampered")
    with pytest.raises(SourceFreezeVerificationError, match="bytes drifted"):
        verify_source_freeze(
            manifest_path=manifest,
            candidate_root=root,
            candidate_label="ONYX-TEST-V53",
        )
    manifest, root = _fixture(tmp_path / "extra")
    (root / "unexpected.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(SourceFreezeVerificationError, match="membership drifted"):
        verify_source_freeze(
            manifest_path=manifest,
            candidate_root=root,
            candidate_label="ONYX-TEST-V53",
        )
