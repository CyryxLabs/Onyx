"""Default-off lifecycle wiring candidate for accepted V7 and Phase 6 V2.

The candidate patches only the post-V7 host lifecycle seams that create and
tear down a Phase 5 session. It does not add command routing, change provider
or circuit seams, import the live host, or activate itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Final

from core import onyx_live_activation_v7 as activation_v7
from core import phase6_agentic_core_v6 as agentic_v6
from core import phase6_live_integration_v2 as integration_v2
from core.missions import MissionStore
from core.phase5_integration_v3 import Phase5IntegrationV3
from core.phase6_agentic_core_v1 import DataClassV1, WorkspaceScopeV1


FEATURE_FLAG = "ONYX_PHASE6_LIVE_WIRING_V1"
SESSION_ATTRIBUTE = "_phase6_live_wiring_v1_session"
SCHEMA_VERSION = 1
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CONSTRUCTION_KEY = object()
_CORE_FACTORY = agentic_v6.create_phase6_agentic_core_v6
_INTEGRATION_FACTORY = integration_v2.create_phase6_live_integration_v2
_IDENTITY_FIELDS: Final = (
    "workspace_id",
    "account_id",
    "profile_id",
    "principal_id",
)


class Phase6LiveWiringV1Error(RuntimeError):
    """The lifecycle wiring could not complete safely."""


class Phase6LiveWiringV1ContractError(ValueError):
    """A wiring input or host contract is not exact."""


class Phase6LiveWiringV1Denied(PermissionError):
    """The wiring authority or runtime identity diverged."""


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _existing_path_is_linked(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _validate_state_root(value: Path | str, *, create: bool) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise Phase6LiveWiringV1ContractError(
            "an explicit absolute wiring state root is required"
        )
    absolute = path.absolute()
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise Phase6LiveWiringV1ContractError(
            "wiring state root cannot be resolved"
        ) from exc
    if resolved != absolute:
        raise Phase6LiveWiringV1ContractError("wiring state root uses a link or alias")
    current = path
    while not current.exists():
        parent = current.parent
        if parent == current:
            raise Phase6LiveWiringV1ContractError(
                "wiring state root has no existing ancestor"
            )
        current = parent
    try:
        while True:
            if _existing_path_is_linked(current):
                raise Phase6LiveWiringV1ContractError(
                    "wiring state root ancestry uses a link or reparse point"
                )
            if current.parent == current:
                break
            current = current.parent
        if create:
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir() or _existing_path_is_linked(path):
                raise Phase6LiveWiringV1ContractError(
                    "wiring state root is not a private directory"
                )
            if path.resolve(strict=True) != absolute:
                raise Phase6LiveWiringV1ContractError(
                    "wiring state root changed during creation"
                )
        elif path.exists() and not path.is_dir():
            raise Phase6LiveWiringV1ContractError(
                "wiring state root is not a directory"
            )
    except OSError as exc:
        raise Phase6LiveWiringV1ContractError(
            "wiring state root authentication failed"
        ) from exc
    return absolute


@dataclass(frozen=True, slots=True)
class LiveWiringFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6LiveWiringV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: dict[str, str] | os._Environ[str] | None = None
    ) -> "LiveWiringFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class LiveWiringIdentityV1:
    workspace_id: str
    account_id: str
    profile_id: str
    principal_id: str

    def __post_init__(self) -> None:
        try:
            integration_v2.HostIdentityBindingV2(
                self.workspace_id,
                self.account_id,
                self.profile_id,
                self.principal_id,
            )
        except Exception as exc:
            raise Phase6LiveWiringV1ContractError(
                "complete canonical V7 identity is required"
            ) from exc

    @classmethod
    def from_activation(
        cls, activation: activation_v7.OnyxLiveActivationV7
    ) -> "LiveWiringIdentityV1":
        if type(activation) is not activation_v7.OnyxLiveActivationV7:
            raise Phase6LiveWiringV1ContractError(
                "exact OnyxLiveActivationV7 is required"
            )
        flags = activation.flags
        return cls(
            flags.workspace_id,
            flags.account_id,
            flags.profile_id,
            flags.principal_id,
        )

    def payload(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in _IDENTITY_FIELDS}

    @property
    def digest(self) -> str:
        return _digest({"schema": "OnyxPhase6LiveWiringIdentity.v1", **self.payload()})

    def as_v2(self) -> integration_v2.HostIdentityBindingV2:
        return integration_v2.HostIdentityBindingV2(**self.payload())

    def attest(
        self,
        activation: activation_v7.OnyxLiveActivationV7,
        bridge: Phase5IntegrationV3 | None = None,
    ) -> None:
        if type(activation) is not activation_v7.OnyxLiveActivationV7:
            raise Phase6LiveWiringV1Denied("V7 activation type diverged")
        flags = activation.flags
        probe = activation.contract.phase5_probe
        observed = (
            flags.workspace_id,
            flags.account_id,
            flags.profile_id,
            flags.principal_id,
        )
        probed = (
            probe.workspace_id,
            probe.account_id,
            probe.profile_id,
            probe.principal_id,
        )
        expected = (
            self.workspace_id,
            self.account_id,
            self.profile_id,
            self.principal_id,
        )
        if observed != expected or probed != expected:
            raise Phase6LiveWiringV1Denied("V7 host identity diverged")
        if bridge is not None:
            binding = bridge.binding
            runtime = (
                binding.workspace_id,
                binding.account_id,
                binding.profile_id,
                getattr(bridge, "_principal_id", None),
            )
            if runtime != expected:
                raise Phase6LiveWiringV1Denied("runtime Phase 5 host identity diverged")


class LiveWiringSessionV1:
    """One identity-bound V2 facade scoped to one Phase 5 session."""

    __slots__ = (
        "identity",
        "session_key",
        "state_path",
        "receipt_path",
        "facade",
        "binding_digest",
        "_closed",
    )

    def __init__(
        self,
        *,
        identity: LiveWiringIdentityV1,
        session_key: str,
        state_path: Path,
        receipt_path: Path,
        facade: integration_v2.Phase6LiveIntegrationV2,
    ) -> None:
        if type(identity) is not LiveWiringIdentityV1:
            raise Phase6LiveWiringV1ContractError("exact wiring identity is required")
        if type(facade) is not integration_v2.Phase6LiveIntegrationV2:
            raise Phase6LiveWiringV1ContractError("exact V2 facade is required")
        self.identity = identity
        self.session_key = session_key
        self.state_path = state_path
        self.receipt_path = receipt_path
        self.facade = facade
        self.binding_digest = _digest(
            {
                "schema": "OnyxPhase6LiveWiringSession.v1",
                "identity": identity.payload(),
                "identity_digest": identity.digest,
                "session_key": session_key,
                "state_path_digest": hashlib.sha256(
                    str(state_path).encode("utf-8")
                ).hexdigest(),
                "receipt_path_digest": hashlib.sha256(
                    str(receipt_path).encode("utf-8")
                ).hexdigest(),
            }
        )
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.facade.close()


class Phase6LiveWiringV1:
    """Transactional post-V7 lifecycle patch with exact rollback."""

    PATCHED_SEAMS = ("__init__", "_start_phase5_session", "_stop_phase5_session")
    PROTECTED_SEAMS = ("_execute_tool", "_run_live_loop", "_send_realtime")

    def __init__(
        self,
        *,
        _key: object,
        activation: activation_v7.OnyxLiveActivationV7,
        identity: LiveWiringIdentityV1,
        state_root: Path,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LiveWiringV1ContractError("use create_phase6_live_wiring_v1")
        if (
            type(activation) is not activation_v7.OnyxLiveActivationV7
            or type(identity) is not LiveWiringIdentityV1
            or not isinstance(state_root, Path)
        ):
            raise Phase6LiveWiringV1ContractError(
                "exact wiring dependencies are required"
            )
        self._activation = activation
        self._identity = identity
        self._state_root = state_root
        self._host_type = activation.contract.base.onyx_live
        self._originals = {
            name: getattr(self._host_type, name) for name in self.PATCHED_SEAMS
        }
        self._protected = {
            name: getattr(self._host_type, name) for name in self.PROTECTED_SEAMS
        }
        self._installed = False
        self._installed_values: dict[str, object] = {}
        self._instances: weakref.WeakSet[object] = weakref.WeakSet()
        self._lock = threading.RLock()
        self._attest_host()

    @property
    def identity(self) -> LiveWiringIdentityV1:
        return self._identity

    @property
    def state_root(self) -> Path:
        return self._state_root

    @property
    def installed(self) -> bool:
        return self._installed

    @property
    def active_sessions(self) -> int:
        return sum(
            1
            for instance in list(self._instances)
            if type(getattr(instance, SESSION_ATTRIBUTE, None)) is LiveWiringSessionV1
        )

    def _attest_factories(self) -> None:
        if (
            agentic_v6.create_phase6_agentic_core_v6 is not _CORE_FACTORY
            or integration_v2.create_phase6_live_integration_v2
            is not _INTEGRATION_FACTORY
        ):
            raise Phase6LiveWiringV1Denied("sealed operational factory diverged")

    def _attest_host(self) -> None:
        self._attest_factories()
        if (
            type(self._activation) is not activation_v7.OnyxLiveActivationV7
            or type(self._activation.contract) is not activation_v7.HostContractV7
            or type(self._activation.contract.module) is not ModuleType
            or self._activation.state is not activation_v7.v6.ActivationV6State.READY
            or getattr(self._activation, "_installation_original", None) is None
        ):
            raise Phase6LiveWiringV1Denied(
                "V7 must be exact, installed and ready before wiring"
            )
        self._identity.attest(self._activation)
        for name, expected in self._protected.items():
            if getattr(self._host_type, name) is not expected:
                raise Phase6LiveWiringV1Denied(f"protected V7 seam diverged: {name}")
        if not self._installed:
            for name, expected in self._originals.items():
                if getattr(self._host_type, name) is not expected:
                    raise Phase6LiveWiringV1Denied(
                        f"post-V7 lifecycle seam diverged: {name}"
                    )
        else:
            for name, expected in self._installed_values.items():
                if getattr(self._host_type, name) is not expected:
                    raise Phase6LiveWiringV1Denied(
                        f"installed wiring seam diverged: {name}"
                    )

    def _session_paths(self, bridge: Phase5IntegrationV3) -> tuple[str, Path, Path]:
        binding = bridge.binding
        session_key = (
            "session-"
            + hashlib.sha256(
                (
                    f"{binding.session_id}\0{binding.trace_id}\0{self._identity.digest}"
                ).encode("utf-8")
            ).hexdigest()[:32]
        )
        session_root = _validate_state_root(
            self._state_root / "sessions" / session_key, create=True
        )
        return (
            session_key,
            session_root / "agentic-state-v6.sqlite3",
            session_root / "live-integration-v2.sqlite3",
        )

    def _workspace_root(self) -> Path:
        module = self._activation.contract.module
        get_base_dir = getattr(module, "get_base_dir", None)
        if not callable(get_base_dir):
            raise Phase6LiveWiringV1Denied("host workspace authority is unavailable")
        try:
            root = Path(get_base_dir()).resolve(strict=True)
        except (OSError, TypeError, ValueError) as exc:
            raise Phase6LiveWiringV1Denied(
                "host workspace authority is invalid"
            ) from exc
        if not root.is_dir() or _existing_path_is_linked(root):
            raise Phase6LiveWiringV1Denied(
                "host workspace authority is linked or unavailable"
            )
        return root

    def _create_session(
        self, instance: object, bridge: Phase5IntegrationV3
    ) -> LiveWiringSessionV1:
        self._attest_host()
        self._identity.attest(self._activation, bridge)
        missions = getattr(instance, "_missions", None)
        if type(missions) is not MissionStore:
            raise Phase6LiveWiringV1Denied(
                "exact host MissionStore authority is required"
            )
        session_key, state_path, receipt_path = self._session_paths(bridge)
        scope = WorkspaceScopeV1(
            self._identity.workspace_id,
            (str(self._workspace_root()),),
            DataClassV1.CONFIDENTIAL,
        )
        core: agentic_v6.AgenticCoreV6 | None = None
        facade: integration_v2.Phase6LiveIntegrationV2 | None = None
        try:
            core = _CORE_FACTORY(
                gate=agentic_v6.AgenticFeatureGateV6(True),
                sidecar_path=state_path,
                mission_store=missions,
                workspace_scope=scope,
            )
            state = getattr(core, "_state", None)
            if type(core) is not agentic_v6.AgenticCoreV6 or type(state) is not (
                agentic_v6.AgenticStateStoreV6
            ):
                raise Phase6LiveWiringV1Denied(
                    "exact Agentic Core V6 factory closure is required"
                )
            facade = _INTEGRATION_FACTORY(
                gate=integration_v2.LiveIntegrationFeatureGateV2(True),
                identity=self._identity.as_v2(),
                agentic_core=core,
                agentic_state=state,
                phase5=bridge,
                receipt_path=receipt_path,
            )
            if type(facade) is not integration_v2.Phase6LiveIntegrationV2:
                raise Phase6LiveWiringV1Denied(
                    "exact Live Integration V2 factory closure is required"
                )
            return LiveWiringSessionV1(
                identity=self._identity,
                session_key=session_key,
                state_path=state_path,
                receipt_path=receipt_path,
                facade=facade,
            )
        except Exception:
            if facade is not None:
                facade.close()
            elif core is not None:
                core.close()
            raise

    @staticmethod
    def _detach_session(instance: object) -> LiveWiringSessionV1 | None:
        session = getattr(instance, SESSION_ATTRIBUTE, None)
        setattr(instance, SESSION_ATTRIBUTE, None)
        if session is None:
            return None
        if type(session) is not LiveWiringSessionV1:
            raise Phase6LiveWiringV1Denied("host wiring session type diverged")
        return session

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and (
            type(fail_after) is not int
            or not 0 <= fail_after <= len(self.PATCHED_SEAMS)
        ):
            raise Phase6LiveWiringV1ContractError(
                "wiring failpoint is outside the patch transaction"
            )
        with self._lock:
            if self._installed:
                raise Phase6LiveWiringV1Denied("wiring is already installed")
            self._attest_host()
            originals = self._originals
            controller = self

            def host_init(instance: object, *args: object, **kwargs: object) -> None:
                originals["__init__"](instance, *args, **kwargs)
                if hasattr(instance, SESSION_ATTRIBUTE):
                    raise Phase6LiveWiringV1Denied(
                        "host wiring session attribute collided"
                    )
                setattr(instance, SESSION_ATTRIBUTE, None)
                controller._instances.add(instance)

            def start_phase5(instance: object) -> None:
                controller._attest_host()
                if getattr(instance, SESSION_ATTRIBUTE, None) is not None:
                    raise Phase6LiveWiringV1Denied(
                        "Phase 6 wiring session is already active"
                    )
                originals["_start_phase5_session"](instance)
                bridge = getattr(instance, "_phase5", None)
                try:
                    if type(bridge) is not Phase5IntegrationV3:
                        raise Phase6LiveWiringV1Denied(
                            "exact runtime Phase 5 V3 bridge is required"
                        )
                    session = controller._create_session(instance, bridge)
                    setattr(instance, SESSION_ATTRIBUTE, session)
                except Exception as exc:
                    try:
                        originals["_stop_phase5_session"](
                            instance, "phase6-live-wiring-failed"
                        )
                    finally:
                        setattr(instance, SESSION_ATTRIBUTE, None)
                    if isinstance(exc, Phase6LiveWiringV1Error):
                        raise
                    raise Phase6LiveWiringV1Denied(
                        "Phase 6 wiring failed closed"
                    ) from exc

            def stop_phase5(instance: object, reason: str) -> None:
                error: Exception | None = None
                try:
                    session = controller._detach_session(instance)
                    if session is not None:
                        session.close()
                except Exception as exc:
                    error = exc
                finally:
                    originals["_stop_phase5_session"](instance, reason)
                if error is not None:
                    if isinstance(error, Phase6LiveWiringV1Error):
                        raise error
                    raise Phase6LiveWiringV1Error(
                        "Phase 6 wiring teardown failed safely"
                    ) from error

            replacements = {
                "__init__": host_init,
                "_start_phase5_session": start_phase5,
                "_stop_phase5_session": stop_phase5,
            }
            patched: list[str] = []
            try:
                if fail_after == 0:
                    raise Phase6LiveWiringV1Error(
                        "injected failure before first wiring patch"
                    )
                for index, name in enumerate(self.PATCHED_SEAMS, start=1):
                    setattr(self._host_type, name, replacements[name])
                    patched.append(name)
                    if fail_after == index:
                        raise Phase6LiveWiringV1Error(
                            "injected wiring patch transaction failure"
                        )
            except Exception:
                for name in reversed(patched):
                    setattr(self._host_type, name, originals[name])
                raise
            self._installed_values = replacements
            self._installed = True
            self._attest_host()

    def rollback_installation(self) -> None:
        with self._lock:
            errors: list[Exception] = []
            for instance in list(self._instances):
                try:
                    session = self._detach_session(instance)
                    if session is not None:
                        session.close()
                    if hasattr(instance, SESSION_ATTRIBUTE):
                        delattr(instance, SESSION_ATTRIBUTE)
                except Exception as exc:
                    errors.append(exc)
            if self._installed:
                for name in reversed(self.PATCHED_SEAMS):
                    setattr(self._host_type, name, self._originals[name])
            self._installed_values = {}
            self._installed = False
            self._instances.clear()
            for name, expected in self._protected.items():
                if getattr(self._host_type, name) is not expected:
                    errors.append(
                        Phase6LiveWiringV1Denied(
                            f"protected V7 seam diverged during rollback: {name}"
                        )
                    )
            for name, expected in self._originals.items():
                if getattr(self._host_type, name) is not expected:
                    errors.append(
                        Phase6LiveWiringV1Denied(
                            f"post-V7 seam did not restore exactly: {name}"
                        )
                    )
            if errors:
                raise Phase6LiveWiringV1Error(
                    "wiring rollback completed with a fail-closed error"
                ) from errors[0]


def create_phase6_live_wiring_v1(
    *,
    gate: LiveWiringFeatureGateV1,
    activation: activation_v7.OnyxLiveActivationV7 | None = None,
    state_root: Path | str | None = None,
) -> Phase6LiveWiringV1 | None:
    """Construct an unwired controller; callers must explicitly install it."""

    if type(gate) is not LiveWiringFeatureGateV1:
        raise Phase6LiveWiringV1ContractError(
            "exact LiveWiringFeatureGateV1 is required"
        )
    if not gate.enabled:
        return None
    if type(activation) is not activation_v7.OnyxLiveActivationV7:
        raise Phase6LiveWiringV1ContractError(
            "enabled wiring requires exact ready V7 activation"
        )
    if state_root is None:
        raise Phase6LiveWiringV1ContractError(
            "enabled wiring requires an explicit state root"
        )
    root = _validate_state_root(state_root, create=False)
    identity = LiveWiringIdentityV1.from_activation(activation)
    identity.attest(activation)
    return Phase6LiveWiringV1(
        _key=_CONSTRUCTION_KEY,
        activation=activation,
        identity=identity,
        state_root=root,
    )


__all__ = [
    "FEATURE_FLAG",
    "SESSION_ATTRIBUTE",
    "LiveWiringFeatureGateV1",
    "LiveWiringIdentityV1",
    "LiveWiringSessionV1",
    "Phase6LiveWiringV1",
    "Phase6LiveWiringV1ContractError",
    "Phase6LiveWiringV1Denied",
    "Phase6LiveWiringV1Error",
    "create_phase6_live_wiring_v1",
]
