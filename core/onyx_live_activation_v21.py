"""Voice/tool exposure for Advanced Operations over exact Onyx Live V20.

V21 adds one local metadata tool. It cannot start a process, access the
network, approve a Phase 6 mission or mark a goal complete from model text.
All execution authority remains in the existing Phase 6 and MissionStore
chain; this layer only manages and projects owner goals and workflow graphs
around that authority.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v10 as v10
from core import onyx_live_activation_v20 as v20
from core.advanced_operations_controller_v1 import (
    HOST_CONTROLLER,
    AdvancedOperationsControllerV1,
)
from core.permission_broker import mark_audit_unhealthy
from core.native_workspace_events_v1 import FEATURE_FLAG as NATIVE_WORKSPACE_EVENTS_FLAG
from core.paths import runtime_dir
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1, _validate_state_root
from core.portable_host_capability_v1 import PortableHostBindingsV1
from core.tool_audit import append_tool_audit


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V21"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V21"
FEATURE_FLAG: Final = "ONYX_ADVANCED_OPERATIONS_COMMANDS_V1"
TOOL_NAME: Final = "advanced_operations"
HOST_MARKER: Final = "_advanced_operations_commands_activation_v21"
CONTROL_FLAGS: Final = (
    LIVE_MASTER_FLAG,
    LIVE_ROLLBACK_FLAG,
    FEATURE_FLAG,
    *v20.CONTROL_FLAGS,
    NATIVE_WORKSPACE_EVENTS_FLAG,
)
_ACTIONS: Final = (
    "status",
    "attention",
    "create_goal",
    "get_goal",
    "activate_goal",
    "pause_goal",
    "cancel_goal",
    "reconcile_goal",
    "create_automation_rule",
    "get_automation_rule",
    "create_site_project",
    "get_site_project",
    "bind_site_operation",
    "reconcile_site_operation",
    "suggest_preference",
    "get_preference_suggestion",
    "promote_preference",
    "reject_preference",
    "rollback_preference",
    "get_active_preference",
    "enroll_device",
    "get_device",
    "enable_device",
    "disable_device",
    "create_workflow",
    "get_workflow",
    "bind_workflow_plan",
    "activate_workflow",
    "pause_workflow",
    "cancel_workflow",
    "reconcile_workflow",
)


class ActivationV21Error(RuntimeError):
    pass


@contextmanager
def phase6_owner_private_state_boundary_v21(project: Path):
    """Keep accepted Phase 6 state out of the immutable application tree.

    V10 historically derives its mutable root from ``main.__file__``. Frozen
    releases place that module under ``_internal``; current V21 instead uses
    the active owner-data runtime (including an explicit diagnostic
    ``ONYX_DATA_DIR``), then restores the exact historical resolver before
    returning from installation.
    """

    try:
        expected_project = Path(project).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ActivationV21Error("Phase 6 project root is unavailable") from exc
    if not expected_project.is_dir():
        raise ActivationV21Error("Phase 6 project root is unavailable")

    original = v10._prepare_state_root
    owner_root = runtime_dir() / "phase6-live-wiring-v1"

    def prepare_state_root(candidate: Path) -> Path:
        try:
            resolved = Path(candidate).resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ActivationV21Error("Phase 6 project root is unavailable") from exc
        if resolved != expected_project or not resolved.is_dir():
            raise ActivationV21Error("Phase 6 project root diverged")
        owner_root.mkdir(parents=True, exist_ok=True)
        return _validate_state_root(owner_root, create=False)

    v10._prepare_state_root = prepare_state_root
    try:
        yield owner_root
    finally:
        if v10._prepare_state_root is not prepare_state_root:
            v10._prepare_state_root = original
            raise ActivationV21Error(
                "Phase 6 state-root seam diverged during activation"
            )
        v10._prepare_state_root = original


def tool_declaration_v21() -> dict[str, object]:
    return {
        "name": TOOL_NAME,
        "description": (
            "Manage Onyx goals, governed workflow graphs, approved automation bindings, "
            "site-operation bindings, "
            "owner-approved interaction preferences and local device enrollment. Read "
            "advanced-operation status and attention. This tool never executes external "
            "work; completion requires independently verified Phase 6 receipts."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "enum": list(_ACTIONS),
                    "description": "Exact local operation to perform.",
                },
                "goal_id": {"type": "STRING"},
                "parent_id": {"type": "STRING"},
                "level": {
                    "type": "STRING",
                    "enum": [
                        "objective",
                        "key_result",
                        "milestone",
                        "task",
                        "daily_action",
                    ],
                },
                "title": {"type": "STRING"},
                "objective": {"type": "STRING"},
                "definition_of_done": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                },
                "target_at": {
                    "type": "NUMBER",
                    "description": "Optional Unix timestamp for the goal target.",
                },
                "rule_id": {"type": "STRING"},
                "event_type": {"type": "STRING"},
                "metadata_filter": {"type": "OBJECT"},
                "plan_id": {"type": "STRING"},
                "mission_id": {"type": "STRING"},
                "expires_at": {"type": "NUMBER"},
                "max_uses": {"type": "INTEGER"},
                "project_id": {"type": "STRING"},
                "repository_id": {"type": "STRING"},
                "root": {"type": "STRING"},
                "operation": {
                    "type": "STRING",
                    "enum": ["build", "preview", "publish"],
                },
                "required_postconditions": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                },
                "binding_id": {"type": "STRING"},
                "suggestion_id": {"type": "STRING"},
                "preference_key": {
                    "type": "STRING",
                    "enum": [
                        "response_detail",
                        "conversation_tone",
                        "initiative",
                        "brief_format",
                        "interruption_style",
                    ],
                },
                "preference_value": {"type": "STRING"},
                "preference_evidence": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "evidence_id": {"type": "STRING"},
                            "source_type": {"type": "STRING"},
                            "source_reference": {"type": "STRING"},
                            "observation_digest": {"type": "STRING"},
                            "occurred_at": {"type": "NUMBER"},
                        },
                        "required": [
                            "evidence_id",
                            "source_type",
                            "source_reference",
                            "observation_digest",
                            "occurred_at",
                        ],
                    },
                },
                "device_id": {"type": "STRING"},
                "device_issuer": {"type": "STRING"},
                "workflow_id": {"type": "STRING"},
                "workflow_name": {"type": "STRING"},
                "workflow_description": {"type": "STRING"},
                "workflow_nodes": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "node_id": {"type": "STRING"},
                            "kind": {
                                "type": "STRING",
                                "enum": [
                                    "trigger",
                                    "condition",
                                    "transform",
                                    "plan",
                                    "output",
                                ],
                            },
                            "config": {"type": "OBJECT"},
                        },
                        "required": ["node_id", "kind", "config"],
                    },
                },
                "workflow_edges": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "source": {"type": "STRING"},
                            "target": {"type": "STRING"},
                            "route": {
                                "type": "STRING",
                                "enum": ["next", "true", "false"],
                            },
                        },
                        "required": ["source", "target", "route"],
                    },
                },
            },
            "required": ["action"],
        },
    }


@dataclass(frozen=True, slots=True)
class ActivationFlagsV21:
    master: bool
    commands: bool
    base: v20.ActivationFlagsV20

    def __post_init__(self) -> None:
        if (
            self.master is not True
            or self.commands is not True
            or type(self.base) is not v20.ActivationFlagsV20
        ):
            raise ActivationV21Error("complete exact V21 flags are required")

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV21":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV21Error("rollback is not an active V21 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(FEATURE_FLAG) != "true":
            raise ActivationV21Error("activation environment is not canonical V21")
        options = (
            {}
            if runtime_endpoint_factory is None
            else {"runtime_endpoint_factory": runtime_endpoint_factory}
        )
        try:
            base = v20.ActivationFlagsV20.from_canonical_environ(
                restore_v20_environment(source), **options
            )
        except v20.ActivationV20Error as exc:
            raise ActivationV21Error("V20 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    **v20_options: Any,
) -> dict[str, str]:
    result = v20.exact_activation_environment(workspace_roots, **v20_options)
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    result[NATIVE_WORKSPACE_EVENTS_FLAG] = "true"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v20_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(FEATURE_FLAG, None)
    result.pop(NATIVE_WORKSPACE_EVENTS_FLAG, None)
    return result


@dataclass(frozen=True, slots=True)
class HostContractV21:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v20.HostContractV20


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
) -> HostContractV21:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV21.from_canonical_environ(source, **options)
    try:
        base = v20.preflight_host(
            module,
            restore_v20_environment(source),
            portable_bindings=portable_bindings,
            **options,
        )
    except v20.ActivationV20Error as exc:
        raise ActivationV21Error("V20 host preflight failed") from exc
    host = getattr(module, "OnyxLive", None)
    declarations = getattr(module, "TOOL_DECLARATIONS", None)
    if (
        not isinstance(host, type)
        or host is not base.onyx_live
        or not isinstance(declarations, list)
        or not callable(getattr(host, "_execute_tool", None))
        or hasattr(host, HOST_MARKER)
    ):
        raise ActivationV21Error("V21 host contract is unavailable")
    return HostContractV21(module, host, base.project, base)


class OnyxLiveActivationV21:
    BASE_SEAM_COUNT = v20.OnyxLiveActivationV20.TOTAL_SEAM_COUNT
    V21_SEAM_COUNT = 4
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V21_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV21,
        contract: HostContractV21,
        **v20_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV21 or type(contract) is not HostContractV21:
            raise ActivationV21Error("exact V21 activation bindings are required")
        self.flags = flags
        self.contract = contract
        self._base = v20.OnyxLiveActivationV20(
            flags.base, contract.base, **v20_options
        )
        self._installed = False
        self._declaration: dict[str, object] | None = None
        self._original_execute: object | None = None
        self._owned_execute: object | None = None
        self._original_build_config: object | None = None
        self._owned_build_config: object | None = None
        self._wiring: Phase6LiveWiringV1 | None = None
        self._wiring_original: object | None = None

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    @property
    def advanced_commands_capability(self) -> str:
        return "available_local_metadata" if self._installed else "inactive"

    def _phase6_wiring(self) -> Phase6LiveWiringV1:
        cursor: object | None = self._base
        for _ in range(20):
            if cursor is None:
                break
            for name in ("wiring_controller", "_wiring_controller"):
                try:
                    candidate = getattr(cursor, name)
                except (AttributeError, RuntimeError):
                    continue
                if type(candidate) is Phase6LiveWiringV1:
                    return candidate
            cursor = getattr(cursor, "__dict__", {}).get("_base")
        raise ActivationV21Error("Phase 6 wiring authority is unavailable")

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV21Error("seam failpoint is outside V21 installation")
        base_failpoint = (
            fail_after
            if fail_after is not None and fail_after <= self.BASE_SEAM_COUNT
            else None
        )
        environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v20_environment(environment))
        try:
            with phase6_owner_private_state_boundary_v21(self.contract.project):
                self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(environment)
        if base_failpoint is not None:
            return
        module = self.contract.module
        host = self.contract.onyx_live
        declarations = module.TOOL_DECLARATIONS
        declaration = tool_declaration_v21()
        original_execute = host._execute_tool
        original_build_config = host._build_config

        async def execute_tool(instance: object, fc: object) -> object:
            if getattr(fc, "name", None) != TOOL_NAME:
                return await original_execute(instance, fc)
            arguments = dict(getattr(fc, "args", None) or {})
            action = str(arguments.get("action", ""))[:80]
            trace_id = os.urandom(8).hex()
            outcome = "completed"
            error_type = ""
            try:
                controller = getattr(instance, HOST_CONTROLLER, None)
                if type(controller) is not AdvancedOperationsControllerV1:
                    raise ActivationV21Error("advanced operations controller is unavailable")
                response = controller.execute(arguments)
                outcome = str(response.get("status", "completed"))
            except Exception as exc:
                outcome = "rejected"
                error_type = type(exc).__name__
                response = {
                    "contract": "OnyxAdvancedOperationsCommand.v1",
                    "status": "rejected",
                    "action": action,
                    "result": "Advanced operations request failed closed.",
                    "error": error_type,
                    "external_dispatch": False,
                }
            try:
                append_tool_audit(
                    profile="runtime",
                    tool=TOOL_NAME,
                    action=action,
                    decision="dispatch",
                    reason="local_metadata_only",
                    arguments=arguments,
                    outcome=outcome,
                    trace_id=trace_id,
                    error_type=error_type,
                )
            except Exception:
                mark_audit_unhealthy()
            return module.types.FunctionResponse(
                id=getattr(fc, "id", None),
                name=TOOL_NAME,
                response=response,
            )

        def build_config(instance: object) -> object:
            config = original_build_config(instance)
            controller = getattr(instance, HOST_CONTROLLER, None)
            if type(controller) is not AdvancedOperationsControllerV1:
                raise ActivationV21Error(
                    "advanced operations preference projection is unavailable"
                )
            projection = controller.preference_prompt_projection()
            if not projection:
                return config
            current = getattr(config, "system_instruction", None)
            if type(current) is not str:
                raise ActivationV21Error("live system instruction contract diverged")
            config.system_instruction = (
                current
                + "\n\n[OWNER-APPROVED INTERACTION PREFERENCES]\n"
                + projection
            )
            return config

        try:
            if any(
                isinstance(item, dict) and item.get("name") == TOOL_NAME
                for item in declarations
            ):
                raise ActivationV21Error("advanced operations declaration already exists")
            declarations.append(declaration)
            self._declaration = declaration
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV21Error("injected V21 declaration failure")
            wiring = self._phase6_wiring()
            with wiring._lock:
                wiring_original = wiring._protected.get("_execute_tool")
                if wiring_original is not original_execute:
                    raise ActivationV21Error("Phase 6 execute authority diverged")
                host._execute_tool = execute_tool
                wiring._protected["_execute_tool"] = execute_tool
            self._original_execute = original_execute
            self._owned_execute = execute_tool
            self._wiring = wiring
            self._wiring_original = wiring_original
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV21Error("injected V21 routing failure")
            host._build_config = build_config
            self._original_build_config = original_build_config
            self._owned_build_config = build_config
            if fail_after == self.BASE_SEAM_COUNT + 3:
                raise ActivationV21Error("injected V21 preference projection failure")
            setattr(host, HOST_MARKER, self)
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV21Error("injected V21 marker failure")
            self._installed = True
        except BaseException:
            self.rollback_all()
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV21Error("V21 activation is not installed")
        instance = self._base.instantiate_live(ui)
        if type(getattr(instance, HOST_CONTROLLER, None)) is not AdvancedOperationsControllerV1:
            raise ActivationV21Error("advanced operations controller did not reach V21")
        return instance

    def rollback_to_v20(self) -> None:
        errors: list[BaseException] = []
        host = self.contract.onyx_live
        wiring = self._wiring
        if self._owned_build_config is not None:
            try:
                if host._build_config is not self._owned_build_config:
                    raise ActivationV21Error("V21 build-config rollback drift")
                host._build_config = self._original_build_config
            except BaseException as exc:
                errors.append(exc)
        if self._owned_execute is not None:
            try:
                if wiring is None:
                    raise ActivationV21Error("V21 wiring rollback authority is missing")
                with wiring._lock:
                    if (
                        host._execute_tool is not self._owned_execute
                        or wiring._protected.get("_execute_tool") is not self._owned_execute
                    ):
                        raise ActivationV21Error("V21 execute rollback drift")
                    host._execute_tool = self._original_execute
                    wiring._protected["_execute_tool"] = self._wiring_original
            except BaseException as exc:
                errors.append(exc)
        marker = getattr(host, HOST_MARKER, None)
        if marker is self:
            delattr(host, HOST_MARKER)
        elif marker is not None:
            errors.append(ActivationV21Error("V21 marker rollback drift"))
        declarations = getattr(self.contract.module, "TOOL_DECLARATIONS", None)
        if isinstance(declarations, list) and self._declaration is not None:
            declarations[:] = [item for item in declarations if item is not self._declaration]
        if getattr(self.contract.module, "_onyx_live_activation_v21", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v21")
        self._declaration = None
        self._original_execute = None
        self._owned_execute = None
        self._original_build_config = None
        self._owned_build_config = None
        self._wiring = None
        self._wiring_original = None
        self._installed = False
        if errors:
            raise ActivationV21Error("V21 rollback completed with errors") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        try:
            self.rollback_to_v20()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ActivationV21Error("V21 full rollback completed with errors") from errors[0]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    portable_bindings: PortableHostBindingsV1 | None = None,
    **v20_options: Any,
) -> OnyxLiveActivationV21:
    source = os.environ if environ is None else environ
    options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV21(
        ActivationFlagsV21.from_canonical_environ(source, **options),
        preflight_host(
            module,
            source,
            portable_bindings=portable_bindings,
            **options,
        ),
        portable_bindings=portable_bindings,
        **v20_options,
    )
    controller.install()
    module._onyx_live_activation_v21 = controller
    return controller


__all__ = [
    "ActivationFlagsV21",
    "ActivationV21Error",
    "CONTROL_FLAGS",
    "FEATURE_FLAG",
    "HOST_MARKER",
    "HostContractV21",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "NATIVE_WORKSPACE_EVENTS_FLAG",
    "OnyxLiveActivationV21",
    "TOOL_NAME",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v20_environment",
    "tool_declaration_v21",
]
