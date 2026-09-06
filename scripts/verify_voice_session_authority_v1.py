"""Reproduce the Guild Project Envelope V1 candidate."""

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
from core import voice_session_authority_v1 as candidate  # noqa: E402
from scripts import (  # noqa: E402
    verify_guild_project_envelope_v1_acceptance as predecessor,
)

BASE = PROJECT / "docs/onyx/checkpoints/voice-session-authority-v1"
MANIFEST = BASE / "manifest.json"
SELECTION = BASE / "cumulative-selection.json"
MARKER = "VOICE_SESSION_AUTHORITY_V1_OK"
ACCEPTED_PREDECESSOR_ROOT = (
    "438fe075ca88e31e588b4e04dc087ab9e58fce5c3fabdfa658a1dc199ad60874"
)
ARTIFACT_PATHS = (
    "core/voice_session_authority_v1.py",
    "tests/test_voice_session_authority_v1.py",
    "scripts/verify_voice_session_authority_v1.py",
    "docs/onyx/adrs/ADR-0061-voice-session-authority-v1.md",
    "docs/onyx/research/VOICE_SESSION_AUTHORITY_V1_SOURCES.md",
    "docs/onyx/checkpoints/voice-session-authority-v1/"
    "VOICE_SESSION_AUTHORITY_V1_CHECKPOINT.md",
    "docs/onyx/checkpoints/voice-session-authority-v1/CAPABILITY_DELTA_SNAPSHOT.md",
    "docs/onyx/checkpoints/voice-session-authority-v1/cumulative-selection.json",
)


class VerificationError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, object]:
    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise VerificationError("duplicate JSON key")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    if type(value) is not dict:
        raise VerificationError("JSON object required")
    return value


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
    manifest = _json(MANIFEST)
    if (
        manifest.get("schema") != "onyx.voice-session-authority.v1"
        or manifest.get("candidate") != "voice-session-authority-v1"
        or manifest.get("feature_flag") != candidate.FEATURE_FLAG
        or manifest.get("default_off") is not True
        or manifest.get("status") != "candidate_e1_e5_e6_pending"
    ):
        raise VerificationError("manifest identity drift")

    predecessor_record = predecessor.verify(run_tests=False)
    if (
        predecessor_record.get("decision") != "accepted"
        or predecessor_record.get("candidate_artifact_root_sha256")
        != ACCEPTED_PREDECESSOR_ROOT
    ):
        raise VerificationError("accepted predecessor entry drift")

    if (
        candidate.VoiceSessionAuthorityFeatureGateV1.from_environ({}).enabled
        is not False
    ):
        raise VerificationError("feature gate is not default-off")

    # The always-explicit set is the safety argument of this slice: it must
    # keep deferring even with a live envelope over matching roots. Deletion
    # inside an authorized root is included deliberately.
    probe = candidate.create_voice_session_authority_v1("liberar trabalho onyx")
    probe.open_from_transcript(
        "onyx liberar trabalho onyx",
        [r"C:\VerifyRoot"],
        envelope_id="verify",
        now_ms=1_000,
        lifetime_ms=60_000,
        operation_cap=5,
    )
    for tool, action in (
        ("file_controller", "delete"),
        ("browser_control", "go_to"),
        ("computer_control", "click"),
        ("desktop_control", "wallpaper"),
        ("send_message", "send"),
    ):
        if probe.evaluate(
            tool, action, {"path": r"C:\VerifyRoot\x"}, 1_000
        ).outcome != "defer":
            raise VerificationError(f"always-explicit drift: {tool}.{action}")
    if probe.evaluate(
        "file_controller", "read", {"path": r"C:\VerifyRoot2\x"}, 1_000
    ).outcome != "defer":
        raise VerificationError("root containment drift")
    if probe.evaluate(
        "file_controller", "read", {"path": r"C:\VerifyRoot\x"}, 1_000
    ).outcome != "allow":
        raise VerificationError("envelope grants nothing")
    probe.engage_kill_switch()
    if probe.evaluate(
        "file_controller", "read", {"path": r"C:\VerifyRoot\x"}, 1_000
    ).outcome != "deny":
        raise VerificationError("kill switch drift")
    if candidate.MAX_LIFETIME_MS > 8 * 60 * 60 * 1000:
        raise VerificationError("lifetime ceiling drift")
    if ("file_controller", "delete") not in candidate.ALWAYS_EXPLICIT:
        raise VerificationError("delete left the always-explicit set")

    artifacts = manifest.get("artifacts")
    if type(artifacts) is not list or len(artifacts) != len(ARTIFACT_PATHS):
        raise VerificationError("artifact closure drift")
    observed: dict[str, str] = {}
    for expected_path, item in zip(ARTIFACT_PATHS, artifacts, strict=True):
        if type(item) is not dict or item.get("path") != expected_path:
            raise VerificationError("artifact order drift")
        path = PROJECT / expected_path
        digest = _digest(path)
        if item.get("sha256") != digest or item.get("bytes") != path.stat().st_size:
            raise VerificationError("artifact hash drift")
        observed[expected_path] = digest
    if manifest.get("artifact_root_sha256") != _root(observed):
        raise VerificationError("artifact root drift")

    source = (PROJECT / "core/voice_session_authority_v1.py").read_text(
        encoding="utf-8"
    )
    for required in (
        'FEATURE_FLAG: Final = "ONYX_VOICE_SESSION_AUTHORITY_V1"',
        "class VoiceSessionAuthorityV1",
        "ALWAYS_EXPLICIT",
        "def engage_kill_switch",
        "ACCEPTED EXPOSURE",
    ):
        if required not in source:
            raise VerificationError("source invariant drift")
    for forbidden in (
        "import requests",
        "urllib",
        "socket",
        "subprocess",
        "time.time",
        "datetime.now",
        "monotonic",
    ):
        if forbidden in source:
            raise VerificationError("authority invariant drift")

    selection = _json(SELECTION)
    expected = {
        "test_files": 35,
        "passed": 977,
        "failed": 0,
        "errors": 0,
        "skipped": 17,
        "subtests_passed": 96,
    }
    tests = selection.get("tests")
    if (
        selection.get("expected") != expected
        or manifest.get("verification") != expected
        or type(tests) is not list
        or len(tests) != 35
    ):
        raise VerificationError("selection drift")
    if (
        sum(item["passed"] for item in tests) != expected["passed"]
        or sum(item["skipped"] for item in tests) != expected["skipped"]
        or sum(item["subtests_passed"] for item in tests) != expected["subtests_passed"]
    ):
        raise VerificationError("selection per-file sum drift")
    if run_tests:
        temporary = (
            PROJECT
            / "runtime/test-tmp/voice-session-authority-v1-verify"
            / f"run-{secrets.token_hex(8)}"
        )
        temporary.mkdir(parents=True, exist_ok=True)
        for index, item in enumerate(tests, start=1):
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    item["path"],
                    "-q",
                    "-rs",
                    "--disable-warnings",
                    "--basetemp",
                    str(temporary / str(index)),
                ],
                cwd=PROJECT,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
            passed = re.search(r"(\d+) passed", process.stdout)
            skipped = re.search(r"(\d+) skipped", process.stdout)
            subtests = re.search(r"(\d+) subtests passed", process.stdout)
            if (
                process.returncode
                or passed is None
                or int(passed.group(1)) != item["passed"]
                or (int(skipped.group(1)) if skipped else 0) != item["skipped"]
                or (int(subtests.group(1)) if subtests else 0)
                != item["subtests_passed"]
            ):
                raise VerificationError(
                    f"selection failed: {item['path']}\n"
                    f"{process.stdout}\n{process.stderr}"
                )
    return {
        "candidate": "voice-session-authority-v1",
        "artifact_root_sha256": manifest["artifact_root_sha256"],
        "feature_flag": candidate.FEATURE_FLAG,
        "results": expected,
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
