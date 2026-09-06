"""Verify the Phase 10 Content Draft acceptance through the CURRENT chain.

The historical content-draft acceptance verifier reproduces its predecessor by
executing the slice-3 candidate verifier, which fails closed against the tree
since `core/phase10_provider_connector_v1.py` drifted post-acceptance (see
docs/onyx/corrections/CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md).
This successor keeps every slice-4 pin byte-exact and re-verifies the slice-4
eight-artifact closure directly, then reproduces the predecessor through the
provider-connector CURRENT successor instead of the broken historical path.
The slice-4 artifact root is unchanged; no historical record is rewritten.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from core import phase10_content_draft_v1 as module  # noqa: E402
from scripts import (  # noqa: E402
    verify_phase10_provider_connector_current_v1_acceptance as provider_current,
)

ID = "VE-P10-CONTENT-DRAFT-V1-E6-001"
RECORD = PROJECT / f"docs/onyx/acceptance/{ID}.md"
METADATA = PROJECT / f"docs/onyx/acceptance/{ID}.manifest.json"
ANCHOR = PROJECT / "docs/onyx/VE-ACCEPTANCE-P10-CONTENT-DRAFT-V1-E6-001.sha256"
MANIFEST = PROJECT / "docs/onyx/checkpoints/phase10-content-draft-v1/manifest.json"
RECORD_SHA = "94f0964876f8c4a094ec8a3152501a87f20ddd8c1e08545eee591d92c822ad13"
METADATA_SHA = "8af9f47156ccd9ad8de232a105a40b6a32d9a42a85852d48de29c805fa5d850f"
ANCHOR_SHA = "cee917429abc1c5463a839411973307b6cf381a6e2003256a309ae5360e8a221"
MANIFEST_SHA = "f57046e1f65de10484b8ef31c706323683fd57952076d164dd0395150fdba8ff"
ROOT = "59308ada89f691443238644bdb18b7bc29aa66a61365b95908bc5631d8b8d449"
MARKER = "P10_CONTENT_DRAFT_CURRENT_V1_ACCEPTANCE_OK"
TEST_PATH = "tests/test_phase10_content_draft_v1.py"
TEST_EXPECTED_PASSED = 37


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("content-draft current acceptance artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    return hashlib.sha256(
        "".join(
            sorted(f"{path}\0{digest}\n" for path, digest in records.items())
        ).encode()
    ).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if (
        _sha(RECORD) != RECORD_SHA
        or _sha(METADATA) != METADATA_SHA
        or _sha(ANCHOR) != ANCHOR_SHA
        or _sha(MANIFEST) != MANIFEST_SHA
    ):
        raise RuntimeError("content-draft acceptance hash drift")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    if (
        metadata["decision"] != "accepted"
        or metadata["artifact_root_sha256"] != ROOT
        or metadata["results"]["passed"] != 607
    ):
        raise RuntimeError("content-draft acceptance semantic drift")

    # Direct slice-4 artifact closure: every artifact byte-exact, root exact.
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    observed: dict[str, str] = {}
    for item in manifest["artifacts"]:
        path = PROJECT / item["path"]
        digest = _sha(path)
        if digest != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise RuntimeError("content-draft artifact closure drift")
        observed[item["path"]] = digest
    if _root(observed) != ROOT:
        raise RuntimeError("content-draft artifact root drift")

    if module.ContentDraftFeatureGateV1.from_environ({}).enabled is not False:
        raise RuntimeError("content-draft feature gate is not default-off")
    module._verify_entry(PROJECT)

    provider_record = provider_current.verify(run_tests=False)
    if provider_record.get("decision") != "accepted_current_successor":
        raise RuntimeError("provider-connector current successor drift")

    if run_tests:
        temporary = (
            PROJECT
            / "runtime/test-tmp/p10-content-current-verify"
            / f"run-{secrets.token_hex(8)}"
        )
        temporary.mkdir(parents=True, exist_ok=True)
        process = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                TEST_PATH,
                "-q",
                "-rs",
                "--disable-warnings",
                "--basetemp",
                str(temporary),
            ],
            cwd=PROJECT,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        passed = re.search(r"(\d+) passed", process.stdout)
        if (
            process.returncode
            or passed is None
            or int(passed.group(1)) != TEST_EXPECTED_PASSED
        ):
            raise RuntimeError(
                f"content-draft current selection failed: {TEST_PATH}\n"
                f"{process.stdout}\n{process.stderr}"
            )
    return {
        "acceptance_id": ID,
        "decision": "accepted",
        "reproduction_path": "provider_connector_current_successor",
        "candidate_artifact_root_sha256": ROOT,
        "marker": MARKER,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
