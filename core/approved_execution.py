"""Execute only source bytes whose identity was approved by the trusted host."""

from __future__ import annotations

import copy
import hashlib
import shlex
import subprocess
import sys
from pathlib import Path


SOURCE_SHA256_KEY = "source_sha256"
SOURCE_SIZE_KEY = "source_size"
_MAX_TIMEOUT = 300


def _normalize_args(value: object) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        values = shlex.split(value, posix=sys.platform != "win32")
        if sys.platform == "win32":
            values = [
                item[1:-1]
                if len(item) >= 2 and item[0] == item[-1] and item[0] in "\"'"
                else item
                for item in values
            ]
        return values
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise ValueError("args must be a string or a list of strings")


def _normalize_timeout(value: object, default: int = 30) -> int:
    if value in (None, ""):
        value = default
    if isinstance(value, bool):
        raise ValueError(f"timeout must be an integer from 1 to {_MAX_TIMEOUT}")
    try:
        timeout = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"timeout must be an integer from 1 to {_MAX_TIMEOUT}"
        ) from exc
    if not 1 <= timeout <= _MAX_TIMEOUT:
        raise ValueError(f"timeout must be an integer from 1 to {_MAX_TIMEOUT}")
    return timeout


def _canonical_file(value: object) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("an exact file path is required")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    return path


def materialize_source_request(parameters: dict | None) -> dict:
    """Bind an execution request to the current canonical file bytes."""
    request = copy.deepcopy(dict(parameters or {}))
    path = _canonical_file(request.get("file_path"))
    source = path.read_bytes()
    request["file_path"] = str(path)
    request["args"] = _normalize_args(request.get("args", []))
    request["timeout"] = _normalize_timeout(request.get("timeout", 30))
    request[SOURCE_SHA256_KEY] = hashlib.sha256(source).hexdigest()
    request[SOURCE_SIZE_KEY] = len(source)
    return request


def validate_materialized_source_request(parameters: dict | None) -> dict:
    """Validate approved identity fields without recomputing or replacing them."""
    request = copy.deepcopy(dict(parameters or {}))
    path = _canonical_file(request.get("file_path"))
    if str(path) != str(request.get("file_path", "")):
        raise ValueError("file path is no longer the approved canonical path")
    request["args"] = _normalize_args(request.get("args", []))
    request["timeout"] = _normalize_timeout(request.get("timeout", 30))
    digest = request.get(SOURCE_SHA256_KEY)
    size = request.get(SOURCE_SIZE_KEY)
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError("approved source SHA-256 is missing or invalid")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError("approved source size is missing or invalid")
    return request


def _stdin_command(path: Path, args: list[str]) -> list[str] | None:
    suffix = path.suffix.lower()
    if suffix == ".py":
        return [sys.executable, "-", *args]
    if suffix == ".js":
        return ["node", "-", *args]
    if suffix == ".ts":
        return ["ts-node", "-", *args]
    if suffix in {".sh", ".bash"}:
        return ["bash", "-s", "--", *args]
    if suffix == ".ps1":
        return ["powershell", "-NoProfile", "-NonInteractive", "-File", "-", *args]
    if suffix == ".rb":
        return ["ruby", "-", *args]
    if suffix == ".php":
        return ["php", *args]
    return None


def execute_materialized_source(parameters: dict | None) -> str:
    """Recheck identity, then execute the verified bytes through stdin.

    The mutable original path is never handed to the interpreter. Relative file
    access continues to use the source directory as cwd; ``__file__``-style
    values identify stdin because security takes priority over path emulation.
    """
    try:
        request = validate_materialized_source_request(parameters)
    except (OSError, ValueError) as exc:
        return f"Execution refused: {exc}"

    path = Path(request["file_path"])
    try:
        # This is the final read. The bytes held here, not the mutable path, are
        # what the interpreter receives.
        source = path.read_bytes()
    except OSError as exc:
        return f"Execution refused: could not re-read approved source: {exc}"
    actual_digest = hashlib.sha256(source).hexdigest()
    if len(source) != request[SOURCE_SIZE_KEY] or actual_digest != request[SOURCE_SHA256_KEY]:
        return "Execution refused: source changed after approval."

    command = _stdin_command(path, request["args"])
    if command is None:
        return f"No interpreter for {path.suffix}."
    try:
        result = subprocess.run(
            command,
            input=source,
            capture_output=True,
            timeout=request["timeout"],
            cwd=str(path.parent),
        )
        stdout = result.stdout.decode("utf-8", errors="replace").strip()
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        parts = []
        if result.returncode != 0:
            parts.append(f"Process failed with exit code {result.returncode}.")
        if stdout:
            parts.append(f"Output:\n{stdout}")
        if stderr:
            parts.append(f"Stderr:\n{stderr}")
        return "\n\n".join(parts) if parts else "Executed with no output."
    except subprocess.TimeoutExpired:
        return f"Timed out after {request['timeout']}s."
    except FileNotFoundError:
        return f"Interpreter not found: {command[0]}."
    except Exception as exc:
        return f"Execution error: {exc}"
