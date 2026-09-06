"""Two observed historical positive assertions succeeded by HUD48/package17.

No pytest hooks, exclusions or fixture replacement live here. The parent wires
only registered node IDs to verify_and_run. Negative/staging tests remain intact.
load_record authenticates immutable bindings without requiring a sealed V99,
so the parent generator can include them without a circular seal dependency.
Every dispatch verifies real HUD48, package17 and V99 before calling the suite
runner, even when that runner already cached a passing or failing result.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath


RECORD = "tests/fixtures/hud_test_succession_v1.json"
RECORD_SHA256 = "898e0505057c77ffd95c48cec3f562f196ae65f9399e907130e0c66124b25592"
HELPER = "scripts/hud_test_succession_v1.py"
TESTS = "tests/test_hud_test_succession_v1.py"
SUCCESSOR = "tests/test_hud_conversation_successor_v48.py"
CLAIM_ID = "hud36-package5-to-hud48-package17-source99"
NODES = (
    "tests/test_onyx_hud_current_acceptance_v36.py::test_v36_authenticates_living_liquid_metal_without_palette_change",
    "tests/test_packaged_runtime_hud_contract_v5.py::test_packaged_v5_authenticates_liquid_metal_runtime",
)
RETAINED_NODES = (
    "tests/test_onyx_hud_current_acceptance_v36.py::test_v36_rejects_manifest_tamper",
    "tests/test_packaged_runtime_hud_contract_v5.py::test_package_hygiene_includes_every_liquid_metal_runtime_file",
)


class HudTestSuccessionError(RuntimeError):
    """Historical bindings or current successor authority failed closed."""


def _file(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if (
        pure.is_absolute()
        or pure.as_posix() != relative
        or "\\" in relative
        or ":" in relative
        or any(part in {".", ".."} for part in pure.parts)
    ):
        raise HudTestSuccessionError("HUD succession binding path is invalid")
    path = root.joinpath(*pure.parts)
    try:
        for candidate in (*reversed(path.parents), path):
            info = candidate.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise HudTestSuccessionError("HUD succession binding path is linked")
        if not stat.S_ISREG(info.st_mode):
            raise HudTestSuccessionError("HUD succession binding is not a file")
    except OSError as exc:
        raise HudTestSuccessionError("HUD succession binding unavailable") from exc
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_record(root: Path) -> dict:
    """Authenticate the closed registry and all 11 pinned source bindings fresh."""
    root = Path(root).absolute()
    raw = _file(root, RECORD).read_bytes()
    if hashlib.sha256(raw).hexdigest() != RECORD_SHA256:
        raise HudTestSuccessionError("HUD succession record digest drifted")
    record = json.loads(raw)
    if (
        record["schema"] != "onyx.hud-test-succession.v1"
        or record["disposition"] != "superseded-not-rebound"
        or record["release"] != 99
        or tuple(row["node"] for row in record["routes"]) != NODES
        or tuple(record["retained_nodes"]) != RETAINED_NODES
        or any(row["successor"] != SUCCESSOR for row in record["routes"])
        or len(record["bindings"]) != 11
    ):
        raise HudTestSuccessionError("HUD succession closed mapping drifted")
    for relative, expected in record["bindings"].items():
        if (
            re.fullmatch(r"[0-9a-f]{64}", expected) is None
            or _sha(_file(root, relative)) != expected
        ):
            raise HudTestSuccessionError(f"HUD succession binding drifted: {relative}")
    for route in record["routes"]:
        manifest = json.loads(_file(root, route["historical_manifest"]).read_bytes())
        # Preserve the original spec digest as historical evidence, never bind
        # it to today's packaging source to force an old verifier to succeed.
        if record["historical_input"] not in manifest["runtime_inputs"]:
            raise HudTestSuccessionError("HUD historical input binding drifted")
    return record


def registered_test_ids(root: Path) -> frozenset[str]:
    return frozenset(row["node"] for row in load_record(root)["routes"])


def require_registered_tests_collected(nodeids, collected_sources, root: Path) -> None:
    """Parent supplies sources selected as whole files, excluding direct nodes."""
    missing = {
        node
        for node in registered_test_ids(root)
        if node.split("::", 1)[0] in collected_sources and node not in nodeids
    }
    if missing:
        raise HudTestSuccessionError(
            f"registered HUD succession nodes missing: {sorted(missing)}"
        )


def verify_and_run(nodeid: str, root: Path, run_suite) -> dict:
    """Validate old bindings and all live authorities before touching suite cache.

    run_suite(claim_id, paths) must execute the closed successor suite or return
    its process-local cached result, propagating failures. It must not translate
    this source-only route into installation, publication, or live acceptance.
    """
    root = Path(root).absolute()
    record = load_record(root)
    if nodeid not in NODES:
        raise HudTestSuccessionError("unregistered HUD succession node")
    if not callable(run_suite):
        raise HudTestSuccessionError("HUD successor suite runner is required")
    old = record["historical_input"]
    if _sha(_file(root, old["path"])) == old["sha256"]:
        raise HudTestSuccessionError(
            "observed historical packaging divergence disappeared"
        )

    from core import onyx_hud_current_acceptance_v48 as hud
    from core import onyx_packaged_runtime_hud_contract_v17 as packaged
    from scripts.verify_release_workflow_v99 import verify_release_workflow_v99

    current_hud = hud.verify_current_hud_acceptance(root)
    current_package = packaged.verify_packaged_runtime_hud_contract(root)
    current_source = verify_release_workflow_v99(root)
    if (
        current_hud["published"] is not False
        or current_hud["primary_layout_changed"] is not False
        or current_hud["live_renderer"] != "three.js-webgl"
        or current_package["schema"] != "onyx.packaged-runtime-hud-contract.v17"
        or current_package["formal_release_ready"] is not False
        or current_source["publishable"] is not False
        or current_source["formal_release_ready"] is not False
        or current_source["transition"]["logical_sequence"] != 99
    ):
        raise HudTestSuccessionError(
            "HUD succession cannot grant release or live authority"
        )
    # Require the parent to include this additive helper, registry, tests and all
    # pinned bindings in V99. Neither V99 nor its own verifier is pinned here.
    release_bindings = {
        row["path"]: row["sha256"]
        for row in current_source["transition"]["current_release_paths"]
    }
    for relative in {*record["bindings"], RECORD, HELPER, TESTS}:
        if release_bindings.get(relative) != _sha(_file(root, relative)):
            raise HudTestSuccessionError(
                f"V99 omits or mismatches HUD succession source: {relative}"
            )
    run_suite(CLAIM_ID, (SUCCESSOR,))
    return {
        "node": nodeid,
        "disposition": record["disposition"],
        "successor": SUCCESSOR,
        "publishable": False,
        "formal_release_ready": False,
    }
