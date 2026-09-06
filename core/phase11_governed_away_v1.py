"""Governed, read-only browser Away Mode for Phase 11.

The legacy browser and native-computer tools remain available through their
existing supervised paths.  This module is a separate, mission-owned boundary:
it accepts only an exact authenticated envelope, launches a headed Playwright
browser with an Onyx-owned profile, and supports low-risk observation only.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import shutil
import socket
import stat
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit, urlunsplit

from memory.store import _harden_mode


MISSION_TYPE = "governed_browser_away_v1"
TOOL_NAME = "phase11_governed_browser_away_v1"
ENVELOPE_SCHEMA = "onyx.phase11.browser_action_envelope.v1"
RECEIPT_SCHEMA = "onyx.phase11.browser_action_receipt.v1"
CONTROL_SCHEMA = "onyx.phase11.away_control.v1"
RUNTIME_DEADLINE_SCHEMA = "onyx.phase11.browser_runtime_deadline.v1"
_ENVELOPE_DOMAIN = b"ONYX/PHASE11/BROWSER-ACTION-ENVELOPE/V1\0"
_RUNTIME_DEADLINE_DOMAIN = b"ONYX/PHASE11/BROWSER-RUNTIME-DEADLINE/V1\0"
_CONTROL_DOMAIN = b"ONYX/PHASE11/AWAY-CONTROL/V1\0"
_INTENT_DOMAIN = b"ONYX/PHASE11/BROWSER-ACTION-INTENT/V1\0"
_MAX_TEXT_BYTES = 16_384
_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_MAX_CONTROL_RECORDS = 4_096
_STOP_ACK_TIMEOUT_SECONDS = 5.0
_NAVIGATION_POLL_SECONDS = 1.0
_AVAILABILITY_CACHE_SECONDS = 5.0
_SAFE_ACTIONS = frozenset({"observe"})
AWAY_UNAVAILABLE_REASONS = frozenset(
    {
        "away_storage_transient_busy",
        "away_storage_acl_or_namespace_invalid",
    }
)
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b(bearer|token|api[_ -]?key|secret|password)\b\s*[:=]\s*\S+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])"),
)


class GovernedAwayError(RuntimeError):
    """Fail-closed Away Mode contract or execution error."""


class GovernedAwayWaiting(GovernedAwayError):
    """A visible owner action or reconciliation is required."""


class GovernedAwayUnavailable(GovernedAwayError):
    """A bounded capability dependency is unavailable before any intent."""

    def __init__(self, reason: str) -> None:
        if reason not in AWAY_UNAVAILABLE_REASONS:
            raise ValueError("Away unavailable reason is invalid")
        self.reason = reason
        super().__init__(reason)


class BrowserDriverV1(Protocol):
    def preflight(
        self,
        *,
        envelope: "BrowserActionEnvelopeV1",
        dns_pins: Mapping[str, tuple[str, ...]],
    ) -> None: ...

    def execute(
        self,
        *,
        envelope: "BrowserActionEnvelopeV1",
        profile_dir: Path,
        publish_artifact: Callable[[str, bytes], str],
        cancel: Callable[[], bool],
        control: "AwayControlV1",
        runtime_deadline: "BrowserRuntimeDeadlineV1",
        dns_pins: Mapping[str, tuple[str, ...]],
    ) -> Mapping[str, Any]: ...

    def stop(self, mission_id: str, *, timeout: float) -> bool: ...


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _safe_text(value: object, label: str, *, maximum: int = 200) -> str:
    if not isinstance(value, str):
        raise GovernedAwayError(f"{label} must be text")
    safe = value.strip()
    if not 1 <= len(safe) <= maximum or _CTRL_RE.search(safe):
        raise GovernedAwayError(f"{label} is invalid")
    return safe


def _workspace_id(value: object) -> str:
    safe = _safe_text(value, "workspace_id", maximum=80)
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", safe) is None:
        raise GovernedAwayError("workspace_id is not canonical")
    return safe


def _mission_id(value: object) -> str:
    safe = _safe_text(value, "mission_id", maximum=96)
    if re.fullmatch(r"mis_[A-Za-z0-9_]+", safe) is None:
        raise GovernedAwayError("mission_id is not canonical")
    return safe


def _canonical_url(value: object) -> tuple[str, str, str]:
    raw = _safe_text(value, "target_url", maximum=2_048)
    if re.search(
        r"(?i)(?:[?&](?:access_?token|auth(?:entication|orization)?|"
        r"credential|session(?:id)?|signature|sig|token|api_?key|secret|"
        r"password|passwd|otp|code|key)=)",
        raw,
    ):
        raise GovernedAwayError("secret-bearing target URLs are forbidden")
    parts = urlsplit(raw)
    if parts.query or parts.fragment:
        raise GovernedAwayError(
            "Away Mode V1 forbids ambiguous target query strings and fragments"
        )
    if parts.scheme.casefold() != "https":
        raise GovernedAwayError("Away Mode browser targets require HTTPS")
    if parts.username or parts.password or not parts.hostname:
        raise GovernedAwayError("target_url authority is invalid")
    host = parts.hostname.rstrip(".").casefold()
    if (
        re.fullmatch(
            r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
            r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
            host,
        )
        is None
    ):
        raise GovernedAwayError("target domain is not a canonical public hostname")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise GovernedAwayError("literal IP targets are forbidden")
    port = parts.port
    if port not in (None, 443):
        raise GovernedAwayError("non-default target ports are forbidden")
    netloc = host
    path = parts.path or "/"
    canonical = urlunsplit(("https", netloc, path, parts.query, ""))
    origin = f"https://{host}"
    return canonical, origin, host


def _resolve_public_host(host: object) -> tuple[str, ...]:
    """Resolve one hostname and reject the entire answer set unless all IPs are global."""

    safe = _safe_text(host, "network_host", maximum=253).rstrip(".").casefold()
    try:
        rows = socket.getaddrinfo(
            safe,
            443,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise GovernedAwayWaiting("browser DNS resolution failed closed") from exc
    addresses: set[str] = set()
    for row in rows:
        try:
            address = str(row[4][0]).split("%", 1)[0]
            parsed = ipaddress.ip_address(address)
        except (IndexError, TypeError, ValueError) as exc:
            raise GovernedAwayWaiting(
                "browser DNS returned an invalid address"
            ) from exc
        if (
            not parsed.is_global
            or parsed.is_private
            or parsed.is_loopback
            or parsed.is_link_local
            or parsed.is_reserved
            or parsed.is_multicast
            or parsed.is_unspecified
        ):
            raise GovernedAwayWaiting(
                "browser DNS resolved to a non-public address"
            )
        addresses.add(parsed.compressed)
    if not addresses:
        raise GovernedAwayWaiting("browser DNS returned no addresses")
    return tuple(sorted(addresses))


def _domains(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 16:
        raise GovernedAwayError("allowed_domains must be a finite list")
    output: list[str] = []
    for item in value:
        safe = _safe_text(item, "allowed_domain", maximum=253).rstrip(".").casefold()
        if (
            re.fullmatch(
                r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?",
                safe,
            )
            is None
        ):
            raise GovernedAwayError("allowed domain is invalid")
        output.append(safe)
    if len(set(output)) != len(output):
        raise GovernedAwayError("allowed_domains contains duplicates")
    return tuple(sorted(output))


def _bounded_seconds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 60:
        raise GovernedAwayError("max_seconds must be an integer from 5 to 60")
    return value


def _redact_text(value: object) -> str:
    text = str(value)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return _CTRL_RE.sub("", text)[:_MAX_TEXT_BYTES]


def _bounded_utf8(value: str, maximum: int) -> str:
    return value.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


def _safe_relative(value: object) -> str:
    safe = _safe_text(value, "away_relative_path", maximum=512).replace("\\", "/")
    parts = tuple(safe.split("/"))
    if (
        not parts
        or any(
            part in {"", ".", ".."}
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", part) is None
            for part in parts
        )
    ):
        raise GovernedAwayError("Away storage relative path is invalid")
    return "/".join(parts)


class _SecureAwayStoreV1:
    """Descriptor-bound Windows storage with a fail-closed portable fallback."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).absolute()
        self._windows_boundary: Any | None = None
        if os.name == "nt":
            from core.phase11_windows_clone_cleanup_v1 import (
                CloneCleanupContractError,
                CloneCleanupWaiting,
            )
            from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

            deadline = time.monotonic() + 5.0
            delay = 0.05
            while True:
                try:
                    self._windows_boundary = WindowsTrustedDirectoryV1(
                        root=self.root,
                        enabled=True,
                    )
                    break
                except CloneCleanupWaiting:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise GovernedAwayUnavailable(
                            "away_storage_transient_busy"
                        )
                    time.sleep(min(delay, remaining))
                    delay = min(delay * 2, 0.5)
                except CloneCleanupContractError as exc:
                    raise GovernedAwayUnavailable(
                        "away_storage_acl_or_namespace_invalid"
                    ) from exc
        else:
            self._ensure_portable_directory(self.root)
        _harden_mode(self.root)

    def _ensure_portable_directory(self, path: Path) -> None:
        path = Path(path)
        missing: list[Path] = []
        cursor = path
        while not cursor.exists():
            missing.append(cursor)
            if cursor == cursor.parent:
                raise GovernedAwayError("Away storage root is unavailable")
            cursor = cursor.parent
        for current in (cursor, *reversed(missing)):
            if current in missing:
                current.mkdir(mode=0o700)
            info = current.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise GovernedAwayError(
                    "Away storage rejects linked or non-directory ancestors"
                )

    def _portable_path(
        self,
        relative: object,
        *,
        create_parents: bool = False,
    ) -> Path:
        safe = _safe_relative(relative)
        target = self.root.joinpath(*safe.split("/"))
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise GovernedAwayError("Away storage path escaped its root") from exc
        if create_parents:
            self._ensure_portable_directory(target.parent)
        else:
            cursor = self.root
            for part in target.relative_to(self.root).parts[:-1]:
                cursor /= part
                info = cursor.lstat()
                if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                    raise GovernedAwayError(
                        "Away storage ancestor changed identity"
                    )
        return target

    def publish_once(self, relative: object, content: bytes) -> bool:
        if not isinstance(content, bytes) or len(content) > _MAX_ARTIFACT_BYTES:
            raise GovernedAwayError("Away storage content is invalid")
        safe = _safe_relative(relative)
        if self._windows_boundary is not None:
            from core.phase11_windows_clone_cleanup_v1 import CloneCleanupWaiting

            try:
                with self._windows_boundary.session() as session:
                    session.publish_create(safe, content)
                return True
            except CloneCleanupWaiting as exc:
                if "artifact_exists" not in str(exc):
                    raise GovernedAwayError("Away trusted write failed") from exc
                self.read(safe, max_bytes=_MAX_ARTIFACT_BYTES)
                return False
        path = self._portable_path(safe, create_parents=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            self.read(safe, max_bytes=_MAX_ARTIFACT_BYTES)
            return False
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise GovernedAwayError("Away storage write was incomplete")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _harden_mode(path)
        return True

    def read_optional(self, relative: object, *, max_bytes: int) -> bytes | None:
        safe = _safe_relative(relative)
        if self._windows_boundary is not None:
            with self._windows_boundary.session() as session:
                return session.read_optional(safe, max_bytes=max_bytes)
        path = self._portable_path(safe)
        if not path.exists():
            return None
        return self.read(safe, max_bytes=max_bytes)

    def read(self, relative: object, *, max_bytes: int) -> bytes:
        safe = _safe_relative(relative)
        if type(max_bytes) is not int or not 0 <= max_bytes <= _MAX_ARTIFACT_BYTES:
            raise GovernedAwayError("Away storage read bound is invalid")
        if self._windows_boundary is not None:
            with self._windows_boundary.session() as session:
                return session.read(safe, max_bytes=max_bytes)
        path = self._portable_path(safe)
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise GovernedAwayError("Away storage file is not trusted")
            content = os.read(descriptor, max_bytes + 1)
            if len(content) > max_bytes:
                raise GovernedAwayError("Away storage file exceeds its bound")
            return content
        finally:
            os.close(descriptor)

    def ensure_directory(self, relative: object) -> Path:
        safe = _safe_relative(relative)
        marker = f"{safe}/onyx-directory.marker"
        self.publish_once(marker, b"ONYX-AWAY-V1\n")
        path = self.root.joinpath(*safe.split("/"))
        if self._windows_boundary is None:
            self._portable_path(f"{safe}/onyx-directory.marker")
        return path

    def close(self) -> None:
        if self._windows_boundary is not None:
            self._windows_boundary.close()
            self._windows_boundary = None


class _ProfileIdentityGuardV1:
    """Pin the profile directory identity for the complete Chromium lifetime."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path).absolute()
        self._windows_boundary: Any | None = None
        self._portable_identity: tuple[int, int] | None = None
        if os.name == "nt":
            from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

            self._windows_boundary = WindowsTrustedDirectoryV1(
                root=self.path,
                enabled=True,
                allow_root_quarantine=True,
            )
        else:
            info = self.path.lstat()
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise GovernedAwayError("Away profile path is not trusted")
            self._portable_identity = (info.st_dev, info.st_ino)
        self.validate()

    def validate(self) -> None:
        if self._windows_boundary is not None:
            with self._windows_boundary.session():
                pass
            return
        if self._portable_identity is None:
            raise GovernedAwayError("Away profile guard is closed")
        info = self.path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or (info.st_dev, info.st_ino) != self._portable_identity
        ):
            raise GovernedAwayError("Away profile identity changed")

    def close_and_discard(self) -> str:
        self.validate()
        if self._windows_boundary is not None:
            boundary = self._windows_boundary
            quarantine_name = f"onyx-quarantine-{os.urandom(16).hex()}"
            try:
                quarantined = boundary.quarantine_root(quarantine_name)
            except BaseException:
                # Keep the identity-pinned boundary open on failure. The caller
                # must report reconciliation instead of falling back to a
                # path-based recursive delete.
                raise
            boundary.close()
            self._windows_boundary = None
            self.path = quarantined
            return "quarantined_orphan"
        before = self.path.lstat()
        if not stat.S_ISDIR(before.st_mode) or stat.S_ISLNK(before.st_mode):
            raise GovernedAwayError("Away profile cleanup target is not trusted")
        shutil.rmtree(self.path)
        if os.path.lexists(self.path):
            raise GovernedAwayError("Away profile cleanup was incomplete")
        self._portable_identity = None
        return "discarded"


def action_intent_digest(
    *,
    workspace_id: object,
    workspace_root: object,
    action: object,
    target_url: object,
    allowed_domains: object,
    capture_screenshot: object,
    max_seconds: object,
) -> str:
    workspace = _workspace_id(workspace_id)
    root = str(Path(_safe_text(workspace_root, "workspace_root", maximum=1_024)).resolve())
    safe_action = _safe_text(action, "action", maximum=40).casefold()
    if safe_action not in _SAFE_ACTIONS:
        raise GovernedAwayError("Away Mode supports only the read-only observe action")
    url, origin, domain = _canonical_url(target_url)
    domains = _domains(allowed_domains)
    if domain not in domains:
        raise GovernedAwayError("target domain is not in the exact allowlist")
    if type(capture_screenshot) is not bool:
        raise GovernedAwayError("capture_screenshot must be boolean")
    seconds = _bounded_seconds(max_seconds)
    payload = {
        "workspace_id": workspace,
        "workspace_root": root,
        "action": safe_action,
        "target_url": url,
        "target_origin": origin,
        "target_domain": domain,
        "allowed_domains": list(domains),
        "capture_screenshot": capture_screenshot,
        "max_seconds": seconds,
    }
    return hashlib.sha256(_INTENT_DOMAIN + _canonical(payload)).hexdigest()


@dataclass(frozen=True)
class BrowserActionEnvelopeV1:
    schema: str
    mission_id: str
    principal_id: str
    away_session_id: str
    lease_generation: int
    workspace_id: str
    workspace_root: str
    profile_id: str
    provider_id: str
    account_id: str
    action: str
    target_url: str
    target_origin: str
    target_domain: str
    allowed_domains: tuple[str, ...]
    capture_screenshot: bool
    max_seconds: int
    max_uses: int
    network_request_budget: int
    output_byte_budget: int
    screenshot_budget: int
    paid_cost_budget: int
    approval_policy_id: str
    approval_digest: str
    key_epoch: int
    stop_policy: tuple[str, ...]
    intent_digest: str
    issued_at_ns: int
    not_before_ns: int
    expires_at_ns: int
    nonce: str
    signature: str

    @classmethod
    def build(
        cls,
        *,
        signing_key: bytes,
        mission_id: object,
        principal_id: object,
        away_session_id: object,
        lease_generation: object,
        workspace_id: object,
        workspace_root: object,
        profile_id: object,
        provider_id: object,
        account_id: object,
        action: object,
        target_url: object,
        allowed_domains: object,
        capture_screenshot: object,
        max_seconds: object,
        max_uses: object,
        network_request_budget: object,
        output_byte_budget: object,
        screenshot_budget: object,
        paid_cost_budget: object,
        approval_policy_id: object,
        approval_digest: object,
        key_epoch: object,
        stop_policy: object,
        issued_at_ns: int | None = None,
        not_before_ns: int | None = None,
        nonce: str | None = None,
    ) -> "BrowserActionEnvelopeV1":
        if not isinstance(signing_key, bytes) or len(signing_key) < 16:
            raise GovernedAwayError("browser envelope signing key is invalid")
        mid = _mission_id(mission_id)
        principal = _safe_text(principal_id, "principal_id", maximum=96)
        if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", principal) is None:
            raise GovernedAwayError("principal_id is not canonical")
        session = _safe_text(away_session_id, "away_session_id", maximum=96)
        if re.fullmatch(r"away_[0-9a-f]{32}", session) is None:
            raise GovernedAwayError("away_session_id is not canonical")
        if (
            isinstance(lease_generation, bool)
            or not isinstance(lease_generation, int)
            or lease_generation != 1
        ):
            raise GovernedAwayError("lease_generation must be exactly one")
        workspace = _workspace_id(workspace_id)
        root = str(Path(_safe_text(workspace_root, "workspace_root", maximum=1_024)).resolve())
        profile = _safe_text(profile_id, "profile_id", maximum=96)
        provider = _safe_text(provider_id, "provider_id", maximum=64)
        account = _safe_text(account_id, "account_id", maximum=96)
        for label, value in (
            ("profile_id", profile),
            ("provider_id", provider),
            ("account_id", account),
        ):
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", value) is None:
                raise GovernedAwayError(f"{label} is not canonical")
        if provider != "playwright-chromium" or account != "none":
            raise GovernedAwayError(
                "browser V1 is limited to anonymous Playwright observation"
            )
        safe_action = _safe_text(action, "action", maximum=40).casefold()
        if safe_action not in _SAFE_ACTIONS:
            raise GovernedAwayError("Away Mode supports only the read-only observe action")
        url, origin, domain = _canonical_url(target_url)
        domains = _domains(allowed_domains)
        if domain not in domains:
            raise GovernedAwayError("target domain is not in the exact allowlist")
        if type(capture_screenshot) is not bool:
            raise GovernedAwayError("capture_screenshot must be boolean")
        seconds = _bounded_seconds(max_seconds)
        if max_uses != 1:
            raise GovernedAwayError("max_uses must be exactly one")
        for label, value, minimum, maximum in (
            ("network_request_budget", network_request_budget, 1, 500),
            ("output_byte_budget", output_byte_budget, 1_024, _MAX_TEXT_BYTES),
            ("screenshot_budget", screenshot_budget, 0, 1),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not minimum <= value <= maximum
            ):
                raise GovernedAwayError(f"{label} is invalid")
        if screenshot_budget != int(capture_screenshot):
            raise GovernedAwayError(
                "screenshot budget diverges from the exact action"
            )
        if paid_cost_budget != 0:
            raise GovernedAwayError("paid_cost_budget must be zero")
        policy_id = _safe_text(
            approval_policy_id, "approval_policy_id", maximum=96
        )
        approval = _safe_text(
            approval_digest, "approval_digest", maximum=64
        )
        if (
            policy_id != "missionstore.exact-plan.v1"
            or re.fullmatch(r"[0-9a-f]{64}", approval) is None
        ):
            raise GovernedAwayError("approval binding is invalid")
        if (
            isinstance(key_epoch, bool)
            or not isinstance(key_epoch, int)
            or key_epoch != 1
        ):
            raise GovernedAwayError("key_epoch must be exactly one")
        required_stops = (
            "cancel",
            "domain_drift",
            "dialog",
            "download",
            "global_kill",
            "mfa",
            "popup",
            "target_drift",
            "timeout",
        )
        safe_stop_policy = (
            tuple(stop_policy) if isinstance(stop_policy, (list, tuple)) else ()
        )
        if safe_stop_policy != required_stops:
            raise GovernedAwayError("stop_policy must match the host policy")
        issued = time.time_ns() if issued_at_ns is None else issued_at_ns
        if isinstance(issued, bool) or not isinstance(issued, int) or issued <= 0:
            raise GovernedAwayError("issued_at_ns is invalid")
        expires = issued + seconds * 1_000_000_000
        not_before = issued if not_before_ns is None else not_before_ns
        if (
            isinstance(not_before, bool)
            or not isinstance(not_before, int)
            or not_before != issued
        ):
            raise GovernedAwayError("not_before_ns must equal issuance")
        safe_nonce = nonce or os.urandom(16).hex()
        if re.fullmatch(r"[0-9a-f]{32}", safe_nonce) is None:
            raise GovernedAwayError("envelope nonce is invalid")
        intent = action_intent_digest(
            workspace_id=workspace,
            workspace_root=root,
            action=safe_action,
            target_url=url,
            allowed_domains=domains,
            capture_screenshot=capture_screenshot,
            max_seconds=seconds,
        )
        unsigned = {
            "schema": ENVELOPE_SCHEMA,
            "mission_id": mid,
            "principal_id": principal,
            "away_session_id": session,
            "lease_generation": lease_generation,
            "workspace_id": workspace,
            "workspace_root": root,
            "profile_id": profile,
            "provider_id": provider,
            "account_id": account,
            "action": safe_action,
            "target_url": url,
            "target_origin": origin,
            "target_domain": domain,
            "allowed_domains": list(domains),
            "capture_screenshot": capture_screenshot,
            "max_seconds": seconds,
            "max_uses": 1,
            "network_request_budget": network_request_budget,
            "output_byte_budget": output_byte_budget,
            "screenshot_budget": screenshot_budget,
            "paid_cost_budget": 0,
            "approval_policy_id": policy_id,
            "approval_digest": approval,
            "key_epoch": key_epoch,
            "stop_policy": list(required_stops),
            "intent_digest": intent,
            "issued_at_ns": issued,
            "not_before_ns": not_before,
            "expires_at_ns": expires,
            "nonce": safe_nonce,
        }
        signature = hmac.new(
            signing_key,
            _ENVELOPE_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return cls(
            **{
                **unsigned,
                "allowed_domains": domains,
                "stop_policy": required_stops,
            },
            signature=signature,
        )

    def authenticate(
        self,
        signing_key: bytes,
        *,
        now_ns: int | None = None,
        require_active: bool = True,
    ) -> None:
        rebuilt = BrowserActionEnvelopeV1.build(
            signing_key=signing_key,
            mission_id=self.mission_id,
            principal_id=self.principal_id,
            away_session_id=self.away_session_id,
            lease_generation=self.lease_generation,
            workspace_id=self.workspace_id,
            workspace_root=self.workspace_root,
            profile_id=self.profile_id,
            provider_id=self.provider_id,
            account_id=self.account_id,
            action=self.action,
            target_url=self.target_url,
            allowed_domains=self.allowed_domains,
            capture_screenshot=self.capture_screenshot,
            max_seconds=self.max_seconds,
            max_uses=self.max_uses,
            network_request_budget=self.network_request_budget,
            output_byte_budget=self.output_byte_budget,
            screenshot_budget=self.screenshot_budget,
            paid_cost_budget=self.paid_cost_budget,
            approval_policy_id=self.approval_policy_id,
            approval_digest=self.approval_digest,
            key_epoch=self.key_epoch,
            stop_policy=self.stop_policy,
            issued_at_ns=self.issued_at_ns,
            not_before_ns=self.not_before_ns,
            nonce=self.nonce,
        )
        if (
            self.schema != ENVELOPE_SCHEMA
            or self.expires_at_ns != rebuilt.expires_at_ns
            or self.intent_digest != rebuilt.intent_digest
            or self.target_origin != rebuilt.target_origin
            or self.target_domain != rebuilt.target_domain
            or not hmac.compare_digest(self.signature, rebuilt.signature)
        ):
            raise GovernedAwayError("browser action envelope authentication failed")
        if require_active:
            now = time.time_ns() if now_ns is None else now_ns
            if isinstance(now, bool) or not isinstance(now, int):
                raise GovernedAwayError("browser envelope clock is invalid")
            if now < self.not_before_ns or now > self.expires_at_ns:
                raise GovernedAwayWaiting("browser action envelope is not active")

    def as_binding(self) -> dict[str, Any]:
        data = asdict(self)
        data["allowed_domains"] = list(self.allowed_domains)
        return data

    @classmethod
    def from_binding(
        cls, value: object, *, signing_key: bytes
    ) -> "BrowserActionEnvelopeV1":
        if not isinstance(value, Mapping):
            raise GovernedAwayError("browser action envelope is unavailable")
        expected = {
            "schema",
            "mission_id",
            "principal_id",
            "away_session_id",
            "lease_generation",
            "workspace_id",
            "workspace_root",
            "profile_id",
            "provider_id",
            "account_id",
            "action",
            "target_url",
            "target_origin",
            "target_domain",
            "allowed_domains",
            "capture_screenshot",
            "max_seconds",
            "max_uses",
            "network_request_budget",
            "output_byte_budget",
            "screenshot_budget",
            "paid_cost_budget",
            "approval_policy_id",
            "approval_digest",
            "key_epoch",
            "stop_policy",
            "intent_digest",
            "issued_at_ns",
            "not_before_ns",
            "expires_at_ns",
            "nonce",
            "signature",
        }
        if set(value) != expected:
            raise GovernedAwayError("browser action envelope schema diverges")
        envelope = cls(
            schema=value["schema"],
            mission_id=value["mission_id"],
            principal_id=value["principal_id"],
            away_session_id=value["away_session_id"],
            lease_generation=value["lease_generation"],
            workspace_id=value["workspace_id"],
            workspace_root=value["workspace_root"],
            profile_id=value["profile_id"],
            provider_id=value["provider_id"],
            account_id=value["account_id"],
            action=value["action"],
            target_url=value["target_url"],
            target_origin=value["target_origin"],
            target_domain=value["target_domain"],
            allowed_domains=tuple(value["allowed_domains"])
            if isinstance(value["allowed_domains"], list)
            else (),
            capture_screenshot=value["capture_screenshot"],
            max_seconds=value["max_seconds"],
            max_uses=value["max_uses"],
            network_request_budget=value["network_request_budget"],
            output_byte_budget=value["output_byte_budget"],
            screenshot_budget=value["screenshot_budget"],
            paid_cost_budget=value["paid_cost_budget"],
            approval_policy_id=value["approval_policy_id"],
            approval_digest=value["approval_digest"],
            key_epoch=value["key_epoch"],
            stop_policy=tuple(value["stop_policy"])
            if isinstance(value["stop_policy"], list)
            else (),
            intent_digest=value["intent_digest"],
            issued_at_ns=value["issued_at_ns"],
            not_before_ns=value["not_before_ns"],
            expires_at_ns=value["expires_at_ns"],
            nonce=value["nonce"],
            signature=value["signature"],
        )
        envelope.authenticate(signing_key, require_active=False)
        return envelope


def _dns_pin_digest(pins: Mapping[str, tuple[str, ...]]) -> str:
    canonical: dict[str, list[str]] = {}
    for host, addresses in sorted(pins.items()):
        safe_host = _safe_text(host, "dns_pin_host", maximum=253).casefold()
        if not addresses:
            raise GovernedAwayError("DNS pin set is empty")
        normalized: list[str] = []
        for address in addresses:
            parsed = ipaddress.ip_address(address)
            if not parsed.is_global:
                raise GovernedAwayError("DNS pin contains a non-global address")
            normalized.append(parsed.compressed)
        canonical[safe_host] = sorted(set(normalized))
    return hashlib.sha256(_canonical(canonical)).hexdigest()


def _chromium_resolver_args(
    pins: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...]:
    rules: list[str] = []
    for host, addresses in sorted(pins.items()):
        if not addresses:
            raise GovernedAwayError("Chromium DNS pin set is empty")
        # One exact member of the already validated public set is safer than
        # allowing Chromium to perform a second, potentially rebound lookup.
        selected = ipaddress.ip_address(addresses[0])
        replacement = (
            f"[{selected.compressed}]"
            if selected.version == 6
            else selected.compressed
        )
        rules.append(f"MAP {host} {replacement}")
    if not rules:
        raise GovernedAwayError("Chromium DNS pin rules are unavailable")
    return (
        "--host-resolver-rules=" + ",".join(rules),
        "--no-proxy-server",
        "--disable-features=DnsOverHttps,UseDnsHttpsSvcbAlpn",
    )


@dataclass(frozen=True)
class BrowserRuntimeDeadlineV1:
    schema: str
    mission_id: str
    intent_digest: str
    binding_digest: str
    approval_digest: str
    execution_id_digest: str
    dns_pin_digest: str
    max_seconds: int
    issued_at_ns: int
    expires_at_ns: int
    signature: str

    @classmethod
    def build(
        cls,
        *,
        signing_key: bytes,
        envelope: BrowserActionEnvelopeV1,
        binding_digest: str,
        execution_id_digest: str,
        dns_pin_digest: str,
        approved_deadline_ns: int,
        issued_at_ns: int | None = None,
    ) -> "BrowserRuntimeDeadlineV1":
        envelope.authenticate(signing_key, require_active=False)
        for label, value in (
            ("binding_digest", binding_digest),
            ("execution_id_digest", execution_id_digest),
            ("dns_pin_digest", dns_pin_digest),
        ):
            if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise GovernedAwayError(f"{label} is invalid")
        issued = time.time_ns() if issued_at_ns is None else issued_at_ns
        if (
            isinstance(issued, bool)
            or not isinstance(issued, int)
            or isinstance(approved_deadline_ns, bool)
            or not isinstance(approved_deadline_ns, int)
            or approved_deadline_ns <= issued
        ):
            raise GovernedAwayWaiting(
                "approved Away execution deadline expired; fresh approval is required"
            )
        unsigned = {
            "schema": RUNTIME_DEADLINE_SCHEMA,
            "mission_id": envelope.mission_id,
            "intent_digest": envelope.intent_digest,
            "binding_digest": binding_digest,
            "approval_digest": envelope.approval_digest,
            "execution_id_digest": execution_id_digest,
            "dns_pin_digest": dns_pin_digest,
            "max_seconds": envelope.max_seconds,
            "issued_at_ns": issued,
            "expires_at_ns": approved_deadline_ns,
        }
        signature = hmac.new(
            signing_key,
            _RUNTIME_DEADLINE_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return cls(**unsigned, signature=signature)

    def authenticate(
        self,
        signing_key: bytes,
        envelope: BrowserActionEnvelopeV1,
        *,
        now_ns: int | None = None,
    ) -> None:
        rebuilt = BrowserRuntimeDeadlineV1.build(
            signing_key=signing_key,
            envelope=envelope,
            binding_digest=self.binding_digest,
            execution_id_digest=self.execution_id_digest,
            dns_pin_digest=self.dns_pin_digest,
            approved_deadline_ns=self.expires_at_ns,
            issued_at_ns=self.issued_at_ns,
        )
        if (
            self.schema != RUNTIME_DEADLINE_SCHEMA
            or not hmac.compare_digest(
                _canonical(asdict(self)),
                _canonical(asdict(rebuilt)),
            )
        ):
            raise GovernedAwayError(
                "Away runtime deadline authentication failed"
            )
        self.assert_active(now_ns=now_ns)

    def assert_active(self, *, now_ns: int | None = None) -> None:
        now = time.time_ns() if now_ns is None else now_ns
        if now < self.issued_at_ns or now > self.expires_at_ns:
            raise GovernedAwayWaiting(
                "Away runtime deadline expired; fresh approval is required"
            )


class AwayControlV1:
    """Process-local state backed by create-once authenticated records."""

    def __init__(
        self,
        mission_id: str,
        store: _SecureAwayStoreV1,
        signing_key: bytes,
    ) -> None:
        self.mission_id = _mission_id(mission_id)
        self._store = store
        self._prefix = f"controls/{self.mission_id}"
        self._key = signing_key
        self._condition = threading.Condition()
        self._state = "running"
        self._sequence = 0
        self._head = ""
        self._store.ensure_directory(self._prefix)
        self._load()

    @property
    def state(self) -> str:
        with self._condition:
            return self._state

    def _load(self) -> None:
        previous = ""
        sequence = 0
        state = "running"
        for index in range(1, _MAX_CONTROL_RECORDS + 1):
            raw = self._store.read_optional(
                f"{self._prefix}/{index:08d}.json",
                max_bytes=8_192,
            )
            if raw is None:
                break
            try:
                record = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise GovernedAwayError("Away control journal is malformed") from exc
            unsigned = {key: value for key, value in record.items() if key != "signature"}
            expected = hmac.new(
                self._key,
                _CONTROL_DOMAIN + bytes.fromhex(previous or "00" * 32) + _canonical(unsigned),
                hashlib.sha256,
            ).hexdigest()
            if (
                set(record)
                != {"schema", "mission_id", "sequence", "state", "issued_at_ns", "previous", "signature"}
                or record["schema"] != CONTROL_SCHEMA
                or record["mission_id"] != self.mission_id
                or record["sequence"] != sequence + 1
                or record["previous"] != previous
                or record["state"] not in {"paused", "takeover", "running", "killed"}
                or not hmac.compare_digest(str(record["signature"]), expected)
            ):
                raise GovernedAwayError("Away control journal authentication failed")
            previous = hashlib.sha256(_canonical(record)).hexdigest()
            sequence += 1
            state = record["state"]
        else:
            raise GovernedAwayError("Away control journal exceeded its bound")
        self._sequence = sequence
        self._head = previous
        self._state = state

    def set(self, state: str) -> None:
        if state not in {"paused", "takeover", "running", "killed"}:
            raise GovernedAwayError("unsupported Away control state")
        with self._condition:
            if self._state == "killed" and state != "killed":
                raise GovernedAwayError("killed Away session cannot resume")
            if self._state in {"paused", "takeover"} and state not in {
                self._state,
                "killed",
            }:
                raise GovernedAwayError(
                    "paused or taken-over Away session is terminal and cannot resume"
                )
            unsigned = {
                "schema": CONTROL_SCHEMA,
                "mission_id": self.mission_id,
                "sequence": self._sequence + 1,
                "state": state,
                "issued_at_ns": time.time_ns(),
                "previous": self._head,
            }
            signature = hmac.new(
                self._key,
                _CONTROL_DOMAIN
                + bytes.fromhex(self._head or "00" * 32)
                + _canonical(unsigned),
                hashlib.sha256,
            ).hexdigest()
            record = {**unsigned, "signature": signature}
            relative = f"{self._prefix}/{self._sequence + 1:08d}.json"
            if not self._store.publish_once(relative, _canonical(record)):
                raise GovernedAwayError("Away control record already exists")
            self._sequence += 1
            self._head = hashlib.sha256(_canonical(record)).hexdigest()
            self._state = state
            self._condition.notify_all()

    def wait_until_running(self, cancel: Callable[[], bool]) -> None:
        with self._condition:
            if self._state in {"paused", "takeover"}:
                raise GovernedAwayWaiting(
                    "Away session was terminally stopped by pause or takeover"
                )
            if self._state == "killed" or cancel():
                raise GovernedAwayWaiting("Away Mode was killed")


@dataclass
class _ActiveRun:
    control: AwayControlV1
    driver: BrowserDriverV1
    profile_dir: Path


@dataclass
class _DriverRunState:
    stop_requested: threading.Event
    closed: threading.Event
    stop_error: BaseException | None = None


class PlaywrightBrowserDriverV1:
    """Headed Playwright implementation with exact navigation guards."""

    def __init__(self) -> None:
        self._active: dict[str, _DriverRunState] = {}
        self._lock = threading.RLock()
        self._availability_cache: tuple[float, bool, str] | None = None

    @staticmethod
    def _probe_available() -> tuple[bool, str]:
        playwright = None
        browser = None
        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            executable = Path(playwright.chromium.executable_path)
            if not executable.is_file():
                return False, "chromium-executable-missing"
            browser = playwright.chromium.launch(
                headless=True,
                # Release builds deliberately ship the full Chromium runtime
                # and omit Playwright's duplicate headless-shell payload.
                # Pin the readiness probe to the same packaged executable
                # used by headed Away missions instead of allowing Playwright
                # to select the absent headless-shell binary.
                executable_path=str(executable),
                args=[
                    "--host-resolver-rules=MAP onyx.invalid 127.0.0.1",
                    "--no-proxy-server",
                ],
            )
        except Exception as exc:
            return False, f"chromium-runtime:{type(exc).__name__}"
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    return False, "chromium-runtime-close-failed"
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    return False, "playwright-runtime-close-failed"
        return True, "ready-dns-pin-capable"

    def available(self) -> tuple[bool, str]:
        """Return a short-lived informational probe result."""
        now = time.monotonic()
        with self._lock:
            cached = self._availability_cache
            if cached is not None and now - cached[0] <= _AVAILABILITY_CACHE_SECONDS:
                return cached[1], cached[2]
        ready, reason = self._probe_available()
        with self._lock:
            self._availability_cache = (time.monotonic(), ready, reason)
        return ready, reason

    def preflight(
        self,
        *,
        envelope: BrowserActionEnvelopeV1,
        dns_pins: Mapping[str, tuple[str, ...]],
    ) -> None:
        if set(dns_pins) != set(envelope.allowed_domains):
            raise GovernedAwayError("DNS pin set diverges from the envelope")
        if _dns_pin_digest(dns_pins) == "":
            raise GovernedAwayError("DNS pin digest is unavailable")
        # Dispatch preflight is authoritative and never trusts the informational
        # availability cache.
        ready, reason = self._probe_available()
        if not ready:
            raise GovernedAwayWaiting(
                f"Chromium runtime unavailable before dispatch: {reason}"
            )

    @staticmethod
    def _install_transport_policy(context: Any, flags: set[str]) -> None:
        """Deny every non-HTTP browser transport before navigation."""

        def deny_websocket(route: Any) -> None:
            flags.add("websocket_blocked")
            route.close()

        # Exact API provided by the installed Playwright version. Registering
        # before navigation covers every WebSocket created by the target page.
        context.route_web_socket("**/*", deny_websocket)
        context.add_init_script(
            script="""
(() => {
  const deny = (name) => class {
    constructor() { throw new DOMException(name + " denied by Onyx Away", "SecurityError"); }
  };
  for (const name of ["RTCPeerConnection", "webkitRTCPeerConnection", "WebTransport"]) {
    try {
      Object.defineProperty(globalThis, name, {
        value: deny(name), writable: false, configurable: false
      });
    } catch (_) {}
  }
})();
"""
        )

    def stop(self, mission_id: str, *, timeout: float) -> bool:
        with self._lock:
            active = self._active.get(mission_id)
        if active is None:
            return True
        active.stop_requested.set()
        if not active.closed.wait(timeout=max(0.0, timeout)):
            return False
        if active.stop_error is not None:
            raise GovernedAwayError(
                "Playwright owner-thread shutdown failed"
            ) from active.stop_error
        return True

    def execute(
        self,
        *,
        envelope: BrowserActionEnvelopeV1,
        profile_dir: Path,
        publish_artifact: Callable[[str, bytes], str],
        cancel: Callable[[], bool],
        control: AwayControlV1,
        runtime_deadline: BrowserRuntimeDeadlineV1,
        dns_pins: Mapping[str, tuple[str, ...]],
    ) -> Mapping[str, Any]:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        profile_dir.mkdir(parents=True, exist_ok=True)
        _harden_mode(profile_dir)
        flags: set[str] = set()
        request_count = 0
        started = time.monotonic()
        playwright = sync_playwright().start()
        executable = Path(playwright.chromium.executable_path)
        if not executable.is_file():
            playwright.stop()
            raise GovernedAwayWaiting(
                "Chromium runtime unavailable after dispatch: "
                "chromium-executable-missing"
            )
        context = None
        run_state = _DriverRunState(threading.Event(), threading.Event())
        with self._lock:
            if envelope.mission_id in self._active:
                raise GovernedAwayError("Playwright mission is already active")
            self._active[envelope.mission_id] = run_state
        cleanup_errors: list[BaseException] = []
        try:
            control.wait_until_running(cancel)
            runtime_deadline.assert_active()
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                executable_path=str(executable),
                accept_downloads=False,
                service_workers="block",
                viewport={"width": 1365, "height": 768},
                args=[
                    "--no-first-run",
                    "--disable-default-apps",
                    "--no-default-browser-check",
                    "--disable-quic",
                    "--disable-webrtc",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--disable-blink-features=WebRTC,WebTransport",
                    *_chromium_resolver_args(dns_pins),
                ],
            )
            self._install_transport_policy(context, flags)
            pages = list(context.pages)
            page = pages[0] if pages else context.new_page()

            def route_guard(route: Any) -> None:
                nonlocal request_count
                try:
                    request_count += 1
                    if request_count > envelope.network_request_budget:
                        flags.add("network_budget_exhausted")
                        route.abort()
                        return
                    if (
                        cancel()
                        or run_state.stop_requested.is_set()
                        or control.state in {"paused", "takeover", "killed"}
                    ):
                        flags.add("cancelled_or_terminal")
                        route.abort()
                        return
                    request_parts = urlsplit(route.request.url)
                    host = (request_parts.hostname or "").rstrip(".").casefold()
                    scheme = request_parts.scheme.casefold()
                    if scheme in {"data", "blob", "about"}:
                        route.continue_()
                    elif scheme == "https" and host in envelope.allowed_domains:
                        if _resolve_public_host(host) != dns_pins[host]:
                            flags.add("dns_rebinding_detected")
                            route.abort()
                            return
                        route.continue_()
                    else:
                        flags.add("network_target_denied")
                        route.abort()
                except Exception:
                    flags.add("network_guard_error")
                    route.abort()

            context.route("**/*", route_guard)

            def on_dialog(dialog: Any) -> None:
                flags.add("unexpected_dialog")
                try:
                    dialog.dismiss()
                except Exception:
                    pass

            def on_download(download: Any) -> None:
                flags.add("download_blocked")
                try:
                    download.cancel()
                except Exception:
                    pass

            def on_page(new_page: Any) -> None:
                if new_page is not page:
                    flags.add("unexpected_popup")
                    try:
                        new_page.close()
                    except Exception:
                        pass

            page.on("dialog", on_dialog)
            page.on("download", on_download)
            context.on("page", on_page)
            control.wait_until_running(cancel)
            if _resolve_public_host(envelope.target_domain) != dns_pins[
                envelope.target_domain
            ]:
                raise GovernedAwayWaiting("DNS changed after pin creation")
            while True:
                runtime_deadline.assert_active()
                if (
                    cancel()
                    or run_state.stop_requested.is_set()
                    or control.state in {"paused", "takeover", "killed"}
                ):
                    raise GovernedAwayWaiting(
                        "browser navigation stopped by owner control"
                    )
                try:
                    page.goto(
                        envelope.target_url,
                        wait_until="domcontentloaded",
                        timeout=int(_NAVIGATION_POLL_SECONDS * 1_000),
                    )
                    break
                except PlaywrightTimeoutError:
                    continue
            control.wait_until_running(cancel)
            if time.monotonic() - started > envelope.max_seconds:
                raise GovernedAwayWaiting("browser action exceeded its signed time bound")
            final_url, final_origin, final_domain = _canonical_url(page.url)
            if (
                final_url != envelope.target_url
                or final_domain not in envelope.allowed_domains
                or final_domain != envelope.target_domain
                or final_origin != envelope.target_origin
            ):
                raise GovernedAwayWaiting("browser target changed outside the signed target")
            if _resolve_public_host(final_domain) != dns_pins[final_domain]:
                raise GovernedAwayWaiting("DNS changed during observation")
            if flags:
                raise GovernedAwayWaiting("browser policy interruption: " + ",".join(sorted(flags)))
            sensitive_selectors = (
                "input[type=password], input[autocomplete*=one-time-code], "
                "input[autocomplete*=cc-], iframe[src*=captcha i], "
                "iframe[title*=captcha i], [data-sitekey]"
            )
            if page.locator(sensitive_selectors).count() > 0:
                raise GovernedAwayWaiting("owner login, MFA, payment, or CAPTCHA is required")
            body = _bounded_utf8(
                _redact_text(page.locator("body").inner_text(timeout=10_000)),
                envelope.output_byte_budget,
            )
            body_raw = body.encode("utf-8")
            screenshot_ref = None
            screenshot_sha256 = None
            screenshot_bytes = 0
            if envelope.capture_screenshot:
                page.add_style_tag(
                    content=(
                        "input,textarea,[contenteditable=true],[data-private],"
                        "[aria-label*=password i],[aria-label*=email i],"
                        "[aria-label*=card i]{filter:blur(14px)!important;"
                        "color:transparent!important;text-shadow:none!important}"
                    )
                )
                raw = page.screenshot(full_page=False)
                if not isinstance(raw, bytes) or not raw:
                    raise GovernedAwayWaiting(
                        "browser screenshot could not be protected"
                    )
                screenshot_sha256 = hashlib.sha256(raw).hexdigest()
                screenshot_bytes = len(raw)
                screenshot_ref = publish_artifact("screenshot", raw)
            # Events can arrive while DOM text or the screenshot is being
            # collected.  Recheck every terminal boundary immediately before
            # reporting a successful driver result.
            control.wait_until_running(cancel)
            if (
                cancel()
                or run_state.stop_requested.is_set()
                or control.state in {"paused", "takeover", "killed"}
            ):
                raise GovernedAwayWaiting(
                    "browser action was cancelled before final commit"
                )
            if time.monotonic() - started > envelope.max_seconds:
                raise GovernedAwayWaiting(
                    "browser action exceeded its signed time bound"
                )
            final_url, final_origin, final_domain = _canonical_url(page.url)
            if (
                final_url != envelope.target_url
                or final_origin != envelope.target_origin
                or final_domain != envelope.target_domain
                or final_domain not in envelope.allowed_domains
            ):
                raise GovernedAwayWaiting(
                    "browser target changed before final commit"
                )
            if _resolve_public_host(final_domain) != dns_pins[final_domain]:
                raise GovernedAwayWaiting("DNS changed before final commit")
            runtime_deadline.assert_active()
            if flags:
                raise GovernedAwayWaiting(
                    "browser policy interruption: " + ",".join(sorted(flags))
                )
            if page.locator(sensitive_selectors).count() > 0:
                raise GovernedAwayWaiting(
                    "owner login, MFA, payment, or CAPTCHA appeared late"
                )
            return {
                "status": "succeeded",
                "final_url": final_url,
                "final_origin": final_origin,
                "final_domain": final_domain,
                "text_sha256": hashlib.sha256(body_raw).hexdigest(),
                "text_bytes": len(body_raw),
                "artifact_ref": screenshot_ref,
                "screenshot_sha256": screenshot_sha256,
                "screenshot_bytes": screenshot_bytes,
                "policy_flags": [],
                "clipboard": "not_accessed",
                "downloads": "blocked",
                "uploads": "unsupported",
                "headed_preview": True,
            }
        finally:
            with self._lock:
                self._active.pop(envelope.mission_id, None)
            if context is not None:
                try:
                    context.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                playwright.stop()
            except BaseException as exc:
                cleanup_errors.append(exc)
            run_state.stop_error = cleanup_errors[0] if cleanup_errors else None
            run_state.closed.set()
            if cleanup_errors:
                raise GovernedAwayError(
                    "Playwright owner-thread cleanup failed"
                ) from cleanup_errors[0]


class GovernedAwayModeV1:
    def __init__(
        self,
        *,
        root: Path,
        signing_key: bytes,
        enabled: bool,
        driver: BrowserDriverV1 | None = None,
    ) -> None:
        self.root = Path(root)
        self.signing_key = bytes(signing_key)
        self.enabled = enabled is True
        self.driver = driver or PlaywrightBrowserDriverV1()
        self._lock = threading.RLock()
        self._active: dict[str, _ActiveRun] = {}
        self._controls: dict[str, AwayControlV1] = {}
        self._store: _SecureAwayStoreV1 | None = None
        if self.enabled:
            self._store = _SecureAwayStoreV1(self.root)

    def availability(self) -> dict[str, object]:
        browser_ready, reason = (
            self.driver.available()
            if isinstance(self.driver, PlaywrightBrowserDriverV1)
            else (True, "injected-driver")
        )
        killed = os.path.lexists(self._global_kill_path())
        kill_reason = None
        if killed:
            try:
                self._global_killed()
                kill_reason = "global_kill_latched"
            except GovernedAwayError:
                kill_reason = "global_kill_invalid_fail_closed"
        return {
            "browser": self.enabled and browser_ready and not killed,
            "browser_reason": kill_reason if killed else reason,
            "browser_mode": "headed_isolated_read_only",
            "computer": False,
            "computer_reason": "no_verified_window_dpi_driver",
            "mutations": False,
        }

    def _global_kill_path(self) -> Path:
        return self.root / "global-kill.json"

    def _attempt_path(self, mission_id: str) -> Path:
        _mission_id(mission_id)
        return self.root / "attempts" / f"{mission_id}.intent.json"

    def _receipt_path(self, mission_id: str) -> Path:
        _mission_id(mission_id)
        return self.root / "attempts" / f"{mission_id}.receipt.json"

    def _write_once(
        self,
        path: Path,
        *,
        domain: bytes,
        payload: Mapping[str, object],
    ) -> bool:
        unsigned = dict(payload)
        record = {
            **unsigned,
            "signature": hmac.new(
                self.signing_key,
                _CONTROL_DOMAIN + domain + _canonical(unsigned),
                hashlib.sha256,
            ).hexdigest(),
        }
        if self._store is None:
            raise GovernedAwayError("Away secure storage is unavailable")
        relative = path.relative_to(self.root).as_posix()
        created = self._store.publish_once(relative, _canonical(record))
        if not created:
            self._read_signed(path, domain=domain)
        return created

    def _read_signed(self, path: Path, *, domain: bytes) -> dict[str, object]:
        if self._store is None:
            raise GovernedAwayError("Away secure storage is unavailable")
        try:
            raw = self._store.read(
                path.relative_to(self.root).as_posix(),
                max_bytes=64 * 1024,
            )
            record = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GovernedAwayError("Away attempt record is unreadable") from exc
        if not isinstance(record, dict) or "signature" not in record:
            raise GovernedAwayError("Away attempt record is malformed")
        unsigned = {key: value for key, value in record.items() if key != "signature"}
        expected = hmac.new(
            self.signing_key,
            _CONTROL_DOMAIN + domain + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(str(record.get("signature", "")), expected):
            raise GovernedAwayError("Away attempt record authentication failed")
        return record

    def reconciliation_status(self, mission_id: str) -> dict[str, object]:
        intent_path = self._attempt_path(mission_id)
        receipt_path = self._receipt_path(mission_id)
        intent = (
            self._read_signed(intent_path, domain=b"INTENT\0")
            if intent_path.exists()
            else None
        )
        receipt = (
            self._read_signed(receipt_path, domain=b"RECEIPT\0")
            if receipt_path.exists()
            else None
        )
        return {
            "intent_persisted": intent is not None,
            "receipt_persisted": receipt is not None,
            "attempt_state": (
                "receipt_persisted"
                if receipt is not None
                else "attempted_unknown"
                if intent is not None
                else "not_started"
            ),
            "redispatch_permitted": False,
        }

    def _control(self, mission_id: str) -> AwayControlV1:
        _mission_id(mission_id)
        with self._lock:
            control = self._controls.get(mission_id)
            if control is None:
                control = AwayControlV1(
                    mission_id,
                    self._require_store(),
                    self.signing_key,
                )
                self._controls[mission_id] = control
            return control

    def _global_killed(self) -> bool:
        path = self._global_kill_path()
        if not os.path.lexists(path):
            return False
        if self._store is None:
            raise GovernedAwayError("Away secure storage is unavailable")
        try:
            raw = self._store.read("global-kill.json", max_bytes=8_192)
            record = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise GovernedAwayError("global Away kill record is unreadable") from exc
        unsigned = {key: value for key, value in record.items() if key != "signature"}
        expected = hmac.new(
            self.signing_key,
            _CONTROL_DOMAIN + b"GLOBAL\0" + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if (
            set(record) != {"schema", "state", "issued_at_ns", "signature"}
            or record["schema"] != CONTROL_SCHEMA
            or record["state"] != "killed"
            or not hmac.compare_digest(str(record["signature"]), expected)
        ):
            raise GovernedAwayError("global Away kill authentication failed")
        return True

    def latch_global_kill(self) -> None:
        with self._lock:
            if not os.path.lexists(self._global_kill_path()):
                unsigned = {
                    "schema": CONTROL_SCHEMA,
                    "state": "killed",
                    "issued_at_ns": time.time_ns(),
                }
                record = {
                    **unsigned,
                    "signature": hmac.new(
                        self.signing_key,
                        _CONTROL_DOMAIN + b"GLOBAL\0" + _canonical(unsigned),
                        hashlib.sha256,
                    ).hexdigest(),
                }
                if not self._require_store().publish_once(
                    "global-kill.json",
                    _canonical(record),
                ):
                    self._global_killed()
            else:
                self._global_killed()
            # The caller must next persist each MissionStore kill record before
            # signaling its driver.  Merely latching the global boundary never
            # terminates a process.

    def control(self, mission_id: str, state: str) -> dict[str, object]:
        if self._global_killed():
            raise GovernedAwayError("global Away kill is latched")
        control = self._control(mission_id)
        control.set(state)
        if state in {"paused", "takeover"}:
            with self._lock:
                active = self._active.get(mission_id)
            if active is not None:
                try:
                    stopped = active.driver.stop(
                        mission_id,
                        timeout=_STOP_ACK_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    raise GovernedAwayError(
                        "Away driver stop failed"
                    ) from exc
                if not stopped:
                    raise GovernedAwayWaiting(
                        "Away owner control persisted but driver stop is incomplete"
                    )
        return {
            "mission_id": mission_id,
            "away_control_state": control.state,
            "durable": True,
        }

    def kill(self, mission_id: str) -> None:
        control = self._control(mission_id)
        control.set("killed")
        with self._lock:
            active = self._active.get(mission_id)
        if active is not None:
            try:
                stopped = active.driver.stop(
                    mission_id,
                    timeout=_STOP_ACK_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                raise GovernedAwayError("Away driver stop failed") from exc
            if not stopped:
                raise GovernedAwayWaiting(
                    "Away kill persisted but driver stop is incomplete"
                )

    def _require_store(self) -> _SecureAwayStoreV1:
        if self._store is None:
            raise GovernedAwayError("Away secure storage is unavailable")
        return self._store

    def _global_stop_requested(self) -> bool:
        """The existence of any latch blocks execution, even when it is corrupt."""

        return os.path.lexists(self._global_kill_path())

    def active_missions(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._active))

    def stop_all_for_global_kill(self) -> dict[str, object]:
        """Stop every active driver after the durable global latch exists."""

        if not self._global_stop_requested():
            raise GovernedAwayError("global Away kill is not latched")
        failures: list[str] = []
        with self._lock:
            active = tuple(self._active.items())
        for mission_id, run in active:
            try:
                stopped = run.driver.stop(
                    mission_id,
                    timeout=_STOP_ACK_TIMEOUT_SECONDS,
                )
                if not stopped:
                    failures.append(f"{mission_id}:stop_timeout")
            except Exception as exc:
                failures.append(f"{mission_id}:{type(exc).__name__}")
        return {
            "stopped": [mission_id for mission_id, _run in active],
            "failures": failures,
        }

    def stop_all_for_shutdown(self) -> dict[str, object]:
        """Stop active owner-thread drivers after per-mission durable kills."""

        failures: list[str] = []
        with self._lock:
            active = tuple(self._active.items())
        for mission_id, run in active:
            try:
                if not run.driver.stop(
                    mission_id,
                    timeout=_STOP_ACK_TIMEOUT_SECONDS,
                ):
                    failures.append(f"{mission_id}:stop_timeout")
            except Exception as exc:
                failures.append(f"{mission_id}:{type(exc).__name__}")
        return {
            "stopped": [mission_id for mission_id, _run in active],
            "failures": failures,
        }

    def close(self) -> None:
        with self._lock:
            if self._active:
                raise GovernedAwayError(
                    "cannot close Away storage while browser actions are active"
                )
        if self._store is not None:
            self._store.close()
            self._store = None

    def _publish_artifact(
        self,
        mission_id: str,
        kind: str,
        content: bytes,
    ) -> str:
        _mission_id(mission_id)
        if kind != "screenshot" or not isinstance(content, bytes) or not content:
            raise GovernedAwayError("Away browser artifact is invalid")
        relative = f"artifacts/{mission_id}.redacted.png"
        if not self._require_store().publish_once(relative, content):
            raise GovernedAwayError("Away browser artifact already exists")
        return f"away-artifact-v1:{mission_id}:screenshot"

    def _validate_driver_output(
        self,
        envelope: BrowserActionEnvelopeV1,
        output: Mapping[str, object],
    ) -> dict[str, object]:
        expected = {
            "status",
            "final_url",
            "final_origin",
            "final_domain",
            "text_sha256",
            "text_bytes",
            "artifact_ref",
            "screenshot_sha256",
            "screenshot_bytes",
            "policy_flags",
            "clipboard",
            "downloads",
            "uploads",
            "headed_preview",
        }
        if set(output) != expected or output.get("status") != "succeeded":
            raise GovernedAwayError("browser driver returned an invalid outcome")
        final_url, final_origin, final_domain = _canonical_url(
            output.get("final_url")
        )
        if (
            final_url != envelope.target_url
            or final_origin != envelope.target_origin
            or final_domain != envelope.target_domain
            or final_domain not in envelope.allowed_domains
        ):
            raise GovernedAwayWaiting("browser driver reported the wrong target")
        if output.get("policy_flags") != []:
            raise GovernedAwayWaiting("browser driver reported a late policy event")
        text_sha256 = output.get("text_sha256")
        text_bytes = output.get("text_bytes")
        if (
            not isinstance(text_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", text_sha256) is None
            or isinstance(text_bytes, bool)
            or not isinstance(text_bytes, int)
            or not 0 <= text_bytes <= envelope.output_byte_budget
        ):
            raise GovernedAwayError("browser text evidence is invalid")
        artifact_ref = output.get("artifact_ref")
        screenshot_sha256 = output.get("screenshot_sha256")
        screenshot_bytes = output.get("screenshot_bytes")
        if envelope.capture_screenshot:
            expected_ref = (
                f"away-artifact-v1:{envelope.mission_id}:screenshot"
            )
            if (
                artifact_ref != expected_ref
                or not isinstance(screenshot_sha256, str)
                or re.fullmatch(r"[0-9a-f]{64}", screenshot_sha256) is None
                or isinstance(screenshot_bytes, bool)
                or not isinstance(screenshot_bytes, int)
                or not 1 <= screenshot_bytes <= _MAX_ARTIFACT_BYTES
            ):
                raise GovernedAwayError("browser screenshot evidence is invalid")
            raw = self._require_store().read(
                f"artifacts/{envelope.mission_id}.redacted.png",
                max_bytes=_MAX_ARTIFACT_BYTES,
            )
            if (
                len(raw) != screenshot_bytes
                or hashlib.sha256(raw).hexdigest() != screenshot_sha256
            ):
                raise GovernedAwayError(
                    "browser screenshot artifact failed containment or digest validation"
                )
        elif (
            artifact_ref is not None
            or screenshot_sha256 is not None
            or screenshot_bytes != 0
        ):
            raise GovernedAwayError(
                "browser returned an unauthorized screenshot artifact"
            )
        if (
            output.get("clipboard") != "not_accessed"
            or output.get("downloads") != "blocked"
            or output.get("uploads") != "unsupported"
            or output.get("headed_preview") is not True
        ):
            raise GovernedAwayError("browser boundary claims are invalid")
        return {
            "final_origin": final_origin,
            "final_domain": final_domain,
            "text_sha256": text_sha256,
            "text_bytes": text_bytes,
            "artifact_ref": artifact_ref,
            "screenshot_sha256": screenshot_sha256,
            "screenshot_bytes": screenshot_bytes,
        }

    def _final_stop_check(
        self,
        envelope: BrowserActionEnvelopeV1,
        runtime_deadline: BrowserRuntimeDeadlineV1,
        control: AwayControlV1,
        cancel: Callable[[], bool],
    ) -> None:
        if (
            cancel()
            or self._global_stop_requested()
            or control.state in {"paused", "takeover", "killed"}
        ):
            raise GovernedAwayWaiting(
                "late browser result discarded after cancel, takeover, or kill"
            )
        envelope.authenticate(self.signing_key, require_active=False)
        runtime_deadline.authenticate(self.signing_key, envelope)

    def _resolve_dns_pins(
        self, envelope: BrowserActionEnvelopeV1
    ) -> dict[str, tuple[str, ...]]:
        resolver = getattr(self.driver, "resolve_public_host", _resolve_public_host)
        pins = {
            domain: tuple(resolver(domain))
            for domain in envelope.allowed_domains
        }
        _dns_pin_digest(pins)
        return pins

    def status(self, mission_id: str) -> dict[str, object]:
        control = self._control(mission_id)
        with self._lock:
            active = mission_id in self._active
        return {
            **self.availability(),
            "control_state": control.state,
            "active": active,
            **self.reconciliation_status(mission_id),
        }

    def execute(
        self,
        *,
        envelope: BrowserActionEnvelopeV1,
        binding_digest: str,
        execution_id_digest: str,
        approved_deadline_ns: int,
        cancel: Callable[[], bool],
    ) -> dict[str, Any]:
        if not self.enabled:
            raise GovernedAwayError("governed Away Mode is disabled")
        if self._global_stop_requested():
            self._global_killed()
            raise GovernedAwayWaiting("global Away kill is latched")
        envelope.authenticate(self.signing_key, require_active=False)
        if re.fullmatch(r"[0-9a-f]{64}", binding_digest) is None:
            raise GovernedAwayError("binding digest is invalid")
        availability = self.availability()
        if availability["browser"] is not True:
            raise GovernedAwayWaiting(
                f"browser capability unavailable: {availability['browser_reason']}"
            )
        control = self._control(envelope.mission_id)
        if control.state in {"paused", "takeover", "killed"}:
            raise GovernedAwayWaiting("Away mission is terminal")
        control.wait_until_running(cancel)
        dns_pins = self._resolve_dns_pins(envelope)
        runtime_deadline = BrowserRuntimeDeadlineV1.build(
            signing_key=self.signing_key,
            envelope=envelope,
            binding_digest=binding_digest,
            execution_id_digest=execution_id_digest,
            dns_pin_digest=_dns_pin_digest(dns_pins),
            approved_deadline_ns=approved_deadline_ns,
        )
        runtime_deadline.authenticate(self.signing_key, envelope)
        preflight = getattr(self.driver, "preflight", None)
        if callable(preflight):
            preflight(envelope=envelope, dns_pins=dns_pins)
        elif isinstance(self.driver, PlaywrightBrowserDriverV1):
            raise GovernedAwayWaiting("Chromium runtime preflight is unavailable")
        runtime_deadline.authenticate(self.signing_key, envelope)
        intent = {
            "schema": "onyx.phase11.away_attempt_intent.v1",
            "mission_id": envelope.mission_id,
            "away_session_id": envelope.away_session_id,
            "lease_generation": envelope.lease_generation,
            "intent_digest": envelope.intent_digest,
            "binding_digest": binding_digest,
            "approval_digest": envelope.approval_digest,
            "runtime_deadline_digest": hashlib.sha256(
                _canonical(asdict(runtime_deadline))
            ).hexdigest(),
            "dns_pin_digest": runtime_deadline.dns_pin_digest,
            "issued_at_ns": time.time_ns(),
        }
        if not self._write_once(
            self._attempt_path(envelope.mission_id),
            domain=b"INTENT\0",
            payload=intent,
        ):
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": (
                    "attempted_unknown: durable intent already exists; "
                    "automatic redispatch is forbidden"
                ),
            }
        profile_key = hashlib.sha256(
            (
                f"{envelope.workspace_id}\0{envelope.target_domain}\0"
                f"{envelope.away_session_id}\0{envelope.mission_id}"
            ).encode("utf-8")
        ).hexdigest()[:32]
        profile_dir = self._require_store().ensure_directory(
            "profiles/"
            f"{envelope.profile_id}/"
            f"{envelope.away_session_id}/"
            f"{profile_key}"
        )
        profile_guard = _ProfileIdentityGuardV1(profile_dir)
        active = _ActiveRun(
            control=control,
            driver=self.driver,
            profile_dir=profile_dir,
        )

        def stop_requested() -> bool:
            return cancel() or self._global_stop_requested()

        with self._lock:
            if envelope.mission_id in self._active:
                raise GovernedAwayWaiting("duplicate browser action is already active")
            self._active[envelope.mission_id] = active
        profile_cleanup_status = "pending"
        try:
            try:
                output = dict(
                    self.driver.execute(
                        envelope=envelope,
                        profile_dir=profile_dir,
                        publish_artifact=lambda kind, content: self._publish_artifact(
                            envelope.mission_id,
                            kind,
                            content,
                        ),
                        cancel=stop_requested,
                        control=control,
                        runtime_deadline=runtime_deadline,
                        dns_pins=dns_pins,
                    )
                )
            except GovernedAwayWaiting as exc:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": _redact_text(exc),
                }
            except Exception as exc:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": (
                        "attempted_unknown: browser action outcome requires "
                        f"reconciliation ({type(exc).__name__})"
                    ),
                }
        except GovernedAwayWaiting as exc:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": _redact_text(exc),
            }
        finally:
            try:
                profile_cleanup_status = profile_guard.close_and_discard()
            except Exception as exc:
                return {
                    "status": "waiting",
                    "data": None,
                    "evidence": [],
                    "postconditions": [],
                    "waiting_for": (
                        "attempted_unknown: Away profile cleanup requires "
                        f"reconciliation ({type(exc).__name__})"
                    ),
                }
            finally:
                with self._lock:
                    self._active.pop(envelope.mission_id, None)
        try:
            self._final_stop_check(
                envelope, runtime_deadline, control, cancel
            )
        except GovernedAwayWaiting as exc:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": _redact_text(exc),
            }
        try:
            verified = self._validate_driver_output(envelope, output)
            self._final_stop_check(
                envelope, runtime_deadline, control, cancel
            )
        except GovernedAwayWaiting as exc:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": _redact_text(exc),
            }
        except GovernedAwayError as exc:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": (
                    "attempted_unknown: browser evidence validation requires "
                    f"reconciliation ({type(exc).__name__})"
                ),
            }
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "mission_id": envelope.mission_id,
            "principal_id": envelope.principal_id,
            "away_session_id": envelope.away_session_id,
            "lease_generation": envelope.lease_generation,
            "workspace_id": envelope.workspace_id,
            "profile_id": envelope.profile_id,
            "provider_id": envelope.provider_id,
            "account_id": envelope.account_id,
            "action": envelope.action,
            "target_origin": envelope.target_origin,
            "target_domain": envelope.target_domain,
            "final_origin": verified["final_origin"],
            "final_domain": verified["final_domain"],
            "intent_digest": envelope.intent_digest,
            "binding_digest": binding_digest,
            "approval_digest": envelope.approval_digest,
            "runtime_deadline_digest": hashlib.sha256(
                _canonical(asdict(runtime_deadline))
            ).hexdigest(),
            "dns_pin_digest": runtime_deadline.dns_pin_digest,
            "key_epoch": envelope.key_epoch,
            "text_sha256": verified["text_sha256"],
            "text_bytes": verified["text_bytes"],
            "artifact_ref": verified["artifact_ref"],
            "screenshot_sha256": verified["screenshot_sha256"],
            "screenshot_bytes": verified["screenshot_bytes"],
            "clipboard": "not_accessed",
            "downloads": "blocked",
            "uploads": "unsupported",
            "headed_preview": True,
            "profile_cleanup": profile_cleanup_status,
            "completed_at_ns": time.time_ns(),
        }
        receipt["receipt_hmac_sha256"] = hmac.new(
            self.signing_key,
            _ENVELOPE_DOMAIN + b"RECEIPT\0" + _canonical(receipt),
            hashlib.sha256,
        ).hexdigest()
        if not self._write_once(
            self._receipt_path(envelope.mission_id),
            domain=b"RECEIPT\0",
            payload=receipt,
        ):
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": (
                    "attempted_unknown: duplicate Away receipt detected; "
                    "automatic success is forbidden"
                ),
            }
        try:
            self._final_stop_check(
                envelope, runtime_deadline, control, cancel
            )
        except GovernedAwayWaiting as exc:
            return {
                "status": "waiting",
                "data": None,
                "evidence": [],
                "postconditions": [],
                "waiting_for": _redact_text(exc),
            }
        return {
            "status": "succeeded",
            "data": {
                "observation": {
                    "text_sha256": verified["text_sha256"],
                    "text_bytes": verified["text_bytes"],
                    "artifact_ref": verified["artifact_ref"],
                    "screenshot_sha256": verified["screenshot_sha256"],
                    "screenshot_bytes": verified["screenshot_bytes"],
                    "profile_cleanup": profile_cleanup_status,
                },
                "receipt": receipt,
            },
            "evidence": [
                {
                    "type": "browser_observation",
                    "ref": verified["artifact_ref"]
                    or f"sha256:{verified['text_sha256']}",
                }
            ],
            "postconditions": [
                {"name": "exact_target_observed", "satisfied": True},
                {"name": "sensitive_fields_redacted", "satisfied": True},
                {"name": "no_clipboard_or_download_access", "satisfied": True},
            ],
            "waiting_for": None,
        }
