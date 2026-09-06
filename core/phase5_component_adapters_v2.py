"""Attested, lifecycle-safe adapters for accepted Phase 5 candidates.

This isolated candidate is default-off and is not imported by any live surface.
It projects accepted component output only; it cannot approve, grant authority,
dispatch, execute, persist, poll, or create threads.

Unlike V1, every dependency is bound to a host-held HMAC attestation covering
its canonical source, exact Python identity, accepted root, instance identity,
and adapter generation.  Approval Inbox pages additionally require host-issued
pre/post attestations covering all five runtime binding dimensions and the exact
request/page bytes.  Missing attestations fail closed.
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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol


ADAPTER_CONTRACT_V2 = "onyx.phase5-component-adapters.v2"
GRANTS_ACCEPTANCE_V2 = "VE-P51-GRANTS-R11-E6-001"
NEXUS_ACCEPTANCE_V2 = "VE-P53-CAPABILITY-NEXUS-V32-E6-001"
INBOX_ACCEPTANCE_V2 = "VE-P52-APPROVAL-INBOX-V15-E6-001"

GRANTS_ROOT_V2 = "b4759d8840611e2affbd322831ae8dc88ff84ac09701a24b4a6f56df66463071"
NEXUS_ROOT_V2 = "86cc174fb212f51c56b59cb9043c8cb59e765307eea2c32a7a44857f6112bfa3"
INBOX_ROOT_V2 = "279052fbcaf3018f7fee6733e063e94c67e90e7ce62a2a2cdc7742b55470631f"
HOST_ROOT_V2 = hashlib.sha256(b"onyx.phase5.host.integration.v2").hexdigest()

MAX_ITEMS_V2 = 128
MAX_PAGE_SIZE_V2 = 50
MAX_CURSOR_BYTES_V2 = 128
MAX_ADVISORY_BYTES_V2 = 512
MAX_SEQUENCE_V2 = 9_999_999

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
        "inbox_projection_attestor": ("__call__",),
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
            GRANTS_ROOT_V2,
            "core.session_" + "grants_v11",
            "SessionGrantShadowStore",
            "core/session_" + "grants_v11.py",
            "r11",
            "0f4ad25b72a9c64064dfc946afab6d2515edff1f91171d46d54e36e38c6cd159",
        ),
        "nexus": (
            NEXUS_ROOT_V2,
            "core.capability_" + "nexus_v32",
            "CapabilityNexusV32",
            "core/capability_" + "nexus_v32.py",
            "v32",
            "576eed0bda063945d33f8bcb79b338e64976ca5252af793633fe3ab667ed1fc9",
        ),
        "inbox": (
            INBOX_ROOT_V2,
            "core.approval_" + "inbox_v15",
            "ApprovalInboxProjectionV15",
            "core/approval_" + "inbox_v15.py",
            "v15",
            "f9627e6b9e840dbca8e098a047e56da4647d24ef80f201c5585a41d405d52061",
        ),
    }
)


class Phase5ComponentAdapterV2Error(RuntimeError):
    """A dependency or lifecycle check could not safely complete."""


class Phase5ComponentAdapterV2ContractError(ValueError):
    """An exact V2 input or attestation contract was violated."""


class RuntimeBatchFactoryV2(Protocol):
    def __call__(
        self,
        items: tuple[Mapping[str, object], ...],
        *,
        replace: bool,
        source_cursor: str | None,
        next_cursor: str | None,
    ) -> object: ...


class RuntimeComponentsFactoryV2(Protocol):
    def __call__(self, **components: object) -> object: ...


def _exact_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise Phase5ComponentAdapterV2ContractError(f"{label} must be exact bool")
    return value


def _safe_id(value: object, label: str) -> str:
    if type(value) is not str or not _SAFE_ID.fullmatch(value):
        raise Phase5ComponentAdapterV2ContractError(f"{label} is invalid")
    return value


def _text(value: object, label: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise Phase5ComponentAdapterV2ContractError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _HEX64.fullmatch(value):
        raise Phase5ComponentAdapterV2ContractError(f"{label} is invalid")
    return value


def _exact_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise Phase5ComponentAdapterV2ContractError(f"{label} is invalid")
    return value


def _enum_value(value: object, label: str) -> str:
    raw = getattr(value, "value", value)
    return _text(raw, label, 64)


def _callable_member(value: object, name: str) -> Callable[..., object]:
    member = getattr(value, name, None)
    if not callable(member):
        raise Phase5ComponentAdapterV2ContractError(
            f"component lacks callable {name}"
        )
    return member


def _canonical_json(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise Phase5ComponentAdapterV2ContractError(
            "attestation payload is not canonical JSON"
        ) from exc


def _source_identity(value: object) -> tuple[str, str, str, str, int]:
    target = value if inspect.isclass(value) else type(value)
    if inspect.isfunction(value) or inspect.ismethod(value):
        target = value.__func__ if inspect.ismethod(value) else value
    module_name = getattr(target, "__module__", None)
    qualname = getattr(target, "__qualname__", None)
    if type(module_name) is not str or type(qualname) is not str:
        raise Phase5ComponentAdapterV2ContractError(
            "component has no exact Python identity"
        )
    try:
        raw_path = inspect.getsourcefile(target) or inspect.getfile(target)
    except (TypeError, OSError) as exc:
        raise Phase5ComponentAdapterV2ContractError(
            "component source is unavailable"
        ) from exc
    if type(raw_path) is not str:
        raise Phase5ComponentAdapterV2ContractError(
            "component source is unavailable"
        )
    lexical = Path(raw_path).absolute()
    try:
        before = os.lstat(lexical)
        canonical = lexical.resolve(strict=True)
        after = os.stat(canonical, follow_symlinks=False)
    except (OSError, RuntimeError) as exc:
        raise Phase5ComponentAdapterV2Error("component source check failed") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or lexical != canonical
    ):
        raise Phase5ComponentAdapterV2ContractError(
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
        raise Phase5ComponentAdapterV2Error("component source read failed") from exc
    identity_after = (
        final.st_dev,
        final.st_ino,
        final.st_size,
        final.st_mtime_ns,
        final.st_ctime_ns,
    )
    if identity_before != identity_after or len(content) != final.st_size:
        raise Phase5ComponentAdapterV2Error("component source changed during read")
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


def _interface_digest(value: object, role: str) -> str:
    payload: list[dict[str, object]] = []
    for name in _ROLE_METHODS.get(role, ()):
        member = getattr(value, name, None)
        if not callable(member):
            raise Phase5ComponentAdapterV2ContractError(
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
class AdapterFlagsV2:
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
            raise Phase5ComponentAdapterV2ContractError(
                "component flags require adapter master flag"
            )


@dataclass(frozen=True, slots=True)
class AcceptedComponentsV2:
    grants: str | None = None
    nexus: str | None = None
    inbox: str | None = None

    def require(self, name: str) -> None:
        expected = {
            "grants": GRANTS_ACCEPTANCE_V2,
            "nexus": NEXUS_ACCEPTANCE_V2,
            "inbox": INBOX_ACCEPTANCE_V2,
        }[name]
        if getattr(self, name) != expected:
            raise Phase5ComponentAdapterV2ContractError(
                f"{name} lacks exact external acceptance"
            )


@dataclass(frozen=True, slots=True)
class AdapterBindingV2:
    trace_id: str
    session_id: str
    workspace_id: str
    account_id: str
    profile_id: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _safe_id(getattr(self, name), name))

    @classmethod
    def from_runtime(cls, value: object) -> "AdapterBindingV2":
        try:
            return cls(
                getattr(value, "trace_id"),
                getattr(value, "session_id"),
                getattr(value, "workspace_id"),
                getattr(value, "account_id"),
                getattr(value, "profile_id"),
            )
        except (AttributeError, TypeError) as exc:
            raise Phase5ComponentAdapterV2ContractError(
                "runtime binding is malformed"
            ) from exc

    def payload(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class ComponentAttestationV2:
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
class ProjectionAttestationV2:
    phase: str
    request_digest: str
    page_digest: str | None
    component_identity: str
    generation: int
    nonce: str
    mac: str


class HostAttestationAuthorityV2:
    """Process-local signing root. Key bytes are copied and never exposed."""

    __slots__ = ("__key", "_lock", "_seen")

    def __init__(self, key: bytes) -> None:
        if type(key) is not bytes or len(key) < 32:
            raise Phase5ComponentAdapterV2ContractError(
                "host attestation key must be at least 32 exact bytes"
            )
        self.__key = bytes(key)
        self._lock = threading.RLock()
        self._seen: set[str] = set()

    def _mac(self, domain: str, payload: Mapping[str, object]) -> str:
        return hmac.new(
            self.__key,
            domain.encode() + b"\0" + _canonical_json(payload),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _root_for(role: str) -> str:
        accepted = _ACCEPTED.get(role)
        return HOST_ROOT_V2 if accepted is None else accepted[0]

    def issue_component(
        self,
        value: object,
        *,
        role: str,
        generation: int,
        binding: AdapterBindingV2 | None = None,
    ) -> ComponentAttestationV2:
        role = _safe_id(role, "role")
        generation = _exact_int(generation, "generation", 0, MAX_SEQUENCE_V2)
        module, qualname, path, digest, size = _source_identity(value)
        accepted = _ACCEPTED.get(role)
        if role == "inbox_projection_attestor":
            if type(binding) is not AdapterBindingV2:
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox projection attestor requires exact 5D binding"
                )
            binding_digest: str | None = hashlib.sha256(
                _canonical_json(binding.payload())
            ).hexdigest()
        elif binding is not None:
            raise Phase5ComponentAdapterV2ContractError(
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
                raise Phase5ComponentAdapterV2ContractError(
                    f"{role} is not the exact accepted public component"
                )
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            "role": role,
            "accepted_root": self._root_for(role),
            "component_version": (
                ADAPTER_CONTRACT_V2 if accepted is None else accepted[4]
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
        return ComponentAttestationV2(**payload, mac=self._mac("component-v2", payload))

    def verify_component(
        self,
        value: object,
        attestation: ComponentAttestationV2,
        *,
        role: str,
        generation: int,
        binding: AdapterBindingV2 | None = None,
    ) -> None:
        if type(attestation) is not ComponentAttestationV2:
            raise Phase5ComponentAdapterV2ContractError(
                "exact component attestation required"
            )
        module, qualname, path, digest, size = _source_identity(value)
        if role == "inbox_projection_attestor":
            if type(binding) is not AdapterBindingV2:
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox projection attestor requires exact 5D binding"
                )
            binding_digest: str | None = hashlib.sha256(
                _canonical_json(binding.payload())
            ).hexdigest()
        elif binding is not None:
            raise Phase5ComponentAdapterV2ContractError(
                "unexpected component binding"
            )
        else:
            binding_digest = None
        expected = {
            "role": _safe_id(role, "role"),
            "accepted_root": self._root_for(role),
            "component_version": (
                ADAPTER_CONTRACT_V2
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
                generation, "generation", 0, MAX_SEQUENCE_V2
            ),
            "binding_digest": binding_digest,
            "nonce": _text(attestation.nonce, "nonce", 64),
        }
        actual = {name: getattr(attestation, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            attestation.mac, self._mac("component-v2", expected)
        ):
            raise Phase5ComponentAdapterV2Error(
                f"{role} component attestation mismatch"
            )

    def issue_projection(
        self,
        *,
        phase: str,
        request_digest: str,
        page_digest: str | None,
        component_identity: str,
        generation: int,
    ) -> ProjectionAttestationV2:
        phase = _text(phase, "phase", 8)
        if phase not in {"pre", "post"}:
            raise Phase5ComponentAdapterV2ContractError("projection phase invalid")
        request_digest = _digest(request_digest, "request_digest")
        if page_digest is not None:
            page_digest = _digest(page_digest, "page_digest")
        if (phase == "pre") != (page_digest is None):
            raise Phase5ComponentAdapterV2ContractError(
                "projection phase/page digest mismatch"
            )
        nonce = secrets.token_hex(16)
        payload: dict[str, object] = {
            "phase": phase,
            "request_digest": request_digest,
            "page_digest": page_digest,
            "component_identity": _digest(
                component_identity, "component_identity"
            ),
            "generation": _exact_int(
                generation, "generation", 0, MAX_SEQUENCE_V2
            ),
            "nonce": nonce,
        }
        return ProjectionAttestationV2(
            **payload, mac=self._mac("projection-v2", payload)
        )

    def verify_projection(
        self,
        value: ProjectionAttestationV2,
        *,
        phase: str,
        request_digest: str,
        page_digest: str | None,
        component_identity: str,
        generation: int,
    ) -> None:
        if type(value) is not ProjectionAttestationV2:
            raise Phase5ComponentAdapterV2ContractError(
                "exact projection attestation required"
            )
        expected = {
            "phase": phase,
            "request_digest": request_digest,
            "page_digest": page_digest,
            "component_identity": component_identity,
            "generation": generation,
            "nonce": value.nonce,
        }
        actual = {name: getattr(value, name) for name in expected}
        if actual != expected or not hmac.compare_digest(
            value.mac, self._mac("projection-v2", expected)
        ):
            raise Phase5ComponentAdapterV2Error("projection attestation mismatch")
        replay_key = f"{phase}:{value.nonce}:{value.mac}"
        with self._lock:
            if replay_key in self._seen:
                raise Phase5ComponentAdapterV2Error(
                    "projection attestation replayed"
                )
            if len(self._seen) >= MAX_ITEMS_V2 * 4:
                raise Phase5ComponentAdapterV2Error(
                    "projection attestation capacity exhausted"
                )
            self._seen.add(replay_key)


class _BindingGuardV2:
    __slots__ = ("_attestor", "binding")

    def __init__(self, binding: AdapterBindingV2, attestor: Callable[[], object]) -> None:
        if not callable(attestor):
            raise Phase5ComponentAdapterV2ContractError(
                "binding_attestor is required"
            )
        self.binding = binding
        self._attestor = attestor

    def validate_runtime(self, value: object) -> None:
        if AdapterBindingV2.from_runtime(value) != self.binding:
            raise Phase5ComponentAdapterV2ContractError("runtime binding mismatch")

    def attest(self) -> None:
        try:
            current = self._attestor()
        except BaseException as exc:
            raise Phase5ComponentAdapterV2Error("binding attestation failed") from exc
        if AdapterBindingV2.from_runtime(current) != self.binding:
            raise Phase5ComponentAdapterV2Error("binding attestation mismatch")


@dataclass(frozen=True, slots=True)
class _CallTokenV2:
    generation: int
    component_identity: str


class _LifecycleV2:
    __slots__ = ("_closed", "_generation", "_lock")

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._closed = False
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin(self, component: object) -> _CallTokenV2:
        with self._lock:
            if self._closed:
                raise Phase5ComponentAdapterV2Error("adapter is closed")
            return _CallTokenV2(self._generation, _instance_identity(component))

    def finish(self, token: _CallTokenV2, component: object) -> None:
        with self._lock:
            if (
                self._closed
                or token.generation != self._generation
                or token.component_identity != _instance_identity(component)
            ):
                raise Phase5ComponentAdapterV2Error(
                    "adapter lifecycle changed during component call"
                )

    def close(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            self._closed = True
            self._generation += 1
            return True

    def invalidate(self, component: object) -> _CallTokenV2 | None:
        with self._lock:
            if self._closed:
                return None
            token = _CallTokenV2(
                self._generation, _instance_identity(component)
            )
            self._closed = True
            self._generation += 1
            return token


def _attested_call(
    *,
    lifecycle: _LifecycleV2,
    authority: HostAttestationAuthorityV2,
    component_getter: Callable[[], object],
    attestation: ComponentAttestationV2,
    role: str,
    callback: Callable[[object], object],
    binding: AdapterBindingV2 | None = None,
) -> tuple[object, _CallTokenV2]:
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
        raise Phase5ComponentAdapterV2Error(f"{role} call failed") from exc
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


_ACTION_FIELDS_V2 = (
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
    binding: AdapterBindingV2,
) -> tuple[object, ...]:
    if type(request) is not expected_type:
        raise Phase5ComponentAdapterV2ContractError(
            "materializer returned wrong exact ActionRequest type"
        )
    params = getattr(expected_type, "__dataclass_params__", None)
    if params is None or not params.frozen:
        raise Phase5ComponentAdapterV2ContractError(
            "ActionRequest type must be frozen"
        )
    try:
        values = tuple(getattr(request, name) for name in _ACTION_FIELDS_V2)
    except AttributeError as exc:
        raise Phase5ComponentAdapterV2ContractError(
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
        and AdapterBindingV2.from_runtime(request_binding) == binding
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
        raise Phase5ComponentAdapterV2ContractError(
            "ActionRequest is not the exact local catalog action"
        )
    return values


class GrantShadowAdapterV2:
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
        binding: AdapterBindingV2,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV2,
        store: object,
        store_attestation: ComponentAttestationV2,
        materialize_request: Callable[[str], object],
        materializer_attestation: ComponentAttestationV2,
        action_request_type: type,
        action_request_type_attestation: ComponentAttestationV2,
    ) -> None:
        self._guard = _BindingGuardV2(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV2()
        self._store = store
        self._store_attestation = store_attestation
        self._materialize = materialize_request
        self._materialize_attestation = materializer_attestation
        if not callable(materialize_request) or not isinstance(action_request_type, type):
            raise Phase5ComponentAdapterV2ContractError(
                "exact grant materializer and ActionRequest type required"
            )
        self._action_type = action_request_type
        self._action_type_attestation = action_request_type_attestation
        module = inspect.getmodule(type(store))
        self._decision_type = (
            None if module is None else getattr(module, "ShadowGrantDecision", None)
        )
        if not isinstance(self._decision_type, type):
            raise Phase5ComponentAdapterV2ContractError(
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
                binding=(
                    binding if role == "inbox_projection_attestor" else None
                ),
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
        if tuple(getattr(request, name) for name in _ACTION_FIELDS_V2) != snapshot:
            raise Phase5ComponentAdapterV2Error(
                "ActionRequest changed after materialization"
            )
        if type(request) is not self._action_type:
            raise Phase5ComponentAdapterV2Error(
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
            raise Phase5ComponentAdapterV2ContractError(
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
                raise Phase5ComponentAdapterV2ContractError("grant outcome invalid")
            if (
                type(decision.authority_granted) is not bool
                or decision.authority_granted
                or type(decision.callback_required) is not bool
                or not decision.callback_required
            ):
                raise Phase5ComponentAdapterV2ContractError(
                    "grant decision conveyed authority"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV2ContractError(
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
        if len(_canonical_json(advisory)) > MAX_ADVISORY_BYTES_V2:
            raise Phase5ComponentAdapterV2ContractError("grant advisory too large")
        return advisory

    def close(self, reason: str) -> None:
        reason = _safe_id(reason, "terminal_reason")
        if reason not in _TERMINAL_REASONS:
            raise Phase5ComponentAdapterV2ContractError("terminal reason invalid")
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
            raise Phase5ComponentAdapterV2Error(
                "grant store changed during terminal callback"
            )
        if failure is not None:
            raise Phase5ComponentAdapterV2Error(
                f"grant {callback} failed after local close"
            ) from failure


class CapabilityNexusAdapterV2:
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
        binding: AdapterBindingV2,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV2,
        nexus: object,
        nexus_attestation: ComponentAttestationV2,
        batch_factory: RuntimeBatchFactoryV2,
        batch_attestation: ComponentAttestationV2,
    ) -> None:
        self._guard = _BindingGuardV2(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV2()
        self._nexus = nexus
        self._nexus_attestation = nexus_attestation
        self._batch_factory = batch_factory
        self._batch_attestation = batch_attestation
        _callable_member(nexus, "snapshot")
        if not callable(batch_factory):
            raise Phase5ComponentAdapterV2ContractError("batch_factory required")
        authority.verify_component(nexus, nexus_attestation, role="nexus", generation=0)
        authority.verify_component(
            batch_factory, batch_attestation, role="batch_factory", generation=0
        )

    @staticmethod
    def _project(entry: object, binding: AdapterBindingV2) -> dict[str, object]:
        try:
            descriptor = entry.descriptor
            if any(
                getattr(entry, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV2ContractError(
                    "nexus projection binding mismatch"
                )
            if (
                type(entry.runtime_available) is not bool
                or entry.runtime_available
                or type(entry.authority_granted) is not bool
                or entry.authority_granted
            ):
                raise Phase5ComponentAdapterV2ContractError(
                    "nexus projection conveyed authority"
                )
            if descriptor.capability_id != "local.catalog":
                raise Phase5ComponentAdapterV2ContractError(
                    "unexpected capability"
                )
            if any(
                getattr(descriptor, name) != getattr(binding, name)
                for name in ("workspace_id", "account_id", "profile_id")
            ):
                raise Phase5ComponentAdapterV2ContractError(
                    "nexus descriptor binding mismatch"
                )
            operations = descriptor.operations
            if type(operations) is not tuple or len(operations) != 1:
                raise Phase5ComponentAdapterV2ContractError(
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
                raise Phase5ComponentAdapterV2ContractError(
                    "local catalog descriptor not exact"
                )
            status_value = _NEXUS_STATUS.get(
                _enum_value(entry.projection_status, "projection_status")
            )
            if status_value is None:
                raise Phase5ComponentAdapterV2ContractError("nexus status invalid")
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
            raise Phase5ComponentAdapterV2ContractError(
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
                raise Phase5ComponentAdapterV2ContractError(
                    "nexus snapshot binding mismatch"
                )
            entries = snapshot.entries
            source_cursor = _digest(snapshot.snapshot_digest, "snapshot_digest")
        except AttributeError as exc:
            raise Phase5ComponentAdapterV2ContractError(
                "nexus snapshot incomplete"
            ) from exc
        if type(entries) is not tuple or len(entries) > MAX_ITEMS_V2:
            raise Phase5ComponentAdapterV2ContractError(
                "nexus snapshot cardinality invalid"
            )
        local = tuple(
            entry
            for entry in entries
            if getattr(getattr(entry, "descriptor", None), "capability_id", None)
            == "local.catalog"
        )
        if len(local) != 1:
            raise Phase5ComponentAdapterV2Error(
                "accepted local.catalog absent or duplicated"
            )
        item = self._project(local[0], binding)
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        result = _make_batch_v2(
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
            raise Phase5ComponentAdapterV2ContractError("terminal reason invalid")
        self._lifecycle.close()


@dataclass(frozen=True, slots=True)
class _CursorRecordV2:
    generation: int
    source_cursor: str
    page_size: int
    expected_offset: int
    total_items: int
    snapshot_id: str
    view_digest: str


def _page_payload(value: object) -> dict[str, object]:
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        raise Phase5ComponentAdapterV2ContractError(
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
        raise Phase5ComponentAdapterV2ContractError(
            "page contains non-canonical data"
        )

    converted = convert(value)
    assert type(converted) is dict
    return converted


def _page_digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(_page_payload(value))).hexdigest()


def _request_digest(
    binding: AdapterBindingV2,
    *,
    component_identity: str,
    generation: int,
    page_size: int,
    cursor: str | None,
) -> str:
    payload: dict[str, object] = {
        **binding.payload(),
        "component_identity": component_identity,
        "generation": generation,
        "page_size": page_size,
        "cursor": cursor,
    }
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


class ApprovalInboxAdapterV2:
    __slots__ = (
        "_authority",
        "_batch_attestation",
        "_batch_factory",
        "_counter",
        "_cursors",
        "_guard",
        "_inbox_attestor",
        "_inbox_attestor_attestation",
        "_journey",
        "_lifecycle",
        "_lock",
        "_projection",
        "_projection_attestation",
    )

    def __init__(
        self,
        *,
        binding: AdapterBindingV2,
        binding_attestor: Callable[[], object],
        authority: HostAttestationAuthorityV2,
        projection: object,
        projection_attestation: ComponentAttestationV2,
        projection_attestor: Callable[..., ProjectionAttestationV2],
        projection_attestor_attestation: ComponentAttestationV2,
        batch_factory: RuntimeBatchFactoryV2,
        batch_attestation: ComponentAttestationV2,
    ) -> None:
        self._guard = _BindingGuardV2(binding, binding_attestor)
        self._authority = authority
        self._lifecycle = _LifecycleV2()
        self._projection = projection
        self._projection_attestation = projection_attestation
        self._inbox_attestor = projection_attestor
        self._inbox_attestor_attestation = projection_attestor_attestation
        self._batch_factory = batch_factory
        self._batch_attestation = batch_attestation
        self._lock = threading.RLock()
        self._cursors: dict[str, _CursorRecordV2] = {}
        self._counter = 0
        self._journey = 0
        for name in ("open_page", "continue_page"):
            _callable_member(projection, name)
        if not callable(projection_attestor) or not callable(batch_factory):
            raise Phase5ComponentAdapterV2ContractError(
                "inbox host attestor and batch factory required"
            )
        for value, attestation, role in (
            (projection, projection_attestation, "inbox"),
            (
                projection_attestor,
                projection_attestor_attestation,
                "inbox_projection_attestor",
            ),
            (batch_factory, batch_attestation, "batch_factory"),
        ):
            authority.verify_component(
                value,
                attestation,
                role=role,
                generation=0,
                binding=(
                    binding if role == "inbox_projection_attestor" else None
                ),
            )

    def factory(self, runtime_binding: object) -> "ApprovalInboxAdapterV2":
        self._guard.validate_runtime(runtime_binding)
        token = self._lifecycle.begin(self._projection)
        self._authority.verify_component(
            self._projection,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
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
            raise Phase5ComponentAdapterV2ContractError(
                "created_at_ms outside supported range"
            ) from exc

    @classmethod
    def _item(cls, value: object, binding: AdapterBindingV2) -> dict[str, object]:
        try:
            if value.workspace_id != binding.workspace_id:
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox item workspace mismatch"
                )
            for name in (
                "authority_granted",
                "approval_action_available",
                "execution_available",
            ):
                if type(getattr(value, name)) is not bool or getattr(value, name):
                    raise Phase5ComponentAdapterV2ContractError(
                        "inbox item conveyed authority"
                    )
            action_display = _text(value.action_display, "action_display", 128)
            if "." not in action_display:
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox action display has no operation"
                )
            operation = _safe_id(action_display.rsplit(".", 1)[1], "operation")
            risk = _text(value.risk, "risk", 16)
            if risk not in _RISKS:
                raise Phase5ComponentAdapterV2ContractError("inbox risk invalid")
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
            raise Phase5ComponentAdapterV2ContractError(
                "inbox item incomplete"
            ) from exc

    def _host_attest(
        self,
        *,
        phase: str,
        request_digest: str,
        page_digest: str | None,
        component_identity: str,
        generation: int,
    ) -> None:
        attestation, token = _attested_call(
            lifecycle=self._lifecycle,
            authority=self._authority,
            component_getter=lambda: self._inbox_attestor,
            attestation=self._inbox_attestor_attestation,
            role="inbox_projection_attestor",
            callback=lambda callback: callback(
                phase=phase,
                request_digest=request_digest,
                page_digest=page_digest,
                component_identity=component_identity,
                generation=generation,
            ),
            binding=self._guard.binding,
        )
        self._authority.verify_projection(
            attestation,
            phase=phase,
            request_digest=request_digest,
            page_digest=page_digest,
            component_identity=component_identity,
            generation=generation,
        )
        self._lifecycle.finish(token, self._inbox_attestor)

    def read_page(
        self, *, binding: object, page_size: int, cursor: str | None
    ) -> object:
        self._guard.validate_runtime(binding)
        page_size = _exact_int(page_size, "page_size", 1, MAX_PAGE_SIZE_V2)
        if cursor is not None:
            cursor = _safe_id(cursor, "cursor")
        with self._lock:
            if cursor is None:
                if self._journey >= MAX_SEQUENCE_V2:
                    raise Phase5ComponentAdapterV2Error(
                        "inbox journey sequence exhausted"
                    )
                self._journey += 1
                self._cursors.clear()
                source: _CursorRecordV2 | None = None
            else:
                source = self._cursors.pop(cursor, None)
                if source is None:
                    raise Phase5ComponentAdapterV2Error(
                        "inbox continuation cursor unavailable"
                    )
                if source.page_size != page_size:
                    raise Phase5ComponentAdapterV2ContractError(
                        "inbox continuation page_size drift"
                    )
        self._guard.attest()
        component = self._projection
        token = self._lifecycle.begin(component)
        self._authority.verify_component(
            component,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
        actual_cursor = None if source is None else source.source_cursor
        request = _request_digest(
            self._guard.binding,
            component_identity=token.component_identity,
            generation=token.generation,
            page_size=page_size,
            cursor=actual_cursor,
        )
        self._host_attest(
            phase="pre",
            request_digest=request,
            page_digest=None,
            component_identity=token.component_identity,
            generation=token.generation,
        )
        try:
            if source is None:
                page = _callable_member(component, "open_page")(page_size=page_size)
            else:
                page = _callable_member(component, "continue_page")(
                    source.source_cursor
                )
        except BaseException as exc:
            raise Phase5ComponentAdapterV2Error("approval inbox read failed") from exc
        current = self._projection
        self._authority.verify_component(
            current,
            self._projection_attestation,
            role="inbox",
            generation=token.generation,
        )
        self._lifecycle.finish(token, current)
        exact_page_digest = _page_digest(page)
        self._host_attest(
            phase="post",
            request_digest=request,
            page_digest=exact_page_digest,
            component_identity=token.component_identity,
            generation=token.generation,
        )
        self._lifecycle.finish(token, self._projection)
        self._guard.attest()
        try:
            if _enum_value(page.state, "inbox state") != "READY":
                raise Phase5ComponentAdapterV2Error("approval inbox not ready")
            for name in (
                "authority_granted",
                "approval_action_available",
                "execution_available",
            ):
                if type(getattr(page, name)) is not bool or getattr(page, name):
                    raise Phase5ComponentAdapterV2ContractError(
                        "inbox page conveyed authority"
                    )
            items = page.items
            if type(items) is not tuple or len(items) > page_size:
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox page cardinality invalid"
                )
            total = _exact_int(page.total_items, "total_items", 0, MAX_ITEMS_V2)
            offset = _exact_int(page.offset, "offset", 0, total)
            if offset + len(items) > total:
                raise Phase5ComponentAdapterV2ContractError("inbox bounds invalid")
            snapshot_id = _digest(page.snapshot_id, "snapshot_id")
            view_digest = _digest(page.view_digest, "view_digest")
            actual_next = page.next_cursor
            if actual_next is not None and (
                type(actual_next) is not str or not actual_next
            ):
                raise Phase5ComponentAdapterV2ContractError(
                    "inbox next cursor invalid"
                )
            if not items and actual_next is not None:
                raise Phase5ComponentAdapterV2ContractError(
                    "empty inbox page cannot continue"
                )
        except AttributeError as exc:
            raise Phase5ComponentAdapterV2ContractError(
                "approval inbox page incomplete"
            ) from exc
        if source is None:
            if offset != 0:
                raise Phase5ComponentAdapterV2ContractError(
                    "first inbox offset not zero"
                )
        elif (
            offset != source.expected_offset
            or total != source.total_items
            or snapshot_id != source.snapshot_id
            or view_digest != source.view_digest
        ):
            raise Phase5ComponentAdapterV2ContractError(
                "inbox continuation relation drift"
            )
        projected = tuple(self._item(item, self._guard.binding) for item in items)
        next_cursor: str | None = None
        if actual_next is not None:
            with self._lock:
                self._lifecycle.finish(token, self._projection)
                if len(self._cursors) >= MAX_ITEMS_V2:
                    raise Phase5ComponentAdapterV2Error(
                        "inbox cursor capacity exhausted"
                    )
                if self._counter >= MAX_SEQUENCE_V2:
                    raise Phase5ComponentAdapterV2Error(
                        "inbox cursor sequence exhausted"
                    )
                self._counter += 1
                next_cursor = f"ibx2-{token.generation}-{self._counter}"
                if len(next_cursor.encode()) > MAX_CURSOR_BYTES_V2:
                    raise Phase5ComponentAdapterV2ContractError(
                        "short cursor invalid"
                    )
                self._cursors[next_cursor] = _CursorRecordV2(
                    token.generation,
                    actual_next,
                    page_size,
                    offset + len(items),
                    total,
                    snapshot_id,
                    view_digest,
                )
        self._authority.verify_component(
            self._batch_factory,
            self._batch_attestation,
            role="batch_factory",
            generation=token.generation,
        )
        result = _make_batch_v2(
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
            raise Phase5ComponentAdapterV2ContractError("terminal reason invalid")
        if self._lifecycle.close():
            with self._lock:
                self._cursors.clear()


def _make_batch_v2(
    factory: RuntimeBatchFactoryV2,
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
        raise Phase5ComponentAdapterV2Error("runtime batch construction failed") from exc
    try:
        if (
            result.items != items
            or result.replace is not replace
            or result.source_cursor != source_cursor
            or result.next_cursor != next_cursor
        ):
            raise Phase5ComponentAdapterV2ContractError(
                "runtime batch factory changed projection"
            )
    except AttributeError as exc:
        raise Phase5ComponentAdapterV2ContractError(
            "runtime batch factory incompatible"
        ) from exc
    return result


@dataclass(frozen=True, slots=True)
class ComponentAdapterBundleV2:
    runtime_components: object
    grant: GrantShadowAdapterV2 | None
    nexus: CapabilityNexusAdapterV2 | None
    inbox: ApprovalInboxAdapterV2 | None


def build_component_adapters_v2(
    *,
    flags: AdapterFlagsV2,
    acceptance: AcceptedComponentsV2,
    binding: object,
    binding_attestor: Callable[[], object],
    authority: HostAttestationAuthorityV2,
    attestations: Mapping[str, ComponentAttestationV2],
    batch_factory: RuntimeBatchFactoryV2,
    components_factory: RuntimeComponentsFactoryV2,
    action_request_type: type | None = None,
    grant_store: object | None = None,
    materialize_grant_request: Callable[[str], object] | None = None,
    nexus: object | None = None,
    inbox_projection: object | None = None,
    inbox_projection_attestor: Callable[..., ProjectionAttestationV2] | None = None,
) -> ComponentAdapterBundleV2:
    if type(flags) is not AdapterFlagsV2 or type(acceptance) is not AcceptedComponentsV2:
        raise Phase5ComponentAdapterV2ContractError(
            "exact flags and acceptance declarations required"
        )
    if type(authority) is not HostAttestationAuthorityV2:
        raise Phase5ComponentAdapterV2ContractError(
            "exact host attestation authority required"
        )
    if type(attestations) not in {dict, MappingProxyType}:
        raise Phase5ComponentAdapterV2ContractError("exact attestation mapping required")
    normalized_binding = AdapterBindingV2.from_runtime(binding)
    supplied = {
        "grant_shadow": grant_store is not None or materialize_grant_request is not None,
        "nexus_projection": nexus is not None,
        "approval_inbox": inbox_projection is not None
        or inbox_projection_attestor is not None,
    }
    for name, present in supplied.items():
        if present and not getattr(flags, name):
            raise Phase5ComponentAdapterV2ContractError(
                f"{name} supplied while flag off"
            )
    if not flags.adapters:
        if attestations:
            raise Phase5ComponentAdapterV2ContractError(
                "disabled adapters reject attestations"
            )
        return ComponentAdapterBundleV2(components_factory(), None, None, None)

    try:
        batch_attestation = attestations["batch_factory"]
        components_attestation = attestations["components_factory"]
    except KeyError as exc:
        raise Phase5ComponentAdapterV2ContractError(
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
    grant_adapter: GrantShadowAdapterV2 | None = None
    nexus_adapter: CapabilityNexusAdapterV2 | None = None
    inbox_adapter: ApprovalInboxAdapterV2 | None = None
    runtime_args: dict[str, object] = {}
    if flags.grant_shadow:
        acceptance.require("grants")
        if (
            grant_store is None
            or materialize_grant_request is None
            or action_request_type is None
        ):
            raise Phase5ComponentAdapterV2ContractError(
                "grant dependencies incomplete"
            )
        grant_adapter = GrantShadowAdapterV2(
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
            raise Phase5ComponentAdapterV2ContractError("nexus dependency missing")
        nexus_adapter = CapabilityNexusAdapterV2(
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
        if inbox_projection is None or inbox_projection_attestor is None:
            raise Phase5ComponentAdapterV2ContractError(
                "inbox dependencies incomplete"
            )
        inbox_adapter = ApprovalInboxAdapterV2(
            binding=normalized_binding,
            binding_attestor=binding_attestor,
            authority=authority,
            projection=inbox_projection,
            projection_attestation=attestations.get("inbox"),  # type: ignore[arg-type]
            projection_attestor=inbox_projection_attestor,
            projection_attestor_attestation=attestations.get(
                "inbox_projection_attestor"
            ),  # type: ignore[arg-type]
            batch_factory=batch_factory,
            batch_attestation=batch_attestation,
        )
        runtime_args.update(
            inbox_factory=inbox_adapter.factory,
            inbox_terminator=inbox_adapter.close,
        )
    components = components_factory(**runtime_args)
    authority.verify_component(
        components_factory,
        components_attestation,
        role="components_factory",
        generation=0,
    )
    for name, expected in runtime_args.items():
        if getattr(components, name, None) != expected:
            raise Phase5ComponentAdapterV2ContractError(
                f"components factory changed {name}"
            )
    return ComponentAdapterBundleV2(
        components, grant_adapter, nexus_adapter, inbox_adapter
    )


__all__ = [
    "ADAPTER_CONTRACT_V2",
    "GRANTS_ACCEPTANCE_V2",
    "NEXUS_ACCEPTANCE_V2",
    "INBOX_ACCEPTANCE_V2",
    "AdapterBindingV2",
    "AdapterFlagsV2",
    "AcceptedComponentsV2",
    "ComponentAttestationV2",
    "ProjectionAttestationV2",
    "HostAttestationAuthorityV2",
    "ApprovalInboxAdapterV2",
    "CapabilityNexusAdapterV2",
    "ComponentAdapterBundleV2",
    "GrantShadowAdapterV2",
    "Phase5ComponentAdapterV2ContractError",
    "Phase5ComponentAdapterV2Error",
    "build_component_adapters_v2",
]
