"""Verify the fail-closed R10B engineering license decision packet."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
PACKET_RELATIVE = Path("docs/onyx/checkpoints/LEGAL_DECISION_PACKET_R10B_V1.json")
WORKLIST_RELATIVE = Path("docs/onyx/THIRD_PARTY_LICENSE_REVIEW_WORKLIST_1.1.9.md")
APPROVAL_RELATIVE = Path("docs/onyx/LEGAL_RELEASE_APPROVAL_1.1.9.md")
EXPECTED_PACKET_SHA256 = (
    "ec123caaf2857f7298c67f2db47170e13e9b679e0d74030b05276040bf932106"
)
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_CANDIDATE = {
    "name": "ONYX-1.1.9-V49-R10B",
    "source_root_sha256": (
        "f9b169d15a964cd25c151dfca0e2ef807229761a6325dab5005c3a93c6487a50"
    ),
    "bundle_root_sha256": (
        "d8ce24ddd991c114367707eb990caaf7e4119cd4650c99fed2ac8a56e8826635"
    ),
    "sbom_sha256": (
        "b335a9a8b33f287bd9b8e91dba7d0ef20bfa8cf163701f2134bd8cb8ee799dd3"
    ),
    "compliance_receipt_sha256": (
        "7aeefaeebb22a1becb93b0a568756234918c259a408dfaae6a9a7dc33ddb6e6f"
    ),
}
EXPECTED_SPDX = {
    "colorama": "BSD-3-Clause",
    "importlib_metadata": "Apache-2.0",
    "itsdangerous": "BSD-3-Clause",
    "markdown-it-py": "MIT",
    "mdurl": "MIT",
    "pdfplumber": "MIT",
    "pycaw": "MIT",
}


class LegalDecisionPacketError(RuntimeError):
    """The R10B legal decision packet is incomplete, widened, or inconsistent."""


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LegalDecisionPacketError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_packet(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LegalDecisionPacketError("decision packet is not strict UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise LegalDecisionPacketError("decision packet root must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object, field: str, *, length: int = 64) -> str:
    pattern = HEX_64 if length == 64 else HEX_40
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise LegalDecisionPacketError(f"{field} must be lowercase SHA-{length * 4}")
    return value


def _relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise LegalDecisionPacketError(f"{field} must be a non-empty path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise LegalDecisionPacketError(f"{field} must be a safe POSIX relative path")
    return value


def verify_legal_decision_packet(
    project: Path = PROJECT,
    *,
    packet_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(project).resolve(strict=True)
    selected = packet_path or root / PACKET_RELATIVE
    packet_sha256 = _sha256(selected)
    if packet_path is None and packet_sha256 != EXPECTED_PACKET_SHA256:
        raise LegalDecisionPacketError("authoritative decision packet digest drifted")
    packet = _read_packet(selected)
    if set(packet) != {
        "schema",
        "candidate",
        "status",
        "legal_approval_granted",
        "public_release_eligible",
        "noassertion_summary",
        "tag_bound_candidates",
        "unresolved",
    }:
        raise LegalDecisionPacketError("decision packet top-level contract drifted")
    if packet["schema"] != "OnyxLegalDecisionPacket.v1":
        raise LegalDecisionPacketError("decision packet schema drifted")
    if packet["candidate"] != EXPECTED_CANDIDATE:
        raise LegalDecisionPacketError("R10B candidate binding drifted")
    if (
        packet["status"] != "ENGINEERING_RECONCILIATION_ONLY"
        or packet["legal_approval_granted"] is not False
        or packet["public_release_eligible"] is not False
    ):
        raise LegalDecisionPacketError("engineering evidence widened into approval")
    if packet["noassertion_summary"] != {
        "sbom_rows": 8,
        "tag_bound_engineering_candidates": 7,
        "substantively_unresolved": 1,
        "legally_approved": 0,
    }:
        raise LegalDecisionPacketError("NOASSERTION summary drifted")

    candidates = packet["tag_bound_candidates"]
    if not isinstance(candidates, list) or len(candidates) != 7:
        raise LegalDecisionPacketError("exactly seven tag-bound candidates are required")
    seen: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict) or set(row) != {
            "package",
            "version",
            "spdx_candidate",
            "upstream_repository",
            "upstream_ref",
            "upstream_commit",
            "comparison",
            "license_files",
            "legal_disposition",
        }:
            raise LegalDecisionPacketError("tag-bound candidate contract drifted")
        package = row["package"]
        if package not in EXPECTED_SPDX or package in seen:
            raise LegalDecisionPacketError(f"unexpected or duplicate package: {package}")
        seen.add(package)
        if row["spdx_candidate"] != EXPECTED_SPDX[package]:
            raise LegalDecisionPacketError(f"SPDX candidate drifted: {package}")
        if row["legal_disposition"] != "REQUIRED":
            raise LegalDecisionPacketError(f"legal disposition widened: {package}")
        if (
            not isinstance(row["upstream_repository"], str)
            or not row["upstream_repository"].startswith("https://github.com/")
            or not isinstance(row["upstream_ref"], str)
            or not row["upstream_ref"]
        ):
            raise LegalDecisionPacketError(f"upstream binding invalid: {package}")
        _digest(row["upstream_commit"], f"{package}.upstream_commit", length=40)
        files = row["license_files"]
        if not isinstance(files, list) or not files:
            raise LegalDecisionPacketError(f"license file evidence missing: {package}")
        for evidence in files:
            required = {
                "upstream_path",
                "upstream_sha256",
                "shipped_path",
                "shipped_sha256",
            }
            if not isinstance(evidence, dict) or not required <= set(evidence):
                raise LegalDecisionPacketError(f"license evidence contract drifted: {package}")
            _relative(evidence["upstream_path"], f"{package}.upstream_path")
            _relative(evidence["shipped_path"], f"{package}.shipped_path")
            upstream = _digest(evidence["upstream_sha256"], f"{package}.upstream_sha256")
            shipped = _digest(evidence["shipped_sha256"], f"{package}.shipped_sha256")
            if row["comparison"] == "raw_exact":
                if set(evidence) != required or upstream != shipped:
                    raise LegalDecisionPacketError(f"raw comparison is not exact: {package}")
            elif row["comparison"] == "utf8_lf_normalized_exact":
                if package != "pycaw" or set(evidence) != required | {
                    "shipped_normalized_sha256"
                }:
                    raise LegalDecisionPacketError("normalized comparison is restricted to pycaw")
                normalized = _digest(
                    evidence["shipped_normalized_sha256"],
                    "pycaw.shipped_normalized_sha256",
                )
                if shipped == upstream or normalized != upstream:
                    raise LegalDecisionPacketError("pycaw normalization evidence drifted")
            else:
                raise LegalDecisionPacketError(f"unsupported comparison: {package}")
    if seen != set(EXPECTED_SPDX):
        raise LegalDecisionPacketError("tag-bound package set is incomplete")

    unresolved = packet["unresolved"]
    if not isinstance(unresolved, list) or len(unresolved) != 1:
        raise LegalDecisionPacketError("exactly one substantive unresolved row is required")
    odfpy = unresolved[0]
    if (
        not isinstance(odfpy, dict)
        or odfpy.get("package") != "odfpy"
        or odfpy.get("version") != "1.4.1"
        or odfpy.get("spdx_candidate") is not None
        or odfpy.get("legal_disposition") != "REQUIRED"
        or "Apache" not in odfpy.get("reason", "")
        or "GPL" not in odfpy.get("reason", "")
    ):
        raise LegalDecisionPacketError("odfpy unresolved boundary drifted")
    _digest(odfpy.get("upstream_commit"), "odfpy.upstream_commit", length=40)
    _digest(odfpy.get("upstream_setup_sha256"), "odfpy.upstream_setup_sha256")
    _relative(odfpy.get("shipped_notice_path"), "odfpy.shipped_notice_path")
    _digest(odfpy.get("shipped_notice_sha256"), "odfpy.shipped_notice_sha256")

    worklist = (root / WORKLIST_RELATIVE).read_text(encoding="utf-8")
    approval = (root / APPROVAL_RELATIVE).read_text(encoding="utf-8")
    for package in {*EXPECTED_SPDX, "odfpy"}:
        if f"`{package}`" not in worklist:
            raise LegalDecisionPacketError(f"worklist omits packet package: {package}")
    if PACKET_RELATIVE.as_posix() not in approval or packet_sha256 not in approval:
        raise LegalDecisionPacketError("approval template is not bound to this packet")
    if "Status: **approval required**" not in approval:
        raise LegalDecisionPacketError("approval template no longer fails closed")

    return {
        "schema": packet["schema"],
        "packet_sha256": packet_sha256,
        "tag_bound_engineering_candidates": 7,
        "substantively_unresolved": 1,
        "legally_approved": 0,
        "legal_approval_granted": False,
        "public_release_eligible": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify_legal_decision_packet(), sort_keys=True))
