import shutil
from pathlib import Path

import pytest

from scripts import source_test_succession_v1 as succession

ROOT = Path(__file__).resolve().parents[1]


def test_closed_record_preserves_all_observed_predecessor_bindings():
    record = succession.load_record(ROOT)
    assert len({row["node"] for row in record["routes"]}) == 37
    assert {row["kind"] for row in record["routes"]} == {"release", "documentation", "hud"}
    assert all(row["successor"] != row["node"].split("::")[0] for row in record["routes"])


@pytest.mark.parametrize("changed", [succession.RECORD,
    "tests/test_current_capability_status_v1.py",
    "tests/fixtures/release_workflow_transition_v71.json",
    "tests/test_hud_conversation_successor_v48.py"])
def test_historical_and_current_test_tamper_is_not_hidden(tmp_path, changed):
    record = succession.load_record(ROOT)
    for relative in {succession.RECORD, *record["bindings"]}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    succession.load_record(tmp_path)
    with (tmp_path / changed).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(RuntimeError, match="succession .*drifted"):
        succession.load_record(tmp_path)


def test_current_source_is_verified_on_every_call_even_with_cached_tests(monkeypatch):
    from scripts import verify_release_workflow_v99 as current

    calls = []
    valid = [True]

    def verify(root):
        assert root == ROOT
        if not valid[0]:
            raise RuntimeError("runtime source drifted")
        return {"publishable": False, "formal_release_ready": False}

    monkeypatch.setattr(current, "verify_release_workflow_v99", verify)
    node = succession.load_record(ROOT)["routes"][0]["node"]
    succession.verify_and_run(node, ROOT, lambda *args: calls.append(args))
    valid[0] = False
    with pytest.raises(RuntimeError, match="runtime source drifted"):
        succession.verify_and_run(node, ROOT, lambda *args: calls.append(args))
    assert len(calls) == 1
