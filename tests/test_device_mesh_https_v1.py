from __future__ import annotations

import hashlib
import json

import pytest

from core.device_mesh_https_v1 import (
    CertificatePinnedHttpsTransportV1,
    DeviceMeshHttpsDenied,
    DeviceMeshHttpsEndpointV1,
)
from core.device_mesh_v1 import AuthenticatedMeshRequestV1


CERTIFICATE = b"test-der-certificate"
PIN = hashlib.sha256(CERTIFICATE).hexdigest()


def _request(payload: bytes = b"metadata") -> AuthenticatedMeshRequestV1:
    return AuthenticatedMeshRequestV1(
        "req_1234567890",
        "device_source",
        "device_target",
        "owner_primary",
        "workspace_primary",
        "onyx.source",
        "onyx.target",
        "read.calendar",
        "calendar_primary",
        100.0,
        160.0,
        "nonce_1234567890",
        hashlib.sha256(payload).hexdigest(),
        "1" * 64,
    )


class _Socket:
    def __init__(self, certificate: bytes) -> None:
        self.certificate = certificate

    def getpeercert(self, *, binary_form: bool = False) -> bytes:
        assert binary_form is True
        return self.certificate


class _Response:
    status = 202

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id

    def read(self, maximum: int) -> bytes:
        assert maximum == 16_385
        return json.dumps(
            {
                "contract": "OnyxDeviceMeshHttpsAck.v1",
                "request_id": self.request_id,
                "status": "accepted",
            }
        ).encode()


class _Connection:
    def __init__(self, certificate: bytes, request_id: str) -> None:
        self.sock = _Socket(certificate)
        self.request_id = request_id
        self.connected = False
        self.sent = []
        self.closed = False

    def connect(self) -> None:
        self.connected = True

    def request(self, method, url, body, headers) -> None:
        assert self.connected is True
        self.sent.append((method, url, body, headers))

    def getresponse(self):
        return _Response(self.request_id)

    def close(self) -> None:
        self.closed = True


def _transport(connection: _Connection) -> CertificatePinnedHttpsTransportV1:
    endpoint = DeviceMeshHttpsEndpointV1(
        "device_target_endpoint",
        "https://device.example.test:8443/onyx/mesh/v1/receive",
        PIN,
    )

    def factory(host, port, timeout, context):
        assert (host, port, timeout) == ("device.example.test", 8443, 10.0)
        assert context.check_hostname is True
        return connection

    return CertificatePinnedHttpsTransportV1(
        endpoint, connection_factory=factory
    )


def test_transport_pins_tls_before_metadata_only_explicit_send() -> None:
    request = _request()
    connection = _Connection(CERTIFICATE, request.request_id)
    transport = _transport(connection)
    acknowledgement = transport.send(request, b"metadata")
    assert acknowledgement == f"https_accepted:{request.request_id}"
    assert transport.background_workers == 0
    assert transport.polling_interval is None
    assert transport.retry_count == 0
    assert connection.closed is True
    method, path, body, headers = connection.sent[0]
    assert (method, path) == ("POST", "/onyx/mesh/v1/receive")
    assert headers["Content-Type"] == "application/json"
    payload = json.loads(body)
    assert payload["request"]["request_id"] == request.request_id
    assert payload["request"]["signature"] == request.signature


def test_pin_mismatch_sends_no_request_bytes_and_closes() -> None:
    request = _request()
    connection = _Connection(b"wrong-certificate", request.request_id)
    with pytest.raises(DeviceMeshHttpsDenied, match="pin"):
        _transport(connection).send(request, b"metadata")
    assert connection.sent == []
    assert connection.closed is True


def test_acknowledgement_must_be_bound_to_exact_request() -> None:
    request = _request()
    connection = _Connection(CERTIFICATE, "req_another_request")
    with pytest.raises(DeviceMeshHttpsDenied, match="bound"):
        _transport(connection).send(request, b"metadata")


def test_receiver_capability_result_is_accepted_without_weakening_ack_binding() -> None:
    request = _request()

    class ResultResponse(_Response):
        def read(self, maximum: int) -> bytes:
            assert maximum == 16_385
            return json.dumps(
                {
                    "contract": "OnyxDeviceMeshHttpsAck.v1",
                    "request_id": self.request_id,
                    "status": "accepted",
                    "result": {"state": "ready", "remote_execution": False},
                }
            ).encode()

    class ResultConnection(_Connection):
        def getresponse(self):
            return ResultResponse(self.request_id)

    connection = ResultConnection(CERTIFICATE, request.request_id)
    assert _transport(connection).send(request, b"metadata") == (
        f"https_accepted:{request.request_id}"
    )


@pytest.mark.parametrize(
    "url",
    (
        "http://device.example.test/mesh",
        "https://user:pass@device.example.test/mesh",
        "https://device.example.test/",
        "https://device.example.test/mesh?token=secret",
        "https://device.example.test/mesh#fragment",
        "https://device.example.test/a/../mesh",
        "https://device.example.test/mesh%2Freceive",
    ),
)
def test_endpoint_rejects_unsafe_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match="URL"):
        DeviceMeshHttpsEndpointV1("device_target_endpoint", url, PIN)
