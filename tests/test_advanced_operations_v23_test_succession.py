import shutil
import json
from pathlib import Path

import pytest

from scripts import advanced_operations_v23_test_succession as route

ROOT = Path(__file__).resolve().parents[1]


def test_exact_unchanged_predecessor_and_successor():
    route.authenticate(ROOT)


@pytest.mark.parametrize("changed", route.BINDINGS)
def test_changed_authority_is_rejected(tmp_path, changed):
    for relative in route.BINDINGS:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    route.authenticate(tmp_path)
    with (tmp_path / changed).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(RuntimeError, match="succession bytes drifted"):
        route.authenticate(tmp_path)


def test_cached_success_does_not_hide_later_runtime_tampering(tmp_path):
    from scripts import verify_advanced_operations_source_acceptance_v24 as current

    manifest = json.loads((ROOT / current.MANIFEST_RELATIVE).read_text())
    paths = {*route.BINDINGS, current.MANIFEST_RELATIVE,
             *(row["path"] for row in manifest["files"])}
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    cached_passes = []
    def run_cached(*args):
        cached_passes.append(args)
    route.run_verified_successor(tmp_path, run_cached)
    with (tmp_path / "ui.py").open("ab") as stream:
        stream.write(b"\n# tampered after the first successful suite")
    with pytest.raises(current.AdvancedOperationsSourceAcceptanceV24Error,
                       match="source drifted: ui.py"):
        route.run_verified_successor(tmp_path, run_cached)
    assert len(cached_passes) == 1
