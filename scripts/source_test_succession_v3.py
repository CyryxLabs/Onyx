"""V101 succession preserving failed V100 qualification and every old binding."""

import hashlib
import json
from pathlib import Path
import re

from scripts import source_test_succession_v2 as previous
from scripts.hud_test_succession_v1 import _file
from scripts.source_test_succession_v2 import replace_collected_item  # noqa: F401

RECORD = "tests/fixtures/source_test_succession_v3.json"
RECORD_SHA256 = "f052b5f549a95b1b04f98941dd15d5ce956a7a0d6feff122d8f967f6cdd57be7"
HELPER = "scripts/source_test_succession_v3.py"
TEST = "tests/test_source_test_succession_v3.py"
ROUTE_COUNT = 208


def load_record(root: Path) -> dict:
    if re.fullmatch(r"[a-f0-9]{64}", RECORD_SHA256) is None:
        raise RuntimeError("V101 test succession registry is unsealed")
    root = Path(root).absolute()
    raw = _file(root, RECORD).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise RuntimeError("V101 test succession record drifted")
    record = json.loads(raw)
    if (record["schema"] != "onyx.source-test-succession.v3"
            or record["release"] != 101
            or record["disposition"] != "superseded-not-rebound"
            or len(record["routes"]) != ROUTE_COUNT
            or record["predecessor"] != {"path": previous.RECORD, "sha256": previous.RECORD_SHA256}):
        raise RuntimeError("V101 test succession shape drifted")
    inherited = previous.load_record(root)
    nodes = {row["node"] for row in record["routes"]}
    if len(nodes) != ROUTE_COUNT or not {row["node"] for row in inherited["routes"]}.issubset(nodes):
        raise RuntimeError("V101 test succession dropped or duplicated routes")
    for relative, digest in inherited["bindings"].items():
        if record["bindings"].get(relative) != digest:
            raise RuntimeError("V101 test succession rebound inherited bytes")
    origin_files = {node.split("::", 1)[0] for node in nodes}
    for row in record["routes"]:
        if (row["kind"] not in {"release", "hud", "documentation", "links", "staged", "smoke"}
                or not 1 <= len(row["successors"]) <= 2
                or row["node"].split("::", 1)[0] not in record["bindings"]):
            raise RuntimeError("V101 test succession route is invalid")
        for successor in row["successors"]:
            if successor.split("::", 1)[0] not in record["bindings"]:
                raise RuntimeError("V101 test succession has an unbound successor")
            if successor.split("::", 1)[0] in origin_files:
                raise RuntimeError("V101 test succession cycle")
    for relative, digest in record["bindings"].items():
        if hashlib.sha256(_file(root, relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"V101 test succession binding drifted: {relative}")
    return record


def verify_and_run(nodeid: str, root: Path, run_suite) -> dict:
    from core.onyx_hud_current_acceptance_v48 import verify_current_hud_acceptance
    from core.onyx_packaged_runtime_hud_contract_v17 import verify_packaged_runtime_hud_contract
    from scripts.verify_release_workflow_v101 import verify_release_workflow_v101

    record = load_record(root)
    route = next((row for row in record["routes"] if row["node"] == nodeid), None)
    if route is None:
        raise RuntimeError("unregistered V101 test succession node")
    current = verify_release_workflow_v101(root)
    if (current["publishable"] is not False or current["formal_release_ready"] is not False
            or current["transition"]["logical_sequence"] != 101):
        raise RuntimeError("V101 test succession cannot grant live or release authority")
    bound = {row["path"]: row["sha256"] for row in current["transition"]["current_release_paths"]}
    for relative in {*record["bindings"], RECORD, HELPER, TEST}:
        if bound.get(relative) != hashlib.sha256(_file(root, relative).read_bytes()).hexdigest():
            raise RuntimeError(f"V101 omits or mismatches succession input: {relative}")
    hud = verify_current_hud_acceptance(root)
    package = verify_packaged_runtime_hud_contract(root)
    if hud["primary_layout_changed"] is not False or package["formal_release_ready"] is not False:
        raise RuntimeError("V101 succession changed the visual or release boundary")
    run_suite("v101-" + route["kind"], tuple(route["successors"]))
    return {"node": nodeid, "disposition": record["disposition"], "publishable": False}
