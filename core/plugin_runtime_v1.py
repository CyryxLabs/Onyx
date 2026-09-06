"""Clean-room, default-off PluginHost V1 contract.

This module is an original implementation based only on the Onyx story contract.
It requires an injected, authenticated native-sandbox capability before dispatch.
Process separation alone is never treated as containment.

IDS decision: CREATE. No existing host-owned plugin runtime or manifest contract was
found under ``core/``, ``scripts/``, or ``tests/``. Existing subprocess/JSON idioms
were adapted without introducing a second permission or audit authority.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

PROTOCOL_VERSION = "onyx.plugin/v1"
MANIFEST_VERSION = 1
MAX_IPC_BYTES = 64 * 1024
DEFAULT_TIMEOUT_SECONDS = 2.0
KNOWN_CAPABILITIES = frozenset({"test.echo"})
SAFE_ENV_KEYS = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TMP", "TEMP")
NATIVE_SANDBOX_CONTRACT = "onyx.native-sandbox/v1"
MANIFEST_FIELDS = frozenset(
    {
        "manifest_version",
        "protocol_version",
        "plugin_id",
        "version",
        "entrypoint",
        "workspace_id",
        "source",
        "content_digest",
        "license",
        "requested_capabilities",
        "trust",
    }
)


class PluginContractError(RuntimeError):
    """A fail-closed plugin contract rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class PluginExecutionCancelled(OSError):
    """The sandbox stopped execution and verified its cleanup."""


@dataclass(frozen=True)
class NativeSandboxAttestation:
    """Fresh attestation returned by the trusted native sandbox boundary."""

    contract: str
    challenge: str
    capability_id: str
    launch_digest: str
    mac: str


class NativeSandboxCapability(Protocol):
    """Privileged adapter that attests and launches inside a native sandbox.

    An adapter that raises :class:`subprocess.TimeoutExpired` owns timeout
    cleanup: it must terminate and reap the child and close all IPC pipes before
    returning control to the host. The host treats the exception as a
    fail-closed timeout and never retries the plugin implicitly.
    """

    def attest(
        self, challenge: str, launch_digest: str
    ) -> NativeSandboxAttestation: ...

    def execute(
        self,
        argv: Sequence[str],
        *,
        input_text: str,
        environment: Mapping[str, str],
        cwd: Path,
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True)
class PluginManifest:
    manifest_version: int
    protocol_version: str
    plugin_id: str
    version: str
    entrypoint: str
    workspace_id: str
    source: str
    content_digest: str
    license: str
    requested_capabilities: tuple[str, ...]
    trust: str

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "PluginManifest":
        unknown = set(value) - MANIFEST_FIELDS
        missing = MANIFEST_FIELDS - set(value)
        if unknown or missing:
            raise PluginContractError(
                "invalid_manifest_fields",
                f"manifest fields mismatch; unknown={sorted(unknown)}, missing={sorted(missing)}",
            )
        scalar_fields = (
            "plugin_id",
            "version",
            "entrypoint",
            "workspace_id",
            "source",
            "license",
            "trust",
        )
        if (
            value["manifest_version"] != MANIFEST_VERSION
            or value["protocol_version"] != PROTOCOL_VERSION
        ):
            raise PluginContractError(
                "unsupported_protocol", "manifest or protocol version is unsupported"
            )
        if any(
            not isinstance(value[name], str) or not value[name].strip()
            for name in scalar_fields
        ):
            raise PluginContractError(
                "invalid_manifest", "required manifest strings must be non-empty"
            )
        capabilities = value["requested_capabilities"]
        if not isinstance(capabilities, list) or any(
            not isinstance(item, str) for item in capabilities
        ):
            raise PluginContractError(
                "invalid_capabilities", "requested_capabilities must be a string array"
            )
        if len(capabilities) != len(set(capabilities)):
            raise PluginContractError(
                "invalid_capabilities", "requested capabilities must be unique"
            )
        unknown_capabilities = set(capabilities) - KNOWN_CAPABILITIES
        if unknown_capabilities:
            raise PluginContractError(
                "unknown_capability",
                f"unknown capabilities: {sorted(unknown_capabilities)}",
            )
        digest = value["content_digest"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise PluginContractError(
                "invalid_digest", "content_digest must be a lowercase sha256 hex digest"
            )
        if value["trust"] != "test-only":
            raise PluginContractError(
                "untrusted_blocked", "PluginHost V1 only recognizes test-only trust"
            )
        entrypoint = Path(value["entrypoint"])
        if (
            entrypoint.is_absolute()
            or ".." in entrypoint.parts
            or entrypoint.suffix != ".py"
        ):
            raise PluginContractError(
                "invalid_entrypoint", "entrypoint must be a relative Python file"
            )
        return cls(**{**value, "requested_capabilities": tuple(capabilities)})


@dataclass
class PluginRecord:
    manifest: dict[str, Any]
    plugin_root: str
    state: str = "disabled"
    approved_capabilities: list[str] = field(default_factory=list)
    lifecycle: list[dict[str, Any]] = field(default_factory=list)


def native_sandbox_attestation_mac(
    key: bytes, *, challenge: str, launch_digest: str, capability_id: str
) -> str:
    """Authenticate a native sandbox attestation without exposing its key."""

    message = "\0".join(
        (NATIVE_SANDBOX_CONTRACT, challenge, launch_digest, capability_id)
    ).encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _launch_digest(
    argv: Sequence[str],
    *,
    input_text: str,
    environment: Mapping[str, str],
    cwd: Path,
    timeout_seconds: float,
) -> str:
    payload = {
        "argv": list(argv),
        "input_sha256": hashlib.sha256(input_text.encode("utf-8")).hexdigest(),
        "environment": dict(sorted(environment.items())),
        "cwd": str(Path(cwd).resolve()),
        "timeout_seconds": timeout_seconds,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class PluginHostV1:
    """Host-owned lifecycle registry and native-sandbox-gated executor.

    ``allow_trusted_test_plugins`` is deliberately false by default. This contract
    only permits dispatch through an injected capability whose fresh attestation
    authenticates native isolation. All non-test trust values remain rejected.
    """

    def __init__(
        self,
        registry_path: Path | str,
        *,
        workspace_id: str,
        allow_trusted_test_plugins: bool = False,
        native_sandbox: NativeSandboxCapability | None = None,
        native_sandbox_attestation_key: bytes | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.registry_path = Path(registry_path)
        self.workspace_id = workspace_id
        self.allow_trusted_test_plugins = allow_trusted_test_plugins
        self.native_sandbox = native_sandbox
        self._native_sandbox_attestation_key = native_sandbox_attestation_key
        self.timeout_seconds = timeout_seconds
        self._cancelled = threading.Event()
        self._cancellation_lock = threading.RLock()
        self._active_cancellations: set[threading.Event] = set()
        self._records = self._load()

    def cancel(self) -> None:
        """Permanently latch cancellation; a new host requires fresh authority."""
        with self._cancellation_lock:
            self._cancelled.set()
            for signal in self._active_cancellations:
                signal.set()

    def _load(self) -> dict[str, PluginRecord]:
        if not self.registry_path.exists():
            return {}
        try:
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if (
                not isinstance(raw, dict)
                or raw.get("protocol_version") != PROTOCOL_VERSION
            ):
                raise ValueError
            records = raw.get("plugins")
            if not isinstance(records, dict):
                raise ValueError
            return {key: PluginRecord(**value) for key, value in records.items()}
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise PluginContractError(
                "registry_unhealthy", "plugin registry is unavailable or malformed"
            ) from exc

    def _save(self) -> None:
        payload = {
            "protocol_version": PROTOCOL_VERSION,
            "plugins": {
                key: asdict(value) for key, value in sorted(self._records.items())
            },
        }
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fd, temporary = tempfile.mkstemp(
            prefix=f".{self.registry_path.name}.", dir=self.registry_path.parent
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.registry_path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _event(record: PluginRecord, event: str) -> None:
        record.lifecycle.append({"event": event, "timestamp_ns": time.time_ns()})

    def install(
        self, manifest_path: Path | str, *, approved_capabilities: Sequence[str] = ()
    ) -> dict[str, Any]:
        path = Path(manifest_path).resolve()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PluginContractError(
                "invalid_manifest", "manifest cannot be read as JSON"
            ) from exc
        if not isinstance(raw, dict):
            raise PluginContractError(
                "invalid_manifest", "manifest root must be an object"
            )
        manifest = PluginManifest.parse(raw)
        if manifest.workspace_id != self.workspace_id:
            raise PluginContractError(
                "workspace_mismatch", "plugin is bound to another workspace"
            )
        entrypoint = (path.parent / manifest.entrypoint).resolve()
        if path.parent not in entrypoint.parents or not entrypoint.is_file():
            raise PluginContractError(
                "invalid_entrypoint", "entrypoint is missing or escapes plugin root"
            )
        if sha256_file(entrypoint) != manifest.content_digest:
            raise PluginContractError(
                "digest_mismatch", "entrypoint content digest does not match manifest"
            )
        approved = set(approved_capabilities)
        if approved - set(manifest.requested_capabilities):
            raise PluginContractError(
                "capability_not_requested",
                "approval contains an unrequested capability",
            )
        record = PluginRecord(
            manifest={
                **raw,
                "requested_capabilities": list(manifest.requested_capabilities),
            },
            plugin_root=str(path.parent),
            approved_capabilities=sorted(approved),
        )
        self._event(record, "installed")
        self._records[manifest.plugin_id] = record
        self._save()
        return self.inspect(manifest.plugin_id)

    def update(
        self, manifest_path: Path | str, *, approved_capabilities: Sequence[str] = ()
    ) -> dict[str, Any]:
        raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        plugin_id = raw.get("plugin_id") if isinstance(raw, dict) else None
        if plugin_id not in self._records:
            raise PluginContractError("not_installed", "plugin is not installed")
        previous = self._records[plugin_id]
        self.install(manifest_path, approved_capabilities=approved_capabilities)
        self._records[plugin_id].lifecycle = (
            previous.lifecycle + self._records[plugin_id].lifecycle
        )
        self._event(self._records[plugin_id], "updated")
        self._save()
        return self.inspect(plugin_id)

    def inspect(self, plugin_id: str) -> dict[str, Any]:
        record = self._records.get(plugin_id)
        if record is None:
            raise PluginContractError("not_installed", "plugin is not installed")
        return asdict(record)

    def list(self) -> list[dict[str, Any]]:
        return [self.inspect(plugin_id) for plugin_id in sorted(self._records)]

    def enable(self, plugin_id: str) -> dict[str, Any]:
        record = self._require(plugin_id)
        record.state = "enabled"
        self._event(record, "enabled")
        self._save()
        return self.inspect(plugin_id)

    def disable(self, plugin_id: str) -> dict[str, Any]:
        record = self._require(plugin_id)
        record.state = "disabled"
        self._event(record, "disabled")
        self._save()
        return self.inspect(plugin_id)

    def remove(self, plugin_id: str) -> dict[str, Any]:
        record = self._require(plugin_id)
        self._event(record, "removed")
        result = asdict(record)
        del self._records[plugin_id]
        self._save()
        return result

    def status(self) -> dict[str, Any]:
        sandbox_available = (
            self.native_sandbox is not None
            and isinstance(self._native_sandbox_attestation_key, bytes)
            and len(self._native_sandbox_attestation_key) >= 32
        )
        return {
            "protocol_version": PROTOCOL_VERSION,
            "execution_enabled": self.allow_trusted_test_plugins and sandbox_available and not self._cancelled.is_set(),
            "cancellation_supported": callable(getattr(self.native_sandbox, "execute_cancellable", None)),
            "cancel_latched": self._cancelled.is_set(),
            "isolation": "native-sandbox-attestation-required",
            "untrusted_execution": "blocked",
            "plugins": self.list(),
        }

    def _require(self, plugin_id: str) -> PluginRecord:
        record = self._records.get(plugin_id)
        if record is None:
            raise PluginContractError("not_installed", "plugin is not installed")
        return record

    def execute(self, plugin_id: str, operation: str, payload: Any, *, cancellation: threading.Event | None = None) -> dict[str, Any]:
        signal = cancellation if cancellation is not None else threading.Event()
        with self._cancellation_lock:
            if self._cancelled.is_set():
                raise PluginContractError("plugin_cancelled", "plugin host cancellation is latched")
            self._active_cancellations.add(signal)
        try:
            return self._execute(plugin_id, operation, payload, cancellation=signal)
        finally:
            with self._cancellation_lock:
                self._active_cancellations.discard(signal)

    def _execute(self, plugin_id: str, operation: str, payload: Any, *, cancellation: threading.Event) -> dict[str, Any]:
        if cancellation.is_set():
            raise PluginContractError("plugin_cancelled", "plugin host cancellation is latched")
        record = self._require(plugin_id)
        manifest = PluginManifest.parse(record.manifest)
        if not self.allow_trusted_test_plugins:
            raise PluginContractError(
                "execution_disabled", "plugin execution is disabled by default"
            )
        if record.state != "enabled":
            raise PluginContractError("plugin_disabled", "plugin is not enabled")
        if manifest.trust != "test-only":
            raise PluginContractError(
                "untrusted_blocked", "untrusted plugins cannot execute"
            )
        if operation not in record.approved_capabilities:
            raise PluginContractError(
                "capability_denied", "capability is not explicitly approved"
            )
        entrypoint = (Path(record.plugin_root) / manifest.entrypoint).resolve()
        if (
            Path(record.plugin_root).resolve() not in entrypoint.parents
            or sha256_file(entrypoint) != manifest.content_digest
        ):
            raise PluginContractError(
                "runtime_integrity_failure", "plugin changed after approval"
            )
        token = secrets.token_urlsafe(32)
        request = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "request",
            "auth": token,
            "workspace_id": self.workspace_id,
            "capability": operation,
            "payload": payload,
        }
        encoded = json.dumps(request, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_IPC_BYTES:
            raise PluginContractError("ipc_too_large", "request exceeds IPC size limit")
        environment = {
            key: os.environ[key] for key in SAFE_ENV_KEYS if key in os.environ
        }
        environment.update({"PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1"})
        sandbox = self.native_sandbox
        attestation_key = self._native_sandbox_attestation_key
        if (
            sandbox is None
            or not isinstance(attestation_key, bytes)
            or len(attestation_key) < 32
        ):
            raise PluginContractError(
                "native_sandbox_required",
                "plugin execution requires authenticated native sandbox attestation",
            )
        argv = [sys.executable, "-I", str(entrypoint)]
        input_text = encoded + "\n"
        launch_digest = _launch_digest(
            argv,
            input_text=input_text,
            environment=environment,
            cwd=Path(record.plugin_root),
            timeout_seconds=self.timeout_seconds,
        )
        challenge = secrets.token_urlsafe(32)
        try:
            attestation = sandbox.attest(challenge, launch_digest)
        except Exception as exc:
            raise PluginContractError(
                "native_sandbox_attestation_failed",
                "native sandbox attestation could not be authenticated",
            ) from exc
        if type(attestation) is not NativeSandboxAttestation:
            raise PluginContractError(
                "native_sandbox_attestation_failed",
                "native sandbox attestation could not be authenticated",
            )
        expected_mac = native_sandbox_attestation_mac(
            attestation_key,
            challenge=challenge,
            launch_digest=launch_digest,
            capability_id=attestation.capability_id,
        )
        if (
            attestation.contract != NATIVE_SANDBOX_CONTRACT
            or not attestation.capability_id.strip()
            or not hmac.compare_digest(attestation.challenge, challenge)
            or not hmac.compare_digest(attestation.launch_digest, launch_digest)
            or not hmac.compare_digest(attestation.mac, expected_mac)
        ):
            raise PluginContractError(
                "native_sandbox_attestation_failed",
                "native sandbox attestation could not be authenticated",
            )
        try:
            if cancellation.is_set():
                raise PluginExecutionCancelled("plugin_cancelled_before_launch")
            cancellable = getattr(sandbox, "execute_cancellable", None)
            runner = cancellable if callable(cancellable) else sandbox.execute
            cancellation_args = {"cancellation": cancellation} if callable(cancellable) else {}
            completed = runner(
                argv,
                input_text=input_text,
                environment=environment,
                cwd=record.plugin_root,
                timeout_seconds=self.timeout_seconds,
                **cancellation_args,
            )
        except PluginExecutionCancelled as exc:
            raise PluginContractError("plugin_cancelled", "plugin was cancelled and sandbox cleanup verified") from exc
        except subprocess.TimeoutExpired as exc:
            raise PluginContractError(
                "plugin_timeout", "plugin exceeded its time limit and was terminated"
            ) from exc
        except (OSError, UnicodeError) as exc:
            raise PluginContractError(
                "plugin_crash", "plugin process could not complete safely"
            ) from exc
        if cancellation.is_set():
            raise PluginContractError("plugin_cancelled", "plugin completed after cancellation; result withheld")
        if completed.returncode != 0:
            raise PluginContractError(
                "plugin_crash", f"plugin exited with code {completed.returncode}"
            )
        if len(
            completed.stdout.encode("utf-8")
        ) > MAX_IPC_BYTES or "\n" in completed.stdout.rstrip("\n"):
            raise PluginContractError(
                "malformed_ipc", "plugin response must be one bounded JSON line"
            )
        try:
            response = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise PluginContractError(
                "malformed_ipc", "plugin response is not JSON"
            ) from exc
        if not isinstance(response, dict) or set(response) != {
            "protocol_version",
            "type",
            "auth",
            "ok",
            "result",
        }:
            raise PluginContractError(
                "malformed_ipc", "plugin response schema is invalid"
            )
        if (
            response["protocol_version"] != PROTOCOL_VERSION
            or response["type"] != "response"
            or response["auth"] != token
        ):
            raise PluginContractError(
                "ipc_auth_failed", "plugin response authentication failed"
            )
        if response["ok"] is not True:
            raise PluginContractError(
                "plugin_rejected", "plugin returned a rejected response"
            )
        return {"ok": True, "result": response["result"]}
