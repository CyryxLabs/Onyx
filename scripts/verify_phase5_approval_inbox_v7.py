"""Freeze and verify Phase 5.2 Approval Inbox V7 candidate evidence."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import pytest


PROJECT = Path(__file__).resolve().parents[1]
TOP_MANIFEST = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V7-001.sha256"
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V7-001.sha256"
EVIDENCE_DIR = "docs/onyx/checkpoints/phase5-approval-inbox-v7"
CHECKPOINT = f"{EVIDENCE_DIR}/PHASE5_2_APPROVAL_INBOX_V7_CHECKPOINT.md"
BUNDLE = f"{EVIDENCE_DIR}/phase5-approval-inbox-v7.bundle.json"
JUNIT = f"{EVIDENCE_DIR}/phase5-approval-inbox-v7.junit.xml"
RAW_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v7.raw.log"
STATIC_LOG = f"{EVIDENCE_DIR}/phase5-approval-inbox-v7.static.log"
LIVE_SCAN_MANIFEST = f"{EVIDENCE_DIR}/phase5-approval-inbox-v7.live-scan.sha256"

V1_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V1-001.sha256"
V1_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V1-001.sha256"
V1_VERIFIER = "scripts/verify_phase5_approval_inbox_v1.py"
V2_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V2-001.sha256"
V2_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V2-001.sha256"
V2_VERIFIER = "scripts/verify_phase5_approval_inbox_v2.py"
V3_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V3-001.sha256"
V3_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V3-001.sha256"
V3_VERIFIER = "scripts/verify_phase5_approval_inbox_v3.py"
V4_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V4-001.sha256"
V4_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V4-001.sha256"
V5_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V5-001.sha256"
V5_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V5-001.sha256"
V5_VERIFIER = "scripts/verify_phase5_approval_inbox_v5.py"
V6_ROOT = "docs/onyx/VE-SOURCE-P52-APPROVAL-INBOX-V6-001.sha256"
V6_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P52-APPROVAL-INBOX-V6-001.sha256"
V6_VERIFIER = "scripts/verify_phase5_approval_inbox_v6.py"
R11_ROOT = "docs/onyx/VE-SOURCE-P51-GRANTS-R11-001.sha256"
R11_ARTIFACT = "docs/onyx/VE-ARTIFACTS-P51-GRANTS-R11-001.sha256"
R11_ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-P51-GRANTS-R11-E6-001.sha256"
R11_ACCEPTANCE = "docs/onyx/acceptance/VE-P51-GRANTS-R11-E6-001.md"
R11_VERIFIER = "scripts/verify_phase5_grants_r11.py"
R11_EXTRA_LIVE = (".github/workflows/release-packages.yml",)
V1_SHA256 = {
    V1_ROOT: "c0a2a7d4d0314d2b061b826463ac9bf6828bc27a0e7ef00dd0d47ab55d19ced8",
    V1_ARTIFACT: "d67c15e1644fd1de16d485714509ca11ec01f458a1464f7457378a00f6c82e21",
    V1_VERIFIER: "ed2cb194492943f70722d203e896d52088a772b3b9651b2a6c800daa8f98d029",
    "core/approval_inbox_v1.py": "01435dee3c5f2122afa05245efac73950b78fe50264c372b53ca61dabc9ad560",
    "tests/test_approval_inbox_v1.py": "605be42da065683e5b107372b4cade271e32ec7002526520dda3a7db947efcaf",
}
V2_SHA256 = {
    V2_ROOT: "29e57a20191c2de46c4bae9476a5e072b7eddb2c9f941897b24b3a6f7d90e54d",
    V2_ARTIFACT: "cc3673ad29e69d8658ca75ffac4cc28279c1b6ca0a63d6b080bd17037f233930",
    "core/approval_inbox_v2.py": "99e29e8d65f35d7abea147e06aeffb5bd1db1b96953c816d4d8967b3f061dabe",
    "tests/test_approval_inbox_v2.py": "c8eac6ccc263ef1f278ad75443eead8aab681c466a823c4414550d0319c44805",
    V2_VERIFIER: "2024016da88ab94d81942c716c948b6b6b4c1dfb78eddcb7ffcda19d6f8e5a56",
}
V3_SHA256 = {
    V3_ROOT: "a780f95c0e8b2b5236ed424e4382e0be1691600d24a08a490d58be942ba149c8",
    V3_ARTIFACT: "bb86dd76bdfc94603bae7c556827062f3a0a65183bd2f3ce65ede620ad9a7192",
    "core/approval_inbox_v3.py": "af4ff749a49867fa47b6d773e8a47d4c82bcb0bad04ad3394bedb9cb4f5d05cb",
    "tests/test_approval_inbox_v3.py": "a2a1721b172a1a23c69590690059aba046b2a60f6354939df1a142ff97858606",
    V3_VERIFIER: "599533f7836b7dc18556758f914d00da0c1755595c6df8dd88040e60195c9db9",
}
V4_SHA256 = {
    V4_ROOT: "a67ffe30ca3c173823ecc061e8c0d0c0a57c0896bf0f0970bf78df8e14178351",
    V4_ARTIFACT: "db4ed6b5a229116168d2abd50743763a2839ff2ae0a49d0ee82bcf5f74aefde1",
    "core/approval_inbox_v4.py": "f517774cfad4931348cfc7326831bdeb68ace1b54dc9cbd685b2a004aa38c66d",
    "tests/test_approval_inbox_v4.py": "5c7db679e0675a00e0782f2a170e5d6e8df6d9867f9ca92225cb510a1eea3873",
    "scripts/verify_phase5_approval_inbox_v4.py": "da97a9348a9765ba0283e811ca59921b783c10f0cf24194afd7bda1d6d9d22ec",
    "scripts/check_phase5_approval_inbox_v4_whitespace.py": "ae456c28cfc7d42468b5c65ffe2575beba3435c9779b236a755aa30f1372ec31",
}
V5_SHA256 = {
    V5_ROOT: "e4c1ed861d51f3d0fb6d72bc82d6c01675efc5a630d795e2d053030221d11feb",
    V5_ARTIFACT: "f9c8c116d0facce83e6404c011c0dea5468314c8589227e5c4903e0e5cbc6108",
    "core/approval_inbox_v5.py": "353244a9a7b83bd79625a4f8df47582b4885dc9958647f1d4b4e5968c4d143d6",
    "tests/test_approval_inbox_v5.py": "4c9bbe9b6b49381fa092fbf99f345f484d6502bdf5401b4f6f841af3a66ce346",
    V5_VERIFIER: "93d51b079e8ba8736147d0c09cff18fb65a94dba3bd28c08cb1458266b440967",
    "scripts/check_phase5_approval_inbox_v5_whitespace.py": "e0e83165db713ea8e62b45134d683c488db2019223362daef658706082c98a17",
}
V6_SHA256 = {
    V6_ROOT: "1c8250b69c9cc006a4d2bc80babe85b256884d584c5eb08c73d5473acdfc6d21",
    V6_ARTIFACT: "178b56813c4c9c9dade23c79df1ca7181e99e3b0600b84a99b340a84163844a1",
    "core/approval_inbox_v6.py": "6978defb139ea86def1d1ce42550e82652435e9cb2b2ac7e0f90e10610b38ecf",
    "tests/test_approval_inbox_v6.py": "d7255530c95f3be46d2b15a688225d4a0106b78d6385189da45856b1bdcaf978",
    V6_VERIFIER: "755d75de078052ec933f731763cbe679d5f62d1b95ad337da28cc21fe8326d5b",
    "scripts/check_phase5_approval_inbox_v6_whitespace.py": "29dde13224e0fb4e835b3cff76b8479033ccbb918392c7d8c74b0daa3b6126a2",
}
R11_SHA256 = {
    R11_ROOT: "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071",
    R11_ARTIFACT: "0253aba6b0fed67bbac6b1eda55ea32a9928f44b036b2fbc0c5daec78e0b33d7",
    R11_ACCEPTANCE_MANIFEST: "36fb198e27ebb7e8e8bb97885d8a823d2a291ed573da3d5513d950715b113bb0",
    R11_ACCEPTANCE: "ff703416675653b4f1611e7f9ee633fac974c3bdf4225a16d84f302233b824d4",
}

SOURCE_SEEDS = (
    "core/approval_inbox_v7.py",
    "scripts/check_phase5_approval_inbox_v7_whitespace.py",
    "scripts/verify_phase5_approval_inbox_v7.py",
    "tests/test_approval_inbox_v7.py",
)
NORMATIVE_SEEDS = (
    "docs/onyx/APPROVAL_POLICY.md",
    "docs/onyx/IMPLEMENTATION_ROADMAP.md",
    "plans/onyx-advanced-entity-redesign.md",
)
LIVE_ROOTS = (
    "main.py",
    "ui.py",
    "actions",
    "core",
    "dashboard",
    "memory",
    "packaging",
    "qml",
    "runtime",
    "scripts",
)
LIVE_SUFFIXES = frozenset(
    {".desktop", ".html", ".iss", ".js", ".json", ".plist", ".py", ".pyw", ".qml", ".spec", ".toml", ".yaml", ".yml"}
)
LIVE_EXCLUDED_PARTS = frozenset(
    {"__pycache__", ".pytest_cache", "evidence", "evidences", "test", "tests"}
)
FROZEN_APPROVAL_PATHS = frozenset(
    {f"core/approval_inbox_v{version}.py" for version in range(1, 8)}
)
STARTUP_ROOTS = ("main.py", "ui.py", "scripts/launch_onyx.pyw")
_APPROVAL_MODULE = re.compile(r"approval_inbox_v[0-9]+\.py\Z", re.I)
_MARKDOWN_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z0-9_./-]+\.md)(?=$|[#)`\]\s,:;])",
    re.I,
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_RAW_PASS = re.compile(r"(?m)^(\d+) passed in ([0-9]+(?:\.[0-9]+)?)s$")

EXPECTED_TEST_COUNT = 92
REQUIRED_TESTS = frozenset(
    {
        "test_strict_default_off_has_no_clock_or_source_callback",
        "test_explicit_host_composition_is_pinned_but_not_claimed_as_same_process_secrecy",
        "test_read_apis_accept_no_source_items_or_authority_fields",
        "test_exact_source_output_types_only_no_subclass_or_custom_mapping",
        "test_bounds_are_checked_before_any_item_traversal_or_copy_hook",
        "test_raw_callback_exception_is_not_chained_or_recoverable",
        "test_complete_review_fields_are_immutable_non_authority_and_digest_internal",
        "test_source_timestamps_are_metadata_not_token_validity",
        "test_refreshed_source_timestamp_metadata_same_epoch_does_not_latch",
        "test_projection_owned_deadline_expires_without_source_callback_and_never_resurrects",
        "test_monotonic_clock_rollback_latches_and_cannot_resurrect",
        "test_same_epoch_equivocation_latches_and_restore_never_resurrects",
        "test_epoch_rollback_latches_and_restore_never_resurrects",
        "test_integrity_latch_is_nonresurrecting_across_concurrent_callers",
        "test_query_sort_page_size_and_allowed_ids_are_bound_into_view_and_token",
        "test_batch_cannot_select_hidden_workspace_or_filtered_item",
        "test_pagination_is_stable_exact_set_without_duplicate_or_omission",
        "test_source_drift_cannot_mix_pages",
        "test_calm_batch_canonical_reorder_add_remove_substitute_and_non_authority",
        "test_page_size_one_requires_second_item_to_be_returned_before_batch",
        "test_review_token_substitution_cross_view_and_restart_replay_fail_closed",
        "test_reopening_identical_view_preserves_previously_returned_review_proofs",
        "test_batch_preview_contains_complete_human_review_fields",
        "test_host_cannot_mislabel_high_or_always_explicit_as_batch_eligible",
        "test_batch_forbids_wildcards_categories_duplicates_and_unbounded_sequences",
        "test_outer_token_validation_occurs_before_hmac_and_normalizes_all_malformed_inputs",
        "test_encode_rejects_incomplete_or_noncanonical_payload_before_hmac",
        "test_valid_hmac_with_malformed_payload_normalizes_to_stale",
        "test_tampered_token_and_restart_old_token_fail_before_source_callback",
        "test_source_concurrency_is_capped_at_one_and_excess_fails_closed",
        "test_source_callbacks_never_run_under_projection_lock",
        "test_result_constructors_reject_forged_or_contradictory_inputs",
        "test_limits_and_bounded_snapshot_view_caches",
        "test_no_mutation_grant_import_persistence_or_live_wiring",
        "test_v1_v2_v3_v4_v5_v6_and_r11_frozen_anchor_bytes_remain_exact",
        "test_r11_transitive_tamper_fixture_rejects_v10_before_recursive_execution",
        "test_v2_transitive_tamper_fixture_rejects_core_v2",
        "test_v3_transitive_tamper_fixture_rejects_core_v3",
        "test_v5_transitive_tamper_fixture_rejects_core_v5",
        "test_v6_transitive_tamper_fixture_rejects_core_v6",
        "test_future_approval_successor_import_indirection_is_rejected",
    }
)
REQUIRED_PREFIX_COUNTS = {
    "test_every_recoverable_display_field_rejects_secrets[": 11,
    "test_high_critical_always_explicit_or_ineligible_never_enters_batch[": 4,
    "test_unknown_identity_safety_and_schema_state_fail_closed[": 7,
    "test_regenerated_hashes_cannot_bypass_semantic_metadata[": 4,
    "test_reopening_conflicting_registered_view_state_latches_fail_closed[": 2,
    "test_literal_dynamic_approval_imports_are_rejected[": 3,
    "test_relative_importlib_wiring_is_resolved_and_rejected[": 2,
    "test_unresolvable_relative_dynamic_imports_fail_closed[": 5,
    "test_future_v8_loader_forms_fail_closed[": 13,
}


class Phase52V7EvidenceError(RuntimeError):
    pass


def _path(relative: str, root: Path = PROJECT) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise Phase52V7EvidenceError(f"unsafe evidence path: {relative}")
    return root / Path(*pure.parts)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def derive_limits(root: Path = PROJECT) -> dict[str, int]:
    tree = ast.parse(_path("core/approval_inbox_v7.py", root).read_text(encoding="utf-8"))
    limits: dict[str, int] = {}
    for node in tree.body:
        if (
            type(node) is ast.Assign
            and len(node.targets) == 1
            and type(node.targets[0]) is ast.Name
            and node.targets[0].id.startswith("MAX_")
        ):
            name = node.targets[0].id
            if type(node.value) is not ast.Constant or type(node.value.value) is not int:
                raise Phase52V7EvidenceError(f"limit is not a literal integer: {name}")
            if node.value.value <= 0 or name.casefold() in limits:
                raise Phase52V7EvidenceError(f"limit declaration is invalid: {name}")
            limits[name.casefold()] = node.value.value
    if not limits:
        raise Phase52V7EvidenceError("V7 declares no bounded limits")
    return {name: limits[name] for name in sorted(limits)}


def _identity(command: list[str], root: Path = PROJECT) -> str:
    result = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    value = (result.stdout + result.stderr).strip()
    if result.returncode or not value or "\n" in value or "\r" in value:
        raise Phase52V7EvidenceError(f"static tool identity unavailable: {command[0]}")
    return value


def current_base_commit(root: Path = PROJECT) -> str:
    value = _identity(["git", "-C", str(root), "rev-parse", "HEAD"], root).casefold()
    if not _HEX40.fullmatch(value):
        raise Phase52V7EvidenceError("current git base commit is invalid")
    return value


def actual_environment(root: Path = PROJECT) -> dict[str, object]:
    return {
        "executable": str(Path(sys.executable).resolve()),
        "platform": platform.platform(),
        "pytest": pytest.__version__,
        "python": platform.python_version(),
        "static_tools": {
            "compile": f"py_compile:{platform.python_version()}",
            "diff_check": _identity(["git", "--version"], root),
            "ruff": _identity([sys.executable, "-m", "ruff", "--version"], root),
            "whitespace_checker_sha256": _sha(
                _path("scripts/check_phase5_approval_inbox_v7_whitespace.py", root)
            ),
        },
    }


def _parse_iso_timestamp(value: object, label: str) -> datetime:
    if type(value) is not str or not value or value.endswith("Z"):
        raise Phase52V7EvidenceError(f"{label} is not canonical ISO-8601")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise Phase52V7EvidenceError(f"{label} is not canonical ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.isoformat() != value:
        raise Phase52V7EvidenceError(f"{label} is not canonical ISO-8601")
    return parsed


def canonical_evidence_timestamp(junit_timestamp: object) -> str:
    parsed = _parse_iso_timestamp(junit_timestamp, "JUnit timestamp")
    return parsed.astimezone(timezone.utc).isoformat()


def validate_semantic_metadata(
    bundle: dict[str, object],
    junit_timestamp: str,
    root: Path = PROJECT,
) -> None:
    if bundle.get("limits") != derive_limits(root):
        raise Phase52V7EvidenceError("bundle limits do not match V7 code constants")
    if bundle.get("base_commit") != current_base_commit(root):
        raise Phase52V7EvidenceError("bundle base commit does not match current git HEAD")
    if bundle.get("environment") != actual_environment(root):
        raise Phase52V7EvidenceError("bundle environment/static tool identity drifted")
    expected_timestamp = canonical_evidence_timestamp(junit_timestamp)
    if bundle.get("timestamp") != expected_timestamp:
        raise Phase52V7EvidenceError("bundle timestamp is not derived from focused JUnit")


def _write(relative: str, content: bytes) -> None:
    path = _path(relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def _parse_manifest(
    relative: str,
    expected: tuple[str, ...] | None = None,
    root: Path = PROJECT,
) -> tuple[tuple[str, str], ...]:
    raw = _path(relative, root).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V7EvidenceError(f"manifest is noncanonical: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        digest, separator, path = line.partition("  ")
        if not separator or not _HEX64.fullmatch(digest):
            raise Phase52V7EvidenceError(f"manifest line is malformed: {relative}")
        _path(path, root)
        entries.append((digest, path))
    paths = tuple(path for _digest, path in entries)
    if not entries or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise Phase52V7EvidenceError(f"manifest order/set is invalid: {relative}")
    if expected is not None and paths != expected:
        raise Phase52V7EvidenceError(f"manifest exact set drifted: {relative}")
    return tuple(entries)


def _verify_entries(entries: tuple[tuple[str, str], ...], root: Path = PROJECT) -> None:
    for expected, relative in entries:
        path = _path(relative, root)
        if not path.is_file() or _sha(path) != expected:
            raise Phase52V7EvidenceError(f"artifact digest drifted: {relative}")


def _manifest_bytes(paths: tuple[str, ...]) -> bytes:
    return "".join(f"{_sha(_path(relative))}  {relative}\n" for relative in paths).encode()


def _historical_manifest_entries(
    relative: str,
    root: Path = PROJECT,
) -> tuple[tuple[str, str], ...]:
    """Read legacy ordering without weakening V7's own strict manifests."""
    raw = _path(relative, root).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V7EvidenceError(f"historical manifest is malformed: {relative}")
    entries: list[tuple[str, str]] = []
    for line in raw.decode("utf-8").splitlines():
        digest, separator, referenced = line.partition("  ")
        if not separator or not _HEX64.fullmatch(digest):
            raise Phase52V7EvidenceError(f"historical manifest line is malformed: {relative}")
        _path(referenced, root)
        entries.append((digest, referenced))
    references = tuple(referenced for _digest, referenced in entries)
    if not references or len(references) != len(set(references)):
        raise Phase52V7EvidenceError(f"historical manifest set is invalid: {relative}")
    return tuple(entries)


def _historical_manifest_references(relative: str) -> tuple[str, ...]:
    return tuple(
        referenced
        for _digest, referenced in _historical_manifest_entries(relative)
    )


def verify_historical_manifest_tree(
    root: Path,
    roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Verify every transitive legacy-manifest edge before recursive execution."""
    queue: list[tuple[str | None, str]] = [(None, relative) for relative in roots]
    visited_manifests: set[str] = set()
    verified: set[str] = set()
    while queue:
        expected, relative = queue.pop(0)
        path = _path(relative, root)
        if not path.is_file():
            raise Phase52V7EvidenceError(f"historical artifact missing: {relative}")
        if expected is not None and _sha(path) != expected:
            raise Phase52V7EvidenceError(f"historical artifact digest drifted: {relative}")
        verified.add(relative)
        if relative.endswith(".sha256") and relative not in visited_manifests:
            visited_manifests.add(relative)
            queue.extend(_historical_manifest_entries(relative, root))
    return tuple(sorted(verified))


def materialize_manifest_tree(
    destination: Path,
    roots: tuple[str, ...],
) -> tuple[str, ...]:
    """Copy only frozen manifest-reachable files; successor files stay absent."""
    destination.mkdir(parents=True, exist_ok=True)
    queue = list(roots)
    copied: set[str] = set()
    while queue:
        relative = queue.pop(0)
        if relative in copied:
            continue
        source = _path(relative)
        if not source.is_file():
            raise Phase52V7EvidenceError(f"frozen materialization source missing: {relative}")
        target = _path(relative, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.add(relative)
        if relative.endswith(".sha256"):
            for referenced in _historical_manifest_references(relative):
                if referenced not in copied:
                    queue.append(referenced)
    git_dir = PROJECT / ".git"
    if git_dir.is_dir():
        (destination / ".git").write_text(
            f"gitdir: {git_dir.resolve().as_posix()}\n", encoding="utf-8"
        )
    return tuple(sorted(copied))


def materialize_r11(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(
        destination,
        (R11_ROOT, R11_ACCEPTANCE_MANIFEST, *R11_EXTRA_LIVE),
    )


def materialize_v1(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V1_ROOT,))


def materialize_v2(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V2_ROOT,))


def materialize_v3(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V3_ROOT,))


def materialize_v5(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V5_ROOT,))


def materialize_v6(destination: Path) -> tuple[str, ...]:
    return materialize_manifest_tree(destination, (V6_ROOT,))


def execute_frozen_verifier(root: Path, relative: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    scripts = PROJECT / ".venv" / "Scripts"
    environment["PATH"] = str(scripts) + os.pathsep + environment.get("PATH", "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    bundle_relative = {
        R11_VERIFIER: "docs/onyx/checkpoints/phase5-grants-r11/phase5-grants-r11.bundle.json",
        V1_VERIFIER: "docs/onyx/checkpoints/phase5-approval-inbox-v1/phase5-approval-inbox-v1.bundle.json",
        V2_VERIFIER: "docs/onyx/checkpoints/phase5-approval-inbox-v2/phase5-approval-inbox-v2.bundle.json",
        V3_VERIFIER: "docs/onyx/checkpoints/phase5-approval-inbox-v3/phase5-approval-inbox-v3.bundle.json",
        V5_VERIFIER: "docs/onyx/checkpoints/phase5-approval-inbox-v5/phase5-approval-inbox-v5.bundle.json",
        V6_VERIFIER: "docs/onyx/checkpoints/phase5-approval-inbox-v6/phase5-approval-inbox-v6.bundle.json",
    }.get(relative)
    if bundle_relative is None:
        raise Phase52V7EvidenceError("unknown frozen verifier")
    bundle = json.loads(_path(bundle_relative, root).read_text(encoding="utf-8"))
    executable = bundle.get("environment", {}).get("executable")
    if type(executable) is not str or not Path(executable).is_file():
        raise Phase52V7EvidenceError("frozen verifier interpreter is unavailable")
    return subprocess.run(
        [executable, str(_path(relative, root))],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900 if relative == V6_VERIFIER else 720 if relative == V5_VERIFIER else 360,
        env=environment,
    )


def verify_r11_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-r11-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_r11(root)
        verify_historical_manifest_tree(
            root,
            (R11_ROOT, R11_ACCEPTANCE_MANIFEST),
        )
        result = execute_frozen_verifier(root, R11_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive R11 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v1_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-v1-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v1(root)
        result = execute_frozen_verifier(root, V1_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive V1 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v2_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-v2-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v2(root)
        verify_historical_manifest_tree(root, (V2_ROOT,))
        result = execute_frozen_verifier(root, V2_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive V2 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v3_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-v3-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v3(root)
        verify_historical_manifest_tree(root, (V3_ROOT,))
        result = execute_frozen_verifier(root, V3_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive V3 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v5_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-v5-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v5(root)
        verify_historical_manifest_tree(root, (V5_ROOT,))
        result = execute_frozen_verifier(root, V5_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive V5 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def verify_v6_recursively() -> str:
    with tempfile.TemporaryDirectory(
        prefix=".onyx-p52-v7-v6-", dir=PROJECT
    ) as directory:
        root = Path(directory)
        materialize_v6(root)
        verify_historical_manifest_tree(root, (V6_ROOT,))
        result = execute_frozen_verifier(root, V6_VERIFIER)
        if result.returncode:
            raise Phase52V7EvidenceError(
                "recursive V6 verifier failed\n" + result.stdout + result.stderr
            )
        return result.stdout.strip()


def _resolve_module(parts: tuple[str, ...]) -> tuple[str, ...]:
    candidates: list[str] = []
    for index in range(1, len(parts)):
        initializer = f"{'/'.join(parts[:index])}/__init__.py"
        if _path(initializer).is_file():
            candidates.append(initializer)
    relative = "/".join(parts)
    for candidate in (f"{relative}/__init__.py", f"{relative}.py"):
        if _path(candidate).is_file():
            candidates.append(candidate)
    return tuple(candidates)


def local_import_closure() -> tuple[str, ...]:
    found = set(SOURCE_SEEDS)
    queue = list(SOURCE_SEEDS)
    while queue:
        relative = queue.pop(0)
        try:
            tree = ast.parse(_path(relative).read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Phase52V7EvidenceError(f"source dependency cannot be parsed: {relative}") from exc
        package = tuple(PurePosixPath(relative).parts[:-1])
        for node in ast.walk(tree):
            targets: list[tuple[str, ...]] = []
            if isinstance(node, ast.Import):
                targets.extend(tuple(alias.name.split(".")) for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    base = package[: max(0, len(package) - node.level + 1)] + base
                targets.append(base)
                targets.extend(base + tuple(alias.name.split(".")) for alias in node.names if alias.name != "*")
            for target in targets:
                for dependency in _resolve_module(tuple(part for part in target if part)):
                    if dependency not in found:
                        found.add(dependency)
                        queue.append(dependency)
    return tuple(sorted(found))


def _normalize_reference(value: PurePosixPath) -> str | None:
    parts: list[str] = []
    for part in value.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) or None


def normative_graph() -> dict[str, list[str]]:
    found = set(NORMATIVE_SEEDS)
    queue = list(NORMATIVE_SEEDS)
    graph: dict[str, list[str]] = {}
    while queue:
        relative = queue.pop(0)
        text = _path(relative).read_text(encoding="utf-8")
        references: set[str] = set()
        for raw in _MARKDOWN_REFERENCE.findall(text):
            pure = PurePosixPath(raw.replace("\\", "/"))
            candidates = (
                (pure,) if raw.startswith(("docs/", "plans/")) else (PurePosixPath(relative).parent / pure, pure)
            )
            for candidate in candidates:
                normalized = _normalize_reference(candidate)
                if normalized and normalized.endswith(".md") and _path(normalized).is_file():
                    references.add(normalized)
                    break
        references.discard(relative)
        graph[relative] = sorted(references)
        for reference in graph[relative]:
            if reference not in found:
                found.add(reference)
                queue.append(reference)
    return {key: graph[key] for key in sorted(graph)}


def _module_map(paths: tuple[str, ...]) -> dict[str, str]:
    modules: dict[str, str] = {}
    for relative in paths:
        pure = PurePosixPath(relative)
        if pure.suffix.casefold() not in {".py", ".pyw"}:
            continue
        parts = list(pure.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        if parts:
            modules[".".join(parts)] = relative
    return modules


def _canonical_module_name(value: str, relative: str) -> str:
    if (
        not value
        or value.startswith(".")
        or any(not part.isidentifier() for part in value.split("."))
    ):
        raise Phase52V7EvidenceError(
            f"dynamic import module name is invalid: {relative}"
        )
    return value


def _dynamic_import_name(node: ast.Call, loader: str, relative: str) -> str:
    positional = list(node.args)
    if any(type(argument) is ast.Starred for argument in positional):
        raise Phase52V7EvidenceError(
            f"dynamic import arguments cannot be verified: {relative}"
        )
    if loader == "importlib.import_module":
        if len(positional) > 2:
            raise Phase52V7EvidenceError(
                f"dynamic import signature is invalid: {relative}"
            )
        name_node = positional[0] if positional else None
        package_node = positional[1] if len(positional) == 2 else None
        for keyword in node.keywords:
            if keyword.arg is None or keyword.arg not in {"name", "package"}:
                raise Phase52V7EvidenceError(
                    f"dynamic import signature is invalid: {relative}"
                )
            if keyword.arg == "name":
                if name_node is not None:
                    raise Phase52V7EvidenceError(
                        f"dynamic import name is duplicated: {relative}"
                    )
                name_node = keyword.value
            else:
                if package_node is not None:
                    raise Phase52V7EvidenceError(
                        f"dynamic import package is duplicated: {relative}"
                    )
                package_node = keyword.value
        if (
            type(name_node) is not ast.Constant
            or type(name_node.value) is not str
            or not name_node.value
        ):
            raise Phase52V7EvidenceError(
                f"nonliteral dynamic import name cannot be verified: {relative}"
            )
        name = name_node.value
        if package_node is not None and (
            type(package_node) is not ast.Constant
            or (
                package_node.value is not None
                and type(package_node.value) is not str
            )
        ):
            raise Phase52V7EvidenceError(
                f"nonliteral dynamic import package cannot be verified: {relative}"
            )
        if name.startswith("."):
            if (
                package_node is None
                or type(package_node) is not ast.Constant
                or type(package_node.value) is not str
                or not package_node.value
            ):
                raise Phase52V7EvidenceError(
                    f"relative dynamic import lacks a literal package: {relative}"
                )
            package = _canonical_module_name(package_node.value, relative)
            try:
                name = importlib.util.resolve_name(name, package)
            except (ImportError, ValueError) as exc:
                raise Phase52V7EvidenceError(
                    f"relative dynamic import cannot be resolved: {relative}"
                ) from exc
        return _canonical_module_name(name, relative)

    if (
        not positional
        or type(positional[0]) is not ast.Constant
        or type(positional[0].value) is not str
        or not positional[0].value
        or positional[0].value.startswith(".")
    ):
        raise Phase52V7EvidenceError(
            f"nonliteral dynamic import cannot be verified: {relative}"
        )
    return _canonical_module_name(positional[0].value, relative)


_MODULE_TAGS = {
    "builtins": "module:builtins",
    "importlib": "module:importlib",
    "runpy": "module:runpy",
}
_ATTRIBUTE_TAGS = {
    ("module:builtins", "__import__"): "builtins.__import__",
    ("module:builtins", "compile"): "code:compile",
    ("module:builtins", "eval"): "code:eval",
    ("module:builtins", "exec"): "code:exec",
    ("module:builtins", "getattr"): "builtin:getattr",
    ("module:importlib", "import_module"): "importlib.import_module",
    ("module:runpy", "run_module"): "runpy.run_module",
}
_SENSITIVE_TAGS = frozenset(
    {*_MODULE_TAGS.values(), *_ATTRIBUTE_TAGS.values(), "ambiguous"}
)


def _expression_tags(
    value: ast.AST,
    symbols: dict[str, frozenset[str]],
    relative: str,
) -> frozenset[str]:
    if type(value) is ast.Name:
        return symbols.get(value.id, frozenset())
    if type(value) is ast.Attribute:
        base = _expression_tags(value.value, symbols, relative)
        tags = {
            tag
            for module_tag in base
            if (tag := _ATTRIBUTE_TAGS.get((module_tag, value.attr))) is not None
        }
        if "ambiguous" in base and value.attr in {
            "__import__",
            "compile",
            "eval",
            "exec",
            "import_module",
            "run_module",
        }:
            tags.add("ambiguous")
        return frozenset(tags)
    if type(value) is ast.Call:
        callee = _expression_tags(value.func, symbols, relative)
        if "builtin:getattr" not in callee:
            return frozenset({"ambiguous"}) if "ambiguous" in callee else frozenset()
        if len(value.args) not in {2, 3} or value.keywords:
            raise Phase52V7EvidenceError(
                f"getattr loader expression cannot be verified: {relative}"
            )
        base = _expression_tags(value.args[0], symbols, relative)
        if not base & frozenset(_MODULE_TAGS.values()):
            return frozenset()
        attribute = value.args[1]
        if type(attribute) is not ast.Constant or type(attribute.value) is not str:
            raise Phase52V7EvidenceError(
                f"nonliteral loader attribute cannot be verified: {relative}"
            )
        tags = {
            tag
            for module_tag in base
            if (tag := _ATTRIBUTE_TAGS.get((module_tag, attribute.value))) is not None
        }
        if not tags:
            raise Phase52V7EvidenceError(
                f"unknown dynamic loader attribute cannot be verified: {relative}"
            )
        return frozenset(tags)
    return frozenset()


def _mentions_sensitive_loader(
    value: ast.AST, symbols: dict[str, frozenset[str]]
) -> bool:
    for node in ast.walk(value):
        if type(node) is ast.Name and symbols.get(node.id, frozenset()) & (
            _SENSITIVE_TAGS - {"builtin:getattr"}
        ):
            return True
        if type(node) is ast.Attribute and type(node.value) is ast.Name:
            base = symbols.get(node.value.id, frozenset())
            if any((module_tag, node.attr) in _ATTRIBUTE_TAGS for module_tag in base):
                return True
    return False


def _bind_symbol(
    symbols: dict[str, frozenset[str]],
    name: str,
    tags: frozenset[str],
    *,
    ambiguous_source: bool,
) -> None:
    previous = symbols.get(name, frozenset())
    if previous & _SENSITIVE_TAGS and previous != tags:
        symbols[name] = frozenset({"ambiguous"})
    elif tags:
        symbols[name] = tags
    elif ambiguous_source:
        symbols[name] = frozenset({"ambiguous"})
    else:
        symbols.pop(name, None)


def _import_targets(
    relative: str, text: str, modules: dict[str, str]
) -> tuple[str, ...]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        raise Phase52V7EvidenceError(f"startup source is invalid: {relative}") from exc
    current = PurePosixPath(relative).with_suffix("").parts
    package = list(current[:-1])
    targets: set[str] = set()
    symbols: dict[str, frozenset[str]] = {
        "__import__": frozenset({"builtins.__import__"}),
        "compile": frozenset({"code:compile"}),
        "eval": frozenset({"code:eval"}),
        "exec": frozenset({"code:exec"}),
        "getattr": frozenset({"builtin:getattr"}),
    }
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    nodes = sorted(
        ast.walk(tree),
        key=lambda node: (
            getattr(node, "lineno", -1),
            getattr(node, "col_offset", -1),
            0 if type(node) in {ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign} else 1,
        ),
    )
    for node in nodes:
        names: list[str] = []
        if type(node) is ast.Import:
            for alias in node.names:
                names.append(alias.name)
                root_name = alias.name.partition(".")[0]
                module_tag = _MODULE_TAGS.get(root_name)
                bound = alias.asname or root_name
                if module_tag is not None:
                    _bind_symbol(
                        symbols,
                        bound,
                        frozenset({module_tag}),
                        ambiguous_source=False,
                    )
        elif type(node) is ast.ImportFrom:
            if node.level:
                keep = max(0, len(package) - (node.level - 1))
                base = list(package[:keep])
            else:
                base = []
            if node.module:
                base.extend(node.module.split("."))
            if base:
                names.append(".".join(base))
                names.extend(".".join((*base, alias.name)) for alias in node.names)
            for alias in node.names:
                module_tag = _MODULE_TAGS.get(node.module or "")
                tag = (
                    _ATTRIBUTE_TAGS.get((module_tag, alias.name))
                    if module_tag is not None
                    else None
                )
                if tag is not None:
                    _bind_symbol(
                        symbols,
                        alias.asname or alias.name,
                        frozenset({tag}),
                        ambiguous_source=False,
                    )
        elif type(node) is ast.Assign:
            tags = _expression_tags(node.value, symbols, relative)
            ambiguous = _mentions_sensitive_loader(node.value, symbols) and not tags
            for target in node.targets:
                if type(target) is not ast.Name:
                    if tags or ambiguous:
                        raise Phase52V7EvidenceError(
                            "dynamic loader assignment cannot be verified: "
                            f"{relative}:{node.lineno}"
                        )
                    continue
                _bind_symbol(
                    symbols,
                    target.id,
                    tags,
                    ambiguous_source=ambiguous,
                )
        elif type(node) is ast.AnnAssign and type(node.target) is ast.Name:
            tags = (
                _expression_tags(node.value, symbols, relative)
                if node.value is not None
                else frozenset()
            )
            ambiguous = (
                node.value is not None
                and _mentions_sensitive_loader(node.value, symbols)
                and not tags
            )
            _bind_symbol(
                symbols,
                node.target.id,
                tags,
                ambiguous_source=ambiguous,
            )
        elif type(node) is ast.Call:
            tags = _expression_tags(node.func, symbols, relative)
            if "ambiguous" in tags or len(tags & _SENSITIVE_TAGS) > 1:
                raise Phase52V7EvidenceError(
                    "ambiguous dynamic loader call cannot be verified: "
                    f"{relative}:{node.lineno}"
                )
            loaders = tags & frozenset(
                {
                    "builtins.__import__",
                    "importlib.import_module",
                    "runpy.run_module",
                }
            )
            if loaders:
                names.append(
                    _dynamic_import_name(node, next(iter(loaders)), relative)
                )
            code_loaders = tags & frozenset({"code:compile", "code:eval", "code:exec"})
            if code_loaders:
                only_compile = code_loaders == {"code:compile"}
                discarded = type(parents.get(node)) is ast.Expr
                if not only_compile or not discarded:
                    raise Phase52V7EvidenceError(
                        f"reachable dynamic code loader cannot be verified: {relative}:{node.lineno}"
                    )
        for name in names:
            candidate = name
            while candidate:
                if candidate in modules:
                    targets.add(modules[candidate])
                    break
                candidate = candidate.rpartition(".")[0]
    return tuple(sorted(targets))


def verify_startup_import_boundaries(
    paths: tuple[str, ...], root: Path = PROJECT
) -> tuple[str, ...]:
    modules = _module_map(paths + tuple(sorted(FROZEN_APPROVAL_PATHS)))
    for frozen in FROZEN_APPROVAL_PATHS:
        path = _path(frozen, root)
        if path.is_file():
            module = ".".join(PurePosixPath(frozen).with_suffix("").parts)
            modules[module] = frozen
    launchers = set(STARTUP_ROOTS)
    for prefix in (root, root / "scripts"):
        if not prefix.is_dir():
            continue
        for candidate in prefix.iterdir():
            if candidate.is_file() and candidate.suffix.casefold() in {".py", ".pyw"}:
                if candidate.stem.casefold().startswith(("launch", "run_", "start_")):
                    launchers.add(candidate.relative_to(root).as_posix())
    queue = [relative for relative in sorted(launchers) if _path(relative, root).is_file()]
    reached: set[str] = set()
    while queue:
        relative = queue.pop(0)
        if relative in reached:
            continue
        reached.add(relative)
        if _APPROVAL_MODULE.fullmatch(PurePosixPath(relative).name):
            raise Phase52V7EvidenceError(
                f"approval inbox is reachable from startup: {relative}"
            )
        if PurePosixPath(relative).suffix.casefold() not in {".py", ".pyw"}:
            continue
        for target in _import_targets(
            relative, _path(relative, root).read_text(encoding="utf-8"), modules
        ):
            if target not in reached:
                queue.append(target)
    for relative in paths:
        if PurePosixPath(relative).suffix.casefold() not in {".py", ".pyw"}:
            continue
        targets = _import_targets(
            relative, _path(relative, root).read_text(encoding="utf-8"), modules
        )
        imported_approval = sorted(set(targets) & FROZEN_APPROVAL_PATHS)
        if imported_approval:
            raise Phase52V7EvidenceError(
                "source surface imports frozen approval inbox "
                f"{imported_approval[0]}: {relative}"
            )
    return tuple(sorted(reached))


def live_scan_paths(root: Path = PROJECT) -> tuple[str, ...]:
    found: set[str] = set()
    for relative_root in LIVE_ROOTS:
        path = _path(relative_root, root)
        candidates = (path,) if path.is_file() else path.rglob("*") if path.is_dir() else ()
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.casefold() not in LIVE_SUFFIXES:
                continue
            relative = candidate.relative_to(root).as_posix()
            parts = {part.casefold() for part in PurePosixPath(relative).parts}
            if (
                parts & LIVE_EXCLUDED_PARTS
                or relative in FROZEN_APPROVAL_PATHS
            ):
                continue
            found.add(relative)
    for candidate in root.iterdir():
        if (
            candidate.is_file()
            and candidate.suffix.casefold() in {".py", ".pyw"}
            and candidate.stem.casefold().startswith(("launch", "run_", "start_"))
        ):
            found.add(candidate.relative_to(root).as_posix())
    paths = tuple(sorted(found))
    if "scripts/launch_onyx.pyw" not in paths:
        raise Phase52V7EvidenceError("operational launcher is absent from live scan")
    verify_startup_import_boundaries(paths, root)
    return paths


def artifact_paths() -> tuple[str, ...]:
    return tuple(
        sorted(
            set(
                (
                    *local_import_closure(),
                    *normative_graph(),
                    *V1_SHA256,
                    *V2_SHA256,
                    *V3_SHA256,
                    *V4_SHA256,
                    *V5_SHA256,
                    *V6_SHA256,
                    *R11_SHA256,
                    *R11_EXTRA_LIVE,
                    CHECKPOINT,
                    BUNDLE,
                    JUNIT,
                    RAW_LOG,
                    STATIC_LOG,
                    LIVE_SCAN_MANIFEST,
                )
            )
        )
    )


def _junit() -> tuple[dict[str, int], str, set[str]]:
    try:
        document = ET.fromstring(_path(JUNIT).read_bytes())
    except (OSError, ET.ParseError) as exc:
        raise Phase52V7EvidenceError("JUnit is invalid") from exc
    suites = [document] if document.tag == "testsuite" else document.findall("testsuite")
    if len(suites) != 1:
        raise Phase52V7EvidenceError("JUnit must contain exactly one suite")
    suite = suites[0]
    cases = suite.findall("testcase")
    names = {case.attrib.get("name", "") for case in cases}
    errors = sum(case.find("error") is not None for case in cases)
    failed = sum(case.find("failure") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    counts = {"errors": errors, "failed": failed, "passed": len(cases) - errors - failed - skipped, "skipped": skipped}
    if len(cases) != EXPECTED_TEST_COUNT or counts != {"errors": 0, "failed": 0, "passed": EXPECTED_TEST_COUNT, "skipped": 0}:
        raise Phase52V7EvidenceError("focused JUnit count/result is invalid")
    if not REQUIRED_TESTS <= names:
        raise Phase52V7EvidenceError("focused JUnit lacks a required test")
    for prefix, expected in REQUIRED_PREFIX_COUNTS.items():
        if sum(name.startswith(prefix) for name in names) != expected:
            raise Phase52V7EvidenceError(f"focused parameter coverage drifted: {prefix}")
    timestamp = suite.attrib.get("timestamp", "")
    _parse_iso_timestamp(timestamp, "JUnit timestamp")
    return counts, timestamp, names


def _verify_static() -> dict[str, int]:
    expected = {
        "COMPILE": "0",
        "DIFF_CHECK": "0",
        "RUFF_F_E9": "0",
        "V6_RECURSIVE": "0",
        "WHITESPACE": "0",
    }
    raw = _path(STATIC_LOG).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V7EvidenceError("static log is noncanonical")
    values: dict[str, str] = {}
    for line in raw.decode().splitlines():
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise Phase52V7EvidenceError("static log shape is invalid")
        values[key] = value
    if values != expected:
        raise Phase52V7EvidenceError("static gates are not all green")
    return {key: int(values[key]) for key in sorted(values)}


def _verify_raw_log() -> dict[str, object]:
    raw = _path(RAW_LOG).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase52V7EvidenceError("focused raw log is noncanonical")
    text = raw.decode("utf-8")
    matches = _RAW_PASS.findall(text)
    if len(matches) != 1 or int(matches[0][0]) != EXPECTED_TEST_COUNT:
        raise Phase52V7EvidenceError("focused raw log pass claim is invalid")
    if " failed" in text.casefold() or " error" in text.casefold():
        raise Phase52V7EvidenceError("focused raw log contains a failure claim")
    return {
        "duration_seconds": matches[0][1],
        "passed": int(matches[0][0]),
    }


def _verify_live() -> tuple[str, ...]:
    paths = live_scan_paths()
    entries = _parse_manifest(LIVE_SCAN_MANIFEST, paths)
    _verify_entries(entries)
    return paths


def _verify_anchors() -> None:
    for relative, expected in {
        **V1_SHA256,
        **V2_SHA256,
        **V3_SHA256,
        **V4_SHA256,
        **V5_SHA256,
        **V6_SHA256,
        **R11_SHA256,
    }.items():
        if _sha(_path(relative)) != expected:
            raise Phase52V7EvidenceError(f"historical/accepted anchor drifted: {relative}")


def _read_bundle() -> dict[str, object]:
    raw = _path(BUNDLE).read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Phase52V7EvidenceError("bundle is invalid JSON") from exc
    if type(value) is not dict or raw != _canonical(value):
        raise Phase52V7EvidenceError("bundle is not canonical")
    return value


def verify(*, recursive: bool = True) -> dict[str, object]:
    _verify_anchors()
    if recursive:
        v6_output = verify_v6_recursively()
        if "P52_APPROVAL_INBOX_V6_FROZEN_OK" not in v6_output:
            raise Phase52V7EvidenceError("recursive V6 verifier did not report success")
    closure = local_import_closure()
    graph = normative_graph()
    expected_artifacts = artifact_paths()
    _verify_entries(_parse_manifest(TOP_MANIFEST, (ARTIFACT_MANIFEST,)))
    _verify_entries(_parse_manifest(ARTIFACT_MANIFEST, expected_artifacts))
    counts, timestamp, _names = _junit()
    static_gates = _verify_static()
    raw_summary = _verify_raw_log()
    live = _verify_live()
    bundle = _read_bundle()
    claims = {
        "bounds_before_traversal_no_arbitrary_copy_hooks": True,
        "callback_exception_secret_context_removed": True,
        "computed_result_digests_and_relational_invariants": True,
        "default_off_no_clock_or_source_callback": True,
        "exact_host_output_types_and_pinned_composition": True,
        "historical_v2_byte_exact_rejected": True,
        "historical_v3_byte_exact_rejected": True,
        "historical_v4_byte_exact_rejected": True,
        "historical_v5_byte_exact_rejected": True,
        "historical_v6_byte_exact_rejected": True,
        "historical_v1_byte_exact_rejected": True,
        "human_review_token_required_for_batch": True,
        "integrity_equivocation_rollback_permanent_latch": True,
        "local_monotonic_deadline_nonresurrection": True,
        "no_live_wiring_mutation_or_authority": True,
        "recursive_r11_v1_through_v10_verification": True,
        "recursive_v3_manifest_closure_verification": True,
        "recursive_v5_and_transitive_prior_verification": True,
        "recursive_v6_and_transitive_prior_verification": True,
        "reopened_identical_view_preserves_returned_review_proofs": True,
        "secret_free_complete_review_fields": True,
        "single_source_callback_concurrency_cap": True,
        "source_callbacks_outside_projection_lock": True,
        "source_timestamp_metadata_excluded_from_integrity_digest": True,
        "strict_token_parse_and_malformed_normalization": True,
        "semantic_evidence_metadata_independently_derived": True,
        "token_verified_internal_result_factories": True,
        "startup_import_walk_no_approval_reachability": True,
        "startup_import_walk_resolves_literal_dynamic_loaders": True,
        "startup_import_walk_resolves_relative_importlib_packages": True,
        "startup_import_walk_tracks_loader_aliases_getattr_builtins_and_code_loaders": True,
        "view_bound_query_sort_page_size_and_item_set": True,
        "view_scoped_exact_calm_batch_only": True,
    }
    files = {
        relative: _sha(_path(relative))
        for relative in expected_artifacts
        if relative != BUNDLE
    }
    expected_dag = {
        "artifact_points_to": list(expected_artifacts),
        "bundle_excludes_manifest_and_self_hashes": True,
        "root": TOP_MANIFEST,
        "root_points_to": [ARTIFACT_MANIFEST],
    }
    if bundle.get("contract") != "Phase52ApprovalInboxEvidence.v7" or bundle.get("status") != "candidate-default-off-not-accepted":
        raise Phase52V7EvidenceError("bundle contract/status is invalid")
    if bundle.get("counts") != counts or bundle.get("junit_timestamp") != timestamp:
        raise Phase52V7EvidenceError("bundle test evidence drifted")
    expected_test_evidence = {
        "junit_timestamp": timestamp,
        "raw_summary": raw_summary,
        "static_gates": static_gates,
    }
    if bundle.get("test_evidence") != expected_test_evidence:
        raise Phase52V7EvidenceError("bundle JUnit/raw/static claims drifted")
    if bundle.get("claims") != claims or bundle.get("files") != files:
        raise Phase52V7EvidenceError("bundle claims/files drifted")
    if bundle.get("dependency_closure") != list(closure) or bundle.get("normative_graph") != graph:
        raise Phase52V7EvidenceError("bundle dependency/normative closure drifted")
    if bundle.get("live_scan_paths") != list(live) or bundle.get("dag") != expected_dag:
        raise Phase52V7EvidenceError("bundle live/DAG closure drifted")
    if bundle.get("history") != {
        "phase51_r11": {"decision": "accepted-default-off", "anchors": R11_SHA256},
        "phase52_v1": {"decision": "historical-rejected", "anchors": V1_SHA256},
        "phase52_v2": {"decision": "historical-rejected", "anchors": V2_SHA256},
        "phase52_v3": {"decision": "historical-rejected", "anchors": V3_SHA256},
        "phase52_v4": {"decision": "historical-rejected", "anchors": V4_SHA256},
        "phase52_v5": {"decision": "historical-rejected", "anchors": V5_SHA256},
        "phase52_v6": {"decision": "historical-rejected", "anchors": V6_SHA256},
    }:
        raise Phase52V7EvidenceError("bundle history claim drifted")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise Phase52V7EvidenceError("bundle external acceptance status is invalid")
    if bundle.get("feature_flag") != {"default": False, "name": "ONYX_APPROVAL_INBOX_V7"}:
        raise Phase52V7EvidenceError("bundle feature flag claim is invalid")
    validate_semantic_metadata(bundle, timestamp)
    print(
        "P52_APPROVAL_INBOX_V7_FROZEN_OK "
        f"tests={counts['passed']} artifacts={len(expected_artifacts)} "
        f"dependencies={len(closure)} normative={len(graph)} live={len(live)} "
        "v6_recursive=ok transitive_v5_r11_v1_v2_v3=ok"
    )
    return bundle


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=PROJECT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
    )


def freeze() -> None:
    _verify_anchors()
    _path(EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    focused = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            "-q",
            "tests/test_approval_inbox_v7.py",
            f"--junitxml={JUNIT}",
        ]
    )
    raw = (focused.stdout + focused.stderr).replace("\r\n", "\n").replace("\r", "\n")
    _write(RAW_LOG, raw.encode())
    if focused.returncode:
        raise Phase52V7EvidenceError("focused tests failed during freeze")
    commands = {
        "RUFF_F_E9": [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "F,E9",
            *SOURCE_SEEDS,
        ],
        "COMPILE": [sys.executable, "-m", "py_compile", *SOURCE_SEEDS],
        "WHITESPACE": [sys.executable, "scripts/check_phase5_approval_inbox_v7_whitespace.py"],
        "DIFF_CHECK": ["git", "diff", "--check", "--", *SOURCE_SEEDS],
    }
    gates: dict[str, int] = {}
    detail = ""
    for name, command in commands.items():
        result = _run(command)
        gates[name] = result.returncode
        detail += result.stdout + result.stderr
    try:
        verify_v6_recursively()
        gates["V6_RECURSIVE"] = 0
    except Phase52V7EvidenceError as exc:
        gates["V6_RECURSIVE"] = 1
        detail += str(exc)
    if any(gates.values()):
        raise Phase52V7EvidenceError(f"static gate failed: {gates}\n{detail}")
    _write(STATIC_LOG, "".join(f"{key}={gates[key]}\n" for key in sorted(gates)).encode())

    live = live_scan_paths()
    _write(LIVE_SCAN_MANIFEST, _manifest_bytes(live))
    counts, timestamp, _names = _junit()
    static_gates = _verify_static()
    raw_summary = _verify_raw_log()
    closure = local_import_closure()
    graph = normative_graph()
    paths = artifact_paths()
    claims = {
        "bounds_before_traversal_no_arbitrary_copy_hooks": True,
        "callback_exception_secret_context_removed": True,
        "computed_result_digests_and_relational_invariants": True,
        "default_off_no_clock_or_source_callback": True,
        "exact_host_output_types_and_pinned_composition": True,
        "historical_v1_byte_exact_rejected": True,
        "historical_v2_byte_exact_rejected": True,
        "historical_v3_byte_exact_rejected": True,
        "historical_v4_byte_exact_rejected": True,
        "historical_v5_byte_exact_rejected": True,
        "historical_v6_byte_exact_rejected": True,
        "human_review_token_required_for_batch": True,
        "integrity_equivocation_rollback_permanent_latch": True,
        "local_monotonic_deadline_nonresurrection": True,
        "no_live_wiring_mutation_or_authority": True,
        "recursive_r11_v1_through_v10_verification": True,
        "recursive_v3_manifest_closure_verification": True,
        "recursive_v5_and_transitive_prior_verification": True,
        "recursive_v6_and_transitive_prior_verification": True,
        "reopened_identical_view_preserves_returned_review_proofs": True,
        "secret_free_complete_review_fields": True,
        "single_source_callback_concurrency_cap": True,
        "source_callbacks_outside_projection_lock": True,
        "source_timestamp_metadata_excluded_from_integrity_digest": True,
        "strict_token_parse_and_malformed_normalization": True,
        "semantic_evidence_metadata_independently_derived": True,
        "token_verified_internal_result_factories": True,
        "startup_import_walk_no_approval_reachability": True,
        "startup_import_walk_resolves_literal_dynamic_loaders": True,
        "startup_import_walk_resolves_relative_importlib_packages": True,
        "startup_import_walk_tracks_loader_aliases_getattr_builtins_and_code_loaders": True,
        "view_bound_query_sort_page_size_and_item_set": True,
        "view_scoped_exact_calm_batch_only": True,
    }
    files = {relative: _sha(_path(relative)) for relative in paths if relative != BUNDLE}
    bundle = {
        "base_commit": current_base_commit(),
        "claims": claims,
        "contract": "Phase52ApprovalInboxEvidence.v7",
        "counts": counts,
        "dag": {
            "artifact_points_to": list(paths),
            "bundle_excludes_manifest_and_self_hashes": True,
            "root": TOP_MANIFEST,
            "root_points_to": [ARTIFACT_MANIFEST],
        },
        "dependency_closure": list(closure),
        "environment": actual_environment(),
        "external_e6": {
            "accepted": False,
            "required_before_acceptance": True,
            "status": "pending-external-review",
        },
        "feature_flag": {"default": False, "name": "ONYX_APPROVAL_INBOX_V7"},
        "files": files,
        "history": {
            "phase51_r11": {"decision": "accepted-default-off", "anchors": R11_SHA256},
            "phase52_v1": {"decision": "historical-rejected", "anchors": V1_SHA256},
            "phase52_v2": {"decision": "historical-rejected", "anchors": V2_SHA256},
            "phase52_v3": {"decision": "historical-rejected", "anchors": V3_SHA256},
            "phase52_v4": {"decision": "historical-rejected", "anchors": V4_SHA256},
            "phase52_v5": {"decision": "historical-rejected", "anchors": V5_SHA256},
            "phase52_v6": {"decision": "historical-rejected", "anchors": V6_SHA256},
        },
        "junit_timestamp": timestamp,
        "limits": derive_limits(),
        "live_scan_paths": list(live),
        "normative_graph": graph,
        "status": "candidate-default-off-not-accepted",
        "test_evidence": {
            "junit_timestamp": timestamp,
            "raw_summary": raw_summary,
            "static_gates": static_gates,
        },
        "timestamp": canonical_evidence_timestamp(timestamp),
    }
    _write(BUNDLE, _canonical(bundle))
    paths = artifact_paths()
    _write(ARTIFACT_MANIFEST, _manifest_bytes(paths))
    _write(TOP_MANIFEST, _manifest_bytes((ARTIFACT_MANIFEST,)))
    verify(recursive=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze", action="store_true")
    arguments = parser.parse_args(argv)
    if arguments.freeze:
        freeze()
    else:
        verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
