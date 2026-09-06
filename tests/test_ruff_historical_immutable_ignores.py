from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tomllib

from scripts.verify_legacy_evidence_retirement_v1 import artifact_retirement
from scripts import verify_phase5_exit_retirement_v1 as exit_retirement
from scripts import verify_r11_projection_retirement_v1 as r11_retirement


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "ruff.toml"
LEDGER = ROOT / "docs/onyx/checkpoints/LEGACY_EVIDENCE_RETIREMENT_V1.json"
ALLOWED_CODES = {
    "E401",
    "E402",
    "E701",
    "E702",
    "E703",
    "F401",
    "F811",
    "S102",
    "S310",
    "S314",
    "S602",
}
ALLOWED_EXTEND_EXCLUDE = {".audit-temp-*", ".cert-final-*", ".pytest-*"}
RELEASE_V54_SHA256 = "c56bc179a032e5b0f94905b040e37aca8dd27413205c608b58f33eca5e6da739"
RELEASE_V54_RECEIPT_SHA256 = "3ad5117879277e3616ab1677fef6446ca7ceff6bf6251374aa0052f799afa84d"
SHA_LINE = re.compile(r"^([0-9a-f]{64})  ([!-~]+)$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _registered_hashes() -> dict[str, set[str]]:
    registered: dict[str, set[str]] = {}
    for manifest in (ROOT / "docs/onyx").rglob("*.sha256"):
        for line in manifest.read_text(encoding="utf-8").splitlines():
            match = SHA_LINE.fullmatch(line)
            if match is not None:
                registered.setdefault(match.group(2), set()).add(match.group(1))

    def collect(value: object) -> None:
        if isinstance(value, dict):
            relative, digest = value.get("path"), value.get("sha256")
            if (
                isinstance(relative, str)
                and isinstance(digest, str)
                and HEX64.fullmatch(digest)
            ):
                registered.setdefault(relative, set()).add(digest)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for manifest in (ROOT / "docs/onyx").rglob("*.json"):
        collect(json.loads(manifest.read_text(encoding="utf-8")))

    # V54 is an immutable predecessor record that binds exact release paths,
    # including the preserved exit-retirement verifier. Authenticate the
    # transition directly through its receipt and predecessor so this lint
    # contract never depends on the globally current successor or mutable
    # ``main.py``.
    transition_path = ROOT / "tests/fixtures/release_workflow_transition_v54.json"
    predecessor_path = ROOT / "tests/fixtures/release_workflow_transition_v53.json"
    receipt_path = ROOT / "docs/onyx/checkpoints/RELEASE_WORKFLOW_V54_VERIFIER_RECEIPT.json"
    transition = json.loads(transition_path.read_text(encoding="utf-8"))
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert transition["schema"] == "onyx.release-workflow-transition.v54"
    assert receipt["schema"] == "onyx.release-workflow-v54-verifier-receipt.v1"
    assert _sha256(transition_path) == RELEASE_V54_SHA256
    assert _sha256(receipt_path) == RELEASE_V54_RECEIPT_SHA256
    assert _sha256(transition_path) == receipt["release_sha256"]
    assert _sha256(predecessor_path) == transition["predecessor"]["sha256"]
    assert receipt["predecessor_sha256"] == transition["predecessor"]["sha256"]
    transition_paths = {
        entry["path"]: entry["sha256"] for entry in transition["current_release_paths"]
    }
    for relative, digest in transition_paths.items():
        registered.setdefault(relative, set()).add(digest)

    phase5_transition_path = exit_retirement.CURRENT_TRANSITION_V54
    phase5_predecessor_path = exit_retirement.CURRENT_TRANSITION_V53
    assert _sha256(phase5_transition_path) == exit_retirement.CURRENT_TRANSITION_V54_SHA256
    assert _sha256(phase5_predecessor_path) == exit_retirement.CURRENT_TRANSITION_V53_SHA256
    phase5_transition = json.loads(phase5_transition_path.read_text(encoding="utf-8"))
    assert phase5_transition["schema"] == "onyx.phase5-current-successor-transition.v54"
    assert phase5_transition["predecessor"]["sha256"] == _sha256(
        phase5_predecessor_path
    )
    for entry in phase5_transition["historical_bindings"]:
        registered.setdefault(entry["path"], set()).add(entry["current_sha256"])
    # Current reviewed source may legitimately succeed historical bytes. Keep
    # every old receipt above, but authenticate current exceptions against the
    # real candidate rather than invoking a stale globally-current V56 gate.
    # The allowlisted codes, exact paths and isolated-finding checks below are
    # unchanged; no new lint exception is granted by this source transition.
    from scripts.verify_release_workflow_v101 import verify_release_workflow_v101

    current = verify_release_workflow_v101(ROOT)
    assert current["publishable"] is False
    assert current["formal_release_ready"] is False
    for entry in current["transition"]["current_release_paths"]:
        registered.setdefault(entry["path"], set()).add(entry["sha256"])
    return registered


def _ignored() -> dict[str, set[str]]:
    value = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    raw = value["lint"]["per-file-ignores"]
    return {relative: set(codes) for relative, codes in raw.items()}


def test_extend_exclude_is_the_exact_transient_policy() -> None:
    value = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    assert set(value["extend-exclude"]) == ALLOWED_EXTEND_EXCLUDE
    assert all(pattern.startswith(".") and pattern.endswith("-*") for pattern in ALLOWED_EXTEND_EXCLUDE)


def test_every_ignore_is_exact_minimal_and_hash_authenticated() -> None:
    ignored = _ignored()
    assert ignored
    assert all(codes and codes <= ALLOWED_CODES for codes in ignored.values())
    assert all(
        str(PurePosixPath(relative)) == relative
        and not PurePosixPath(relative).is_absolute()
        and not any(character in relative for character in "*?[]\\")
        for relative in ignored
    )

    registered = _registered_hashes()
    ledger = json.loads(LEDGER.read_text(encoding="utf-8"))
    retired = {record["path"]: record for record in ledger["artifacts"]}
    exit_bindings: dict[str, dict[str, object]] | None = None
    r11_successors: dict[str, dict[str, object]] | None = None
    for relative in ignored:
        path = ROOT.joinpath(*PurePosixPath(relative).parts)
        assert path.is_file() and not path.is_symlink()
        digest = _sha256(path)
        if digest in registered.get(relative, set()):
            continue
        if relative in retired:
            record = retired[relative]
            result = artifact_retirement(
                ROOT,
                relative,
                record["historical_sha256"],
                historical_bytes=record["historical_bytes"],
            )
            assert result["disposition"].endswith("-not-rebound")
        else:
            if r11_successors is None:
                r11_successors = {
                    record["path"]: record
                    for record in r11_retirement.load_retirement_record()[
                        "implementation_successors"
                    ]
                }
            if relative in r11_successors:
                record = r11_successors[relative]
                assert digest == record["current_sha256"]
                assert record["historical_sha256"] != digest
                continue
            if exit_bindings is None:
                exit_bindings = {
                    record["path"]: record
                    for record in exit_retirement.load_record()["bindings"]
                }
            if relative in exit_bindings:
                record = exit_bindings[relative]
                assert (
                    exit_retirement.classify(
                        ROOT, relative, str(record["historical_sha256"])
                    )
                    == "archived-exact"
                )
                exit_retirement.authenticate_successor(record["successor"])
                continue
            raise AssertionError(f"unregistered immutable Ruff exception: {relative}")


def test_every_exception_matches_an_exact_isolated_ruff_finding() -> None:
    ignored = _ignored()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--no-cache",
            "--isolated",
            "--select",
            ",".join(sorted(ALLOWED_CODES)),
            "--output-format",
            "json",
            *ignored,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1, result.stderr
    findings: dict[str, set[str]] = {relative: set() for relative in ignored}
    for finding in json.loads(result.stdout):
        relative = (
            Path(finding["filename"]).resolve().relative_to(ROOT.resolve()).as_posix()
        )
        assert relative in ignored
        findings[relative].add(finding["code"])
    assert findings == ignored
