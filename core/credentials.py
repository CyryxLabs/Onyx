"""Secure, user-scoped credential storage for Onyx.

Secrets are resolved from an explicit environment override first and otherwise
from the operating-system credential vault.  There is deliberately no
plaintext fallback.  ``config/api_keys.json`` is reserved for non-secret
settings and is only touched by :func:`migrate_legacy`.
"""

from __future__ import annotations

import argparse
import ctypes
import getpass
import hmac
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from core import native_vault
from core.paths import config_file, resource_root


SERVICE = "Onyx.GeminiAPIKey"
ACCOUNT = "gemini"
ROOT = resource_root()
CONFIG_PATH = config_file()
ENV_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
_GEMINI_REFERENCE = native_vault.SecretReference(
    SERVICE, ACCOUNT, "Onyx Gemini API key"
)


class CredentialError(RuntimeError):
    """A safe-to-display credential backend error."""


def _environment_value() -> tuple[str | None, str | None]:
    for name in ENV_NAMES:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip(), name
    return None, None


def _win_api() -> Any:
    try:
        return native_vault._win_api()
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc)) from exc


def _windows_get() -> str | None:
    try:
        raw = native_vault.windows_get(
            _GEMINI_REFERENCE, api_factory=_win_api, legacy_target=True
        )
        if raw is None:
            return None
        try:
            return raw.decode("utf-16-le", errors="strict")
        except UnicodeDecodeError as exc:
            raise CredentialError("Windows Credential Manager returned malformed data") from exc
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _windows_set(secret: str) -> None:
    try:
        native_vault.windows_set(
            _GEMINI_REFERENCE,
            secret.encode("utf-16-le"),
            api_factory=_win_api,
            wipe=ctypes.memset,
            legacy_target=True,
        )
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _windows_delete() -> bool:
    try:
        return native_vault.windows_delete(
            _GEMINI_REFERENCE, api_factory=_win_api, legacy_target=True
        )
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _run_backend(argv: list[str], *, secret_input: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run a fixed-argv native vault helper without exposing secret output."""
    try:
        return native_vault._run_backend(argv, secret_input=secret_input)
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc)) from exc


def _mac_security() -> tuple[Any, Any]:
    try:
        return native_vault._mac_security()
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc)) from exc


def _mac_get() -> str | None:
    try:
        raw = native_vault.mac_get(
            _GEMINI_REFERENCE, security_loader=_mac_security
        )
        if raw is None:
            return None
        try:
            return raw.decode("utf-8", errors="strict") or None
        except UnicodeDecodeError as exc:
            raise CredentialError("macOS Keychain returned malformed data") from exc
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _mac_set(secret: str) -> None:
    try:
        native_vault.mac_set(
            _GEMINI_REFERENCE,
            secret.encode("utf-8"),
            security_loader=_mac_security,
            wipe=ctypes.memset,
        )
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _mac_delete() -> bool:
    try:
        return native_vault.mac_delete(
            _GEMINI_REFERENCE, security_loader=_mac_security
        )
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _linux_get() -> str | None:
    try:
        raw = native_vault.linux_get(
            _GEMINI_REFERENCE, runner=_run_backend, binary=False
        )
        return raw.decode("utf-8", errors="strict") if raw is not None else None
    except (UnicodeDecodeError, native_vault.NativeVaultError) as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _linux_set(secret: str) -> None:
    try:
        native_vault.linux_set(
            _GEMINI_REFERENCE,
            secret.encode("utf-8"),
            runner=_run_backend,
            binary=False,
        )
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _linux_delete() -> bool:
    try:
        return native_vault.linux_delete(_GEMINI_REFERENCE, runner=_run_backend)
    except native_vault.NativeVaultError as exc:
        raise CredentialError(str(exc).replace("secret", "credential")) from exc


def _backend_name(system: str | None = None) -> str:
    name = system or platform.system()
    names = {"Windows": "Windows Credential Manager", "Darwin": "macOS Keychain",
             "Linux": "Secret Service"}
    if name not in names:
        raise CredentialError("No secure credential backend supports this operating system")
    return names[name]


def _backend(operation: str, *args: Any) -> Any:
    system = platform.system()
    prefix = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}.get(system)
    if prefix is None:
        raise CredentialError("No secure credential backend supports this operating system")
    return globals()[f"_{prefix}_{operation}"](*args)


def get(*, required: bool = True) -> str | None:
    """Return the Gemini key, honoring GEMINI_API_KEY before GOOGLE_API_KEY."""
    value, _name = _environment_value()
    if value is None:
        value = _backend("get")
    if required and not value:
        raise CredentialError(
            "Gemini credential is not configured; run `python -m core.credentials set`"
        )
    return value


def set(secret: str) -> None:
    value = secret.strip()
    if not value:
        raise CredentialError("Credential cannot be empty")
    _backend("set", value)
    saved = _backend("get")
    if not saved or not hmac.compare_digest(saved, value):
        raise CredentialError("Credential vault verification failed")


def delete() -> bool:
    return bool(_backend("delete"))


def status() -> dict[str, object]:
    """Return non-secret credential metadata suitable for logs/readiness output."""
    env_value, env_name = _environment_value()
    if env_value is not None:
        return {"configured": True, "source": "environment", "environment": env_name,
                "backend": _backend_name()}
    try:
        configured = bool(_backend("get"))
        return {"configured": configured, "source": "vault" if configured else "absent",
                "backend": _backend_name()}
    except CredentialError as exc:
        return {"configured": False, "source": "unavailable", "backend": _backend_name(),
                "error": str(exc)}


def _path_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size)


def _reject_unsafe_config_path(path: Path) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CredentialError("Settings path is unavailable") from exc
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if path.is_symlink() or attributes & reparse or not stat.S_ISREG(info.st_mode):
        raise CredentialError("Settings path must be a regular non-link file")
    return info


def _read_config_object(path: Path) -> tuple[dict[str, Any], os.stat_result]:
    before = _reject_unsafe_config_path(path)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            opened = os.fstat(handle.fileno())
            if _path_identity(opened) != _path_identity(before):
                raise CredentialError("Settings file changed while opening")
            data = json.load(handle)
    except CredentialError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CredentialError("Settings file is unreadable") from exc
    if not isinstance(data, dict):
        raise CredentialError("Settings root must be an object")
    return data, before


def _atomic_write_json(
    path: Path,
    data: dict[str, Any],
    *,
    expected: os.stat_result | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if expected is not None:
            current = _reject_unsafe_config_path(path)
            if _path_identity(current) != _path_identity(expected):
                raise CredentialError("Settings file changed during update")
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def save_settings(updates: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    """Atomically update non-secret settings while preserving existing values."""
    forbidden = {"gemini_api_key", "api_key", "google_api_key"}
    if forbidden.intersection(updates):
        raise CredentialError("Secret values cannot be stored in the settings file")
    data: dict[str, Any] = {}
    expected = None
    if path.exists():
        loaded, expected = _read_config_object(path)
        data = {k: v for k, v in loaded.items() if k not in forbidden}
    data.update(updates)
    _atomic_write_json(path, data, expected=expected)


def migrate_legacy(path: Path = CONFIG_PATH) -> bool:
    """Move a legacy plaintext Gemini key to the vault and scrub only secrets."""
    if not path.exists():
        return False
    data, expected = _read_config_object(path)
    secret = next((data.get(name) for name in ("gemini_api_key", "api_key")
                   if isinstance(data.get(name), str) and data.get(name).strip()), None)
    secret_fields = {name for name in ("gemini_api_key", "api_key") if name in data}
    if not secret_fields:
        return False
    if secret:
        set(secret)
        saved = _backend("get")
        if not saved or not hmac.compare_digest(saved, secret.strip()):
            raise CredentialError("Credential migration verification failed")
    cleaned = {key: value for key, value in data.items() if key not in secret_fields}
    _atomic_write_json(path, cleaned, expected=expected)
    return True


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage Onyx's Gemini credential")
    parser.add_argument("command", choices=("status", "set", "delete", "migrate"))
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            info = status()
            print(json.dumps(info, sort_keys=True))
            return 0 if info["configured"] else 1
        if args.command == "set":
            first = getpass.getpass("Gemini API key: ")
            second = getpass.getpass("Confirm Gemini API key: ")
            if not hmac.compare_digest(first, second):
                raise CredentialError("Credential confirmation did not match")
            set(first)
            print("Credential stored securely.")
        elif args.command == "delete":
            print("Credential deleted." if delete() else "Credential was not configured.")
        else:
            print("Legacy credential migrated." if migrate_legacy() else "No legacy credential found.")
        return 0
    except CredentialError as exc:
        print(f"Credential error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(_main())
