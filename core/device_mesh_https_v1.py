"""Certificate-pinned HTTPS transport for authenticated Onyx mesh requests.

This transport owns no listener, worker, discovery mechanism or retry loop. It
performs one explicit HTTPS exchange after the caller has durably reserved the
request through ``AuthenticatedDeviceMeshV1.send``. TLS identity is pinned
before request bytes leave the process and the acknowledgement is bound to the
exact request identifier.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import http.client
import json
import re
import ssl
from dataclasses import dataclass
from typing import Callable, Protocol
from urllib.parse import urlsplit

from core.device_mesh_v1 import AuthenticatedMeshRequestV1


_DIGEST = re.compile(r"[0-9a-f]{64}")
_PATH = re.compile(r"/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]+")
_MAX_RESPONSE_BYTES = 16_384
_MAX_WIRE_BYTES = 96_000


class DeviceMeshHttpsError(RuntimeError):
    pass


class DeviceMeshHttpsContractError(ValueError):
    pass


class DeviceMeshHttpsDenied(PermissionError):
    pass


class _SocketV1(Protocol):
    def getpeercert(self, *, binary_form: bool = False) -> bytes: ...


class _ConnectionV1(Protocol):
    sock: _SocketV1 | None

    def connect(self) -> None: ...

    def request(
        self,
        method: str,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> None: ...

    def getresponse(self) -> http.client.HTTPResponse: ...

    def close(self) -> None: ...


ConnectionFactoryV1 = Callable[[str, int, float, ssl.SSLContext], _ConnectionV1]


@dataclass(frozen=True)
class DeviceMeshHttpsEndpointV1:
    endpoint_id: str
    url: str
    certificate_sha256: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if (
            type(self.endpoint_id) is not str
            or not 3 <= len(self.endpoint_id) <= 128
            or not self.endpoint_id.replace("_", "").replace("-", "").isalnum()
        ):
            raise DeviceMeshHttpsContractError("endpoint_id is invalid")
        parsed = urlsplit(self.url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or _PATH.fullmatch(parsed.path) is None
            or any(part in {".", ".."} for part in parsed.path.split("/"))
        ):
            raise DeviceMeshHttpsContractError("endpoint URL is invalid")
        try:
            port = parsed.port
        except ValueError as exc:
            raise DeviceMeshHttpsContractError("endpoint port is invalid") from exc
        if port is not None and not 1 <= port <= 65_535:
            raise DeviceMeshHttpsContractError("endpoint port is invalid")
        if _DIGEST.fullmatch(self.certificate_sha256) is None:
            raise DeviceMeshHttpsContractError("certificate pin is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 1.0 <= float(self.timeout_seconds) <= 30.0
        ):
            raise DeviceMeshHttpsContractError("timeout_seconds is invalid")


def _default_connection(
    host: str, port: int, timeout: float, context: ssl.SSLContext
) -> _ConnectionV1:
    return http.client.HTTPSConnection(host, port, timeout=timeout, context=context)


def _tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


class CertificatePinnedHttpsTransportV1:
    def __init__(
        self,
        endpoint: DeviceMeshHttpsEndpointV1,
        *,
        connection_factory: ConnectionFactoryV1 = _default_connection,
    ) -> None:
        if type(endpoint) is not DeviceMeshHttpsEndpointV1:
            raise DeviceMeshHttpsContractError("exact endpoint is required")
        if not callable(connection_factory):
            raise DeviceMeshHttpsContractError("connection factory is invalid")
        self.endpoint = endpoint
        self._connection_factory = connection_factory
        self.background_workers = 0
        self.polling_interval = None
        self.retry_count = 0

    def send(self, request: AuthenticatedMeshRequestV1, payload: bytes) -> str:
        if type(request) is not AuthenticatedMeshRequestV1:
            raise DeviceMeshHttpsContractError("exact authenticated request is required")
        if type(payload) is not bytes:
            raise DeviceMeshHttpsContractError("payload must be exact bytes")
        if hashlib.sha256(payload).hexdigest() != request.payload_digest:
            raise DeviceMeshHttpsDenied("payload digest does not match request")
        wire = json.dumps(
            {
                "contract": "OnyxDeviceMeshHttpsRequest.v1",
                "request": {**request.unsigned_claims(), "signature": request.signature},
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(wire) > _MAX_WIRE_BYTES:
            raise DeviceMeshHttpsContractError("wire request exceeds its byte budget")

        parsed = urlsplit(self.endpoint.url)
        assert parsed.hostname is not None
        port = parsed.port or 443
        connection = self._connection_factory(
            parsed.hostname,
            port,
            float(self.endpoint.timeout_seconds),
            _tls_context(),
        )
        try:
            connection.connect()
            socket = connection.sock
            if socket is None:
                raise DeviceMeshHttpsDenied("TLS peer socket is unavailable")
            certificate = socket.getpeercert(binary_form=True)
            if not certificate or not isinstance(certificate, bytes):
                raise DeviceMeshHttpsDenied("TLS peer certificate is unavailable")
            observed = hashlib.sha256(certificate).hexdigest()
            if not hmac.compare_digest(observed, self.endpoint.certificate_sha256):
                raise DeviceMeshHttpsDenied("TLS certificate pin does not match")
            connection.request(
                "POST",
                parsed.path,
                wire,
                {
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Content-Length": str(len(wire)),
                    "User-Agent": "Onyx-Device-Mesh/1",
                },
            )
            response = connection.getresponse()
            if not 200 <= response.status <= 299:
                raise DeviceMeshHttpsError(
                    f"mesh endpoint returned HTTP {response.status}"
                )
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise DeviceMeshHttpsError("mesh acknowledgement exceeds its byte budget")
            try:
                acknowledgement = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise DeviceMeshHttpsError("mesh acknowledgement is invalid JSON") from exc
            expected = {
                "contract": "OnyxDeviceMeshHttpsAck.v1",
                "request_id": request.request_id,
                "status": "accepted",
            }
            if (
                type(acknowledgement) is not dict
                or set(acknowledgement) not in (
                    set(expected),
                    {*expected, "result"},
                )
                or any(acknowledgement.get(key) != value for key, value in expected.items())
                or (
                    "result" in acknowledgement
                    and type(acknowledgement["result"]) is not dict
                )
            ):
                raise DeviceMeshHttpsDenied(
                    "mesh acknowledgement is not bound to the request"
                )
            return f"https_accepted:{request.request_id}"
        finally:
            connection.close()
