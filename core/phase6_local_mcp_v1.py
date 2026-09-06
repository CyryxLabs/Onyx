"""Provider-free local read-only MCP client adapter for Phase 6.

The module implements the stable 2025-11-25 MCP lifecycle over stdio.  It is
strictly default-off, launches only an explicitly pinned local server artifact,
and projects exactly one locally-authored read-only tool contract.  Server
descriptions and instructions are treated as untrusted data and never become
Onyx policy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
from typing import Final


FEATURE_FLAG: Final = "ONYX_PHASE6_LOCAL_MCP_V1"
PROTOCOL_VERSION: Final = "2025-11-25"
TOOL_NAME: Final = "local_catalog_read"
MAX_MESSAGE_BYTES: Final = 1_048_576
MAX_RESULT_BYTES: Final = 262_144
MAX_CREDENTIAL_BYTES: Final = 4_096
DEFAULT_TIMEOUT_SECONDS: Final = 3.0
MAX_TOOL_PAGES: Final = 16
MAX_DISCOVERED_TOOLS: Final = 256

_ID = re.compile(r"[a-z][a-z0-9-]{2,63}\Z")
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{2,63}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CONSTRUCTION_KEY = object()
_EOF = object()


class Phase6LocalMCPError(RuntimeError):
    """The local MCP operation could not complete."""


class Phase6LocalMCPContractError(ValueError):
    """A local MCP input was not canonical."""


class Phase6LocalMCPDenied(PermissionError):
    """Local MCP authority or identity was denied."""


class Phase6LocalMCPUnavailable(Phase6LocalMCPError):
    """The pinned MCP server was unavailable or violated the protocol."""


def _canonical_json(value: object, *, maximum: int = MAX_RESULT_BYTES) -> bytes:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Phase6LocalMCPContractError("value is not canonical JSON") from exc
    if len(payload) > maximum:
        raise Phase6LocalMCPContractError("canonical JSON exceeds the size limit")
    return payload


def _sha(value: bytes | str | object) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = _canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def _strict_json_object(payload: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise Phase6LocalMCPUnavailable(
                    f"MCP JSON-RPC contains duplicate key: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicates)
    except Phase6LocalMCPUnavailable:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise Phase6LocalMCPUnavailable(
            "MCP server emitted malformed JSON-RPC"
        ) from exc
    if type(value) is not dict:
        raise Phase6LocalMCPUnavailable("MCP server emitted a non-JSON-RPC object")
    return value


def _child_environment(credential_name: str, credential: str) -> dict[str, str]:
    # Do not disclose the caller's arbitrary environment to an untrusted local
    # server. Only cross-platform process/locale essentials and the one
    # explicitly configured credential cross the boundary.
    allowed = (
        "COMSPEC",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "PATH",
        "PATHEXT",
        "SystemRoot",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "WINDIR",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment[credential_name] = credential
    return environment


def _canonical_id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise Phase6LocalMCPContractError(
            f"{label} must be a canonical local identifier"
        )
    return value


def _regular_absolute(path: Path | str, label: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.name in {"", ".", ".."}:
        raise Phase6LocalMCPContractError(f"{label} must be an absolute path")
    if candidate.is_symlink() or not candidate.is_file():
        raise Phase6LocalMCPContractError(f"{label} must be a regular file")
    return candidate


@dataclass(frozen=True, slots=True)
class LocalMCPFeatureGateV1:
    enabled: bool = False

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise Phase6LocalMCPContractError("MCP gate must be an exact boolean")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "LocalMCPFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class LocalMCPIdentityV1:
    workspace_id: str
    principal_id: str

    def __post_init__(self) -> None:
        _canonical_id(self.workspace_id, "workspace_id")
        _canonical_id(self.principal_id, "principal_id")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxPhase6LocalMCPIdentity.v1",
                "workspace_id": self.workspace_id,
                "principal_id": self.principal_id,
            }
        )


@dataclass(frozen=True, slots=True)
class LocalMCPServerCommandV1:
    server_id: str
    workspace_id: str
    executable: Path
    executable_sha256: str
    arguments: tuple[str, ...]
    server_artifact: Path
    server_sha256: str
    credential_env_name: str

    def __post_init__(self) -> None:
        _canonical_id(self.server_id, "server_id")
        _canonical_id(self.workspace_id, "workspace_id")
        executable = _regular_absolute(self.executable, "executable")
        artifact = _regular_absolute(self.server_artifact, "server_artifact")
        object.__setattr__(self, "executable", executable)
        object.__setattr__(self, "server_artifact", artifact)
        if (
            type(self.arguments) is not tuple
            or not self.arguments
            or len(self.arguments) > 16
        ):
            raise Phase6LocalMCPContractError(
                "server arguments must be a bounded non-empty tuple"
            )
        for argument in self.arguments:
            if (
                type(argument) is not str
                or not argument
                or len(argument.encode("utf-8")) > 4_096
                or "\x00" in argument
                or "\r" in argument
                or "\n" in argument
            ):
                raise Phase6LocalMCPContractError("server argument is not canonical")
        for label in ("executable_sha256", "server_sha256"):
            value = getattr(self, label)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise Phase6LocalMCPContractError(f"{label} must be SHA-256")
        if self.arguments.count(str(artifact)) != 1:
            raise Phase6LocalMCPContractError(
                "server arguments must bind the pinned artifact exactly once"
            )
        if (
            type(self.credential_env_name) is not str
            or _ENV_NAME.fullmatch(self.credential_env_name) is None
        ):
            raise Phase6LocalMCPContractError("credential_env_name must be canonical")

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxPhase6LocalMCPServerCommand.v1",
                "server_id": self.server_id,
                "workspace_id": self.workspace_id,
                "executable": str(self.executable),
                "executable_sha256": self.executable_sha256,
                "arguments": self.arguments,
                "server_artifact": str(self.server_artifact),
                "server_sha256": self.server_sha256,
                "credential_env_name": self.credential_env_name,
            }
        )

    def attest(self) -> None:
        executable = _regular_absolute(self.executable, "executable")
        artifact = _regular_absolute(self.server_artifact, "server_artifact")
        if executable != self.executable or artifact != self.server_artifact:
            raise Phase6LocalMCPDenied("MCP command paths drifted")
        observed_executable = _sha(executable.read_bytes())
        if not hmac.compare_digest(observed_executable, self.executable_sha256):
            raise Phase6LocalMCPDenied("pinned MCP executable drifted")
        observed_artifact = _sha(artifact.read_bytes())
        if not hmac.compare_digest(observed_artifact, self.server_sha256):
            raise Phase6LocalMCPDenied("pinned MCP server artifact drifted")


@dataclass(frozen=True, slots=True)
class LocalCatalogMCPRequestV1:
    request_id: str
    identity: LocalMCPIdentityV1
    page_size: int = 25
    cursor: str | None = None

    def __post_init__(self) -> None:
        _canonical_id(self.request_id, "request_id")
        if type(self.identity) is not LocalMCPIdentityV1:
            raise Phase6LocalMCPContractError("exact MCP identity is required")
        if type(self.page_size) is not int or not 1 <= self.page_size <= 50:
            raise Phase6LocalMCPContractError("page_size must be from 1 through 50")
        if self.cursor is not None and (
            type(self.cursor) is not str
            or not self.cursor
            or len(self.cursor.encode("utf-8")) > 4_096
            or "\x00" in self.cursor
            or "\r" in self.cursor
            or "\n" in self.cursor
        ):
            raise Phase6LocalMCPContractError("cursor is not canonical")

    @property
    def arguments(self) -> dict[str, object]:
        result: dict[str, object] = {"page_size": self.page_size}
        if self.cursor is not None:
            result["cursor"] = self.cursor
        return result

    @property
    def digest(self) -> str:
        return _sha(
            {
                "schema": "OnyxPhase6LocalMCPCatalogRequest.v1",
                "request_id": self.request_id,
                "identity_digest": self.identity.digest,
                "tool": TOOL_NAME,
                "arguments": self.arguments,
            }
        )


@dataclass(frozen=True, slots=True)
class LocalCatalogMCPReceiptV1:
    request_id: str
    request_digest: str
    identity_digest: str
    server_command_digest: str
    result_digest: str
    protocol_version: str
    tool_name: str
    transport: str
    egress: str
    mutation: str
    receipt_digest: str

    def __post_init__(self) -> None:
        _canonical_id(self.request_id, "request_id")
        for label in (
            "request_digest",
            "identity_digest",
            "server_command_digest",
            "result_digest",
            "receipt_digest",
        ):
            value = getattr(self, label)
            if type(value) is not str or _SHA256.fullmatch(value) is None:
                raise Phase6LocalMCPContractError(f"{label} must be SHA-256")
        if (
            self.protocol_version != PROTOCOL_VERSION
            or self.tool_name != TOOL_NAME
            or self.transport != "stdio"
            or self.egress != "none"
            or self.mutation != "none"
        ):
            raise Phase6LocalMCPContractError("MCP receipt boundary is invalid")
        if not hmac.compare_digest(self.receipt_digest, _sha(self.payload())):
            raise Phase6LocalMCPContractError("MCP receipt digest mismatch")

    def payload(self) -> dict[str, str]:
        return {
            "schema": "OnyxPhase6LocalMCPCatalogReceipt.v1",
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "identity_digest": self.identity_digest,
            "server_command_digest": self.server_command_digest,
            "result_digest": self.result_digest,
            "protocol_version": self.protocol_version,
            "tool_name": self.tool_name,
            "transport": self.transport,
            "egress": self.egress,
            "mutation": self.mutation,
        }


class _StdioJSONRPCV1:
    """Single-flight newline-delimited UTF-8 JSON-RPC stdio transport."""

    def __init__(
        self,
        *,
        _key: object,
        command: LocalMCPServerCommandV1,
        credential: str,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LocalMCPDenied("MCP transport requires the factory")
        command.attest()
        environment = _child_environment(command.credential_env_name, credential)
        argv = [str(command.executable), *command.arguments]
        try:
            process = subprocess.Popen(
                argv,
                cwd=str(command.server_artifact.parent),
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                bufsize=0,
            )
        except OSError as exc:
            raise Phase6LocalMCPUnavailable(
                "pinned MCP server could not start"
            ) from exc
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise Phase6LocalMCPUnavailable("MCP stdio pipes are unavailable")
        self._process = process
        self._queue: queue.Queue[bytes | object | BaseException] = queue.Queue()
        self._write_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._next_id = 1
        self._cancelled_ids: set[int] = set()
        self._closed = False
        self._credential_marker = credential.encode("utf-8")
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name="onyx-mcp-stdout", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name="onyx-mcp-stderr", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()

    @property
    def process_id(self) -> int:
        return self._process.pid

    @property
    def running(self) -> bool:
        return not self._closed and self._process.poll() is None

    def _read_stdout(self) -> None:
        try:
            while True:
                line = self._process.stdout.readline(MAX_MESSAGE_BYTES + 1)
                if not line:
                    self._queue.put(_EOF)
                    return
                if len(line) > MAX_MESSAGE_BYTES:
                    self._queue.put(
                        Phase6LocalMCPUnavailable(
                            "MCP server response exceeds the message limit"
                        )
                    )
                    return
                if self._credential_marker in line:
                    self._queue.put(
                        Phase6LocalMCPUnavailable(
                            "MCP server attempted credential reflection"
                        )
                    )
                    return
                self._queue.put(line)
        except BaseException as exc:
            self._queue.put(exc)

    def _drain_stderr(self) -> None:
        try:
            while self._process.stderr.read(8_192):
                pass
        except BaseException:
            return

    def _send(self, message: Mapping[str, object]) -> None:
        if self._closed or self._process.poll() is not None:
            raise Phase6LocalMCPUnavailable("MCP stdio transport is closed")
        payload = _canonical_json(message, maximum=MAX_MESSAGE_BYTES)
        if b"\r" in payload or b"\n" in payload:
            raise Phase6LocalMCPContractError(
                "serialized MCP message contains a raw newline"
            )
        with self._write_lock:
            try:
                self._process.stdin.write(payload + b"\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise Phase6LocalMCPUnavailable(
                    "MCP server input closed unexpectedly"
                ) from exc

    def notify(self, method: str, params: Mapping[str, object] | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = dict(params)
        self._send(message)

    def request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float,
    ) -> dict[str, object]:
        if (
            type(timeout_seconds) not in (float, int)
            or isinstance(timeout_seconds, bool)
            or not 0.05 <= float(timeout_seconds) <= 30.0
        ):
            raise Phase6LocalMCPContractError("MCP timeout is out of bounds")
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": dict(params),
                }
            )
            deadline = time.monotonic() + float(timeout_seconds)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._cancel_timeout(method, request_id)
                    raise Phase6LocalMCPUnavailable("MCP request timed out")
                try:
                    item = self._queue.get(timeout=remaining)
                except queue.Empty as exc:
                    self._cancel_timeout(method, request_id)
                    raise Phase6LocalMCPUnavailable("MCP request timed out") from exc
                if item is _EOF:
                    raise Phase6LocalMCPUnavailable(
                        "MCP server closed output unexpectedly"
                    )
                if isinstance(item, BaseException):
                    if isinstance(item, Phase6LocalMCPError):
                        raise item
                    raise Phase6LocalMCPUnavailable(
                        "MCP stdout reader failed"
                    ) from item
                try:
                    decoded = item.decode("utf-8", errors="strict")
                    if decoded.endswith("\r\n"):
                        body = decoded[:-2]
                    elif decoded.endswith("\n"):
                        body = decoded[:-1]
                    else:
                        raise ValueError("message is not newline delimited")
                    if "\r" in body or "\n" in body:
                        raise ValueError("message contains an embedded newline")
                    message = _strict_json_object(body)
                except UnicodeDecodeError as exc:
                    raise Phase6LocalMCPUnavailable(
                        "MCP server emitted malformed JSON-RPC"
                    ) from exc
                except ValueError as exc:
                    raise Phase6LocalMCPUnavailable(
                        "MCP server emitted malformed JSON-RPC"
                    ) from exc
                if message.get("jsonrpc") != "2.0":
                    raise Phase6LocalMCPUnavailable(
                        "MCP server emitted a non-JSON-RPC object"
                    )
                if "method" in message:
                    if "id" in message:
                        raise Phase6LocalMCPUnavailable(
                            "server-initiated MCP requests are not authorized"
                        )
                    if message.get("method") not in {
                        "notifications/message",
                        "notifications/progress",
                    }:
                        raise Phase6LocalMCPUnavailable(
                            "unexpected MCP server notification"
                        )
                    continue
                response_id = message.get("id")
                if type(response_id) is not int:
                    raise Phase6LocalMCPUnavailable("MCP response ID type diverged")
                if response_id in self._cancelled_ids:
                    self._cancelled_ids.remove(response_id)
                    continue
                if response_id != request_id:
                    raise Phase6LocalMCPUnavailable("MCP response correlation diverged")
                has_result = "result" in message
                has_error = "error" in message
                if has_result == has_error:
                    raise Phase6LocalMCPUnavailable(
                        "MCP response must contain exactly one result or error"
                    )
                if has_error:
                    error = message.get("error")
                    if type(error) is not dict:
                        raise Phase6LocalMCPUnavailable(
                            "MCP protocol error is malformed"
                        )
                    code = error.get("code")
                    text = error.get("message")
                    if type(code) is not int or type(text) is not str:
                        raise Phase6LocalMCPUnavailable(
                            "MCP protocol error is malformed"
                        )
                    raise Phase6LocalMCPUnavailable(
                        f"MCP protocol error {code}: {text[:160]}"
                    )
                result = message.get("result")
                if type(result) is not dict:
                    raise Phase6LocalMCPUnavailable("MCP result must be an object")
                _canonical_json(result, maximum=MAX_RESULT_BYTES)
                return result

    def _cancel_timeout(self, method: str, request_id: int) -> None:
        # MCP explicitly forbids cancellation of initialize. All other
        # non-task requests use the ordinary cancellation notification.
        if method == "initialize":
            return
        self._cancelled_ids.add(request_id)
        try:
            self.notify(
                "notifications/cancelled",
                {
                    "requestId": request_id,
                    "reason": "onyx-local-timeout",
                },
            )
        except Phase6LocalMCPError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._process.stdin.close()
        except OSError:
            pass
        try:
            try:
                self._process.wait(timeout=0.75)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=0.75)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=0.75)
        finally:
            for stream in (self._process.stdout, self._process.stderr):
                try:
                    stream.close()
                except OSError:
                    pass
            self._stdout_thread.join(timeout=0.75)
            self._stderr_thread.join(timeout=0.75)


class LocalReadOnlyMCPAdapterV1:
    """Identity-bound adapter exposing one sanitized read-only MCP tool."""

    def __init__(
        self,
        *,
        _key: object,
        command: LocalMCPServerCommandV1,
        identity: LocalMCPIdentityV1,
        transport: _StdioJSONRPCV1,
        timeout_seconds: float,
    ) -> None:
        if _key is not _CONSTRUCTION_KEY:
            raise Phase6LocalMCPDenied("MCP adapter requires the factory")
        if identity.workspace_id != command.workspace_id:
            raise Phase6LocalMCPDenied("MCP workspace identity diverged")
        self._command = command
        self._identity = identity
        self._transport = transport
        self._timeout = float(timeout_seconds)
        self._closed = False
        self._receipts: dict[
            str, tuple[str, dict[str, object], LocalCatalogMCPReceiptV1]
        ] = {}
        self._initialize()

    @property
    def process_id(self) -> int:
        return self._transport.process_id

    @property
    def server_running(self) -> bool:
        return self._transport.running

    @property
    def identity(self) -> LocalMCPIdentityV1:
        return self._identity

    @property
    def tool_declaration(self) -> dict[str, object]:
        return {
            "name": TOOL_NAME,
            "title": "Onyx Local Capability Catalog",
            "description": (
                "Reads allowlisted provider-free capability metadata from the "
                "current Onyx workspace. It cannot read file contents or mutate."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page_size": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "cursor": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "maxItems": 50,
                        "items": {
                            "type": "object",
                            "properties": {
                                "capability_id": {"type": "string"},
                                "mode": {"const": "read-only"},
                                "provider": {"const": "local"},
                            },
                            "required": ["capability_id", "mode", "provider"],
                            "additionalProperties": False,
                        },
                    },
                    "page_size": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "next_cursor": {
                        "type": ["string", "null"],
                    },
                },
                "required": ["items", "page_size", "next_cursor"],
                "additionalProperties": False,
            },
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            "execution": {"taskSupport": "forbidden"},
        }

    def _initialize(self) -> None:
        result = self._transport.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "onyx-local-mcp-client",
                    "title": "Onyx Local MCP Client",
                    "version": "1.0.0",
                    "description": "Cyryx Labs provider-free read-only MCP client",
                },
            },
            timeout_seconds=self._timeout,
        )
        if result.get("protocolVersion") != PROTOCOL_VERSION:
            raise Phase6LocalMCPUnavailable("MCP protocol negotiation failed")
        capabilities = result.get("capabilities")
        server_info = result.get("serverInfo")
        tools_capability = (
            capabilities.get("tools") if type(capabilities) is dict else None
        )
        if (
            type(capabilities) is not dict
            or type(tools_capability) is not dict
            or type(server_info) is not dict
            or server_info.get("name") != self._command.server_id
        ):
            raise Phase6LocalMCPUnavailable(
                "MCP server identity or tools capability diverged"
            )
        list_changed = tools_capability.get("listChanged")
        if list_changed is not None and type(list_changed) is not bool:
            raise Phase6LocalMCPUnavailable("MCP tools capability is malformed")
        # Optional server instructions are intentionally ignored.  They are
        # untrusted content and cannot amend Onyx authority or policy.
        self._transport.notify("notifications/initialized")
        matches: list[dict[str, object]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        discovered = 0
        for _page in range(MAX_TOOL_PAGES):
            params: dict[str, object] = {}
            if cursor is not None:
                params["cursor"] = cursor
            listed = self._transport.request(
                "tools/list", params, timeout_seconds=self._timeout
            )
            tools = listed.get("tools")
            if type(tools) is not list:
                raise Phase6LocalMCPUnavailable("MCP tools/list result is malformed")
            discovered += len(tools)
            if discovered > MAX_DISCOVERED_TOOLS:
                raise Phase6LocalMCPUnavailable(
                    "MCP tool discovery exceeds the bounded limit"
                )
            matches.extend(
                item
                for item in tools
                if type(item) is dict and item.get("name") == TOOL_NAME
            )
            next_cursor = listed.get("nextCursor")
            if next_cursor is None:
                break
            if (
                type(next_cursor) is not str
                or not next_cursor
                or len(next_cursor.encode("utf-8")) > 4_096
                or next_cursor in seen_cursors
                or "\x00" in next_cursor
                or "\r" in next_cursor
                or "\n" in next_cursor
            ):
                raise Phase6LocalMCPUnavailable("MCP tools/list cursor is malformed")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        else:
            raise Phase6LocalMCPUnavailable("MCP tool discovery exceeds the page limit")
        if len(matches) != 1:
            raise Phase6LocalMCPUnavailable(
                "pinned local read-only MCP tool is absent or duplicated"
            )
        schema = matches[0].get("inputSchema")
        if type(schema) is not dict or schema.get("type") != "object":
            raise Phase6LocalMCPUnavailable("MCP tool input schema is malformed")

    def call_catalog(
        self, request: LocalCatalogMCPRequestV1
    ) -> tuple[dict[str, object], LocalCatalogMCPReceiptV1]:
        if self._closed:
            raise Phase6LocalMCPUnavailable("MCP adapter is closed")
        if type(request) is not LocalCatalogMCPRequestV1:
            raise Phase6LocalMCPContractError("exact MCP request is required")
        if request.identity != self._identity:
            raise Phase6LocalMCPDenied("MCP request identity diverged")
        prior = self._receipts.get(request.request_id)
        if prior is not None:
            if not hmac.compare_digest(prior[0], request.digest):
                raise Phase6LocalMCPDenied(
                    "MCP request ID is already bound to different input"
                )
            return dict(prior[1]), prior[2]
        result = self._transport.request(
            "tools/call",
            {"name": TOOL_NAME, "arguments": request.arguments},
            timeout_seconds=self._timeout,
        )
        if result.get("isError", False) is not False:
            raise Phase6LocalMCPUnavailable("local MCP tool reported an error")
        content = result.get("content")
        structured = result.get("structuredContent")
        if type(content) is not list or type(structured) is not dict:
            raise Phase6LocalMCPUnavailable(
                "local MCP tool result lacks canonical structured content"
            )
        if len(content) != 1:
            raise Phase6LocalMCPUnavailable(
                "local MCP tool returned unsupported content"
            )
        block = content[0]
        if (
            type(block) is not dict
            or set(block) != {"type", "text"}
            or block.get("type") != "text"
            or type(block.get("text")) is not str
        ):
            raise Phase6LocalMCPUnavailable(
                "local MCP tool returned unsupported content"
            )
        text_copy = _strict_json_object(block["text"])
        sanitized = self._sanitize_catalog_result(structured, request)
        if not hmac.compare_digest(
            _canonical_json(text_copy), _canonical_json(sanitized)
        ):
            raise Phase6LocalMCPUnavailable("MCP text and structured result diverged")
        result_digest = _sha(sanitized)
        payload = {
            "schema": "OnyxPhase6LocalMCPCatalogReceipt.v1",
            "request_id": request.request_id,
            "request_digest": request.digest,
            "identity_digest": self._identity.digest,
            "server_command_digest": self._command.digest,
            "result_digest": result_digest,
            "protocol_version": PROTOCOL_VERSION,
            "tool_name": TOOL_NAME,
            "transport": "stdio",
            "egress": "none",
            "mutation": "none",
        }
        receipt = LocalCatalogMCPReceiptV1(
            request_id=request.request_id,
            request_digest=request.digest,
            identity_digest=self._identity.digest,
            server_command_digest=self._command.digest,
            result_digest=result_digest,
            protocol_version=PROTOCOL_VERSION,
            tool_name=TOOL_NAME,
            transport="stdio",
            egress="none",
            mutation="none",
            receipt_digest=_sha(payload),
        )
        self._receipts[request.request_id] = (
            request.digest,
            sanitized,
            receipt,
        )
        return dict(sanitized), receipt

    @staticmethod
    def _sanitize_catalog_result(
        value: dict[str, object], request: LocalCatalogMCPRequestV1
    ) -> dict[str, object]:
        if set(value) != {"items", "page_size", "next_cursor"}:
            raise Phase6LocalMCPUnavailable("structured MCP result fields diverged")
        page_size = value.get("page_size")
        items = value.get("items")
        next_cursor = value.get("next_cursor")
        if page_size != request.page_size or type(page_size) is not int:
            raise Phase6LocalMCPUnavailable("structured MCP page size diverged")
        if type(items) is not list or len(items) > request.page_size:
            raise Phase6LocalMCPUnavailable("structured MCP item bounds diverged")
        sanitized_items: list[dict[str, str]] = []
        for item in items:
            if (
                type(item) is not dict
                or set(item) != {"capability_id", "mode", "provider"}
                or item.get("mode") != "read-only"
                or item.get("provider") != "local"
            ):
                raise Phase6LocalMCPUnavailable(
                    "structured MCP item is outside the local catalog contract"
                )
            capability_id = item.get("capability_id")
            if type(capability_id) is not str or _ID.fullmatch(capability_id) is None:
                raise Phase6LocalMCPUnavailable(
                    "structured MCP capability ID is invalid"
                )
            sanitized_items.append(
                {
                    "capability_id": capability_id,
                    "mode": "read-only",
                    "provider": "local",
                }
            )
        if next_cursor is not None and (
            type(next_cursor) is not str
            or not next_cursor
            or len(next_cursor.encode("utf-8")) > 4_096
            or "\x00" in next_cursor
            or "\r" in next_cursor
            or "\n" in next_cursor
        ):
            raise Phase6LocalMCPUnavailable("structured MCP next cursor is invalid")
        sanitized = {
            "items": sanitized_items,
            "page_size": page_size,
            "next_cursor": next_cursor,
        }
        _canonical_json(sanitized, maximum=MAX_RESULT_BYTES)
        return sanitized

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def __enter__(self) -> "LocalReadOnlyMCPAdapterV1":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def create_local_read_only_mcp_v1(
    *,
    gate: LocalMCPFeatureGateV1,
    command: LocalMCPServerCommandV1 | None = None,
    identity: LocalMCPIdentityV1 | None = None,
    credential: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> LocalReadOnlyMCPAdapterV1 | None:
    """Create the exact local stdio adapter after all static attestations."""

    if type(gate) is not LocalMCPFeatureGateV1:
        raise Phase6LocalMCPContractError("exact MCP feature gate is required")
    if not gate.enabled:
        return None
    if (
        type(command) is not LocalMCPServerCommandV1
        or type(identity) is not LocalMCPIdentityV1
        or type(credential) is not str
    ):
        raise Phase6LocalMCPContractError(
            "enabled MCP requires exact command, identity and credential"
        )
    credential_payload = credential.encode("utf-8")
    if (
        len(credential_payload) < 8
        or len(credential_payload) > MAX_CREDENTIAL_BYTES
        or "\x00" in credential
        or "\r" in credential
        or "\n" in credential
    ):
        raise Phase6LocalMCPContractError("MCP credential is not canonical")
    if identity.workspace_id != command.workspace_id:
        raise Phase6LocalMCPDenied("MCP command workspace diverged")
    command.attest()
    transport = _StdioJSONRPCV1(
        _key=_CONSTRUCTION_KEY,
        command=command,
        credential=credential,
    )
    try:
        return LocalReadOnlyMCPAdapterV1(
            _key=_CONSTRUCTION_KEY,
            command=command,
            identity=identity,
            transport=transport,
            timeout_seconds=float(timeout_seconds),
        )
    except Exception:
        transport.close()
        raise


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "FEATURE_FLAG",
    "MAX_MESSAGE_BYTES",
    "PROTOCOL_VERSION",
    "TOOL_NAME",
    "LocalCatalogMCPReceiptV1",
    "LocalCatalogMCPRequestV1",
    "LocalMCPFeatureGateV1",
    "LocalMCPIdentityV1",
    "LocalMCPServerCommandV1",
    "LocalReadOnlyMCPAdapterV1",
    "Phase6LocalMCPContractError",
    "Phase6LocalMCPDenied",
    "Phase6LocalMCPError",
    "Phase6LocalMCPUnavailable",
    "create_local_read_only_mcp_v1",
]
