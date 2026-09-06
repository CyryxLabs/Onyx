"""Onyx Live Activation V9: accepted V8 runtime plus accepted HUD V6.

V9 is an additive, default-off Windows source-checkout composition. Activation
V8 remains the runtime authority. The only new live seams install the accepted
HUD V6 host before ``MainWindow`` construction and replace V8's source shortcut
with the canonical V9 bootstrap. Frozen/package and non-Windows shortcut
behavior continues through V8 unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import Any, Final

from core import onyx_hud_orb_v6 as hud_v6
from core import onyx_live_activation_v8 as v8


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V9"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V9"
HUD_V6_FLAG: Final = hud_v6.FLAG_NAME
OWNER_PROFILE_FLAG = v8.OWNER_PROFILE_FLAG
HUD_V5_FLAG = v8.HUD_FLAG
PHASE5_FLAGS = v8.PHASE5_FLAGS
PHASE5_IDENTITY_FLAGS = v8.PHASE5_IDENTITY_FLAGS
PHASE5_IDENTITY_ALIASES = v8.PHASE5_IDENTITY_ALIASES
CANONICAL_PHASE5_IDENTITY = v8.CANONICAL_PHASE5_IDENTITY

BOOTSTRAP_RELATIVE = Path("scripts") / "bootstrap_onyx_live_v9.pyw"
CANONICAL_LAUNCHER_RELATIVE = Path("scripts") / "launch_onyx_live_v9.pyw"
RUNTIME_MANIFEST_RELATIVE = (
    Path("docs")
    / "onyx"
    / "checkpoints"
    / "onyx-live-activation-v9"
    / "runtime-manifest.json"
)
LEGACY_LAUNCHERS = frozenset(
    {
        "launch_onyx.pyw",
        "launch_onyx_live_v7.pyw",
        "launch_onyx_live_v8.pyw",
        "bootstrap_onyx_live_v8.pyw",
    }
)

# Filled only from independent E6 records. A non-hex placeholder fails closed.
V8_ACCEPTANCE_RELATIVE = Path(
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V8-E6-001.md"
)
HUD_V6_ACCEPTANCE_RELATIVE = Path("docs/onyx/acceptance/VE-HUD-ORB-V6-C003-E6-001.md")
V8_ACCEPTANCE_SHA256 = (
    "ee17b06e2f468c94621e7dda913e3dcda6850f3fbce478f0a5200fa9de1f1c0b"
)
HUD_V6_ACCEPTANCE_SHA256 = (
    "c9663515321554cec4e69524ee13eb543194562167da6ac21aafb219bcc65d9f"
)
V8_ACCEPTANCE_MANIFEST_RELATIVE = Path(
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V8-E6-001.manifest.json"
)
HUD_V6_ACCEPTANCE_MANIFEST_RELATIVE = Path(
    "docs/onyx/acceptance/VE-HUD-ORB-V6-C003-E6-001.manifest.json"
)
V8_ACCEPTANCE_MANIFEST_SHA256 = (
    "7a5c9f903bded763457bc465ab3dfdbb8c63193776cbab449725d7438f1dc479"
)
HUD_V6_ACCEPTANCE_MANIFEST_SHA256 = (
    "fbd22e3fd4e944a55ef872370c858783871eb5b20c27df58cefe14b3dc7dc4b9"
)
V8_MANIFEST_RELATIVE = Path(
    "docs/onyx/checkpoints/onyx-live-activation-v8/manifest.json"
)
HUD_V6_MANIFEST_RELATIVE = Path(
    "docs/onyx/checkpoints/hud-orb-v6-candidate/manifest.json"
)
V8_MANIFEST_SHA256 = "ab28f369248df1ed807aeeee15658193a533881bf68fb2268d49692b52c20392"
HUD_V6_MANIFEST_SHA256 = (
    "ba034588791b1003a6743bf037ae32a11285adcac7c4084cba1bc5bb3923ae1c"
)
RUNTIME_MANIFEST_SHA256 = (
    "8474c1716d9ad0ece51b52cfca3d80a75e5c8fa45ed35b2385b8d91b6b939947"
)

VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 10)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (
    *VERSION_CONTROL_FLAGS,
    HUD_V6_FLAG,
    *v8.CHILD_FLAGS,
    *PHASE5_IDENTITY_FLAGS,
    *PHASE5_IDENTITY_ALIASES,
)


class ActivationV9Error(RuntimeError):
    """The V9 composition, evidence root, or shortcut was not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_file(project: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise ActivationV9Error("noncanonical V9 path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise ActivationV9Error(f"required V9 file is unavailable: {relative}")
    try:
        path.resolve().relative_to(project.resolve())
    except ValueError as exc:
        raise ActivationV9Error(f"V9 path escapes project: {relative}") from exc
    return path


def _verify_file(project: Path, relative: Path, expected: str) -> Path:
    if (
        type(expected) is not str
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ActivationV9Error(f"unbound acceptance/hash root: {relative}")
    path = _canonical_file(project, relative)
    if _sha256(path) != expected:
        raise ActivationV9Error(f"V9 evidence drift: {relative}")
    return path


def _verify_accepted_roots(project: Path) -> None:
    for relative, digest in (
        (V8_ACCEPTANCE_RELATIVE, V8_ACCEPTANCE_SHA256),
        (HUD_V6_ACCEPTANCE_RELATIVE, HUD_V6_ACCEPTANCE_SHA256),
        (V8_ACCEPTANCE_MANIFEST_RELATIVE, V8_ACCEPTANCE_MANIFEST_SHA256),
        (
            HUD_V6_ACCEPTANCE_MANIFEST_RELATIVE,
            HUD_V6_ACCEPTANCE_MANIFEST_SHA256,
        ),
        (V8_MANIFEST_RELATIVE, V8_MANIFEST_SHA256),
        (HUD_V6_MANIFEST_RELATIVE, HUD_V6_MANIFEST_SHA256),
    ):
        _verify_file(project, relative, digest)


def _strict_json(path: Path) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ActivationV9Error(f"duplicate runtime-manifest key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationV9Error("runtime manifest is unreadable") from exc
    if type(payload) is not dict:
        raise ActivationV9Error("runtime manifest must be an object")
    return payload


def _verify_runtime_bundle(project: Path) -> dict[str, Path]:
    manifest_path = _verify_file(
        project, RUNTIME_MANIFEST_RELATIVE, RUNTIME_MANIFEST_SHA256
    )
    manifest = _strict_json(manifest_path)
    if manifest.get("schema") != "onyx.live-activation.v9.runtime":
        raise ActivationV9Error("runtime manifest schema mismatch")
    files = manifest.get("files")
    expected_names = {
        "pythonw": Path(".venv") / "Scripts" / "pythonw.exe",
        "bootstrap": BOOTSTRAP_RELATIVE,
        "launcher": CANONICAL_LAUNCHER_RELATIVE,
    }
    if type(files) is not dict or set(files) != set(expected_names):
        raise ActivationV9Error("runtime manifest file closure is incomplete")
    verified: dict[str, Path] = {}
    for name, expected_relative in expected_names.items():
        record = files[name]
        if type(record) is not dict:
            raise ActivationV9Error("runtime manifest record must be an object")
        if record.get("path") != expected_relative.as_posix():
            raise ActivationV9Error(f"runtime path mismatch: {name}")
        digest = record.get("sha256")
        if type(digest) is not str:
            raise ActivationV9Error(f"runtime hash missing: {name}")
        verified[name] = _verify_file(project, expected_relative, digest)
    return verified


@dataclass(frozen=True, slots=True)
class ActivationFlagsV9:
    master: bool
    hud_v6: bool
    base: v8.ActivationFlagsV8

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.hud_v6) is not bool
            or not self.master
            or not self.hud_v6
            or type(self.base) is not v8.ActivationFlagsV8
        ):
            raise ActivationV9Error("complete exact V9 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV9":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV9Error("rollback is not an active V9 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(HUD_V6_FLAG) != "1":
            raise ActivationV9Error("activation environment is not canonical V9")
        try:
            base = v8.ActivationFlagsV8.from_canonical_environ(source)
        except v8.ActivationV8Error as exc:
            raise ActivationV9Error("accepted V8 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v8.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[HUD_V6_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v8_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    result = dict(source)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(HUD_V6_FLAG, None)
    result.update(v8.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class ShortcutSpecV9:
    link: str
    target: str
    arguments: str
    working_directory: str
    icon: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ActivationV9Error("shortcut fields must be non-empty strings")
        if Path(self.arguments).name != BOOTSTRAP_RELATIVE.name:
            raise ActivationV9Error("shortcut must target the V9 bootstrap")
        if Path(self.arguments).name in LEGACY_LAUNCHERS:
            raise ActivationV9Error("legacy/V7/V8 shortcut entrypoint is forbidden")


@dataclass(frozen=True, slots=True)
class HostContractV9:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    project: Path
    base: v8.HostContractV8


def preflight_host(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> HostContractV9:
    source = os.environ if environ is None else environ
    ActivationFlagsV9.from_canonical_environ(source)
    project = Path(module.__file__).resolve().parent
    _verify_accepted_roots(project)
    _verify_runtime_bundle(project)
    base = v8.preflight_host(module, v8.exact_activation_environment())
    ui_module = base.ui_module
    if getattr(ui_module, "_ONYX_HUD_V6_INSTALLATION", None) is not None:
        raise ActivationV9Error("HUD V6 is already installed outside V9")
    return HostContractV9(module, ui_module, base.main_window, project, base)


class OnyxLiveActivationV9:
    """Three additive seams: HUD V6, V9 shortcut, and setup persistence."""

    BASE_SEAM_COUNT = v8.OnyxLiveActivationV8.TOTAL_SEAM_COUNT
    V9_SEAM_COUNT = 3
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V9_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV9,
        contract: HostContractV9,
        **v8_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV9 or type(contract) is not HostContractV9:
            raise ActivationV9Error("exact V9 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v8.OnyxLiveActivationV8(flags.base, contract.base, **v8_options)
        self._hud_installed = False
        self._shortcut_original: object | None = None
        self._setup_original: object | None = None

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def failure_type(self) -> str | None:
        return self._base.failure_type

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _source_shortcut_spec(self, instance: object) -> ShortcutSpecV9:
        verified = _verify_runtime_bundle(self.contract.project)
        bootstrap = verified["bootstrap"]
        launcher = verified["launcher"]
        target = verified["pythonw"]
        if bootstrap.name in LEGACY_LAUNCHERS or launcher.name in LEGACY_LAUNCHERS:
            raise ActivationV9Error("V9 runtime bundle selected a legacy entrypoint")
        desktop = instance._desktop_path("Windows")
        icon = self.contract.project / "config" / "onyx.ico"
        return ShortcutSpecV9(
            link=str(desktop / "Onyx.lnk"),
            target=str(target),
            arguments=str(bootstrap),
            working_directory=str(self.contract.project),
            icon=str(icon),
        )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV9Error("seam failpoint is outside V9 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        try:
            if not hud_v6.install_candidate(self.contract.ui_module):
                raise ActivationV9Error("HUD V6 exact flag was not installed")
            self._hud_installed = True
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV9Error("injected V9 HUD seam failure")

            window_type = self.contract.main_window
            original = window_type._create_desktop_shortcut
            controller = self

            def create_desktop_shortcut(instance: object) -> None:
                if (
                    controller.contract.ui_module.is_frozen()
                    or platform.system() != "Windows"
                ):
                    original(instance)
                    return
                try:
                    spec = controller._source_shortcut_spec(instance)
                    icon_path = Path(spec.icon)
                    if not icon_path.exists():
                        instance._build_onyx_icon(icon_path)
                    instance._create_lnk_windows(
                        spec.link,
                        spec.target,
                        spec.arguments,
                        spec.working_directory,
                        spec.icon,
                    )
                    instance._log.append_log(
                        "SYS: Desktop shortcut created for Onyx Live V9."
                    )
                except Exception as exc:
                    instance._log.append_log(
                        f"ERR: Shortcut failed safely ({type(exc).__name__})."
                    )

            window_type._create_desktop_shortcut = create_desktop_shortcut
            self._shortcut_original = original
            if fail_after == self.BASE_SEAM_COUNT + 2:
                raise ActivationV9Error("injected V9 shortcut seam failure")

            original_setup = window_type._on_setup_done

            def setup_done(
                instance: object,
                key: str,
                os_name: str,
                owner_name: str = "",
            ) -> None:
                original_setup(instance, key, os_name, owner_name)
                if getattr(instance, "_ready", False) and not getattr(
                    instance, "_overlay", None
                ):
                    instance._create_desktop_shortcut()

            window_type._on_setup_done = setup_done
            self._setup_original = original_setup
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV9Error("injected V9 setup seam failure")
        except Exception:
            self.rollback_installation()
            raise

    def start(self) -> object:
        return self._base.start()

    def rollback_installation(self) -> None:
        """Remove only V9/V6 state and retain the exact installed V8."""

        if self._setup_original is not None:
            self.contract.main_window._on_setup_done = self._setup_original
            self._setup_original = None
        if self._shortcut_original is not None:
            self.contract.main_window._create_desktop_shortcut = self._shortcut_original
            self._shortcut_original = None
        if self._hud_installed:
            if not hud_v6.uninstall_candidate(self.contract.ui_module):
                raise ActivationV9Error("HUD V6 rollback state was unavailable")
            self._hud_installed = False
        restored = restore_v8_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV9:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV9.from_canonical_environ(source)
    controller = OnyxLiveActivationV9(flags, preflight_host(module, source))
    controller.install()
    controller.start()
    module._onyx_live_activation_v9 = controller
    return controller


__all__ = [
    "ActivationFlagsV9",
    "ActivationV9Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HUD_V6_FLAG",
    "HostContractV9",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV9",
    "RUNTIME_MANIFEST_RELATIVE",
    "ShortcutSpecV9",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v8_environment",
]
