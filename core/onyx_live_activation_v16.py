"""Additive reversible Onyx Live V16 governance activation over V15."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import platform
import socket
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v15 as v15
from core import onyx_live_activation_v4 as v4
from core import permission_broker
from core.governance_nucleus_v1 import (
    DOWNGRADE_RECEIPT_ACCOUNT,
    DOWNGRADE_RECEIPT_SERVICE,
    DOWNGRADE_RECEIPT_TTL_MS,
    DOWNGRADE_SIGNING_ACCOUNT,
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
    _GovernanceLedgerV1,
    create_governance_nucleus_v1,
)
from core.portable_host_capability_v1 import (
    PortableHostBindingsV1,
    PortableHostCapabilityV1Error,
    require_portable_host_bindings_v1,
)
from core.workspaces import WorkspaceRecord


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V16"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V16"
FEATURE_FLAG: Final = "ONYX_GOVERNANCE_NUCLEUS_V1"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v15.CONTROL_FLAGS,
)
_DOWNGRADE_TARGETS: Final = frozenset({"v15", "v14", "rollback"})
_CONSUMED_DOWNGRADES: set[str] = set()
_DOWNGRADE_LOCK = threading.RLock()
GOVERNANCE_SMOKE_ARGUMENT: Final = "--governance-smoke-test"
GOVERNANCE_SMOKE_OUTPUT_ENV: Final = "ONYX_GOVERNANCE_SMOKE_OUTPUT"
GOVERNANCE_SMOKE_FAILURE_EXIT: Final = 79
_ACTIVE_HOST_LOCK = threading.RLock()
_ACTIVE_HOST_OWNER: tuple[object, object] | None = None


def _downgrade_vault() -> object:
    from core.native_vault import NativeSecretVault, SecretReference

    return NativeSecretVault(
        SecretReference(
            DOWNGRADE_RECEIPT_SERVICE,
            DOWNGRADE_RECEIPT_ACCOUNT,
            "Onyx V16 one-time owner-authorized downgrade receipt",
        )
    )


def _downgrade_signing_vault() -> object:
    from core.native_vault import NativeSecretVault, SecretReference

    return NativeSecretVault(
        SecretReference(
            DOWNGRADE_RECEIPT_SERVICE,
            DOWNGRADE_SIGNING_ACCOUNT,
            "Onyx V16 downgrade receipt authentication key",
        )
    )


def _downgrade_replay_ledger() -> _GovernanceLedgerV1:
    from core.native_vault import NativeSecretVault, SecretReference
    from core.paths import private_control_plane_runtime_dir

    root = private_control_plane_runtime_dir() / "governance-v1"
    return _GovernanceLedgerV1(
        root / "downgrade-replay.sqlite3",
        key_vault=NativeSecretVault(
            SecretReference(
                DOWNGRADE_RECEIPT_SERVICE,
                "downgrade-replay-key",
                "Onyx V16 downgrade replay ledger key",
            )
        ),
        head_vault=NativeSecretVault(
            SecretReference(
                DOWNGRADE_RECEIPT_SERVICE,
                "downgrade-replay-head",
                "Onyx V16 downgrade replay ledger head",
            )
        ),
        pending_vault=NativeSecretVault(
            SecretReference(
                DOWNGRADE_RECEIPT_SERVICE,
                "downgrade-replay-pending",
                "Onyx V16 downgrade replay pending append",
            )
        ),
    ).initialize()


def _consume_host_downgrade_receipt_v1(target: str) -> bool:
    if target not in _DOWNGRADE_TARGETS:
        return False
    store = _downgrade_vault()
    raw = store.get_bytes()
    if type(raw) is not bytes:
        return False
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    now = time.time_ns() // 1_000_000
    if (
        type(payload) is not dict
        or set(payload)
        != {
            "contract",
            "principal_id",
            "workspace_id",
            "session_id",
            "account_id",
            "profile_id",
            "target",
            "one_time",
            "request_digest",
            "issued_at_ms",
            "expires_at_ms",
            "nonce",
            "receipt_hmac",
        }
        or payload["contract"] != "OnyxV16DowngradeReceipt.v2"
        or payload["target"] != target
        or payload["one_time"] is not True
        or any(
            type(payload[name]) is not str or not payload[name]
            for name in (
                "principal_id",
                "workspace_id",
                "session_id",
                "account_id",
                "profile_id",
                "request_digest",
            )
        )
        or len(str(payload["request_digest"])) != 64
        or type(payload["issued_at_ms"]) is not int
        or type(payload["expires_at_ms"]) is not int
        or not payload["issued_at_ms"] <= now <= payload["expires_at_ms"]
        or payload["expires_at_ms"] - payload["issued_at_ms"]
        != DOWNGRADE_RECEIPT_TTL_MS
        or type(payload["nonce"]) is not str
        or len(payload["nonce"]) != 32
        or type(payload["receipt_hmac"]) is not str
        or len(payload["receipt_hmac"]) != 64
    ):
        return False
    supplied = str(payload.pop("receipt_hmac"))
    key_store = _downgrade_signing_vault()
    key = key_store.get_bytes()
    if type(key) is not bytes or len(key) != 32:
        return False
    expected = hmac.new(
        key,
        b"ONYX-V16-DOWNGRADE-RECEIPT.v2\0"
        + json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        return False
    with _DOWNGRADE_LOCK:
        ledger = _downgrade_replay_ledger()
        receipt_digest = hashlib.sha256(raw).hexdigest()
        try:
            ledger.append(
                "downgrade-receipt-consumed",
                "receipt-" + receipt_digest[:24],
                "global-downgrade",
                {
                    "nonce": payload["nonce"],
                    "target": target,
                    "receipt_digest": receipt_digest,
                    "request_digest": payload["request_digest"],
                },
                enforce_unique_entity=True,
            )
        except GovernanceV1Denied:
            return False
        except Exception:
            return False
        finally:
            ledger.close()
        if not store.delete() and store.get_bytes() is not None:
            return False
        _CONSUMED_DOWNGRADES.add(target)
    return True


def consume_bootstrap_downgrade_marker_v1(target: str) -> bool:
    with _DOWNGRADE_LOCK:
        if target not in _CONSUMED_DOWNGRADES:
            return False
        _CONSUMED_DOWNGRADES.remove(target)
        return True


def _derived_id(prefix: str, value: str) -> str:
    return prefix + "-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def governance_workspace_bindings_v1(
    workspace_roots: Sequence[str | os.PathLike[str]],
    *,
    owner_profile_id: str = v4.OWNER_PROFILE_ID,
) -> tuple[GovernanceIdentityV1, tuple[WorkspaceRecord, ...]]:
    roots = tuple(Path(item).resolve(strict=True) for item in workspace_roots)
    if not roots or len(set(roots)) != len(roots):
        raise ActivationV16Error("V16 workspace registry roots are invalid")
    principal_id = _derived_id("principal", owner_profile_id)
    account_id = _derived_id("account", owner_profile_id)
    profile_id = _derived_id("profile", owner_profile_id)
    records = tuple(
        WorkspaceRecord(
            _derived_id("workspace", os.path.normcase(str(root))),
            f"{root.name or 'Workspace'} [{index + 1}]",
            "personal" if index == 0 else "professional",
            "active",
            1,
            "derived-v16",
            "derived-v16",
        )
        for index, root in enumerate(roots)
    )
    primary = records[0]
    return (
        GovernanceIdentityV1(
            principal_id,
            primary.workspace_id,
            account_id,
            profile_id,
            primary.display_name,
        ),
        records,
    )


class ActivationV16Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ActivationFlagsV16:
    master: bool
    governance: bool
    base: v15.ActivationFlagsV15

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.governance) is not bool
            or not self.master
            or not self.governance
            or type(self.base) is not v15.ActivationFlagsV15
        ):
            raise ActivationV16Error("complete exact V16 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV16":
        source = os.environ if environ is None else environ
        endpoint_options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV16Error("rollback is not an active V16 configuration")
        if (
            source.get(LIVE_MASTER_FLAG) != "1"
            or source.get(FEATURE_FLAG) != "true"
        ):
            raise ActivationV16Error("activation environment is not canonical V16")
        base_source = restore_v15_environment(source)
        try:
            base = v15.ActivationFlagsV15.from_canonical_environ(
                base_source,
                **endpoint_options,
            )
        except v15.ActivationV15Error as exc:
            raise ActivationV16Error("V15 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v15_options: Any,
) -> dict[str, str]:
    result = v15.exact_activation_environment(
        workspace_roots, **v15_options
    )
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v15_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV16:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v15.HostContractV15


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV16:
    source = os.environ if environ is None else environ
    if os.name != "nt":
        try:
            sealed = require_portable_host_bindings_v1(
                portable_bindings,
                stage="governance_v16",
            )
        except PortableHostCapabilityV1Error as exc:
            raise ActivationV16Error(
                "V16 portable governance host boundary is unavailable"
            ) from exc
        if sealed.governance_descriptor_io is not True:
            raise ActivationV16Error(
                "V16 portable descriptor governance is unavailable"
            )
        if runtime_endpoint_factory not in (None, sealed.runtime_endpoint_factory):
            raise ActivationV16Error(
                "V16 portable runtime endpoint factory is invalid"
            )
        runtime_endpoint_factory = sealed.runtime_endpoint_factory
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV16.from_canonical_environ(
        source,
        **endpoint_options,
    )
    base_source = restore_v15_environment(source)
    try:
        base = v15.preflight_host(
            module,
            base_source,
            **endpoint_options,
        )
    except v15.ActivationV15Error as exc:
        raise ActivationV16Error("V15 host contract is unavailable") from exc
    onyx_live = getattr(module, "OnyxLive", None)
    if not isinstance(onyx_live, type):
        raise ActivationV16Error("V16 OnyxLive contract is unavailable")
    for name in (
        "__init__",
        "_start_phase5_session",
        "_stop_phase5_session",
        "_execute_tool",
    ):
        if not callable(getattr(onyx_live, name, None)):
            raise ActivationV16Error(f"V16 host seam unavailable: {name}")
    return HostContractV16(module, onyx_live, base.project, base)


class OnyxLiveActivationV16:
    """V15 plus one host-owned, durable governance nucleus."""

    BASE_SEAM_COUNT = v15.OnyxLiveActivationV15.TOTAL_SEAM_COUNT
    V16_SEAM_COUNT = 1
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V16_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV16,
        contract: HostContractV16,
        *,
        nucleus_factory: object | None = None,
        governance_path: Path | None = None,
        portable_bindings: PortableHostBindingsV1 | None = None,
        **v15_options: Any,
    ) -> None:
        if (
            type(flags) is not ActivationFlagsV16
            or type(contract) is not HostContractV16
        ):
            raise ActivationV16Error("exact V16 flags and contract are required")
        if nucleus_factory is not None and not callable(nucleus_factory):
            raise ActivationV16Error("nucleus factory must be callable")
        sealed: PortableHostBindingsV1 | None = None
        if os.name != "nt":
            if any(
                name in v15_options
                for name in (
                    "phase11_trusted_directory_factory",
                    "phase11_kill_signal_factory",
                )
            ):
                raise ActivationV16Error(
                    "arbitrary portable Phase 11 bindings are denied"
                )
            try:
                sealed = require_portable_host_bindings_v1(
                    portable_bindings,
                    stage="governance_v16",
                )
            except PortableHostCapabilityV1Error as exc:
                raise ActivationV16Error(
                    "V16 portable governance host boundary is unavailable"
                ) from exc
            if sealed.governance_descriptor_io is not True:
                raise ActivationV16Error(
                    "V16 portable descriptor governance is unavailable"
                )
            v15_options.update(
                phase11_trusted_directory_factory=sealed.trusted_directory_factory,
                phase11_kill_signal_factory=sealed.kill_signal_factory,
            )
        elif portable_bindings is not None:
            raise ActivationV16Error("portable V16 bindings are invalid on Windows")
        self.flags = flags
        self.contract = contract
        self._base = v15.OnyxLiveActivationV15(
            flags.base, contract.base, **v15_options
        )
        self._factory = nucleus_factory
        self._governance_path = governance_path
        self._portable_bindings = sealed
        self._installed = False
        self._originals: dict[str, object] = {}
        self._wrappers: dict[str, object] = {}
        self._nuclei: list[GovernanceNucleusV1] = []
        self._trusted_callback: object | None = None

    @property
    def executable_capability(self) -> str:
        return self._base.executable_capability

    @property
    def away_capability(self) -> str:
        return self._base.away_capability

    @property
    def external_agent_capability(self) -> str:
        return self._base.external_agent_capability

    @property
    def governance_capability(self) -> str:
        return "available" if self._installed else "inactive"

    def _create_nucleus(self) -> GovernanceNucleusV1:
        if self._factory is not None:
            result = self._factory()
            if type(result) is not GovernanceNucleusV1:
                raise ActivationV16Error(
                    "nucleus factory returned the wrong concrete type"
                )
            return result
        owner_controller = self._base._owner_controller
        authority = getattr(owner_controller, "_authority", None)
        snapshot = getattr(authority, "snapshot", None)
        owner_profile_id = getattr(authority, "_owner_profile_id", None)
        if (
            owner_controller is None
            or getattr(getattr(owner_controller, "state", None), "value", None)
            != "ready"
            or snapshot is None
            or getattr(snapshot, "reconciled", False) is not True
            or owner_profile_id != v4.OWNER_PROFILE_ID
        ):
            raise ActivationV16Error(
                "authenticated owner profile is unavailable for governance"
            )
        identity, workspace_records = governance_workspace_bindings_v1(
            self.flags.base.workspace_roots,
            owner_profile_id=owner_profile_id,
        )
        path = self._governance_path
        if path is None:
            from core.paths import private_control_plane_runtime_dir

            path = (
                private_control_plane_runtime_dir()
                / "governance-v1"
                / "governance.sqlite3"
            )
        return create_governance_nucleus_v1(
            path=path,
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            account_id=identity.account_id,
            profile_id=identity.profile_id,
            workspace_display=identity.workspace_display,
            workspace_records=workspace_records,
            trusted_directory_factory=(
                None
                if self._portable_bindings is None
                else self._portable_bindings.trusted_directory_factory
            ),
            require_host_boundary=(
                None if self._portable_bindings is None else True
            ),
        )

    def _install_seams(self, fail_after: int | None = None) -> None:
        host = self.contract.onyx_live
        protected = tuple(
            getattr(host, name)
            for name in (
                "_start_phase5_session",
                "_stop_phase5_session",
                "_execute_tool",
            )
        )
        if hasattr(host, "_governance_activation_v16"):
            raise ActivationV16Error("V16 host extension already exists")
        setattr(host, "_governance_activation_v16", self)
        if protected != tuple(
            getattr(host, name)
            for name in (
                "_start_phase5_session",
                "_stop_phase5_session",
                "_execute_tool",
            )
        ):
            raise ActivationV16Error("V16 altered a protected host seam")
        if fail_after == 1:
            raise ActivationV16Error("injected V16 seam failure")

    def initialize_host(self, instance: object) -> None:
        """Attach governance through the host's official post-init extension."""

        global _ACTIVE_HOST_OWNER
        with _ACTIVE_HOST_LOCK:
            if _ACTIVE_HOST_OWNER is not None:
                raise ActivationV16Error(
                    "another V16 live host already owns governance"
                )
            _ACTIVE_HOST_OWNER = (self, instance)
        try:
            if hasattr(instance, "_governance_nucleus_v1"):
                raise ActivationV16Error("governance nucleus already exists")
            nucleus = self._create_nucleus()
            setattr(instance, "_governance_nucleus_v1", nucleus)
            self._nuclei.append(nucleus)
            if self._trusted_callback is None:
                # The launcher installs the activation chain before main()
                # builds the UI, so the trusted callback does not exist at
                # install time. Resolve it here, at host construction, where
                # main() has already registered it. Without this the inbox
                # never wraps the callback, a human approval registers no
                # action-intent, and every governed dispatch fails the fence.
                # Never adopt an already-wrapped callback: it belongs to
                # another nucleus and wrap() refuses it, which would turn
                # host construction into a hard failure.
                candidate = permission_broker.get_permission_callback()
                if (
                    getattr(candidate, "_onyx_governance_inbox_v1", None)
                    is None
                ):
                    self._trusted_callback = candidate
            if self._trusted_callback is not None:
                permission_broker.set_permission_callback(
                    nucleus.approval_inbox.wrap(self._trusted_callback)
                )
            # Owner autonomy is evaluated inside the nucleus so an autonomous
            # grant records an action-intent like any other authorization and
            # satisfies the dispatch fence.  Without this the configured
            # autonomy is inert, because the broker only consults it when no
            # governance nucleus exists.
            nucleus.set_owner_autonomy_evaluator(
                permission_broker.owner_autonomy_evaluator
            )
            permission_broker.set_governance_authorization_hook(
                nucleus.authorization_hook
            )
        except BaseException:
            with _ACTIVE_HOST_LOCK:
                if (
                    _ACTIVE_HOST_OWNER is not None
                    and _ACTIVE_HOST_OWNER[0] is self
                    and _ACTIVE_HOST_OWNER[1] is instance
                ):
                    _ACTIVE_HOST_OWNER = None
            raise

    def begin_phase5_session(
        self, instance: object
    ) -> dict[str, str]:
        """Begin Governance while V4 preserves its own Phase 5 binding."""

        with _ACTIVE_HOST_LOCK:
            if _ACTIVE_HOST_OWNER != (self, instance):
                raise ActivationV16Error(
                    "V16 governance host does not own the Phase 5 session"
                )
        nucleus = getattr(instance, "_governance_nucleus_v1", None)
        if type(nucleus) is not GovernanceNucleusV1:
            raise ActivationV16Error("V16 governance nucleus is unavailable")
        nucleus.begin_session()
        try:
            return os.environ.copy()
        except BaseException:
            nucleus.end_session("phase5-start-failed")
            raise

    def abort_phase5_session(self, instance: object, reason: str) -> None:
        """Compensate a failed V4 bridge start; repeated cleanup is idempotent."""

        with _ACTIVE_HOST_LOCK:
            if _ACTIVE_HOST_OWNER != (self, instance):
                raise ActivationV16Error(
                    "V16 governance host does not own Phase 5 compensation"
                )
        nucleus = getattr(instance, "_governance_nucleus_v1", None)
        if type(nucleus) is not GovernanceNucleusV1:
            raise ActivationV16Error("V16 governance nucleus is unavailable")
        nucleus.end_session(reason)

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV16Error("seam failpoint is outside V16 installation")
        base_failpoint = (
            fail_after
            if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT
            else None
        )
        environment = dict(os.environ)
        self._trusted_callback = permission_broker.get_permission_callback()
        os.environ.clear()
        os.environ.update(restore_v15_environment(environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return
        try:
            v16_failpoint = (
                fail_after - self.BASE_SEAM_COUNT
                if fail_after is not None
                else None
            )
            self._install_seams(v16_failpoint)
            self._installed = True
        except BaseException:
            # V16 activation is atomic: a failure in any added seam restores
            # the exact pre-V15 host rather than leaving a partial base live.
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV16Error("V16 activation is not installed")
        instance = self._base.instantiate_live(ui)
        nucleus = getattr(instance, "_governance_nucleus_v1", None)
        if type(nucleus) is not GovernanceNucleusV1:
            raise ActivationV16Error("V16 nucleus did not reach live host")
        return instance

    def rollback_installation(self) -> None:
        global _ACTIVE_HOST_OWNER
        host = self.contract.onyx_live
        self._wrappers.clear()
        self._originals.clear()
        permission_broker.set_governance_authorization_hook(None)
        permission_broker.set_permission_callback(self._trusted_callback)
        self._trusted_callback = None
        with _ACTIVE_HOST_LOCK:
            if (
                _ACTIVE_HOST_OWNER is not None
                and _ACTIVE_HOST_OWNER[0] is self
            ):
                _ACTIVE_HOST_OWNER = None
        marker = getattr(host, "_governance_activation_v16", None)
        if marker is self:
            delattr(host, "_governance_activation_v16")
        elif marker is not None:
            raise ActivationV16Error("V16 rollback extension drift")
        module_marker = getattr(
            self.contract.module, "_onyx_live_activation_v16", None
        )
        if module_marker is self:
            delattr(self.contract.module, "_onyx_live_activation_v16")
        self._installed = False

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        for nucleus in tuple(self._nuclei):
            try:
                nucleus.close()
            except BaseException as exc:
                errors.append(exc)
        self._nuclei.clear()
        try:
            self.rollback_installation()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV16Error("V16 full rollback failed") from errors[0]


class GovernanceSmokePlatformRefusalV1(ActivationV16Error):
    """Typed refusal for the Windows-only native Governance smoke."""


class GovernanceSmokeExecutionErrorV1(ActivationV16Error):
    """Bounded smoke failure carrying the observed attempt counters."""

    def __init__(
        self,
        error_type: str,
        *,
        network_calls: int,
        provider_calls: int,
    ) -> None:
        super().__init__("native governance smoke failed safely")
        self.error_type = error_type
        self.network_calls = network_calls
        self.provider_calls = provider_calls


class _GovernanceSmokeIsolationV1:
    """Block and count real network/provider entry points before activation."""

    def __init__(self, module: ModuleType) -> None:
        self.module = module
        self.network_calls = 0
        self.provider_calls = 0
        self._installed = False
        self._socket = socket.socket
        self._create_connection = socket.create_connection
        provider = getattr(module, "genai", None)
        client = getattr(provider, "Client", None)
        if provider is None or not callable(client):
            raise ActivationV16Error(
                "real Gemini provider creation path is unavailable"
            )
        self._provider = provider
        self._client = client

    def _network_refused(
        self, *_args: object, **_kwargs: object
    ) -> object:
        self.network_calls += 1
        raise ActivationV16Error("network used by governance smoke")

    def _provider_refused(
        self, *_args: object, **_kwargs: object
    ) -> object:
        self.provider_calls += 1
        raise ActivationV16Error("provider used by governance smoke")

    def install(self) -> None:
        if self._installed:
            raise ActivationV16Error("governance smoke isolation is active")
        socket.socket = self._network_refused  # type: ignore[assignment]
        socket.create_connection = self._network_refused
        self._provider.Client = self._provider_refused
        self._installed = True

    def close(self) -> None:
        if not self._installed:
            return
        self._provider.Client = self._client
        socket.create_connection = self._create_connection
        socket.socket = self._socket  # type: ignore[assignment]
        self._installed = False


def _governance_smoke_native_vaults_v1(data: Path) -> tuple[object, ...]:
    """Create production-native vaults uniquely scoped to the isolated root."""

    from core.native_vault import NativeSecretVault, SecretReference

    scope = hashlib.sha256(
        os.path.normcase(str(data.resolve())).encode("utf-8")
    ).hexdigest()[:24]
    service = f"Onyx.GovernanceV1.Smoke.{scope}"
    return tuple(
        NativeSecretVault(
            SecretReference(
                service,
                account,
                f"Onyx Governance native smoke {label} for {scope}",
            )
        )
        for account, label in (
            ("ledger-key", "key"),
            ("ledger-head", "head"),
            ("ledger-pending", "pending commit"),
        )
    )


class _GovernanceSmokeUIV1:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None
        self.logs: list[str] = []

    def write_log(self, value: str) -> None:
        self.logs.append(str(value))

    def set_state(self, _value: str) -> None:
        pass


def _governance_smoke_output_path_v1() -> tuple[Path, Path]:
    from core.paths import data_root

    root = data_root().resolve()
    raw = os.environ.get(GOVERNANCE_SMOKE_OUTPUT_ENV, "").strip()
    if not raw:
        raise ActivationV16Error("isolated governance smoke output is required")
    output = Path(raw).resolve()
    if output.parent != root and not output.parent.is_relative_to(root):
        raise ActivationV16Error(
            "governance smoke output must remain inside isolated data root"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    return root, output


def write_governance_smoke_failure_v1(error: BaseException) -> None:
    """Persist a bounded failure result without copying exception details."""

    try:
        _root, output = _governance_smoke_output_path_v1()
        payload = {
            "contract": "OnyxGovernanceSmoke.v1",
            "status": "failed",
            "error_type": getattr(error, "error_type", type(error).__name__),
        }
        network_calls = getattr(error, "network_calls", None)
        provider_calls = getattr(error, "provider_calls", None)
        if type(network_calls) is int and type(provider_calls) is int:
            payload.update(
                {
                    "network_calls": network_calls,
                    "provider_calls": provider_calls,
                }
            )
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(output)
    except Exception:
        return


def _run_governance_smoke_windows_v1(
    module: ModuleType,
    *,
    data: Path,
    output: Path,
    isolation: _GovernanceSmokeIsolationV1,
    **v15_options: Any,
) -> dict[str, object]:
    """Run the Windows-native provider-free governance contract end to end."""

    flags = ActivationFlagsV16.from_canonical_environ(os.environ)
    identity, records = governance_workspace_bindings_v1(
        flags.base.workspace_roots
    )
    vaults = _governance_smoke_native_vaults_v1(data)
    ledger_path = data / "governance-smoke-v1" / "governance.sqlite3"

    def nucleus_factory() -> GovernanceNucleusV1:
        return create_governance_nucleus_v1(
            path=ledger_path,
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            account_id=identity.account_id,
            profile_id=identity.profile_id,
            workspace_display=identity.workspace_display,
            key_vault=vaults[0],
            head_vault=vaults[1],
            pending_vault=vaults[2],
            require_windows_boundary=True,
            workspace_records=records,
        )

    trusted_calls: list[str] = []

    def trusted(request: dict[str, object]) -> object:
        digest = request.get("digest")
        if type(digest) is str:
            trusted_calls.append(digest)
        return digest

    controller = OnyxLiveActivationV16(
        flags,
        preflight_host(module, os.environ),
        nucleus_factory=nucleus_factory,
        **v15_options,
    )
    permission_broker.set_permission_callback(trusted)
    instance: object | None = None
    reopened: GovernanceNucleusV1 | None = None
    killed: GovernanceNucleusV1 | None = None
    original_memory_dir = getattr(module, "memory_dir")
    original_runtime_dir = getattr(module, "runtime_dir")
    try:
        controller.install()
        module.memory_dir = lambda: data / "memory"
        module.runtime_dir = lambda: data / "runtime"
        smoke_ui = _GovernanceSmokeUIV1()
        instance = controller.instantiate_live(smoke_ui)
        nucleus = instance._governance_nucleus_v1
        try:
            instance._start_phase5_session()
        except Exception as exc:
            tail = [
                (event.event_type, event.payload)
                for event in nucleus._ledger.events(identity.workspace_id)[-6:]
            ]
            raise ActivationV16Error(
                "Phase 5 start failed during governance smoke: "
                f"cause={type(exc).__name__} events={tail!r} "
                f"logs={smoke_ui.logs!r}"
            ) from exc
        bridge = instance._phase5
        if nucleus.status().session_id is None:
            tail = [
                (event.event_type, event.payload)
                for event in nucleus._ledger.events(identity.workspace_id)[-4:]
            ]
            raise ActivationV16Error(
                "governance session ended during Phase5 start: "
                f"events={tail!r} logs={smoke_ui.logs!r}"
            )
        if bridge is None:
            raise ActivationV16Error("provider-free local catalog is unavailable")

        catalog_reads: list[dict[str, object]] = []
        for index in (1, 2):
            reference = f"smoke-{index}"
            allowed, reason = permission_broker.authorize_model_tool(
                "local_catalog_read",
                {
                    "page_size": 2,
                    "_phase5_invocation_ref": reference,
                },
            )
            if not allowed:
                raise ActivationV16Error(
                    "provider-free local catalog authorization failed: "
                    + reason
                )
            page = bridge.catalog_read(reference, {"page_size": 2})
            if page.get("state") != "completed":
                raise ActivationV16Error(
                    "provider-free local catalog read did not complete"
                )
            catalog_reads.append(
                {
                    "state": "completed",
                    "items": len(page.get("items", ())),
                }
            )
        if trusted_calls:
            raise ActivationV16Error(
                "provider-free reads unexpectedly requested trusted UI"
            )

        def govern(reference: str) -> tuple[bool, str]:
            return permission_broker.authorize_model_tool(
                "system_status",
                {"_governance_invocation_ref": reference},
            )

        first = govern("governance-smoke-grant-1")
        second = govern("governance-smoke-grant-2")
        if not first[0] or first != second:
            raise ActivationV16Error(
                "low-risk grant was not reused: "
                f"first={first!r} second={second!r}"
            )
        grant_one = first[1].removeprefix("governance-grant:")
        used_after_two = nucleus._grants[grant_one].used
        if used_after_two != 2:
            raise ActivationV16Error("low-risk grant use count is incorrect")
        nucleus.dashboard_facade(None, None).revoke_grant(grant_one)
        third = govern("governance-smoke-grant-3")
        grant_two = third[1].removeprefix("governance-grant:")
        if not third[0] or grant_two == grant_one:
            raise ActivationV16Error("revoked grant was reused")
        nucleus._grants[grant_two] = replace(
            nucleus._grants[grant_two], expires_at_ms=0
        )
        fourth = govern("governance-smoke-grant-4")
        grant_three = fourth[1].removeprefix("governance-grant:")
        if not fourth[0] or grant_three in {grant_one, grant_two}:
            raise ActivationV16Error("expired grant was reused")

        generation = nucleus.status().session_generation
        external_agent = controller.external_agent_capability
        away = controller.away_capability
        instance._stop_phase5_session("governance-smoke-restart")
        controller.rollback_all()
        instance = None

        reopened = nucleus_factory()
        restarted = reopened.begin_session()
        if restarted.generation != generation + 1:
            raise ActivationV16Error("session generation did not survive restart")
        if reopened.status().active_grants != 0:
            raise ActivationV16Error("grant survived governed restart")
        token = reopened.begin_invocation("governance-smoke-late")
        try:
            allowed = reopened.authorization_hook("system_status", {})
        finally:
            reopened.end_invocation(token)
        if allowed is None or allowed[0] is not True:
            raise ActivationV16Error("pre-kill action was not materialized")
        kill = reopened.global_kill()
        reopened.record_outcome(
            invocation_id="governance-smoke-late",
            outcome="completed",
            result={"late": True},
        )
        late_event = reopened._ledger.events(identity.workspace_id)[-1].event_type
        reopened.close()
        reopened = None
        killed = nucleus_factory()
        restart_kill_denied = False
        try:
            killed.begin_session()
        except GovernanceV1Denied:
            restart_kill_denied = True
        finally:
            killed.close()
            killed = None
        if late_event != "action-late-blocked" or not restart_kill_denied:
            raise ActivationV16Error("global kill did not survive restart")

        payload: dict[str, object] = {
            "contract": "OnyxGovernanceSmoke.v1",
            "status": "passed",
            "catalog_reads": catalog_reads,
            "trusted_ui_prompts": len(trusted_calls),
            "grant_reused": True,
            "grant_use_count_after_two": used_after_two,
            "grant_revoke_replaced": grant_two != grant_one,
            "grant_expiry_replaced": grant_three != grant_two,
            "restart_generation": restarted.generation,
            "restart_active_grants": 0,
            "global_kill_latched": kill.get("mutations_frozen") is True,
            "late_result_event": late_event,
            "restart_kill_denied": restart_kill_denied,
            "network_calls": isolation.network_calls,
            "provider_calls": isolation.provider_calls,
            "external_agent": external_agent,
            "away": away,
        }
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(output)
        return payload
    finally:
        module.memory_dir = original_memory_dir
        module.runtime_dir = original_runtime_dir
        if reopened is not None:
            reopened.close()
        if killed is not None:
            killed.close()
        if controller.governance_capability == "available":
            controller.rollback_all()
        permission_broker.set_permission_callback(None)
        for vault in vaults:
            vault.delete()


def run_governance_smoke_v1(
    module: ModuleType,
    **v15_options: Any,
) -> dict[str, object]:
    """Run the native Windows V16 smoke inside the isolated data root."""

    if platform.system() != "Windows":
        raise GovernanceSmokePlatformRefusalV1(
            "Governance V16 smoke is Windows-only"
        )
    data, output = _governance_smoke_output_path_v1()
    isolation = _GovernanceSmokeIsolationV1(module)
    isolation.install()
    try:
        return _run_governance_smoke_windows_v1(
            module,
            data=data,
            output=output,
            isolation=isolation,
            **v15_options,
        )
    except GovernanceSmokeExecutionErrorV1:
        raise
    except BaseException as exc:
        raise GovernanceSmokeExecutionErrorV1(
            type(exc).__name__,
            network_calls=isolation.network_calls,
            provider_calls=isolation.provider_calls,
        ) from exc
    finally:
        isolation.close()


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v15_options: Any,
) -> OnyxLiveActivationV16:
    source = os.environ if environ is None else environ
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV16(
        ActivationFlagsV16.from_canonical_environ(
            source,
            **endpoint_options,
        ),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **endpoint_options,
        ),
        portable_bindings=portable_bindings,
        **v15_options,
    )
    controller.install()
    module._onyx_live_activation_v16 = controller
    return controller


__all__ = [
    "ActivationFlagsV16",
    "ActivationV16Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "GOVERNANCE_SMOKE_ARGUMENT",
    "GOVERNANCE_SMOKE_FAILURE_EXIT",
    "GOVERNANCE_SMOKE_OUTPUT_ENV",
    "GovernanceSmokeExecutionErrorV1",
    "GovernanceSmokePlatformRefusalV1",
    "HostContractV16",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV16",
    "activate_main",
    "consume_bootstrap_downgrade_marker_v1",
    "exact_activation_environment",
    "exact_rollback_environment",
    "governance_workspace_bindings_v1",
    "preflight_host",
    "run_governance_smoke_v1",
    "restore_v15_environment",
    "write_governance_smoke_failure_v1",
]
