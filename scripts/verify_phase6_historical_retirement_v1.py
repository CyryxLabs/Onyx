"""Authenticate retired Phase 6 test nodes and their named successors."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable, Final


PROJECT: Final = Path(__file__).resolve().parents[1]
LEDGER: Final = "docs/onyx/checkpoints/PHASE6_HISTORICAL_RETIREMENT_V1.json"
LEDGER_SHA256: Final = (
    "2e500e1f0f0e7e251e13fc2fa22af372571d28be0a4ffbbc3ae695fabb495083"
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Phase6HistoricalRetirementV1Error(RuntimeError):
    """The authenticated retirement binding is invalid."""


def _relative(relative: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise Phase6HistoricalRetirementV1Error("retirement path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise Phase6HistoricalRetirementV1Error("retirement path is not canonical")
    return Path(*parsed.parts)


def _bytes(project: Path, relative: str) -> bytes:
    root = project.resolve(strict=True)
    path = (root / _relative(relative)).resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise Phase6HistoricalRetirementV1Error(
            f"retirement source escapes project: {relative}"
        ) from exc
    if not path.is_file():
        raise Phase6HistoricalRetirementV1Error(
            f"retirement source is not a file: {relative}"
        )
    return path.read_bytes()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_retirement_ledger(project: Path = PROJECT) -> dict[str, object]:
    raw = _bytes(Path(project), LEDGER)
    if _sha(raw) != LEDGER_SHA256:
        raise Phase6HistoricalRetirementV1Error("retirement ledger digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase6HistoricalRetirementV1Error("retirement ledger is not canonical")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase6HistoricalRetirementV1Error("retirement ledger is invalid") from exc
    if type(record) is not dict or set(record) != {
        "schema",
        "issued_at",
        "disposition",
        "policy",
        "counts",
        "successors",
        "sources",
        "retired_tests",
    }:
        raise Phase6HistoricalRetirementV1Error("retirement contract drifted")
    if (
        record["schema"] != "onyx.test.phase6-historical-retirement.v1"
        or record["disposition"] != "superseded-point-in-time-tests-not-rebound"
        or record["policy"]
        != {
            "current_successor_required": True,
            "historical_hashes_are_rebound_to_live_bytes": False,
            "historical_manifests_remain_immutable": True,
            "registered_nodes_must_remain_exactly_collectable": True,
        }
        or record["counts"]
        != {
            "retired_nodes": 45,
            "phase6_current_successor_nodes": 34,
            "capability_current_successor_nodes": 11,
            "source_files": 25,
        }
    ):
        raise Phase6HistoricalRetirementV1Error("retirement policy drifted")

    successors = record["successors"]
    expected_successors = {
        "phase6-current-v1": (
            "VE-PHASE6-CURRENT-V1-001",
            "scripts.verify_phase6_current_v1",
            "PHASE6_CURRENT_V1_ACCEPTANCE_OK",
        ),
        "capability-nexus-current-v1": (
            "VE-CAPABILITY-NEXUS-CURRENT-V1-E6-001",
            "scripts.verify_capability_nexus_current_v1",
            "CAPABILITY_NEXUS_CURRENT_V1_ACCEPTANCE_OK",
        ),
    }
    if type(successors) is not list or len(successors) != 2:
        raise Phase6HistoricalRetirementV1Error("successor set drifted")
    seen_successors: set[str] = set()
    for successor in successors:
        if type(successor) is not dict or set(successor) != {
            "id", "contract", "verifier", "marker"
        }:
            raise Phase6HistoricalRetirementV1Error("successor is malformed")
        identifier = successor["id"]
        expected = expected_successors.get(identifier)
        if expected is None or tuple(successor[key] for key in (
            "contract", "verifier", "marker"
        )) != expected or identifier in seen_successors:
            raise Phase6HistoricalRetirementV1Error("successor binding drifted")
        seen_successors.add(identifier)
    if seen_successors != set(expected_successors):
        raise Phase6HistoricalRetirementV1Error("successor closure drifted")

    sources = record["sources"]
    if type(sources) is not list or len(sources) != 25:
        raise Phase6HistoricalRetirementV1Error("retirement source set drifted")
    source_paths: list[str] = []
    for source in sources:
        if type(source) is not dict or set(source) != {"path", "sha256"}:
            raise Phase6HistoricalRetirementV1Error("retirement source is malformed")
        relative, expected = source["path"], source["sha256"]
        if (
            type(relative) is not str
            or type(expected) is not str
            or _HEX64.fullmatch(expected) is None
            or source_paths
            and relative <= source_paths[-1]
        ):
            raise Phase6HistoricalRetirementV1Error("retirement source is invalid")
        if _sha(_bytes(Path(project), relative)) != expected:
            raise Phase6HistoricalRetirementV1Error(
                f"retired test source drifted: {relative}"
            )
        source_paths.append(relative)

    retired = record["retired_tests"]
    if type(retired) is not list or len(retired) != 45:
        raise Phase6HistoricalRetirementV1Error("retired node set drifted")
    seen_nodes: set[str] = set()
    successor_counts = {name: 0 for name in expected_successors}
    for entry in retired:
        if type(entry) is not dict or set(entry) != {"id", "successor"}:
            raise Phase6HistoricalRetirementV1Error("retired node is malformed")
        nodeid, successor_id = entry["id"], entry["successor"]
        if (
            type(nodeid) is not str
            or nodeid.count("::") != 1
            or nodeid in seen_nodes
            or nodeid.split("::", 1)[0] not in source_paths
            or successor_id not in expected_successors
        ):
            raise Phase6HistoricalRetirementV1Error("retired node is invalid")
        seen_nodes.add(nodeid)
        successor_counts[successor_id] += 1
    if successor_counts != {
        "phase6-current-v1": 34,
        "capability-nexus-current-v1": 11,
    }:
        raise Phase6HistoricalRetirementV1Error("retired successor counts drifted")
    return record


def registered_test_ids(project: Path = PROJECT) -> frozenset[str]:
    return frozenset(
        entry["id"] for entry in load_retirement_ledger(project)["retired_tests"]
    )


def require_registered_tests_collected(
    collected_nodeids: Iterable[str],
    *,
    covered_sources: Iterable[str],
    project: Path = PROJECT,
) -> None:
    """Fail if a fully collected source silently loses a registered node."""

    collected = frozenset(collected_nodeids)
    sources = frozenset(covered_sources)
    required = {
        nodeid
        for nodeid in registered_test_ids(project)
        if nodeid.split("::", 1)[0] in sources
    }
    missing = sorted(required - collected)
    if missing:
        raise Phase6HistoricalRetirementV1Error(
            f"registered retired node is no longer collected: {missing}"
        )


def successor_binding(
    nodeid: str,
    *,
    successor_contract: str,
    successor_verifier: str,
    successor_marker: str,
    project: Path = PROJECT,
) -> dict[str, str]:
    """Authenticate one exact node-to-current-successor mapping."""

    ledger = load_retirement_ledger(project)
    matches = [entry for entry in ledger["retired_tests"] if entry["id"] == nodeid]
    if len(matches) != 1:
        raise Phase6HistoricalRetirementV1Error(
            f"test node lacks exact retirement: {nodeid}"
        )
    successor_id = matches[0]["successor"]
    successor = next(
        item for item in ledger["successors"] if item["id"] == successor_id
    )
    if (
        successor["contract"] != successor_contract
        or successor["verifier"] != successor_verifier
        or successor["marker"] != successor_marker
    ):
        raise Phase6HistoricalRetirementV1Error(
            f"test node successor binding drifted: {nodeid}"
        )
    return {
        "historical_test_id": nodeid,
        "disposition": "superseded-point-in-time-test-not-rebound",
        "successor_id": successor_id,
        "successor_contract": successor_contract,
        "successor_verifier": successor_verifier,
        "successor_marker": successor_marker,
    }
