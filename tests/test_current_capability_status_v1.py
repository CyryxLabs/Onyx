from pathlib import Path

from core.version import __version__


ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.10"
STATUS = ROOT / "docs" / "onyx" / "CURRENT_CAPABILITY_STATUS_V1.md"
HISTORICAL_STATUS = ROOT / "docs" / "onyx" / "CURRENT_RELEASE_STATUS.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_current_version_claims_agree_across_runtime_and_current_docs() -> None:
    readme = _text(ROOT / "readme.md")
    installation = _text(ROOT / "docs" / "INSTALLATION.md")
    status = _text(STATUS)

    assert __version__ == VERSION
    assert f"current engineering candidate is **Onyx {VERSION}**" in readme
    assert f"current engineering candidate is **Onyx {VERSION}**" in installation
    assert f"Current candidate: **Onyx {VERSION} Windows x64 engineering candidate**" in status
    assert f"build_release.py --version {VERSION}" in readme
    assert f"build_release.py --version {VERSION}" in installation


def test_candidate_matrix_separates_every_required_evidence_layer() -> None:
    status = _text(STATUS)
    header = (
        "| Candidate | implemented | source-wired | host-wired | tested | "
        "packaged | installed | provider-tested | signed | released |"
    )
    row = (
        f"| Onyx {VERSION} Windows x64 | `YES` | `YES` | "
        "`YES_LOCAL_WINDOWS` | `YES_FOCUSED` | `YES_LOCAL_WINDOWS` | "
        "`YES_LOCAL_WINDOWS` | `UNVERIFIED` | `NO_UNSIGNED_UNTRUSTED` | `NO` |"
    )

    assert header in status
    assert row in status
    assert "109 passed + 230\n  subtests" in status


def test_unsigned_unreleased_and_provider_unverified_claims_are_cross_file() -> None:
    documents = (
        _text(ROOT / "readme.md"),
        _text(ROOT / "docs" / "INSTALLATION.md"),
        _text(STATUS),
    )

    for document in documents:
        folded = document.casefold()
        assert "unsigned-untrusted" in folded
        assert "not released" in folded
        assert "unverified" in folded


def test_1_1_9_release_status_is_referenced_only_as_historical_formal_no_go() -> None:
    current_documents = (
        _text(ROOT / "readme.md"),
        _text(ROOT / "docs" / "INSTALLATION.md"),
        _text(STATUS),
    )
    historical = _text(HISTORICAL_STATUS)

    for document in current_documents:
        assert "historical formal" in document.casefold()
        assert "1.1.9 R15B NO-GO" in document
    assert "Current installed product: **Onyx 1.1.9 Windows x64 R15B" in historical
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in historical
