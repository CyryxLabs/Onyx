"""Internal cross-platform access to the current user's native secret vault.

This module has no environment or file fallback.  Callers must use an explicit,
bounded service/account namespace.  The public application credential API lives
in :mod:`core.credentials`; this module is intentionally a small host primitive.
"""
from __future__ import annotations

import base64
import ctypes
import os
import platform
import re
import stat
import subprocess
import weakref
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_MAX_LABEL_CHARS = 160
_MAX_SECRET_BYTES = 2048
_LINUX_BINARY_PREFIX = "onyx-native-binary-v1:"
_ERR_SEC_SUCCESS = 0
_ERR_SEC_ITEM_NOT_FOUND = -25300
_DOMAIN_ANCHOR_SERVICE_PREFIX = "Onyx.DomainLedgerAnchor"
_PHASE11_ANCHOR_SERVICE_PREFIXES = (
    "Onyx.Phase11AuthorityAnchor",
    "Onyx.Phase11AuthorityCheckpoint",
    "Onyx.Phase11AutopilotCheckpoint",
)
_ISSUED_ANCHOR_CAPABILITIES: weakref.WeakKeyDictionary[
    _AnchorNamespaceCapability, tuple[bytes, weakref.ReferenceType[object]]
] = weakref.WeakKeyDictionary()
_PHASE11_ANCHOR_CAPABILITIES: weakref.WeakKeyDictionary[
    object, weakref.ReferenceType[object]
] = weakref.WeakKeyDictionary()


class NativeVaultError(RuntimeError):
    """A safe-to-display native vault failure that never contains a secret."""


class _AnchorNamespaceCapability:
    __slots__ = ("_factory", "_token", "__weakref__")

    def __init__(self, token: bytes, factory: object):
        self._token = token
        self._factory = factory

    def __copy__(self):
        raise TypeError("Anchor vault capability cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("Anchor vault capability cannot be copied")

    def __reduce__(self):
        raise TypeError("Anchor vault capability cannot be serialized")


def _bind_anchor_namespace_owner(owner: object) -> _AnchorNamespaceCapability:
    try:
        owner_reference = weakref.ref(owner)
    except TypeError as exc:
        raise TypeError("Anchor vault owner must be weak-referenceable") from exc
    capability = _AnchorNamespaceCapability(os.urandom(32), object())
    _ISSUED_ANCHOR_CAPABILITIES[capability] = (
        capability._token,
        owner_reference,
    )
    return capability


def _anchor_capability_valid(capability: object) -> bool:
    if not isinstance(capability, _AnchorNamespaceCapability):
        return False
    issued = _ISSUED_ANCHOR_CAPABILITIES.get(capability)
    return (
        issued is not None
        and issued[1]() is not None
        and hmac_compare(issued[0], capability._token)
    )


def _register_phase11_anchor_capability(
    capability: object, owner: object
) -> None:
    try:
        owner_reference = weakref.ref(owner)
        weakref.ref(capability)
    except TypeError as exc:
        raise TypeError(
            "Phase 11 anchor authority must be weak-referenceable"
        ) from exc
    _PHASE11_ANCHOR_CAPABILITIES[capability] = owner_reference


def _unregister_phase11_anchor_capability(
    capability: object, owner: object
) -> None:
    """Revoke a partially initialized Phase 11 anchor authority."""

    try:
        owner_reference = _PHASE11_ANCHOR_CAPABILITIES.get(capability)
    except TypeError:
        return
    if owner_reference is not None and owner_reference() is owner:
        _PHASE11_ANCHOR_CAPABILITIES.pop(capability, None)


def _phase11_anchor_capability_valid(capability: object) -> bool:
    try:
        owner = _PHASE11_ANCHOR_CAPABILITIES.get(capability)
    except TypeError:
        return False
    return owner is not None and owner() is not None


def hmac_compare(left: bytes, right: bytes) -> bool:
    # Local import keeps the native primitive dependency surface small.
    import hmac

    return hmac.compare_digest(left, right)


@dataclass(frozen=True, slots=True)
class SecretReference:
    service: str
    account: str
    label: str

    def __post_init__(self) -> None:
        if not isinstance(self.service, str) or not _NAME.fullmatch(self.service):
            raise NativeVaultError("Native vault service namespace is invalid")
        if not isinstance(self.account, str) or not _NAME.fullmatch(self.account):
            raise NativeVaultError("Native vault account namespace is invalid")
        if (
            not isinstance(self.label, str)
            or not self.label.strip()
            or len(self.label) > _MAX_LABEL_CHARS
            or any(ord(character) < 32 for character in self.label)
        ):
            raise NativeVaultError("Native vault label is invalid")


def _check_reference(
    reference: SecretReference, capability: _AnchorNamespaceCapability | None
) -> None:
    if not isinstance(reference, SecretReference):
        raise TypeError("reference must be a SecretReference")
    if reference.service.startswith(
        _DOMAIN_ANCHOR_SERVICE_PREFIX
    ) and not _anchor_capability_valid(capability):
        raise NativeVaultError("Protected anchor vault namespace is unavailable")
    if any(
        reference.service.startswith(prefix)
        for prefix in _PHASE11_ANCHOR_SERVICE_PREFIXES
    ) and not _phase11_anchor_capability_valid(capability):
        raise NativeVaultError("Protected anchor vault namespace is unavailable")


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _bounded_secret(secret: bytes | bytearray) -> bytes:
    if not isinstance(secret, (bytes, bytearray)):
        raise TypeError("secret must be bytes")
    value = bytes(secret)
    if not value or len(value) > _MAX_SECRET_BYTES:
        raise NativeVaultError("Native vault secret size is invalid")
    return value


def _win_api() -> Any:
    try:
        return ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    except (AttributeError, OSError) as exc:
        raise NativeVaultError("Windows Credential Manager is unavailable") from exc


def windows_get(
    reference: SecretReference,
    *,
    api_factory: Callable[[], Any] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
    legacy_target: bool = False,
) -> bytes | None:
    _check_reference(reference, capability)
    api = (api_factory or _win_api)()
    target = reference.service if legacy_target else f"{reference.service}:{reference.account}"
    pointer = ctypes.POINTER(_CREDENTIALW)()
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
    ]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [wintypes.LPVOID]
    api.CredFree.restype = None
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise NativeVaultError("Windows Credential Manager could not read the secret")
    try:
        item = pointer.contents
        if item.CredentialBlobSize > _MAX_SECRET_BYTES:
            raise NativeVaultError("Windows Credential Manager returned oversized data")
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
    finally:
        api.CredFree(pointer)


def windows_set(
    reference: SecretReference,
    secret: bytes | bytearray,
    *,
    api_factory: Callable[[], Any] | None = None,
    wipe: Callable[[int, int, int], Any] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
    legacy_target: bool = False,
) -> None:
    _check_reference(reference, capability)
    raw = bytearray(_bounded_secret(secret))
    api = (api_factory or _win_api)()
    wipe_secret = wipe or ctypes.memset
    blob = (ctypes.c_ubyte * len(raw)).from_buffer(raw)
    credential = _CREDENTIALW()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = (
        reference.service if legacy_target else f"{reference.service}:{reference.account}"
    )
    credential.Comment = reference.label
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE; protected per user
    credential.UserName = reference.account
    api.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    try:
        if not api.CredWriteW(ctypes.byref(credential), 0):
            raise NativeVaultError("Windows Credential Manager could not store the secret")
    finally:
        wipe_secret(ctypes.addressof(blob), 0, len(raw))


def windows_delete(
    reference: SecretReference,
    *,
    api_factory: Callable[[], Any] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
    legacy_target: bool = False,
) -> bool:
    _check_reference(reference, capability)
    api = (api_factory or _win_api)()
    target = reference.service if legacy_target else f"{reference.service}:{reference.account}"
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    if api.CredDeleteW(target, 1, 0):
        return True
    if ctypes.get_last_error() == 1168:
        return False
    raise NativeVaultError("Windows Credential Manager could not delete the secret")


def _mac_security() -> tuple[Any, Any]:
    try:
        security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
        core_foundation = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
    except OSError as exc:
        raise NativeVaultError("macOS Keychain is unavailable") from exc
    security.SecKeychainFindGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    security.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
    security.SecKeychainItemDelete.restype = ctypes.c_int32
    security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecKeychainItemFreeContent.restype = ctypes.c_int32
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    core_foundation.CFRelease.restype = None
    return security, core_foundation


def _mac_find(
    reference: SecretReference,
    *,
    include_secret: bool,
    security_loader: Callable[[], tuple[Any, Any]],
) -> tuple[int, bytes | None, Any]:
    security, _core_foundation = security_loader()
    service = reference.service.encode("utf-8")
    account = reference.account.encode("utf-8")
    item = ctypes.c_void_p()
    password_length = ctypes.c_uint32()
    password_data = ctypes.c_void_p()
    status = security.SecKeychainFindGenericPassword(
        None,
        len(service),
        service,
        len(account),
        account,
        ctypes.byref(password_length) if include_secret else None,
        ctypes.byref(password_data) if include_secret else None,
        ctypes.byref(item),
    )
    value = None
    if status == _ERR_SEC_SUCCESS and include_secret:
        try:
            if password_length.value > _MAX_SECRET_BYTES:
                raise NativeVaultError("macOS Keychain returned oversized data")
            value = ctypes.string_at(password_data, password_length.value)
        finally:
            if password_data:
                security.SecKeychainItemFreeContent(None, password_data)
    return status, value, item


def mac_get(
    reference: SecretReference,
    *,
    security_loader: Callable[[], tuple[Any, Any]] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> bytes | None:
    _check_reference(reference, capability)
    loader = security_loader or _mac_security
    status, value, item = _mac_find(
        reference, include_secret=True, security_loader=loader
    )
    try:
        if status == _ERR_SEC_ITEM_NOT_FOUND:
            return None
        if status != _ERR_SEC_SUCCESS:
            raise NativeVaultError("macOS Keychain could not read the secret")
        return value
    finally:
        if item:
            _security, core_foundation = loader()
            core_foundation.CFRelease(item)


def mac_set(
    reference: SecretReference,
    secret: bytes | bytearray,
    *,
    security_loader: Callable[[], tuple[Any, Any]] | None = None,
    wipe: Callable[[int, int, int], Any] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> None:
    _check_reference(reference, capability)
    loader = security_loader or _mac_security
    wipe_secret = wipe or ctypes.memset
    raw = bytearray(_bounded_secret(secret))
    security, core_foundation = loader()
    status, _value, item = _mac_find(
        reference, include_secret=False, security_loader=loader
    )
    blob = (ctypes.c_ubyte * len(raw)).from_buffer(raw)
    pointer = ctypes.cast(blob, ctypes.c_void_p)
    try:
        if status == _ERR_SEC_SUCCESS:
            result = security.SecKeychainItemModifyAttributesAndData(
                item, None, len(raw), pointer
            )
        elif status == _ERR_SEC_ITEM_NOT_FOUND:
            service = reference.service.encode("utf-8")
            account = reference.account.encode("utf-8")
            result = security.SecKeychainAddGenericPassword(
                None,
                len(service),
                service,
                len(account),
                account,
                len(raw),
                pointer,
                None,
            )
        else:
            raise NativeVaultError("macOS Keychain could not access the secret")
        if result != _ERR_SEC_SUCCESS:
            raise NativeVaultError("macOS Keychain could not store the secret")
    finally:
        wipe_secret(ctypes.addressof(blob), 0, len(raw))
        if item:
            core_foundation.CFRelease(item)


def mac_delete(
    reference: SecretReference,
    *,
    security_loader: Callable[[], tuple[Any, Any]] | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> bool:
    _check_reference(reference, capability)
    loader = security_loader or _mac_security
    security, core_foundation = loader()
    status, _value, item = _mac_find(
        reference, include_secret=False, security_loader=loader
    )
    try:
        if status == _ERR_SEC_ITEM_NOT_FOUND:
            return False
        if status != _ERR_SEC_SUCCESS:
            raise NativeVaultError("macOS Keychain could not access the secret")
        if security.SecKeychainItemDelete(item) != _ERR_SEC_SUCCESS:
            raise NativeVaultError("macOS Keychain could not delete the secret")
        return True
    finally:
        if item:
            core_foundation.CFRelease(item)


def _run_backend(
    argv: list[str], *, secret_input: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            input=secret_input,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise NativeVaultError("The operating-system credential vault is unavailable") from exc


def _validate_linux_tool(tool_path: str) -> str:
    candidate = Path(tool_path)
    try:
        info = candidate.lstat()
    except FileNotFoundError as exc:
        raise NativeVaultError("Linux Secret Service helper is unavailable") from exc
    except OSError as exc:
        raise NativeVaultError("Linux Secret Service helper is unavailable") from exc
    if (
        not candidate.is_absolute()
        or candidate.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or info.st_uid != 0
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise NativeVaultError("Linux Secret Service helper is not trusted")
    return os.fspath(candidate)


def _linux_secret_tool() -> str:
    for literal in ("/usr/bin/secret-tool", "/bin/secret-tool"):
        try:
            Path(literal).lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise NativeVaultError("Linux Secret Service helper is unavailable") from exc
        return _validate_linux_tool(literal)
    raise NativeVaultError("Linux Secret Service helper is unavailable")


def _linux_backend_probe(
    tool: str,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """Prove Secret Service health without treating lookup status as health.

    Upstream ``secret-tool lookup`` returns status 1 both when no item exists
    and when libsecret reports a backend error.  A search for a fresh random
    account has an unambiguous contract: a reachable backend returns success
    with no matches, while a D-Bus/libsecret failure remains non-zero.  The
    random namespace also prevents the probe from retrieving an application
    secret.
    """

    probe = run(
        [
            tool,
            "search",
            "--all",
            "service",
            "Onyx.NativeVault.HealthProbe",
            "account",
            f"probe-{os.getpid()}-{os.urandom(16).hex()}",
        ]
    )
    if (
        probe.returncode != 0
        or bool((probe.stderr or "").strip())
        or bool((probe.stdout or "").strip())
    ):
        raise NativeVaultError("Linux Secret Service backend is unavailable")


def _linux_lookup_value(
    reference: SecretReference,
    *,
    tool: str,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> str | None:
    result = run(
        [tool, "lookup", "service", reference.service, "account", reference.account]
    )
    stdout = result.stdout or ""
    stderr = result.stderr or ""
    if stderr.strip():
        raise NativeVaultError("Linux Secret Service could not read the secret")
    if result.returncode == 0:
        if not stdout:
            raise NativeVaultError("Linux Secret Service returned malformed data")
        return stdout.rstrip("\r\n")
    if result.returncode != 1 or stdout:
        raise NativeVaultError("Linux Secret Service could not read the secret")

    # Status 1 plus empty streams is the documented no-match shape, but it is
    # not unique to that condition across Secret Service implementations.
    # Confirm backend health before returning the semantic absence value.
    _linux_backend_probe(tool, run)
    return None


def linux_get(
    reference: SecretReference,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    binary: bool = True,
    tool_path: str | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> bytes | None:
    _check_reference(reference, capability)
    run = runner or _run_backend
    tool = _validate_linux_tool(tool_path) if tool_path is not None else _linux_secret_tool()
    value = _linux_lookup_value(reference, tool=tool, run=run)
    if value is None:
        return None
    if not binary:
        try:
            return value.encode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise NativeVaultError("Linux Secret Service returned malformed data") from exc
    if not value.startswith(_LINUX_BINARY_PREFIX):
        raise NativeVaultError("Linux Secret Service returned an incompatible secret")
    encoded = value.removeprefix(_LINUX_BINARY_PREFIX)
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise NativeVaultError("Linux Secret Service returned malformed data") from exc
    return _bounded_secret(decoded)


def linux_set(
    reference: SecretReference,
    secret: bytes | bytearray,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    binary: bool = True,
    tool_path: str | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> None:
    _check_reference(reference, capability)
    run = runner or _run_backend
    tool = _validate_linux_tool(tool_path) if tool_path is not None else _linux_secret_tool()
    raw = _bounded_secret(secret)
    if binary:
        value = _LINUX_BINARY_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")
    else:
        try:
            value = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise NativeVaultError("Text secret is not valid UTF-8") from exc
    result = run(
        [
            tool,
            "store",
            f"--label={reference.label}",
            "service",
            reference.service,
            "account",
            reference.account,
        ],
        secret_input=value,
    )
    if result.returncode != 0:
        raise NativeVaultError("Linux Secret Service could not store the secret")


def linux_delete(
    reference: SecretReference,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    tool_path: str | None = None,
    capability: _AnchorNamespaceCapability | None = None,
) -> bool:
    _check_reference(reference, capability)
    run = runner or _run_backend
    tool = _validate_linux_tool(tool_path) if tool_path is not None else _linux_secret_tool()
    existing = _linux_lookup_value(reference, tool=tool, run=run)
    if existing is None:
        return False
    result = run(
        [tool, "clear", "service", reference.service, "account", reference.account]
    )
    if result.returncode != 0:
        raise NativeVaultError("Linux Secret Service could not delete the secret")
    return True


class NativeSecretVault:
    """Fixed-namespace native vault with no fallback or environment lookup."""

    def __init__(
        self,
        reference: SecretReference,
        *,
        system: str | None = None,
        capability: _AnchorNamespaceCapability | None = None,
    ):
        if not isinstance(reference, SecretReference):
            raise TypeError("reference must be a SecretReference")
        _check_reference(reference, capability)
        name = platform.system() if system is None else system
        if name not in {"Windows", "Darwin", "Linux"}:
            raise NativeVaultError("No secure native vault supports this operating system")
        self.reference = reference
        self.system = name
        self._capability = capability

    @property
    def backend_name(self) -> str:
        return {
            "Windows": "Windows Credential Manager",
            "Darwin": "macOS Keychain",
            "Linux": "Secret Service",
        }[self.system]

    def get_bytes(self) -> bytes | None:
        if self.system == "Windows":
            return windows_get(self.reference, capability=self._capability)
        if self.system == "Darwin":
            return mac_get(self.reference, capability=self._capability)
        return linux_get(self.reference, capability=self._capability)

    def set_bytes(self, secret: bytes | bytearray) -> None:
        raw = _bounded_secret(secret)
        if self.system == "Windows":
            windows_set(self.reference, raw, capability=self._capability)
        elif self.system == "Darwin":
            mac_set(self.reference, raw, capability=self._capability)
        else:
            linux_set(self.reference, raw, capability=self._capability)

    def delete(self) -> bool:
        if self.system == "Windows":
            return windows_delete(self.reference, capability=self._capability)
        if self.system == "Darwin":
            return mac_delete(self.reference, capability=self._capability)
        return linux_delete(self.reference, capability=self._capability)


__all__ = ["NativeVaultError"]
