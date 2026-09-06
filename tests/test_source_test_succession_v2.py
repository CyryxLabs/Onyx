"""Exact routes and fresh admission; synthetic cache tests are not a release seal."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import source_test_succession_v2 as route

ROOT = Path(__file__).resolve().parents[1]


def test_replacement_rebuilds_explicit_fixtures_but_keeps_autouse_and_exact_node(tmp_path):
    # This tests pytest lifecycle only, not source admission. The production
    # callback independently authenticates V100 before executing real suites.
    (tmp_path / "conftest.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from scripts.source_test_succession_v2 import replace_collected_item\n"
        "def pytest_collection_modifyitems(items):\n"
        "    for i, item in enumerate(items):\n"
        "        if item.name.startswith('test_historical'):\n"
        "            def successor():\n"
        "                assert item.module.current_autouse_ready is True\n"
        "            items[i] = replace_collected_item(item, successor)\n",
        encoding="utf-8",
    )
    (tmp_path / "test_lifecycle.py").write_text(
        "import pytest\n"
        "current_autouse_ready = False\n"
        "@pytest.fixture(autouse=True)\n"
        "def current_session():\n"
        "    global current_autouse_ready\n"
        "    current_autouse_ready = True\n"
        "@pytest.fixture\n"
        "def stale_source():\n"
        "    pytest.fail('obsolete source fixture was executed')\n"
        "@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_historical(stale_source, value):\n"
        "    pytest.fail('historical body was executed')\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "--confcutdir", str(tmp_path), str(tmp_path)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_historical[1] PASSED" in result.stdout
    assert "test_historical[2] PASSED" in result.stdout


def test_unsealed_registry_cannot_read_or_admit(monkeypatch):
    monkeypatch.setattr(route, "RECORD_SHA256", "UNSEALED")
    monkeypatch.setattr(route, "_file", lambda *a: pytest.fail("unsealed registry read source"))
    with pytest.raises(RuntimeError, match="registry is unsealed"):
        route.load_record(ROOT)


def test_closed_routes_preserve_inheritance_and_specific_negative_coverage():
    record = route.load_record(ROOT)
    rows = {row["node"]: row for row in record["routes"]}
    assert len(rows) == 122
    broker = rows["tests/test_onyx_hud_current_acceptance_v33.py::test_v33_rejects_linked_runtime_input"]
    assert broker["successors"] == [
        "tests/test_hud_linked_input_v1.py",
        "tests/test_release_workflow_transition_v100.py::test_rejects_linked_permission_broker",
    ]
    assert rows["tests/test_packaged_runtime_hud_contract_v4.py::test_packaged_v4_rejects_linked_runtime_input"]["successors"] == [
        "tests/test_staged_capability_source_v1.py"
    ]
    assert "tests/test_hud_conversation_successor_v48.py" not in {node.split("::")[0] for node in rows}


@pytest.mark.parametrize("changed", [route.RECORD,
    "tests/test_onyx_hud_current_acceptance_v33.py",
    "tests/test_release_workflow_transition_v99.py",
    "tests/test_hud_linked_input_v1.py",
    "tests/fixtures/hud_test_succession_v1.json"])
def test_registry_and_old_or_current_binding_tamper_rejected(tmp_path, changed):
    record = route.load_record(ROOT)
    for relative in {route.RECORD, *record["bindings"]}:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    route.load_record(tmp_path)
    with (tmp_path / changed).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(RuntimeError, match="drifted"):
        route.load_record(tmp_path)


def test_current_source_rechecked_before_cached_success(monkeypatch):
    from scripts import verify_release_workflow_v100 as source

    record = route.load_record(ROOT)
    paths = {*record["bindings"], route.RECORD, route.HELPER, route.TEST}
    current = {
        "publishable": False, "formal_release_ready": False,
        "transition": {"logical_sequence": 100, "current_release_paths": [
            {"path": path, "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest()}
            for path in sorted(paths)
        ]},
    }
    valid = [True]
    admissions = []
    def verify(root):
        assert root == ROOT
        if not valid[0]:
            raise RuntimeError("current source drifted")
        return current
    monkeypatch.setattr(source, "verify_release_workflow_v100", verify)
    node = record["routes"][0]["node"]
    route.verify_and_run(node, ROOT, lambda *args: admissions.append(args))
    valid[0] = False
    with pytest.raises(RuntimeError, match="current source drifted"):
        route.verify_and_run(node, ROOT, lambda *args: admissions.append(args))
    assert len(admissions) == 1
