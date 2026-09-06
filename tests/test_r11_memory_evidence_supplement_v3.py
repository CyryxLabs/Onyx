import hashlib
import shutil

import pytest

from scripts import r11_memory_evidence_supplement_v3 as supplement


@pytest.mark.parametrize("relative", supplement.EDGES)
def test_exact_bytes_match_preexisting_manifest_edge(relative):
    digest, _ = supplement.EDGES[relative]
    assert hashlib.sha256(supplement.read_evidence(relative, digest)).hexdigest() == digest


def test_wrong_requested_edge_is_rejected():
    with pytest.raises(RuntimeError, match="edge drifted"):
        supplement.read_memory_evidence("0" * 64)


def test_tamper_after_success_is_rejected(tmp_path):
    target = tmp_path / supplement.SNAPSHOT
    target.parent.mkdir(parents=True)
    shutil.copyfile(supplement.PROJECT / supplement.SNAPSHOT, target)
    supplement.read_memory_evidence(supplement.EXPECTED, tmp_path)
    with target.open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(RuntimeError, match="digest drifted"):
        supplement.read_memory_evidence(supplement.EXPECTED, tmp_path)


def test_unrelated_path_uses_original_verifier_and_restore(monkeypatch):
    calls = []

    def original(path, digest):
        calls.append((path, digest))
        raise ValueError("unrelated historical drift")

    monkeypatch.setattr(supplement.predecessor, "_historical_head_file", original)
    restore = supplement.install()
    try:
        assert supplement.predecessor._historical_head_file(supplement.RELATIVE, supplement.EXPECTED)
        with pytest.raises(ValueError, match="unrelated historical drift"):
            supplement.predecessor._historical_head_file("other.py", "bad")
    finally:
        restore()
    assert calls == [("other.py", "bad")]
    assert supplement.predecessor._historical_head_file is original
