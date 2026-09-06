from __future__ import annotations

from pathlib import Path

import pytest

from scripts.verify_current_release_docs_r15b import (
    CurrentReleaseDocumentationError,
    FORBIDDEN_CURRENT,
    REQUIRED,
    verify_current_release_docs,
)


def _fixture(tmp_path: Path) -> Path:
    for name, literals in REQUIRED.items():
        (tmp_path / name).write_text("\n".join(literals) + "\n", encoding="utf-8")
    (tmp_path / "LEGAL_RELEASE_APPROVAL_1.1.9.md").write_text(
        "R10B\nOWNER_OR_LEGAL_APPROVAL_REQUIRED\nDecision:\n",
        encoding="utf-8",
    )
    return tmp_path


def test_current_release_documentation_contract_passes(tmp_path: Path) -> None:
    report = verify_current_release_docs(_fixture(tmp_path))
    assert report["status"] == "passed_r15b_current_authority"
    assert report["public_release_eligible"] is False
    assert set(report["document_sha256"]) == set(REQUIRED) | {
        "LEGAL_RELEASE_APPROVAL_1.1.9.md"
    }


def test_current_release_documentation_contract_rejects_stale_literal(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    name, literals = next(iter(FORBIDDEN_CURRENT.items()))
    with (root / name).open("a", encoding="utf-8") as stream:
        stream.write(literals[0] + "\n")
    with pytest.raises(CurrentReleaseDocumentationError, match="stale current"):
        verify_current_release_docs(root)


def test_current_release_documentation_contract_rejects_false_legal_approval(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    with (root / "LEGAL_RELEASE_APPROVAL_1.1.9.md").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write("Decision: `APPROVED`\n")
    with pytest.raises(CurrentReleaseDocumentationError, match="unexpectedly claims"):
        verify_current_release_docs(root)
