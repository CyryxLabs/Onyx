"""Closed observed stale-source claims routed to current, tested V99 authority.

Thirty-seven node IDs are explicit; no filename wildcard, skip, fabricated
historical bytes or digest substitution. The original 61 bindings stay exact.
Every invocation authenticates current source before consulting a suite cache.
"""

import hashlib
import json
from pathlib import Path

RECORD = "tests/fixtures/source_test_succession_v1.json"
RECORD_SHA256 = "215fcc1393df42935629df10070239f66818811becbf98d3b70213b42a4e7e07"


def load_record(root: Path):
    path = root / RECORD
    if path.is_symlink() or path.resolve(strict=True) != path.absolute():
        raise RuntimeError("source test succession record path drifted")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise RuntimeError("source test succession record drifted")
    record = json.loads(raw)
    if (record["schema"] != "onyx.source-test-succession.v1"
            or record["disposition"] != "superseded-not-rebound"
            or record["release"] != 99 or len(record["routes"]) != 37
            or len(record["bindings"]) != 61):
        raise RuntimeError("source test succession shape drifted")
    for relative, digest in record["bindings"].items():
        target = root / relative
        if target.is_symlink() or target.resolve(strict=True) != target.absolute():
            raise RuntimeError(f"source test succession binding path drifted: {relative}")
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError(f"source test succession binding drifted: {relative}")
    return record


def verify_and_run(nodeid: str, root: Path, run_suite):
    from scripts.verify_release_workflow_v99 import verify_release_workflow_v99

    record = load_record(root)
    route = next((row for row in record["routes"] if row["node"] == nodeid), None)
    if route is None:
        raise RuntimeError("unregistered source test succession node")
    current = verify_release_workflow_v99(root)
    if current["publishable"] is not False or current["formal_release_ready"] is not False:
        raise RuntimeError("source-only succession cannot grant public release")
    run_suite("source-succession-" + route["kind"], (route["successor"],))
