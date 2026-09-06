"""Verify intentional successor drift without rewriting historical evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping


PROJECT = Path(__file__).resolve().parents[1]
LEDGER = "docs/onyx/checkpoints/LEGACY_EVIDENCE_RETIREMENT_V1.json"
# Filled from the canonical LF/UTF-8 ledger.  It is deliberately outside the
# ledger so the retirement authority cannot authenticate itself.
LEDGER_SHA256 = "1f672a18f8100c8ce7a262d3a224806aa8d45438e0e709e722801552bb837fc9"
CAPABILITY_PERMISSION_BROKER_TEST_IDS = tuple(
    "tests/test_capability_nexus_v"
    f"{version}.py::test_frozen_history_proof_never_spawns_a_recursive_verifier"
    for version in range(15, 33)
)
CAPABILITY_PERMISSION_BROKER_HISTORICAL_PATH = "core/permission_broker.py"
CAPABILITY_PERMISSION_BROKER_HISTORICAL_SHA256 = (
    "8358ba39d7ff2d965eae7af7c24007f64f4670bef349447737c72e88776cbffc"
)


class LegacyEvidenceRetirementError(RuntimeError):
    """Historical evidence was changed without an exact retirement record."""


def _canonical_relative(relative: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise LegacyEvidenceRetirementError("retirement path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise LegacyEvidenceRetirementError("retirement path is not canonical")
    return Path(*parsed.parts)


def _bytes(project: Path, relative: str) -> bytes:
    path = project.resolve() / _canonical_relative(relative)
    try:
        path.resolve(strict=True).relative_to(project.resolve(strict=True))
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise LegacyEvidenceRetirementError(
            f"retirement evidence unavailable: {relative}"
        ) from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_retirement_ledger(project: Path = PROJECT) -> dict[str, object]:
    raw = _bytes(Path(project), LEDGER)
    if _sha256(raw) != LEDGER_SHA256:
        raise LegacyEvidenceRetirementError("retirement ledger digest drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise LegacyEvidenceRetirementError("retirement ledger is not canonical")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyEvidenceRetirementError("retirement ledger is invalid") from exc
    if type(value) is not dict or set(value) != {
        "schema",
        "issued_at",
        "policy",
        "claims",
        "artifacts",
    }:
        raise LegacyEvidenceRetirementError("retirement ledger contract drifted")
    if value["schema"] != "onyx.legacy-evidence-retirement.v1" or value["policy"] != {
        "historical_hashes_are_rebound_to_successor_bytes": False,
        "historical_manifests_remain_immutable": True,
        "successor_drift_requires_an_exact_record": True,
    }:
        raise LegacyEvidenceRetirementError("retirement ledger policy drifted")
    artifacts = value["artifacts"]
    claims = value["claims"]
    if type(artifacts) is not list or type(claims) is not list:
        raise LegacyEvidenceRetirementError("retirement ledger entries are invalid")
    artifact_keys = {
        "id",
        "path",
        "historical_bytes",
        "historical_sha256",
        "disposition",
        "successor_contract",
    }
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for record in artifacts:
        if type(record) is not dict or set(record) != artifact_keys:
            raise LegacyEvidenceRetirementError("retirement artifact is malformed")
        identifier = record["id"]
        relative = record["path"]
        digest = record["historical_sha256"]
        if (
            type(identifier) is not str
            or not identifier
            or identifier in seen_ids
            or type(relative) is not str
            or relative in seen_paths
            or type(record["historical_bytes"]) is not int
            or record["historical_bytes"] < 0
            or type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or not str(record["disposition"]).endswith("-not-rebound")
            or type(record["successor_contract"]) is not str
            or not record["successor_contract"]
        ):
            raise LegacyEvidenceRetirementError("retirement artifact is invalid")
        _canonical_relative(relative)
        seen_ids.add(identifier)
        seen_paths.add(relative)
    if (
        len(claims) != 3
        or {claim.get("id") for claim in claims if type(claim) is dict}
        != {
            "phase4-r3-authority-free-startup",
            "capability-nexus-v3-no-live-wiring",
            "capability-nexus-v15-v32-permission-broker-history",
        }
    ):
        raise LegacyEvidenceRetirementError("retirement claim set drifted")
    return value


def artifact_retirement(
    project: Path,
    relative: str,
    historical_sha256: str,
    *,
    historical_bytes: int | None = None,
) -> dict[str, object]:
    """Authenticate one old digest and require the live successor to differ."""

    ledger = load_retirement_ledger(project)
    matches = [
        record
        for record in ledger["artifacts"]
        if record["path"] == relative
        and record["historical_sha256"] == historical_sha256
    ]
    if len(matches) != 1:
        raise LegacyEvidenceRetirementError(
            f"historical drift lacks exact retirement: {relative}"
        )
    record = matches[0]
    if historical_bytes is not None and record["historical_bytes"] != historical_bytes:
        raise LegacyEvidenceRetirementError(
            f"historical byte count lacks exact retirement: {relative}"
        )
    current = _bytes(Path(project), relative)
    current_sha256 = _sha256(current)
    if current_sha256 == historical_sha256:
        raise LegacyEvidenceRetirementError(
            f"retired artifact unexpectedly matches live successor: {relative}"
        )
    return {
        "path": relative,
        "historical_sha256": historical_sha256,
        "historical_bytes": record["historical_bytes"],
        "current_sha256": current_sha256,
        "current_bytes": len(current),
        "disposition": record["disposition"],
        "successor_contract": record["successor_contract"],
    }


def classify_historical_artifact(
    project: Path,
    relative: str,
    historical_sha256: str,
    *,
    historical_bytes: int | None = None,
) -> dict[str, object]:
    """Return exact-preserved or explicitly-superseded historical state."""

    current = _bytes(Path(project), relative)
    current_sha256 = _sha256(current)
    if current_sha256 == historical_sha256:
        if historical_bytes is not None and len(current) != historical_bytes:
            raise LegacyEvidenceRetirementError(
                f"historical byte count contradicts digest: {relative}"
            )
        return {
            "path": relative,
            "historical_sha256": historical_sha256,
            "state": "preserved-exact",
        }
    retired = artifact_retirement(
        Path(project),
        relative,
        historical_sha256,
        historical_bytes=historical_bytes,
    )
    retired["state"] = "superseded-not-rebound"
    return retired


def verify_phase4_authority_succession(
    project: Path,
    *,
    static_modules: list[str],
    fresh_import_modules: list[str],
) -> dict[str, object]:
    ledger = load_retirement_ledger(project)
    claim = next(
        item
        for item in ledger["claims"]
        if item["id"] == "phase4-r3-authority-free-startup"
    )
    if claim.get("disposition") != "superseded-not-rebound":
        raise LegacyEvidenceRetirementError("authority retirement disposition drifted")
    for evidence in claim.get("historical_evidence", []):
        if type(evidence) is not dict or set(evidence) != {"path", "sha256"}:
            raise LegacyEvidenceRetirementError("authority history is malformed")
        if _sha256(_bytes(Path(project), evidence["path"])) != evidence["sha256"]:
            raise LegacyEvidenceRetirementError("authority history digest drifted")
    expected_static = claim.get("current_static_authority_modules")
    expected_fresh = claim.get("current_fresh_import_authority_modules")
    if static_modules != expected_static or fresh_import_modules != expected_fresh:
        raise LegacyEvidenceRetirementError(
            "current authority closure is outside the recorded successor"
        )
    return {
        "historical_claim": "superseded-not-rebound",
        "successor_contract": claim["successor_contract"],
        "static_authority": static_modules,
        "fresh_import_authority": fresh_import_modules,
    }


def verify_capability_nexus_wiring_succession(
    project: Path,
    *,
    collected_test_id: str,
    successor_contract: str,
    successor_verifier: str,
    successor_marker: str,
) -> dict[str, object]:
    """Bind the collected historical V3 node to the distinct current gate."""

    ledger = load_retirement_ledger(project)
    claim = next(
        item
        for item in ledger["claims"]
        if item["id"] == "capability-nexus-v3-no-live-wiring"
    )
    if (
        claim.get("disposition") != "superseded-not-rebound"
        or collected_test_id != claim.get("historical_test_id")
        or successor_contract != claim.get("successor_contract")
        or successor_verifier != claim.get("successor_verifier")
        or successor_marker != claim.get("successor_marker")
    ):
        raise LegacyEvidenceRetirementError(
            "capability nexus wiring succession drifted"
        )
    historical_path = claim.get("historical_test_path")
    historical_sha256 = claim.get("historical_test_sha256")
    if (
        type(historical_path) is not str
        or type(historical_sha256) is not str
        or _sha256(_bytes(Path(project), historical_path)) != historical_sha256
    ):
        raise LegacyEvidenceRetirementError(
            "capability nexus historical test bytes drifted"
        )
    return {
        "historical_claim": "superseded-not-rebound",
        "historical_test_id": collected_test_id,
        "successor_contract": successor_contract,
        "successor_verifier": successor_verifier,
        "successor_marker": successor_marker,
    }


def verify_capability_nexus_permission_broker_succession(
    project: Path,
    *,
    collected_test_id: str,
    successor_contract: str,
    successor_verifier: str,
    successor_marker: str,
) -> dict[str, object]:
    """Bind one collected V15-V32 frozen-leaf node to current evidence."""

    ledger = load_retirement_ledger(project)
    claim = next(
        item
        for item in ledger["claims"]
        if item["id"] == "capability-nexus-v15-v32-permission-broker-history"
    )
    required_keys = {
        "id",
        "disposition",
        "historical_claim",
        "historical_leaf_path",
        "historical_leaf_sha256",
        "historical_test_ids",
        "successor_contract",
        "successor_verifier",
        "successor_marker",
        "reason",
    }
    if (
        set(claim) != required_keys
        or claim.get("disposition") != "superseded-not-rebound"
        or claim.get("historical_leaf_path")
        != CAPABILITY_PERMISSION_BROKER_HISTORICAL_PATH
        or claim.get("historical_leaf_sha256")
        != CAPABILITY_PERMISSION_BROKER_HISTORICAL_SHA256
        or claim.get("historical_test_ids")
        != list(CAPABILITY_PERMISSION_BROKER_TEST_IDS)
        or collected_test_id not in CAPABILITY_PERMISSION_BROKER_TEST_IDS
        or successor_contract != claim.get("successor_contract")
        or successor_verifier != claim.get("successor_verifier")
        or successor_marker != claim.get("successor_marker")
    ):
        raise LegacyEvidenceRetirementError(
            "capability permission-broker succession drifted"
        )
    current_sha256 = _sha256(
        _bytes(Path(project), CAPABILITY_PERMISSION_BROKER_HISTORICAL_PATH)
    )
    if current_sha256 == CAPABILITY_PERMISSION_BROKER_HISTORICAL_SHA256:
        raise LegacyEvidenceRetirementError(
            "historical permission-broker leaf unexpectedly became current"
        )
    return {
        "historical_claim": "superseded-not-rebound",
        "historical_leaf_path": CAPABILITY_PERMISSION_BROKER_HISTORICAL_PATH,
        "historical_leaf_sha256": CAPABILITY_PERMISSION_BROKER_HISTORICAL_SHA256,
        "current_leaf_sha256": current_sha256,
        "historical_test_id": collected_test_id,
        "successor_contract": successor_contract,
        "successor_verifier": successor_verifier,
        "successor_marker": successor_marker,
    }


def verify_recorded_manifest(
    project: Path,
    manifest_relative: str,
    manifest_sha256: str,
    artifact_root_sha256: str,
    root_algorithm: Callable[[Mapping[str, str]], str],
) -> dict[str, object]:
    """Verify immutable manifest history and classify live successor drift."""

    raw = _bytes(Path(project), manifest_relative)
    if _sha256(raw) != manifest_sha256:
        raise LegacyEvidenceRetirementError(
            f"historical manifest drifted: {manifest_relative}"
        )
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise LegacyEvidenceRetirementError("historical manifest is invalid") from exc
    entries = manifest.get("artifacts")
    if type(entries) is not list or not entries:
        raise LegacyEvidenceRetirementError("historical artifact closure is invalid")
    artifacts: dict[str, str] = {}
    states: dict[str, str] = {}
    for entry in entries:
        if type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}:
            raise LegacyEvidenceRetirementError("historical artifact entry is malformed")
        relative = entry["path"]
        if relative in artifacts:
            raise LegacyEvidenceRetirementError("historical artifact path is duplicated")
        state = classify_historical_artifact(
            Path(project),
            relative,
            entry["sha256"],
            historical_bytes=entry["bytes"],
        )
        artifacts[relative] = entry["sha256"]
        states[relative] = state["state"]
    if root_algorithm(artifacts) != artifact_root_sha256:
        raise LegacyEvidenceRetirementError("historical artifact root does not recompute")
    if manifest.get("artifact_root_sha256") != artifact_root_sha256:
        raise LegacyEvidenceRetirementError("historical manifest root binding drifted")
    return {
        "manifest_sha256": manifest_sha256,
        "artifact_root_sha256": artifact_root_sha256,
        "artifacts": len(artifacts),
        "states": states,
    }
