from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "onyx"


def test_r10b_is_the_current_documented_candidate() -> None:
    status = (DOCS / "CURRENT_RELEASE_STATUS.md").read_text(encoding="utf-8")
    index = (DOCS / "DOCUMENTATION_INDEX.md").read_text(encoding="utf-8")
    evidence = (DOCS / "FINAL_EVIDENCE_INDEX_1.1.9.md").read_text(
        encoding="utf-8"
    )

    assert "Current installed product: **Onyx 1.1.9 Windows x64 R10B" in status
    assert "Current frozen source: **V49 R10B, 2,769 files" in status
    assert "PASSED_UNSIGNED_WINDOWS_R10B_TECHNICAL" in status
    assert "publicReleaseEligible=false" in status
    assert "IN_PROGRESS_R10B_ATTEMPT3" in status
    assert "stale `in_progress` receipt is invalid as a pass" in status
    assert "DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md" in index
    assert "R10B WINDOWS LOCAL ACCEPTANCE PASSED" in evidence
    assert "long-session-r10b-attempt3" in evidence
    assert "Attempt 1 is invalid as a pass" in evidence
    assert "INCOMPLETE" in evidence


def test_r10b_legal_materials_remain_human_gated() -> None:
    worklist = (DOCS / "THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md").read_text(
        encoding="utf-8"
    )
    approval = (DOCS / "LEGAL_RELEASE_APPROVAL_1.1.9.md").read_text(
        encoding="utf-8"
    )

    assert "R10B TECHNICAL WORKLIST" in worklist
    assert "Shipped runtime distributions: 116" in worklist
    assert "`NOASSERTION` declaration | 8" in worklist
    assert "Candidate: Windows x64 R10B" in approval
    assert "Status: **approval required**" in approval
    assert "Decision: `APPROVED` or `REJECTED`" in approval


def test_stale_release_documents_route_directly_to_r10b_authority() -> None:
    stale = (
        DOCS / "ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-04.md",
        DOCS / "ONYX_PROJECT_COMPLETION_ROADMAP_V23_2026-08-04.md",
        DOCS / "ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md",
        DOCS / "operations/ONYX_1_1_9_V31_WINDOWS_ACCEPTANCE_2026-08-04.md",
        DOCS / "operations/ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md",
        DOCS / "operations/ONYX_1_1_9_V41_SBOM_RECONCILIATION_2026-08-10.md",
        DOCS / "operations/ONYX_1_1_9_V41_LINUX_BUILD_FAILURE_2026-08-10.md",
    )
    for path in stale:
        header = "\n".join(path.read_text(encoding="utf-8").splitlines()[:10])
        assert "SUPERSEDED FOR CURRENT-STATE CLAIMS" in header, path
        assert "CURRENT_RELEASE_STATUS.md" in header, path
        assert "DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md" in header, path

    registry = (DOCS / "DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md").read_text(
        encoding="utf-8"
    )
    assert "V41 Windows acceptance/SBOM records" in registry
