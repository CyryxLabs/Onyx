"""Independent, acyclic verifier for the current Release V33 receipt."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Final


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

RELEASE_V33_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v33.json"
)
RELEASE_V33_SHA256: Final = (
    "aa1e0b21a2836c1d762d06038b4576c2446d133550025b0d9fc202941b854ee8"
)
RELEASE_V32_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v32.json"
)
RELEASE_V32_SHA256: Final = (
    "78f02874ee159ce60428ff71701ca3b1dab3159e61ff69fed4e1dad90f46b251"
)
RELEASE_V31_RELATIVE: Final = Path(
    "tests/fixtures/release_workflow_transition_v31.json"
)
RELEASE_V31_SHA256: Final = (
    "372e86d759f326fbc9198f9c6d1b49032f7db849f6e4bfb5bc7d93f6e6389307"
)
RELEASE_V33_ROOT_SHA256: Final = (
    "86729a72963b34615f3425a8f9b2b0eb5f4ebe3af64ecd693b304cde4491acfe"
)
RELEASE_V32_ROOT_SHA256: Final = (
    "abec138b6a40ff211163bf33ca1648739baa9635d5f5cf281be76ac63bc92480"
)
RELEASE_V32_VERIFIER_RELATIVE: Final = Path(
    "scripts/verify_release_workflow_v32.py"
)
RELEASE_V32_VERIFIER_SHA256: Final = (
    "e3f84599153f1f55050c3b755abf73053c30b1e49414b04068f42ea58f592110"
)
RELEASE_V32_RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V32_VERIFIER_RECEIPT.json"
)
RELEASE_V32_RECEIPT_SHA256: Final = (
    "c35bcb7497ab0fb6a500d49073b96a69400950746490287bada7d85467d1fe73"
)
RELEASE_V32_TEST_SHA256: Final = (
    "9e48eee99d4866e72fdc5b55e294f29a77f534d0d472c9c55b6ad3cec40a4c35"
)
VERIFIER_RELATIVE: Final = Path("scripts/verify_release_workflow_v33.py")
RECEIPT_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/RELEASE_WORKFLOW_V33_VERIFIER_RECEIPT.json"
)
TEST_RELATIVE: Final = Path("tests/test_release_workflow_transition_v33.py")
POLICY: Final = {
    "predecessor_is_immutable": True,
    "historical_hashes_are_rebound": False,
    "current_release_paths_are_sha256_bound": True,
    "unsigned_windows_may_be_formal": False,
    "diagnostic_candidates_may_be_published": False,
}


class ReleaseWorkflowV33Error(RuntimeError):
    """Release V33 or its externally anchored verifier receipt drifted."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_file(root: Path, relative: str | Path) -> Path:
    value = relative.as_posix() if isinstance(relative, Path) else relative
    parsed = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or parsed.is_absolute()
        or parsed.as_posix() != value
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ReleaseWorkflowV33Error(f"noncanonical release path: {value!r}")
    candidate = root.joinpath(*parsed.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise ReleaseWorkflowV33Error(f"release input unavailable: {value}")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ReleaseWorkflowV33Error(f"release input escapes root: {value}") from exc
    if resolved != candidate.absolute():
        raise ReleaseWorkflowV33Error(f"release input is linked: {value}")
    return resolved


def _strict_json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise ReleaseWorkflowV33Error("duplicate release JSON key")
            result[key] = value
        return result

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise ReleaseWorkflowV33Error("release JSON is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseWorkflowV33Error("release JSON is invalid") from exc
    if type(value) is not dict:
        raise ReleaseWorkflowV33Error("release JSON must be an object")
    return value


def _frame(digest: object, value: str) -> None:
    encoded = value.encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _root(record: dict[str, object], domain: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    if record.get("schema") == "onyx.release-workflow-transition.v33":
        _frame(digest, record["issued_at"])
        _frame(digest, str(record["logical_sequence"]))
        anomaly = record["predecessor_clock_anomaly"]
        _frame(digest, anomaly["predecessor_issued_at"])
        _frame(digest, anomaly["observed_at"])
        _frame(digest, anomaly["reason"])
    predecessor = record["predecessor"]
    _frame(digest, predecessor["path"])
    _frame(digest, predecessor["sha256"])
    for entry in record["current_release_paths"]:
        _frame(digest, entry["path"])
        _frame(digest, entry["sha256"])
    return digest.hexdigest()


def _valid_sha(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


_RFC3339_AWARE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


def _parse_rfc3339(value: object, *, label: str) -> datetime:
    if type(value) is not str or _RFC3339_AWARE.fullmatch(value) is None:
        raise ReleaseWorkflowV33Error(f"{label} is not timezone-aware RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseWorkflowV33Error(
            f"{label} is not timezone-aware RFC3339"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ReleaseWorkflowV33Error(f"{label} is not timezone-aware RFC3339")
    return parsed


def _validate_chronology(
    transition: dict[str, object], predecessor: dict[str, object]
) -> None:
    predecessor_schema = predecessor.get("schema")
    match = (
        re.fullmatch(r"onyx\.release-workflow-transition\.v(\d+)", predecessor_schema)
        if type(predecessor_schema) is str
        else None
    )
    logical_sequence = transition.get("logical_sequence")
    if (
        match is None
        or type(logical_sequence) is not int
        or logical_sequence != int(match.group(1)) + 1
    ):
        raise ReleaseWorkflowV33Error("Release V33 logical sequence drifted")

    issued_raw = transition.get("issued_at")
    predecessor_raw = predecessor.get("issued_at")
    issued = _parse_rfc3339(issued_raw, label="Release V33 issued_at")
    predecessor_issued = _parse_rfc3339(
        predecessor_raw, label="Release V32 issued_at"
    )
    if issued == predecessor_issued:
        raise ReleaseWorkflowV33Error("Release V33 chronology cannot be equal")

    anomaly = transition.get("predecessor_clock_anomaly")
    if issued < predecessor_issued:
        expected = {
            "predecessor_issued_at": predecessor_raw,
            "observed_at": issued_raw,
            "reason": "predecessor_future_dated",
        }
        if anomaly != expected:
            raise ReleaseWorkflowV33Error(
                "Release V33 predecessor clock anomaly drifted"
            )
    elif anomaly is not None:
        raise ReleaseWorkflowV33Error(
            "Release V33 has a false predecessor clock anomaly"
        )


def _validated_entries(
    record: dict[str, object], *, label: str
) -> list[dict[str, str]]:
    entries = record.get("current_release_paths")
    if type(entries) is not list or not entries:
        raise ReleaseWorkflowV33Error(f"{label} membership drifted")
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or type(entry.get("path")) is not str
            or not _valid_sha(entry.get("sha256"))
        ):
            raise ReleaseWorkflowV33Error(f"{label} entry is malformed")
        paths.append(entry["path"])
    if paths != sorted(set(paths)):
        raise ReleaseWorkflowV33Error(f"{label} membership drifted")
    return entries


def verify_release_workflow_v33(project: Path = PROJECT) -> dict[str, object]:
    """Validate V33, immutable V32/V31, current bytes, receipt and V26."""

    root = Path(project).resolve(strict=True)
    v33_path = _canonical_file(root, RELEASE_V33_RELATIVE)
    if _sha256(v33_path) != RELEASE_V33_SHA256:
        raise ReleaseWorkflowV33Error("Release V33 fixture digest drifted")
    transition = _strict_json(v33_path)
    if (
        set(transition)
        != {
            "schema",
            "issued_at",
            "logical_sequence",
            "predecessor_clock_anomaly",
            "predecessor",
            "policy",
            "current_release_paths",
            "current_root_sha256",
        }
        or transition.get("schema") != "onyx.release-workflow-transition.v33"
        or transition.get("predecessor")
        != {
            "path": RELEASE_V32_RELATIVE.as_posix(),
            "sha256": RELEASE_V32_SHA256,
        }
        or transition.get("policy") != POLICY
        or transition.get("current_root_sha256") != RELEASE_V33_ROOT_SHA256
    ):
        raise ReleaseWorkflowV33Error("Release V33 contract drifted")

    v32_path = _canonical_file(root, RELEASE_V32_RELATIVE)
    if _sha256(v32_path) != RELEASE_V32_SHA256:
        raise ReleaseWorkflowV33Error("Release V32 predecessor digest drifted")
    predecessor = _strict_json(v32_path)
    if (
        predecessor.get("schema") != "onyx.release-workflow-transition.v32"
        or predecessor.get("predecessor")
        != {
            "path": RELEASE_V31_RELATIVE.as_posix(),
            "sha256": RELEASE_V31_SHA256,
        }
        or predecessor.get("policy") != POLICY
        or predecessor.get("current_root_sha256") != RELEASE_V32_ROOT_SHA256
        or _root(predecessor, b"ONYX-RELEASE-WORKFLOW-TRANSITION-V32\0")
        != RELEASE_V32_ROOT_SHA256
    ):
        raise ReleaseWorkflowV33Error("Release V32 predecessor contract drifted")
    _validate_chronology(transition, predecessor)

    current_entries = _validated_entries(transition, label="Release V33")
    predecessor_entries = _validated_entries(predecessor, label="Release V32")
    current_hashes = {entry["path"]: entry["sha256"] for entry in current_entries}
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor_entries
    }
    for entry in current_entries:
        relative = entry["path"]
        if _sha256(_canonical_file(root, relative)) != entry["sha256"]:
            raise ReleaseWorkflowV33Error(
                f"current release target drifted: {relative}"
            )
        if predecessor_hashes.get(relative) == entry["sha256"]:
            raise ReleaseWorkflowV33Error(
                f"Release V33 contains unchanged target: {relative}"
            )
    if _root(transition, b"ONYX-RELEASE-WORKFLOW-TRANSITION-V33\0") != (
        RELEASE_V33_ROOT_SHA256
    ):
        raise ReleaseWorkflowV33Error("Release V33 root drifted")

    for entry in predecessor_entries:
        relative = entry["path"]
        actual_sha256 = _sha256(_canonical_file(root, relative))
        if (
            actual_sha256 != entry["sha256"]
            and current_hashes.get(relative) != actual_sha256
        ):
            raise ReleaseWorkflowV33Error(
                f"Release V32 current target drifted: {relative}"
            )

    v32_verifier = _canonical_file(root, RELEASE_V32_VERIFIER_RELATIVE)
    v32_receipt_path = _canonical_file(root, RELEASE_V32_RECEIPT_RELATIVE)
    if (
        _sha256(v32_verifier) != RELEASE_V32_VERIFIER_SHA256
        or _sha256(v32_receipt_path) != RELEASE_V32_RECEIPT_SHA256
    ):
        raise ReleaseWorkflowV33Error("Release V32 external authority drifted")
    v32_receipt = _strict_json(v32_receipt_path)
    if v32_receipt != {
        "schema": "onyx.release-workflow-v32-verifier-receipt.v1",
        "release_path": RELEASE_V32_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V32_SHA256,
        "release_root_sha256": RELEASE_V32_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V31_SHA256,
        "verifier_path": RELEASE_V32_VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": RELEASE_V32_VERIFIER_SHA256,
        "test_path": "tests/test_release_workflow_transition_v32.py",
        "test_sha256": RELEASE_V32_TEST_SHA256,
    }:
        raise ReleaseWorkflowV33Error("Release V32 external receipt drifted")
    current_v32_test_sha256 = _sha256(
        _canonical_file(root, "tests/test_release_workflow_transition_v32.py")
    )
    if current_hashes.get("tests/test_release_workflow_transition_v32.py") != (
        current_v32_test_sha256
    ):
        raise ReleaseWorkflowV33Error("Release V32 test successor drifted")

    v31_path = _canonical_file(root, RELEASE_V31_RELATIVE)
    if _sha256(v31_path) != RELEASE_V31_SHA256:
        raise ReleaseWorkflowV33Error("Release V31 predecessor digest drifted")
    v31 = _strict_json(v31_path)
    if (
        v31.get("schema") != "onyx.release-workflow-transition.v31"
        or v31.get("policy") != POLICY
        or _root(v31, b"ONYX-RELEASE-WORKFLOW-TRANSITION-V31\0")
        != v31.get("current_root_sha256")
    ):
        raise ReleaseWorkflowV33Error("Release V31 predecessor contract drifted")
    v32_hashes = {**predecessor_hashes, **current_hashes}
    for entry in _validated_entries(v31, label="Release V31"):
        relative = entry["path"]
        actual_sha256 = _sha256(_canonical_file(root, relative))
        if actual_sha256 != entry["sha256"] and v32_hashes.get(relative) != actual_sha256:
            raise ReleaseWorkflowV33Error(
                f"Release V31 current target drifted: {relative}"
            )

    receipt = _strict_json(_canonical_file(root, RECEIPT_RELATIVE))
    verifier_sha = _sha256(_canonical_file(root, VERIFIER_RELATIVE))
    test_sha = _sha256(_canonical_file(root, TEST_RELATIVE))
    if receipt != {
        "schema": "onyx.release-workflow-v33-verifier-receipt.v1",
        "release_path": RELEASE_V33_RELATIVE.as_posix(),
        "release_sha256": RELEASE_V33_SHA256,
        "release_root_sha256": RELEASE_V33_ROOT_SHA256,
        "predecessor_sha256": RELEASE_V32_SHA256,
        "verifier_path": VERIFIER_RELATIVE.as_posix(),
        "verifier_sha256": verifier_sha,
        "test_path": TEST_RELATIVE.as_posix(),
        "test_sha256": test_sha,
        "chronology": "logical_successor_with_predecessor_clock_anomaly",
    }:
        raise ReleaseWorkflowV33Error("Release V33 verifier receipt drifted")

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    runtime = verify_current_hud_acceptance(root)
    return {
        "transition": transition,
        "predecessor": predecessor,
        "runtime": runtime,
        "receipt": receipt,
    }


if __name__ == "__main__":
    verified = verify_release_workflow_v33()
    print(
        json.dumps(
            {
                "release_schema": verified["transition"]["schema"],
                "release_root_sha256": verified["transition"][
                    "current_root_sha256"
                ],
                "runtime_root_sha256": verified["runtime"][
                    "artifact_root_sha256"
                ],
                "verifier_sha256": verified["receipt"]["verifier_sha256"],
            },
            sort_keys=True,
        )
    )
