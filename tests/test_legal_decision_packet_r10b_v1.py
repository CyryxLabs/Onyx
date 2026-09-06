from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_legal_decision_packet_r10b_v1 import (
    LegalDecisionPacketError,
    PACKET_RELATIVE,
    verify_legal_decision_packet,
)


ROOT = Path(__file__).resolve().parents[1]


def _packet() -> dict[str, object]:
    return json.loads((ROOT / PACKET_RELATIVE).read_text(encoding="utf-8"))


def _write_packet(tmp_path: Path, value: dict[str, object]) -> Path:
    path = tmp_path / "packet.json"
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")
    return path


def test_real_r10b_engineering_packet_passes_without_widening_release() -> None:
    result = verify_legal_decision_packet(ROOT)
    assert result["tag_bound_engineering_candidates"] == 7
    assert result["substantively_unresolved"] == 1
    assert result["legally_approved"] == 0
    assert result["legal_approval_granted"] is False
    assert result["public_release_eligible"] is False


def test_packet_cannot_self_approve(tmp_path: Path) -> None:
    packet = _packet()
    packet["legal_approval_granted"] = True
    with pytest.raises(LegalDecisionPacketError, match="widened into approval"):
        verify_legal_decision_packet(
            ROOT,
            packet_path=_write_packet(tmp_path, packet),
        )


def test_raw_exact_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    packet = _packet()
    candidates = packet["tag_bound_candidates"]
    assert isinstance(candidates, list)
    evidence = candidates[0]["license_files"][0]
    evidence["shipped_sha256"] = "0" * 64
    with pytest.raises(LegalDecisionPacketError, match="raw comparison is not exact"):
        verify_legal_decision_packet(
            ROOT,
            packet_path=_write_packet(tmp_path, packet),
        )
