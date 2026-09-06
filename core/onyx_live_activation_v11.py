"""Default-off V11 activation adding accepted HUD V8 over accepted V10 C003."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import runpy
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import FunctionType, ModuleType
from typing import Any, Final

from core import onyx_live_activation_v10 as v10


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V11"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V11"
HUD_V8_FLAG: Final = "ONYX_HUD_V8_LIVE"
BOOTSTRAP_RELATIVE: Final = Path("scripts/bootstrap_onyx_live_v11.pyw")
CANONICAL_LAUNCHER_RELATIVE: Final = Path("scripts/launch_onyx_live_v11.pyw")
RUNTIME_MANIFEST_RELATIVE: Final = Path(
    "docs/onyx/checkpoints/onyx-live-activation-v11/runtime-manifest.json"
)
RUNTIME_MANIFEST_SHA256: Final = (
    "80bb3591318c7fcdd9757b7353a15e938a672e8b42349414acf8b1deb94775ef"
)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

V10_ACCEPTED_ROOTS: Final = (
    (
        Path("core/onyx_live_activation_v10.py"),
        "36c5710f7bf651b3412cccfb3ddc6586607df1e528acfe19021393c2ecfe1201",
    ),
    (
        Path("docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"),
        "b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236",
    ),
    (
        Path(
            "docs/onyx/acceptance/"
            "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.md"
        ),
        "4134d37498ccefe9044782c5c4edace53f14c29396117eac7a1181006cc38154",
    ),
    (
        Path(
            "docs/onyx/acceptance/"
            "VE-ONYX-LIVE-ACTIVATION-V10-C003-E6-001.manifest.json"
        ),
        "31f4d19c25d137edff5f9c1a148e141e66174709021cbda73b56788fd9537ce0",
    ),
)
HUD_V8_ACCEPTED_ROOTS: Final = (
    (
        Path("core/onyx_hud_orb_v8.py"),
        "f30c4d7433780082bb0ed87170e3e173b4bbc662c729ca83d075114f2775cd86",
    ),
    (
        Path("docs/onyx/checkpoints/hud-orb-v8-candidate/manifest.json"),
        "b3ea35bea9a160803ae01c3ddfc8e4e5811d5547095f7dc21b0ca8f2adbf4152",
    ),
    (
        Path("docs/onyx/acceptance/VE-HUD-ORB-V8-C001-E6-001.md"),
        "cc7241c02ce14a78929e5bd19e34ca5e5972fac49f4794cef5bcb3b377b6761c",
    ),
    (
        Path(
            "docs/onyx/acceptance/VE-HUD-ORB-V8-C001-E6-001.manifest.json"
        ),
        "313ef43b3c723100c4b0db0a341b9b3b5a30309800ad0385c01ebfb6ca28c256",
    ),
)
HUD_V8_ARTIFACT_ROOT_SHA256: Final = (
    "7d32ac55daeb3bb01dcdb18ea112c4d6d71453ff28cf1aed7fb07d9ae803a967"
)
HUD_V8_ARTIFACT_PATHS: Final = (
    "core/onyx_hud_orb_v8.py",
    "docs/onyx/checkpoints/hud-orb-v8-candidate/HUD_ORB_V8_CHECKPOINT.md",
    "docs/onyx/checkpoints/hud-orb-v8-candidate/hud-orb-v8-idle-1440x900.png",
    "docs/onyx/checkpoints/hud-orb-v8-candidate/hud-orb-v8-speaking-a-1440x900.png",
    "docs/onyx/checkpoints/hud-orb-v8-candidate/hud-orb-v8-speaking-b-1440x900.png",
    "docs/onyx/checkpoints/hud-orb-v8-candidate/hud-orb-v8.metrics.json",
    "qml/components/OnyxOrbVoiceLayerV8.qml",
    "qml/OnyxLiveShellV8.qml",
    "scripts/capture_hud_orb_v8_evidence.py",
    "scripts/verify_hud_orb_v8_candidate.py",
    "tests/test_onyx_hud_orb_v8_candidate.py",
)

VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 12)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (*VERSION_CONTROL_FLAGS, HUD_V8_FLAG, *v10.CONTROL_FLAGS)


class ActivationV11Error(RuntimeError):
    """The accepted V11 visual activation or runtime closure was not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_file(project: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise ActivationV11Error("noncanonical V11 path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise ActivationV11Error(f"required V11 file is unavailable: {relative}")
    try:
        path.resolve().relative_to(project.resolve())
    except ValueError as exc:
        raise ActivationV11Error(f"V11 path escapes project: {relative}") from exc
    return path


def _verify_file(project: Path, relative: Path, expected: str) -> Path:
    if (
        type(expected) is not str
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ActivationV11Error(f"unbound acceptance/hash root: {relative}")
    path = _canonical_file(project, relative)
    if _sha256(path) != expected:
        raise ActivationV11Error(f"V11 evidence drift: {relative}")
    return path


def _strict_json(path: Path) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ActivationV11Error(f"duplicate V11 manifest key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationV11Error("V11 manifest is unreadable") from exc
    if type(payload) is not dict:
        raise ActivationV11Error("V11 manifest must be an object")
    return payload


def _verify_accepted_roots(project: Path) -> None:
    for relative, expected in (*V10_ACCEPTED_ROOTS, *HUD_V8_ACCEPTED_ROOTS):
        _verify_file(project, relative, expected)
    v10_e6 = _strict_json(project / V10_ACCEPTED_ROOTS[3][0])
    hud_e6 = _strict_json(project / HUD_V8_ACCEPTED_ROOTS[3][0])
    for envelope in (v10_e6, hud_e6):
        if envelope.get("decision") != "accepted" or envelope.get(
            "findings"
        ) != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}:
            raise ActivationV11Error("accepted predecessor envelope is invalid")
    _verify_hud_v8_closure(project)


def _verify_hud_v8_closure(project: Path) -> None:
    manifest = _strict_json(project / HUD_V8_ACCEPTED_ROOTS[1][0])
    if (
        manifest.get("schema") != "onyx.hud-orb.v8.candidate"
        or manifest.get("candidate") != "hud-orb-v8-voice-reactive-candidate-001"
        or manifest.get("default_off") is not True
        or manifest.get("live_activated") is not False
    ):
        raise ActivationV11Error("accepted HUD V8 manifest contract drift")
    records = manifest.get("artifacts")
    if type(records) is not list or len(records) != len(HUD_V8_ARTIFACT_PATHS):
        raise ActivationV11Error("accepted HUD V8 artifact closure is incomplete")
    normalized: list[dict[str, str]] = []
    for index, record in enumerate(records):
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise ActivationV11Error("accepted HUD V8 artifact record is invalid")
        relative = record["path"]
        expected = record["sha256"]
        if relative != HUD_V8_ARTIFACT_PATHS[index]:
            raise ActivationV11Error("accepted HUD V8 artifact membership drift")
        _verify_file(project, Path(relative), expected)
        normalized.append({"path": relative, "sha256": expected})
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n"
        for record in sorted(normalized, key=lambda record: record["path"])
    ).encode()
    root = hashlib.sha256(material).hexdigest()
    if (
        root != HUD_V8_ARTIFACT_ROOT_SHA256
        or manifest.get("artifact_root_sha256") != root
    ):
        raise ActivationV11Error("accepted HUD V8 artifact root drift")
    anchors = manifest.get("frozen_anchors")
    if type(anchors) is not dict or len(anchors) != 2:
        raise ActivationV11Error("accepted HUD V8 anchor closure is incomplete")
    for relative, expected in anchors.items():
        _verify_file(project, Path(relative), expected)


def _load_accepted_hud_v8(
    project: Path,
    accepted_v7_module: ModuleType,
) -> tuple[ModuleType, FunctionType, FunctionType]:
    """Load the accepted V8 bytes and bind the exact V10-installed V7 registry."""

    expected_path = _verify_file(
        project,
        HUD_V8_ACCEPTED_ROOTS[0][0],
        HUD_V8_ACCEPTED_ROOTS[0][1],
    ).resolve()
    if (
        not isinstance(accepted_v7_module, ModuleType)
        or accepted_v7_module.__name__ != "_onyx_v10_verified_hud_v7"
    ):
        raise ActivationV11Error("V10-installed HUD V7 authority is unavailable")
    module_name = "_onyx_v11_verified_hud_v8"
    namespace = runpy.run_path(str(expected_path), run_name=module_name)
    install_hud = namespace.get("install_candidate")
    uninstall_hud = namespace.get("uninstall_candidate")
    if type(install_hud) is FunctionType and type(uninstall_hud) is FunctionType:
        install_hud.__globals__["hud_v7"] = accepted_v7_module
        uninstall_hud.__globals__["hud_v7"] = accepted_v7_module
    namespace["hud_v7"] = accepted_v7_module
    module = ModuleType(module_name)
    module.__file__ = str(expected_path)
    module.__dict__.update(namespace)
    if (
        type(install_hud) is not FunctionType
        or type(uninstall_hud) is not FunctionType
        or install_hud.__module__ != module_name
        or uninstall_hud.__module__ != module_name
        or Path(install_hud.__code__.co_filename).resolve() != expected_path
        or Path(uninstall_hud.__code__.co_filename).resolve() != expected_path
        or install_hud.__globals__.get("hud_v7") is not accepted_v7_module
    ):
        raise ActivationV11Error("accepted HUD V8 in-memory API failed authentication")
    return module, install_hud, uninstall_hud


def _install_accepted_hud_v8(
    ui_module: ModuleType,
    accepted_v7_module: ModuleType,
    install_hud: FunctionType,
) -> bool:
    """Bridge only V10's hash-loaded private module name into V8 authentication."""

    record = accepted_v7_module._ACTIVE_INSTALLATIONS.get(id(ui_module))
    marker = getattr(ui_module, "_ONYX_HUD_V7_INSTALLATION", None)
    host = getattr(ui_module, "_CinematicHudV5Host", None)
    if (
        record is None
        or record.ui_module is not ui_module
        or record.installed_host is not host
        or marker is not accepted_v7_module._INSTALLATION_TOKEN
        or not isinstance(host, type)
        or host.__module__ != accepted_v7_module.__name__
        or host.__qualname__
        != "install_candidate.<locals>._CinematicHudV7Host"
    ):
        raise ActivationV11Error("private V10 HUD V7 bridge authentication failed")
    original_module = host.__module__
    try:
        host.__module__ = "core.onyx_hud_orb_v7"
        return install_hud(ui_module)
    finally:
        host.__module__ = original_module


def _verify_runtime_bundle(project: Path) -> dict[str, Path]:
    manifest_path = _verify_file(
        project, RUNTIME_MANIFEST_RELATIVE, RUNTIME_MANIFEST_SHA256
    )
    manifest = _strict_json(manifest_path)
    if (
        manifest.get("schema") != "onyx.live-activation.v11.runtime"
        or manifest.get("candidate") != "onyx-live-activation-v11-c001"
    ):
        raise ActivationV11Error("V11 runtime manifest schema mismatch")
    expected_names = {
        "pythonw": Path(".venv/Scripts/pythonw.exe"),
        "bootstrap": BOOTSTRAP_RELATIVE,
        "launcher": CANONICAL_LAUNCHER_RELATIVE,
    }
    files = manifest.get("files")
    if type(files) is not dict or set(files) != set(expected_names):
        raise ActivationV11Error("V11 runtime file closure is incomplete")
    verified: dict[str, Path] = {}
    for name, relative in expected_names.items():
        record = files[name]
        if (
            type(record) is not dict
            or record.get("path") != relative.as_posix()
            or type(record.get("sha256")) is not str
        ):
            raise ActivationV11Error(f"V11 runtime record mismatch: {name}")
        if name == "pythonw" and getattr(sys, "frozen", False):
            # A native PyInstaller release has no source-checkout virtualenv.
            # Its authenticated runtime is the bootloader executable itself;
            # the bootstrap and launcher remain verified against the accepted
            # V11 manifest below.
            executable = Path(sys.executable).resolve()
            if executable.is_symlink() or not executable.is_file():
                raise ActivationV11Error("frozen Onyx executable is unavailable")
            verified[name] = executable
            continue
        verified[name] = _verify_file(project, relative, record["sha256"])
    return verified


@dataclass(frozen=True, slots=True)
class ActivationFlagsV11:
    master: bool
    hud_v8: bool
    base: v10.ActivationFlagsV10

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.hud_v8) is not bool
            or not self.master
            or not self.hud_v8
            or type(self.base) is not v10.ActivationFlagsV10
        ):
            raise ActivationV11Error("complete exact V11 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV11":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV11Error("rollback is not an active V11 configuration")
        if source.get(LIVE_MASTER_FLAG) != "1" or source.get(HUD_V8_FLAG) != "1":
            raise ActivationV11Error("activation environment is not canonical V11")
        try:
            base = v10.ActivationFlagsV10.from_canonical_environ(source)
        except v10.ActivationV10Error as exc:
            raise ActivationV11Error("accepted V10 environment is incomplete") from exc
        return cls(True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v10.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[HUD_V8_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v10_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    result = dict(os.environ if environ is None else environ)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(HUD_V8_FLAG, None)
    result.update(v10.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class ShortcutSpecV11:
    link: str
    target: str
    arguments: str
    working_directory: str
    icon: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ActivationV11Error("shortcut fields must be non-empty strings")
        if Path(self.arguments).name != BOOTSTRAP_RELATIVE.name:
            raise ActivationV11Error("shortcut must target the V11 bootstrap")


@dataclass(frozen=True, slots=True)
class HostContractV11:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    project: Path
    base: v10.HostContractV10


@dataclass(frozen=True, slots=True)
class _RollbackAuthorityV11:
    controller: object
    main_window: type
    hud_module: ModuleType
    uninstall_hud: FunctionType
    shortcut_v10: object | None = None


_ROLLBACK_AUTHORITIES: dict[int, _RollbackAuthorityV11] = {}


def preflight_host(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> HostContractV11:
    source = os.environ if environ is None else environ
    ActivationFlagsV11.from_canonical_environ(source)
    project = Path(module.__file__).resolve().parent
    _verify_accepted_roots(project)
    _verify_runtime_bundle(project)
    base = v10.preflight_host(module, v10.exact_activation_environment())
    return HostContractV11(module, base.ui_module, base.main_window, project, base)


def verify_activation_prerequisites(
    project: Path, environ: Mapping[str, str] | None = None
) -> None:
    ActivationFlagsV11.from_canonical_environ(
        os.environ if environ is None else environ
    )
    _verify_accepted_roots(project)
    _verify_runtime_bundle(project)
    v10.verify_activation_prerequisites(
        project, v10.exact_activation_environment()
    )


class OnyxLiveActivationV11:
    """Exact accepted V10 C003 plus HUD V8 and its canonical shortcut seam."""

    BASE_SEAM_COUNT = v10.OnyxLiveActivationV10.TOTAL_SEAM_COUNT
    V11_SEAM_COUNT = 2
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V11_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV11,
        contract: HostContractV11,
        **v10_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV11 or type(contract) is not (
            HostContractV11
        ):
            raise ActivationV11Error("exact V11 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v10.OnyxLiveActivationV10(
            flags.base, contract.base, **v10_options
        )
        self._hud_v8_module: ModuleType | None = None
        self._shortcut_v10: object | None = None

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def wiring_controller(self) -> object:
        return self._base.wiring_controller

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _source_shortcut_spec(self, instance: object) -> ShortcutSpecV11:
        verified = _verify_runtime_bundle(self.contract.project)
        desktop = instance._desktop_path("Windows")
        icon = self.contract.project / "config" / "onyx.ico"
        return ShortcutSpecV11(
            link=str(desktop / "Onyx.lnk"),
            target=str(verified["pythonw"]),
            arguments=str(verified["bootstrap"]),
            working_directory=str(self.contract.project),
            icon=str(icon),
        )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV11Error("seam failpoint is outside V11 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        if base_failpoint is not None:
            return
        try:
            if id(self) in _ROLLBACK_AUTHORITIES:
                raise ActivationV11Error("V11 rollback authority already exists")
            accepted_v7 = self._base._hud_v7_module
            hud_v8, install_hud, uninstall_hud = _load_accepted_hud_v8(
                self.contract.project, accepted_v7
            )
            if (
                _install_accepted_hud_v8(
                    self.contract.ui_module,
                    accepted_v7,
                    install_hud,
                )
                is not True
            ):
                raise ActivationV11Error("HUD V8 installation was not exact")
            self._hud_v8_module = hud_v8
            authority = _RollbackAuthorityV11(
                controller=self,
                main_window=self.contract.main_window,
                hud_module=hud_v8,
                uninstall_hud=uninstall_hud,
            )
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV11Error("injected V11 HUD V8 seam failure")

            window_type = self.contract.main_window
            original_shortcut = window_type._create_desktop_shortcut
            activation = self

            def create_desktop_shortcut(instance: object) -> None:
                if (
                    activation.contract.ui_module.is_frozen()
                    or platform.system() != "Windows"
                ):
                    original_shortcut(instance)
                    return
                try:
                    spec = activation._source_shortcut_spec(instance)
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
                        "SYS: Desktop shortcut created for Onyx Live V11."
                    )
                except Exception as exc:
                    instance._log.append_log(
                        f"ERR: Shortcut failed safely ({type(exc).__name__})."
                    )

            window_type._create_desktop_shortcut = create_desktop_shortcut
            self._shortcut_v10 = original_shortcut
            authority = _RollbackAuthorityV11(
                controller=self,
                main_window=window_type,
                hud_module=hud_v8,
                uninstall_hud=uninstall_hud,
                shortcut_v10=original_shortcut,
            )
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV11Error("injected V11 shortcut seam failure")
        except Exception:
            self.rollback_installation()
            raise

    def rollback_installation(self) -> None:
        """Remove V11 only and leave the exact accepted V10 installed."""

        errors: list[Exception] = []
        authority = _ROLLBACK_AUTHORITIES.pop(id(self), None)
        if authority is not None and (
            type(authority) is not _RollbackAuthorityV11
            or authority.controller is not self
            or authority.main_window is not self.contract.main_window
        ):
            errors.append(ActivationV11Error("V11 rollback authority drift denied"))
            authority = None
        if authority is None and any(
            value is not None
            for value in (self._hud_v8_module, self._shortcut_v10)
        ):
            errors.append(ActivationV11Error("V11 rollback authority is unavailable"))
        if authority is not None and authority.shortcut_v10 is not None:
            self.contract.main_window._create_desktop_shortcut = (
                authority.shortcut_v10
            )
        self._shortcut_v10 = None
        if authority is not None:
            try:
                if authority.uninstall_hud(self.contract.ui_module) is not True:
                    raise ActivationV11Error("HUD V8 rollback was not exact")
            except Exception as exc:
                errors.append(exc)
        self._hud_v8_module = None
        restored = restore_v10_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v11", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v11")
        if errors:
            raise ActivationV11Error(
                "V11 rollback completed with authority error"
            ) from errors[0]

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV11:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV11.from_canonical_environ(source)
    controller = OnyxLiveActivationV11(flags, preflight_host(module, source))
    controller.install()
    module._onyx_live_activation_v11 = controller
    return controller


__all__ = [
    "ActivationFlagsV11",
    "ActivationV11Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HUD_V8_FLAG",
    "HostContractV11",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV11",
    "RUNTIME_MANIFEST_RELATIVE",
    "ShortcutSpecV11",
    "activate_main",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v10_environment",
    "verify_activation_prerequisites",
]
