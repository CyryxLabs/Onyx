"""Verify the external E6 acceptance for frozen Owner Profile V8."""

from __future__ import annotations

import hashlib
import importlib
import json
import platform
from pathlib import Path, PurePosixPath
import secrets
import stat
import sys


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-OWNER-PROFILE-V8-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-OWNER-PROFILE-V8-E6-001.sha256"
CORE = "core/owner_profile_v8.py"
TESTS = "tests/test_owner_profile_v8.py"
CANDIDATE_MANIFEST = "docs/onyx/checkpoints/owner-profile-v8/manifest.json"

CORE_SHA256 = "837295cfdf663dc97bf32592d186e0ba76ee74c83e1c757cfe420baea7dc0f3b"
TESTS_SHA256 = "b835c5d213dd9bc1e58065c700e180046da2918b06da18c6539ff1916f6d2642"
MANIFEST_SHA256 = "33f762cde3e23b00b0e89732b147b4aee28c68e6576fd38ba6c46c21c38b46c5"
ACCEPTANCE_MARKER = "OWNER_PROFILE_V8_ACCEPTANCE_OK"
_REPARSE_ATTRIBUTE = 0x400

HISTORICAL = {
    1: (
        "b2296227bb165f32117978e234519430af15838ad757104eeba08b8b7751b754",
        "fafdf46a0a716f09aca81668ffda0b566af369be4d89095dc1be0a02209ee035",
    ),
    2: (
        "12c459c1d34376a121e7a837d6dbeca365967c69affdc12b7d3e18ea1c76cd73",
        "76f0481f91b82b650ece00d86ad0bfffe21fa4020e46d8e3dcaaaf7e36832714",
    ),
    3: (
        "abf5e990b875a4ed04e9e9fed15eb550f972facf02b060683aa1e3abe88e4d16",
        "f327a01f7d82a5df2d5e05d2bde70e3b89f06c6c4f69011e0ee257521033fe38",
    ),
    4: (
        "a3ab381ed50c6fd539b10775ce0058b51c5a06b89bd87b1156e6793f6f438fd5",
        "ee57cc1f0b629f72cbdd8f7d53bc2fd78451a7524995c5eac74d6e60d043d5f0",
    ),
    5: (
        "53f6de7dfb7eb1f15f4f5c309257219a2ce67af7a662f0bb7e267fd1644daa18",
        "1a4f9e2dcd5ec4ca1e3f4ff0390200ce56a6705dceb5499203d34a45dbab36ad",
    ),
    6: (
        "f5bc62f7c326acea61ff8e2508814cbbbd7ac2c4833b2bcccb5353d44c530e0d",
        "72d44825c927704faae4f46802820babf89e4645d7cf16b33dc923289a155df1",
    ),
    7: (
        "6976ee481a9e494f4fa16548ac1d6a4eb8f5c160753cef3114b4d647220114e7",
        "79f416d5d279b32e74279bcd981fbbe777b0f7886824e82149d6179b392d9466",
    ),
}


class OwnerProfileV8AcceptanceError(RuntimeError):
    """The external acceptance or one of its immutable anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or "\x00" in relative
    ):
        raise OwnerProfileV8AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if (
        parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise OwnerProfileV8AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise OwnerProfileV8AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise OwnerProfileV8AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise OwnerProfileV8AcceptanceError(
                f"acceptance ancestor is unavailable: {relative}"
            ) from exc
        if part not in entries:
            raise OwnerProfileV8AcceptanceError(
                f"acceptance path is missing or case-mismatched: {relative}"
            )
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise OwnerProfileV8AcceptanceError(
                f"acceptance path is unavailable: {relative}"
            ) from exc
        if (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        ):
            raise OwnerProfileV8AcceptanceError(
                f"acceptance path uses a link/reparse point: {relative}"
            )
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise OwnerProfileV8AcceptanceError(
                f"acceptance path leaves the project: {relative}"
            ) from exc
        if resolved.name != part:
            raise OwnerProfileV8AcceptanceError(
                f"acceptance path uses a name alias: {relative}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise OwnerProfileV8AcceptanceError(
                f"acceptance ancestor is not a directory: {relative}"
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        raise OwnerProfileV8AcceptanceError(
            f"acceptance leaf is not a regular file: {relative}"
        )
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise OwnerProfileV8AcceptanceError(
            f"cannot read acceptance path: {relative}"
        ) from exc


def _text(project: Path, relative: str) -> str:
    raw = _bytes(project, relative)
    try:
        value = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise OwnerProfileV8AcceptanceError(
            f"acceptance text is not UTF-8: {relative}"
        ) from exc
    if "\r" in value or not value.endswith("\n"):
        raise OwnerProfileV8AcceptanceError(
            f"acceptance text is not canonical LF: {relative}"
        )
    return value


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_digest(project: Path, relative: str, expected: str) -> None:
    actual = _digest(project, relative)
    if actual != expected:
        raise OwnerProfileV8AcceptanceError(
            f"acceptance anchor drifted: {relative}: expected {expected}, got {actual}"
        )


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1:
        raise OwnerProfileV8AcceptanceError(
            "acceptance manifest must contain exactly one record"
        )
    line = lines[0]
    if len(line) < 67 or line[64:66] != "  ":
        raise OwnerProfileV8AcceptanceError("acceptance manifest record is malformed")
    digest, relative = line[:64], line[66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise OwnerProfileV8AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    manifest_digest, manifest_path = _manifest_line(_text(project, ACCEPTANCE_MANIFEST))
    if manifest_path != ACCEPTANCE_RECORD:
        raise OwnerProfileV8AcceptanceError(
            "acceptance manifest points to an unexpected record"
        )
    record_digest = _digest(project, ACCEPTANCE_RECORD)
    if record_digest != manifest_digest:
        raise OwnerProfileV8AcceptanceError(
            "external acceptance record does not match its manifest"
        )
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED - Owner Profile V8 only, frozen Windows candidate handoff",
        CORE_SHA256,
        TESTS_SHA256,
        MANIFEST_SHA256,
        "P0=0, P1=0, P2=0, P3=0",
        "17 passed, 0 failed",
        "201 passed, 15 subtests passed, 0 failed",
        "real isolated Windows primitive gate: **PASS**",
        "V8 remains isolated, default-off and unwired",
        "macOS Keychain or Linux Secret Service",
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise OwnerProfileV8AcceptanceError(
            f"acceptance record is missing required binding: {missing[0]}"
        )
    return record_digest


def _verify_candidate(project: Path) -> dict[str, int]:
    for relative, expected in (
        (CORE, CORE_SHA256),
        (TESTS, TESTS_SHA256),
        (CANDIDATE_MANIFEST, MANIFEST_SHA256),
    ):
        _require_digest(project, relative, expected)
    try:
        manifest = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise OwnerProfileV8AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("schema") != "onyx.owner-profile-candidate-bundle.v8"
        or manifest.get("candidate") != "owner-profile-v8"
        or manifest.get("isolated") is not True
        or manifest.get("default_off") is not True
        or manifest.get("live_wired") is not False
    ):
        raise OwnerProfileV8AcceptanceError(
            "candidate manifest does not retain the frozen default-off contract"
        )
    files = manifest.get("files")
    if files != [
        {"path": CORE, "sha256": CORE_SHA256},
        {"path": TESTS, "sha256": TESTS_SHA256},
    ]:
        raise OwnerProfileV8AcceptanceError("candidate file closure is malformed")
    history = manifest.get("preserved_rejected_candidates")
    if type(history) is not list or len(history) != 7:
        raise OwnerProfileV8AcceptanceError("historical candidate closure is malformed")
    for version, entry in enumerate(history, 1):
        expected_core, expected_tests = HISTORICAL[version]
        if (
            type(entry) is not dict
            or entry.get("candidate") != f"owner-profile-v{version}"
            or entry.get("core_sha256") != expected_core
            or entry.get("tests_sha256") != expected_tests
        ):
            raise OwnerProfileV8AcceptanceError(
                f"historical V{version} binding is malformed"
            )
        _require_digest(project, f"core/owner_profile_v{version}.py", expected_core)
        _require_digest(
            project, f"tests/test_owner_profile_v{version}.py", expected_tests
        )
    sequence = manifest.get("sequence_protocol")
    lease = manifest.get("lease_protocol")
    verification = manifest.get("verification")
    if (
        type(sequence) is not dict
        or sequence.get("maximum_terminal_sequence") != (1 << 63) - 1
        or sequence.get("terminal_increment") != 2
        or sequence.get("overflow_preflight")
        != "rejected before PREPARED and before config, memory, journal, or chain-head writes"
        or type(lease) is not dict
        or lease.get("required_port") != "HostTransactionLease.hold"
        or lease.get("anchor_cas_retained") is not True
        or type(verification) is not dict
        or verification.get("focused_v8") != {"passed": 17, "failed": 0}
        or verification.get("live_surface_imports") != 0
    ):
        raise OwnerProfileV8AcceptanceError(
            "candidate protocol or verification declaration drifted"
        )
    cumulative = verification.get("cumulative_v1_v2_v3_v4_v5_v6_v7_v8_memory_store")
    if cumulative != {"passed": 201, "subtests_passed": 15, "failed": 0}:
        raise OwnerProfileV8AcceptanceError(
            "candidate cumulative verification declaration drifted"
        )
    forbidden = (
        ACCEPTANCE_ID,
        ACCEPTANCE_RECORD,
        ACCEPTANCE_MANIFEST,
        "scripts/verify_owner_profile_v8_acceptance.py",
        "tests/test_owner_profile_v8_acceptance.py",
    )
    candidate_manifest_text = _text(project, CANDIDATE_MANIFEST)
    if any(item in candidate_manifest_text for item in forbidden):
        raise OwnerProfileV8AcceptanceError(
            "external acceptance path entered the frozen candidate root"
        )
    return {"candidate_files": len(files), "historical_candidates": len(history)}


def _verify_unwired(project: Path) -> int:
    live_paths = ["main.py", "ui.py"]
    # Scan executable/configuration source surfaces only. ``runtime`` is a
    # mutable data root (including pytest basetemps and user-created links),
    # so treating it as application source makes this provider-free static
    # check depend on unrelated process residue.
    roots = (
        "actions",
        "config",
        "core",
        "dashboard",
        "memory",
        "packaging",
        "qml",
    )
    suffixes = {
        ".html",
        ".ini",
        ".iss",
        ".js",
        ".json",
        ".py",
        ".pyw",
        ".ps1",
        ".qml",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    for root_name in roots:
        root = project / root_name
        if not root.is_dir():
            continue
        live_paths.extend(
            path.relative_to(project).as_posix()
            for path in sorted(root.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in suffixes
            and path.relative_to(project).as_posix() != CORE
        )
    needles = ("owner_profile_v8", "ONYX_OWNER_PROFILE_V8")
    wired: list[str] = []
    for relative in live_paths:
        try:
            value = _bytes(project, relative).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise OwnerProfileV8AcceptanceError(
                f"live surface is not UTF-8: {relative}"
            ) from exc
        if any(needle in value for needle in needles):
            wired.append(relative)
    if wired:
        raise OwnerProfileV8AcceptanceError(
            f"Owner Profile V8 entered a live surface: {wired[0]}"
        )
    return len(live_paths)


def _verify_windows_primitives(project: Path = PROJECT) -> dict[str, object]:
    if platform.system() != "Windows":
        return {"status": "not-run-non-windows", "platform": platform.system()}
    project_text = str(project.resolve(strict=True))
    inserted = not sys.path or sys.path[0] != project_text
    if inserted:
        sys.path.insert(0, project_text)
    namespace_confirmed_empty = False
    store = None
    reference = None
    owner = None
    native_vault = None
    try:
        profile = importlib.import_module("core.owner_profile_v8")
        native_vault = importlib.import_module("core.native_vault")
        if Path(profile.__file__).resolve(strict=True) != (project / CORE).resolve(
            strict=True
        ):
            raise OwnerProfileV8AcceptanceError(
                "Windows primitive gate imported a non-authoritative candidate"
            )
        owner = "acceptance-" + secrets.token_hex(16)
        store = profile.WindowsCredentialChainHeadStore(timeout_seconds=2.0)
        reference = store._reference(owner)
        if store.load(owner) is not None:
            raise OwnerProfileV8AcceptanceError(
                "unique Windows acceptance namespace was unexpectedly occupied"
            )
        namespace_confirmed_empty = True
        genesis = profile.genesis_head(owner)
        if store.compare_and_set(owner, None, genesis) is not True:
            raise OwnerProfileV8AcceptanceError(
                "Windows genesis compare-and-set did not commit"
            )
        if store.load(owner) != genesis:
            raise OwnerProfileV8AcceptanceError("Windows genesis readback diverged")
        terminal = profile.ChainHead(genesis.version, owner, 2, "1" * 64)
        if store.compare_and_set(owner, genesis, terminal) is not True:
            raise OwnerProfileV8AcceptanceError(
                "Windows terminal compare-and-set did not commit"
            )
        if store.load(owner) != terminal:
            raise OwnerProfileV8AcceptanceError("Windows terminal readback diverged")
        return {
            "status": "pass",
            "platform": "Windows",
            "global_named_mutex": True,
            "credential_manager_cas": True,
            "terminal_sequence": 2,
        }
    except OwnerProfileV8AcceptanceError:
        raise
    except Exception as exc:
        raise OwnerProfileV8AcceptanceError(
            "real Windows owner-profile primitive gate failed"
        ) from exc
    finally:
        cleanup_error: Exception | None = None
        if (
            namespace_confirmed_empty
            and store is not None
            and reference is not None
            and owner is not None
            and native_vault is not None
        ):
            try:
                native_vault.windows_delete(reference)
                if store.load(owner) is not None:
                    cleanup_error = OwnerProfileV8AcceptanceError(
                        "temporary Windows acceptance chain head was not deleted"
                    )
            except Exception as exc:
                cleanup_error = exc
            try:
                if native_vault.windows_get(reference) is not None:
                    cleanup_error = OwnerProfileV8AcceptanceError(
                        "temporary Windows acceptance credential was not deleted"
                    )
            except Exception as exc:
                cleanup_error = cleanup_error or exc
        if inserted and sys.path and sys.path[0] == project_text:
            sys.path.pop(0)
        if cleanup_error is not None:
            raise OwnerProfileV8AcceptanceError(
                "temporary Windows acceptance credential cleanup failed"
            ) from cleanup_error


def verify(
    project: Path = PROJECT, *, run_windows_primitives: bool = True
) -> dict[str, object]:
    project = Path(project)
    record_sha256 = _verify_record(project)
    closure = _verify_candidate(project)
    live_files = _verify_unwired(project)
    windows = (
        _verify_windows_primitives(project)
        if run_windows_primitives
        else {"status": "not-requested"}
    )
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": record_sha256,
        "core_sha256": CORE_SHA256,
        "tests_sha256": TESTS_SHA256,
        "manifest_sha256": MANIFEST_SHA256,
        "closure": closure,
        "live_files_checked": live_files,
        "windows_primitives": windows,
        "scope": "owner-profile-v8-isolated-default-off-unwired-windows-handoff",
    }


def main() -> int:
    payload = verify()
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(payload, sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
