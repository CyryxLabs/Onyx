"""Fail closed when Onyx current-release documentation drifts behind R15B."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


class CurrentReleaseDocumentationError(RuntimeError):
    """The current documentation set contains a missing or stale authority."""


REQUIRED: dict[str, tuple[str, ...]] = {
    "DOCUMENTATION_INDEX.md": (
        "V53 R15B",
        "DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md",
        "346dcba124fceb30de34c2502164c9ef01e1b8a7350b35d362fd3aee2f3e0f45",
        "NOT RELEASE-ELIGIBLE",
        "57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f",
        "e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c",
    ),
    "CURRENT_RELEASE_STATUS.md": (
        "V53 R15B",
        # R15B is now built, installed, soaked and consolidated on this host.
        "PASSED_EXACT_REBUILD",
        "R15B_INSTALLED_AND_ACCEPTED",
        "PASSED_R15B_EIGHT_HOUR",
        "PASSED_LIVE_FROZEN_SOURCE",
        "PASSED_LOCAL_WINDOWS_AND_CONTAINER",
        # Consolidated acceptance receipt and the installed executable it binds.
        "b6266dfcdc9441901cfe57d2a502d3a74a6f9c9baf11d8b7533cba2437411cd6",
        "ff289de8b8c607586ae580949359568805a54f928edda92b44efe9d39cb8cda7",
        "127c6b18f98375da8f488c623900d2a558f0a7b5f7ff0da7fa757e71cc68b634",
        # The Linux reproducibility limitation must stay stated, with its
        # hash-bound finding, and must never be quietly upgraded to a pass.
        "PASSED_WITH_REPRODUCIBILITY_NOT_PROVEN",
        "cross-build byte reproducibility NOT proven",
        "9f2dbffb40d4dd566644726e51438af3c7b8d16785b2f55c09488d262c92735f",
        "57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f",
        "e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c",
        "NO-GO",
    ),
    "FINAL_EVIDENCE_INDEX_1.1.9.md": (
        "V53 R15B",
        "long-session-r10b-attempt4",
        "20569b3c16c82301d5f787398f689ed2afdd545dfb29b3bde2885a7c36ccfcd0",
        "fb9128ecfddf479528176e19991cade497e3e0c0f81890e37c309449aac06684",
        "INCOMPLETE",
        "57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f",
        "e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c",
    ),
    "DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md": (
        "ONYX-1.1.9-V53-R15B",
        "first R15B artifact attempt is **rejected**",
        "Gates still open",
        "57557e9ae420b1050036cec1259f70c1ce930fa50ad2374332ee4db59a9ad58f",
        "e6a43cbe638a05c33a7b4925c828f863f530a99052645a2489108953fc641c6c",
    ),
    "DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md": (
        "SUPERSEDED FOR CURRENT-STATE CLAIMS",
        "DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md",
    ),
    "DOCUMENT_SUPERSESSION_REGISTRY_R8B_2026-08-11.md": (
        "SUPERSEDED FOR CURRENT-STATE CLAIMS",
        "DOCUMENT_SUPERSESSION_REGISTRY_R15B_2026-08-11.md",
    ),
}

FORBIDDEN_CURRENT: dict[str, tuple[str, ...]] = {
    "DOCUMENTATION_INDEX.md": (
        "Current frozen source: **V49 R10B",
        "DOCUMENT_SUPERSESSION_REGISTRY_R10B_2026-08-11.md` — current",
    ),
    "CURRENT_RELEASE_STATUS.md": (
        "Current frozen source: **V49 R10B",
        "IN_PROGRESS_R10B_ATTEMPT3",
        # Superseded R15B states: the soak terminalized, the exact rebuild
        # happened, R15B is installed, and the Linux gate ran for real.
        "IN_PROGRESS_R10B_ATTEMPT4",
        "REJECTED_FIRST_ATTEMPT_RECOVERY_ARMED",
        "R10B_PREDECESSOR_RUNNING",
        "CONTAINERIZED_R15B_PREFLIGHT_PASSED",
    ),
    "FINAL_EVIDENCE_INDEX_1.1.9.md": (
        "Frozen source: **V49 R10B",
        "attempt3/ONYX_1_1_9_R10B_WINDOWS_LONG_SESSION_ATTEMPT3_RECEIPT",
        "Microsoft Graph DayOps live | Onyx-specific Entra identity, least-privilege consent and live calendar/mail receipts | Missing",
    ),
}


def verify_current_release_docs(docs_root: Path) -> dict[str, object]:
    errors: list[str] = []
    checked: list[str] = []
    document_sha256: dict[str, str] = {}

    for name, literals in REQUIRED.items():
        path = docs_root / name
        if not path.is_file():
            errors.append(f"missing current-release document: {name}")
            continue
        text = path.read_text(encoding="utf-8")
        checked.append(name)
        document_sha256[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for literal in literals:
            if literal not in text:
                errors.append(f"{name}: required literal absent: {literal}")
        current_text = text
        if name == "CURRENT_RELEASE_STATUS.md":
            current_text = text.split("## R10B installed predecessor boundary", 1)[0]
        for literal in FORBIDDEN_CURRENT.get(name, ()):
            if literal in current_text:
                errors.append(f"{name}: stale current literal present: {literal}")

    legal = docs_root / "LEGAL_RELEASE_APPROVAL_1.1.9.md"
    if not legal.is_file():
        errors.append("missing predecessor legal approval worklist")
    else:
        legal_text = legal.read_text(encoding="utf-8")
        if "R10B" not in legal_text or "OWNER_OR_LEGAL_APPROVAL_REQUIRED" not in legal_text:
            errors.append("legal approval record must remain R10B-bound and unresolved")
        if re.search(
            r"(?mi)^(?:-\s*)?Decision:\s*`?APPROVED`?\s*$", legal_text
        ):
            errors.append("legal approval record unexpectedly claims APPROVED")
        checked.append(legal.name)
        document_sha256[legal.name] = hashlib.sha256(legal.read_bytes()).hexdigest()

    if errors:
        raise CurrentReleaseDocumentationError("; ".join(errors))

    return {
        "schema": "OnyxCurrentReleaseDocumentationVerification.v1",
        "status": "passed_r15b_current_authority",
        "documents_checked": sorted(checked),
        "document_sha256": dict(sorted(document_sha256.items())),
        "public_release_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "onyx",
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    try:
        report = verify_current_release_docs(args.docs_root.resolve())
    except CurrentReleaseDocumentationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        return 1
    payload = json.dumps(report, indent=2) + "\n"
    if args.receipt is not None:
        receipt = args.receipt.resolve()
        receipt.parent.mkdir(parents=True, exist_ok=True)
        temporary = receipt.with_name(receipt.name + ".tmp")
        temporary.write_text(payload, encoding="utf-8", newline="\n")
        temporary.replace(receipt)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
