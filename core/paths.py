"""Cross-platform resource and writable-data locations for Onyx.

Source checkouts keep their historical in-repository layout. Frozen releases
read immutable assets from the PyInstaller bundle and write owner data only to
the current user's application-data directory.
"""
from __future__ import annotations

import os
import platform
import stat
import sys
import ctypes
import tempfile
from pathlib import Path


APP_VENDOR = "Cyryx Labs"
APP_NAME = "Onyx"
_POSIX_SYSTEM_NAMESPACE_ROOTS = frozenset(
    {
        "Applications",
        "Library",
        "System",
        "bin",
        "boot",
        "dev",
        "etc",
        "nix",
        "opt",
        "private",
        "proc",
        "run",
        "sbin",
        "srv",
        "sys",
        "usr",
        "var",
    }
)


class PrivateDataPathError(RuntimeError):
    """Raised when a trustworthy per-user private-data root is unavailable."""


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    )


_FOLDERID_LOCAL_APP_DATA = _GUID(
    0xF1B32785,
    0x6FBA,
    0x4FCF,
    (ctypes.c_ubyte * 8)(0x9D, 0x55, 0x7B, 0x8E, 0x7F, 0x15, 0x70, 0x91),
)


def _native_windows_local_app_data() -> Path:
    """Resolve FOLDERID_LocalAppData for the current Windows token."""
    if os.name != "nt":
        raise PrivateDataPathError("Windows Known Folders are unavailable")
    from ctypes import wintypes

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    get_known_folder = shell32.SHGetKnownFolderPath
    get_known_folder.argtypes = (
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.LPWSTR),
    )
    get_known_folder.restype = ctypes.c_long
    free_memory = ole32.CoTaskMemFree
    free_memory.argtypes = (ctypes.c_void_p,)
    free_memory.restype = None

    value = wintypes.LPWSTR()
    result = get_known_folder(
        ctypes.byref(_FOLDERID_LOCAL_APP_DATA), 0, None, ctypes.byref(value)
    )
    try:
        if result < 0 or not value.value:
            raise PrivateDataPathError(
                f"SHGetKnownFolderPath(FOLDERID_LocalAppData) failed: HRESULT 0x{result & 0xFFFFFFFF:08X}"
            )
        candidate = Path(value.value)
        if not candidate.is_absolute():
            raise PrivateDataPathError("Windows Known Folder returned a relative path")
        return candidate
    finally:
        if value:
            free_memory(ctypes.cast(value, ctypes.c_void_p))


def windows_local_app_data_dir() -> Path:
    """Return canonical LocalAppData or fail closed without environment fallback."""
    try:
        return _native_windows_local_app_data()
    except PrivateDataPathError:
        raise
    except (AttributeError, OSError) as exc:
        raise PrivateDataPathError(
            f"canonical LocalAppData resolution failed: {exc}"
        ) from exc


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _absolute_without_link_resolution(path: Path) -> Path:
    """Return an absolute lexical path while preserving link components."""

    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _absolute_posix_configuration(raw: str, *, variable: str) -> Path:
    """Validate one configured POSIX root before lexical normalization."""

    configured = Path(raw).expanduser()
    # Unit/package harnesses can exercise the Linux branch from Windows. Keep
    # POSIX root syntax meaningful there without weakening native validation.
    if os.name == "nt" and raw.startswith("/"):
        return configured
    if not configured.is_absolute():
        raise PrivateDataPathError(f"{variable} must be an absolute path")
    return _absolute_without_link_resolution(configured)


def _reject_posix_filesystem_root_configuration(
    path: Path,
    *,
    variable: str,
) -> None:
    """Reject a configured container that would claim the whole filesystem."""

    if _absolute_without_link_resolution(path) == Path("/"):
        raise PrivateDataPathError(f"{variable} is too broad or sensitive: /")


def _reject_broad_posix_private_root(path: Path) -> None:
    """Reject roots whose permission changes could affect unrelated data."""

    candidate = _absolute_without_link_resolution(path)
    try:
        home = _absolute_without_link_resolution(Path.home())
    except RuntimeError as exc:
        # Cross-platform packaging tests intentionally emulate Linux while
        # clearing a Windows environment. Native POSIX must still fail closed
        # if its account home cannot be resolved.
        if os.name != "nt":
            raise PrivateDataPathError(
                "current-user home cannot be resolved safely"
            ) from exc
        home = Path("/__onyx_unavailable_test_home__")
    temporary = _absolute_without_link_resolution(Path(tempfile.gettempdir()))
    sensitive = {
        Path("/"),
        Path("/tmp"),
        Path("/var/tmp"),
        Path("/run"),
        Path("/var"),
        Path("/usr"),
        Path("/etc"),
        Path("/opt"),
        Path("/home"),
        Path("/Users"),
        home,
        home / ".local" / "share",
        home / "Library" / "Application Support",
        temporary,
    }
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg_data:
        xdg_root = _absolute_posix_configuration(
            xdg_data,
            variable="XDG_DATA_HOME",
        )
        sensitive.add(xdg_root)
    if candidate in sensitive or candidate.parent == Path("/"):
        raise PrivateDataPathError(
            f"private data root is too broad or sensitive: {candidate}"
        )

    # A private leaf beneath the current user's home or the process's native
    # temporary root is a valid per-user/test boundary, even on systems where
    # those roots live below /root or /private/var. The roots themselves were
    # rejected above.
    for user_area in (home, temporary):
        try:
            candidate.relative_to(user_area)
        except ValueError:
            continue
        else:
            return

    # Outside the user's known areas, never accept a configured data root
    # anywhere below an operating-system namespace. Checking the first path
    # component closes descendants such as /usr/local/Onyx and /var/lib/Onyx,
    # not only the broad namespace directory itself. ``lib*`` covers the
    # conventional Linux /lib, /lib32, /lib64, and /libx32 roots without
    # conflating macOS's case-sensitive /Library namespace.
    parts = candidate.parts
    namespace = parts[1] if len(parts) > 1 else ""
    if (
        namespace in _POSIX_SYSTEM_NAMESPACE_ROOTS
        or namespace == "lib"
        or (
            namespace.startswith("lib")
            and namespace[3:] in {"32", "64", "x32"}
        )
    ):
        raise PrivateDataPathError(
            f"private data root is inside a system namespace: {candidate}"
        )


def _known_onyx_leaf(path: Path) -> bool:
    """Return whether a path name itself proves it is an Onyx-owned leaf."""

    return path.name.casefold() in {"onyx", "onyx-data"}


def _reject_posix_linked_components(path: Path) -> None:
    """Fail closed when an existing component of ``path`` is a symlink.

    This check intentionally happens before directory creation and does not use
    ``Path.resolve()``: resolving first would erase the evidence that a
    configured private-data root, or one of its ancestors, was redirected.
    """

    candidate = _absolute_without_link_resolution(path)
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PrivateDataPathError(
                f"private data path component cannot be validated: {current}"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise PrivateDataPathError(
                f"private data path component is linked: {current}"
            )


def resource_root() -> Path:
    """Return the read-only source/bundle root containing shipped assets."""
    if is_frozen():
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_root() -> Path:
    """Return the writable per-user data root without requiring elevation."""
    override = os.environ.get("ONYX_DATA_DIR", "").strip()
    if override:
        if os.name == "nt":
            return Path(override).expanduser().resolve()
        candidate = _absolute_posix_configuration(
            override,
            variable="ONYX_DATA_DIR",
        )
        _reject_broad_posix_private_root(candidate)
        _reject_posix_linked_components(candidate)
        return candidate

    # Preserve the existing checkout behavior for developers and tests.
    if not is_frozen():
        return resource_root()

    system = platform.system()
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local_app_data)
            if local_app_data
            else Path.home() / "AppData" / "Local"
        )
        return base / APP_VENDOR / APP_NAME
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_VENDOR / APP_NAME

    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    base = (
        _absolute_posix_configuration(xdg_data, variable="XDG_DATA_HOME")
        if xdg_data
        else Path.home() / ".local" / "share"
    )
    if xdg_data:
        _reject_posix_filesystem_root_configuration(
            base,
            variable="XDG_DATA_HOME",
        )
    candidate = base / "cyryx-labs" / "onyx"
    _reject_broad_posix_private_root(candidate)
    _reject_posix_linked_components(candidate)
    return candidate


def config_dir() -> Path:
    return data_root() / "config"


def config_file() -> Path:
    return config_dir() / "api_keys.json"


def memory_dir() -> Path:
    return data_root() / "memory"


def runtime_dir() -> Path:
    return data_root() / "runtime"


def private_control_plane_runtime_dir() -> Path:
    """Return M1's fixed per-user runtime, independent of source checkout mode.

    This deliberately does not honor ``ONYX_DATA_DIR`` and does not change the
    historical ``data_root``/``runtime_dir`` contract used by the existing app.
    """
    system = platform.system()
    if system == "Windows":
        return windows_local_app_data_dir() / APP_VENDOR / APP_NAME / "runtime"
    if system == "Darwin":
        candidate = (
            Path.home()
            / "Library"
            / "Application Support"
            / APP_VENDOR
            / APP_NAME
            / "runtime"
        )
        _reject_broad_posix_private_root(candidate)
        _reject_posix_linked_components(candidate)
        return candidate
    xdg_data = os.environ.get("XDG_DATA_HOME", "").strip()
    candidate = (
        _absolute_posix_configuration(xdg_data, variable="XDG_DATA_HOME")
        if xdg_data
        else None
    )
    if candidate is not None:
        _reject_posix_filesystem_root_configuration(
            candidate,
            variable="XDG_DATA_HOME",
        )
    base = candidate if candidate is not None else Path.home() / ".local" / "share"
    runtime = base / "cyryx-labs" / "onyx" / "runtime"
    _reject_broad_posix_private_root(runtime)
    _reject_posix_linked_components(runtime)
    return runtime


def uploads_dir() -> Path:
    return data_root() / "uploads"


def _ensure_posix_private_directory(
    path: Path,
    *,
    repair_existing: bool,
) -> None:
    """Create/secure one directory through an ``O_NOFOLLOW`` descriptor walk."""

    candidate = _absolute_without_link_resolution(path)
    if candidate == Path("/"):
        raise PrivateDataPathError("private data path cannot be the filesystem root")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        descriptor = os.open("/", flags)
    except OSError as exc:
        raise PrivateDataPathError("private data root cannot be opened safely") from exc
    final_created = False
    try:
        for index, component in enumerate(candidate.parts[1:]):
            created = False
            try:
                child = os.open(component, flags, dir_fd=descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=descriptor)
                    created = True
                except FileExistsError:
                    pass
                child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            if index == len(candidate.parts[1:]) - 1:
                final_created = created
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or int(info.st_uid) != os.geteuid():
            raise PrivateDataPathError(
                f"private data path is not owner-controlled: {candidate}"
            )
        if stat.S_IMODE(info.st_mode) != 0o700:
            if not final_created and not repair_existing:
                raise PrivateDataPathError(
                    "existing private data root is not an explicitly identifiable "
                    f"Onyx leaf with mode 0700: {candidate}"
                )
            os.fchmod(descriptor, 0o700)
        secured = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(secured.st_mode)
            or int(secured.st_uid) != os.geteuid()
            or stat.S_IMODE(secured.st_mode) != 0o700
        ):
            raise PrivateDataPathError(
                f"private data path permissions are invalid: {candidate}"
            )
    except PrivateDataPathError:
        raise
    except OSError as exc:
        raise PrivateDataPathError(
            f"private data path cannot be secured safely: {candidate}"
        ) from exc
    finally:
        os.close(descriptor)


def ensure_data_layout() -> Path:
    """Create Onyx's non-secret writable directory layout."""
    root = data_root()
    managed = (
        config_dir(),
        config_dir() / "certs",
        memory_dir(),
        runtime_dir() / "audit",
        runtime_dir() / "logs",
        uploads_dir(),
    )
    if os.name == "nt":
        for path in managed:
            path.mkdir(parents=True, exist_ok=True)
        return root

    # A non-frozen checkout intentionally keeps its historical in-repository
    # layout. Creating absent directories remains supported for development,
    # but Onyx must never rewrite permissions on the checkout itself. Frozen
    # installs and explicit ONYX_DATA_DIR overrides always take the hardened
    # owner-only branch below.
    if not is_frozen() and not os.environ.get("ONYX_DATA_DIR", "").strip():
        for path in managed:
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise PrivateDataPathError(
                    f"managed data path escapes source checkout: {path}"
                ) from exc
            path.mkdir(parents=True, exist_ok=True)
        return root

    _reject_posix_linked_components(root)
    _reject_broad_posix_private_root(root)
    _ensure_posix_private_directory(
        root,
        repair_existing=_known_onyx_leaf(root),
    )
    for path in managed:
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise PrivateDataPathError(
                f"managed data path escapes private root: {path}"
            ) from exc
        current = root
        for component in relative.parts:
            current /= component
            _ensure_posix_private_directory(current, repair_existing=True)
    # Reuse the product's descriptor-bound POSIX authority to prove that the
    # final names still resolve beneath the pinned root after creation/repair.
    try:
        from core.host_security_boundary_v1 import HostSecurityBoundaryError
        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        with PosixTrustedDirectoryV1(root=root, enabled=True) as boundary:
            with boundary.session() as session:
                for path in managed:
                    relative = path.relative_to(root).as_posix()
                    if not session.exists(relative, directory=True):
                        raise PrivateDataPathError(
                            f"managed private data directory is missing: {path}"
                        )
    except PrivateDataPathError:
        raise
    except HostSecurityBoundaryError as exc:
        raise PrivateDataPathError(
            "private data layout failed descriptor-bound validation"
        ) from exc
    return root


def _windows_known_folder(name: str) -> Path | None:
    """Resolve a redirected Windows shell folder, or ``None`` if unavailable.

    Windows lets the owner relocate Desktop, Documents and Downloads — OneDrive
    does this by default.  ``Path.home() / "Desktop"`` then points at a mostly
    empty stub while the owner's real files live elsewhere, so anything that
    guesses the path silently reads the wrong directory.
    """
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        ) as key:
            raw, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    if type(raw) is not str or not raw.strip():
        return None
    try:
        resolved = Path(os.path.expandvars(raw))
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_dir() else None


def user_desktop_dir() -> Path:
    """The owner's real Desktop, honouring redirection on every platform."""
    redirected = _windows_known_folder("Desktop")
    if redirected is not None:
        return redirected
    if platform.system() == "Windows":
        for variable in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
            root = os.environ.get(variable, "").strip()
            if root:
                candidate = Path(root) / "Desktop"
                if candidate.is_dir():
                    return candidate
    xdg = os.environ.get("XDG_DESKTOP_DIR", "")
    if xdg and Path(xdg).is_dir():
        return Path(xdg)
    return Path.home() / "Desktop"


def user_downloads_dir() -> Path:
    """The owner's real Downloads folder, honouring redirection."""
    redirected = _windows_known_folder("{374DE290-123F-4565-9164-39C4925E467B}")
    if redirected is not None:
        return redirected
    xdg = os.environ.get("XDG_DOWNLOAD_DIR", "")
    if xdg and Path(xdg).is_dir():
        return Path(xdg)
    return Path.home() / "Downloads"
