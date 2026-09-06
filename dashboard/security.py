"""Pure TLS and bearer-token primitives shared by dashboard and diagnostics.

Importing this module performs no filesystem, network, or process activity.
"""

from __future__ import annotations

import ipaddress
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ONYX_KEY_NAME = "onyx.key"
ONYX_CERT_NAME = "onyx.crt"


def ensure_local_certificate(cert_dir: Path, hosts: list[str]) -> tuple[Path, Path]:
    """Create or validate a unique per-install self-signed TLS identity."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key_path = cert_dir / ONYX_KEY_NAME
    cert_path = cert_dir / ONYX_CERT_NAME
    if key_path.exists() and cert_path.exists():
        try:
            existing_cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
            existing_key = serialization.load_pem_private_key(
                key_path.read_bytes(), password=None
            )
            cert_public = existing_cert.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            key_public = existing_key.public_key().public_bytes(
                serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            expires = getattr(existing_cert, "not_valid_after_utc", None)
            if expires is None:
                expires = existing_cert.not_valid_after.replace(tzinfo=timezone.utc)
            san = existing_cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            cert_hosts = {
                str(value)
                for value in (
                    san.get_values_for_type(x509.DNSName)
                    + san.get_values_for_type(x509.IPAddress)
                )
            }
            requested_hosts = {"localhost", *filter(None, hosts)}
            if (
                cert_public == key_public
                and expires > datetime.now(timezone.utc) + timedelta(days=7)
                and requested_hosts.issubset(cert_hosts)
            ):
                return key_path, cert_path
        except Exception:
            pass

    cert_dir.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Onyx Local Dashboard")]
    )
    san_names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for host in hosts:
        try:
            san_names.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            if host and host != "localhost":
                san_names.append(x509.DNSName(host))

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    try:
        key_path.chmod(0o600)
    except OSError:
        pass
    print(f"[Dashboard] Generated unique local TLS certificate: {cert_path}")
    return key_path, cert_path


def issue_token(
    tokens: dict[str, float],
    token_keys: dict[str, str],
    session_key: str,
    ttl: float,
    *,
    now: float | None = None,
) -> str:
    """Issue a bearer token into caller-owned stores."""
    token = secrets.token_urlsafe(32)
    tokens[token] = (time.time() if now is None else now) + ttl
    token_keys[token] = session_key
    return token


def token_is_valid(
    tokens: dict[str, float],
    token_keys: dict[str, str],
    token: str,
    *,
    now: float | None = None,
) -> bool:
    """Validate a bearer token and remove expired state."""
    if tokens.get(token, 0) > (time.time() if now is None else now):
        return True
    tokens.pop(token, None)
    token_keys.pop(token, None)
    return False
