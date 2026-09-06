"""Provider-free Founder Snapshot V1.

This module is deliberately an orchestration seam: Phase 7 remains the sole
authority for approved sources, company-graph projection, and brief creation.
It never opens a socket, starts a process, or invokes a model/provider.
"""

from __future__ import annotations

import base64
from contextlib import nullcontext
from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
from typing import Callable, Mapping

from core.governance_nucleus_v1 import GovernanceIdentityV1
from core.host_security_boundary_v1 import TrustedDirectoryV1
from core.native_vault import NativeSecretVault
from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1
from core.phase11_windows_clone_cleanup_v1 import CloneCleanupWaiting
from core.phase7_approved_sources_v1 import ApprovedSourceRegistryV1
from core.phase7_company_graph_v1 import (
    CompanyGraphAssertionV1,
    CompanyGraphProjectorV1,
    GraphEvidenceBindingV1,
)
from core.phase7_founder_command_v1 import (
    FounderCommandBriefV1,
    FounderCommandGeneratorV1,
)

MANIFEST_SCHEMA = "onyx.founder-snapshot-manifest.v1"
STORE_SCHEMA = "onyx.founder-snapshot-history.v1"
CADENCES = frozenset({"daily", "weekly"})
MAX_MANIFEST_BYTES = 512 * 1024
MAX_ASSERTIONS = 256
MAX_SOURCES = 128
MAX_HISTORY_ENTRIES = 4096
MAX_HISTORY_BYTES = 64 * 1024 * 1024
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LOCK = threading.RLock()
_VAULT_HEAD_LOCK = threading.RLock()
_VAULT_PREFIX = b"ONYXFS1:"


class FounderSnapshotV1Error(RuntimeError):
    """Base safe-to-display Founder Snapshot error."""


class FounderSnapshotV1ContractError(ValueError):
    """Caller supplied a malformed or incompatible contract."""


class FounderSnapshotV1Denied(PermissionError):
    """Snapshot execution failed closed."""


class FounderSnapshotV1PlatformDenied(FounderSnapshotV1Denied):
    """Active V1 is not available on this operating system."""


@dataclass(frozen=True, slots=True)
class FounderSnapshotResultV1:
    cadence: str
    manifest_sha256: str
    brief: FounderCommandBriefV1
    history_sequence: int
    previous_entry_sha256: str | None


@dataclass(frozen=True, slots=True)
class FounderManifestPreflightV1:
    """Authenticated, path-bound manifest observation with no durable effect."""

    relative: str
    cadence: str
    manifest_sha256: str
    content_sha256: str

    def __post_init__(self) -> None:
        path = Path(self.relative)
        if (
            type(self.relative) is not str
            or not self.relative
            or path.is_absolute()
            or ".." in path.parts
            or not self.relative.endswith(".json")
            or self.cadence not in CADENCES
            or not _HEX64.fullmatch(self.manifest_sha256)
            or not _HEX64.fullmatch(self.content_sha256)
        ):
            raise FounderSnapshotV1ContractError("manifest preflight is invalid")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FounderSnapshotV1ContractError("value is not canonical JSON") from exc


def _strict_json(
    raw: bytes, *, max_bytes: int = MAX_MANIFEST_BYTES
) -> dict[str, object]:
    if len(raw) > max_bytes:
        raise FounderSnapshotV1Denied("snapshot manifest exceeds size bound")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(text)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FounderSnapshotV1Denied("snapshot manifest is not strict JSON") from exc
    if type(value) is not dict or _canonical(value) != raw:
        raise FounderSnapshotV1Denied("snapshot manifest is not canonical JSON")
    return value


def _unsigned_manifest(payload: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in payload.items() if key != "receipt_hmac_sha256"}


def _manifest_digest_payload(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"manifest_sha256", "receipt_hmac_sha256"}
    }


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _history_namespace(identity: GovernanceIdentityV1, cadence: str) -> str:
    return f"history/id-{_identity_digest(identity)}/{cadence}"


def _runtime_platform() -> str:
    return os.name


def _identity_digest(identity: GovernanceIdentityV1) -> str:
    return _digest(_identity_payload(identity))


def _identity_payload(identity: GovernanceIdentityV1) -> dict[str, object]:
    return {
        "principal_id": identity.principal_id,
        "workspace_id": identity.workspace_id,
        "account_id": identity.account_id,
        "profile_id": identity.profile_id,
        "workspace_display": identity.workspace_display,
    }


def _assertion_payload(assertion: CompanyGraphAssertionV1) -> dict[str, object]:
    return asdict(assertion)


def _parse_assertion(value: object) -> CompanyGraphAssertionV1:
    if type(value) is not dict:
        raise FounderSnapshotV1Denied("snapshot assertion is invalid")
    expected = {
        "claim_id",
        "semantic",
        "project_id",
        "project_name",
        "subject_id",
        "subject_name",
        "owner",
        "status",
        "blockers",
        "next_milestone",
        "definition_of_done",
        "last_verified_ms",
        "evidence",
    }
    if set(value) != expected:
        raise FounderSnapshotV1Denied("snapshot assertion shape drift")
    evidence_value = value.get("evidence")
    blockers_value = value.get("blockers")
    if type(evidence_value) is not list or type(blockers_value) is not list:
        raise FounderSnapshotV1Denied("snapshot assertion collection drift")
    try:
        evidence = tuple(
            GraphEvidenceBindingV1(**item)
            for item in evidence_value
            if type(item) is dict
        )
        if len(evidence) != len(evidence_value):
            raise FounderSnapshotV1Denied("snapshot evidence shape drift")
        return CompanyGraphAssertionV1(
            claim_id=value["claim_id"],  # type: ignore[arg-type]
            semantic=value["semantic"],  # type: ignore[arg-type]
            project_id=value["project_id"],  # type: ignore[arg-type]
            project_name=value["project_name"],  # type: ignore[arg-type]
            subject_id=value["subject_id"],  # type: ignore[arg-type]
            subject_name=value["subject_name"],  # type: ignore[arg-type]
            owner=value["owner"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            blockers=tuple(blockers_value),
            next_milestone=value["next_milestone"],  # type: ignore[arg-type]
            definition_of_done=value["definition_of_done"],  # type: ignore[arg-type]
            last_verified_ms=value["last_verified_ms"],  # type: ignore[arg-type]
            evidence=evidence,
        )
    except (TypeError, ValueError) as exc:
        raise FounderSnapshotV1Denied("snapshot assertion contract denied") from exc


class FounderSnapshotLiveV1:
    """Default-off local Founder Snapshot with an injected host boundary seam."""

    __slots__ = (
        "enabled",
        "identity",
        "root",
        "_sources",
        "_projector",
        "_generator",
        "_vault",
        "_key",
        "_heads",
        "_boundary",
        "_fault_hook",
    )

    def __init__(
        self,
        *,
        identity: GovernanceIdentityV1,
        root: str | os.PathLike[str],
        sources: ApprovedSourceRegistryV1 | None = None,
        projector: CompanyGraphProjectorV1 | None = None,
        generator: FounderCommandGeneratorV1 | None = None,
        vault: NativeSecretVault | None = None,
        enabled: bool = False,
        fault_hook: Callable[[str], None] | None = None,
        trusted_directory_factory: Callable[..., object] | None = None,
    ) -> None:
        if type(identity) is not GovernanceIdentityV1:
            raise FounderSnapshotV1ContractError("exact Governance identity required")
        if type(enabled) is not bool:
            raise FounderSnapshotV1ContractError("enabled must be exact bool")
        if fault_hook is not None and not callable(fault_hook):
            raise FounderSnapshotV1ContractError("fault_hook must be callable")
        if trusted_directory_factory is not None and not callable(
            trusted_directory_factory
        ):
            raise FounderSnapshotV1ContractError(
                "trusted_directory_factory must be callable"
            )
        self.enabled = enabled
        self.identity = identity
        self.root = Path(root)
        self._sources = sources
        self._projector = projector
        self._generator = generator
        self._vault = vault
        self._key: bytes | None = None
        self._heads: dict[str, dict[str, object]] = {}
        self._boundary: TrustedDirectoryV1 | None = None
        self._fault_hook = fault_hook
        if not enabled:
            return
        if _runtime_platform() != "nt" and trusted_directory_factory is None:
            raise FounderSnapshotV1PlatformDenied("founder_snapshot_windows_required")
        if (
            type(sources) is not ApprovedSourceRegistryV1
            or type(projector) is not CompanyGraphProjectorV1
            or type(generator) is not FounderCommandGeneratorV1
            or type(vault) is not NativeSecretVault
        ):
            raise FounderSnapshotV1ContractError("exact Phase 7 and native-vault bindings required")
        if (
            sources.workspace_id != identity.workspace_id
            or sources.principal_id != identity.principal_id
            or projector.workspace_id != identity.workspace_id
            or projector.principal_id != identity.principal_id
            or generator.workspace_id != identity.workspace_id
            or generator.principal_id != identity.principal_id
            or generator._projector is not projector
            or projector._sources is not sources
        ):
            raise FounderSnapshotV1Denied("founder snapshot identity binding denied")
        key = vault.get_bytes()
        if type(key) is not bytes:
            raise FounderSnapshotV1Denied("founder snapshot receipt key unavailable")
        self._key, self._heads = self._decode_vault_state(bytes(key))
        boundary_factory = (
            trusted_directory_factory or WindowsTrustedDirectoryV1
        )
        boundary = boundary_factory(root=self.root, enabled=True)
        if not isinstance(boundary, TrustedDirectoryV1):
            close = getattr(boundary, "close", None)
            if callable(close):
                close()
            raise FounderSnapshotV1ContractError(
                "trusted Founder Snapshot boundary is invalid"
            )
        self._boundary = boundary

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("FounderSnapshotLiveV1 cannot be subclassed")

    def close(self) -> None:
        boundary = self._boundary
        if boundary is not None:
            boundary.close()
            self._boundary = None
        self._key = None
        self._heads = {}

    def _decode_vault_state(
        self, raw: bytes
    ) -> tuple[bytes, dict[str, dict[str, object]]]:
        if not raw.startswith(_VAULT_PREFIX):
            if len(raw) < 32:
                raise FounderSnapshotV1Denied(
                    "founder snapshot receipt key unavailable"
                )
            return raw, {}
        payload = _strict_json(raw[len(_VAULT_PREFIX) :], max_bytes=2_048)
        if set(payload) != {"schema", "identity_sha256", "key_b64", "heads", "hmac_sha256"}:
            raise FounderSnapshotV1Denied("founder snapshot vault state denied")
        encoded = payload.get("key_b64")
        heads = payload.get("heads")
        mac = payload.get("hmac_sha256")
        try:
            key = base64.b64decode(encoded, validate=True) if type(encoded) is str else b""
        except (ValueError, base64.binascii.Error) as exc:
            raise FounderSnapshotV1Denied("founder snapshot vault state denied") from exc
        unsigned = {name: value for name, value in payload.items() if name != "hmac_sha256"}
        if (
            payload.get("schema") != "onyx.founder-snapshot-vault.v1"
            or payload.get("identity_sha256") != _identity_digest(self.identity)
            or len(key) < 32
            or type(heads) is not dict
            or set(heads) - CADENCES
            or type(mac) is not str
            or not hmac.compare_digest(
                mac, hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest()
            )
        ):
            raise FounderSnapshotV1Denied("founder snapshot vault state denied")
        parsed: dict[str, dict[str, object]] = {}
        for cadence, head in heads.items():
            if type(head) is not dict or set(head) != {
                "sequence",
                "entry_sha256",
                "pending_sequence",
                "pending_entry_sha256",
            }:
                raise FounderSnapshotV1Denied("founder snapshot vault head denied")
            sequence = head.get("sequence")
            entry_sha = head.get("entry_sha256")
            pending_sequence = head.get("pending_sequence")
            pending_sha = head.get("pending_entry_sha256")
            if (
                type(sequence) is not int
                or sequence < 0
                or (sequence == 0) != (entry_sha is None)
                or (entry_sha is not None and (type(entry_sha) is not str or not _HEX64.fullmatch(entry_sha)))
                or (pending_sequence is None) != (pending_sha is None)
                or (
                    pending_sequence is not None
                    and (
                        type(pending_sequence) is not int
                        or pending_sequence != sequence + 1
                        or type(pending_sha) is not str
                        or not _HEX64.fullmatch(pending_sha)
                    )
                )
            ):
                raise FounderSnapshotV1Denied("founder snapshot vault head denied")
            parsed[cadence] = dict(head)
        return key, parsed

    def _encode_vault_state(
        self, heads: dict[str, dict[str, object]]
    ) -> bytes:
        if self._key is None:
            raise FounderSnapshotV1Denied("founder snapshot vault is unavailable")
        unsigned: dict[str, object] = {
            "schema": "onyx.founder-snapshot-vault.v1",
            "identity_sha256": _identity_digest(self.identity),
            "key_b64": base64.b64encode(self._key).decode("ascii"),
            "heads": heads,
        }
        payload = {
            **unsigned,
            "hmac_sha256": hmac.new(
                self._key, _canonical(unsigned), hashlib.sha256
            ).hexdigest(),
        }
        return _VAULT_PREFIX + _canonical(payload)

    def _reload_heads_locked(self) -> dict[str, dict[str, object]]:
        if self._key is None or self._vault is None:
            raise FounderSnapshotV1Denied("founder snapshot vault is unavailable")
        try:
            raw = self._vault.get_bytes()
        except Exception as exc:
            raise FounderSnapshotV1Denied(
                "founder snapshot vault head reload failed"
            ) from exc
        if type(raw) is not bytes:
            raise FounderSnapshotV1Denied("founder snapshot vault state unavailable")
        key, heads = self._decode_vault_state(raw)
        if not hmac.compare_digest(key, self._key):
            raise FounderSnapshotV1Denied("founder snapshot vault key drift denied")
        return heads

    def _cas_head(
        self,
        cadence: str,
        *,
        expected: dict[str, object] | None,
        desired: dict[str, object],
    ) -> None:
        if self._vault is None:
            raise FounderSnapshotV1Denied("founder snapshot vault is unavailable")
        with _VAULT_HEAD_LOCK:
            current = self._reload_heads_locked()
            if current.get(cadence) != expected:
                raise FounderSnapshotV1Denied(
                    "founder snapshot vault head compare-and-swap denied"
                )
            merged = {name: dict(head) for name, head in current.items()}
            merged[cadence] = dict(desired)
            encoded = self._encode_vault_state(merged)
            try:
                self._vault.set_bytes(encoded)
                readback = self._vault.get_bytes()
            except Exception as exc:
                raise FounderSnapshotV1Denied(
                    "founder snapshot vault head persistence failed"
                ) from exc
            if type(readback) is not bytes:
                raise FounderSnapshotV1Denied(
                    "founder snapshot vault head read-back failed"
                )
            key, verified = self._decode_vault_state(readback)
            if (
                self._key is None
                or not hmac.compare_digest(key, self._key)
                or verified != merged
            ):
                raise FounderSnapshotV1Denied(
                    "founder snapshot vault head read-back denied"
                )
            self._heads = verified

    def _attest_or_recover_head(
        self, cadence: str, history: list[dict[str, object]]
    ) -> None:
        with _VAULT_HEAD_LOCK:
            self._heads = self._reload_heads_locked()
        head = self._heads.get(cadence)
        if head is None:
            if history:
                raise FounderSnapshotV1Denied("snapshot history truncation denied")
            return
        sequence = int(head["sequence"])
        entry_sha = head["entry_sha256"]
        pending_sequence = head["pending_sequence"]
        pending_sha = head["pending_entry_sha256"]
        observed_sequence = len(history)
        observed_sha = history[-1]["entry_sha256"] if history else None
        if pending_sequence is not None:
            observed_committed_sha = (
                history[sequence - 1]["entry_sha256"]
                if sequence > 0 and len(history) >= sequence
                else None
            )
            if (
                observed_sequence == pending_sequence
                and observed_sha == pending_sha
                and observed_committed_sha == entry_sha
            ):
                recovered = {
                    "sequence": pending_sequence,
                    "entry_sha256": pending_sha,
                    "pending_sequence": None,
                    "pending_entry_sha256": None,
                }
                self._cas_head(cadence, expected=head, desired=recovered)
                return
            raise FounderSnapshotV1Denied("snapshot pending history recovery denied")
        if observed_sequence != sequence or observed_sha != entry_sha:
            raise FounderSnapshotV1Denied("snapshot history truncation denied")

    def _pending_head_recovery_required(self, cadence: str) -> bool:
        with _VAULT_HEAD_LOCK:
            self._heads = self._reload_heads_locked()
        head = self._heads.get(cadence)
        return head is not None and head.get("pending_sequence") is not None

    def _require_active(self) -> tuple[bytes, TrustedDirectoryV1]:
        if not self.enabled or self._key is None or self._boundary is None:
            raise FounderSnapshotV1Denied("founder snapshot is disabled or closed")
        return self._key, self._boundary

    @staticmethod
    def _relative_manifest_path(manifest_path: str | os.PathLike[str]) -> str:
        if type(manifest_path) not in {str, Path}:
            raise FounderSnapshotV1ContractError("manifest path type denied")
        relative = str(manifest_path).replace("\\", "/")
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not relative.endswith(".json"):
            raise FounderSnapshotV1Denied("manifest path escapes trusted root")
        return relative

    def preflight_manifest(
        self, manifest_path: str | os.PathLike[str]
    ) -> FounderManifestPreflightV1:
        """Authenticate one exact manifest without generation or persistence."""

        _key, boundary = self._require_active()
        relative = self._relative_manifest_path(manifest_path)
        with _LOCK, boundary.session() as session:
            raw = session.read(relative, max_bytes=MAX_MANIFEST_BYTES)
            payload = self._validate_manifest(raw)
        return FounderManifestPreflightV1(
            relative=relative,
            cadence=str(payload["cadence"]),
            manifest_sha256=str(payload["manifest_sha256"]),
            content_sha256=hashlib.sha256(raw).hexdigest(),
        )

    def _fault(self, point: str) -> None:
        if self._fault_hook is not None:
            self._fault_hook(point)

    def seal_manifest(self, manifest: Mapping[str, object]) -> bytes:
        """Return canonical manifest bytes with a native-vault HMAC receipt."""
        key, _boundary = self._require_active()
        if type(manifest) is not dict or any(
            name in manifest for name in ("manifest_sha256", "receipt_hmac_sha256")
        ):
            raise FounderSnapshotV1ContractError("unsigned exact manifest dict required")
        unsigned = dict(manifest)
        digest = _digest(unsigned)
        authenticated = {**unsigned, "manifest_sha256": digest}
        receipt = hmac.new(key, _canonical(authenticated), hashlib.sha256).hexdigest()
        return _canonical({**authenticated, "receipt_hmac_sha256": receipt})

    def publish_manifest(
        self,
        relative: str,
        manifest: Mapping[str, object],
    ) -> str:
        """Seal and atomically publish a new local manifest below the held root."""
        _key, boundary = self._require_active()
        if type(relative) is not str or not relative.endswith(".json"):
            raise FounderSnapshotV1ContractError("manifest relative path is invalid")
        content = self.seal_manifest(manifest)
        with boundary.session() as session:
            session.publish_create(relative, content)
        return hashlib.sha256(content).hexdigest()

    def _validate_manifest(self, raw: bytes) -> dict[str, object]:
        key, _boundary = self._require_active()
        payload = _strict_json(raw)
        expected = {
            "schema",
            "cadence",
            "workspace_id",
            "principal_id",
            "governance_identity",
            "identity_sha256",
            "generated_at_ms",
            "allowed_sensitivities",
            "sources",
            "assertions",
            "manifest_sha256",
            "receipt_hmac_sha256",
        }
        receipt = payload.get("receipt_hmac_sha256")
        manifest_sha = payload.get("manifest_sha256")
        if (
            set(payload) != expected
            or payload.get("schema") != MANIFEST_SCHEMA
            or payload.get("cadence") not in CADENCES
            or payload.get("workspace_id") != self.identity.workspace_id
            or payload.get("principal_id") != self.identity.principal_id
            or payload.get("governance_identity")
            != _identity_payload(self.identity)
            or payload.get("identity_sha256")
            != _identity_digest(self.identity)
            or type(payload.get("generated_at_ms")) is not int
            or payload["generated_at_ms"] < 0  # type: ignore[operator]
            or type(receipt) is not str
            or not _HEX64.fullmatch(receipt)
            or type(manifest_sha) is not str
            or not _HEX64.fullmatch(manifest_sha)
            or manifest_sha != _digest(_manifest_digest_payload(payload))
            or not hmac.compare_digest(
                receipt,
                hmac.new(
                    key,
                    _canonical(_unsigned_manifest(payload)),
                    hashlib.sha256,
                ).hexdigest(),
            )
        ):
            raise FounderSnapshotV1Denied("snapshot manifest identity or receipt denied")
        sensitivities = payload.get("allowed_sensitivities")
        sources = payload.get("sources")
        assertions = payload.get("assertions")
        if (
            type(sensitivities) is not list
            or not sensitivities
            or sensitivities != sorted(set(sensitivities))
            or any(value not in {"public", "internal", "confidential"} for value in sensitivities)
            or type(sources) is not list
            or not sources
            or len(sources) > MAX_SOURCES
            or type(assertions) is not list
            or not assertions
            or len(assertions) > MAX_ASSERTIONS
        ):
            raise FounderSnapshotV1Denied("snapshot manifest limits or policy denied")
        return payload

    def _brief_from_payload(
        self,
        payload: dict[str, object],
        *,
        previous: FounderCommandBriefV1 | None,
    ) -> FounderCommandBriefV1:
        assert self._sources is not None
        assert self._generator is not None
        now_ms = payload["generated_at_ms"]
        source_rows = payload["sources"]
        assertion_rows = payload["assertions"]
        sensitivities = tuple(payload["allowed_sensitivities"])
        if type(now_ms) is not int or type(source_rows) is not list or type(assertion_rows) is not list:
            raise FounderSnapshotV1Denied("snapshot manifest collection drift")
        names: list[str] = []
        for item in source_rows:
            if type(item) is not dict or set(item) != {
                "source_name",
                "source_id",
                "source_identity_sha256",
                "citation",
            }:
                raise FounderSnapshotV1Denied("snapshot source shape drift")
            name = item.get("source_name")
            if type(name) is not str:
                raise FounderSnapshotV1Denied("snapshot source name drift")
            record = self._sources.get(name, now_ms=now_ms, require_fresh=True)
            if (
                item.get("source_id") != record.source_id
                or item.get("source_identity_sha256") != record.source_identity_sha256
                or item.get("citation") != record.citation
                or record.sensitivity not in sensitivities
            ):
                raise FounderSnapshotV1Denied("snapshot approved-source binding denied")
            names.append(name)
        if names != sorted(set(names)):
            raise FounderSnapshotV1Denied("snapshot sources must be unique and sorted")
        assertions = tuple(_parse_assertion(item) for item in assertion_rows)
        if tuple(sorted(assertions, key=lambda item: item.claim_id)) != assertions:
            raise FounderSnapshotV1Denied("snapshot assertions must be sorted")
        allowed_names = set(names)
        if any(
            evidence.source_name not in allowed_names
            for assertion in assertions
            for evidence in assertion.evidence
        ):
            raise FounderSnapshotV1Denied("snapshot assertion cites undeclared source")
        brief = self._generator.generate(
            assertions,
            now_ms=now_ms,
            allowed_sensitivities=sensitivities,
            cadence=payload["cadence"],  # type: ignore[arg-type]
            previous_brief=previous,
        )
        if (
            type(brief) is not FounderCommandBriefV1
            or brief.workspace_id != self.identity.workspace_id
            or brief.principal_id != self.identity.principal_id
            or brief.cadence != payload["cadence"]
            or any(not item.citations for item in brief.items)
        ):
            raise FounderSnapshotV1Denied("Founder Brief output contract denied")
        return brief

    def _read_history(
        self,
        session: object,
        cadence: str,
        key: bytes,
    ) -> list[dict[str, object]]:
        namespace = _history_namespace(self.identity, cadence)
        entries: list[dict[str, object]] = []
        previous_entry_sha: str | None = None
        total = 0
        for sequence in range(1, MAX_HISTORY_ENTRIES + 1):
            relative = f"{namespace}/{sequence:08d}.json"
            raw = session.read_optional(relative, max_bytes=MAX_MANIFEST_BYTES * 2)  # type: ignore[attr-defined]
            if raw is None:
                break
            total += len(raw)
            if total > MAX_HISTORY_BYTES:
                raise FounderSnapshotV1Denied("snapshot history size bound exceeded")
            entry = _strict_json(raw, max_bytes=MAX_MANIFEST_BYTES * 2)
            expected = {
                "schema",
                "sequence",
                "cadence",
                "workspace_id",
                "principal_id",
                "governance_identity",
                "identity_sha256",
                "generated_at_ms",
                "manifest_b64",
                "manifest_sha256",
                "brief_sha256",
                "previous_brief_sha256",
                "previous_entry_sha256",
                "entry_sha256",
                "hmac_sha256",
            }
            unsigned = {name: value for name, value in entry.items() if name != "hmac_sha256"}
            digest_material = {
                name: value for name, value in unsigned.items() if name != "entry_sha256"
            }
            if (
                set(entry) != expected
                or entry.get("schema") != STORE_SCHEMA
                or entry.get("sequence") != sequence
                or entry.get("cadence") != cadence
                or entry.get("workspace_id") != self.identity.workspace_id
                or entry.get("principal_id") != self.identity.principal_id
                or entry.get("governance_identity")
                != _identity_payload(self.identity)
                or entry.get("identity_sha256")
                != _identity_digest(self.identity)
                or entry.get("previous_entry_sha256") != previous_entry_sha
                or entry.get("entry_sha256") != _digest(digest_material)
                or type(entry.get("hmac_sha256")) is not str
                or not hmac.compare_digest(
                    str(entry["hmac_sha256"]),
                    hmac.new(key, _canonical(unsigned), hashlib.sha256).hexdigest(),
                )
            ):
                raise FounderSnapshotV1Denied("snapshot history authentication denied")
            previous_entry_sha = str(entry["entry_sha256"])
            entries.append(entry)
        if len(entries) == MAX_HISTORY_ENTRIES:
            overflow = f"{namespace}/{MAX_HISTORY_ENTRIES + 1:08d}.json"
            if session.exists(overflow, directory=False):  # type: ignore[attr-defined]
                raise FounderSnapshotV1Denied("snapshot history count bound exceeded")
        return entries

    def _history_namespace_exists(self, session: object, cadence: str) -> bool:
        """Probe ancestors one at a time without creating durable namespace."""

        namespace = _history_namespace(self.identity, cadence)
        parts = namespace.split("/")
        for index in range(1, len(parts) + 1):
            if not session.exists("/".join(parts[:index]), directory=True):  # type: ignore[attr-defined]
                return False
        return True

    def _manifest_from_history(self, entry: dict[str, object]) -> dict[str, object]:
        encoded = entry.get("manifest_b64")
        if type(encoded) is not str:
            raise FounderSnapshotV1Denied("snapshot history manifest denied")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise FounderSnapshotV1Denied("snapshot history manifest denied") from exc
        payload = self._validate_manifest(raw)
        if payload["manifest_sha256"] != entry.get("manifest_sha256"):
            raise FounderSnapshotV1Denied("snapshot history manifest digest denied")
        return payload

    def generate(
        self,
        manifest_path: str | os.PathLike[str],
        *,
        preflight: FounderManifestPreflightV1 | None = None,
        commit_guard: Callable[[], object] | None = None,
    ) -> FounderSnapshotResultV1:
        key, boundary = self._require_active()
        if preflight is not None and type(preflight) is not FounderManifestPreflightV1:
            raise FounderSnapshotV1ContractError("exact manifest preflight required")
        if commit_guard is not None and not callable(commit_guard):
            raise FounderSnapshotV1ContractError("commit guard must be callable")
        relative = self._relative_manifest_path(manifest_path)
        with _LOCK, boundary.session() as session:
            def commit_context():
                value = commit_guard() if commit_guard is not None else None
                if (
                    callable(getattr(value, "__enter__", None))
                    and callable(getattr(value, "__exit__", None))
                ):
                    return value
                return nullcontext()

            raw = session.read(relative, max_bytes=MAX_MANIFEST_BYTES)
            payload = self._validate_manifest(raw)
            if preflight is not None and (
                preflight.relative != relative
                or preflight.cadence != payload["cadence"]
                or preflight.manifest_sha256 != payload["manifest_sha256"]
                or preflight.content_sha256 != hashlib.sha256(raw).hexdigest()
            ):
                raise FounderSnapshotV1Denied("manifest changed after authenticated preflight")
            cadence = str(payload["cadence"])
            namespace = _history_namespace(self.identity, cadence)
            namespace_record = _canonical(
                {
                    "schema": "onyx.founder-snapshot-namespace.v1",
                    "workspace_id": self.identity.workspace_id,
                    "principal_id": self.identity.principal_id,
                    "governance_identity": _identity_payload(self.identity),
                    "identity_sha256": _identity_digest(self.identity),
                    "cadence": cadence,
                }
            )
            # Pure projection phase. It reads and authenticates existing
            # history but creates no namespace, lock file, head, or pending
            # anchor. A concurrent committer is detected by the exact re-read
            # after the governance fence is acquired.
            history = (
                self._read_history(session, cadence, key)
                if self._history_namespace_exists(session, cadence)
                else []
            )
            if self._pending_head_recovery_required(cadence):
                # A prior publish already crossed its commit boundary. Recover
                # that durable pending head under the same Governance fence
                # before computing a new projection; never re-execute it.
                with commit_context():
                    self._attest_or_recover_head(cadence, history)
            observed_history = tuple(
                str(item["entry_sha256"]) for item in history
            )
            previous: FounderCommandBriefV1 | None = None
            previous_entry_sha: str | None = None
            if history:
                prior_payload = self._manifest_from_history(history[-1])
                if (
                    payload["generated_at_ms"] <= prior_payload["generated_at_ms"]  # type: ignore[operator]
                    or payload["manifest_sha256"] == prior_payload["manifest_sha256"]
                ):
                    raise FounderSnapshotV1Denied(
                        "snapshot cadence history conflict denied"
                    )
                for history_entry in history:
                    history_payload = self._manifest_from_history(history_entry)
                    previous = self._brief_from_payload(
                        history_payload, previous=previous
                    )
                    if previous.brief_sha256 != history_entry.get("brief_sha256"):
                        raise FounderSnapshotV1Denied(
                            "snapshot previous brief digest denied"
                        )
                previous_entry_sha = str(history[-1]["entry_sha256"])
            if len(history) >= MAX_HISTORY_ENTRIES:
                raise FounderSnapshotV1Denied(
                    "snapshot history count bound exceeded"
                )
            brief = self._brief_from_payload(payload, previous=previous)
            sequence = len(history) + 1
            material: dict[str, object] = {
                "schema": STORE_SCHEMA,
                "sequence": sequence,
                "cadence": cadence,
                "workspace_id": self.identity.workspace_id,
                "principal_id": self.identity.principal_id,
                "governance_identity": _identity_payload(self.identity),
                "identity_sha256": _identity_digest(self.identity),
                "generated_at_ms": payload["generated_at_ms"],
                "manifest_b64": base64.b64encode(raw).decode("ascii"),
                "manifest_sha256": payload["manifest_sha256"],
                "brief_sha256": brief.brief_sha256,
                "previous_brief_sha256": (
                    previous.brief_sha256 if previous is not None else None
                ),
                "previous_entry_sha256": previous_entry_sha,
            }
            entry_sha = _digest(material)
            unsigned = {**material, "entry_sha256": entry_sha}
            entry = {
                **unsigned,
                "hmac_sha256": hmac.new(
                    key, _canonical(unsigned), hashlib.sha256
                ).hexdigest(),
            }

            with commit_context():
                # Revalidate the exact authenticated bytes only after the
                # governance/lease fence linearizes against global kill.
                commit_raw = session.read(relative, max_bytes=MAX_MANIFEST_BYTES)
                commit_payload = self._validate_manifest(commit_raw)
                if (
                    commit_raw != raw
                    or commit_payload["cadence"] != cadence
                    or commit_payload["manifest_sha256"]
                    != payload["manifest_sha256"]
                ):
                    raise FounderSnapshotV1Denied(
                        "manifest changed before durable commit"
                    )
                try:
                    session.publish_create(
                        f"{namespace}/namespace.v1", namespace_record
                    )
                except CloneCleanupWaiting as exc:
                    if str(exc) != "phase11_namespace_artifact_exists":
                        raise
                    existing = session.read(
                        f"{namespace}/namespace.v1",
                        max_bytes=len(namespace_record),
                    )
                    if existing != namespace_record:
                        raise FounderSnapshotV1Denied(
                            "snapshot history namespace identity denied"
                        ) from exc
                with session.lock(f"{namespace}/history.lock"):
                    commit_history = self._read_history(session, cadence, key)
                    if tuple(
                        str(item["entry_sha256"]) for item in commit_history
                    ) != observed_history:
                        raise FounderSnapshotV1Denied(
                            "snapshot history changed before durable commit"
                        )
                    self._attest_or_recover_head(cadence, commit_history)
                    previous_head = self._heads.get(cadence)
                    pending_head = {
                        "sequence": len(commit_history),
                        "entry_sha256": previous_entry_sha,
                        "pending_sequence": sequence,
                        "pending_entry_sha256": entry_sha,
                    }
                    self._cas_head(
                        cadence,
                        expected=previous_head,
                        desired=pending_head,
                    )
                    try:
                        session.publish_create(
                            f"{namespace}/{sequence:08d}.json",
                            _canonical(entry),
                        )
                        self._fault("post_publish")
                    except BaseException:
                        raise
                    committed_head = {
                        "sequence": sequence,
                        "entry_sha256": entry_sha,
                        "pending_sequence": None,
                        "pending_entry_sha256": None,
                    }
                    self._cas_head(
                        cadence,
                        expected=pending_head,
                        desired=committed_head,
                    )
            return FounderSnapshotResultV1(
                cadence=cadence,
                manifest_sha256=str(payload["manifest_sha256"]),
                brief=brief,
                history_sequence=sequence,
                previous_entry_sha256=previous_entry_sha,
            )


__all__ = [
    "FounderManifestPreflightV1",
    "FounderSnapshotLiveV1",
    "FounderSnapshotResultV1",
    "FounderSnapshotV1ContractError",
    "FounderSnapshotV1Denied",
    "FounderSnapshotV1Error",
    "FounderSnapshotV1PlatformDenied",
]
