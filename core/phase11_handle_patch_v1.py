"""Canonical handle-relative add/modify patch engine for Phase 11."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Callable, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.phase11_windows_clone_cleanup_v1 import (
    CloneCleanupContractError,
)


MAX_PATCH_FILE_BYTES = 16 * 1024 * 1024
JOURNAL_NAME = "patch.apply.journal.v1.json"
JOURNAL_SCHEMA = "onyx.phase11.handle-patch.journal.v1"
_JOURNAL_DOMAIN = b"ONYX/PHASE11/HANDLE-PATCH/JOURNAL/V1\0"
_ENCRYPTION_DOMAIN = b"ONYX/PHASE11/HANDLE-PATCH/ROLLBACK/V1\0"
_DIFF = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_HUNK = re.compile(
    r"^@@ -([0-9]+)(?:,([0-9]+))? "
    r"\+([0-9]+)(?:,([0-9]+))? @@(?: .*)?$"
)


class MissionArtifacts(Protocol):
    def has_entry(
        self, name: str, *, directory: bool | None = None
    ) -> bool: ...

    def read_artifact(self, name: str, *, max_bytes: int) -> bytes: ...

    def write_artifact(
        self, name: str, content: bytes, *, create: bool
    ) -> None: ...

    def scrub_artifact(self, name: str, *, max_bytes: int) -> bool: ...


class CloneFiles(Protocol):
    def read_file(
        self, relative: str, *, max_bytes: int
    ) -> bytes: ...

    def read_file_optional(
        self, relative: str, *, max_bytes: int
    ) -> bytes | None: ...

    def write_existing(
        self,
        relative: str,
        content: bytes,
        *,
        expected_sha256: str,
        fault_hook: object | None = None,
    ) -> None: ...

    def create_file(
        self,
        relative: str,
        content: bytes,
        *,
        fault_hook: object | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PatchHunkV1:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class PatchOperationV1:
    path: str
    kind: str
    hunks: tuple[PatchHunkV1, ...]


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_path(path: str) -> str:
    if (
        not path
        or "\\" in path
        or "\0" in path
        or ":" in path
        or path.startswith("/")
    ):
        raise CloneCleanupContractError("phase11_patch_path_invalid")
    components = path.split("/")
    if any(
        not component
        or component in {".", ".."}
        or component.casefold() == ".git"
        for component in components
    ):
        raise CloneCleanupContractError("phase11_patch_path_invalid")
    return path


def parse_canonical_patch(patch: str) -> tuple[PatchOperationV1, ...]:
    if (
        not patch
        or not patch.endswith("\n")
        or "\r" in patch
        or "\0" in patch
    ):
        raise CloneCleanupContractError(
            "phase11_patch_newline_policy_refused"
        )
    lines = patch.splitlines()
    operations: list[PatchOperationV1] = []
    seen: set[str] = set()
    index = 0
    while index < len(lines):
        match = _DIFF.fullmatch(lines[index])
        if match is None:
            raise CloneCleanupContractError(
                "phase11_patch_header_invalid"
            )
        left = _safe_path(match.group(1))
        right = _safe_path(match.group(2))
        if left != right or left in seen:
            raise CloneCleanupContractError(
                "phase11_patch_rename_or_duplicate_refused"
            )
        seen.add(left)
        index += 1
        while index < len(lines) and not lines[index].startswith("--- "):
            metadata = lines[index]
            if metadata == "new file mode 100644" or re.fullmatch(
                r"index [0-9a-f]+\.\.[0-9a-f]+(?: 100644)?",
                metadata,
            ):
                index += 1
                continue
            raise CloneCleanupContractError(
                "phase11_patch_metadata_refused"
            )
        if index + 1 >= len(lines):
            raise CloneCleanupContractError(
                "phase11_patch_block_incomplete"
            )
        old_marker = lines[index][4:]
        new_line = lines[index + 1]
        if not new_line.startswith("+++ "):
            raise CloneCleanupContractError(
                "phase11_patch_block_incomplete"
            )
        new_marker = new_line[4:]
        if old_marker == "/dev/null" and new_marker == f"b/{left}":
            kind = "add"
        elif old_marker == f"a/{left}" and new_marker == f"b/{left}":
            kind = "modify"
        else:
            raise CloneCleanupContractError(
                "phase11_patch_delete_or_path_change_refused"
            )
        index += 2
        hunks: list[PatchHunkV1] = []
        while index < len(lines) and not lines[index].startswith(
            "diff --git "
        ):
            header = _HUNK.fullmatch(lines[index])
            if header is None:
                raise CloneCleanupContractError(
                    "phase11_patch_hunk_header_invalid"
                )
            old_start = int(header.group(1))
            old_count = int(header.group(2) or "1")
            new_start = int(header.group(3))
            new_count = int(header.group(4) or "1")
            if old_count == 0 and new_count == 0:
                raise CloneCleanupContractError(
                    "phase11_patch_empty_hunk_refused"
                )
            index += 1
            old_seen = new_seen = 0
            body: list[tuple[str, str]] = []
            while old_seen < old_count or new_seen < new_count:
                if index >= len(lines):
                    raise CloneCleanupContractError(
                        "phase11_patch_hunk_incomplete"
                    )
                line = lines[index]
                if not line or line[0] not in {" ", "-", "+"}:
                    raise CloneCleanupContractError(
                        "phase11_patch_hunk_invalid"
                    )
                marker, content = line[0], line[1:]
                if marker in {" ", "-"}:
                    old_seen += 1
                if marker in {" ", "+"}:
                    new_seen += 1
                if old_seen > old_count or new_seen > new_count:
                    raise CloneCleanupContractError(
                        "phase11_patch_hunk_invalid"
                    )
                body.append((marker, content))
                index += 1
            hunks.append(
                PatchHunkV1(
                    old_start,
                    old_count,
                    new_start,
                    new_count,
                    tuple(body),
                )
            )
        if not hunks:
            raise CloneCleanupContractError(
                "phase11_patch_hunk_required"
            )
        operations.append(
            PatchOperationV1(left, kind, tuple(hunks))
        )
    return tuple(operations)


def _apply_hunks(operation: PatchOperationV1, preimage: bytes) -> bytes:
    if len(preimage) > MAX_PATCH_FILE_BYTES:
        raise CloneCleanupContractError(
            "phase11_patch_file_budget_exhausted"
        )
    try:
        source = preimage.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CloneCleanupContractError(
            "phase11_patch_utf8_required"
        ) from exc
    if "\r" in source or (source and not source.endswith("\n")):
        raise CloneCleanupContractError(
            "phase11_patch_newline_policy_refused"
        )
    source_lines = source.splitlines()
    output: list[str] = []
    cursor = 0
    for hunk in operation.hunks:
        old_index = 0 if hunk.old_start == 0 else hunk.old_start - 1
        if old_index < cursor or old_index > len(source_lines):
            raise CloneCleanupContractError(
                "phase11_patch_hunk_conflict"
            )
        output.extend(source_lines[cursor:old_index])
        if len(output) != (
            0 if hunk.new_start == 0 else hunk.new_start - 1
        ):
            raise CloneCleanupContractError(
                "phase11_patch_hunk_conflict"
            )
        cursor = old_index
        for marker, content in hunk.lines:
            if marker in {" ", "-"}:
                if (
                    cursor >= len(source_lines)
                    or source_lines[cursor] != content
                ):
                    raise CloneCleanupContractError(
                        "phase11_patch_preimage_mismatch"
                    )
                cursor += 1
            if marker in {" ", "+"}:
                output.append(content)
    output.extend(source_lines[cursor:])
    encoded = (
        b""
        if not output
        else ("\n".join(output) + "\n").encode("utf-8")
    )
    if len(encoded) > MAX_PATCH_FILE_BYTES:
        raise CloneCleanupContractError(
            "phase11_patch_file_budget_exhausted"
        )
    return encoded


class HandlePatchEngineV1:
    def __init__(
        self,
        *,
        signing_key: bytes,
        mission: MissionArtifacts,
        clone: CloneFiles,
    ) -> None:
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise ValueError("patch signing key must be at least 32 bytes")
        self._key = bytes(signing_key)
        self._mission = mission
        self._clone = clone
        self._encryption_key = hashlib.sha256(
            self._key + _ENCRYPTION_DOMAIN
        ).digest()

    def _journal(
        self,
        *,
        operation: PatchOperationV1,
        patch_digest: str,
        preimage: bytes,
        postimage: bytes,
    ) -> bytes:
        metadata = {
            "schema": JOURNAL_SCHEMA,
            "path": operation.path,
            "kind": operation.kind,
            "patch_digest": patch_digest,
            "pre_sha256": hashlib.sha256(preimage).hexdigest(),
            "post_sha256": hashlib.sha256(postimage).hexdigest(),
        }
        nonce = secrets.token_bytes(12)
        encrypted = AESGCM(self._encryption_key).encrypt(
            nonce, preimage, _canonical(metadata)
        )
        payload = {
            **metadata,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "rollback_ciphertext": base64.b64encode(
                encrypted
            ).decode("ascii"),
        }
        signature = hmac.new(
            self._key,
            _JOURNAL_DOMAIN + _canonical(payload),
            hashlib.sha256,
        ).hexdigest()
        return _canonical({"payload": payload, "signature": signature})

    def _load_journal(self) -> tuple[dict[str, object], bytes] | None:
        if not self._mission.has_entry(JOURNAL_NAME, directory=False):
            return None
        raw = self._mission.read_artifact(
            JOURNAL_NAME, max_bytes=MAX_PATCH_FILE_BYTES * 2
        )
        try:
            document = json.loads(raw)
            payload = document["payload"]
            signature = document["signature"]
            expected = hmac.new(
                self._key,
                _JOURNAL_DOMAIN + _canonical(payload),
                hashlib.sha256,
            ).hexdigest()
            if (
                not isinstance(payload, dict)
                or not isinstance(signature, str)
                or not hmac.compare_digest(signature, expected)
                or payload.get("schema") != JOURNAL_SCHEMA
            ):
                raise ValueError
            nonce = base64.b64decode(
                str(payload["nonce"]), validate=True
            )
            ciphertext = base64.b64decode(
                str(payload["rollback_ciphertext"]),
                validate=True,
            )
            metadata = {
                key: value
                for key, value in payload.items()
                if key not in {"nonce", "rollback_ciphertext"}
            }
            preimage = AESGCM(self._encryption_key).decrypt(
                nonce, ciphertext, _canonical(metadata)
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            raise CloneCleanupContractError(
                "phase11_patch_journal_invalid"
            ) from exc
        return payload, preimage

    def _clear_journal(self) -> None:
        self._mission.scrub_artifact(
            JOURNAL_NAME, max_bytes=MAX_PATCH_FILE_BYTES * 2
        )

    def _recover(
        self,
        operation: PatchOperationV1,
        patch_digest: str,
        postimage: bytes,
    ) -> bool:
        loaded = self._load_journal()
        if loaded is None:
            return False
        payload, preimage = loaded
        expected = {
            "path": operation.path,
            "kind": operation.kind,
            "patch_digest": patch_digest,
            "pre_sha256": hashlib.sha256(preimage).hexdigest(),
            "post_sha256": hashlib.sha256(postimage).hexdigest(),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise CloneCleanupContractError(
                "phase11_patch_journal_binding_mismatch"
            )
        current = self._clone.read_file_optional(
            operation.path, max_bytes=MAX_PATCH_FILE_BYTES
        )
        post_sha = expected["post_sha256"]
        if current is not None and hmac.compare_digest(
            hashlib.sha256(current).hexdigest(), post_sha
        ):
            self._clear_journal()
            return True
        if operation.kind == "add":
            if current is not None:
                raise CloneCleanupContractError(
                    "phase11_patch_add_recovery_conflict"
                )
            self._clear_journal()
            return False
        if current is None:
            raise CloneCleanupContractError(
                "phase11_patch_modify_target_missing"
            )
        current_sha = hashlib.sha256(current).hexdigest()
        pre_sha = expected["pre_sha256"]
        if not hmac.compare_digest(current_sha, pre_sha):
            self._clone.write_existing(
                operation.path,
                preimage,
                expected_sha256=current_sha,
            )
        self._clear_journal()
        return False

    def apply(
        self,
        patch: str,
        *,
        fault_hook: Callable[[str], None] | None = None,
    ) -> tuple[PatchOperationV1, ...]:
        operations = parse_canonical_patch(patch)
        patch_digest = hashlib.sha256(patch.encode("utf-8")).hexdigest()
        for operation in operations:
            pending = self._load_journal()
            if pending is not None:
                pending_payload, pending_preimage = pending
                if (
                    pending_payload.get("path") != operation.path
                    or pending_payload.get("kind") != operation.kind
                    or pending_payload.get("patch_digest")
                    != patch_digest
                ):
                    raise CloneCleanupContractError(
                        "phase11_patch_journal_binding_mismatch"
                    )
                pending_postimage = _apply_hunks(
                    operation, pending_preimage
                )
                if self._recover(
                    operation, patch_digest, pending_postimage
                ):
                    continue
            current = self._clone.read_file_optional(
                operation.path, max_bytes=MAX_PATCH_FILE_BYTES
            )
            if operation.kind == "add":
                preimage = b""
                postimage = _apply_hunks(operation, preimage)
                if current is not None:
                    if hmac.compare_digest(
                        hashlib.sha256(current).hexdigest(),
                        hashlib.sha256(postimage).hexdigest(),
                    ):
                        continue
                    raise CloneCleanupContractError(
                        "phase11_patch_add_target_exists"
                    )
            else:
                if current is None:
                    raise CloneCleanupContractError(
                        "phase11_patch_modify_target_missing"
                    )
                preimage = current
                postimage = _apply_hunks(operation, preimage)
            if self._recover(operation, patch_digest, postimage):
                continue
            journal = self._journal(
                operation=operation,
                patch_digest=patch_digest,
                preimage=preimage,
                postimage=postimage,
            )
            self._mission.write_artifact(
                JOURNAL_NAME, journal, create=True
            )
            if fault_hook is not None:
                fault_hook("after_journal")
            if operation.kind == "add":
                self._clone.create_file(
                    operation.path,
                    postimage,
                    fault_hook=fault_hook,
                )
            else:
                self._clone.write_existing(
                    operation.path,
                    postimage,
                    expected_sha256=hashlib.sha256(
                        preimage
                    ).hexdigest(),
                    fault_hook=fault_hook,
                )
            if fault_hook is not None:
                fault_hook("after_commit")
            self._clear_journal()
        return operations
