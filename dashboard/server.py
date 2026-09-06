"""
dashboard/server.py — Onyx Local HTTP Dashboard

HTTPS on port 8000 with a unique per-install self-signed certificate.
Commands also use AES-256-CBC with a session-key-derived key.
CryptoJS is auto-downloaded once and served locally — no CDN needed after that.

Install deps:  pip install fastapi "uvicorn[standard]" cryptography
"""

import asyncio
import base64
import hashlib
import ipaddress
import os
import re
import secrets
import socket
import stat
import string
import time
from pathlib import Path
from urllib.parse import quote

from dashboard.security import (
    ONYX_CERT_NAME,
    ONYX_KEY_NAME,
    ensure_local_certificate as _ensure_local_certificate,
    issue_token as _issue_bearer_token,
    token_is_valid as _bearer_token_is_valid,
)
from core.paths import config_dir, resource_root, uploads_dir as app_uploads_dir

_DEPS_OK = False
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
    from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, StreamingResponse
    import uvicorn
    _DEPS_OK = True
except ImportError:
    pass

# python-multipart is required for file uploads — optional dependency
_UPLOAD_OK = False
try:
    from fastapi import UploadFile, File as FastAPIFile
    _UPLOAD_OK = True
except Exception:
    pass

BASE_DIR    = resource_root()
STATIC_DIR  = BASE_DIR / "dashboard" / "static"
VISUAL_DIR  = BASE_DIR / "qml" / "web"
PORT        = 8000
MAX_UPLOAD_MB = 500
ACCESS_TOKEN_TTL = 60 * 60
WS_TICKET_TTL = 15
DEVICE_TOKEN_TTL = 7 * 24 * 60 * 60
LOGIN_WINDOW_SECS = 60
LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECS = 5 * 60


def _make_uploads_dir() -> Path:
    """Return (and create) the cross-platform uploads folder."""
    for candidate in [app_uploads_dir()]:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            _verified_upload_root(candidate)
            try:
                candidate.chmod(0o700)
            except OSError:
                pass
            return candidate
        except Exception:
            pass
    raise RuntimeError("Unable to create a safe Onyx uploads directory")


_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_UPLOAD_TEMP_PREFIX = ".onyx-upload-"


class _UnsafeUploadPath(OSError):
    """Raised when an upload path fails a no-link identity check."""


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        stat.S_IFMT(left.st_mode),
    ) == (
        right.st_dev,
        right.st_ino,
        stat.S_IFMT(right.st_mode),
    )


def _verified_upload_root(root: Path) -> os.stat_result:
    """Return the root's lstat only when it is a real, non-reparse directory."""
    info = os.lstat(root)
    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
        raise _UnsafeUploadPath("Uploads directory is not a real directory")
    return info


def _root_still_matches(root: Path, expected: os.stat_result) -> None:
    current = _verified_upload_root(root)
    if not _same_object(expected, current):
        raise _UnsafeUploadPath("Uploads directory changed during the operation")


def _safe_filename(raw: str) -> str:
    name = Path(raw).name
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(". ")
    return name or "upload"


def _open_upload_temp(
    root: Path, root_info: os.stat_result
) -> tuple[Path, int, os.stat_result]:
    """Create an unguessable, exclusive, no-follow temporary upload file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for _ in range(64):
        path = root / f"{_UPLOAD_TEMP_PREFIX}{secrets.token_hex(16)}.tmp"
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError:
            continue
        try:
            opened = os.fstat(fd)
            on_disk = os.lstat(path)
            if (
                not stat.S_ISREG(opened.st_mode)
                or _is_link_or_reparse(on_disk)
                or not _same_object(opened, on_disk)
            ):
                raise _UnsafeUploadPath("Temporary upload is not a regular file")
            _root_still_matches(root, root_info)
            return path, fd, opened
        except Exception:
            os.close(fd)
            try:
                current = os.lstat(path)
                if _same_object(opened, current):
                    os.unlink(path)
            except (OSError, UnboundLocalError):
                pass
            raise
    raise FileExistsError("Unable to allocate a temporary upload file")


def _unlink_if_same(path: Path, expected: os.stat_result) -> None:
    """Remove only the exact object previously opened by this process."""
    try:
        current = os.lstat(path)
        if _same_object(expected, current) and not _is_link_or_reparse(current):
            os.unlink(path)
    except OSError:
        pass


def _publish_upload_no_replace(
    root: Path,
    root_info: os.stat_result,
    temp_path: Path,
    temp_info: os.stat_result,
    requested_name: str,
) -> Path:
    """Atomically publish by hard link; an existing name is never replaced."""
    stem, suffix = Path(requested_name).stem, Path(requested_name).suffix
    for counter in range(10_000):
        name = requested_name if counter == 0 else f"{stem}_{counter}{suffix}"
        candidate = root / name
        _root_still_matches(root, root_info)
        source_now = os.lstat(temp_path)
        if (
            _is_link_or_reparse(source_now)
            or not stat.S_ISREG(source_now.st_mode)
            or not _same_object(temp_info, source_now)
        ):
            raise _UnsafeUploadPath("Temporary upload changed before publication")
        try:
            os.link(temp_path, candidate, follow_symlinks=False)
        except FileExistsError:
            continue

        published = None
        try:
            published = os.lstat(candidate)
            _root_still_matches(root, root_info)
            if (
                _is_link_or_reparse(published)
                or not stat.S_ISREG(published.st_mode)
                or not _same_object(temp_info, published)
            ):
                raise _UnsafeUploadPath("Published upload failed its identity check")
            return candidate
        except Exception:
            if published is not None:
                _unlink_if_same(candidate, published)
            raise
    raise FileExistsError("Too many files use that upload name")


def _open_verified_download(
    root: Path, filename: str
) -> tuple[object, os.stat_result]:
    """Open a direct child and bind path validation to the returned handle."""
    root_info = _verified_upload_root(root)
    path = root / filename
    before = os.lstat(path)
    if _is_link_or_reparse(before) or not stat.S_ISREG(before.st_mode):
        raise _UnsafeUploadPath("Download is not a regular file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        after = os.lstat(path)
        _root_still_matches(root, root_info)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _is_link_or_reparse(after)
            or not _same_object(before, opened)
            or not _same_object(opened, after)
        ):
            raise _UnsafeUploadPath("Download changed while it was opened")
        return os.fdopen(fd, "rb", closefd=True), opened
    except Exception:
        os.close(fd)
        raise


def _stream_file_handle(handle, chunk_size: int = 64 * 1024):
    """Stream from the already-verified handle, never by reopening its pathname."""
    try:
        while chunk := handle.read(chunk_size):
            yield chunk
    finally:
        handle.close()


def _list_verified_uploads(root: Path) -> list[dict]:
    """List only direct, regular, no-follow children of an unchanged root."""
    root_info = _verified_upload_root(root)
    found: list[tuple[int, dict]] = []
    with os.scandir(root) as entries:
        for entry in entries:
            if (
                entry.name.startswith(_UPLOAD_TEMP_PREFIX)
                or _safe_filename(entry.name) != entry.name
            ):
                continue
            try:
                entry_info = entry.stat(follow_symlinks=False)
                info = os.lstat(root / entry.name)
            except OSError:
                continue
            if (
                _is_link_or_reparse(entry_info)
                or _is_link_or_reparse(info)
                or not stat.S_ISREG(info.st_mode)
            ):
                continue
            found.append((info.st_mtime_ns, {"name": entry.name, "size": info.st_size}))
    _root_still_matches(root, root_info)
    found.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in found]


def _get_gemini_key() -> str | None:
    try:
        from core.credentials import get
        return get(required=False)
    except Exception:
        return None

_KEY_CHARS = [c for c in (string.ascii_uppercase + string.digits)
              if c not in ('O', 'I', 'L', '0', '1')]

# ── AES-256-CBC ───────────────────────────────────────────────────────────────
_AES_SALT = b'ONYX-DASHBOARD-v2'


def _derive_key(session_key: str, salt: bytes = _AES_SALT) -> bytes:
    """SHA-256(sessionKey‖salt) → 32-byte AES-256 key (microseconds, no PBKDF2 needed)."""
    return hashlib.sha256(session_key.encode('utf-8') + salt).digest()


def _decrypt_cbc(aes_key: bytes, enc_b64: str) -> str:
    """Decrypt base64(IV[16] ‖ ciphertext) with AES-256-CBC + PKCS7."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding as sym_pad
    raw      = base64.b64decode(enc_b64)
    iv, ct   = raw[:16], raw[16:]
    dec      = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
    padded   = dec.update(ct) + dec.finalize()
    unpadder = sym_pad.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode('utf-8')


# ── CryptoJS (auto-download once, served locally) ─────────────────────────────
_CRYPTOJS_CDN  = ("https://cdnjs.cloudflare.com/ajax/libs/"
                  "crypto-js/4.2.0/crypto-js.min.js")
_CRYPTOJS_FILE = STATIC_DIR / "crypto-js.min.js"


def _ensure_network_access(port: int) -> None:
    """Print narrow manual LAN setup guidance; never elevate or change networking."""
    import sys

    print(f"[Dashboard] LAN access may require an inbound TCP rule for port {port}.")
    if sys.platform == "win32":
        print(
            "[Dashboard] Optional manual Administrator command (Private profile only): "
            f'netsh advfirewall firewall add rule name="Onyx Dashboard {port}" '
            f"dir=in action=allow protocol=TCP localport={port} profile=private"
        )
        print("[Dashboard] Onyx will not elevate itself or change the network profile.")
    elif sys.platform == "darwin":
        print("[Dashboard] If blocked, allow Python/Onyx in System Settings > Network > Firewall.")
    else:
        print(f"[Dashboard] Optional manual command: sudo ufw allow {port}/tcp")
    # An active VPN client on this machine commonly drops inbound LAN
    # connections even when binding, TLS and the firewall rule are correct,
    # which presents as "the phone cannot load the dashboard" after scanning
    # the QR code. Detect the usual adapters and say so explicitly.
    try:
        import psutil

        vpn_words = (
            "nordlynx", "nordvpn", "tailscale", "wireguard", "openvpn",
            "proton", "zerotier", "mullvad", "surfshark", "expressvpn",
        )
        active = sorted(
            name
            for name, stats in psutil.net_if_stats().items()
            if stats.isup and any(word in name.casefold() for word in vpn_words)
        )
        if active:
            print(
                "[Dashboard] Active VPN adapter(s) detected: "
                + ", ".join(active)
                + ". VPN clients usually block inbound LAN connections."
            )
            print(
                "[Dashboard] If the phone cannot load the dashboard, enable the "
                "VPN's LAN/local-network access option (NordVPN: Settings > "
                "Kill Switch / Advanced > 'LAN discovery') or disconnect the "
                "VPN, then scan the QR code again."
            )
    except Exception:
        pass


def _ensure_crypto_js() -> None:
    if _CRYPTOJS_FILE.exists():
        return
    try:
        import urllib.request
        print("[Dashboard] Downloading CryptoJS (one-time setup)…")
        urllib.request.urlretrieve(_CRYPTOJS_CDN, str(_CRYPTOJS_FILE))  # noqa: S310 - fixed HTTPS CDN
        print("[Dashboard] CryptoJS cached — will serve locally from now on.")
    except Exception as e:
        print(f"[Dashboard] CryptoJS download failed: {e}")
        print("[Dashboard] Encryption will fall back to CDN load on client.")


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_ip() -> str:
    """Return the best phone-reachable LAN IPv4, excluding VPN/link-local NICs."""
    candidates: list[tuple[int, str]] = []

    def add(ip: str, interface: str = "") -> None:
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return
        name = interface.casefold()
        # A connected mesh VPN (Tailscale) hands out an RFC 6598 shared-space
        # address, which `is_private` reports as False.  It is the only address
        # that reaches this machine from outside the LAN, so it is accepted
        # explicitly and preferred: a phone away from home, or one whose VPN
        # blocks inbound LAN traffic, can reach nothing else.  An unconnected
        # mesh adapter carries a link-local address and is still rejected below.
        mesh = "tailscale" in name and address in ipaddress.ip_network("100.64.0.0/10")
        if (
            address.version != 4
            or (not address.is_private and not mesh)
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
        ):
            return
        if mesh:
            candidates.append((500, ip))
            return
        virtual = any(word in name for word in (
            "tailscale", "nord", "openvpn", "wireguard", "wsl", "hyper-v",
            "vethernet", "virtual", "loopback", "bluetooth",
        ))
        preferred = any(word in name for word in ("ethernet", "wi-fi", "wifi", "wireless"))
        # Prefer a physical LAN adapter, then the common home-LAN ranges.
        score = (0 if virtual else 100) + (50 if preferred else 0)
        score += 30 if ip.startswith("192.168.") else 20 if ip.startswith("10.") else 10
        candidates.append((score, ip))

    # psutil is already present with the desktop/audio dependencies. Keeping it
    # optional preserves dashboard importability in minimal readiness installs.
    try:
        import psutil
        stats = psutil.net_if_stats()
        for name, addresses in psutil.net_if_addrs().items():
            if name in stats and not stats[name].isup:
                continue
            for address in addresses:
                if address.family == socket.AF_INET:
                    add(address.address, name)
    except (ImportError, OSError):
        pass

    # Hostname enumeration remains a portable fallback.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except Exception:
        pass
    return max(candidates, default=(0, "127.0.0.1"))[1]


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


# ── DashboardServer ───────────────────────────────────────────────────────────

class DashboardServer:

    def __init__(
        self,
        *,
        local_ip: str | None = None,
        cert_dir: Path | None = None,
        uploads_dir: Path | None = None,
        static_dir: Path | None = None,
        visual_dir: Path | None = None,
        phase5_enabled: bool = False,
    ):
        """Construct the real app; injectable paths keep readiness ephemeral."""
        if type(phase5_enabled) is not bool:
            raise TypeError("phase5_enabled must be exact bool")
        self._ip                          = local_ip or _local_ip()
        self._cert_dir                    = cert_dir or config_dir() / "certs"
        self._static_dir                  = static_dir or STATIC_DIR
        self._visual_dir                  = visual_dir or VISUAL_DIR
        _ensure_local_certificate(
            self._cert_dir,
            [self._ip, "127.0.0.1"],
        )
        self._tokens: dict[str, float]     = {}   # auth_token → expiry timestamp
        self._token_keys: dict[str, str]   = {}   # auth_token → session_key
        self._ws_tickets: dict[str, dict]  = {}   # one-use ticket → token/scope/expiry
        self._aes_cache:  dict[str, bytes]= {}   # session_key → AES bytes
        self._clients: dict[WebSocket, str] = {}  # websocket -> access token
        self._history: list[dict]         = []
        self._command_queue               = asyncio.Queue()
        self._wake_callback               = None
        self._connect_callback            = None
        self._phase5_enabled              = phase5_enabled
        self._phase5_bridge               = None
        self._pending_keys: dict[str, float] = {}
        self._device_sessions: dict[str, dict] = {}  # device_token → session key + expiry
        self._login_failures: dict[str, list[float]] = {}
        self._login_lockouts: dict[str, float] = {}
        self._phone_audio_queue: asyncio.Queue    = asyncio.Queue(maxsize=200)
        self._uploads_dir_injected        = uploads_dir is not None
        self._uploads_dir                 = uploads_dir or app_uploads_dir()
        self._login_html                  = (self._static_dir / "login.html").read_text(encoding="utf-8")
        self._app_html                    = (self._static_dir / "app.html").read_text(encoding="utf-8")
        self._visual_assets               = {
            "onyx-humanoid-three-v5.html": self._visual_dir / "onyx-humanoid-three-v5.html",
            "onyx-humanoid-three-v4.html": self._visual_dir / "onyx-humanoid-three-v4.html",
            "onyx-humanoid-three-v3.html": self._visual_dir / "onyx-humanoid-three-v3.html",
            "onyx-humanoid-three-v2.html": self._visual_dir / "onyx-humanoid-three-v2.html",
            "data/onyx-humanoid-pointcloud-v1.js": (
                self._visual_dir / "data" / "onyx-humanoid-pointcloud-v1.js"
            ),
            "vendor/three/three.module.min.js": (
                self._visual_dir / "vendor" / "three" / "three.module.min.js"
            ),
            "vendor/three/three.core.min.js": (
                self._visual_dir / "vendor" / "three" / "three.core.min.js"
            ),
        }
        missing_visuals = [
            name for name, path in self._visual_assets.items()
            if not path.is_file() or path.is_symlink()
        ]
        if missing_visuals:
            raise FileNotFoundError(
                "required Onyx humanoid assets are unavailable: "
                + ", ".join(sorted(missing_visuals))
            )
        self.app                          = self._build_app()

    # ── one-time key management ───────────────────────────────────────────

    def new_key(self, expiry_secs: int = 600) -> str:
        now = time.time()
        self._pending_keys = {k: v for k, v in self._pending_keys.items() if v > now}
        key = ''.join(secrets.choice(_KEY_CHARS) for _ in range(6))
        self._pending_keys[key] = now + expiry_secs
        return key

    def _ssl_enabled(self) -> bool:
        return (self._cert_dir / ONYX_KEY_NAME).exists() and (
            self._cert_dir / ONYX_CERT_NAME
        ).exists()

    def get_url(self) -> str:
        proto = "https" if self._ssl_enabled() else "http"
        return f"{proto}://{self._ip}:{PORT}"

    def get_manual_url(self) -> str:
        """URL for manual browser entry. When HTTPS active, points to alias port (also HTTPS)."""
        if self._ssl_enabled():
            return f"https://{self._ip}:{PORT + 1}"
        return f"http://{self._ip}:{PORT}"

    def _aes_key(self, session_key: str) -> bytes:
        if session_key not in self._aes_cache:
            self._aes_cache[session_key] = _derive_key(session_key)
        return self._aes_cache[session_key]

    def _decrypt(self, token: str, enc_b64: str) -> str | None:
        sk = self._token_keys.get(token)
        if not sk:
            return None
        try:
            return _decrypt_cbc(self._aes_key(sk), enc_b64)
        except Exception:
            return None

    def _issue_token(self, session_key: str) -> str:
        token = _issue_bearer_token(
            self._tokens, self._token_keys, session_key, ACCESS_TOKEN_TTL
        )
        self._aes_key(session_key)
        return token

    def _token_is_valid(self, token: str) -> bool:
        return _bearer_token_is_valid(self._tokens, self._token_keys, token)

    def _issue_ws_ticket(self, token: str, scope: str) -> str:
        """Issue a short-lived ticket bound to one access token and WS scope."""
        if scope not in {"command", "audio"} or not self._token_is_valid(token):
            raise ValueError("invalid WebSocket ticket request")
        now = time.time()
        self._ws_tickets = {
            ticket: record
            for ticket, record in self._ws_tickets.items()
            if record["expires_at"] > now
        }
        ticket = secrets.token_urlsafe(32)
        self._ws_tickets[ticket] = {
            "token": token,
            "scope": scope,
            "expires_at": now + WS_TICKET_TTL,
        }
        return ticket

    def _consume_ws_ticket(self, ticket: str, scope: str) -> str | None:
        """Atomically burn a ticket, then validate its scope, expiry, and session."""
        record = self._ws_tickets.pop(ticket, None)
        if (
            not record
            or record["scope"] != scope
            or record["expires_at"] <= time.time()
        ):
            return None
        token = record["token"]
        return token if self._token_is_valid(token) else None

    def _login_client_id(self, req: Request) -> str:
        return req.client.host if req.client else "unknown"

    def _login_is_locked(self, client_id: str, now: float) -> bool:
        locked_until = self._login_lockouts.get(client_id, 0)
        if locked_until > now:
            return True
        self._login_lockouts.pop(client_id, None)
        return False

    def _record_login_failure(self, client_id: str, now: float) -> None:
        recent = [
            stamp for stamp in self._login_failures.get(client_id, [])
            if stamp > now - LOGIN_WINDOW_SECS
        ]
        recent.append(now)
        self._login_failures[client_id] = recent
        if len(recent) >= LOGIN_MAX_FAILURES:
            self._login_lockouts[client_id] = now + LOGIN_LOCKOUT_SECS
            self._login_failures.pop(client_id, None)

    # ── callbacks ────────────────────────────────────────────────────────

    def set_wake_callback(self, fn) -> None:
        self._wake_callback = fn

    def set_connect_callback(self, fn) -> None:
        self._connect_callback = fn

    def set_phase5_bridge(self, bridge) -> None:
        """Bind only the read/kill facade; no approval or dispatch API exists."""
        if bridge is not None and (
            not callable(getattr(bridge, "dashboard_read", None))
            or not callable(getattr(bridge, "kill", None))
        ):
            raise TypeError("invalid Phase 5 dashboard bridge")
        self._phase5_bridge = bridge

    # ── broadcast ────────────────────────────────────────────────────────

    async def broadcast(self, msg: dict) -> None:
        self._history.append(msg)
        if len(self._history) > 300:
            self._history = self._history[-300:]
        dead: set[WebSocket] = set()
        for ws, token in list(self._clients.items()):
            try:
                if not self._token_is_valid(token):
                    await ws.close(code=4001, reason="Session expired")
                    dead.add(ws)
                    continue
                await ws.send_json(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self._clients.pop(ws, None)

    # ── FastAPI app ───────────────────────────────────────────────────────

    def _build_app(self) -> "FastAPI":
        app = FastAPI(docs_url=None, redoc_url=None)

        @app.middleware("http")
        async def security_headers(req: Request, call_next):
            response = await call_next(req)
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; base-uri 'none'; object-src 'none'; "
                "frame-ancestors 'self'; form-action 'self'; "
                "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: blob:; font-src 'self' data:; "
                "media-src 'self' blob:; connect-src 'self' ws: wss:"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Permissions-Policy"] = (
                "microphone=(self), camera=(), geolocation=(), payment=(), usb=()"
            )
            response.headers["Referrer-Policy"] = "no-referrer"
            forwarded_proto = req.headers.get("x-forwarded-proto", "").lower()
            if req.url.scheme == "https" or forwarded_proto == "https":
                response.headers["Strict-Transport-Security"] = (
                    "max-age=31536000; includeSubDomains"
                )
            content_type = response.headers.get("content-type", "").lower()
            if not req.url.path.startswith("/static/") or "text/html" in content_type:
                response.headers["Cache-Control"] = "no-store"
            return response

        def _auth(req: Request) -> bool:
            tok = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            return bool(tok) and self._token_is_valid(tok)

        # serve CryptoJS from local cache, fallback to CDN redirect
        @app.get("/static/crypto.js")
        async def serve_crypto():
            if _CRYPTOJS_FILE.exists():
                return FileResponse(str(_CRYPTOJS_FILE),
                                    media_type="application/javascript")
            from fastapi.responses import RedirectResponse
            return RedirectResponse(_CRYPTOJS_CDN)

        @app.get("/visual/{asset_path:path}")
        async def serve_humanoid_asset(asset_path: str):
            """Serve only the frozen desktop humanoid runtime used by mobile."""

            normalized = asset_path.replace("\\", "/").strip("/")
            target = self._visual_assets.get(normalized)
            if target is None:
                return JSONResponse({"error": "Not found"}, status_code=404)
            media_type = "text/html" if normalized.endswith(".html") else "text/javascript"
            return FileResponse(str(target), media_type=media_type)

        @app.get("/login", response_class=HTMLResponse)
        async def login_page():
            return HTMLResponse(self._login_html)

        @app.get("/", response_class=HTMLResponse)
        async def index():
            # Auth is handled client-side via sessionStorage bearer token.
            # Server-side header auth can't work here because browser navigations
            # don't send custom headers (location.href doesn't carry Authorization).
            html = (self._app_html
                    .replace("__IP__", self._ip)
                    .replace("__PORT__", str(PORT)))
            return HTMLResponse(html)

        @app.post("/login")
        async def login(req: Request):
            body    = await req.json()
            entered = str(body.get("pin", "")).strip().upper()
            now     = time.time()
            client_id = self._login_client_id(req)
            if self._login_is_locked(client_id, now):
                return JSONResponse(
                    {"ok": False, "error": "Too many attempts; try again later"},
                    status_code=429,
                )
            if entered in self._pending_keys and self._pending_keys[entered] > now:
                del self._pending_keys[entered]          # one-time use
                self._login_failures.pop(client_id, None)
                tok = self._issue_token(entered)
                if self._connect_callback:
                    self._connect_callback()
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Remote connection established."}
                ))
                # Bearer token in response body — no cookies needed (works on any browser/HTTP)
                return JSONResponse({"ok": True, "token": tok, "expires_in": ACCESS_TOKEN_TTL})
            self._record_login_failure(client_id, now)
            return JSONResponse({"ok": False, "error": "Invalid or expired key"},
                                status_code=401)

        @app.get("/pair", response_class=HTMLResponse)
        async def pair_page():
            """Neutral QR target: no secret, token or code is carried in its URL."""
            return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width">
<title>Pair with Onyx</title><style>
body{background:#07090f;color:#dde3ed;font-family:system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}.card{width:min(88vw,360px);
padding:28px;border:1px solid #1b3940;border-radius:18px;background:#0a0d0f}
h1{font-size:20px;color:#19c7c0;margin:0 0 8px}p{color:#8c949e;font-size:14px}
input,button{box-sizing:border-box;width:100%;height:48px;border-radius:9px;font-size:18px}
input{background:#07090f;color:#fff;border:1px solid #2b4248;padding:0 14px;text-align:center;
letter-spacing:5px;text-transform:uppercase}button{margin-top:12px;background:#19c7c0;color:#031011;
border:0;font-weight:700}#status{min-height:20px;color:#f87171}
</style></head><body><main class="card"><h1>PAIR WITH ONYX</h1>
<p>Enter the one-time code shown on your trusted Onyx desktop.</p>
<input id="pin" maxlength="8" autocomplete="one-time-code" inputmode="text" autofocus>
<button id="pair">PAIR DEVICE</button><p id="status"></p></main><script>
const statusNode=document.getElementById('status');
document.getElementById('pair').onclick=async()=>{statusNode.textContent='';
 const pin=document.getElementById('pin').value.trim().toUpperCase();
 const response=await fetch('/pair',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({pin})}); const data=await response.json();
 if(!response.ok||!data.ok){statusNode.textContent=data.error||'Pairing failed';return;}
 sessionStorage.setItem('onyx_token',data.token);sessionStorage.setItem('onyx_key',data.key);
 localStorage.setItem('onyx_device_token',data.device_token);location.replace('/');};
</script></body></html>""")

        @app.post("/pair")
        async def pair_device(req: Request):
            """Consume an owner-visible code and return credentials in the body only."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False, "error": "Invalid request"}, status_code=400)
            entered = str(body.get("pin", "")).strip().upper()
            now = time.time()
            client_id = self._login_client_id(req)
            if self._login_is_locked(client_id, now):
                return JSONResponse(
                    {"ok": False, "error": "Too many attempts; try again later"},
                    status_code=429,
                )
            if entered not in self._pending_keys or self._pending_keys[entered] <= now:
                self._record_login_failure(client_id, now)
                return JSONResponse(
                    {"ok": False, "error": "Invalid or expired code"}, status_code=401
                )
            del self._pending_keys[entered]
            self._login_failures.pop(client_id, None)
            token = self._issue_token(entered)
            device_token = secrets.token_urlsafe(32)
            self._device_sessions[device_token] = {
                "session_key": entered,
                "expires_at": now + DEVICE_TOKEN_TTL,
            }
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Remote device paired with an owner-visible code."}
            ))
            return JSONResponse({
                "ok": True,
                "token": token,
                "key": entered,
                "device_token": device_token,
                "expires_in": ACCESS_TOKEN_TTL,
            })

        @app.get("/auto-login")
        async def retired_auto_login():
            """Never accept a credential-bearing URL retained by an older client."""
            return JSONResponse(
                {"ok": False, "error": "Credential-bearing QR links are retired; use /pair"},
                status_code=410,
            )

        @app.post("/api/device-login")
        async def device_login_ep(req: Request):
            """Return a fresh auth token for a previously paired device token."""
            try:
                body = await req.json()
            except Exception:
                return JSONResponse({"ok": False}, status_code=400)
            dev_tok = (body.get("device_token") or "").strip()
            device = self._device_sessions.get(dev_tok)
            if not device or device.get("expires_at", 0) <= time.time():
                self._device_sessions.pop(dev_tok, None)
                return JSONResponse({"ok": False}, status_code=401)
            session_key = device["session_key"]
            tok = self._issue_token(session_key)
            if self._connect_callback:
                self._connect_callback()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Known device reconnected automatically."}
            ))
            return JSONResponse({
                "ok": True, "token": tok, "key": session_key,
                "expires_in": ACCESS_TOKEN_TTL,
            })

        @app.post("/api/revoke-devices")
        async def revoke_devices(req: Request):
            """Invalidate all persistent device tokens (admin action)."""
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            count = len(self._device_sessions)
            self._device_sessions.clear()
            return JSONResponse({"ok": True, "revoked": count})

        if self._phase5_enabled:
            async def _phase5_read(
                req: Request,
                surface: str,
                *,
                offset: int = 0,
                page_size: int = 50,
            ):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)
                if offset < 0 or offset > 128 or page_size < 1 or page_size > 50:
                    return JSONResponse(
                        {"error": "Invalid bounded page"}, status_code=400
                    )
                bridge = self._phase5_bridge
                if bridge is None:
                    return JSONResponse(
                        {"error": "Phase 5 session unavailable"}, status_code=503
                    )
                try:
                    payload = await asyncio.to_thread(
                        lambda: bridge.dashboard_read(
                            surface, offset=offset, page_size=page_size
                        )
                    )
                except Exception as exc:
                    return JSONResponse(
                        {
                            "error": "Phase 5 projection unavailable",
                            "reason": type(exc).__name__,
                        },
                        status_code=503,
                    )
                return JSONResponse({"ok": True, **payload})

            @app.get("/api/phase5/status")
            async def phase5_status(req: Request):
                return await _phase5_read(req, "status")

            @app.get("/api/phase5/inbox")
            async def phase5_inbox(
                req: Request, offset: int = 0, page_size: int = 50
            ):
                return await _phase5_read(
                    req, "inbox", offset=offset, page_size=page_size
                )

            @app.get("/api/phase5/capabilities")
            async def phase5_capabilities(
                req: Request, offset: int = 0, page_size: int = 50
            ):
                return await _phase5_read(
                    req, "capabilities", offset=offset, page_size=page_size
                )

            @app.post("/api/phase5/kill")
            async def phase5_kill(req: Request):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)
                bridge = self._phase5_bridge
                if bridge is None:
                    return JSONResponse(
                        {"error": "Phase 5 session unavailable"}, status_code=503
                    )
                try:
                    payload = await asyncio.to_thread(bridge.kill)
                except Exception as exc:
                    return JSONResponse(
                        {
                            "error": "Phase 5 kill failed closed",
                            "reason": type(exc).__name__,
                        },
                        status_code=503,
                    )
                return JSONResponse({"ok": True, **payload})

        @app.post("/api/command")
        async def command(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body  = await req.json()
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            enc   = body.get("enc", "")
            if enc:
                text = self._decrypt(token, enc)
                if text is None:
                    return JSONResponse({"error": "Decryption failed"}, status_code=400)
            else:
                text = (body.get("text") or "").strip()
            if text:
                await self._command_queue.put(text)
                if self._wake_callback:
                    self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/wake")
        async def wake_ep(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            if self._wake_callback:
                self._wake_callback()
            return JSONResponse({"ok": True})

        @app.post("/api/ws-ticket")
        async def issue_ws_ticket(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            body = await req.json()
            scope = str(body.get("scope", "")).strip().lower()
            if scope not in {"command", "audio"}:
                return JSONResponse({"error": "Invalid WebSocket scope"}, status_code=400)
            token = req.headers.get("authorization", "").removeprefix("Bearer ").strip()
            ticket = self._issue_ws_ticket(token, scope)
            return JSONResponse({"ticket": ticket, "expires_in": WS_TICKET_TTL})

        # ── Phone mic real-time audio → Gemini Live ──────────────────────────

        @app.websocket("/ws/phone-audio")
        async def phone_audio_ws(websocket: WebSocket, ticket: str = ""):
            tok = self._consume_ws_ticket(ticket.strip(), "audio")
            if not tok:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            asyncio.create_task(self.broadcast(
                {"type": "sys", "text": "Phone microphone live."}
            ))
            try:
                while True:
                    remaining = self._tokens.get(tok, 0) - time.time()
                    if remaining <= 0 or not self._token_is_valid(tok):
                        await websocket.close(code=4001)
                        break
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_bytes(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        await websocket.close(code=4001, reason="Session expired")
                        break
                    if not self._token_is_valid(tok):
                        await websocket.close(code=4001, reason="Session expired")
                        break
                    try:
                        self._phone_audio_queue.put_nowait(
                            {"data": data, "mime_type": "audio/pcm"}
                        )
                    except asyncio.QueueFull:
                        pass  # drop frame rather than block
            except WebSocketDisconnect:
                pass
            finally:
                asyncio.create_task(self.broadcast(
                    {"type": "sys", "text": "Phone microphone stopped."}
                ))

        # ── File sharing ──────────────────────────────────────────────────────

        if _UPLOAD_OK:
            @app.post("/api/upload")
            async def upload_file(req: Request, file: UploadFile = FastAPIFile(...)):
                if not _auth(req):
                    return JSONResponse({"error": "Unauthorized"}, status_code=401)

                safe = _safe_filename(file.filename or "upload")
                size = 0
                max_bytes = MAX_UPLOAD_MB * 1024 * 1024
                temp_path = None
                temp_info = None
                fd = None
                try:
                    root_info = _verified_upload_root(self._uploads_dir)
                    temp_path, fd, temp_info = _open_upload_temp(
                        self._uploads_dir, root_info
                    )
                    with os.fdopen(fd, "wb", closefd=True) as fout:
                        fd = None
                        while True:
                            chunk = await file.read(65536)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                return JSONResponse(
                                    {"error": f"File too large (max {MAX_UPLOAD_MB} MB)"},
                                    status_code=413,
                                )
                            fout.write(chunk)
                        fout.flush()
                        os.fsync(fout.fileno())
                        written = os.fstat(fout.fileno())
                        if not _same_object(temp_info, written):
                            raise _UnsafeUploadPath(
                                "Temporary upload identity changed while writing"
                            )
                        dest = _publish_upload_no_replace(
                            self._uploads_dir,
                            root_info,
                            temp_path,
                            written,
                            safe,
                        )
                except (OSError, _UnsafeUploadPath):
                    return JSONResponse(
                        {"error": "Upload could not be stored safely"}, status_code=409
                    )
                finally:
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    if temp_path is not None and temp_info is not None:
                        _unlink_if_same(temp_path, temp_info)

                asyncio.create_task(self.broadcast({
                    "type": "file_received",
                    "name": dest.name,
                    "size": size,
                    "saved_to": str(self._uploads_dir),
                }))
                return JSONResponse({"ok": True, "name": dest.name, "size": size})
        else:
            @app.post("/api/upload")
            async def upload_unavailable(req: Request):
                return JSONResponse(
                    {"error": "File uploads require: pip install python-multipart"},
                    status_code=503,
                )

        @app.get("/api/files")
        async def list_files(req: Request):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                files = _list_verified_uploads(self._uploads_dir)
            except (OSError, _UnsafeUploadPath):
                files = []
            return JSONResponse({"files": files})

        @app.get("/uploads/{filename}")
        async def download_file(req: Request, filename: str):
            if not _auth(req):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            safe = _safe_filename(filename)
            if safe != filename or safe.startswith(_UPLOAD_TEMP_PREFIX):
                return JSONResponse({"error": "Not found"}, status_code=404)
            try:
                handle, info = _open_verified_download(self._uploads_dir, safe)
            except (OSError, _UnsafeUploadPath):
                return JSONResponse({"error": "Not found"}, status_code=404)
            try:
                return StreamingResponse(
                    _stream_file_handle(handle),
                    media_type="application/octet-stream",
                    headers={
                        "Content-Length": str(info.st_size),
                        "Content-Disposition": (
                            f"attachment; filename*=UTF-8''{quote(safe, safe='')}"
                        ),
                        "Cache-Control": "no-store",
                        "Referrer-Policy": "no-referrer",
                        "X-Content-Type-Options": "nosniff",
                    },
                )
            except Exception:
                handle.close()
                raise

        @app.websocket("/ws")
        async def ws_ep(websocket: WebSocket, ticket: str = ""):
            tok = self._consume_ws_ticket(ticket.strip(), "command")
            if not tok:
                await websocket.close(code=4001)
                return
            await websocket.accept()
            self._clients[websocket] = tok
            for entry in self._history[-50:]:
                try:
                    if not self._token_is_valid(tok):
                        await websocket.close(code=4001, reason="Session expired")
                        return
                    await websocket.send_json(entry)
                except Exception:
                    break
            try:
                while True:
                    remaining = self._tokens.get(tok, 0) - time.time()
                    if remaining <= 0 or not self._token_is_valid(tok):
                        await websocket.close(code=4001)
                        break
                    try:
                        data = await asyncio.wait_for(
                            websocket.receive_json(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        await websocket.close(code=4001, reason="Session expired")
                        break
                    # The token may have expired while the frame was in flight.
                    if not self._token_is_valid(tok):
                        await websocket.close(code=4001, reason="Session expired")
                        break
                    if data.get("type") == "command":
                        enc = data.get("enc", "")
                        t   = self._decrypt(tok, enc) if enc else (data.get("text") or "").strip()
                        if t:
                            await self._command_queue.put(t)
                            if self._wake_callback:
                                self._wake_callback()
            except WebSocketDisconnect:
                pass
            finally:
                self._clients.pop(websocket, None)

        return app

    # ── serve ─────────────────────────────────────────────────────────────

    async def _serve_alias(self) -> None:
        """Second HTTPS server on PORT+1 sharing the same app and in-memory state.
        Chrome HTTPS-upgrades any bare IP:PORT the user types, so this port also needs TLS.
        User types IP:8001 → Chrome tries https → self-signed cert warning → accept once → done."""
        ssl_key  = self._cert_dir / ONYX_KEY_NAME
        ssl_cert = self._cert_dir / ONYX_CERT_NAME
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT + 1)
        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT + 1, log_level="warning",
            lifespan="off",
            ssl_keyfile=str(ssl_key), ssl_certfile=str(ssl_cert),
        )
        print(
            f"[Dashboard] Manual entry:  {self.get_manual_url()}  "
            "(type in browser, accept cert once)"
        )
        await uvicorn.Server(cfg).serve()

    async def serve(self) -> None:
        if not _DEPS_OK:
            print("[Dashboard] fastapi/uvicorn not installed — dashboard disabled.")
            print("[Dashboard] Run:  pip install fastapi 'uvicorn[standard]' cryptography")
            return

        # Runtime-only setup: importing this module remains offline and
        # filesystem-neutral for diagnostics and tooling.
        await asyncio.to_thread(_ensure_crypto_js)
        if not self._uploads_dir_injected:
            self._uploads_dir = _make_uploads_dir()

        # Firewall setup runs in a thread — uvicorn starts immediately,
        # no waiting for UAC dialogs or subprocess timeouts.
        asyncio.get_event_loop().run_in_executor(None, _ensure_network_access, PORT)

        use_ssl  = self._ssl_enabled()
        ssl_key  = self._cert_dir / ONYX_KEY_NAME
        ssl_cert = self._cert_dir / ONYX_CERT_NAME

        alias_task = asyncio.create_task(self._serve_alias()) if use_ssl else None

        cfg = uvicorn.Config(
            self.app, host="0.0.0.0", port=PORT, log_level="warning",
            lifespan="off",
            **({"ssl_keyfile": str(ssl_key), "ssl_certfile": str(ssl_cert)} if use_ssl else {}),
        )

        proto = "https" if use_ssl else "http"
        print(f"[Dashboard] {proto}://{self._ip}:{PORT}")
        print("[Dashboard] Press 'Remote Control' in Onyx UI to get the QR code.")
        try:
            await uvicorn.Server(cfg).serve()
        finally:
            if alias_task is not None:
                alias_task.cancel()
                await asyncio.gather(alias_task, return_exceptions=True)
