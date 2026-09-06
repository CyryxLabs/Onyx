"""Attested, lifecycle-safe adapters for accepted Phase 5 candidates.

This isolated candidate is default-off and is not imported by any live surface.
It projects accepted component output only; it cannot approve, grant authority,
dispatch, execute, persist, poll, or create threads.

V3 preserves the accepted grant and capability adapters while replacing the
Approval Inbox trust boundary.  The adapter now constructs the exact accepted
V15 projection itself from host inputs.  An immutable HMAC construction receipt
binds that concrete instance, source callback, store scope and all five runtime
dimensions.  Every page then travels through a bounded monotonic pre/post
envelope window and a source-scope receipt derived from the actual V15 capture.
No caller-supplied projection or signer is accepted.
"""

from __future__ import annotations

import dataclasses
import hashlib
import hmac
import inspect
import json
import os
import re
import secrets
import stat
import threading
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from core import approval_inbox_v15 as _inbox_v15


ADAPTER_CONTRACT_V3 = "onyx.phase5-component-adapters.v3"
GRANTS_ACCEPTANCE_V3 = "VE-P51-GRANTS-R11-E6-001"
NEXUS_ACCEPTANCE_V3 = "VE-P53-CAPABILITY-NEXUS-V32-E6-001"
INBOX_ACCEPTANCE_V3 = "VE-P52-APPROVAL-INBOX-V15-E6-001"

GRANTS_ROOT_V3 = "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071"
NEXUS_ROOT_V3 = "86cc174fb212f51c56b59cb9043c8cb59e765307eea2c32a7a44857f6112bfa3"
INBOX_ROOT_V3 = "279052fbcaf3018f7fee6733e063e94c67e90e7ce62a2a2cdc7742b55470631f"
HOST_ROOT_V3 = hashlib.sha256(b"onyx.phase5.host.integration.v3").hexdigest()

MAX_ITEMS_V3 = 128
MAX_PAGE_SIZE_V3 = 50
MAX_CURSOR_BYTES_V3 = 128
MAX_ADVISORY_BYTES_V3 = 512
MAX_SEQUENCE_V3 = 9_223_372_036_854_775_807
MAX_ACTIVE_INBOX_OWNERS_V3 = 128

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RISKS = frozenset({"low", "medium", "high", "critical"})
_TERMINAL_REASONS = frozenset(
    {"kill", "revoke", "rollback", "end_session", "reconnect", "shutdown"}
)
_NEXUS_STATUS = {
    "available_read_only": "available",
    "degraded": "degraded",
    "blocked_by_access": "blocked",
    "blocked_by_scope": "blocked",
    "blocked_by_platform": "blocked",
    "blocked_by_license": "blocked",
    "disabled": "disabled",
}
_ROLE_METHODS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "grant_store": ("evaluate", "kill", "end_session"),
        "grant_materializer": ("__call__",),
        "nexus": ("snapshot",),
        "inbox": ("open_page", "continue_page"),
    }
)
_CATALOG_LIMITATION = (
    "metadata_allowlisted;read_only;provider_free;effect_none;egress_none;"
    "cost_micro_0;dispatch_unavailable"
)

_PROJECT_ROOT = Path(__file__).resolve(strict=True).parents[1]
_SOURCE_CACHE_LOCK = threading.RLock()
_SOURCE_CACHE: dict[tuple[object, ...], str] = {}
_ACCEPTED: Mapping[str, tuple[str, str, str, str, str, str]] = MappingProxyType(
    {
        "grant_store": (
            GRANTS_ROOT_V3,
            "core.session_" + "grants_v11",
            "SessionGrantShadowStore",
            "core/session_" + "grants_v11.py",
            "r11",
            "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
        ),
        "nexus": (
            NEXUS_ROOT_V3,
            "core.capability_" + "nexus_v32",
            "CapabilityNexusV32",
            "core/capability_" + "nexus_v32.py",
            "v32",
            "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
        ),
        "inbox": (
            INBOX_ROOT_V3,
            "core.approval_" + "inbox_v15",
            "ApprovalInboxProjectionV15",
            "core/approval_" + "inbox_v15.py",
            "v15",
            "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
        ),
    }
)


class Phase5ComponentAdapterV3Error(RuntimeError):
    """A dependency or lifecycle check could not safely complete."""


class Phase5ComponentAdapterV3ContractError(ValueError):
    """An exact V3 input or attestation contract was violated."""


class RuntimeBatchFactoryV3(Protocol):
    def __call__(
        self,
        items: tuple[Mapping[str, object], ...],
        *,
        replace: bool,
        source_cursor: str | None,
        next_cursor: str | None,
    ) -> object: ...


class RuntimeComponentsFactoryV3(Protocol):
    def __call__(self, **components: object) -> object: ...


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5ComponentAdapterV3ContractError(f"{label} must be exact bool")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5ComponentAdapterV3ContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise Phase5ComponentAdapterV3ContractError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise Phase5ComponentAdapterV3ContractError(f"{label} is invalid")
    return value


def _exact_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise Phase5ComponentAdapterV3ContractError(f"{label} is invalid")
    return value


def _enum_value(value: object, label: str) -> str:
    raw = getattr(value, "value", value)
    return _text(raw, label, 64)


def _callable_member(value: object, name: str) -> Callable[..., object]:
    member = getattr(value, name, None)
    if not callable(member):
        raise Phase5ComponentAdapterV3ContractError(
            f"component lacks callable {name}"
        )
    return member


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise Phase5ComponentAdapterV3ContractError(
            "attestation payload is not canonical JSON"
        ) from exc


def _source_identity(value: object) -> tuple[str, str, str, str, int]:
    target = value if inspect.isclass(value) else type(value)
    if inspect.isfunction(value) or inspect.ismethod(value):
        target = value.__func__ if inspect.ismethod(value) else value
    module_name = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if type(module_name) is not str or type(qualname) is not str:
        raise Phase5ComponentAdapterV3ContractError(
            "component has no exact Python identity"
        )
    try:
        raw_path = inspect.getsourcefile(target) or inspect.getfile(target)
    except (TypeError, OSError) as exc:
        raise Phase5ComponentAdapterV3ContractError(
            "component source is unavailable"
        ) from exc
    if type(raw_path) is not str:
        raise Phase5ComponentAdapterV3ContractError(
            "component source is unavailable"
        )
    lexical = Path(raw_path).absolute()
    try:
        before = os.lstat(lexical)
        canonical = lexical.resolve(strict=True)
        after = os.stat(canonical, follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise Phase5ComponentAdapterV3Error("component source check failed") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or lexical != canonical
    ):
        raise Phase5ComponentAdapterV3ContractError(
            "component source must be a canonical regular file"
        )
    identity_before = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
    cache_key: tuple[object, ...] = (str(canonical), *identity_before)
    with _SOURCE_CACHE_LOCK:
        cached = _SOURCE_CACHE.get(cache_key)
    if cached is not None:
        return module_name, qualname, str(canonical), cached, after.st_size
    try:
        content = canonical.read_bytes()
        final = os.stat(canonical, follow_symlinks=False)
    except OSError as exc:
        raise Phase5ComponentAdapterV3Error("component source read failed") from exc
    identity_after = (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
        final.st_ctime_ns,
    )
    if identity_before != identity_after or len(content) != final.st_size:
        raise Phase5ComponentAdapterV3Error("component source changed during read")
    digest = hashlib.sha256(content).hexdigest()
    with _SOURCE_CACHE_LOCK:
        if len(_SOURCE_CACHE) >= 64:
            _SOURCE_CACHE.clear()
        _SOURCE_CACHE[cache_key] = digest
    return (
        module_name,
        qualname,
        str(canonical),
        digest,
        len(content),
    )


def _instance_identity(value: object) -> str:
    return hashlib.sha256(
        f"{type(value).__module__}:{type(value).__qualname__}:{id(value):x}".encode()
    ).hexdigest()


def _exact_record_payload(value: object) -> dict[str, object]:
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        raise Phase5ComponentAdapterV3ContractError("exact dataclass record required")
    payload: dict[str, object] = {}
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if type(item) not in {str, int, bool} and item is not None:
            raise Phase5ComponentAdapterV3ContractError(
                "attested record contains non-canonical value"
            )
        payload[field.name] = item
    return payload


def _receipt_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(_exact_record_payload(value))).hexdigest()


def _callable_identity(value: object, label: str) -> str:
    if not callable(value):
        raise Phase5ComponentAdapterV3ContractError(f"{label} must be callable")
    module, qualname, path, digest, size = _source_identity(value)
    payload: dict[str, object] = {
        "module": module,
        "qualname": qualname,
        "path": path,
        "source_sha256": digest,
        "source_size": size,
        "callable_identity": _instance_identity(value),
        "bound_identity": None
        if getattr(value, "__self__", None) is None
        else _instance_identity(value.__self__),
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _interface_digest(value: object, role: str) -> str:
    payload: list[dict[str, object]] = []
    for name in _ROLE_METHODS.get(role, ()):
        member = getattr(value, name, None)
        if not callable(member):
            raise Phase5ComponentAdapterV3ContractError(
                f"{role} lacks exact callable {name}"
            )
        function = getattr(member, "__func__", member)
        payload.append(
            {
                "name": name,
                "module": getattr(function, "__module__", ""),
                "qualname": getattr(function, "__qualname__", ""),
                "function_identity": f"{id(function):x}",
                "bound_identity": (
                    None
                    if getattr(member, "__self__", None) is None
                    else f"{id(member.__self__):x}"
                ),
            }
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class AdapterFlagsV3:
    adapters: bool = False
    grant_shadow: bool = False
    nexus_projection: bool = False
    approval_inbox: bool = False

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            _exact_bool(getattr(self, name), name)
        if not self.adapters and any(
            (self.grant_shadow, self.nexus_projection, self.approval_inbox)
        ):
            raise Phase5ComponentAdapterV3ContractError(
                "component flags require adapter master flag"
            )


@dataclass(frozen=True, slots=True)
class AcceptedComponentsV3:
    grants: str | None = None
    nexus: str | None = None
    inbox: str | None = None

    def require(self, name: str) -> None:
        expected = {
            "grants": GRANTS_ACCEPTANCE_V3,
            "nexus": NEXUS_ACCEPTANCE_V3,
            "inbox": INBOX_ACCEPTANCE_V3,
        }[name]
        if getattr(self, name) != expected:
            raise Phase5ComponentAdapterV3ContractError(
                f"{name} lacks exact external acceptance"
            )


@dataclass(frozen=True, slots=True)
class AdapterBindingV3:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))

    @classmethod
    def from_runtime(cls, value: object) -> "AdapterBindingV3":
        try:
            return cls(
                getattr(value, "trace_id"),
                getattr(value, "session_id"),
                getattr(value, "workspace_id"),
                getattr(value, "account_id"),
                getattr(value, "profile_id"),
            )
        except (AttributeError, TypeError) as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "runtime binding is malformed"
            ) from exc

    def payload(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ComponentAttestationV3:
    role: str
    accepted_root: str
    component_version: str
    module_name: str
    qualname: str
    canonical_module_path: str
    source_sha256: str
    source_size: int
    instance_identity: str
    interface_digest: str
    generation: int
    binding_digest: str | None
    nonce: str
    mac: str


@dataclass(frozen=True, slots=True)
class InboxConstructionReceiptV3:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    principal_id: str
    accepted_root: str
    accepted_source_sha256: str
    projection_identity: str
    source_identity: str
    capture_callback_identity: str
    epoch_reader_identity: str
    clock_identity: str
    store_scope_fingerprint: str
    generation: int
    nonce: str
    mac: str


@dataclass(frozen=True, slots=True)
class InboxSnapshotScopeReceiptV3:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    projection_identity: str
    source_identity: str
    construction_digest: str
    capture_sequence: int
    source_epoch: int
    item_count: int
    snapshot_digest: str
    snapshot_scope_fingerprint: str
    generation: int
    nonce: str
    mac: str


@dataclass(frozen=True, slots=True)
class InboxPageEnvelopeV3:
    phase: str
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str
    projection_identity: str
    source_identity: str
    construction_digest: str
    snapshot_scope_receipt_digest: str | None
    journey: int
    sequence: int
    generation: int
    request_digest: str
    page_digest: str | None
    nonce: str
    mac: str


@dataclass(slots=True)
class _EnvelopeWindowV3:
    generation: int
    highest_journey: int = 0
    active_journey: int | None = None
    next_sequence: int = 0
    pending_request: tuple[int, str, str | None] | None = None


class HostAttestationAuthorityV3:
    """Process-local signing root. Key bytes are copied and never exposed."""

    __slots__ = ("__key", "_lock", "_windows")

    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise Phase5ComponentAdapterV3ContractError(
                "host attestation key must be at least 32 exact bytes"
            )
        self.__key = bytes(key)
        self._lock = threading.RLock()
        self._windows: OrderedDict[str, _EnvelopeWindowV3] = OrderedDict()

    def _mac(self, domain: str, payload: Mapping[str, object]) -> str:
        return hmac.new(
            self.__key,
            domain.encode() + b"\0" + _canonical_json(payload),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _root_for(role: str) -> str:
        accepted = _ACCEPTED.get(role)
        return HOST_ROOT_V3 if accepted is None else accepted[0]

    def issue_component(
        self,
        value: object,
        *,
        role: str,
        generation: int,
        binding: AdapterBindingV3 | None = None,
    ) -> ComponentAttestationV3:
        role = _safe_id(role, "role")
        generation = _exact_int(generation, "generation", 0, MAX_SEQUENCE_V3)
        module, qualname, path, digest, size = _source_identity(value)
        accepted = _ACCEPTED.get(role)
        if binding is not None:
            raise Phase5ComponentAdapterV3ContractError(
                "unexpected component binding"
            )
        else:
            binding_digest = None
        if accepted is not None:
            (
                _root,
                expected_module,
                expected_qualname,
                expected_relative,
                _version,
                expected_digest,
            ) = accepted
            expected_path = (_PROJECT_ROOT / expected_relative).resolve(strict=True)
            if (
                module != expected_module
                or qualname != expected_qualname
                or Path(path) != expected_path
                or digest != expected_digest
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    f"{role} is not the exact accepted public component"
                )
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            "role": role,
            "accepted_root": self._root_for(role),
            "component_version": (
                ADAPTER_CONTRACT_V3 if accepted is None else accepted[4]
            ),
            "module_name": module,
            "qualname": qualname,
            "canonical_module_path": path,
            "source_sha256": digest,
            "source_size": size,
            "instance_identity": _instance_identity(value),
            "interface_digest": _interface_digest(value, role),
            "generation": generation,
            "binding_digest": binding_digest,
            "nonce": nonce,
        }
        return ComponentAttestationV3(**payload, mac=self._mac("component-v3", payload))

    def verify_component(
        self,
        value: object,
        attestation: ComponentAttestationV3,
        *,
        role: str,
        generation: int,
        binding: AdapterBindingV3 | None = None,
    ) -> None:
        if type(attestation) is not ComponentAttestationV3:
            raise Phase5ComponentAdapterV3ContractError(
                "exact component attestation required"
            )
        module, qualname, path, digest, size = _source_identity(value)
        if binding is not None:
            raise Phase5ComponentAdapterV3ContractError(
                "unexpected component binding"
            )
        else:
            binding_digest = None
        expected = {
            "role": _safe_id(role, "role"),
            "accepted_root": self._root_for(role),
            "component_version": (
                ADAPTER_CONTRACT_V3
                if _ACCEPTED.get(role) is None
                else _ACCEPTED[role][4]
            ),
            "module_name": module,
            "qualname": qualname,
            "canonical_module_path": path,
            "source_sha256": digest,
            "source_size": size,
            "instance_identity": _instance_identity(value),
            "interface_digest": _interface_digest(value, role),
            "generation": _exact_int(
                generation, "generation", 0, MAX_SEQUENCE_V3
            ),
            "binding_digest": binding_digest,
            "nonce": _text(attestation.nonce, "nonce", 64),
        }
        actual = {name: getattr(attestation, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            attestation.mac, self._mac("component-v3", expected)
        ):
            raise Phase5ComponentAdapterV3Error(
                f"{role} component attestation mismatch"
            )

    def issue_construction(
        self,
        *,
        binding: AdapterBindingV3,
        principal_id: str,
        projection_identity: str,
        source_identity: str,
        capture_callback_identity: str,
        epoch_reader_identity: str,
        clock_identity: str,
        store_scope_fingerprint: str,
        generation: int,
    ) -> InboxConstructionReceiptV3:
        if type(binding) is not AdapterBindingV3:
            raise Phase5ComponentAdapterV3ContractError("exact 5D binding required")
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            **binding.payload(),
            "principal_id": _safe_id(principal_id, "principal_id"),
            "accepted_root": INBOX_ROOT_V3,
            "accepted_source_sha256": _ACCEPTED["inbox"][5],
            "projection_identity": _digest(projection_identity, "projection_identity"),
            "source_identity": _digest(source_identity, "source_identity"),
            "capture_callback_identity": _digest(
                capture_callback_identity, "capture_callback_identity"
            ),
            "epoch_reader_identity": _digest(
                epoch_reader_identity, "epoch_reader_identity"
            ),
            "clock_identity": _digest(clock_identity, "clock_identity"),
            "store_scope_fingerprint": _digest(
                store_scope_fingerprint, "store_scope_fingerprint"
            ),
            "generation": _exact_int(generation, "generation", 0, MAX_SEQUENCE_V3),
            "nonce": nonce,
        }
        receipt = InboxConstructionReceiptV3(
            **payload, mac=self._mac("inbox-construction-v3", payload)
        )
        with self._lock:
            if projection_identity in self._windows:
                raise Phase5ComponentAdapterV3Error(
                    "inbox construction identity already registered"
                )
            if len(self._windows) >= MAX_ACTIVE_INBOX_OWNERS_V3:
                raise Phase5ComponentAdapterV3Error(
                    "active inbox owner capacity exhausted"
                )
            self._windows[projection_identity] = _EnvelopeWindowV3(generation)
        return receipt

    def verify_construction(
        self,
        value: InboxConstructionReceiptV3,
        *,
        binding: AdapterBindingV3,
        principal_id: str,
        projection_identity: str,
        source_identity: str,
        capture_callback_identity: str,
        epoch_reader_identity: str,
        clock_identity: str,
        store_scope_fingerprint: str,
        generation: int,
    ) -> None:
        if type(value) is not InboxConstructionReceiptV3:
            raise Phase5ComponentAdapterV3ContractError(
                "exact inbox construction receipt required"
            )
        expected = {
            **binding.payload(),
            "principal_id": principal_id,
            "accepted_root": INBOX_ROOT_V3,
            "accepted_source_sha256": _ACCEPTED["inbox"][5],
            "projection_identity": projection_identity,
            "source_identity": source_identity,
            "capture_callback_identity": capture_callback_identity,
            "epoch_reader_identity": epoch_reader_identity,
            "clock_identity": clock_identity,
            "store_scope_fingerprint": store_scope_fingerprint,
            "generation": generation,
            "nonce": _text(value.nonce, "construction nonce", 64),
        }
        actual = {name: getattr(value, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            value.mac, self._mac("inbox-construction-v3", expected)
        ):
            raise Phase5ComponentAdapterV3Error("inbox construction receipt mismatch")
        with self._lock:
            window = self._windows.get(projection_identity)
            if window is None or window.generation != generation:
                raise Phase5ComponentAdapterV3Error(
                    "inbox construction owner unavailable"
                )

    def issue_snapshot_scope(
        self,
        *,
        binding: AdapterBindingV3,
        projection_identity: str,
        source_identity: str,
        construction_digest: str,
        capture_sequence: int,
        source_epoch: int,
        item_count: int,
        snapshot_digest: str,
        snapshot_scope_fingerprint: str,
        generation: int,
    ) -> InboxSnapshotScopeReceiptV3:
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            **binding.payload(),
            "projection_identity": _digest(projection_identity, "projection_identity"),
            "source_identity": _digest(source_identity, "source_identity"),
            "construction_digest": _digest(construction_digest, "construction_digest"),
            "capture_sequence": _exact_int(
                capture_sequence, "capture_sequence", 1, MAX_SEQUENCE_V3
            ),
            "source_epoch": _exact_int(source_epoch, "source_epoch", 0, MAX_SEQUENCE_V3),
            "item_count": _exact_int(item_count, "item_count", 0, MAX_ITEMS_V3),
            "snapshot_digest": _digest(snapshot_digest, "snapshot_digest"),
            "snapshot_scope_fingerprint": _digest(
                snapshot_scope_fingerprint, "snapshot_scope_fingerprint"
            ),
            "generation": _exact_int(generation, "generation", 0, MAX_SEQUENCE_V3),
            "nonce": nonce,
        }
        return InboxSnapshotScopeReceiptV3(
            **payload, mac=self._mac("inbox-snapshot-scope-v3", payload)
        )

    def verify_snapshot_scope(
        self,
        value: InboxSnapshotScopeReceiptV3,
        **expected_values: object,
    ) -> None:
        if type(value) is not InboxSnapshotScopeReceiptV3:
            raise Phase5ComponentAdapterV3ContractError(
                "exact inbox snapshot scope receipt required"
            )
        expected = dict(expected_values)
        expected["nonce"] = _text(value.nonce, "snapshot nonce", 64)
        actual = {name: getattr(value, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            value.mac, self._mac("inbox-snapshot-scope-v3", expected)
        ):
            raise Phase5ComponentAdapterV3Error("inbox snapshot scope mismatch")

    def issue_page_envelope(
        self,
        *,
        phase: str,
        binding: AdapterBindingV3,
        projection_identity: str,
        source_identity: str,
        construction_digest: str,
        snapshot_scope_receipt_digest: str | None,
        journey: int,
        sequence: int,
        generation: int,
        request_digest: str,
        page_digest: str | None,
    ) -> InboxPageEnvelopeV3:
        phase = _text(phase, "phase", 8)
        if phase not in {"pre", "post"}:
            raise Phase5ComponentAdapterV3ContractError("page phase invalid")
        if phase == "pre":
            if page_digest is not None or snapshot_scope_receipt_digest is not None:
                raise Phase5ComponentAdapterV3ContractError(
                    "pre envelope cannot claim output scope"
                )
        else:
            page_digest = _digest(page_digest, "page_digest")
            snapshot_scope_receipt_digest = _digest(
                snapshot_scope_receipt_digest, "snapshot_scope_receipt_digest"
            )
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            "phase": phase,
            **binding.payload(),
            "projection_identity": _digest(projection_identity, "projection_identity"),
            "source_identity": _digest(source_identity, "source_identity"),
            "construction_digest": _digest(construction_digest, "construction_digest"),
            "snapshot_scope_receipt_digest": snapshot_scope_receipt_digest,
            "journey": _exact_int(journey, "journey", 1, MAX_SEQUENCE_V3),
            "sequence": _exact_int(sequence, "sequence", 0, MAX_SEQUENCE_V3),
            "generation": _exact_int(generation, "generation", 0, MAX_SEQUENCE_V3),
            "request_digest": _digest(request_digest, "request_digest"),
            "page_digest": page_digest,
            "nonce": nonce,
        }
        return InboxPageEnvelopeV3(
            **payload, mac=self._mac("inbox-page-envelope-v3", payload)
        )

    def verify_page_envelope(
        self,
        value: InboxPageEnvelopeV3,
        *,
        binding: AdapterBindingV3,
        projection_identity: str,
        source_identity: str,
        construction_digest: str,
        snapshot_scope_receipt_digest: str | None,
        journey: int,
        sequence: int,
        generation: int,
        request_digest: str,
        page_digest: str | None,
        journey_complete: bool,
    ) -> None:
        if type(value) is not InboxPageEnvelopeV3:
            raise Phase5ComponentAdapterV3ContractError("exact page envelope required")
        phase = value.phase
        if phase not in {"pre", "post"}:
            raise Phase5ComponentAdapterV3ContractError("page phase invalid")
        expected = {
            "phase": phase,
            **binding.payload(),
            "projection_identity": projection_identity,
            "source_identity": source_identity,
            "construction_digest": construction_digest,
            "snapshot_scope_receipt_digest": snapshot_scope_receipt_digest,
            "journey": journey,
            "sequence": sequence,
            "generation": generation,
            "request_digest": request_digest,
            "page_digest": page_digest,
            "nonce": _text(value.nonce, "envelope nonce", 64),
        }
        actual = {name: getattr(value, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            value.mac, self._mac("inbox-page-envelope-v3", expected)
        ):
            raise Phase5ComponentAdapterV3Error("inbox page envelope mismatch")
        with self._lock:
            window = self._windows.get(projection_identity)
            if window is None or window.generation != generation:
                raise Phase5ComponentAdapterV3Error("inbox envelope owner unavailable")
            if phase == "pre":
                if snapshot_scope_receipt_digest is not None or page_digest is not None:
                    raise Phase5ComponentAdapterV3ContractError(
                        "pre envelope contains output evidence"
                    )
                if window.pending_request is not None:
                    raise Phase5ComponentAdapterV3Error("inbox envelope phase replay")
                if window.active_journey is None:
                    if journey <= window.highest_journey or sequence != 0:
                        raise Phase5ComponentAdapterV3Error(
                            "inbox journey replay or sequence drift"
                        )
                    window.active_journey = journey
                    window.next_sequence = 0
                if (
                    window.active_journey != journey
                    or window.next_sequence != sequence
                ):
                    raise Phase5ComponentAdapterV3Error(
                        "inbox journey or sequence drift"
                    )
                window.pending_request = (sequence, request_digest, None)
            else:
                pending = window.pending_request
                if (
                    pending is None
                    or window.active_journey != journey
                    or window.next_sequence != sequence
                    or pending[:2] != (sequence, request_digest)
                    or snapshot_scope_receipt_digest is None
                    or page_digest is None
                ):
                    raise Phase5ComponentAdapterV3Error(
                        "inbox post envelope replay or relation drift"
                    )
                window.pending_request = None
                window.next_sequence += 1
                if journey_complete:
                    window.highest_journey = journey
                    window.active_journey = None
                    window.next_sequence = 0

    def abort_journey(self, projection_identity: str, *, generation: int) -> None:
        with self._lock:
            window = self._windows.get(projection_identity)
            if window is None or window.generation != generation:
                return
            if window.active_journey is not None:
                window.highest_journey = max(
                    window.highest_journey, window.active_journey
                )
            window.active_journey = None
            window.next_sequence = 0
            window.pending_request = None

    def release_owner(self, projection_identity: str, *, generation: int) -> None:
        with self._lock:
            window = self._windows.get(projection_identity)
            if window is not None and window.generation == generation:
                del self._windows[projection_identity]

    @property
    def active_inbox_state_size(self) -> int:
        with self._lock:
            return len(self._windows)


class _BindingGuardV3:
    __slots__ = ("_attestor", "binding")

    def __init__(self, binding: AdapterBindingV3, attestor: Callable[[], object]) -> None:
        if not callable(attestor):
            raise Phase5ComponentAdapterV3ContractError(
                "binding_attestor is required"
            )
        self.binding = binding
        self._attestor = attestor

    def validate_runtime(self, value: object) -> None:
        if AdapterBindingV3.from_runtime(value) != self.binding:
            raise Phase5ComponentAdapterV3ContractError("runtime binding mismatch")

    def attest(self) -> None:
        try:
            current = self._attestor()
        except BaseException as exc:
            raise Phase5ComponentAdapterV3Error("binding attestation failed") from exc
        if AdapterBindingV3.from_runtime(current) != self.binding:
            raise Phase5ComponentAdapterV3Error("binding attestation mismatch")


@dataclass(frozen=True, slots=True)
class _CallTokenV3:
    generation: int
    component_identity: str


class _LifecycleV3:
    __slots__ = ("_closed", "_generation", "_lock")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin(self, component: object) -> _CallTokenV3:
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV3Error("adapter is closed")
            return _CallTokenV3(self._generation, _instance_identity(component))

    def finish(self, token: _CallTokenV3, component: object) -> None:
        with self._lock:
            if (
                self._closed
                or token.generation != self._generation
                or token.component_identity != _instance_identity(component)
            ):
                raise Phase5ComponentAdapterV3Error(
                    "adapter lifecycle changed during component call"
                )

    def close(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._closed = True
            self._generation += 1
            return True

    def invalidate(self, component: object) -> _CallTokenV3 | None:
        with self._lock:
            if self._closed:
                return None
            token = _CallTokenV3(
                self._generation, _instance_identity(component)
            )
            self._closed = True
            self._generation += 1
            return token


def _attested_call(
    *,
    lifecycle: _LifecycleV3,
    authority: HostAttestationAuthorityV3,
    component_getter: Callable[[], object],
    attestation: ComponentAttestationV3,
    role: str,
    callback: Callable[[object], object],
    binding: AdapterBindingV3 | None = None,
) -> tuple[object, _CallTokenV3]:
    component = component_getter()
    token = lifecycle.begin(component)
    authority.verify_component(
        component,
        attestation,
        role=role,
        generation=token.generation,
        binding=binding,
    )
    try:
        result = callback(component)
    except BaseException as exc:
        raise Phase5ComponentAdapterV3Error(f"{role} call failed") from exc
    current = component_getter()
    authority.verify_component(
        current,
        attestation,
        role=role,
        generation=token.generation,
        binding=binding,
    )
    lifecycle.finish(token, current)
    return result, token


_ACTION_FIELDS_V3 = (
    "invocation_ref",
    "binding",
    "capability",
    "operation",
    "provider_free",
    "read_only",
    "effect",
    "egress",
    "metadata_allowlisted",
    "cost_micro",
    "risk",
    "reversible",
    "uses_credentials",
    "privileged",
    "irreversible",
    "action_classes",
)


def _validate_action(
    request: object,
    *,
    expected_type: type,
    reference: str,
    binding: AdapterBindingV3,
) -> tuple[object, ...]:
    if type(request) is not expected_type:
        raise Phase5ComponentAdapterV3ContractError(
            "materializer returned wrong exact ActionRequest type"
        )
    params = getattr(expected_type, "__dataclass_params__", None)
    if params is None or not params.frozen:
        raise Phase5ComponentAdapterV3ContractError(
            "ActionRequest type must be frozen"
        )
    try:
        values = tuple(getattr(request, name) for name in _ACTION_FIELDS_V3)
    except AttributeError as exc:
        raise Phase5ComponentAdapterV3ContractError(
            "ActionRequest is incomplete"
        ) from exc
    (
        invocation_ref,
        request_binding,
        capability,
        operation,
        provider_free,
        read_only,
        effect,
        egress,
        metadata_allowlisted,
        cost_micro,
        risk,
        reversible,
        uses_credentials,
        privileged,
        irreversible,
        action_classes,
    ) = values
    exact = (
        type(invocation_ref) is str
        and invocation_ref == reference
        and AdapterBindingV3.from_runtime(request_binding) == binding
        and type(capability) is str
        and capability == "local.catalog"
        and type(operation) is str
        and operation == "catalog_read"
        and type(provider_free) is bool
        and provider_free is True
        and type(read_only) is bool
        and read_only is True
        and type(effect) is str
        and effect == "none"
        and type(egress) is str
        and egress == "none"
        and type(metadata_allowlisted) is bool
        and metadata_allowlisted is True
        and type(cost_micro) is int
        and not isinstance(cost_micro, bool)
        and cost_micro == 0
        and type(risk) is str
        and risk == "low"
        and type(reversible) is bool
        and reversible is True
        and type(uses_credentials) is bool
        and uses_credentials is False
        and type(privileged) is bool
        and privileged is False
        and type(irreversible) is bool
        and irreversible is False
        and type(action_classes) is tuple
        and not action_classes
    )
    if not exact:
        raise Phase5ComponentAdapterV3ContractError(
            "ActionRequest is not the exact local catalog action"
        )
    return values


class GrantShadowAdapterV3:
    __slots__ = (
        "_action_type",
        "_action_type_attestation",
        "_authority",
        "_decision_type",
        "_guard",
        "_lifecycle",
        "_materialize",
        "_materialize_attestation",
        "_store",
        "_store_attestation",
    )

    def __init__(
        self,
        *,
        binding: AdapterBindingV3,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV3,
        store: object,
        store_attestation: ComponentAttestationV3,
        materialize_request: Callable[[str], object],
        materializer_attestation: ComponentAttestationV3,
        action_request_type: type,
        action_request_type_attestation: ComponentAttestationV3,
    ) -> None:
        self._guard = _BindingGuardV3(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV3()
        self._store = store
        self._store_attestation = store_attestation
        self._materialize = materialize_request
        self._materialize_attestation = materializer_attestation
        if not callable(materialize_request) or not isinstance(action_request_type, type):
            raise Phase5ComponentAdapterV3ContractError(
                "exact grant materializer and ActionRequest type required"
            )
        self._action_type = action_request_type
        self._action_type_attestation = action_request_type_attestation
        module = inspect.getmodule(type(store))
        self._decision_type = (
            None if module is None else getattr(module, "ShadowGrantDecision", None)
        )
        if not isinstance(self._decision_type, type):
            raise Phase5ComponentAdapterV3ContractError(
                "accepted grant decision type unavailable"
            )
        _callable_member(store, "evaluate")
        _callable_member(store, "end_session")
        _callable_member(store, "kill")
        for value, attestation, role in (
            (store, store_attestation, "grant_store"),
            (materialize_request, materializer_attestation, "grant_materializer"),
            (
                action_request_type,
                action_request_type_attestation,
                "action_request_type",
            ),
        ):
            authority.verify_component(
                value,
                attestation,
                role=role,
                generation=0,
            )

    def evaluate(self, invocation_ref: str) -> dict[str, object]:
        reference = _safe_id(invocation_ref, "invocation_ref")
        self._guard.attest()
        request, materialize_token = _attested_call(
            lifecycle=self._lifecycle,
            authority=self._authority,
            component_getter=lambda: self._materialize,
            attestation=self._materialize_attestation,
            role="grant_materializer",
            callback=lambda component: component(reference),
        )
        snapshot = _validate_action(
            request,
            expected_type=self._action_type,
            reference=reference,
            binding=self._guard.binding,
        )
        self._authority.verify_component(
            self._action_type,
            self._action_type_attestation,
            role="action_request_type",
            generation=materialize_token.generation,
        )
        decision, store_token = _attested_call(
            lifecycle=self._lifecycle,
            authority=self._authority,
            component_getter=lambda: self._store,
            attestation=self._store_attestation,
            role="grant_store",
            callback=lambda component: _callable_member(component, "evaluate")(
                reference
            ),
        )
        self._lifecycle.finish(materialize_token, self._materialize)
        self._lifecycle.finish(store_token, self._store)
        if tuple(getattr(request, name) for name in _ACTION_FIELDS_V3) != snapshot:
            raise Phase5ComponentAdapterV3Error(
                "ActionRequest changed after materialization"
            )
        if type(request) is not self._action_type:
            raise Phase5ComponentAdapterV3Error(
                "ActionRequest type changed after materialization"
            )
        self._authority.verify_component(
            self._action_type,
            self._action_type_attestation,
            role="action_request_type",
            generation=store_token.generation,
        )
        self._guard.attest()
        if type(decision) is not self._decision_type:
            raise Phase5ComponentAdapterV3ContractError(
                "grant evaluator returned wrong exact decision type"
            )
        try:
            outcome = _text(decision.outcome, "outcome", 32)
            reason = _safe_id(decision.reason, "reason")
            grant_id = decision.grant_id
            if grant_id is not None:
                grant_id = _safe_id(grant_id, "grant_id")
            scope = _digest(decision.scope_digest, "scope_digest")
            action = _digest(decision.action_audit_digest, "action_audit_digest")
            if outcome not in {"disabled", "would-allow", "would-deny"}:
                raise Phase5ComponentAdapterV3ContractError("grant outcome invalid")
            if (
                type(decision.authority_granted) is not bool
                or decision.authority_granted
                or type(decision.callback_required) is not bool
                or not decision.callback_required
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "grant decision conveyed authority"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "grant decision incomplete"
            ) from exc
        advisory: dict[str, object] = {
            "outcome": outcome,
            "reason": reason,
            "scope_digest": scope,
            "action_digest": action,
        }
        if grant_id is not None:
            advisory["grant_id"] = grant_id
        if len(_canonical_json(advisory)) > MAX_ADVISORY_BYTES_V3:
            raise Phase5ComponentAdapterV3ContractError("grant advisory too large")
        return advisory

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV3ContractError("terminal reason invalid")
        component = self._store
        token = self._lifecycle.invalidate(component)
        if token is None:
            return
        self._authority.verify_component(
            component,
            self._store_attestation,
            role="grant_store",
            generation=token.generation,
        )
        callback = "kill" if reason == "kill" else "end_session"
        failure: BaseException | None = None
        try:
            _callable_member(component, callback)()
        except BaseException as exc:
            failure = exc
        current = self._store
        self._authority.verify_component(
            current,
            self._store_attestation,
            role="grant_store",
            generation=token.generation,
        )
        if current is not component:
            raise Phase5ComponentAdapterV3Error(
                "grant store changed during terminal callback"
            )
        if failure is not None:
            raise Phase5ComponentAdapterV3Error(
                f"grant {callback} failed after local close"
            ) from failure


class CapabilityNexusAdapterV3:
    __slots__ = (
        "_authority",
        "_batch_factory",
        "_batch_attestation",
        "_guard",
        "_lifecycle",
        "_nexus",
        "_nexus_attestation",
    )

    def __init__(
        self,
        *,
        binding: AdapterBindingV3,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV3,
        nexus: object,
        nexus_attestation: ComponentAttestationV3,
        batch_factory: RuntimeBatchFactoryV3,
        batch_attestation: ComponentAttestationV3,
    ) -> None:
        self._guard = _BindingGuardV3(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV3()
        self._nexus = nexus
        self._nexus_attestation = nexus_attestation
        self._batch_factory = batch_factory
        self._batch_attestation = batch_attestation
        _callable_member(nexus, "snapshot")
        if not callable(batch_factory):
            raise Phase5ComponentAdapterV3ContractError("batch_factory required")
        authority.verify_component(nexus, nexus_attestation, role="nexus", generation=0)
        authority.verify_component(
            batch_factory, batch_attestation, role="batch_factory", generation=0
        )

    @staticmethod
    def _project(entry: object, binding: AdapterBindingV3) -> dict[str, object]:
        try:
            descriptor = entry.descriptor
            if any(
                getattr(entry, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "nexus projection binding mismatch"
                )
            if (
                type(entry.runtime_available) is not bool
                or entry.runtime_available
                or type(entry.authority_granted) is not bool
                or entry.authority_granted
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "nexus projection conveyed authority"
                )
            if descriptor.capability_id != "local.catalog":
                raise Phase5ComponentAdapterV3ContractError(
                    "unexpected capability"
                )
            if any(
                getattr(descriptor, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "nexus descriptor binding mismatch"
                )
            operations = descriptor.operations
            if type(operations) is not tuple or len(operations) != 1:
                raise Phase5ComponentAdapterV3ContractError(
                    "local catalog operation set invalid"
                )
            operation = operations[0]
            exact = (
                descriptor.provider == "onyx_local"
                and _enum_value(descriptor.transport, "transport") == "local"
                and descriptor.api_name == "local_catalog"
                and descriptor.credential_alias is None
                and operation.operation_id == "catalog_read"
                and _enum_value(operation.kind, "operation kind") == "read"
                and operation.required_scopes == ("catalog.metadata.read",)
                and operation.data_classes == ("allowlisted_metadata",)
                and operation.risk_class == "low"
                and operation.allowed_targets == ("local_catalog",)
                and operation.allowed_domains == ()
                and operation.cost == "zero_local_micros"
                and operation.host_policy == "always_confirm"
            )
            if not exact:
                raise Phase5ComponentAdapterV3ContractError(
                    "local catalog descriptor not exact"
                )
            status_value = _NEXUS_STATUS.get(
                _enum_value(entry.projection_status, "projection_status")
            )
            if status_value is None:
                raise Phase5ComponentAdapterV3ContractError("nexus status invalid")
            return {
                "capability_id": "local.catalog",
                "display_name": "Local catalog metadata",
                "provider": "onyx_local",
                "version": _safe_id(
                    descriptor.capability_version, "capability_version"
                ),
                "status": status_value,
                "operations": ("catalog_read",),
                "limitation": _CATALOG_LIMITATION,
            }
        except AttributeError as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "nexus projection incomplete"
            ) from exc

    def project(self, runtime_binding: object) -> object:
        self._guard.validate_runtime(runtime_binding)
        self._guard.attest()
        binding = self._guard.binding
        snapshot, token = _attested_call(
            lifecycle=self._lifecycle,
            authority=self._authority,
            component_getter=lambda: self._nexus,
            attestation=self._nexus_attestation,
            role="nexus",
            callback=lambda component: _callable_member(component, "snapshot")(
                workspace_id=binding.workspace_id,
                account_id=binding.account_id,
                profile_id=binding.profile_id,
            ),
        )
        self._guard.attest()
        try:
            if any(
                getattr(snapshot, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "nexus snapshot binding mismatch"
                )
            entries = snapshot.entries
            source_cursor = _digest(snapshot.snapshot_digest, "snapshot_digest")
        except AttributeError as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "nexus snapshot incomplete"
            ) from exc
        if type(entries) is not tuple or len(entries) > MAX_ITEMS_V3:
            raise Phase5ComponentAdapterV3ContractError(
                "nexus snapshot cardinality invalid"
            )
        local = tuple(
            entry
            for entry in entries
            if getattr(getattr(entry, "descriptor", None), "capability_id", None)
            == "local.catalog"
        )
        if len(local) != 1:
            raise Phase5ComponentAdapterV3Error(
                "accepted local.catalog absent or duplicated"
            )
        item = self._project(local[0], binding)
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        result = _make_batch_v3(
            self._batch_factory,
            (item,),
            replace=True,
            source_cursor=source_cursor,
            next_cursor=None,
        )
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        self._lifecycle.finish(token, self._nexus)
        return result

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV3ContractError("terminal reason invalid")
        self._lifecycle.close()


@dataclass(frozen=True, slots=True)
class InboxConstructionInputsV3:
    principal_id: str
    capture_callback: Callable[[], object]
    epoch_reader: Callable[[], int]
    clock: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "principal_id", _safe_id(self.principal_id, "principal_id"))
        if not callable(self.capture_callback) or not callable(self.epoch_reader):
            raise Phase5ComponentAdapterV3ContractError(
                "inbox capture callback and epoch reader are required"
            )
        if type(self.clock) not in {
            _inbox_v15.MonotonicInboxClockV15,
            _inbox_v15.DeterministicInboxClockV15,
        }:
            raise Phase5ComponentAdapterV3ContractError(
                "exact accepted V15 monotonic clock required"
            )


class _ScopedInboxCaptureV3:
    """Host-owned sidecar that derives scope from each actual V15 snapshot."""

    __slots__ = (
        "_authority",
        "_binding",
        "_callback",
        "_capture_sequence",
        "_construction_digest",
        "_generation",
        "_latest",
        "_lock",
        "_projection_identity",
        "_source_identity",
    )

    def __init__(
        self,
        *,
        authority: HostAttestationAuthorityV3,
        binding: AdapterBindingV3,
        callback: Callable[[], object],
        generation: int,
    ) -> None:
        self._authority = authority
        self._binding = binding
        self._callback = callback
        self._generation = generation
        self._capture_sequence = 0
        self._construction_digest: str | None = None
        self._projection_identity: str | None = None
        self._source_identity: str | None = None
        self._latest: InboxSnapshotScopeReceiptV3 | None = None
        self._lock = threading.RLock()

    def attach(
        self,
        *,
        construction_digest: str,
        projection_identity: str,
        source_identity: str,
    ) -> None:
        with self._lock:
            if self._construction_digest is not None:
                raise Phase5ComponentAdapterV3Error("inbox sidecar already attached")
            self._construction_digest = _digest(
                construction_digest, "construction_digest"
            )
            self._projection_identity = _digest(
                projection_identity, "projection_identity"
            )
            self._source_identity = _digest(source_identity, "source_identity")

    def prepare_capture(self) -> int:
        with self._lock:
            self._latest = None
            return self._capture_sequence + 1

    def capture(self) -> object:
        raw = self._callback()
        if type(raw) is not _inbox_v15.HostInboxSnapshotV15:
            raise Phase5ComponentAdapterV3ContractError(
                "host capture returned wrong V15 snapshot type"
            )
        if type(raw.items) is not tuple or len(raw.items) > MAX_ITEMS_V3:
            raise Phase5ComponentAdapterV3ContractError(
                "host capture item collection is invalid"
            )
        for item in raw.items:
            if type(item) is not _inbox_v15.HostInboxItemV15:
                raise Phase5ComponentAdapterV3ContractError(
                    "host capture item has wrong V15 type"
                )
            for name in ("session_id", "workspace_id", "account_id"):
                value = getattr(item, name)
                if type(value) is not str or value != getattr(self._binding, name):
                    raise Phase5ComponentAdapterV3ContractError(
                        f"host capture {name} scope mismatch"
                    )
        source_epoch = _exact_int(
            raw.source_epoch, "source_epoch", 0, MAX_SEQUENCE_V3
        )
        snapshot_digest = hashlib.sha256(
            _canonical_json(_page_payload(raw))
        ).hexdigest()
        with self._lock:
            if (
                self._construction_digest is None
                or self._projection_identity is None
                or self._source_identity is None
            ):
                raise Phase5ComponentAdapterV3Error("inbox sidecar is unattached")
            if self._capture_sequence >= MAX_SEQUENCE_V3:
                raise Phase5ComponentAdapterV3Error(
                    "inbox capture sequence exhausted"
                )
            self._capture_sequence += 1
            scope_payload: dict[str, object] = {
                **self._binding.payload(),
                "source_epoch": source_epoch,
                "item_count": len(raw.items),
                "snapshot_digest": snapshot_digest,
                "capture_sequence": self._capture_sequence,
            }
            scope_fingerprint = hashlib.sha256(
                _canonical_json(scope_payload)
            ).hexdigest()
            self._latest = self._authority.issue_snapshot_scope(
                binding=self._binding,
                projection_identity=self._projection_identity,
                source_identity=self._source_identity,
                construction_digest=self._construction_digest,
                capture_sequence=self._capture_sequence,
                source_epoch=source_epoch,
                item_count=len(raw.items),
                snapshot_digest=snapshot_digest,
                snapshot_scope_fingerprint=scope_fingerprint,
                generation=self._generation,
            )
        return raw

    def consume_capture(
        self, expected_sequence: int
    ) -> InboxSnapshotScopeReceiptV3:
        with self._lock:
            receipt = self._latest
            self._latest = None
        if receipt is None or receipt.capture_sequence != expected_sequence:
            raise Phase5ComponentAdapterV3Error(
                "V15 page lacks the exact source capture receipt"
            )
        return receipt


def _construct_inbox_v3(
    *,
    binding: AdapterBindingV3,
    authority: HostAttestationAuthorityV3,
    inputs: InboxConstructionInputsV3,
    generation: int,
) -> tuple[
    object,
    object,
    _ScopedInboxCaptureV3,
    ComponentAttestationV3,
    InboxConstructionReceiptV3,
]:
    # All V15 constructor types must still come from the exact accepted source.
    for value in (
        _inbox_v15.ApprovalInboxProjectionV15,
        _inbox_v15.ApprovalInboxFeatureGateV15,
        _inbox_v15.HostInboxSourceV15,
        type(inputs.clock),
    ):
        module, _qualname, path, digest, _size = _source_identity(value)
        if (
            module != "core.approval_inbox_v15"
            or Path(path) != (_PROJECT_ROOT / "core/approval_inbox_v15.py").resolve(strict=True)
            or digest != _ACCEPTED["inbox"][5]
        ):
            raise Phase5ComponentAdapterV3ContractError(
                "inbox constructor does not come from accepted V15 source"
            )
    callback_identity = _callable_identity(
        inputs.capture_callback, "capture_callback"
    )
    epoch_identity = _callable_identity(inputs.epoch_reader, "epoch_reader")
    clock_identity = hashlib.sha256(
        _canonical_json(
            {
                "source": _source_identity(type(inputs.clock))[3],
                "instance": _instance_identity(inputs.clock),
                "type": type(inputs.clock).__qualname__,
            }
        )
    ).hexdigest()
    sidecar = _ScopedInboxCaptureV3(
        authority=authority,
        binding=binding,
        callback=inputs.capture_callback,
        generation=generation,
    )
    source = _inbox_v15.HostInboxSourceV15(
        principal_id=inputs.principal_id,
        session_id=binding.session_id,
        capture_callback=sidecar.capture,
    )
    gate = _inbox_v15.ApprovalInboxFeatureGateV15(
        environ={_inbox_v15.APPROVAL_INBOX_V15_FLAG: "true"},
        epoch_reader=inputs.epoch_reader,
    )
    projection = _inbox_v15.ApprovalInboxProjectionV15(
        gate=gate, source=source, clock=inputs.clock
    )
    if (
        projection._source is not source
        or source.session_id != binding.session_id
        or source.principal_id != inputs.principal_id
        or getattr(source._capture_callback, "__self__", None) is not sidecar
        or getattr(source._capture_callback, "__func__", None)
        is not _ScopedInboxCaptureV3.capture
    ):
        raise Phase5ComponentAdapterV3Error(
            "V15 construction did not retain the scoped source"
        )
    projection_identity = _instance_identity(projection)
    source_identity = _instance_identity(source)
    store_scope_fingerprint = hashlib.sha256(
        _canonical_json(
            {
                **binding.payload(),
                "principal_id": inputs.principal_id,
                "capture_callback_identity": callback_identity,
                "source_identity": source_identity,
            }
        )
    ).hexdigest()
    receipt = authority.issue_construction(
        binding=binding,
        principal_id=inputs.principal_id,
        projection_identity=projection_identity,
        source_identity=source_identity,
        capture_callback_identity=callback_identity,
        epoch_reader_identity=epoch_identity,
        clock_identity=clock_identity,
        store_scope_fingerprint=store_scope_fingerprint,
        generation=generation,
    )
    try:
        sidecar.attach(
            construction_digest=_receipt_digest(receipt),
            projection_identity=projection_identity,
            source_identity=source_identity,
        )
        attestation = authority.issue_component(
            projection, role="inbox", generation=generation
        )
    except BaseException:
        authority.release_owner(projection_identity, generation=generation)
        raise
    return projection, source, sidecar, attestation, receipt


@dataclass(frozen=True, slots=True)
class _CursorRecordV3:
    generation: int
    source_cursor: str
    page_size: int
    expected_offset: int
    total_items: int
    snapshot_id: str
    view_digest: str
    journey: int
    sequence: int
    scope_receipt: InboxSnapshotScopeReceiptV3


def _page_payload(value: object) -> dict[str, object]:
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        raise Phase5ComponentAdapterV3ContractError(
            "page must be an exact dataclass value"
        )

    def convert(item: object) -> object:
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return {
                field.name: convert(getattr(item, field.name))
                for field in dataclasses.fields(item)
            }
        if type(item) is tuple:
            return [convert(child) for child in item]
        if type(item) in {str, int, bool} or item is None:
            return item
        raw = getattr(item, "value", None)
        if type(raw) is str:
            return raw
        raise Phase5ComponentAdapterV3ContractError(
            "page contains non-canonical data"
        )

    converted = convert(value)
    assert type(converted) is dict
    return converted


def _page_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(_page_payload(value))).hexdigest()


def _request_digest(
    binding: AdapterBindingV3,
    *,
    component_identity: str,
    source_identity: str,
    construction_digest: str,
    generation: int,
    journey: int,
    sequence: int,
    page_size: int,
    cursor: str | None,
) -> str:
    payload: dict[str, object] = {
        **binding.payload(),
        "component_identity": component_identity,
        "source_identity": source_identity,
        "construction_digest": construction_digest,
        "generation": generation,
        "journey": journey,
        "sequence": sequence,
        "page_size": page_size,
        "cursor": cursor,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class ApprovalInboxAdapterV3:
    __slots__ = (
        "_authority",
        "_batch_attestation",
        "_batch_factory",
        "_callback_identity",
        "_callback_instance_identity",
        "_clock_identity",
        "_clock_instance_identity",
        "_counter",
        "_cursors",
        "_guard",
        "_inputs",
        "_epoch_identity",
        "_epoch_instance_identity",
        "_journey",
        "_lifecycle",
        "_lock",
        "_read_lock",
        "_projection",
        "_projection_attestation",
        "_source",
        "_sidecar",
        "_store_scope_fingerprint",
        "_construction_receipt",
    )

    def __init__(
        self,
        *,
        binding: AdapterBindingV3,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV3,
        projection: object,
        source: object,
        sidecar: _ScopedInboxCaptureV3,
        projection_attestation: ComponentAttestationV3,
        construction_receipt: InboxConstructionReceiptV3,
        construction_inputs: InboxConstructionInputsV3,
        batch_factory: RuntimeBatchFactoryV3,
        batch_attestation: ComponentAttestationV3,
    ) -> None:
        self._guard = _BindingGuardV3(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV3()
        self._projection = projection
        self._source = source
        self._sidecar = sidecar
        self._projection_attestation = projection_attestation
        self._construction_receipt = construction_receipt
        self._inputs = construction_inputs
        self._callback_identity = _callable_identity(
            construction_inputs.capture_callback, "capture_callback"
        )
        self._callback_instance_identity = _instance_identity(
            construction_inputs.capture_callback
        )
        self._epoch_identity = _callable_identity(
            construction_inputs.epoch_reader, "epoch_reader"
        )
        self._epoch_instance_identity = _instance_identity(
            construction_inputs.epoch_reader
        )
        self._clock_instance_identity = _instance_identity(
            construction_inputs.clock
        )
        self._clock_identity = hashlib.sha256(
            _canonical_json(
                {
                    "source": _source_identity(type(construction_inputs.clock))[3],
                    "instance": self._clock_instance_identity,
                    "type": type(construction_inputs.clock).__qualname__,
                }
            )
        ).hexdigest()
        self._store_scope_fingerprint = hashlib.sha256(
            _canonical_json(
                {
                    **binding.payload(),
                    "principal_id": construction_inputs.principal_id,
                    "capture_callback_identity": self._callback_identity,
                    "source_identity": _instance_identity(source),
                }
            )
        ).hexdigest()
        self._batch_factory = batch_factory
        self._batch_attestation = batch_attestation
        self._lock = threading.RLock()
        self._read_lock = threading.RLock()
        self._cursors: dict[str, _CursorRecordV3] = {}
        self._counter = 0
        self._journey = 0
        for name in ("open_page", "continue_page"):
            _callable_member(projection, name)
        if not callable(batch_factory):
            raise Phase5ComponentAdapterV3ContractError(
                "inbox batch factory required"
            )
        for value, attestation, role in (
            (projection, projection_attestation, "inbox"),
            (batch_factory, batch_attestation, "batch_factory"),
        ):
            authority.verify_component(
                value,
                attestation,
                role=role,
                generation=0,
            )
        self._verify_construction(0)

    def _verify_construction(self, generation: int) -> None:
        projection_identity = _instance_identity(self._projection)
        source_identity = _instance_identity(self._source)
        if (
            type(self._projection) is not _inbox_v15.ApprovalInboxProjectionV15
            or type(self._source) is not _inbox_v15.HostInboxSourceV15
            or self._projection._source is not self._source
            or self._source.session_id != self._guard.binding.session_id
            or self._source.principal_id != self._inputs.principal_id
            or getattr(self._source._capture_callback, "__self__", None)
            is not self._sidecar
            or getattr(self._source._capture_callback, "__func__", None)
            is not _ScopedInboxCaptureV3.capture
        ):
            raise Phase5ComponentAdapterV3Error(
                "inbox scoped construction identity changed"
            )
        if (
            _instance_identity(self._inputs.capture_callback)
            != self._callback_instance_identity
            or _instance_identity(self._inputs.epoch_reader)
            != self._epoch_instance_identity
            or _instance_identity(self._inputs.clock)
            != self._clock_instance_identity
        ):
            raise Phase5ComponentAdapterV3Error(
                "inbox construction input identity changed"
            )
        self._authority.verify_construction(
            self._construction_receipt,
            binding=self._guard.binding,
            principal_id=self._inputs.principal_id,
            projection_identity=projection_identity,
            source_identity=source_identity,
            capture_callback_identity=self._callback_identity,
            epoch_reader_identity=self._epoch_identity,
            clock_identity=self._clock_identity,
            store_scope_fingerprint=self._store_scope_fingerprint,
            generation=generation,
        )

    def factory(self, runtime_binding: object) -> "ApprovalInboxAdapterV3":
        self._guard.validate_runtime(runtime_binding)
        token = self._lifecycle.begin(self._projection)
        self._authority.verify_component(
            self._projection,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
        self._verify_construction(token.generation)
        self._lifecycle.finish(token, self._projection)
        return self

    @staticmethod
    def _created_at(milliseconds: object) -> str:
        value = _exact_int(milliseconds, "created_at_ms", 0, 2**63 - 1)
        try:
            return (
                datetime.fromtimestamp(value / 1000, UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError) as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "created_at_ms outside supported range"
            ) from exc

    @classmethod
    def _item(cls, value: object, binding: AdapterBindingV3) -> dict[str, object]:
        try:
            if value.workspace_id != binding.workspace_id:
                raise Phase5ComponentAdapterV3ContractError(
                    "inbox item workspace mismatch"
                )
            for name in (
                "authority_granted",
                "approval_action_available",
                "execution_available",
            ):
                if type(getattr(value, name)) is not bool or getattr(value, name):
                    raise Phase5ComponentAdapterV3ContractError(
                        "inbox item conveyed authority"
                    )
            action_display = _text(value.action_display, "action_display", 128)
            if "." not in action_display:
                raise Phase5ComponentAdapterV3ContractError(
                    "inbox action display has no operation"
                )
            operation = _safe_id(action_display.rsplit(".", 1)[1], "operation")
            risk = _text(value.risk, "risk", 16)
            if risk not in _RISKS:
                raise Phase5ComponentAdapterV3ContractError("inbox risk invalid")
            return {
                "item_id": _safe_id(value.item_id, "item_id"),
                "request_ref": _safe_id(
                    value.action_request_id, "action_request_id"
                ),
                "capability": _text(
                    value.connector_display, "connector_display", 128
                ),
                "operation": operation,
                "risk": risk,
                "state": "pending",
                "summary": _text(value.reason, "reason", 512),
                "created_at": cls._created_at(value.created_at_ms),
            }
        except AttributeError as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "inbox item incomplete"
            ) from exc

    def _host_envelope(
        self,
        *,
        phase: str,
        request_digest: str,
        page_digest: str | None,
        scope_receipt: InboxSnapshotScopeReceiptV3 | None,
        journey: int,
        sequence: int,
        generation: int,
        journey_complete: bool,
    ) -> InboxPageEnvelopeV3:
        projection_identity = _instance_identity(self._projection)
        source_identity = _instance_identity(self._source)
        construction_digest = _receipt_digest(self._construction_receipt)
        scope_digest = (
            None if scope_receipt is None else _receipt_digest(scope_receipt)
        )
        envelope = self._authority.issue_page_envelope(
            phase=phase,
            binding=self._guard.binding,
            projection_identity=projection_identity,
            source_identity=source_identity,
            construction_digest=construction_digest,
            snapshot_scope_receipt_digest=scope_digest,
            journey=journey,
            sequence=sequence,
            generation=generation,
            request_digest=request_digest,
            page_digest=page_digest,
        )
        self._authority.verify_page_envelope(
            envelope,
            binding=self._guard.binding,
            projection_identity=projection_identity,
            source_identity=source_identity,
            construction_digest=construction_digest,
            snapshot_scope_receipt_digest=scope_digest,
            journey=journey,
            sequence=sequence,
            generation=generation,
            request_digest=request_digest,
            page_digest=page_digest,
            journey_complete=journey_complete,
        )
        return envelope

    def _verify_scope_receipt(
        self, receipt: InboxSnapshotScopeReceiptV3, generation: int
    ) -> None:
        self._authority.verify_snapshot_scope(
            receipt,
            **self._guard.binding.payload(),
            projection_identity=_instance_identity(self._projection),
            source_identity=_instance_identity(self._source),
            construction_digest=_receipt_digest(self._construction_receipt),
            capture_sequence=receipt.capture_sequence,
            source_epoch=receipt.source_epoch,
            item_count=receipt.item_count,
            snapshot_digest=receipt.snapshot_digest,
            snapshot_scope_fingerprint=receipt.snapshot_scope_fingerprint,
            generation=generation,
        )

    def read_page(
        self, *, binding: object, page_size: int, cursor: str | None
    ) -> object:
        with self._read_lock:
            try:
                return self._read_page_locked(
                    binding=binding, page_size=page_size, cursor=cursor
                )
            except BaseException:
                self._authority.abort_journey(
                    _instance_identity(self._projection),
                    generation=self._lifecycle.generation,
                )
                with self._lock:
                    self._cursors.clear()
                raise

    def _read_page_locked(
        self, *, binding: object, page_size: int, cursor: str | None
    ) -> object:
        self._guard.validate_runtime(binding)
        page_size = _exact_int(page_size, "page_size", 1, MAX_PAGE_SIZE_V3)
        if cursor is not None:
            cursor = _safe_id(cursor, "cursor")
        with self._lock:
            if cursor is None:
                if self._journey >= MAX_SEQUENCE_V3:
                    raise Phase5ComponentAdapterV3Error(
                        "inbox journey sequence exhausted"
                    )
                if self._cursors:
                    self._authority.abort_journey(
                        _instance_identity(self._projection),
                        generation=self._lifecycle.generation,
                    )
                self._journey += 1
                self._cursors.clear()
                source: _CursorRecordV3 | None = None
                journey = self._journey
                sequence = 0
            else:
                source = self._cursors.pop(cursor, None)
                if source is None:
                    raise Phase5ComponentAdapterV3Error(
                        "inbox continuation cursor unavailable"
                    )
                if source.page_size != page_size:
                    raise Phase5ComponentAdapterV3ContractError(
                        "inbox continuation page_size drift"
                    )
                journey = source.journey
                sequence = source.sequence
        self._guard.attest()
        component = self._projection
        token = self._lifecycle.begin(component)
        self._authority.verify_component(
            component,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
        self._verify_construction(token.generation)
        actual_cursor = None if source is None else source.source_cursor
        request = _request_digest(
            self._guard.binding,
            component_identity=token.component_identity,
            source_identity=_instance_identity(self._source),
            construction_digest=_receipt_digest(self._construction_receipt),
            generation=token.generation,
            journey=journey,
            sequence=sequence,
            page_size=page_size,
            cursor=actual_cursor,
        )
        self._host_envelope(
            phase="pre",
            request_digest=request,
            page_digest=None,
            scope_receipt=None,
            journey=journey,
            sequence=sequence,
            generation=token.generation,
            journey_complete=False,
        )
        try:
            if source is None:
                expected_capture = self._sidecar.prepare_capture()
                page = _callable_member(component, "open_page")(page_size=page_size)
                scope_receipt = self._sidecar.consume_capture(expected_capture)
            else:
                page = _callable_member(component, "continue_page")(
                    source.source_cursor
                )
                scope_receipt = source.scope_receipt
        except BaseException as exc:
            raise Phase5ComponentAdapterV3Error("approval inbox read failed") from exc
        current = self._projection
        self._authority.verify_component(
            current,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
        self._verify_construction(token.generation)
        self._lifecycle.finish(token, current)
        try:
            if _enum_value(page.state, "inbox state") != "READY":
                raise Phase5ComponentAdapterV3Error("approval inbox not ready")
            for name in (
                "authority_granted",
                "approval_action_available",
                "execution_available",
            ):
                if type(getattr(page, name)) is not bool or getattr(page, name):
                    raise Phase5ComponentAdapterV3ContractError(
                        "inbox page conveyed authority"
                    )
            items = page.items
            if type(items) is not tuple or len(items) > page_size:
                raise Phase5ComponentAdapterV3ContractError(
                    "inbox page cardinality invalid"
                )
            total = _exact_int(page.total_items, "total_items", 0, MAX_ITEMS_V3)
            offset = _exact_int(page.offset, "offset", 0, total)
            if offset + len(items) > total:
                raise Phase5ComponentAdapterV3ContractError("inbox bounds invalid")
            snapshot_id = _digest(page.snapshot_id, "snapshot_id")
            view_digest = _digest(page.view_digest, "view_digest")
            actual_next = page.next_cursor
            if actual_next is not None and (
                type(actual_next) is not str or not actual_next
            ):
                raise Phase5ComponentAdapterV3ContractError(
                    "inbox next cursor invalid"
                )
            if not items and actual_next is not None:
                raise Phase5ComponentAdapterV3ContractError(
                    "empty inbox page cannot continue"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV3ContractError(
                "approval inbox page incomplete"
            ) from exc
        if source is None:
            if offset != 0:
                raise Phase5ComponentAdapterV3ContractError(
                    "first inbox offset not zero"
                )
        elif (
            offset != source.expected_offset
            or total != source.total_items
            or snapshot_id != source.snapshot_id
            or view_digest != source.view_digest
        ):
            raise Phase5ComponentAdapterV3ContractError(
                "inbox continuation relation drift"
            )
        self._verify_scope_receipt(scope_receipt, token.generation)
        exact_page_digest = _page_digest(page)
        self._host_envelope(
            phase="post",
            request_digest=request,
            page_digest=exact_page_digest,
            scope_receipt=scope_receipt,
            journey=journey,
            sequence=sequence,
            generation=token.generation,
            journey_complete=actual_next is None,
        )
        self._lifecycle.finish(token, self._projection)
        self._guard.attest()
        projected = tuple(self._item(item, self._guard.binding) for item in items)
        next_cursor: str | None = None
        if actual_next is not None:
            with self._lock:
                self._lifecycle.finish(token, self._projection)
                if len(self._cursors) >= MAX_ITEMS_V3:
                    raise Phase5ComponentAdapterV3Error(
                        "inbox cursor capacity exhausted"
                    )
                if self._counter >= MAX_SEQUENCE_V3:
                    raise Phase5ComponentAdapterV3Error(
                        "inbox cursor sequence exhausted"
                    )
                self._counter += 1
                next_cursor = f"ibx3-{token.generation}-{journey}-{sequence + 1}-{self._counter}"
                if len(next_cursor.encode()) > MAX_CURSOR_BYTES_V3:
                    raise Phase5ComponentAdapterV3ContractError(
                        "short cursor invalid"
                    )
                self._cursors[next_cursor] = _CursorRecordV3(
                    token.generation,
                    actual_next,
                    page_size,
                    offset + len(items),
                    total,
                    snapshot_id,
                    view_digest,
                    journey,
                    sequence + 1,
                    scope_receipt,
                )
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        result = _make_batch_v3(
            self._batch_factory,
            projected,
            replace=cursor is None,
            source_cursor=cursor,
            next_cursor=next_cursor,
        )
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        self._lifecycle.finish(token, self._projection)
        return result

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV3ContractError("terminal reason invalid")
        generation = self._lifecycle.generation
        if self._lifecycle.close():
            projection_identity = _instance_identity(self._projection)
            self._authority.abort_journey(
                projection_identity, generation=generation
            )
            self._authority.release_owner(
                projection_identity, generation=generation
            )
            with self._lock:
                self._cursors.clear()


def _make_batch_v3(
    factory: RuntimeBatchFactoryV3,
    items: tuple[Mapping[str, object], ...],
    *,
    replace: bool,
    source_cursor: str | None,
    next_cursor: str | None,
) -> object:
    try:
        result = factory(
            items,
            replace=replace,
            source_cursor=source_cursor,
            next_cursor=next_cursor,
        )
    except BaseException as exc:
        raise Phase5ComponentAdapterV3Error("runtime batch construction failed") from exc
    try:
        if (
            result.items != items
            or result.replace is not replace
            or result.source_cursor != source_cursor
            or result.next_cursor != next_cursor
        ):
            raise Phase5ComponentAdapterV3ContractError(
                "runtime batch factory changed projection"
            )
    except AttributeError as exc:
        raise Phase5ComponentAdapterV3ContractError(
            "runtime batch factory incompatible"
        ) from exc
    return result


@dataclass(frozen=True, slots=True)
class ComponentAdapterBundleV3:
    runtime_components: object
    grant: GrantShadowAdapterV3 | None
    nexus: CapabilityNexusAdapterV3 | None
    inbox: ApprovalInboxAdapterV3 | None


def build_component_adapters_v3(
    *,
    flags: AdapterFlagsV3,
    acceptance: AcceptedComponentsV3,
    binding: object,
    binding_attestor: Callable[[], object],
    authority: HostAttestationAuthorityV3,
    attestations: Mapping[str, ComponentAttestationV3],
    batch_factory: RuntimeBatchFactoryV3,
    components_factory: RuntimeComponentsFactoryV3,
    action_request_type: type | None = None,
    grant_store: object | None = None,
    materialize_grant_request: Callable[[str], object] | None = None,
    nexus: object | None = None,
    inbox_construction: InboxConstructionInputsV3 | None = None,
) -> ComponentAdapterBundleV3:
    if type(flags) is not AdapterFlagsV3 or type(acceptance) is not AcceptedComponentsV3:
        raise Phase5ComponentAdapterV3ContractError(
            "exact flags and acceptance declarations required"
        )
    if type(authority) is not HostAttestationAuthorityV3:
        raise Phase5ComponentAdapterV3ContractError(
            "exact host attestation authority required"
        )
    if type(attestations) not in {dict, MappingProxyType}:
        raise Phase5ComponentAdapterV3ContractError("exact attestation mapping required")
    normalized_binding = AdapterBindingV3.from_runtime(binding)
    supplied = {
        "grant_shadow": grant_store is not None or materialize_grant_request is not None,
        "nexus_projection": nexus is not None,
        "approval_inbox": inbox_construction is not None,
    }
    for name, present in supplied.items():
        if present and not getattr(flags, name):
            raise Phase5ComponentAdapterV3ContractError(
                f"{name} supplied while flag off"
            )
    if not flags.adapters:
        if attestations:
            raise Phase5ComponentAdapterV3ContractError(
                "disabled adapters reject attestations"
            )
        return ComponentAdapterBundleV3(components_factory(), None, None, None)
    if "inbox" in attestations or "inbox_projection_attestor" in attestations:
        raise Phase5ComponentAdapterV3ContractError(
            "V3 rejects caller-supplied inbox projection attestations"
        )

    try:
        batch_attestation = attestations["batch_factory"]
        components_attestation = attestations["components_factory"]
    except KeyError as exc:
        raise Phase5ComponentAdapterV3ContractError(
            "runtime factory attestations required"
        ) from exc
    authority.verify_component(
        batch_factory, batch_attestation, role="batch_factory", generation=0
    )
    authority.verify_component(
        components_factory,
        components_attestation,
        role="components_factory",
        generation=0,
    )
    grant_adapter: GrantShadowAdapterV3 | None = None
    nexus_adapter: CapabilityNexusAdapterV3 | None = None
    inbox_adapter: ApprovalInboxAdapterV3 | None = None
    runtime_args: dict[str, object] = {}
    if flags.grant_shadow:
        acceptance.require("grants")
        if (
            grant_store is None
            or materialize_grant_request is None
            or action_request_type is None
        ):
            raise Phase5ComponentAdapterV3ContractError(
                "grant dependencies incomplete"
            )
        grant_adapter = GrantShadowAdapterV3(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            authority=authority,
            store=grant_store,
            store_attestation=attestations.get("grant_store"),  # type: ignore[arg-type]
            materialize_request=materialize_grant_request,
            materializer_attestation=attestations.get("grant_materializer"),  # type: ignore[arg-type]
            action_request_type=action_request_type,
            action_request_type_attestation=attestations.get(
                "action_request_type"
            ),  # type: ignore[arg-type]
        )
        runtime_args.update(
            grant_evaluator=grant_adapter.evaluate,
            grant_terminator=grant_adapter.close,
        )
    if flags.nexus_projection:
        acceptance.require("nexus")
        if nexus is None:
            raise Phase5ComponentAdapterV3ContractError("nexus dependency missing")
        nexus_adapter = CapabilityNexusAdapterV3(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            authority=authority,
            nexus=nexus,
            nexus_attestation=attestations.get("nexus"),  # type: ignore[arg-type]
            batch_factory=batch_factory,
            batch_attestation=batch_attestation,
        )
        runtime_args.update(
            nexus_projector=nexus_adapter.project,
            nexus_terminator=nexus_adapter.close,
        )
    if flags.approval_inbox:
        acceptance.require("inbox")
        if type(inbox_construction) is not InboxConstructionInputsV3:
            raise Phase5ComponentAdapterV3ContractError(
                "exact inbox construction inputs required"
            )
        projection, source, sidecar, projection_attestation, receipt = (
            _construct_inbox_v3(
                binding=normalized_binding,
                authority=authority,
                inputs=inbox_construction,
                generation=0,
            )
        )
        try:
            inbox_adapter = ApprovalInboxAdapterV3(
                binding=normalized_binding,
                binding_attestor=binding_attestor,
                authority=authority,
                projection=projection,
                source=source,
                sidecar=sidecar,
                projection_attestation=projection_attestation,
                construction_receipt=receipt,
                construction_inputs=inbox_construction,
                batch_factory=batch_factory,
                batch_attestation=batch_attestation,
            )
        except BaseException:
            authority.release_owner(_instance_identity(projection), generation=0)
            raise
        runtime_args.update(
            inbox_factory=inbox_adapter.factory,
            inbox_terminator=inbox_adapter.close,
        )
    try:
        components = components_factory(**runtime_args)
        authority.verify_component(
            components_factory,
            components_attestation,
            role="components_factory",
            generation=0,
        )
        for name, expected in runtime_args.items():
            if getattr(components, name, None) != expected:
                raise Phase5ComponentAdapterV3ContractError(
                    f"components factory changed {name}"
                )
    except BaseException:
        if inbox_adapter is not None:
            inbox_adapter.close("rollback")
        raise
    return ComponentAdapterBundleV3(
        components, grant_adapter, nexus_adapter, inbox_adapter
    )


__all__ = [
    "ADAPTER_CONTRACT_V3",
    "GRANTS_ACCEPTANCE_V3",
    "NEXUS_ACCEPTANCE_V3",
    "INBOX_ACCEPTANCE_V3",
    "AdapterBindingV3",
    "AdapterFlagsV3",
    "AcceptedComponentsV3",
    "ComponentAttestationV3",
    "InboxConstructionReceiptV3",
    "InboxSnapshotScopeReceiptV3",
    "InboxPageEnvelopeV3",
    "InboxConstructionInputsV3",
    "HostAttestationAuthorityV3",
    "ApprovalInboxAdapterV3",
    "CapabilityNexusAdapterV3",
    "ComponentAdapterBundleV3",
    "GrantShadowAdapterV3",
    "Phase5ComponentAdapterV3ContractError",
    "Phase5ComponentAdapterV3Error",
    "build_component_adapters_v3",
]
