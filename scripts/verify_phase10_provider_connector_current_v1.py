"""Verify the Phase 10 Provider Connector CURRENT source-integrity successor.

The accepted 2026-07-25 module bytes drifted post-acceptance (see
docs/onyx/corrections/CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md).
This successor binds the CURRENT bytes — the ones every candidate tree from
V34 through the released V53 R15B carries — without rewriting the historical
acceptance, whose own verifier correctly fails closed against the current
tree and is retained as the historical record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from core import phase10_provider_connector_v1 as candidate  # noqa: E402

MARKER = "P10_PROVIDER_CONNECTOR_CURRENT_V1_OK"
CORRECTION = (
    "docs/onyx/corrections/"
    "CORRECTION-P10-PROVIDER-CONNECTOR-POST-ACCEPTANCE-DRIFT.md"
)
HISTORICAL_ACCEPTANCE = "VE-P10-PROVIDER-CONNECTOR-V1-E6-001"
CURRENT_MODULE_SHA = (
    "327f7d949ae764b6e3353e258500bc4a3ccc9f2bc87637f27b12bdbff71cb588"
)
CURRENT_MODULE_BYTES = 15989
CURRENT_ROOT = "90139dd8b2856a6d778356b64a747d851e5320afe2241401b7150cf9499d9054"
HISTORICAL_MANIFEST = (
    PROJECT / "docs/onyx/checkpoints/phase10-provider-connector-v1/manifest.json"
)
# The historical acceptance four-file tuple must stay byte-exact — the
# successor supersedes current-state reproduction, never the record.
HISTORICAL_PINS = (
    (
        "docs/onyx/checkpoints/phase10-provider-connector-v1/manifest.json",
        "87b3ed60dd533f29e3b42447ada20846dda231f8b5f5478da59c9d7e1d822d0c",
    ),
    (
        "docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-V1-E6-001.md",
        "c5a68dc99acb0c102de42c9434907ab6619423efa04e87ab5299bba195043cfe",
    ),
    (
        "docs/onyx/acceptance/VE-P10-PROVIDER-CONNECTOR-V1-E6-001.manifest.json",
        "e84e22f6af91a32a70ee3cb8464aa471c7fada3ab30d5a74ce6cb54bfb77535e",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-PROVIDER-CONNECTOR-V1-E6-001.sha256",
        "b2d49c458659af647e844663f470e0510b9f837954f9a358161c7618eb1be6ab",
    ),
)
TEST_PATH = "tests/test_phase10_provider_connector_v1.py"
TEST_EXPECTED_PASSED = 32


class VerificationError(RuntimeError):
    pass


def _digest(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise VerificationError("artifact unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(records: dict[str, str]) -> str:
    return hashlib.sha256(
        "".join(
            sorted(f"{path}\0{digest}\n" for path, digest in records.items())
        ).encode()
    ).hexdigest()


def verify(*, run_tests: bool = True) -> dict[str, object]:
    if not (PROJECT / CORRECTION).is_file():
        raise VerificationError("drift correction record unavailable")
    for relative, expected in HISTORICAL_PINS:
        if _digest(PROJECT / relative) != expected:
            raise VerificationError("historical acceptance evidence drift")

    module = PROJECT / "core/phase10_provider_connector_v1.py"
    if (
        _digest(module) != CURRENT_MODULE_SHA
        or module.stat().st_size != CURRENT_MODULE_BYTES
    ):
        raise VerificationError("current successor module drift")

    manifest = json.loads(HISTORICAL_MANIFEST.read_text(encoding="utf-8"))
    observed: dict[str, str] = {}
    for item in manifest["artifacts"]:
        observed[item["path"]] = _digest(PROJECT / item["path"])
    if _root(observed) != CURRENT_ROOT:
        raise VerificationError("current successor root drift")

    if candidate.ProviderConnectorFeatureGateV1.from_environ({}).enabled is not False:
        raise VerificationError("feature gate is not default-off")

    source = module.read_text(encoding="utf-8")
    for required in (
        'FEATURE_FLAG: Final = "ONYX_PHASE10_PROVIDER_CONNECTOR_V1"',
        "class ProviderConnectorSessionV1",
        "def fetch_account_status",
        "expected_handle",
        "ProviderConnectorV1Denied",
    ):
        if required not in source:
            raise VerificationError("source invariant drift")
    for forbidden in ("import requests", "subprocess", "def publish", "def schedule"):
        if forbidden in source:
            raise VerificationError("authority invariant drift")

    if run_tests:
        temporary = (
            PROJECT
            / "runtime/test-tmp/p10-provider-current-verify"
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
            raise VerificationError(
                f"successor selection failed: {TEST_PATH}\n"
                f"{process.stdout}\n{process.stderr}"
            )
    return {
        "candidate": "phase10-provider-connector-current-v1",
        "decision": "accepted_current_successor",
        "historical_acceptance": HISTORICAL_ACCEPTANCE,
        "correction": CORRECTION,
        "candidate_artifact_root_sha256": CURRENT_ROOT,
        "feature_flag": candidate.FEATURE_FLAG,
        "marker": MARKER,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-tests", action="store_true")
    result = verify(run_tests=not parser.parse_args().no_tests)
    print(json.dumps(result, sort_keys=True))
    print(MARKER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
