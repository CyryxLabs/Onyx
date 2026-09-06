from pathlib import Path

from core.version import __version__

ROOT = Path(__file__).resolve().parents[1]


def test_current_candidate_matches_runtime_without_claiming_installation():
    for name in ("readme.md", "docs/INSTALLATION.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"current engineering candidate is **Onyx {__version__}**" in text
        assert "Onyx 1.1.31 / V96" in text
        assert "CURRENT_CAPABILITY_STATUS_V2.md" in text
        assert "source-only" in text
        assert f"build_release.py --version {__version__}" in text
        assert "unsigned-untrusted" in text and "not released" in text
    status = (ROOT / "docs/onyx/CURRENT_CAPABILITY_STATUS_V2.md").read_text()
    assert f"Current candidate: **Onyx {__version__} Windows x64 engineering candidate**" in status
    assert "| `NO` | `NO` | `UNVERIFIED` | `NO_UNSIGNED_UNTRUSTED` | `NO` |" in status
    assert "`PARTIAL`" in status and "FOCUSED_PASS_FULL_PENDING" in status


def test_predecessor_evidence_is_separate_and_retained():
    old = (ROOT / "docs/onyx/CURRENT_CAPABILITY_STATUS_V1.md").read_text()
    assert "Current candidate: **Onyx 1.1.10" in old
    assert "109 passed + 230\n  subtests" in old
    status = (ROOT / "docs/onyx/CURRENT_CAPABILITY_STATUS_V2.md").read_text()
    assert "1.1.9 R15B NO-GO" in status
    assert "POST_INSTALL_1_1_31_20260905.md" in status
