"""Canonical V15 activation reaching the immutable Phase 11 live bridge."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any, Final

from core import onyx_live_activation_v14 as v14
from core import onyx_live_activation_v4 as v4
from core import onyx_live_activation_v6 as v6
from core import owner_profile_v8 as owner_v8
from core.executable_runtime_endpoint_v1 import ExecutableRuntimeEndpointV1
from core.phase11_live_mission_v1 import (
    FEATURE_FLAG,
    Phase11LiveMissionV1,
    WORKSPACE_ROOTS_FLAG,
)
from core.phase11_governed_away_v1 import AWAY_UNAVAILABLE_REASONS
from core.phase11_executable_sandbox_v1 import (
    ExecutableSandboxHostV1,
    FEATURE_FLAG as EXECUTABLE_SANDBOX_FLAG,
)
from core.phase11_project_autopilot_v1 import (
    FEATURE_FLAG as PROJECT_AUTOPILOT_FLAG,
)
from core.phase6_live_wiring_v1 import Phase6LiveWiringV1
from core.external_agent_adapter_v1 import (
    ExternalAgentUnavailable,
    ExternalCodingAgentAdapterV1,
    discover_claude_code_provider_v1,
    resolve_trusted_git_v1,
)
from core.live_voice_continuity_v1 import (
    LiveVoiceContinuityInstallationV1,
    install_live_voice_continuity_v1,
)
from memory.store import _is_reparse


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V15"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V15"
PLATFORM_REFUSAL_SIGNAL: Final = (
    "ONYX_LIVE_V15_PLATFORM_UNAVAILABLE_WINDOWS_REQUIRED"
)
PLATFORM_REFUSAL_EXIT: Final = 78
OWNER_NAME_REQUIRED_MESSAGE: Final = (
    "Enter your real name. 'Sir' is only Onyx's temporary form of address "
    "until it knows what to call you."
)
OWNER_ADDRESS_PREFERENCE_KEY: Final = "owner_address_preference"
EXPLICIT_SIR_ADDRESS: Final = "Sir"
EXECUTABLE_DOCKER_CLI_FLAG: Final = "ONYX_PHASE11_EXECUTABLE_DOCKER_CLI"
EXECUTABLE_DOCKER_HOST_FLAG: Final = "ONYX_PHASE11_EXECUTABLE_DOCKER_HOST"
EXECUTABLE_PLATFORM_FLAG: Final = "ONYX_PHASE11_EXECUTABLE_PLATFORM"
EXECUTABLE_IMAGE_IDS_FLAG: Final = "ONYX_PHASE11_EXECUTABLE_IMAGE_IDS"
DEFAULT_WINDOWS_DOCKER_CLI: Final = (
    r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
)
DEFAULT_WINDOWS_DOCKER_HOST: Final = "npipe:////./pipe/docker_engine"
DEFAULT_EXECUTABLE_PLATFORM: Final = "linux/amd64"
# This immutable no-volume image is already the sandbox's documented local
# smoke target. It provides a deterministic default authority set without
# permitting tags, pulls, builds, or arbitrary image discovery.
DEFAULT_EXECUTABLE_IMAGE_IDS: Final = (
    "sha256:37a38e48e9338cd7e89dfeb487f37b02ebfcd9cb23111bed2d345e79d37d6dd6",
)
DEFAULT_EXTERNAL_AGENT_MODEL: Final = "sonnet"
DEFAULT_EXTERNAL_AGENT_MAX_BUDGET_USD: Final = 1.0
DEFAULT_EXTERNAL_AGENT_MAX_SECONDS: Final = 900
DEFAULT_EXTERNAL_AGENT_MAX_OUTPUT_BYTES: Final = 512 * 1024
BOOTSTRAP_RELATIVE: Final = Path("scripts/bootstrap_onyx_live_v15.pyw")
CANONICAL_LAUNCHER_RELATIVE: Final = Path("scripts/launch_onyx_live_v15.pyw")
V14_FROZEN_ROOTS: Final = (
    (
        Path("core/onyx_live_activation_v14.py"),
        "df604cb355125be3907f84c30df13bd080406524d19f2ad81b8c117771684c21",
    ),
    (
        Path("scripts/bootstrap_onyx_live_v14.pyw"),
        "61ac705b22c1367522baa69cfd58232f3b3a4d8ff9189cebafd34b2d4431e84c",
    ),
    (
        Path("scripts/launch_onyx_live_v14.pyw"),
        "796988ba1cbca6d38da37d6b005fb90aa7767b7ec4a009a2f5d9705e39dbbf0c",
    ),
)
VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 16)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (
    *VERSION_CONTROL_FLAGS,
    FEATURE_FLAG,
    WORKSPACE_ROOTS_FLAG,
    PROJECT_AUTOPILOT_FLAG,
    EXECUTABLE_SANDBOX_FLAG,
    EXECUTABLE_DOCKER_CLI_FLAG,
    EXECUTABLE_DOCKER_HOST_FLAG,
    EXECUTABLE_PLATFORM_FLAG,
    EXECUTABLE_IMAGE_IDS_FLAG,
    *v14.CONTROL_FLAGS,
)


class ActivationV15Error(RuntimeError):
    pass


def _validate_external_agent_factory_v1(factory: object) -> None:
    """Fail during injection when a factory cannot accept the live binding."""

    if not callable(factory):
        raise ActivationV15Error(
            "V15 external-agent factory must be callable"
        )
    try:
        signature = inspect.signature(factory)
        signature.bind(
            state_root=Path("external-agent-signature-probe"),
            signing_key=b"signature-probe",
            terminal_state_resolver=lambda _mission_id: "",
        )
    except (TypeError, ValueError) as exc:
        raise ActivationV15Error(
            "V15 external-agent factory must accept state_root, signing_key, "
            "and terminal_state_resolver keywords"
        ) from exc


def _validated_away_degradation_reason(
    bridge: object,
    *,
    phase11_enabled: bool,
) -> str | None:
    away_mode = getattr(bridge, "away_mode", None)
    reason = getattr(bridge, "away_unavailable_reason", None)
    if not phase11_enabled:
        return None
    if away_mode is not None:
        if reason is not None:
            raise ActivationV15Error(
                "V15 Away capability state is inconsistent"
            )
        return None
    if type(reason) is str and reason in AWAY_UNAVAILABLE_REASONS:
        return reason
    raise ActivationV15Error(
        "V15 Away capability degradation reason is missing or invalid"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _workspace_roots(raw: str) -> tuple[str, ...]:
    if not isinstance(raw, str) or not raw.strip():
        raise ActivationV15Error("V15 requires explicitly provisioned workspace roots")
    roots: list[str] = []
    for item in raw.split(os.pathsep):
        if not item.strip():
            continue
        path = Path(item)
        if not path.is_absolute():
            raise ActivationV15Error("V15 workspace root is unavailable or unsafe")
        absolute = path.absolute()
        current = Path(absolute.anchor)
        for part in absolute.parts[1:]:
            current /= part
            if not current.exists():
                continue
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or _is_reparse(current):
                raise ActivationV15Error(
                    "V15 workspace root has a linked or reparse ancestor"
                )
        if not absolute.is_dir():
            raise ActivationV15Error("V15 workspace root is unavailable or unsafe")
        resolved = str(absolute.resolve())
        if resolved in roots:
            raise ActivationV15Error("V15 workspace roots must be unique")
        roots.append(resolved)
    if not roots:
        raise ActivationV15Error("V15 requires explicitly provisioned workspace roots")
    return tuple(roots)


def _executable_image_ids(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, str) or not raw:
        raise ActivationV15Error(
            "V15 executable image allowlist must be explicit"
        )
    values = tuple(raw.split(","))
    if (
        not values
        or len(values) > 16
        or len(set(values)) != len(values)
        or any(
            not re.fullmatch(r"sha256:[0-9a-f]{64}", value)
            for value in values
        )
    ):
        raise ActivationV15Error(
            "V15 executable image allowlist is not canonical"
        )
    return values


def _validated_executable_cli(
    raw: object, *, require_available: bool = True
) -> str:
    if (
        not isinstance(raw, str)
        or not raw
        or any(character in raw for character in ("\x00", "\r", "\n"))
    ):
        raise ActivationV15Error("V15 Docker CLI path is not canonical")
    path = Path(raw)
    if not path.is_absolute():
        raise ActivationV15Error("V15 Docker CLI path must be absolute")
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not current.exists():
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or _is_reparse(current):
            raise ActivationV15Error(
                "V15 Docker CLI path has a linked or reparse ancestor"
            )
    if require_available and not absolute.is_file():
        raise ActivationV15Error("V15 Docker CLI is unavailable")
    if absolute.is_file():
        return str(absolute.resolve(strict=True))
    return str(absolute)


def _executable_configuration(
    source: Mapping[str, str],
    *,
    runtime_endpoint: ExecutableRuntimeEndpointV1 | None = None,
) -> tuple[bool, str, str, str, tuple[str, ...]]:
    sandbox_flag = source.get(EXECUTABLE_SANDBOX_FLAG)
    if source.get(PROJECT_AUTOPILOT_FLAG) != "true" or sandbox_flag not in {
        "true",
        "false",
    }:
        raise ActivationV15Error(
            "V15 executable Project Autopilot flags are incomplete"
        )
    sandbox_available = sandbox_flag == "true"
    docker_cli = _validated_executable_cli(
        source.get(EXECUTABLE_DOCKER_CLI_FLAG),
        require_available=sandbox_available,
    )
    docker_host = source.get(EXECUTABLE_DOCKER_HOST_FLAG, "")
    if runtime_endpoint is None and not re.fullmatch(
        r"npipe:////\./pipe/[A-Za-z0-9_.-]+", docker_host
    ):
        raise ActivationV15Error("V15 Docker host must be an exact local npipe")
    if runtime_endpoint is not None and (
        type(runtime_endpoint) is not ExecutableRuntimeEndpointV1
        or runtime_endpoint.is_local is not True
        or runtime_endpoint.command_value() != docker_host
    ):
        raise ActivationV15Error(
            "V15 executable runtime endpoint binding is invalid"
        )
    platform = source.get(EXECUTABLE_PLATFORM_FLAG, "")
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ActivationV15Error(
            "V15 executable platform is not canonical"
        )
    image_ids = _executable_image_ids(
        source.get(EXECUTABLE_IMAGE_IDS_FLAG)
    )
    return sandbox_available, docker_cli, docker_host, platform, image_ids


def _verify_v14_roots(project: Path) -> None:
    root = project.resolve()
    for relative, expected in V14_FROZEN_ROOTS:
        path = root / relative
        if path.is_symlink() or not path.is_file() or _sha256(path) != expected:
            raise ActivationV15Error(f"V14 predecessor drift: {relative}")
    for relative in (BOOTSTRAP_RELATIVE, CANONICAL_LAUNCHER_RELATIVE):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ActivationV15Error(f"V15 runtime file unavailable: {relative}")


@dataclass(frozen=True, slots=True)
class ActivationFlagsV15:
    master: bool
    phase11: bool
    workspace_roots: tuple[str, ...]
    project_autopilot: bool
    executable_sandbox: bool
    executable_docker_cli: str
    executable_docker_host: str
    executable_platform: str
    executable_image_ids: tuple[str, ...]
    base: v14.ActivationFlagsV14
    runtime_endpoint: ExecutableRuntimeEndpointV1 | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.phase11) is not bool
            or not self.master
            or not self.phase11
            or not self.workspace_roots
            or type(self.project_autopilot) is not bool
            or type(self.executable_sandbox) is not bool
            or not self.project_autopilot
            or not isinstance(self.executable_docker_cli, str)
            or not isinstance(self.executable_docker_host, str)
            or not isinstance(self.executable_platform, str)
            or not self.executable_docker_cli
            or not self.executable_docker_host
            or self.executable_platform
            not in {"linux/amd64", "linux/arm64"}
            or type(self.workspace_roots) is not tuple
            or type(self.executable_image_ids) is not tuple
            or any(
                not isinstance(root, str) for root in self.workspace_roots
            )
            or any(
                not isinstance(image_id, str)
                for image_id in self.executable_image_ids
            )
            or type(self.base) is not v14.ActivationFlagsV14
        ):
            raise ActivationV15Error("complete exact V15 flags are required")
        roots = _workspace_roots(os.pathsep.join(self.workspace_roots))
        if roots != self.workspace_roots:
            raise ActivationV15Error(
                "V15 direct workspace roots are not canonical"
            )
        source = {
            PROJECT_AUTOPILOT_FLAG: (
                "true" if self.project_autopilot else "false"
            ),
            EXECUTABLE_SANDBOX_FLAG: (
                "true" if self.executable_sandbox else "false"
            ),
            EXECUTABLE_DOCKER_CLI_FLAG: self.executable_docker_cli,
            EXECUTABLE_DOCKER_HOST_FLAG: self.executable_docker_host,
            EXECUTABLE_PLATFORM_FLAG: self.executable_platform,
            EXECUTABLE_IMAGE_IDS_FLAG: ",".join(
                self.executable_image_ids
            ),
        }
        sandbox_available, docker_cli, docker_host, platform, image_ids = (
            _executable_configuration(
                source,
                runtime_endpoint=self.runtime_endpoint,
            )
        )
        if (
            sandbox_available is not self.executable_sandbox
            or docker_cli != self.executable_docker_cli
            or docker_host != self.executable_docker_host
            or platform != self.executable_platform
            or image_ids != self.executable_image_ids
        ):
            raise ActivationV15Error(
                "V15 direct executable configuration is not canonical"
            )

    @classmethod
    def from_canonical_environ(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        runtime_endpoint_factory: object | None = None,
    ) -> "ActivationFlagsV15":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV15Error("rollback is not an active V15 configuration")
        if (
            source.get(LIVE_MASTER_FLAG) != "1"
            or source.get(FEATURE_FLAG) != "true"
        ):
            raise ActivationV15Error("activation environment is not canonical V15")
        roots = _workspace_roots(source.get(WORKSPACE_ROOTS_FLAG, ""))
        if runtime_endpoint_factory is not None and not callable(
            runtime_endpoint_factory
        ):
            raise ActivationV15Error(
                "V15 runtime endpoint factory must be callable"
            )
        runtime_endpoint = None
        if runtime_endpoint_factory is not None:
            try:
                runtime_endpoint = runtime_endpoint_factory(
                    source.get(EXECUTABLE_DOCKER_HOST_FLAG, "")
                )
            except Exception as exc:
                raise ActivationV15Error(
                    "V15 runtime endpoint factory failed"
                ) from exc
        sandbox_available, docker_cli, docker_host, platform, image_ids = (
            _executable_configuration(
                source,
                runtime_endpoint=runtime_endpoint,
            )
        )
        try:
            base = v14.ActivationFlagsV14.from_canonical_environ(source)
        except v14.ActivationV14Error as exc:
            raise ActivationV15Error("V14 environment is incomplete") from exc
        return cls(
            True,
            True,
            roots,
            True,
            sandbox_available,
            docker_cli,
            docker_host,
            platform,
            image_ids,
            base,
            runtime_endpoint,
        )


def exact_activation_environment(
    workspace_roots: Sequence[str | os.PathLike[str]],
    *,
    executable_docker_cli: str = DEFAULT_WINDOWS_DOCKER_CLI,
    executable_docker_host: str = DEFAULT_WINDOWS_DOCKER_HOST,
    executable_platform: str = DEFAULT_EXECUTABLE_PLATFORM,
    executable_image_ids: Sequence[str] = DEFAULT_EXECUTABLE_IMAGE_IDS,
    executable_sandbox: bool = True,
    runtime_endpoint: ExecutableRuntimeEndpointV1 | None = None,
) -> dict[str, str]:
    raw = os.pathsep.join(str(Path(item)) for item in workspace_roots)
    roots = _workspace_roots(raw)
    result = v14.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[FEATURE_FLAG] = "true"
    result[WORKSPACE_ROOTS_FLAG] = os.pathsep.join(roots)
    result[PROJECT_AUTOPILOT_FLAG] = "true"
    if type(executable_sandbox) is not bool:
        raise ActivationV15Error(
            "V15 executable sandbox availability must be explicit"
        )
    result[EXECUTABLE_SANDBOX_FLAG] = (
        "true" if executable_sandbox else "false"
    )
    result[EXECUTABLE_DOCKER_CLI_FLAG] = executable_docker_cli
    result[EXECUTABLE_DOCKER_HOST_FLAG] = executable_docker_host
    result[EXECUTABLE_PLATFORM_FLAG] = executable_platform
    result[EXECUTABLE_IMAGE_IDS_FLAG] = ",".join(executable_image_ids)
    _executable_configuration(result, runtime_endpoint=runtime_endpoint)
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v14_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    for name in (
        LIVE_MASTER_FLAG,
        LIVE_ROLLBACK_FLAG,
        FEATURE_FLAG,
        WORKSPACE_ROOTS_FLAG,
        PROJECT_AUTOPILOT_FLAG,
        EXECUTABLE_SANDBOX_FLAG,
        EXECUTABLE_DOCKER_CLI_FLAG,
        EXECUTABLE_DOCKER_HOST_FLAG,
        EXECUTABLE_PLATFORM_FLAG,
        EXECUTABLE_IMAGE_IDS_FLAG,
    ):
        result.pop(name, None)
    result.update(v14.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class HostContractV15:
    module: ModuleType
    onyx_live: type
    project: Path
    base: v14.HostContractV14


def preflight_host(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
) -> HostContractV15:
    source = os.environ if environ is None else environ
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    ActivationFlagsV15.from_canonical_environ(
        source,
        **endpoint_options,
    )
    saved_environment = dict(os.environ)
    os.environ.clear()
    os.environ.update(restore_v14_environment(source))
    try:
        base = v14.preflight_host(module, os.environ)
    finally:
        os.environ.clear()
        os.environ.update(saved_environment)
    _verify_v14_roots(base.project)
    onyx_live = getattr(module, "OnyxLive", None)
    if (
        not isinstance(onyx_live, type)
        or not callable(getattr(module, "phase11_feature_enabled", None))
        or getattr(module, "Phase11LiveMissionV1", None) is not Phase11LiveMissionV1
    ):
        raise ActivationV15Error("V15 Phase 11 host contract is unavailable")
    return HostContractV15(module, onyx_live, base.project, base)


def verify_activation_prerequisites(
    project: Path,
    environ: Mapping[str, str] | None = None,
) -> None:
    source = os.environ if environ is None else environ
    ActivationFlagsV15.from_canonical_environ(source)
    saved_environment = dict(os.environ)
    os.environ.clear()
    os.environ.update(restore_v14_environment(source))
    try:
        v14.verify_activation_prerequisites(project, os.environ)
    finally:
        os.environ.clear()
        os.environ.update(saved_environment)
    _verify_v14_roots(project)


class OnyxLiveActivationV15:
    """V14 plus Phase 11 reachability and reversible onboarding repair."""

    BASE_SEAM_COUNT = v14.OnyxLiveActivationV14.TOTAL_SEAM_COUNT
    V15_SEAM_COUNT = 8
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V15_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV15,
        contract: HostContractV15,
        executable_sandbox_process_factory: object | None = None,
        external_agent_factory: object | None = None,
        phase11_trusted_directory_factory: object | None = None,
        phase11_kill_signal_factory: object | None = None,
        **v14_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV15 or type(contract) is not HostContractV15:
            raise ActivationV15Error("exact V15 flags and host contract are required")
        flags.validate()
        self.flags = flags
        self.contract = contract
        self._base = v14.OnyxLiveActivationV14(
            flags.base, contract.base, **v14_options
        )
        if executable_sandbox_process_factory is not None and not callable(
            executable_sandbox_process_factory
        ):
            raise ActivationV15Error(
                "V15 executable sandbox process adapter must be callable"
            )
        host_options = (
            {}
            if executable_sandbox_process_factory is None
            else {"process_factory": executable_sandbox_process_factory}
        )
        self._runtime_sandbox_host = ExecutableSandboxHostV1(
            docker_cli=self.flags.executable_docker_cli,
            docker_host=self.flags.executable_docker_host,
            **host_options,
        )
        if external_agent_factory is not None:
            _validate_external_agent_factory_v1(external_agent_factory)
        self._external_agent_factory_override = external_agent_factory
        if (
            phase11_trusted_directory_factory is not None
            and not callable(phase11_trusted_directory_factory)
        ):
            raise ActivationV15Error(
                "V15 Phase 11 trusted-directory factory must be callable"
            )
        if (
            phase11_kill_signal_factory is not None
            and not callable(phase11_kill_signal_factory)
        ):
            raise ActivationV15Error(
                "V15 Phase 11 kill-signal factory must be callable"
            )
        if (phase11_trusted_directory_factory is None) is not (
            phase11_kill_signal_factory is None
        ):
            raise ActivationV15Error(
                "V15 portable Phase 11 boundaries must be paired"
            )
        self._phase11_trusted_directory_factory = (
            phase11_trusted_directory_factory
        )
        self._phase11_kill_signal_factory = phase11_kill_signal_factory
        self.executable_capability = (
            "available"
            if self.flags.executable_sandbox
            else "unavailable:docker_cli_missing"
        )
        self.away_capability = "available"
        self.external_agent_capability = "probing"
        self._installed = False
        self._phase11_init_original: object | None = None
        self._phase11_init_wrapper: object | None = None
        self._owner_controller: v4.OnyxLiveActivationV4 | None = None
        self._owner_set_wrapper: object | None = None
        self._owner_correct_wrapper: object | None = None
        self._owner_forget_wrapper: object | None = None
        self._owner_name_wrapper: object | None = None
        self._owner_address_wrapper: object | None = None
        self._owner_prompt_wrapper: object | None = None
        self._owner_execute_original: object | None = None
        self._owner_execute_wrapper: object | None = None
        self._phase6_wiring: Phase6LiveWiringV1 | None = None
        self._phase6_execute_original: object | None = None
        self._check_config_original: object | None = None
        self._check_config_wrapper: object | None = None
        self._window_init_original: object | None = None
        self._window_init_wrapper: object | None = None
        self._setup_original: object | None = None
        self._setup_wrapper: object | None = None
        self._voice_continuity: LiveVoiceContinuityInstallationV1 | None = None
        self._live_bridges: list[Phase11LiveMissionV1] = []

    def _external_agent_factory(self, **binding: object) -> object:
        override = self._external_agent_factory_override
        if override is not None:
            return override(**binding)
        try:
            git_cli = resolve_trusted_git_v1()
        except ExternalAgentUnavailable:
            self.external_agent_capability = "unavailable:trusted_git_missing"
            raise
        try:
            provider = discover_claude_code_provider_v1()
        except ExternalAgentUnavailable as exc:
            self.external_agent_capability = (
                "unavailable:" + str(exc).replace(" ", "_")[:100]
            )
            raise
        adapter = ExternalCodingAgentAdapterV1(
            provider=provider,
            git_cli=git_cli,
            model=DEFAULT_EXTERNAL_AGENT_MODEL,
            max_budget_usd=DEFAULT_EXTERNAL_AGENT_MAX_BUDGET_USD,
            max_seconds=DEFAULT_EXTERNAL_AGENT_MAX_SECONDS,
            max_output_bytes=DEFAULT_EXTERNAL_AGENT_MAX_OUTPUT_BYTES,
            enabled=True,
            **binding,
        )
        health = adapter.health()
        if health.get("billable_dispatch_available") is not True:
            self.external_agent_capability = (
                "health_only:execution_account_receipt_unavailable"
            )
        else:
            self.external_agent_capability = "available:claude_code_cli"
        return adapter

    def _install_phase11_executable_runtime(self) -> None:
        bridge_type = Phase11LiveMissionV1
        original_init = bridge_type.__init__
        injected = {
            "autopilot_enabled": True,
            "governed_away_enabled": True,
            "executable_sandbox_enabled": self.flags.executable_sandbox,
            "executable_sandbox_host": (
                self._runtime_sandbox_host
                if self.flags.executable_sandbox
                else None
            ),
            "approved_executable_image_ids": self.flags.executable_image_ids,
            "executable_platform": self.flags.executable_platform,
            "external_agent_enabled": True,
            "external_agent_factory": self._external_agent_factory,
        }
        if self._phase11_trusted_directory_factory is not None:
            injected.update(
                {
                    "trusted_directory_factory": (
                        self._phase11_trusted_directory_factory
                    ),
                    "kill_signal_factory": self._phase11_kill_signal_factory,
                }
            )

        def initialize(
            instance: object, *args: object, **kwargs: object
        ) -> None:
            if set(injected).intersection(kwargs):
                raise ActivationV15Error(
                    "V15 Phase 11 executable authority is activation-owned"
                )
            original_init(instance, *args, **{**kwargs, **injected})
            if (
                isinstance(instance, Phase11LiveMissionV1)
                and instance not in self._live_bridges
            ):
                self._live_bridges.append(instance)

        bridge_type.__init__ = initialize
        self._phase11_init_original = original_init
        self._phase11_init_wrapper = initialize

    def _find_owner_controller(self) -> v4.OnyxLiveActivationV4:
        candidate: object | None = self._base
        observed: set[int] = set()
        while candidate is not None and id(candidate) not in observed:
            observed.add(id(candidate))
            if type(candidate) is v4.OnyxLiveActivationV4:
                return candidate
            candidate = getattr(candidate, "_base", None)
        raise ActivationV15Error("V15 owner controller is unavailable")

    def _find_voice_controller(self) -> v6.OnyxLiveActivationV6:
        candidate: object | None = self._base
        observed: set[int] = set()
        while candidate is not None and id(candidate) not in observed:
            observed.add(id(candidate))
            if type(candidate) is v6.OnyxLiveActivationV6:
                return candidate
            candidate = getattr(candidate, "_base", None)
        raise ActivationV15Error("V15 Gemini voice controller is unavailable")

    def _install_voice_continuity(self) -> None:
        self._voice_continuity = install_live_voice_continuity_v1(
            self._find_voice_controller()
        )

    @staticmethod
    def _validated_owner_name(value: object) -> str:
        if isinstance(value, str) and " ".join(value.split()).casefold() == "sir":
            return EXPLICIT_SIR_ADDRESS
        normalized = owner_v8.normalize_display_name(value)
        if normalized is None:
            raise owner_v8.InvalidDisplayName("A real display name is required")
        return normalized

    @staticmethod
    def _owner_config_path(controller: v4.OnyxLiveActivationV4) -> Path:
        authority = getattr(controller, "_authority", None)
        path = getattr(authority, "_config_path", None)
        if not isinstance(path, Path):
            raise ActivationV15Error("V15 owner projection path is unavailable")
        return path

    def _explicit_sir_selected(self, controller: v4.OnyxLiveActivationV4) -> bool:
        path = self._owner_config_path(controller)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return (
            isinstance(data, dict)
            and data.get(OWNER_ADDRESS_PREFERENCE_KEY) == EXPLICIT_SIR_ADDRESS
        )

    def _persist_explicit_sir(
        self,
        controller: v4.OnyxLiveActivationV4,
        *,
        selected: bool,
    ) -> None:
        from core.credentials import save_settings

        path = self._owner_config_path(controller)
        expected = EXPLICIT_SIR_ADDRESS if selected else ""
        save_settings({OWNER_ADDRESS_PREFERENCE_KEY: expected}, path)
        try:
            observed = json.loads(path.read_text(encoding="utf-8")).get(
                OWNER_ADDRESS_PREFERENCE_KEY
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ActivationV15Error(
                "V15 owner address preference readback failed"
            ) from exc
        if observed != expected:
            raise ActivationV15Error(
                "V15 owner address preference readback diverged"
            )

    def _install_owner_validation(self) -> None:
        controller = self._find_owner_controller()
        owned_names = {
            "set_name",
            "correct_name",
            "forget_name",
            "owner_name",
            "owner_address",
            "owner_prompt_directive",
        }
        if owned_names.intersection(vars(controller)):
            raise ActivationV15Error("V15 owner validation seam already exists")
        original_set = controller.set_name
        original_correct = controller.correct_name
        original_forget = controller.forget_name
        original_owner_name = controller.owner_name
        original_owner_address = controller.owner_address
        original_owner_prompt = controller.owner_prompt_directive
        activation = self

        def select_sir() -> object:
            prior_name = original_owner_name()
            prior_selected = activation._explicit_sir_selected(controller)
            snapshot = original_forget()
            try:
                activation._persist_explicit_sir(controller, selected=True)
                controller._contact_question = None
            except Exception:
                if prior_name:
                    original_correct(prior_name)
                if prior_selected:
                    activation._persist_explicit_sir(controller, selected=True)
                    controller._contact_question = None
                raise
            return snapshot

        def update_name(value: object, operation: str) -> object:
            normalized = activation._validated_owner_name(value)
            if normalized == EXPLICIT_SIR_ADDRESS:
                return select_sir()
            prior_selected = activation._explicit_sir_selected(controller)
            action = original_set if operation == "set" else original_correct
            snapshot = action(normalized)
            try:
                activation._persist_explicit_sir(controller, selected=False)
            except Exception:
                if prior_selected:
                    original_forget()
                    activation._persist_explicit_sir(controller, selected=True)
                    controller._contact_question = None
                raise
            return snapshot

        def set_name(value: object) -> object:
            return update_name(value, "set")

        def correct_name(value: object) -> object:
            return update_name(value, "correct")

        def forget_name() -> object:
            snapshot = original_forget()
            activation._persist_explicit_sir(controller, selected=False)
            return snapshot

        def owner_name() -> str:
            if activation._explicit_sir_selected(controller):
                return EXPLICIT_SIR_ADDRESS
            return original_owner_name()

        def owner_address() -> str:
            if activation._explicit_sir_selected(controller):
                return EXPLICIT_SIR_ADDRESS
            return original_owner_address()

        def owner_prompt_directive() -> str:
            if activation._explicit_sir_selected(controller):
                return (
                    "[OWNER ADDRESS - EXPLICIT USER PREFERENCE]\n"
                    "Address the owner with the literal English word 'Sir'. "
                    "Never translate, localize, or replace it with Efendim. "
                    "Do not ask for a different name unless the owner requests it."
                )
            return original_owner_prompt()

        controller.set_name = set_name
        controller.correct_name = correct_name
        controller.forget_name = forget_name
        controller.owner_name = owner_name
        controller.owner_address = owner_address
        controller.owner_prompt_directive = owner_prompt_directive
        if self._explicit_sir_selected(controller):
            controller._contact_question = None
        self._owner_controller = controller
        self._owner_set_wrapper = set_name
        self._owner_correct_wrapper = correct_name
        self._owner_forget_wrapper = forget_name
        self._owner_name_wrapper = owner_name
        self._owner_address_wrapper = owner_address
        self._owner_prompt_wrapper = owner_prompt_directive

    def _install_owner_tool_routing(self) -> None:
        controller = self._owner_controller
        if controller is None:
            raise ActivationV15Error("V15 owner validation must be installed first")
        host_type = self.contract.onyx_live
        original_execute = host_type._execute_tool
        module = self.contract.module

        async def execute_tool(instance: object, fc: object) -> object:
            name = getattr(fc, "name", None)
            if name not in v4._OWNER_TOOLS:
                return await original_execute(instance, fc)
            try:
                response = controller.handle_owner_tool(
                    name, dict(getattr(fc, "args", None) or {})
                )
            except Exception as exc:
                response = {
                    "result": "owner profile update refused",
                    "error": type(exc).__name__,
                }
            return module.types.FunctionResponse(
                id=fc.id,
                name=name,
                response=response,
            )

        wiring = self._base.wiring_controller
        if type(wiring) is not Phase6LiveWiringV1:
            raise ActivationV15Error("V15 Phase 6 wiring authority is unavailable")
        with wiring._lock:
            phase6_original = wiring._protected.get("_execute_tool")
            if phase6_original is not original_execute:
                raise ActivationV15Error(
                    "V15 Phase 6 owner routing authority diverged"
                )
            host_type._execute_tool = execute_tool
            wiring._protected["_execute_tool"] = execute_tool
        self._owner_execute_original = original_execute
        self._owner_execute_wrapper = execute_tool
        self._phase6_wiring = wiring
        self._phase6_execute_original = phase6_original

    def _install_onboarding_readiness(self) -> None:
        controller = self._owner_controller
        if controller is None:
            raise ActivationV15Error("V15 owner validation must be installed first")
        window_type = self.contract.base.base.main_window
        original_check = window_type._check_config

        def check_config(instance: object) -> bool:
            if not controller.owner_name():
                return False
            return original_check(instance) is True

        window_type._check_config = check_config
        self._check_config_original = original_check
        self._check_config_wrapper = check_config

    def _install_onboarding_init(self) -> None:
        controller = self._owner_controller
        if controller is None or self._check_config_wrapper is None:
            raise ActivationV15Error("V15 onboarding readiness must be installed first")
        window_type = self.contract.base.base.main_window
        original_init = window_type.__init__

        def initialize(instance: object, *args: object, **kwargs: object) -> None:
            original_init(instance, *args, **kwargs)
            if controller.owner_name():
                return
            overlay = getattr(instance, "_overlay", None)
            name_input = getattr(overlay, "_name_input", None)
            if name_input is None:
                return
            name_input.clear()
            name_input.setPlaceholderText("Your name (Onyx will use 'Sir' until then)")

        window_type.__init__ = initialize
        self._window_init_original = original_init
        self._window_init_wrapper = initialize

    def _install_onboarding_setup(self) -> None:
        if self._window_init_wrapper is None:
            raise ActivationV15Error("V15 onboarding init must be installed first")
        window_type = self.contract.base.base.main_window
        original_setup = window_type._on_setup_done
        activation = self

        def setup_done(
            instance: object,
            key: str,
            os_name: str,
            owner_name: str = "",
        ) -> None:
            try:
                normalized = activation._validated_owner_name(owner_name)
            except owner_v8.InvalidDisplayName:
                overlay = getattr(instance, "_overlay", None)
                if overlay is not None:
                    overlay.show_error(OWNER_NAME_REQUIRED_MESSAGE)
                return
            original_setup(instance, key, os_name, normalized)

        window_type._on_setup_done = setup_done
        self._setup_original = original_setup
        self._setup_wrapper = setup_done

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not 1 <= fail_after <= self.TOTAL_SEAM_COUNT:
            raise ActivationV15Error("seam failpoint is outside V15 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        v15_environment = dict(os.environ)
        os.environ.clear()
        os.environ.update(restore_v14_environment(v15_environment))
        try:
            self._base.install(fail_after=base_failpoint)
        finally:
            os.environ.clear()
            os.environ.update(v15_environment)
        if base_failpoint is not None:
            return
        if hasattr(self.contract.onyx_live, "_phase11_activation_v15"):
            self._base.rollback_all()
            raise ActivationV15Error("V15 host marker already exists")
        try:
            self.contract.onyx_live._phase11_activation_v15 = self
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV15Error("injected V15 reachability seam failure")
            self._install_phase11_executable_runtime()
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV15Error(
                    "injected V15 executable runtime seam failure"
                )
            self._install_owner_validation()
            if fail_after == self.BASE_SEAM_COUNT + 3:
                raise ActivationV15Error("injected V15 owner validation seam failure")
            self._install_owner_tool_routing()
            if fail_after == self.BASE_SEAM_COUNT + 4:
                raise ActivationV15Error("injected V15 owner routing seam failure")
            self._install_onboarding_readiness()
            if fail_after == self.BASE_SEAM_COUNT + 5:
                raise ActivationV15Error("injected V15 onboarding readiness seam failure")
            self._install_onboarding_init()
            if fail_after == self.BASE_SEAM_COUNT + 6:
                raise ActivationV15Error("injected V15 onboarding init seam failure")
            self._install_onboarding_setup()
            if fail_after == self.BASE_SEAM_COUNT + 7:
                raise ActivationV15Error("injected V15 onboarding setup seam failure")
            self._install_voice_continuity()
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV15Error("injected V15 voice continuity seam failure")
            self._installed = True
        except BaseException as primary:
            try:
                self.rollback_all()
            except BaseException as rollback:
                failure = ActivationV15Error(
                    "V15 installation and rollback both failed"
                )
                failure.add_note(f"primary failure type: {type(primary).__name__}")
                raise failure from rollback
            raise

    def instantiate_live(self, ui: object) -> object:
        if not self._installed:
            raise ActivationV15Error("V15 must be installed before runtime preflight")
        instance = self.contract.onyx_live(ui)
        bridge = getattr(instance, "_phase11_missions", None)
        worker = getattr(instance, "_mission_worker", None)
        runner = getattr(worker, "runner", None)
        autopilot = getattr(bridge, "autopilot", None)
        phase11_enabled = getattr(bridge, "enabled", False) is True
        away_mode = getattr(bridge, "away_mode", None)
        away_reason = _validated_away_degradation_reason(
            bridge,
            phase11_enabled=phase11_enabled,
        )
        away_degraded = away_reason is not None
        if (
            type(bridge) is not Phase11LiveMissionV1
            or getattr(runner, "__self__", None) is not bridge
            or getattr(runner, "__func__", None) is not Phase11LiveMissionV1.runner
            or getattr(worker, "running", True)
            or (
                not phase11_enabled
                and not getattr(bridge, "unavailable_reason", None)
            )
            or (
                phase11_enabled
                and away_mode is None
                and not away_degraded
            )
            or (
                phase11_enabled
                and getattr(autopilot, "_executable_sandbox_enabled", None)
                is not self.flags.executable_sandbox
            )
            or (
                phase11_enabled
                and self.flags.executable_sandbox
                and getattr(autopilot, "_executable_sandbox_host", None)
                is not self._runtime_sandbox_host
            )
            or (
                phase11_enabled
                and not self.flags.executable_sandbox
                and getattr(autopilot, "_executable_sandbox_host", None)
                is not None
            )
            or (
                phase11_enabled
                and getattr(autopilot, "_approved_executable_image_ids", None)
                != frozenset(self.flags.executable_image_ids)
            )
        ):
            raise ActivationV15Error(
                "V15 executable Phase 11 bridge did not reach the real MissionWorker"
            )
        if away_degraded:
            self.away_capability = f"unavailable:{away_reason}"
        elif not phase11_enabled:
            self.away_capability = (
                "unavailable:"
                + str(getattr(bridge, "unavailable_reason", "phase11_unavailable"))
            )
        else:
            self.away_capability = "available"
        if bridge not in self._live_bridges:
            self._live_bridges.append(bridge)
        return instance

    def rollback_installation(self) -> None:
        errors: list[BaseException] = []
        if self._voice_continuity is not None:
            try:
                self._voice_continuity.rollback()
            except BaseException as exc:
                errors.append(exc)
        self._voice_continuity = None
        window_type = self.contract.base.base.main_window
        if self._setup_wrapper is not None:
            if window_type._on_setup_done is self._setup_wrapper:
                window_type._on_setup_done = self._setup_original
            else:
                errors.append(ActivationV15Error("V15 setup seam authority drift"))
        self._setup_original = None
        self._setup_wrapper = None
        if self._window_init_wrapper is not None:
            if window_type.__init__ is self._window_init_wrapper:
                window_type.__init__ = self._window_init_original
            else:
                errors.append(ActivationV15Error("V15 init seam authority drift"))
        self._window_init_original = None
        self._window_init_wrapper = None
        if self._check_config_wrapper is not None:
            if window_type._check_config is self._check_config_wrapper:
                window_type._check_config = self._check_config_original
            else:
                errors.append(
                    ActivationV15Error("V15 readiness seam authority drift")
                )
        self._check_config_original = None
        self._check_config_wrapper = None
        if self._owner_execute_wrapper is not None:
            host_type = self.contract.onyx_live
            wiring = self._phase6_wiring
            if wiring is None:
                errors.append(ActivationV15Error("V15 Phase 6 routing authority lost"))
            else:
                with wiring._lock:
                    if (
                        host_type._execute_tool is self._owner_execute_wrapper
                        and wiring._protected.get("_execute_tool")
                        is self._owner_execute_wrapper
                    ):
                        host_type._execute_tool = self._owner_execute_original
                        wiring._protected["_execute_tool"] = (
                            self._phase6_execute_original
                        )
                    else:
                        errors.append(
                            ActivationV15Error("V15 owner routing authority drift")
                        )
        self._owner_execute_original = None
        self._owner_execute_wrapper = None
        self._phase6_wiring = None
        self._phase6_execute_original = None
        owner_controller = self._owner_controller
        if owner_controller is not None:
            for name, wrapper in (
                ("owner_prompt_directive", self._owner_prompt_wrapper),
                ("owner_address", self._owner_address_wrapper),
                ("owner_name", self._owner_name_wrapper),
                ("forget_name", self._owner_forget_wrapper),
                ("correct_name", self._owner_correct_wrapper),
                ("set_name", self._owner_set_wrapper),
            ):
                observed = vars(owner_controller).get(name)
                if observed is wrapper:
                    delattr(owner_controller, name)
                elif wrapper is not None:
                    errors.append(
                        ActivationV15Error(
                            f"V15 owner {name} validation authority drift"
                        )
                    )
        self._owner_controller = None
        self._owner_set_wrapper = None
        self._owner_correct_wrapper = None
        self._owner_forget_wrapper = None
        self._owner_name_wrapper = None
        self._owner_address_wrapper = None
        self._owner_prompt_wrapper = None
        if self._phase11_init_wrapper is not None:
            if Phase11LiveMissionV1.__init__ is self._phase11_init_wrapper:
                Phase11LiveMissionV1.__init__ = self._phase11_init_original
            else:
                errors.append(
                    ActivationV15Error(
                        "V15 Phase 11 executable runtime authority drift"
                    )
                )
        self._phase11_init_original = None
        self._phase11_init_wrapper = None
        marker = getattr(self.contract.onyx_live, "_phase11_activation_v15", None)
        if marker is self:
            delattr(self.contract.onyx_live, "_phase11_activation_v15")
        elif self._installed:
            errors.append(ActivationV15Error("V15 rollback marker authority drift"))
        self._installed = False
        restored = restore_v14_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v15", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v15")
        if errors:
            raise ActivationV15Error("V15 rollback failed") from errors[0]

    def rollback_all(self) -> None:
        errors: list[BaseException] = []
        bridges = tuple(self._live_bridges)
        self._live_bridges.clear()
        for bridge in bridges:
            try:
                bridge.close(15.0)
            except BaseException as exc:
                errors.append(exc)
        try:
            self.rollback_installation()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._base.rollback_all()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            failure = ActivationV15Error("V15 full rollback failed")
            for error in errors[:-1]:
                failure.add_note(f"rollback failure type: {type(error).__name__}")
            raise failure from errors[-1]


def activate_main(
    module: ModuleType,
    environ: Mapping[str, str] | None = None,
    *,
    runtime_endpoint_factory: object | None = None,
    **v14_options: Any,
) -> OnyxLiveActivationV15:
    source = os.environ if environ is None else environ
    endpoint_options = (
        {}
        if runtime_endpoint_factory is None
        else {"runtime_endpoint_factory": runtime_endpoint_factory}
    )
    controller = OnyxLiveActivationV15(
        ActivationFlagsV15.from_canonical_environ(
            source,
            **endpoint_options,
        ),
        preflight_host(
            module,
            source,
            **endpoint_options,
        ),
        **v14_options,
    )
    controller.install()
    module._onyx_live_activation_v15 = controller
    return controller


__all__ = [
    "ActivationFlagsV15",
    "ActivationV15Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HostContractV15",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV15",
    "PLATFORM_REFUSAL_EXIT",
    "PLATFORM_REFUSAL_SIGNAL",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v14_environment",
    "verify_activation_prerequisites",
]
