"""Descriptor-bound, provider-free, read-only workspace mission tools."""
from __future__ import annotations
import ctypes, hashlib, os, re, stat, time
from pathlib import Path
from typing import Any
from memory.store import _is_reparse, contains_secret

MAX_FILES=2000;MAX_DIRS=500;MAX_ENTRIES_VISITED=10000;MAX_RESULTS=200;MAX_READ_BYTES=256_000;MAX_FILE_BYTES=5_000_000;MAX_SECONDS=10.0
_BLOCKED=re.compile(r"(?i)(credential|password|passwd|secret|token|cookie|api.?key|private.?key|\.env)")
_TEXT_EXT={".txt",".md",".rst",".py",".js",".ts",".tsx",".jsx",".json",".toml",".yaml",".yml",".ini",".cfg",".csv",".html",".css",".sql",".xml"}
class WorkspaceToolError(RuntimeError):pass
def _before_native_open(path:Path)->None:pass

def _raw_roots() -> list[Path]:
    configured=os.environ.get("ONYX_WORKSPACE_ROOTS","")
    if not configured.strip():raise WorkspaceToolError("ONYX_WORKSPACE_ROOTS is required")
    return [Path(x) for x in configured.split(os.pathsep) if x.strip()]

def _reject_chain(path: Path) -> None:
    current=Path(path.anchor)
    for part in path.parts[1:]:
        current/=part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):raise WorkspaceToolError("linked or reparse paths are not allowed")

def _roots() -> list[Path]:
    roots=[]
    for raw in _raw_roots():
        absolute=raw.absolute();_reject_chain(absolute)
        if not absolute.is_dir():raise WorkspaceToolError("configured workspace root is not a directory")
        roots.append(absolute.resolve())
    return roots

def _blocked(path: Path) -> bool:return any(_BLOCKED.search(part) or contains_secret(part) for part in path.parts)

def _safe(root: object,relative: object=".") -> tuple[Path,Path]:
    if root is None:raise WorkspaceToolError("an explicit workspace root is required")
    candidate=Path(str(root));
    if not candidate.is_absolute():raise WorkspaceToolError("workspace root must be absolute")
    _reject_chain(candidate.absolute());candidate=candidate.resolve()
    if candidate not in _roots():raise WorkspaceToolError("root is outside the configured workspace allowlist")
    rel=Path(str(relative or "."))
    if rel.is_absolute() or ".." in rel.parts or _blocked(rel):raise WorkspaceToolError("unsafe relative workspace path")
    current=candidate
    for part in rel.parts:
        current/=part
        if current.exists() and (current.is_symlink() or _is_reparse(current)):raise WorkspaceToolError("linked or reparse paths are not allowed")
    if not (current==candidate or current.resolve(strict=False).is_relative_to(candidate)):raise WorkspaceToolError("path escapes workspace root")
    return candidate,current

def _root_for(path:Path)->tuple[Path,Path]:
    for root in _roots():
        try:return root,path.relative_to(root)
        except ValueError:continue
    raise WorkspaceToolError("file is outside configured roots")

def _open_verified(path: Path,max_bytes: int) -> tuple[int,os.stat_result]:
    fd: int | None=None
    try:
        root,relative=_root_for(path)
        before=path.lstat()
        if stat.S_ISLNK(before.st_mode) or _is_reparse(path) or not stat.S_ISREG(before.st_mode):raise WorkspaceToolError("a regular non-linked file is required")
        _before_native_open(path)
        flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
        if os.name!="nt" and os.open in getattr(os,"supports_dir_fd",set()):
            parent=os.open(root,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0))
            try:
                parts=relative.parts
                for component in parts[:-1]:
                    child=os.open(component,os.O_RDONLY|getattr(os,"O_DIRECTORY",0)|getattr(os,"O_NOFOLLOW",0),dir_fd=parent);os.close(parent);parent=child
                fd=os.open(parts[-1],flags,dir_fd=parent)
            finally:os.close(parent)
        else:
            # Windows: open the final object as a native reparse-point handle,
            # verify its kernel-resolved path remains under the trusted root,
            # then bind Python reads to that exact handle.
            if os.name=="nt":
                import msvcrt
                kernel=ctypes.windll.kernel32;OPEN_EXISTING=3;READ=0x80000000;SHARE=7;OPEN_REPARSE=0x00200000
                kernel.CreateFileW.restype=ctypes.c_void_p;kernel.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
                kernel.GetFinalPathNameByHandleW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32]
                kernel.CloseHandle.argtypes=[ctypes.c_void_p]
                handle=kernel.CreateFileW(str(path),READ,SHARE,None,OPEN_EXISTING,OPEN_REPARSE,None)
                if not handle or handle==ctypes.c_void_p(-1).value:raise WorkspaceToolError("Windows safe handle open failed")
                buffer=ctypes.create_unicode_buffer(32768)
                if not kernel.GetFinalPathNameByHandleW(handle,buffer,len(buffer),0):kernel.CloseHandle(handle);raise WorkspaceToolError("Windows canonical handle verification failed")
                final=buffer.value.removeprefix("\\\\?\\")
                try:Path(final).resolve().relative_to(root)
                except ValueError:kernel.CloseHandle(handle);raise WorkspaceToolError("handle resolved outside workspace root")
                fd=msvcrt.open_osfhandle(handle,os.O_RDONLY|getattr(os,"O_BINARY",0))
            else:raise WorkspaceToolError("safe descriptor traversal is unavailable")
        assert fd is not None;held=os.fstat(fd)
        after=path.lstat()
        if (before.st_dev,before.st_ino)!=(held.st_dev,held.st_ino) or (after.st_dev,after.st_ino)!=(held.st_dev,held.st_ino) or _is_reparse(path):raise WorkspaceToolError("file identity changed during open")
        if not stat.S_ISREG(held.st_mode) or held.st_size>max_bytes:raise WorkspaceToolError("file exceeds the bounded size limit")
        return fd,held
    except WorkspaceToolError:
        if fd is not None:
            try:os.close(fd)
            except OSError:pass
        raise
    except OSError as exc:
        if fd is not None:
            try:os.close(fd)
            except OSError:pass
        raise WorkspaceToolError("workspace file could not be opened safely") from exc

def _read_fd(path:Path,limit:int) -> tuple[bytes,bool,os.stat_result]:
    fd,held=_open_verified(path,limit+1)
    try:
        chunks=[];remaining=limit+1
        while remaining:
            chunk=os.read(fd,min(65536,remaining))
            if not chunk:break
            chunks.append(chunk);remaining-=len(chunk)
        data=b"".join(chunks);return data[:limit],len(data)>limit,held
    finally:os.close(fd)

def _decode_text(data:bytes) -> str:
    try:text=data.decode("utf-8",errors="strict")
    except UnicodeDecodeError as exc:raise WorkspaceToolError("file is not strict UTF-8 text") from exc
    controls=sum(1 for c in text if ord(c)<32 and c not in "\n\r\t")
    if controls or (text and controls/max(1,len(text))>.001):raise WorkspaceToolError("file contains binary control characters")
    if contains_secret(text):raise WorkspaceToolError("file content appears to contain a credential")
    return text

def inventory(args:dict[str,Any])->dict[str,Any]:
    root,target=_safe(args.get("root"),args.get("path","."));files_limit=min(MAX_FILES,max(1,int(args.get("max_files",500))));dirs_limit=min(MAX_DIRS,max(1,int(args.get("max_dirs",200))));seconds=min(MAX_SECONDS,max(.01,float(args.get("max_seconds",3))));started=time.monotonic();items=[];dir_count=0
    stack=[target];visited=0
    while stack:
        if time.monotonic()-started>seconds:return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":True,"reason":"time_limit","citation":f"workspace:{root}"}
        basep=stack.pop();dir_count+=1
        if dir_count>dirs_limit:return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":True,"reason":"directory_limit","citation":f"workspace:{root}"}
        try:entries=os.scandir(basep)
        except OSError:continue
        with entries:
            for entry in entries:
                visited+=1
                if visited>MAX_ENTRIES_VISITED:return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":True,"reason":"entry_limit","citation":f"workspace:{root}"}
                if time.monotonic()-started>seconds:return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":True,"reason":"time_limit","citation":f"workspace:{root}"}
                p=Path(entry.path)
                try:
                    if _blocked(p.relative_to(root)) or entry.is_symlink() or _is_reparse(p):continue
                    if entry.is_dir(follow_symlinks=False):stack.append(p);continue
                    if not entry.is_file(follow_symlinks=False):continue
                    fd,held=_open_verified(p,MAX_FILE_BYTES);os.close(fd)
                except (OSError,WorkspaceToolError):continue
                items.append({"path":p.relative_to(root).as_posix(),"size":held.st_size,"modified_ns":held.st_mtime_ns,"text":p.suffix.lower() in _TEXT_EXT})
                if len(items)>=files_limit:return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":True,"reason":"file_limit","citation":f"workspace:{root}"}
    return {"root":str(root),"files":sorted(items,key=lambda x:x["path"]),"truncated":False,"citation":f"workspace:{root}"}

def read_text(args:dict[str,Any])->dict[str,Any]:
    root,path=_safe(args.get("root"),args.get("path"));limit=min(MAX_READ_BYTES,max(1,int(args.get("max_bytes",65536))))
    if path.suffix.lower() not in _TEXT_EXT:raise WorkspaceToolError("unsupported text extension")
    data,truncated,_=_read_fd(path,limit);text=_decode_text(data)
    return {"path":path.relative_to(root).as_posix(),"text":text,"truncated":truncated,"citation":f"file:{path.relative_to(root).as_posix()}"}

def file_hash(args:dict[str,Any])->dict[str,Any]:
    root,path=_safe(args.get("root"),args.get("path"));fd,_=_open_verified(path,MAX_FILE_BYTES);digest=hashlib.sha256()
    try:
        while True:
            chunk=os.read(fd,65536)
            if not chunk:break
            digest.update(chunk)
    finally:os.close(fd)
    return {"path":path.relative_to(root).as_posix(),"sha256":digest.hexdigest(),"citation":f"file:{path.relative_to(root).as_posix()}"}

def search(args:dict[str,Any])->dict[str,Any]:
    if args.get("regex"):raise WorkspaceToolError("regex search is disabled; literal search only")
    query=str(args.get("query",""))
    if not query or len(query)>300:raise WorkspaceToolError("query is blank or too long")
    listing=inventory(args);limit=min(MAX_RESULTS,max(1,int(args.get("max_results",100))));results=[];needle=query.casefold();started=time.monotonic();seconds=min(MAX_SECONDS,max(.01,float(args.get("max_seconds",3))))
    for item in listing["files"]:
        if time.monotonic()-started>seconds:break
        if not item["text"] or item["size"]>MAX_READ_BYTES:continue
        try:text=read_text({"root":listing["root"],"path":item["path"],"max_bytes":MAX_READ_BYTES})["text"]
        except WorkspaceToolError:continue
        for number,line in enumerate(text.splitlines(),1):
            if needle in line.casefold():
                results.append({"path":item["path"],"line":number,"text":line[:500],"citation":f"file:{item['path']}:{number}"})
                if len(results)>=limit:return {"matches":results,"truncated":True,"citation":listing["citation"]}
    return {"matches":results,"truncated":listing.get("truncated",False),"citation":listing["citation"]}

def run(tool:str,args:dict[str,Any],key:str)->Any:
    if tool=="workspace_inventory":data=inventory(args);condition="inventory_completed"
    elif tool=="workspace_text_search":data=search(args);condition="literal_search_completed"
    elif tool=="workspace_read_text":data=read_text(args);condition="descriptor_bound_read_completed"
    elif tool=="workspace_hash":data=file_hash(args);condition="sha256_computed"
    elif tool=="readiness_summary":
        from core.readiness import readiness_state, run_checks
        checks=run_checks(timeout=10);report=readiness_state(checks)
        data={"install_ready":bool(report.get("install_ready")),"operationally_verified":bool(report.get("operationally_verified")),"checks":[{"name":x.check,"status":x.status} for x in checks[:50]],"citation":"core.readiness"};condition="readiness_checks_completed"
    elif tool=="local_system_status":data={"platform":os.name,"python":f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}","provider_free":True,"citation":"local-runtime"};condition="runtime_status_observed"
    else:raise WorkspaceToolError("unsupported provider-free mission tool")
    evidence=[]
    if data.get("citation"):evidence.append({"type":"citation","value":data["citation"]})
    if tool=="workspace_hash":evidence.append({"type":"sha256","value":data["sha256"]})
    return {"status":"succeeded","data":data,"evidence":evidence,"postconditions":[{"name":condition,"satisfied":True}],"waiting_for":None}
