from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REL = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V8-001.sha256"
ARTIFACTS_REL = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V8-001.sha256"
BUNDLE_REL = "docs/onyx/checkpoints/phase5-approval-inbox-v8/phase5-approval-inbox-v8.bundle.json"
WORKER_REL = "scripts/verify_phase5_approval_inbox_v8_worker.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"P52_APPROVAL_INBOX_V8_EVIDENCE_FAIL {message}")


def manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([!-~]+)", line)
        if match is None or match.group(2) in result:
            fail(f"manifest:{path.name}")
        result[match.group(2)] = match.group(1)
    return result


def main() -> int:
    source_path = ROOT / SOURCE_REL
    artifacts_path = ROOT / ARTIFACTS_REL
    worker_path = ROOT / WORKER_REL
    bundle_path = ROOT / BUNDLE_REL
    if any(
        path.is_symlink() or not path.is_file()
        for path in (source_path, artifacts_path, worker_path, bundle_path)
    ):
        fail("authority-path")
    source = manifest(source_path)
    if source != {ARTIFACTS_REL: sha(artifacts_path)}:
        fail("root-relation")
    artifacts = manifest(artifacts_path)
    for relative in (WORKER_REL, BUNDLE_REL):
        expected = artifacts.get(relative)
        if expected is None or sha(ROOT / relative) != expected:
            fail(f"prelaunch-drift:{relative}")
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v8":
        fail("bundle-contract")
    process = subprocess.run(
        [sys.executable, str(worker_path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=180,
        check=False,
    )
    if process.returncode:
        print(process.stdout, end="")
        fail("worker")
    lines = [line for line in process.stdout.splitlines() if line]
    if len(lines) != 1 or not lines[0].startswith("P52_APPROVAL_INBOX_V8_EVIDENCE_OK "):
        print(process.stdout, end="")
        fail("worker-marker")
    print(lines[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
