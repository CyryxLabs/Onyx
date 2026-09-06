"""Default-off composition of accepted V9 and Phase 6 Live Wiring V1.

V10 changes no accepted byte. It activates the exact accepted V9 controller,
extracts its embedded exact V7 authority, installs the accepted lifecycle
wiring, and then replaces only the V9 source-checkout shortcut/setup seams with
the canonical V10 bootstrap.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import runpy
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import FunctionType, ModuleType
from typing import Any, Final

from core import onyx_live_activation_v7 as v7
from core import onyx_live_activation_v9 as v9
from core import phase6_live_wiring_v1 as wiring


LIVE_MASTER_FLAG: Final = "ONYX_LIVE_ACTIVATION_V10"
LIVE_ROLLBACK_FLAG: Final = "ONYX_LIVE_ROLLBACK_V10"
WIRING_FLAG: Final = wiring.FEATURE_FLAG
WIRING_VALUE: Final = "true"
HUD_V7_FLAG: Final = "ONYX_HUD_V7_LIVE"
VALID_OS_SYSTEMS: Final = frozenset({"windows", "mac", "linux"})
OWNER_PLACEHOLDERS: Final = frozenset(
    {
        "",
        "sir",
        "efendim",
        "guest",
        "name",
        "owner",
        "placeholder",
        "unknown",
        "user",
        "your name",
    }
)
BOOTSTRAP_RELATIVE = Path("scripts/bootstrap_onyx_live_v10.pyw")
CANONICAL_LAUNCHER_RELATIVE = Path("scripts/launch_onyx_live_v10.pyw")
RUNTIME_MANIFEST_RELATIVE = Path(
    "docs/onyx/checkpoints/onyx-live-activation-v10/runtime-manifest.json"
)
STATE_ROOT_RELATIVE = Path("runtime/phase6-live-wiring-v1")
LEGACY_LAUNCHERS = frozenset(
    {
        "launch_onyx.pyw",
        "launch_onyx_live_v7.pyw",
        "launch_onyx_live_v8.pyw",
        "launch_onyx_live_v9.pyw",
        "bootstrap_onyx_live_v8.pyw",
        "bootstrap_onyx_live_v9.pyw",
    }
)

ACCEPTED_ROOTS = (
    (
        Path("docs/onyx/checkpoints/onyx-live-activation-v9/manifest.json"),
        "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a",
    ),
    (
        Path("docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.md"),
        "91a3613df269d1fe222c437b92b0d3022f3f2a603ae9689a951e63e0c4e4f0ec",
    ),
    (
        Path("docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V9-E6-001.manifest.json"),
        "bb8a3e88b6db05b548a306aba3e2c09bdd3b0f760777d34a64326e8820743cbd",
    ),
    (
        Path("docs/onyx/checkpoints/phase6-live-wiring-v1/manifest.json"),
        "d98cdd73ae056e3afe5eac2976565d8b301fb1410a8b0498f04c6f7e8c2db6ee",
    ),
    (
        Path("docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.md"),
        "51c542420b55f58409fba1b9a5efe753fb9aabdfebd1bc5e3ab2b9abf1f15dd7",
    ),
    (
        Path("docs/onyx/acceptance/VE-P6-LIVE-WIRING-V1-E6-001.manifest.json"),
        "8e4f139033bd8450a7f4c3c325363e57166bb7d0de3d5f5e6baf4f6817e8088c",
    ),
    (
        Path("docs/onyx/checkpoints/phase5-exit-candidate-v2/manifest.json"),
        "b2cf8d781fc1f72a375be444c24ad74c4e59b910adab765a48c7c7b59ae15d2b",
    ),
    (
        Path("docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.md"),
        "052426cc0d62aad20af4ee8f1810d0729698fb0dd74e95cb76c1bbf0f50404d3",
    ),
    (
        Path("docs/onyx/acceptance/VE-P5-EXIT-CANDIDATE-V2-E6-001.manifest.json"),
        "db41fff1130f4991f6e6f3da9811f6a8877a408a17ffef809f41eb128704392c",
    ),
)

HUD_V7_ACCEPTED_PATHS: Final = (
    Path("core/onyx_hud_orb_v7.py"),
    Path("docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json"),
    Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md"),
    Path("docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json"),
)
HUD_V7_ARTIFACT_ROOT_SHA256: Final = (
    "5e0f16fcbf6885ed20b3bf3967a2af24b1d8dc4d174c0fdb7b0f5b78855aafe4"
)
HUD_V7_ARTIFACT_PATHS: Final = (
    "core/onyx_hud_orb_v7.py",
    "docs/onyx/checkpoints/hud-orb-v7-candidate/HUD_ORB_V7_CHECKPOINT.md",
    "docs/onyx/checkpoints/hud-orb-v7-candidate/hud-orb-v7-c003-1440x900.png",
    "docs/onyx/checkpoints/hud-orb-v7-candidate/hud-orb-v7-c003.metrics.json",
    "docs/onyx/rejections/HUD_ORB_V6_VISUAL_REJECTION.md",
    "qml/OnyxLiveShellV7.qml",
    "qml/components/OnyxOrbEntityV7.qml",
    "scripts/capture_hud_orb_v7_evidence.py",
    "scripts/verify_hud_orb_v7_candidate.py",
    "tests/test_onyx_hud_orb_v7_candidate.py",
)


def bind_hud_v7_accepted_roots(
    digests: Mapping[str, str],
    *,
    allow_unbound: bool = False,
) -> tuple[tuple[Path, str], ...]:
    """Bind exactly the four reviewed HUD V7 artifacts without discovery."""

    expected = tuple(path.as_posix() for path in HUD_V7_ACCEPTED_PATHS)
    if type(digests) is not dict or tuple(digests) != expected:
        raise ActivationV10Error("HUD V7 binding must contain four exact ordered paths")
    roots: list[tuple[Path, str]] = []
    for path in HUD_V7_ACCEPTED_PATHS:
        digest = digests[path.as_posix()]
        if allow_unbound and digest == "UNBOUND":
            roots.append((path, digest))
            continue
        if (
            type(digest) is not str
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ActivationV10Error(f"invalid HUD V7 binding: {path}")
        roots.append((path, digest))
    return tuple(roots)


# C002 binds the independently accepted C003 HUD closure by four exact paths;
# no directory or acceptance-record discovery participates in activation.
HUD_V7_ACCEPTED_ROOTS = bind_hud_v7_accepted_roots(
    {
        "core/onyx_hud_orb_v7.py": (
            "31fd7d0df7413ac9dbba3db463de28390bdfaa75e2173dae54c04dfd82a6c150"
        ),
        "docs/onyx/checkpoints/hud-orb-v7-candidate/manifest.json": (
            "38f77492b6b72eeb8bff8c1bddbe129081bbe79e67b7f8679054d86dff781f03"
        ),
        "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.md": (
            "1ef23e14d42a9ff199115cbf1615e68318b492978487d90a1b6cc61c74a32a3d"
        ),
        "docs/onyx/acceptance/VE-HUD-ORB-V7-C003-E6-001.manifest.json": (
            "ef17dfcdb63ebd3b48dcfcb1feb2c0b76a300bd86ff7ae3cdbbae87f94118500"
        ),
    },
)

RUNTIME_MANIFEST_SHA256 = (
    "190156fdb78158a8685c08d4751471346ac49b5c8d7184ce236a2c32080f36ba"
)
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

VERSION_CONTROL_FLAGS = tuple(
    name
    for version in range(1, 11)
    for name in (
        f"ONYX_LIVE_ACTIVATION_V{version}",
        f"ONYX_LIVE_ROLLBACK_V{version}",
    )
)
CONTROL_FLAGS = (
    *VERSION_CONTROL_FLAGS,
    WIRING_FLAG,
    HUD_V7_FLAG,
    *v9.CONTROL_FLAGS,
)


class ActivationV10Error(RuntimeError):
    """The accepted V10 composition or runtime closure was not exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_file(project: Path, relative: Path) -> Path:
    pure = PurePosixPath(relative.as_posix())
    if pure.is_absolute() or ".." in pure.parts or str(pure) != relative.as_posix():
        raise ActivationV10Error("noncanonical V10 path")
    path = project.joinpath(*pure.parts)
    if path.is_symlink() or not path.is_file():
        raise ActivationV10Error(f"required V10 file is unavailable: {relative}")
    try:
        path.resolve().relative_to(project.resolve())
    except ValueError as exc:
        raise ActivationV10Error(f"V10 path escapes project: {relative}") from exc
    return path


def _verify_file(project: Path, relative: Path, expected: str) -> Path:
    if (
        type(expected) is not str
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ActivationV10Error(f"unbound acceptance/hash root: {relative}")
    path = _canonical_file(project, relative)
    if _sha256(path) != expected:
        raise ActivationV10Error(f"V10 evidence drift: {relative}")
    return path


def _verify_accepted_roots(project: Path) -> None:
    for relative, digest in ACCEPTED_ROOTS:
        _verify_file(project, relative, digest)
    for relative, digest in HUD_V7_ACCEPTED_ROOTS:
        _verify_file(project, relative, digest)
    _verify_hud_v7_closure(project)


def _load_accepted_hud_v7(
    project: Path,
) -> tuple[ModuleType, FunctionType, FunctionType]:
    """Execute a fresh hash-bound HUD namespace, ignoring ``sys.modules``."""

    expected_path = _verify_file(
        project,
        HUD_V7_ACCEPTED_PATHS[0],
        dict(HUD_V7_ACCEPTED_ROOTS)[HUD_V7_ACCEPTED_PATHS[0]],
    ).resolve()
    module_name = "_onyx_v10_verified_hud_v7"
    namespace = runpy.run_path(str(expected_path), run_name=module_name)
    module = ModuleType(module_name)
    module.__file__ = str(expected_path)
    module.__dict__.update(namespace)
    install_hud = namespace.get("install_candidate")
    uninstall_hud = namespace.get("uninstall_candidate")
    if (
        type(install_hud) is not FunctionType
        or type(uninstall_hud) is not FunctionType
        or install_hud.__module__ != module_name
        or uninstall_hud.__module__ != module_name
        or Path(install_hud.__code__.co_filename).resolve() != expected_path
        or Path(uninstall_hud.__code__.co_filename).resolve() != expected_path
    ):
        raise ActivationV10Error("accepted HUD V7 in-memory API failed authentication")
    return module, install_hud, uninstall_hud


def _strict_json(path: Path) -> dict[str, object]:
    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ActivationV10Error(f"duplicate runtime-manifest key: {key}")
            result[key] = value
        return result

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ActivationV10Error("runtime manifest is unreadable") from exc
    if type(payload) is not dict:
        raise ActivationV10Error("runtime manifest must be an object")
    return payload


def _verify_hud_v7_closure(project: Path) -> None:
    manifest_path = _verify_file(
        project,
        HUD_V7_ACCEPTED_PATHS[1],
        dict(HUD_V7_ACCEPTED_ROOTS)[HUD_V7_ACCEPTED_PATHS[1]],
    )
    manifest = _strict_json(manifest_path)
    if (
        manifest.get("schema") != "onyx.hud-orb.v7.candidate"
        or manifest.get("candidate") != "hud-orb-v7-cinematic-candidate-003"
        or manifest.get("default_off") is not True
        or manifest.get("live_activated") is not False
        or manifest.get("artifact_root_algorithm")
        != "sha256-sorted-path-nul-digest-lf-v1"
    ):
        raise ActivationV10Error("accepted HUD V7 manifest contract drift")
    records = manifest.get("artifacts")
    if type(records) is not list or len(records) != len(HUD_V7_ARTIFACT_PATHS):
        raise ActivationV10Error("accepted HUD V7 artifact closure is incomplete")
    normalized: list[dict[str, str]] = []
    for index, record in enumerate(records):
        if type(record) is not dict or set(record) != {"path", "sha256"}:
            raise ActivationV10Error("accepted HUD V7 artifact record is invalid")
        relative = record["path"]
        expected_digest = record["sha256"]
        if relative != HUD_V7_ARTIFACT_PATHS[index]:
            raise ActivationV10Error("accepted HUD V7 artifact membership drift")
        _verify_file(project, Path(relative), expected_digest)
        normalized.append({"path": relative, "sha256": expected_digest})
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n"
        for record in sorted(normalized, key=lambda record: record["path"])
    ).encode()
    root = hashlib.sha256(material).hexdigest()
    if (
        root != HUD_V7_ARTIFACT_ROOT_SHA256
        or manifest.get("artifact_root_sha256") != root
    ):
        raise ActivationV10Error("accepted HUD V7 artifact root drift")
    anchors = manifest.get("frozen_anchors")
    if type(anchors) is not dict or len(anchors) != 7:
        raise ActivationV10Error("accepted HUD V7 anchor closure is incomplete")
    for relative, expected_digest in anchors.items():
        if type(relative) is not str or type(expected_digest) is not str:
            raise ActivationV10Error("accepted HUD V7 anchor record is invalid")
        _verify_file(project, Path(relative), expected_digest)


def _verify_runtime_bundle(project: Path) -> dict[str, Path]:
    manifest_path = _verify_file(
        project, RUNTIME_MANIFEST_RELATIVE, RUNTIME_MANIFEST_SHA256
    )
    manifest = _strict_json(manifest_path)
    if (
        manifest.get("schema") != "onyx.live-activation.v10.runtime"
        or manifest.get("candidate") != "onyx-live-activation-v10-c003"
        or manifest.get("onboarding")
        != {
            "secure_unknown_owner_ready": True,
            "credential_required": True,
            "valid_os_required": True,
            "unreadable_config_denied": True,
            "fallback_address": "Sir",
        }
    ):
        raise ActivationV10Error("runtime manifest schema mismatch")
    files = manifest.get("files")
    expected_names = {
        "pythonw": Path(".venv/Scripts/pythonw.exe"),
        "bootstrap": BOOTSTRAP_RELATIVE,
        "launcher": CANONICAL_LAUNCHER_RELATIVE,
    }
    if type(files) is not dict or set(files) != set(expected_names):
        raise ActivationV10Error("runtime manifest file closure is incomplete")
    verified: dict[str, Path] = {}
    for name, expected_relative in expected_names.items():
        record = files[name]
        if type(record) is not dict:
            raise ActivationV10Error("runtime manifest record must be an object")
        if record.get("path") != expected_relative.as_posix():
            raise ActivationV10Error(f"runtime path mismatch: {name}")
        digest = record.get("sha256")
        if type(digest) is not str:
            raise ActivationV10Error(f"runtime hash missing: {name}")
        if name == "pythonw" and getattr(sys, "frozen", False):
            # Native releases execute through the PyInstaller bootloader and
            # intentionally do not ship a development virtual environment.
            executable = Path(sys.executable).resolve()
            if executable.is_symlink() or not executable.is_file():
                raise ActivationV10Error("frozen Onyx executable is unavailable")
            verified[name] = executable
            continue
        verified[name] = _verify_file(project, expected_relative, digest)
    return verified


def _path_is_linked(path: Path) -> bool:
    metadata = path.lstat()
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _prepare_state_root(project: Path) -> Path:
    root = project / STATE_ROOT_RELATIVE
    if not project.is_absolute() or _path_is_linked(project):
        raise ActivationV10Error("project root is linked or unavailable")
    current = root
    while not current.exists():
        if current.parent == current:
            raise ActivationV10Error("state root has no existing ancestor")
        current = current.parent
    while True:
        if _path_is_linked(current):
            raise ActivationV10Error("state-root ancestry uses a reparse point")
        if current == project:
            break
        if current.parent == current:
            raise ActivationV10Error("state root escapes project")
        current = current.parent
    root.mkdir(parents=True, exist_ok=True)
    if (
        not root.is_dir()
        or _path_is_linked(root)
        or root.resolve() != (project.resolve() / STATE_ROOT_RELATIVE)
    ):
        raise ActivationV10Error("state root is not canonical")
    return root


@dataclass(frozen=True, slots=True)
class ActivationFlagsV10:
    master: bool
    wiring: bool
    hud_v7: bool
    base: v9.ActivationFlagsV9

    def __post_init__(self) -> None:
        if (
            type(self.master) is not bool
            or type(self.wiring) is not bool
            or type(self.hud_v7) is not bool
            or not self.master
            or not self.wiring
            or not self.hud_v7
            or type(self.base) is not v9.ActivationFlagsV9
        ):
            raise ActivationV10Error("complete exact V10 flags are required")

    @classmethod
    def from_canonical_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ActivationFlagsV10":
        source = os.environ if environ is None else environ
        if source.get(LIVE_ROLLBACK_FLAG) is not None:
            raise ActivationV10Error("rollback is not an active V10 configuration")
        if (
            source.get(LIVE_MASTER_FLAG) != "1"
            or source.get(WIRING_FLAG) != WIRING_VALUE
            or source.get(HUD_V7_FLAG) != "1"
        ):
            raise ActivationV10Error("activation environment is not canonical V10")
        try:
            base = v9.ActivationFlagsV9.from_canonical_environ(source)
        except v9.ActivationV9Error as exc:
            raise ActivationV10Error("accepted V9 environment is incomplete") from exc
        return cls(True, True, True, base)


def exact_activation_environment() -> dict[str, str]:
    result = v9.exact_activation_environment()
    result[LIVE_MASTER_FLAG] = "1"
    result[WIRING_FLAG] = WIRING_VALUE
    result[HUD_V7_FLAG] = "1"
    return result


def exact_rollback_environment() -> dict[str, str]:
    return {LIVE_ROLLBACK_FLAG: "1"}


def restore_v9_environment(
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source = os.environ if environ is None else environ
    result = dict(source)
    result.pop(LIVE_MASTER_FLAG, None)
    result.pop(LIVE_ROLLBACK_FLAG, None)
    result.pop(WIRING_FLAG, None)
    result.pop(HUD_V7_FLAG, None)
    result.update(v9.exact_activation_environment())
    return result


@dataclass(frozen=True, slots=True)
class ShortcutSpecV10:
    link: str
    target: str
    arguments: str
    working_directory: str
    icon: str

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not str or not value:
                raise ActivationV10Error("shortcut fields must be non-empty strings")
        if Path(self.arguments).name != BOOTSTRAP_RELATIVE.name:
            raise ActivationV10Error("shortcut must target the V10 bootstrap")
        if Path(self.arguments).name in LEGACY_LAUNCHERS:
            raise ActivationV10Error("legacy/V7/V8/V9 shortcut is forbidden")


@dataclass(frozen=True, slots=True)
class HostContractV10:
    module: ModuleType
    ui_module: ModuleType
    main_window: type
    project: Path
    base: v9.HostContractV9


@dataclass(frozen=True, slots=True)
class _RollbackAuthorityV10:
    controller: object
    main_window: type
    hud_module: ModuleType
    uninstall_hud: FunctionType
    wiring_controller: wiring.Phase6LiveWiringV1 | None = None
    shortcut_v9: object | None = None
    setup_v9: object | None = None
    check_config_v9: object | None = None
    init_v9: object | None = None


_ROLLBACK_AUTHORITIES: dict[int, _RollbackAuthorityV10] = {}


def _refresh_configured_shortcut(instance: object) -> None:
    """Refresh the canonical shortcut for already-configured owners."""

    if getattr(instance, "_ready", False) and not getattr(instance, "_overlay", None):
        instance._create_desktop_shortcut()


def _secure_onboarding_ready(
    ui_module: ModuleType,
    original_check: object,
    instance: object,
) -> bool:
    """Accept reconciled unknown-owner state without weakening secure setup."""

    if not callable(original_check):
        return False
    try:
        if original_check(instance) is True:
            return True
        from core import credentials

        status = credentials.status()
        if type(status) is not dict or status.get("configured") is not True:
            return False
        config_path = Path(ui_module.API_FILE)
        settings, _identity = credentials._read_config_object(config_path)
        os_system = settings.get("os_system")
        owner_name = settings.get("owner_name", "")
        if type(os_system) is not str or type(owner_name) is not str:
            return False
        if os_system.strip().casefold() not in VALID_OS_SYSTEMS:
            return False
        owner_value = " ".join(owner_name.split()).casefold()
        return owner_value in OWNER_PLACEHOLDERS
    except Exception:
        return False


def preflight_host(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> HostContractV10:
    source = os.environ if environ is None else environ
    ActivationFlagsV10.from_canonical_environ(source)
    project = Path(module.__file__).resolve().parent
    _verify_accepted_roots(project)
    _verify_runtime_bundle(project)
    base = v9.preflight_host(module, v9.exact_activation_environment())
    return HostContractV10(module, base.ui_module, base.main_window, project, base)


def verify_activation_prerequisites(
    project: Path, environ: Mapping[str, str] | None = None
) -> None:
    """Verify all evidence before importing the live host or creating state."""

    source = os.environ if environ is None else environ
    ActivationFlagsV10.from_canonical_environ(source)
    _verify_accepted_roots(project)
    _verify_runtime_bundle(project)


class OnyxLiveActivationV10:
    """Accepted V9, HUD V7, wiring and four V10 surface/onboarding seams."""

    BASE_SEAM_COUNT = v9.OnyxLiveActivationV9.TOTAL_SEAM_COUNT
    HUD_V7_SEAM_COUNT = 1
    WIRING_SEAM_COUNT = len(wiring.Phase6LiveWiringV1.PATCHED_SEAMS)
    V10_SEAM_COUNT = HUD_V7_SEAM_COUNT + WIRING_SEAM_COUNT + 4
    TOTAL_SEAM_COUNT = BASE_SEAM_COUNT + V10_SEAM_COUNT

    def __init__(
        self,
        flags: ActivationFlagsV10,
        contract: HostContractV10,
        **v9_options: Any,
    ) -> None:
        if type(flags) is not ActivationFlagsV10 or type(contract) is not (
            HostContractV10
        ):
            raise ActivationV10Error("exact V10 flags and host contract are required")
        self.flags = flags
        self.contract = contract
        self._base = v9.OnyxLiveActivationV9(flags.base, contract.base, **v9_options)
        self._wiring: wiring.Phase6LiveWiringV1 | None = None
        self._hud_v7_module: ModuleType | None = None
        self._shortcut_v9: object | None = None
        self._setup_v9: object | None = None
        self._check_config_v9: object | None = None
        self._init_v9: object | None = None

    @property
    def state(self) -> object:
        return self._base.state

    @property
    def wiring_controller(self) -> wiring.Phase6LiveWiringV1 | None:
        return self._wiring

    def __getattr__(self, name: str) -> object:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._base, name)

    def _embedded_v7(self) -> v7.OnyxLiveActivationV7:
        activation = self._base._base._base
        if type(activation) is not v7.OnyxLiveActivationV7:
            raise ActivationV10Error("embedded V7 activation type diverged")
        return activation

    def _source_shortcut_spec(self, instance: object) -> ShortcutSpecV10:
        verified = _verify_runtime_bundle(self.contract.project)
        bootstrap = verified["bootstrap"]
        launcher = verified["launcher"]
        target = verified["pythonw"]
        if bootstrap.name in LEGACY_LAUNCHERS or launcher.name in LEGACY_LAUNCHERS:
            raise ActivationV10Error("V10 bundle selected an obsolete entrypoint")
        desktop = instance._desktop_path("Windows")
        icon = self.contract.project / "config" / "onyx.ico"
        return ShortcutSpecV10(
            link=str(desktop / "Onyx.lnk"),
            target=str(target),
            arguments=str(bootstrap),
            working_directory=str(self.contract.project),
            icon=str(icon),
        )

    def install(self, *, fail_after: int | None = None) -> None:
        if fail_after is not None and not (1 <= fail_after <= self.TOTAL_SEAM_COUNT):
            raise ActivationV10Error("seam failpoint is outside V10 installation")
        base_failpoint = (
            fail_after if fail_after and fail_after <= self.BASE_SEAM_COUNT else None
        )
        self._base.install(fail_after=base_failpoint)
        if base_failpoint is not None:
            return
        self._base.start()
        try:
            if id(self) in _ROLLBACK_AUTHORITIES:
                raise ActivationV10Error("V10 rollback authority already exists")
            hud_v7, install_hud, uninstall_hud = _load_accepted_hud_v7(
                self.contract.project
            )
            installed = install_hud(self.contract.ui_module)
            if installed is not True:
                raise ActivationV10Error("HUD V7 candidate installation was not exact")
            self._hud_v7_module = hud_v7
            authority = _RollbackAuthorityV10(
                controller=self,
                main_window=self.contract.main_window,
                hud_module=hud_v7,
                uninstall_hud=uninstall_hud,
            )
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == self.BASE_SEAM_COUNT + 1:
                raise ActivationV10Error("injected V10 HUD V7 seam failure")

            root = _prepare_state_root(self.contract.project)
            controller = wiring.create_phase6_live_wiring_v1(
                gate=wiring.LiveWiringFeatureGateV1.from_environ(
                    {WIRING_FLAG: WIRING_VALUE}
                ),
                activation=self._embedded_v7(),
                state_root=root,
            )
            if type(controller) is not wiring.Phase6LiveWiringV1:
                raise ActivationV10Error("exact Wiring V1 controller was not created")
            self._wiring = controller
            authority = replace(authority, wiring_controller=controller)
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            wiring_failpoint = None
            if (
                fail_after is not None
                and self.BASE_SEAM_COUNT + self.HUD_V7_SEAM_COUNT
                < fail_after
                <= self.BASE_SEAM_COUNT
                + self.HUD_V7_SEAM_COUNT
                + self.WIRING_SEAM_COUNT
            ):
                wiring_failpoint = (
                    fail_after - self.BASE_SEAM_COUNT - self.HUD_V7_SEAM_COUNT
                )
            controller.install(fail_after=wiring_failpoint)

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
                        "SYS: Desktop shortcut created for Onyx Live V10."
                    )
                except Exception as exc:
                    instance._log.append_log(
                        f"ERR: Shortcut failed safely ({type(exc).__name__})."
                    )

            window_type._create_desktop_shortcut = create_desktop_shortcut
            self._shortcut_v9 = original_shortcut
            authority = replace(authority, shortcut_v9=original_shortcut)
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == (
                self.BASE_SEAM_COUNT
                + self.HUD_V7_SEAM_COUNT
                + self.WIRING_SEAM_COUNT
                + 1
            ):
                raise ActivationV10Error("injected V10 shortcut seam failure")

            original_setup = window_type._on_setup_done
            v9_setup = self._base._setup_original
            if not callable(v9_setup):
                raise ActivationV10Error("V9 setup authority is unavailable")

            def setup_done(
                instance: object,
                key: str,
                os_name: str,
                owner_name: str = "",
            ) -> None:
                v9_setup(instance, key, os_name, owner_name)
                if getattr(instance, "_ready", False) and not getattr(
                    instance, "_overlay", None
                ):
                    instance._create_desktop_shortcut()

            window_type._on_setup_done = setup_done
            self._setup_v9 = original_setup
            authority = replace(authority, setup_v9=original_setup)
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == (
                self.BASE_SEAM_COUNT
                + self.HUD_V7_SEAM_COUNT
                + self.WIRING_SEAM_COUNT
                + 2
            ):
                raise ActivationV10Error("injected V10 setup seam failure")

            original_check_config = window_type._check_config

            def check_config(instance: object) -> bool:
                return _secure_onboarding_ready(
                    activation.contract.ui_module,
                    original_check_config,
                    instance,
                )

            window_type._check_config = check_config
            self._check_config_v9 = original_check_config
            authority = replace(authority, check_config_v9=original_check_config)
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == (
                self.BASE_SEAM_COUNT
                + self.HUD_V7_SEAM_COUNT
                + self.WIRING_SEAM_COUNT
                + 3
            ):
                raise ActivationV10Error("injected V10 onboarding seam failure")

            original_init = window_type.__init__

            def initialize(instance: object, *args: object, **kwargs: object) -> None:
                original_init(instance, *args, **kwargs)
                if platform.system() == "Windows":
                    _refresh_configured_shortcut(instance)

            window_type.__init__ = initialize
            self._init_v9 = original_init
            authority = replace(authority, init_v9=original_init)
            _ROLLBACK_AUTHORITIES[id(self)] = authority
            if fail_after == self.TOTAL_SEAM_COUNT:
                raise ActivationV10Error("injected V10 configured-owner seam failure")
        except Exception:
            self.rollback_installation()
            raise

    def rollback_installation(self) -> None:
        """Remove V10/Wiring only and leave exact accepted V9 installed."""

        errors: list[Exception] = []
        authority = _ROLLBACK_AUTHORITIES.pop(id(self), None)
        if authority is not None and (
            type(authority) is not _RollbackAuthorityV10
            or authority.controller is not self
            or authority.main_window is not self.contract.main_window
        ):
            errors.append(ActivationV10Error("V10 rollback authority drift denied"))
            authority = None
        if authority is None and any(
            value is not None
            for value in (
                self._hud_v7_module,
                self._wiring,
                self._shortcut_v9,
                self._setup_v9,
                self._check_config_v9,
                self._init_v9,
            )
        ):
            errors.append(ActivationV10Error("V10 rollback authority is unavailable"))
        if authority is not None and authority.init_v9 is not None:
            self.contract.main_window.__init__ = authority.init_v9
        if authority is not None and authority.check_config_v9 is not None:
            self.contract.main_window._check_config = authority.check_config_v9
        if authority is not None and authority.setup_v9 is not None:
            self.contract.main_window._on_setup_done = authority.setup_v9
        if authority is not None and authority.shortcut_v9 is not None:
            self.contract.main_window._create_desktop_shortcut = authority.shortcut_v9
        self._init_v9 = None
        self._check_config_v9 = None
        self._setup_v9 = None
        self._shortcut_v9 = None
        wiring_controller = (
            authority.wiring_controller if authority is not None else None
        )
        if wiring_controller is not None:
            try:
                wiring_controller.rollback_installation()
            except Exception as exc:
                errors.append(exc)
        self._wiring = None
        if authority is not None:
            try:
                if authority.uninstall_hud(self.contract.ui_module) is not True:
                    raise ActivationV10Error("HUD V7 rollback was not exact")
            except Exception as exc:
                errors.append(exc)
        self._hud_v7_module = None
        restored = restore_v9_environment(os.environ)
        os.environ.clear()
        os.environ.update(restored)
        if getattr(self.contract.module, "_onyx_live_activation_v10", None) is self:
            delattr(self.contract.module, "_onyx_live_activation_v10")
        if errors:
            raise ActivationV10Error(
                "V10 rollback completed with authority error"
            ) from (errors[0])

    def rollback_all(self) -> None:
        self.rollback_installation()
        self._base.rollback_all()


def activate_main(
    module: ModuleType, environ: Mapping[str, str] | None = None
) -> OnyxLiveActivationV10:
    source = os.environ if environ is None else environ
    flags = ActivationFlagsV10.from_canonical_environ(source)
    controller = OnyxLiveActivationV10(flags, preflight_host(module, source))
    controller.install()
    module._onyx_live_activation_v10 = controller
    return controller


__all__ = [
    "ActivationFlagsV10",
    "ActivationV10Error",
    "BOOTSTRAP_RELATIVE",
    "CANONICAL_LAUNCHER_RELATIVE",
    "CONTROL_FLAGS",
    "HostContractV10",
    "HUD_V7_FLAG",
    "HUD_V7_ACCEPTED_PATHS",
    "LIVE_MASTER_FLAG",
    "LIVE_ROLLBACK_FLAG",
    "OnyxLiveActivationV10",
    "OWNER_PLACEHOLDERS",
    "RUNTIME_MANIFEST_RELATIVE",
    "STATE_ROOT_RELATIVE",
    "ShortcutSpecV10",
    "VALID_OS_SYSTEMS",
    "WIRING_FLAG",
    "WIRING_VALUE",
    "activate_main",
    "bind_hud_v7_accepted_roots",
    "exact_activation_environment",
    "exact_rollback_environment",
    "preflight_host",
    "restore_v9_environment",
    "verify_activation_prerequisites",
]
