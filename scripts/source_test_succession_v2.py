"""Closed V100 succession with real current positive and negative coverage.

V1 source/HUD registries remain immutable predecessor records. This successor
re-authenticates their bindings and current source on every invocation, before
consulting the process-local suite cache. No wildcard routes or exclusions.
"""

import hashlib
import json
from pathlib import Path
import re

from scripts import source_test_succession_v1 as previous_source
from scripts import hud_test_succession_v1 as previous_hud
from scripts.hud_test_succession_v1 import _file

RECORD = "tests/fixtures/source_test_succession_v2.json"
RECORD_SHA256 = "4812751922b68d5b242d31a37af60d1bce258e332718d358e7cf3e586025cfe3"
HELPER = "scripts/source_test_succession_v2.py"
TEST = "tests/test_source_test_succession_v2.py"
ROUTE_COUNT = 122


def replace_collected_item(item, callback):
    """Keep exact identity and current autouse fixtures, not obsolete inputs.

    Setting item.obj alone leaves its original fixture dependency graph intact.
    A V99 source-copy fixture would then fail before the V100 negative suite.
    The replacement executes the authenticated successor; it is never a skip.
    """
    import pytest

    replacement = pytest.Function.from_parent(
        item.parent, name=item.name, callobj=callback,
    )
    if replacement.nodeid != item.nodeid:
        raise RuntimeError("succession changed the collected node identity")
    return replacement


def load_record(root: Path) -> dict:
    if re.fullmatch(r"[a-f0-9]{64}", RECORD_SHA256) is None:
        raise RuntimeError("V100 test succession registry is unsealed")
    root = Path(root).absolute()
    raw = _file(root, RECORD).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise RuntimeError("V100 test succession record drifted")
    record = json.loads(raw)
    if (record["schema"] != "onyx.source-test-succession.v2"
            or record["release"] != 100
            or record["disposition"] != "superseded-not-rebound"
            or len(record["routes"]) != ROUTE_COUNT):
        raise RuntimeError("V100 test succession shape drifted")
    expected_predecessors = [
        {"path": previous_source.RECORD, "sha256": previous_source.RECORD_SHA256},
        {"path": previous_hud.RECORD, "sha256": previous_hud.RECORD_SHA256},
    ]
    if record["predecessors"] != expected_predecessors:
        raise RuntimeError("V100 test succession predecessor drifted")
    inherited = (previous_source.load_record(root), previous_hud.load_record(root))
    nodes = {row["node"] for row in record["routes"]}
    if len(nodes) != ROUTE_COUNT:
        raise RuntimeError("V100 test succession has duplicate nodes")
    for predecessor in inherited:
        if not {row["node"] for row in predecessor["routes"]}.issubset(nodes):
            raise RuntimeError("V100 test succession dropped an inherited route")
        for relative, digest in predecessor["bindings"].items():
            if record["bindings"].get(relative) != digest:
                raise RuntimeError("V100 test succession rebound inherited bytes")
    for row in record["routes"]:
        if (row["kind"] not in {"release", "hud", "documentation", "links", "staged", "smoke"}
                or not 1 <= len(row["successors"]) <= 2
                or row["node"].split("::", 1)[0] not in record["bindings"]):
            raise RuntimeError("V100 test succession route is invalid")
        for successor in row["successors"]:
            if successor.split("::", 1)[0] not in record["bindings"]:
                raise RuntimeError("V100 test succession has an unbound successor")
            if successor in nodes or successor.split("::", 1)[0] in {
                node.split("::", 1)[0] for node in nodes
            }:
                raise RuntimeError("V100 test succession cycle")
    for relative, digest in record["bindings"].items():
        if hashlib.sha256(_file(root, relative).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"V100 test succession binding drifted: {relative}")
    return record


def verify_and_run(nodeid: str, root: Path, run_suite) -> dict:
    from core.onyx_hud_current_acceptance_v48 import verify_current_hud_acceptance
    from core.onyx_packaged_runtime_hud_contract_v17 import verify_packaged_runtime_hud_contract
    from scripts.verify_release_workflow_v100 import verify_release_workflow_v100

    record = load_record(root)
    route = next((row for row in record["routes"] if row["node"] == nodeid), None)
    if route is None:
        raise RuntimeError("unregistered V100 test succession node")
    current = verify_release_workflow_v100(root)
    if (current["publishable"] is not False or current["formal_release_ready"] is not False
            or current["transition"]["logical_sequence"] != 100):
        raise RuntimeError("V100 test succession cannot grant live or release authority")
    bound = {row["path"]: row["sha256"] for row in current["transition"]["current_release_paths"]}
    for relative in {*record["bindings"], RECORD, HELPER, TEST}:
        if bound.get(relative) != hashlib.sha256(_file(root, relative).read_bytes()).hexdigest():
            raise RuntimeError(f"V100 omits or mismatches succession input: {relative}")
    hud = verify_current_hud_acceptance(root)
    package = verify_packaged_runtime_hud_contract(root)
    if hud["primary_layout_changed"] is not False or package["formal_release_ready"] is not False:
        raise RuntimeError("V100 succession changed the visual or release boundary")
    run_suite("v100-" + route["kind"], tuple(route["successors"]))
    return {"node": nodeid, "disposition": record["disposition"], "publishable": False}
