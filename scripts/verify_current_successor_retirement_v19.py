"""Authenticate the additive V59 HUD-authority retirement over immutable V18."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import verify_current_successor_retirement_v18 as predecessor


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V19.json"
PREDECESSOR_SHA256 = "5eb69ec483bbb978ffeadb676717e948accc62042a0f877fd6a169f2c4f6f517"
RECORD_SHA256 = "98bb577a70761fac13840704368c52bb5bed592f70653afb196b336f562ca0e6"
V18_REGISTERED_ROUTES = 376
CURRENT_EXTENSION_RECORD_V14_SHA256 = predecessor.CURRENT_EXTENSION_RECORD_V14_SHA256


class CurrentSuccessorRetirementV19Error(RuntimeError):
    """V19, V18, or a V59 successor binding failed closed."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_relative_file(root: Path, relative: object, label: str) -> Path:
    parsed = PurePosixPath(relative) if type(relative) is str else PurePosixPath("..")
    if parsed.is_absolute() or parsed.as_posix() != relative or any(part in {"", ".", ".."} for part in parsed.parts):
        raise CurrentSuccessorRetirementV19Error(f"{label} path is invalid")
    path = root.joinpath(*parsed.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise CurrentSuccessorRetirementV19Error(f"{label} path is invalid") from error
    if path.is_symlink() or resolved != path.absolute() or not resolved.is_file():
        raise CurrentSuccessorRetirementV19Error(f"{label} path is invalid")
    return resolved


def _claim(root: Path, raw: bytes, expected_digest: str) -> dict[str, object]:
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise CurrentSuccessorRetirementV19Error("retirement V19 digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise CurrentSuccessorRetirementV19Error("retirement V19 is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise CurrentSuccessorRetirementV19Error("retirement V19 is invalid") from error
    expected_nodes = [
        "tests/test_native_release_gate_v1.py::test_pyinstaller_input_discovery_covers_entrypoints_and_resources",
        "tests/test_onyx_hud_orb_v7_candidate.py::test_v7_one_widget_projection_and_exact_v6_rollback",
        "tests/test_onyx_hud_orb_v8_candidate.py::test_module_does_not_enable_itself_or_edit_v7",
        "tests/test_onyx_hud_orb_v8_candidate.py::test_v8_one_widget_projection_and_exact_v7_rollback",
        "tests/test_onyx_hud_orb_v8_candidate.py::test_voice_layer_has_speaking_only_governed_motion",
    ]
    if (
        type(record) is not dict
        or set(record) != {"schema", "issued_at", "predecessor", "policy", "additional_claims"}
        or record.get("schema") != "onyx.current-successor-retirement.v19"
        or record.get("predecessor") != {
            "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V18.json",
            "sha256": PREDECESSOR_SHA256,
        }
        or type(record.get("additional_claims")) is not list
        or len(record["additional_claims"]) != 1
    ):
        raise CurrentSuccessorRetirementV19Error("retirement V19 contract drifted")
    claim = record["additional_claims"][0]
    if (
        type(claim) is not dict
        or set(claim) != {"id", "disposition", "historical_test_ids", "successor_tests", "validated_tests", "reason"}
        or claim.get("id") != "hud-v58-to-v59-current-authority"
        or claim.get("disposition") != "superseded-not-rebound"
        or claim.get("historical_test_ids") != expected_nodes
        or claim.get("validated_tests") != len(expected_nodes)
        or type(claim.get("reason")) is not str
        or not claim["reason"]
        or type(claim.get("successor_tests")) is not list
        or len(claim["successor_tests"]) != 3
    ):
        raise CurrentSuccessorRetirementV19Error("retirement V19 claim drifted")
    for binding in claim["successor_tests"]:
        if type(binding) is not dict or set(binding) != {"path", "sha256"}:
            raise CurrentSuccessorRetirementV19Error("retirement V19 successor is malformed")
        successor = _strict_relative_file(root, binding["path"], "retirement V19 successor")
        if _sha256(successor) != binding["sha256"]:
            raise CurrentSuccessorRetirementV19Error("retirement V19 successor drifted")
    return claim


def _current_claims(project: Path = PROJECT) -> tuple[dict[str, object], ...]:
    root = Path(project).resolve(strict=True)
    predecessor_path = _strict_relative_file(
        root, "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V18.json", "retirement V18 predecessor"
    )
    if _sha256(predecessor_path) != PREDECESSOR_SHA256:
        raise CurrentSuccessorRetirementV19Error("retirement V18 predecessor drifted")
    predecessor_claims = predecessor._current_claims(root)
    if len(predecessor.registered_test_ids(root)) != V18_REGISTERED_ROUTES:
        raise CurrentSuccessorRetirementV19Error("retirement V18 routes drifted")
    return (_claim(root, (root / RECORD.relative_to(PROJECT)).read_bytes(), RECORD_SHA256),) + tuple(predecessor_claims)


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(node for claim in _current_claims(project) for node in claim["historical_test_ids"])


def claim_for_test(nodeid: str, project: Path = PROJECT) -> dict[str, object]:
    for claim in _current_claims(project):
        if nodeid in claim["historical_test_ids"]:
            return claim
    raise CurrentSuccessorRetirementV19Error(f"unregistered historical test: {nodeid}")


if __name__ == "__main__":
    claims = _current_claims()
    print("CURRENT_SUCCESSOR_RETIREMENT_V19_OK", f"claims={len(claims)}", f"tests={len(registered_test_ids())}")
