import os
import hashlib
import shutil
import platform
import stat as stat_module
import time
from contextlib import AbstractContextManager
from pathlib import Path
from datetime import datetime

from core.undo_journal_v1 import register_undo

try:
    import send2trash
    _SEND2TRASH = True
except ImportError:
    _SEND2TRASH = False

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"
_SAFE_OPERATION_TEST_HOOK = None

_SAFE_ROOTS: list[Path] = [
    Path.home(),
    Path(__file__).resolve().parents[1],
]

_PROTECTED_NAMES = frozenset({"appdata", ".ssh", ".aws", ".azure", ".gnupg", "credentials", "certs", "vault"})
_WINDOWS_RESERVED = frozenset({"con","prn","aux","nul",*(f"com{i}" for i in range(1,10)),*(f"lpt{i}" for i in range(1,10))})


def _artifact_fingerprint(path: Path) -> tuple[str, int, int, int, str]:
    """Return a bounded identity/content proof for a file or directory."""

    stat = path.lstat()
    if path.is_dir():
        return ("dir", stat.st_dev, stat.st_ino, stat.st_mtime_ns, "")
    digest = hashlib.sha256()
    fd, held = _open_bound_file(path)
    try:
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
    finally:
        os.close(fd)
    return ("file", held.st_dev, held.st_ino, held.st_size, digest.hexdigest())


def _require_unchanged(path: Path, expected: tuple[str, int, int, int, str]) -> None:
    if not path.exists() or not _is_safe_path(path):
        raise RuntimeError(f"'{path.name}' is missing or no longer safe")
    if _artifact_fingerprint(path) != expected:
        raise RuntimeError(f"'{path.name}' changed after Onyx acted; leaving it untouched")


def _reverse_created(path: Path, expected: tuple[str, int, int, int, str]) -> str:
    _require_unchanged(path, expected)
    if path.is_dir():
        if any(path.iterdir()):
            raise RuntimeError(f"'{path.name}' is no longer empty; leaving it untouched")
        with SafeOperationGuard(path.parent):
            path.rmdir()
    else:
        with SafeOperationGuard(path.parent):
            path.unlink()
    return f"Removed '{path.name}'."


def _reverse_move(
    original: Path,
    current: Path,
    expected: tuple[str, int, int, int, str],
) -> str:
    if original.exists():
        raise RuntimeError(f"the original path '{original.name}' is occupied")
    _require_unchanged(current, expected)
    if not _is_safe_path(original):
        raise RuntimeError("the original path is no longer safe")
    with SafeOperationGuard(original.parent, current.parent) as guard:
        guard.rename(current, original)
    return f"Restored '{original.name}' to {original.parent.name}/."

def _win_kernel32():
    import ctypes
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateFileW.argtypes=(ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p)
    kernel.CreateFileW.restype=ctypes.c_void_p
    kernel.CloseHandle.argtypes=(ctypes.c_void_p,);kernel.CloseHandle.restype=ctypes.c_bool
    kernel.GetFinalPathNameByHandleW.argtypes=(ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32)
    kernel.GetFinalPathNameByHandleW.restype=ctypes.c_uint32
    kernel.GetFileAttributesW.argtypes=(ctypes.c_wchar_p,);kernel.GetFileAttributesW.restype=ctypes.c_uint32
    kernel.SetFileInformationByHandle.argtypes=(ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_uint32)
    kernel.SetFileInformationByHandle.restype=ctypes.c_bool
    return kernel

def _is_safe_path(target: Path) -> bool:
    """Is the given path inside _SAFE_ROOTS? If not, refuse the operation."""
    try:
        raw = str(target).strip().casefold()
        if raw.startswith(("\\\\", "\\device\\")):
            return False
        for index,part in enumerate(target.parts):
            clean=part.rstrip(" .").casefold();stem=clean.split(".",1)[0]
            if stem in _WINDOWS_RESERVED:return False
            if ":" in part and not (index==0 and len(part)==3 and part[1:]==":\\"):return False
        resolved = target.resolve()
        cursor=target if target.exists() else target.parent
        while cursor.parent!=cursor:
            try:
                stat=cursor.lstat()
                if cursor.is_symlink() or getattr(stat,"st_file_attributes",0)&0x400:return False
            except OSError:return False
            cursor=cursor.parent
        if any(part.casefold() in _PROTECTED_NAMES for part in resolved.parts):
            return False
        project = Path(__file__).resolve().parents[1]
        protected_project = (project / "config", project / "certs", project / "memory", project / "runtime", project / "core", project / "actions", project / "tests")
        if any(resolved == item.resolve() or resolved.is_relative_to(item.resolve()) for item in protected_project):
            return False
        return any(
            resolved == root.resolve() or resolved.is_relative_to(root.resolve())
            for root in _SAFE_ROOTS
        )
    except Exception:
        return False

def _get_desktop() -> Path:
    # Windows relocates Desktop when OneDrive backs it up, so guessing
    # ``home/Desktop`` reads an almost-empty stub instead of the owner's files.
    from core.paths import user_desktop_dir

    return user_desktop_dir()

def _get_downloads() -> Path:
    from core.paths import user_downloads_dir

    return user_downloads_dir()

def _get_documents() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_DOCUMENTS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Documents"

def _get_pictures() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_PICTURES_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Pictures"

def _get_music() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_MUSIC_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Music"

def _get_videos() -> Path:
    if _OS == "Linux":
        xdg = os.environ.get("XDG_VIDEOS_DIR", "")
        if xdg and Path(xdg).exists():
            return Path(xdg)
    return Path.home() / "Videos"


def _resolve_path(raw: str) -> Path:
    shortcuts: dict[str, Path] = {
        "desktop":   _get_desktop(),
        "downloads": _get_downloads(),
        "documents": _get_documents(),
        "pictures":  _get_pictures(),
        "music":     _get_music(),
        "videos":    _get_videos(),
        "home":      Path.home(),
    }
    lower = raw.strip().lower()
    if lower in shortcuts:
        return shortcuts[lower]
    return Path(raw).expanduser()


def _bounded_safe_files(root: Path, *, max_entries: int = 10_000, max_dirs: int = 1_000, max_seconds: float = 3.0):
    """Stream safe files without following links or materializing directory trees."""
    stack = [root]
    entries = dirs = 0
    deadline = time.monotonic() + max_seconds
    while stack and entries < max_entries and dirs < max_dirs and time.monotonic() < deadline:
        directory = stack.pop()
        if not _is_safe_path(directory):
            continue
        dirs += 1
        try:
            with os.scandir(directory) as iterator:
                for entry in iterator:
                    if entries >= max_entries or time.monotonic() >= deadline:
                        return
                    entries += 1
                    path = Path(entry.path)
                    if not _is_safe_path(path):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            yield path
                    except OSError:
                        continue
        except OSError:
            continue


def _open_bound_file(path: Path) -> tuple[int, os.stat_result]:
    before=path.lstat()
    with SafeOperationGuard(path.parent) as guard:
        if os.name == "nt":
            import ctypes,msvcrt
            kernel=_win_kernel32();handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x00200000,None)
            if not handle or handle==ctypes.c_void_p(-1).value:raise PermissionError("safe Windows file binding unavailable")
            buffer=ctypes.create_unicode_buffer(32768)
            if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0) or Path(buffer.value.removeprefix("\\\\?\\")).resolve()!=path.resolve(strict=True):
                kernel.CloseHandle(handle);raise PermissionError("file canonicalization failed")
            fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|getattr(os,"O_BINARY",0))
        else:
            fd=os.open(path.name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=guard.dir_fds[path.parent.resolve()])
        held=os.fstat(fd);after=path.lstat()
        if (before.st_dev,before.st_ino)!=(held.st_dev,held.st_ino) or (after.st_dev,after.st_ino)!=(held.st_dev,held.st_ino):
            os.close(fd);raise PermissionError("file identity changed during open")
        return fd,held


class SafeOperationGuard(AbstractContextManager):
    """Hold ancestor directory identities stable for a bounded mutation."""
    def __init__(self, *parents: Path):
        self.parents=tuple(sorted({p.resolve(strict=True) for p in parents},key=lambda p:str(p).casefold()))
        self.handles=[]
        self.dir_fds={}
        self.win_dir_handles={}

    def __enter__(self):
        for parent in self.parents:
            if not _is_safe_path(parent):raise PermissionError("unsafe mutation parent")
            root=next((r.resolve() for r in _SAFE_ROOTS if parent==r.resolve() or parent.is_relative_to(r.resolve())),None)
            if root is None:raise PermissionError("mutation parent outside allowed roots")
            chain=[];cursor=parent
            while cursor!=root:chain.append(cursor);cursor=cursor.parent
            chain.append(root)
            for directory in reversed(chain):
                if os.name=="nt":
                    import ctypes
                    kernel=_win_kernel32()
                    handle=kernel.CreateFileW(str(directory),0x81,3,None,3,0x02200000,None)
                    if not handle or handle==ctypes.c_void_p(-1).value:raise PermissionError("safe Windows directory binding unavailable")
                    buffer=ctypes.create_unicode_buffer(32768)
                    if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0):kernel.CloseHandle(handle);raise PermissionError("canonical handle verification failed")
                    final=Path(buffer.value.removeprefix("\\\\?\\")).resolve()
                    if not (final==root or final.is_relative_to(root)):kernel.CloseHandle(handle);raise PermissionError("handle escaped allowed root")
                    if kernel.GetFileAttributesW(str(directory))&0x400:kernel.CloseHandle(handle);raise PermissionError("reparse ancestor refused")
                    self.handles.append(("win",handle))
                    self.win_dir_handles[directory]=handle
                else:
                    try:
                        if directory==root:
                            fd=os.open(root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
                        else:
                            parent_fd=self.dir_fds[directory.parent]
                            fd=os.open(directory.name,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=parent_fd)
                    except Exception:
                        self.__exit__();raise
                    held=os.fstat(fd)
                    if not stat_module.S_ISDIR(held.st_mode):os.close(fd);raise PermissionError("non-directory ancestor refused")
                    self.handles.append(("fd",fd));self.dir_fds[directory]=fd
        return self

    def __exit__(self,*_):
        for kind,handle in reversed(self.handles):
            try:
                if kind=="win":
                    _win_kernel32().CloseHandle(handle)
                else:os.close(handle)
            except Exception:pass
        self.handles.clear()
        self.dir_fds.clear()
        self.win_dir_handles.clear()

    def write_bytes(self,target:Path,data:bytes,append:bool=False) -> None:
        if os.name=="nt":
            if not append:
                with open(target,"xb") as handle:handle.write(data)
                return
            import ctypes,msvcrt
            kernel=_win_kernel32();handle=kernel.CreateFileW(str(target),0x00000004,3,None,3,0x00200000,None)
            if not handle or handle==ctypes.c_void_p(-1).value:raise PermissionError("safe Windows append binding unavailable")
            buffer=ctypes.create_unicode_buffer(32768)
            if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0) or Path(buffer.value.removeprefix("\\\\?\\")).resolve()!=target.resolve(strict=True):
                kernel.CloseHandle(handle);raise PermissionError("append target identity changed")
            if _SAFE_OPERATION_TEST_HOOK is not None:_SAFE_OPERATION_TEST_HOOK(target,target)
            fd=msvcrt.open_osfhandle(handle,os.O_WRONLY|getattr(os,"O_BINARY",0))
            try:os.write(fd,data)
            finally:os.close(fd)
            return
        parent=self.dir_fds[target.parent.resolve()]
        flags=os.O_WRONLY|os.O_CREAT|getattr(os,"O_NOFOLLOW",0)|(os.O_APPEND if append else os.O_EXCL)
        fd=os.open(target.name,flags,0o600,dir_fd=parent)
        try:os.write(fd,data)
        finally:os.close(fd)

    def mkdir(self,target:Path) -> None:
        if os.name=="nt":target.mkdir(exist_ok=False)
        else:os.mkdir(target.name,0o700,dir_fd=self.dir_fds[target.parent.resolve()])

    def rename(self,source:Path,target:Path) -> None:
        if target.exists():raise FileExistsError("target already exists")
        if os.name=="nt":
            import ctypes
            kernel=_win_kernel32()
            # DELETE access; omit FILE_SHARE_DELETE so another actor cannot swap the leaf.
            handle=kernel.CreateFileW(str(source),0x00010000,3,None,3,0x00200000,None)
            if not handle or handle==ctypes.c_void_p(-1).value:
                raise PermissionError("safe Windows source binding unavailable")
            try:
                canonical=ctypes.create_unicode_buffer(32768)
                if not kernel.GetFinalPathNameByHandleW(handle,canonical,len(canonical),0):
                    raise PermissionError("source canonicalization failed")
                if Path(canonical.value.removeprefix("\\\\?\\")).resolve()!=source.resolve(strict=True):
                    raise PermissionError("source identity changed")
                if _SAFE_OPERATION_TEST_HOOK is not None:
                    _SAFE_OPERATION_TEST_HOOK(source, target)
                leaf=target.name
                if not leaf or leaf in {".",".."} or Path(leaf).name!=leaf:
                    raise PermissionError("rename target must be a simple leaf name")
                encoded=("\\??\\"+str(target)).encode("utf-16-le")
                # FILE_RENAME_INFO: Flags/ReplaceIfExists, padding, RootDirectory,
                # FileNameLength, then the non-NUL-terminated UTF-16 leaf.
                offset=20 if ctypes.sizeof(ctypes.c_void_p)==8 else 12
                info=ctypes.create_string_buffer(offset+len(encoded)+2)
                ctypes.c_uint32.from_buffer(info,0).value=0
                ctypes.c_void_p.from_buffer(info,8 if offset==20 else 4).value=None
                ctypes.c_uint32.from_buffer(info,16 if offset==20 else 8).value=len(encoded)
                ctypes.memmove(ctypes.addressof(info)+offset,encoded,len(encoded))
                if not kernel.SetFileInformationByHandle(handle,3,info,len(info)):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(handle)
            return
        os.rename(source.name,target.name,src_dir_fd=self.dir_fds[source.parent.resolve()],dst_dir_fd=self.dir_fds[target.parent.resolve()])

    def copy_file(self,source:Path,target:Path) -> None:
        if os.name=="nt":
            import ctypes
            import msvcrt
            kernel=_win_kernel32()
            handle=kernel.CreateFileW(str(source),0x80000000,3,None,3,0x00200000,None)
            if not handle or handle==ctypes.c_void_p(-1).value:
                raise PermissionError("safe Windows source binding unavailable")
            buffer=ctypes.create_unicode_buffer(32768)
            if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0):
                kernel.CloseHandle(handle);raise PermissionError("source canonicalization failed")
            final=Path(buffer.value.removeprefix("\\\\?\\")).resolve()
            if final!=source.resolve(strict=True):
                kernel.CloseHandle(handle);raise PermissionError("source identity changed")
            fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|getattr(os,"O_BINARY",0))
            try:
                with os.fdopen(fd,"rb") as src,open(target,"xb") as dst:
                    shutil.copyfileobj(src,dst,1024*1024)
            except Exception:
                try:os.close(fd)
                except OSError:pass
                raise
            return
        src=os.open(source.name,os.O_RDONLY|getattr(os,"O_NOFOLLOW",0),dir_fd=self.dir_fds[source.parent.resolve()])
        try:
            dst=os.open(target.name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0),0o600,dir_fd=self.dir_fds[target.parent.resolve()])
            try:
                while chunk:=os.read(src,1024*1024):os.write(dst,chunk)
            finally:os.close(dst)
        finally:os.close(src)

def _format_size(b: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def _safe_trash(target: Path) -> str:

    if not _SEND2TRASH:
        return (
            "send2trash is not installed. "
            "Run: pip install send2trash — "
            "Permanent deletion is disabled for safety."
        )
    send2trash.send2trash(str(target))
    return f"Moved to Trash: {target.name}"


def list_files(path: str = "desktop", show_hidden: bool = False) -> str:
    try:
        target = _resolve_path(path)
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Path not found: {target}"
        if not target.is_dir():
            return f"Not a directory: {target}"

        items = []
        for item in sorted(target.iterdir()):
            if not _is_safe_path(item):continue
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                items.append(f"📁 {item.name}/")
            else:
                size = _format_size(item.stat().st_size)
                items.append(f"📄 {item.name} ({size})")

        if not items:
            return f"Directory is empty: {target.name}/"

        return f"Contents of {target.name}/ ({len(items)} items):\n" + "\n".join(items)

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Error listing files: {e}"


def create_file(path: str, name: str = "", content: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.parent.is_dir():
            return f"Parent directory not found: {target.parent}"
        with SafeOperationGuard(target.parent) as guard:
            guard.write_bytes(target, content.encode("utf-8"))
        fingerprint = _artifact_fingerprint(target)
        register_undo(
            f"created file {target.name}",
            lambda p=target, proof=fingerprint: _reverse_created(p, proof),
        )
        return f"File created: {target.name}"
    except Exception as e:
        return f"Could not create file: {e}"


def create_folder(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.parent.is_dir():
            return f"Parent directory not found: {target.parent}"
        with SafeOperationGuard(target.parent) as guard:
            guard.mkdir(target)
        fingerprint = _artifact_fingerprint(target)
        register_undo(
            f"created folder {target.name}",
            lambda p=target, proof=fingerprint: _reverse_created(p, proof),
        )
        return f"Folder created: {target.name}"
    except Exception as e:
        return f"Could not create folder: {e}"


def delete_file(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        # Safe-directory check - protect the owner's critical folders
        protected = {
            _get_desktop(), _get_downloads(), _get_documents(),
            _get_pictures(), _get_music(), _get_videos(), Path.home()
        }
        if target.resolve() in {p.resolve() for p in protected}:
            return f"Protected directory, cannot delete: {target.name}"

        return (
            "Delete requires manual confirmation: the platform Trash API is "
            "path-based and cannot provide race-safe descriptor-bound deletion."
        )

    except PermissionError:
        return f"Permission denied: {path}"
    except Exception as e:
        return f"Could not delete: {e}"


def move_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base   = _resolve_path(path)
        src    = (base / name) if name else base
        dst    = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        if not dst.parent.is_dir():
            return f"Destination directory not found: {dst.parent}"
        with SafeOperationGuard(src.parent, dst.parent) as guard:
            guard.rename(src, dst)
        fingerprint = _artifact_fingerprint(dst)
        register_undo(
            f"moved {src.name} to {dst.parent.name}/",
            lambda before=src, after=dst, proof=fingerprint: _reverse_move(
                before, after, proof
            ),
        )
        return f"Moved: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not move: {e}"


def copy_file(path: str, name: str = "", destination: str = "") -> str:
    try:
        base = _resolve_path(path)
        src  = (base / name) if name else base
        dst  = _resolve_path(destination) if destination else None

        if not src.exists():
            return f"Source not found: {src.name}"
        if dst is None:
            return "No destination specified."
        if not _is_safe_path(src):
            return f"Access denied (source): {src}"
        if not _is_safe_path(dst):
            return f"Access denied (destination): {dst}"

        if dst.is_dir():
            dst = dst / src.name

        if not dst.parent.is_dir():
            return f"Destination directory not found: {dst.parent}"
        if src.is_dir():
            return "Directory copy requires manual confirmation; safe recursive copy is not available."
        with SafeOperationGuard(src.parent, dst.parent) as guard:
            guard.copy_file(src, dst)

        fingerprint = _artifact_fingerprint(dst)
        register_undo(
            f"copied {src.name} to {dst.parent.name}/",
            lambda p=dst, proof=fingerprint: _reverse_created(p, proof),
        )

        return f"Copied: {src.name} → {dst.parent.name}/"

    except Exception as e:
        return f"Could not copy: {e}"


def rename_file(path: str, name: str = "", new_name: str = "") -> str:
    try:
        base     = _resolve_path(path)
        target   = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"
        if not new_name:
            return "No new name provided."

        new_path = target.parent / new_name
        if not _is_safe_path(new_path):
            return f"Access denied: {new_path}"
        if new_path.parent.resolve() != target.parent.resolve():
            return "New name must not contain a path."
        if new_path.exists():
            return f"A file named '{new_name}' already exists here."

        with SafeOperationGuard(target.parent, new_path.parent) as guard:
            guard.rename(target, new_path)
        fingerprint = _artifact_fingerprint(new_path)
        register_undo(
            f"renamed {target.name} to {new_name}",
            lambda before=target, after=new_path, proof=fingerprint: _reverse_move(
                before, after, proof
            ),
        )
        return f"Renamed: {target.name} → {new_name}"

    except Exception as e:
        return f"Could not rename: {e}"


def read_file(path: str, name: str = "", max_chars: int = 4000) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"File not found: {target.name}"
        if not target.is_file():
            return f"Not a file: {target.name}"

        fd,_held=_open_bound_file(target)
        try:
            data=os.read(fd,max_chars*4+1)
        finally:os.close(fd)
        content=data.decode("utf-8",errors="ignore")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n\n[Truncated — {len(content)} total chars]"
        return content

    except Exception as e:
        return f"Could not read file: {e}"


def write_file(path: str, name: str = "", content: str = "",
               append: bool = False) -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.parent.is_dir():
            return f"Parent directory not found: {target.parent}"
        if target.exists() and not append:
            return "Refusing race-safe overwrite; rename the existing file or use append."
        existed = target.exists()
        before_size = target.stat().st_size if existed else 0
        with SafeOperationGuard(target.parent) as guard:
            guard.write_bytes(target, content.encode("utf-8"), append=append)
        fingerprint = _artifact_fingerprint(target)

        if existed and append:
            def reverse_append(
                target_path=target,
                original_size=before_size,
                proof=fingerprint,
            ) -> str:
                _require_unchanged(target_path, proof)
                with SafeOperationGuard(target_path.parent):
                    with open(target_path, "r+b") as handle:
                        handle.truncate(original_size)
                return f"Removed the text appended to '{target_path.name}'."

            register_undo(f"appended to {target.name}", reverse_append)
        elif not existed:
            register_undo(
                f"wrote new file {target.name}",
                lambda p=target, proof=fingerprint: _reverse_created(p, proof),
            )
        action = "Appended to" if append else "Written to"
        return f"{action}: {target.name}"
    except Exception as e:
        return f"Could not write file: {e}"


def find_files(name: str = "", extension: str = "",
               path: str = "home", max_results: int = 20) -> str:
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Search path not found: {path}"

        results = []
        for item in _bounded_safe_files(search_path):
            if extension and item.suffix.lower() != extension.lower():
                continue
            if name and name.lower() not in item.name.lower():
                continue
            size = _format_size(item.stat().st_size)
            results.append(f"📄 {item.name} ({size}) — {item.parent}")
            if len(results) >= max_results:
                break

        if not results:
            query = name or extension or "files"
            return f"No {query} found in {search_path.name}/"

        return f"Found {len(results)} file(s):\n" + "\n".join(results)

    except Exception as e:
        return f"Search error: {e}"


def get_largest_files(path: str = "downloads", count: int = 10) -> str:
    count = min(count, 50)  # maksimum 50
    try:
        search_path = _resolve_path(path)
        if not _is_safe_path(search_path):
            return f"Access denied: {search_path}"
        if not search_path.exists():
            return f"Path not found: {path}"

        files = []
        for item in _bounded_safe_files(search_path):
            try:
                files.append((item.stat().st_size, item))
            except OSError:
                continue

        files.sort(reverse=True)
        top = files[:count]

        if not top:
            return "No files found."

        lines = [f"Top {len(top)} largest files in {search_path.name}/:"]
        for size, f in top:
            lines.append(f"  {_format_size(size):>10}  {f.name}  ({f.parent})")

        return "\n".join(lines)

    except Exception as e:
        return f"Error: {e}"


def get_disk_usage(path: str = "home") -> str:
    try:
        target = _resolve_path(path)
        usage  = shutil.disk_usage(target)
        pct    = usage.used / usage.total * 100
        return (
            f"Disk usage ({target}):\n"
            f"  Total : {_format_size(usage.total)}\n"
            f"  Used  : {_format_size(usage.used)} ({pct:.1f}%)\n"
            f"  Free  : {_format_size(usage.free)}"
        )
    except Exception as e:
        return f"Could not get disk usage: {e}"


def organize_desktop() -> str:
    type_map = {
        "Images":    {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
        "Documents": {".pdf", ".doc", ".docx", ".txt", ".xls", ".xlsx",
                      ".ppt", ".pptx", ".csv", ".odt", ".ods", ".odp"},
        "Videos":    {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v"},
        "Music":     {".mp3", ".wav", ".flac", ".aac", ".ogg", ".wma", ".m4a"},
        "Archives":  {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
        "Code":      {".py", ".js", ".ts", ".html", ".css", ".json", ".xml",
                      ".cpp", ".java", ".cs", ".go", ".rs", ".sh"},
    }

    desktop = _get_desktop()
    moved, skipped = [], []
    journal: list[tuple[Path, Path, tuple[str, int, int, int, str]]] = []
    created_dirs: set[Path] = set()

    try:
        for item in desktop.iterdir():
            if not _is_safe_path(item):
                skipped.append(item.name)
                continue
            # Never touch folders, hidden files, or already-organised folders
            if item.is_dir() or item.name.startswith("."):
                continue
            if item.name in {k for k in type_map}:
                continue

            ext        = item.suffix.lower()
            target_dir = desktop / "Others"
            for folder, exts in type_map.items():
                if ext in exts:
                    target_dir = desktop / folder
                    break

            if not target_dir.exists():
                with SafeOperationGuard(target_dir.parent) as guard:guard.mkdir(target_dir)
                created_dirs.add(target_dir)
            new_path = target_dir / item.name

            if new_path.exists():
                skipped.append(item.name)
                continue

            with SafeOperationGuard(item.parent, new_path.parent) as guard:
                guard.rename(item, new_path)
            journal.append((item, new_path, _artifact_fingerprint(new_path)))
            moved.append(f"{item.name} → {target_dir.name}/")

        if journal:
            def reverse_organize(
                entries=tuple(journal),
                folders=tuple(created_dirs),
            ) -> str:
                # Validate every destination before moving any of them.  A
                # changed or occupied path refuses the whole batch.
                for original, current, proof in entries:
                    if original.exists():
                        raise RuntimeError(
                            f"the original path '{original.name}' is occupied"
                        )
                    _require_unchanged(current, proof)
                for original, current, proof in reversed(entries):
                    _reverse_move(original, current, proof)
                for folder in folders:
                    if folder.exists() and folder.is_dir() and not any(folder.iterdir()):
                        with SafeOperationGuard(folder.parent):
                            folder.rmdir()
                return f"Restored {len(entries)} desktop file(s)."

            register_undo(
                f"organized the desktop ({len(journal)} files)",
                reverse_organize,
            )

        result = f"Desktop organized: {len(moved)} files moved."
        if moved:
            preview = moved[:8]
            result += "\n" + "\n".join(preview)
            if len(moved) > 8:
                result += f"\n... and {len(moved) - 8} more."
        if skipped:
            result += f"\n{len(skipped)} file(s) skipped (name conflict)."
        return result

    except Exception as e:
        return f"Could not organize desktop: {e}"


def get_file_info(path: str, name: str = "") -> str:
    try:
        base   = _resolve_path(path)
        target = (base / name) if name else base
        if not _is_safe_path(target):
            return f"Access denied: {target}"
        if not target.exists():
            return f"Not found: {target.name}"

        if target.is_file():
            fd,stat=_open_bound_file(target);os.close(fd)
        else:
            with SafeOperationGuard(target.parent):stat=target.stat()
        info = {
            "Name":      target.name,
            "Type":      "Folder" if target.is_dir() else "File",
            "Size":      _format_size(stat.st_size),
            "Location":  str(target.parent),
            "Created":   datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M"),
            "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "Extension": target.suffix or "—",
        }
        return "\n".join(f"  {k}: {v}" for k, v in info.items())

    except Exception as e:
        return f"Could not get file info: {e}"

def file_controller(
    parameters: dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    action = params.get("action", "").lower().strip()
    path   = params.get("path", "desktop")
    name   = params.get("name", "")

    if player:
        player.write_log(f"[file] {action} {name or path}")

    try:
        if action == "list":
            return list_files(path)

        elif action == "create_file":
            return create_file(path, name=name, content=params.get("content", ""))

        elif action == "create_folder":
            return create_folder(path, name=name)

        elif action == "delete":
            return delete_file(path, name=name)

        elif action == "move":
            return move_file(path, name=name, destination=params.get("destination", ""))

        elif action == "copy":
            return copy_file(path, name=name, destination=params.get("destination", ""))

        elif action == "rename":
            return rename_file(path, name=name, new_name=params.get("new_name", ""))

        elif action == "read":
            return read_file(path, name=name)

        elif action == "write":
            return write_file(
                path, name=name,
                content=params.get("content", ""),
                append=params.get("append", False)
            )

        elif action == "find":
            return find_files(
                name=name or params.get("name", ""),
                extension=params.get("extension", ""),
                path=path,
                max_results=min(int(params.get("max_results", 20)), 50),
            )

        elif action == "largest":
            return get_largest_files(
                path=path,
                count=int(params.get("count", 10)),
            )

        elif action == "disk_usage":
            return get_disk_usage(path)

        elif action == "organize_desktop":
            return organize_desktop()

        elif action == "info":
            return get_file_info(path, name=name)

        else:
            return f"Unknown action: '{action}'"

    except Exception as e:
        return f"File controller error ({action}): {e}"
