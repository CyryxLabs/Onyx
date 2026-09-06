from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.device_mesh_receiver_v1 import (
    CAPABILITY_ADVERTISE,
    CAPABILITY_HEALTH,
    CAPABILITY_RECEIPT,
    CONTRACT_REQUEST,
    RECEIVER_RESOURCE,
    DeviceMeshReceiverAsgiV1,
    DeviceMeshReceiverDenied,
    DeviceMeshReceiverError,
    DeviceMeshReceiverFeatureGateV1,
    DeviceMeshReceiverStoreV1,
    DeviceMeshReceiverV1,
    OutboundDispatchBindingV1,
    mount_device_mesh_receiver_v1,
)
from core.device_mesh_v1 import (
    AuthenticatedDeviceMeshV1,
    AuthenticatedMeshRequestV1,
    DeviceMeshDenied,
    DeviceMeshError,
    DeviceMeshFeatureGateV1,
    DeviceMeshRegistryV1,
    EnrolledDeviceV1,
)
from core.native_vault import SecretReference


OWNER = "owner_primary"
WORKSPACE = "workspace_primary"
SOURCE_SECRET = b"source-device-secret-material-32bytes"
TARGET_SECRET = b"target-device-secret-material-32bytes"
MESH_LEDGER_KEY = b"m" * 32
RECEIVER_LEDGER_KEY = b"r" * 32
_DEFAULT_LOOKUP = object()


def _device(device_id: str, issuer: str, account: str) -> EnrolledDeviceV1:
    return EnrolledDeviceV1(
        device_id,
        OWNER,
        WORKSPACE,
        issuer,
        SecretReference("Onyx.DeviceMesh.v1", account, f"Onyx device {device_id}"),
        True,
    )


def _vault(reference: SecretReference) -> bytes | None:
    return {"source": SOURCE_SECRET, "target": TARGET_SECRET}.get(reference.account)


def _registry(path: Path) -> DeviceMeshRegistryV1:
    registry = DeviceMeshRegistryV1(
        path, DeviceMeshFeatureGateV1(True), ledger_auth_key=MESH_LEDGER_KEY
    )
    registry.enroll(_device("device_source", "onyx.source", "source"))
    registry.enroll(_device("device_target", "onyx.target", "target"))
    return registry


def _mesh(registry: DeviceMeshRegistryV1, local: str) -> AuthenticatedDeviceMeshV1:
    return AuthenticatedDeviceMeshV1(
        local_device_id=local,
        registry=registry,
        vault_reader=_vault,
        authority=lambda *_args: True,
        clock=lambda: 1_000.0,
    )


def _outbound_lookup(origin_request_id: str) -> OutboundDispatchBindingV1 | None:
    if origin_request_id != "req_origin_123":
        return None
    return OutboundDispatchBindingV1(
        "req_origin_123",
        OWNER,
        WORKSPACE,
        "device_source",
        "a" * 64,
        "succeeded",
    )


def _receiver(
    tmp_path: Path,
    *,
    authority=lambda *_args: True,
    max_source_requests: int = 60,
    timeout: float = 1.0,
    max_concurrency: int = 8,
    outbound_lookup=_DEFAULT_LOOKUP,
) -> tuple[
    AuthenticatedDeviceMeshV1,
    DeviceMeshReceiverV1,
    DeviceMeshReceiverAsgiV1,
    Path,
]:
    registry = _registry(tmp_path / "mesh.sqlite3")
    source = _mesh(registry, "device_source")
    target = _mesh(registry, "device_target")
    path = tmp_path / "receiver.sqlite3"
    gate = DeviceMeshReceiverFeatureGateV1(True)
    store = DeviceMeshReceiverStoreV1(path, gate, ledger_auth_key=RECEIVER_LEDGER_KEY)
    receiver = DeviceMeshReceiverV1(
        mesh=target,
        store=store,
        authority=authority,
        outbound_dispatch_lookup=(
            _outbound_lookup if outbound_lookup is _DEFAULT_LOOKUP else outbound_lookup
        ),
        max_source_requests=max_source_requests,
    )
    adapter = DeviceMeshReceiverAsgiV1(
        receiver,
        gate,
        max_concurrency=max_concurrency,
        request_timeout_seconds=timeout,
    )
    return source, receiver, adapter, path


def _sign(request: AuthenticatedMeshRequestV1) -> AuthenticatedMeshRequestV1:
    signature = hmac.new(
        SOURCE_SECRET,
        json.dumps(
            request.unsigned_claims(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        hashlib.sha256,
    ).hexdigest()
    return replace(request, signature=signature)


def _issue(
    source: AuthenticatedDeviceMeshV1,
    capability: str,
    resource: str,
    payload: bytes = b"{}",
) -> tuple[AuthenticatedMeshRequestV1, bytes]:
    return source.issue(
        target_device_id="device_target",
        capability=capability,
        resource=resource,
        payload=payload,
    )


def _wire(request: AuthenticatedMeshRequestV1, payload: bytes) -> bytes:
    return json.dumps(
        {
            "contract": CONTRACT_REQUEST,
            "request": {**request.unsigned_claims(), "signature": request.signature},
            "payload_base64": base64.b64encode(payload).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _plain_anchor(
    event_count: int, tail_seq: int, tail_hash: str, projection_digest: str
) -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "event_count": event_count,
                "tail_seq": tail_seq,
                "tail_hash": tail_hash,
                "projection_digest": projection_digest,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()


def _post(client: TestClient, path: str, request, payload):
    return client.post(path, content=_wire(request, payload))


def test_receiver_is_default_off_and_has_zero_idle_work(tmp_path: Path) -> None:
    assert DeviceMeshReceiverFeatureGateV1.from_environ({}).enabled is False
    with pytest.raises(DeviceMeshReceiverDenied, match="disabled"):
        DeviceMeshReceiverStoreV1(
            tmp_path / "off.sqlite3", DeviceMeshReceiverFeatureGateV1(False)
        )
    _source, receiver, adapter, _path = _receiver(tmp_path)
    assert receiver.background_workers == adapter.background_workers == 0
    assert receiver.polling_interval is adapter.polling_interval is None


def test_enabled_receiver_store_requires_exact_external_ledger_key(
    tmp_path: Path,
) -> None:
    for invalid in (None, b"short", b"x" * 33):
        with pytest.raises(DeviceMeshReceiverDenied, match="authentication key"):
            DeviceMeshReceiverStoreV1(
                tmp_path / f"invalid-{len(invalid or b'')}.sqlite3",
                DeviceMeshReceiverFeatureGateV1(True),
                ledger_auth_key=invalid,
            )


def test_receiver_store_reopen_with_wrong_external_key_fails_closed(
    tmp_path: Path,
) -> None:
    _source, _receiver_value, _adapter, path = _receiver(tmp_path)
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=b"w" * 32,
        )


def test_signed_health_and_capability_advertisement_use_exact_central_authority(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []
    source, _receiver_value, adapter, _path = _receiver(
        tmp_path, authority=lambda *args: calls.append(args) is None
    )
    with TestClient(adapter, base_url="https://receiver.test") as client:
        request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
        response = _post(client, "/onyx/mesh/v1/health", request, payload)
        assert response.status_code == 202
        assert response.json()["result"] == {
            "remote_execution": False,
            "state": "ready",
        }
        advertised, advertised_payload = _issue(
            source, CAPABILITY_ADVERTISE, RECEIVER_RESOURCE
        )
        capability_response = _post(
            client,
            "/onyx/mesh/v1/capabilities",
            advertised,
            advertised_payload,
        )
    assert capability_response.status_code == 202
    assert capability_response.json()["result"]["remote_execution"] is False
    assert set(capability_response.json()["result"]["capabilities"]) == {
        CAPABILITY_HEALTH,
        CAPABILITY_ADVERTISE,
        CAPABILITY_RECEIPT,
    }
    assert calls == [
        (OWNER, WORKSPACE, CAPABILITY_HEALTH, RECEIVER_RESOURCE, "device_source"),
        (OWNER, WORKSPACE, CAPABILITY_ADVERTISE, RECEIVER_RESOURCE, "device_source"),
    ]


def test_adapter_mounts_additively_on_existing_tls_asgi_app(tmp_path: Path) -> None:
    source, _receiver_value, adapter, _path = _receiver(tmp_path)
    app = FastAPI()

    @app.get("/existing")
    async def existing():
        return {"ok": True}

    mount_device_mesh_receiver_v1(app, adapter)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(app, base_url="https://receiver.test") as client:
        assert client.get("/existing").json() == {"ok": True}
        response = _post(client, "/onyx/mesh/v1/health", request, payload)
    assert response.status_code == 202
    assert response.json()["request_id"] == request.request_id


def test_receipt_intent_is_durable_and_duplicate_returns_identical_ack(
    tmp_path: Path,
) -> None:
    source, _receiver_value, adapter, path = _receiver(tmp_path)
    payload = json.dumps(
        {
            "contract": "OnyxDeviceMeshReceipt.v1",
            "origin_request_id": "req_origin_123",
            "status": "succeeded",
            "payload_digest": "a" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request, payload = _issue(source, CAPABILITY_RECEIPT, "req_origin_123", payload)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        first = _post(client, "/onyx/mesh/v1/receive", request, payload)
        duplicate = _post(client, "/onyx/mesh/v1/receive", request, payload)
    assert first.status_code == duplicate.status_code == 202
    assert first.content == duplicate.content
    assert _receiver_value.store.receipt(request.request_id).response == first.json()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT status FROM receiver_intents WHERE request_id=?",
            (request.request_id,),
        ).fetchone() == ("accepted",)
    raw = path.read_bytes()
    assert payload not in raw
    assert SOURCE_SECRET not in raw


def test_receipt_fails_closed_without_authoritative_outbound_lookup(
    tmp_path: Path,
) -> None:
    source, _receiver_value, adapter, path = _receiver(tmp_path, outbound_lookup=None)
    payload = json.dumps(
        {
            "contract": "OnyxDeviceMeshReceipt.v1",
            "origin_request_id": "req_nonexistent_123",
            "status": "succeeded",
            "payload_digest": "f" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request, payload = _issue(
        source, CAPABILITY_RECEIPT, "req_nonexistent_123", payload
    )
    with TestClient(adapter, base_url="https://receiver.test") as client:
        response = _post(client, "/onyx/mesh/v1/receive", request, payload)
    assert response.status_code == 503
    assert response.json()["result"] == {
        "reason": "outbound_dispatch_authority_unavailable"
    }
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (0,)


def test_receipt_for_nonexistent_authoritative_origin_is_durably_denied(
    tmp_path: Path,
) -> None:
    source, _receiver_value, adapter, path = _receiver(tmp_path)
    payload = json.dumps(
        {
            "contract": "OnyxDeviceMeshReceipt.v1",
            "origin_request_id": "req_nonexistent_123",
            "status": "succeeded",
            "payload_digest": "f" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request, payload = _issue(
        source, CAPABILITY_RECEIPT, "req_nonexistent_123", payload
    )
    with TestClient(adapter, base_url="https://receiver.test") as client:
        first = _post(client, "/onyx/mesh/v1/receive", request, payload)
        duplicate = _post(client, "/onyx/mesh/v1/receive", request, payload)
    assert first.status_code == duplicate.status_code == 403
    assert first.content == duplicate.content
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT status FROM receiver_intents WHERE request_id=?",
            (request.request_id,),
        ).fetchone() == ("denied",)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("origin_request_id", "req_different_123"),
        ("owner_profile_id", "owner_different"),
        ("workspace_id", "workspace_different"),
        ("target_device_id", "device_different"),
        ("payload_digest", "b" * 64),
        ("receipt_status", "failed"),
    ),
)
def test_receipt_rejects_every_outbound_binding_mismatch(
    tmp_path: Path, field: str, replacement: str
) -> None:
    def mismatched(origin_request_id: str) -> OutboundDispatchBindingV1:
        values = {
            "origin_request_id": origin_request_id,
            "owner_profile_id": OWNER,
            "workspace_id": WORKSPACE,
            "target_device_id": "device_source",
            "payload_digest": "a" * 64,
            "receipt_status": "succeeded",
        }
        values[field] = replacement
        return OutboundDispatchBindingV1(**values)

    source, _receiver_value, adapter, _path = _receiver(
        tmp_path, outbound_lookup=mismatched
    )
    payload = json.dumps(
        {
            "contract": "OnyxDeviceMeshReceipt.v1",
            "origin_request_id": "req_origin_123",
            "status": "succeeded",
            "payload_digest": "a" * 64,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    request, payload = _issue(source, CAPABILITY_RECEIPT, "req_origin_123", payload)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        first = _post(client, "/onyx/mesh/v1/receive", request, payload)
        duplicate = _post(client, "/onyx/mesh/v1/receive", request, payload)
    assert first.status_code == duplicate.status_code == 403
    assert first.content == duplicate.content
    assert first.json()["result"] == {"reason": "outbound_dispatch_binding_denied"}


def test_tls_query_tamper_spoof_and_unsupported_action_fail_closed(
    tmp_path: Path,
) -> None:
    authority_calls: list[object] = []
    source, _receiver_value, adapter, path = _receiver(
        tmp_path, authority=lambda *args: authority_calls.append(args) is None
    )
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(adapter, base_url="http://receiver.test") as client:
        assert (
            _post(client, "/onyx/mesh/v1/health", request, payload).status_code == 426
        )
    with TestClient(adapter, base_url="https://receiver.test") as client:
        assert (
            client.post(
                "/onyx/mesh/v1/health?token=forbidden",
                content=_wire(request, payload),
            ).status_code
            == 405
        )
        assert (
            _post(
                client, "/onyx/mesh/v1/health", request, b'{"tampered":true}'
            ).status_code
            == 403
        )
        spoofed = _sign(replace(request, audience="onyx.attacker"))
        assert (
            _post(client, "/onyx/mesh/v1/health", spoofed, payload).status_code == 403
        )
        unsupported, unsupported_payload = _issue(
            source, "desktop.execute", "desktop_primary"
        )
        assert (
            _post(
                client,
                "/onyx/mesh/v1/receive",
                unsupported,
                unsupported_payload,
            ).status_code
            == 403
        )
    assert authority_calls == []
    with sqlite3.connect(path) as connection:
        # Authentication failures never create a durable dispatch intent.
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (0,)


def test_nonce_rebinding_and_cross_scope_spoof_are_denied(tmp_path: Path) -> None:
    source, _receiver_value, adapter, _path = _receiver(tmp_path)
    first, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    second, _ = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    rebound = _sign(replace(second, nonce=first.nonce))
    cross_scope = _sign(replace(second, owner_profile_id="owner_attacker"))
    with TestClient(adapter, base_url="https://receiver.test") as client:
        assert _post(client, "/onyx/mesh/v1/health", first, payload).status_code == 202
        assert (
            _post(client, "/onyx/mesh/v1/health", rebound, payload).status_code == 409
        )
        assert (
            _post(client, "/onyx/mesh/v1/health", cross_scope, payload).status_code
            == 403
        )


def test_expired_signed_request_is_denied_without_durable_intent(
    tmp_path: Path,
) -> None:
    source, _receiver_value, adapter, path = _receiver(tmp_path)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    expired = _sign(replace(request, issued_at=900.0, expires_at=999.0))
    with TestClient(adapter, base_url="https://receiver.test") as client:
        response = _post(client, "/onyx/mesh/v1/health", expired, payload)
    assert response.status_code == 403
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (0,)


def test_wire_size_and_authenticated_source_rate_are_bounded(tmp_path: Path) -> None:
    source, _receiver_value, adapter, path = _receiver(tmp_path, max_source_requests=1)
    first, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    second, _ = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        accepted = _post(client, "/onyx/mesh/v1/health", first, payload)
        limited = _post(client, "/onyx/mesh/v1/health", second, payload)
        duplicate = _post(client, "/onyx/mesh/v1/health", first, payload)
        oversized = client.post("/onyx/mesh/v1/health", content=b"x" * 96_001)
    assert accepted.status_code == duplicate.status_code == 202
    assert accepted.content == duplicate.content
    assert limited.status_code == 429
    assert oversized.status_code == 400
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (1,)
        # Rate denials happen before durable reservation and event amplification.
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_events"
        ).fetchone() == (2,)


def test_timeout_becomes_stable_reconciliation_and_survives_restart(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def slow_authority(*_args) -> bool:
        entered.set()
        try:
            release.wait(1.0)
            return True
        finally:
            completed.set()

    source, receiver, adapter, path = _receiver(
        tmp_path, authority=slow_authority, timeout=0.05, max_concurrency=1
    )
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    second, second_payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        response = _post(client, "/onyx/mesh/v1/health", request, payload)
        assert entered.is_set()
        limited = _post(client, "/onyx/mesh/v1/health", second, second_payload)
        assert limited.status_code == 429
        assert adapter.active_workers == 1
        assert adapter.background_workers == 1
        assert adapter.execution_worker_capacity == 1
        release.set()
        assert completed.wait(0.5)
        deadline = time.monotonic() + 0.5
        while adapter.active_workers and time.monotonic() < deadline:
            time.sleep(0.005)
        assert adapter.background_workers == 0
        duplicate = _post(client, "/onyx/mesh/v1/health", request, payload)
    assert response.status_code == duplicate.status_code == 202
    assert response.json()["status"] == "reconciliation"
    assert response.content == duplicate.content
    restarted_store = DeviceMeshReceiverStoreV1(
        path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
    )
    restarted = DeviceMeshReceiverV1(
        mesh=receiver._mesh,
        store=restarted_store,
        authority=lambda *_args: True,
    )
    assert restarted.recovered_on_startup == 0
    assert restarted.process(request, payload).status == "reconciliation"


def test_authority_exception_returns_stored_reconciliation_on_first_response(
    tmp_path: Path,
) -> None:
    def failing_authority(*_args) -> bool:
        raise RuntimeError("authority backend unavailable")

    source, _receiver_value, adapter, _path = _receiver(
        tmp_path, authority=failing_authority
    )
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        first = _post(client, "/onyx/mesh/v1/health", request, payload)
        duplicate = _post(client, "/onyx/mesh/v1/health", request, payload)
    assert first.status_code == duplicate.status_code == 202
    assert first.content == duplicate.content
    assert first.json()["status"] == "reconciliation"
    assert first.json()["result"] == {
        "detail": "receiver_failure_requires_reconciliation"
    }


def test_concurrent_exact_duplicate_reconciles_before_rate_limit(
    tmp_path: Path,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    results = []

    def blocking_authority(*_args) -> bool:
        entered.set()
        release.wait(1.0)
        return True

    source, receiver, _adapter, _path = _receiver(
        tmp_path, authority=blocking_authority, max_source_requests=1
    )
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    first_thread = threading.Thread(
        target=lambda: results.append(receiver.process(request, payload))
    )
    first_thread.start()
    assert entered.wait(0.5)
    duplicate = receiver.process(request, payload)
    release.set()
    first_thread.join(0.5)
    assert first_thread.is_alive() is False
    assert duplicate.status == "reconciliation"
    assert len(results) == 1
    assert results[0].response == duplicate.response


def test_concurrency_budget_rejects_second_inflight_request(tmp_path: Path) -> None:
    entered = threading.Event()
    release = threading.Event()

    def blocking_authority(*_args) -> bool:
        entered.set()
        release.wait(1.0)
        return True

    source, _receiver_value, adapter, _path = _receiver(
        tmp_path,
        authority=blocking_authority,
        timeout=1.0,
        max_concurrency=1,
    )
    first, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    second, _ = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)

    async def exchange(request: AuthenticatedMeshRequestV1) -> tuple[int, bytes]:
        sent: list[dict[str, object]] = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": _wire(request, payload)}

        async def send(message):
            sent.append(message)

        await adapter(
            {
                "type": "http",
                "scheme": "https",
                "method": "POST",
                "path": "/onyx/mesh/v1/health",
                "root_path": "",
                "query_string": b"",
            },
            receive,
            send,
        )
        status = int(sent[0]["status"])
        return status, bytes(sent[1]["body"])

    async def scenario():
        first_task = asyncio.create_task(exchange(first))
        assert await asyncio.to_thread(entered.wait, 0.5)
        second_result = await exchange(second)
        release.set()
        return await first_task, second_result

    first_result, second_result = asyncio.run(scenario())
    assert first_result[0] == 202
    assert second_result[0] == 429


def test_crash_left_intent_is_reconciled_before_any_new_dispatch(
    tmp_path: Path,
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    receiver._mesh.authenticate(request, payload)
    assert receiver.store.reserve(request).fresh is True
    restarted_store = DeviceMeshReceiverStoreV1(
        path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
    )
    restarted = DeviceMeshReceiverV1(
        mesh=receiver._mesh,
        store=restarted_store,
        authority=lambda *_args: True,
    )
    assert restarted.recovered_on_startup == 1
    receipt = restarted.process(request, payload)
    assert receipt.status == "reconciliation"
    assert receipt.response["result"] == {"detail": "restart_requires_reconciliation"}


@pytest.mark.parametrize("mutation", ("gap", "previous", "hash", "canonical"))
def test_receiver_event_chain_tamper_fails_closed_after_trigger_recreation(
    tmp_path: Path, mutation: str
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert receiver.process(request, payload).status == "accepted"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER receiver_events_no_update")
        connection.execute("DROP TRIGGER receiver_events_no_delete")
        if mutation == "gap":
            connection.execute("DELETE FROM receiver_events WHERE seq=1")
        elif mutation == "previous":
            connection.execute(
                "UPDATE receiver_events SET prev_hash=? WHERE seq=2", ("f" * 64,)
            )
        elif mutation == "hash":
            connection.execute(
                "UPDATE receiver_events SET event_hash=? WHERE seq=1", ("f" * 64,)
            )
        else:
            connection.execute(
                "UPDATE receiver_events SET detail_json='{ }' WHERE seq=1"
            )
        connection.execute(
            """CREATE TRIGGER receiver_events_no_update BEFORE UPDATE ON receiver_events
            BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END"""
        )
        connection.execute(
            """CREATE TRIGGER receiver_events_no_delete BEFORE DELETE ON receiver_events
            BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END"""
        )
    with pytest.raises(DeviceMeshReceiverError, match="event chain"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )


@pytest.mark.parametrize("mutation", ("gap", "previous", "hash", "canonical"))
def test_mesh_event_chain_tamper_fails_closed_after_trigger_recreation(
    tmp_path: Path, mutation: str
) -> None:
    path = tmp_path / "mesh.sqlite3"
    _registry(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER mesh_events_no_update")
        connection.execute("DROP TRIGGER mesh_events_no_delete")
        if mutation == "gap":
            connection.execute("DELETE FROM mesh_events WHERE seq=1")
        elif mutation == "previous":
            connection.execute(
                "UPDATE mesh_events SET prev_hash=? WHERE seq=2", ("f" * 64,)
            )
        elif mutation == "hash":
            connection.execute(
                "UPDATE mesh_events SET event_hash=? WHERE seq=1", ("f" * 64,)
            )
        else:
            connection.execute("UPDATE mesh_events SET detail_json='{ }' WHERE seq=1")
        connection.execute(
            """CREATE TRIGGER mesh_events_no_update BEFORE UPDATE ON mesh_events
            BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END"""
        )
        connection.execute(
            """CREATE TRIGGER mesh_events_no_delete BEFORE DELETE ON mesh_events
            BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END"""
        )
    with pytest.raises(DeviceMeshError, match="event chain"):
        DeviceMeshRegistryV1(
            path, DeviceMeshFeatureGateV1(True), ledger_auth_key=MESH_LEDGER_KEY
        )


@pytest.mark.parametrize("truncation", ("maximum", "suffix", "all"))
def test_receiver_ledger_anchor_rejects_every_suffix_truncation(
    tmp_path: Path, truncation: str
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    for _index in range(2):
        request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
        assert receiver.process(request, payload).status == "accepted"
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_events"
        ).fetchone() == (4,)
        connection.execute("DROP TRIGGER receiver_events_no_delete")
        if truncation == "maximum":
            connection.execute(
                "DELETE FROM receiver_events WHERE seq=(SELECT MAX(seq) FROM receiver_events)"
            )
        elif truncation == "suffix":
            connection.execute("DELETE FROM receiver_events WHERE seq>=3")
        else:
            connection.execute("DELETE FROM receiver_events")
        connection.execute(
            """CREATE TRIGGER receiver_events_no_delete BEFORE DELETE ON receiver_events
            BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END"""
        )
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )


@pytest.mark.parametrize("truncation", ("maximum", "suffix", "all"))
def test_mesh_ledger_anchor_rejects_every_suffix_truncation(
    tmp_path: Path, truncation: str
) -> None:
    path = tmp_path / "mesh.sqlite3"
    registry = _registry(path)
    source = _mesh(registry, "device_source")
    request, _payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    registry.reserve(request, "outbound")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM mesh_events").fetchone() == (3,)
        connection.execute("DROP TRIGGER mesh_events_no_delete")
        if truncation == "maximum":
            connection.execute(
                "DELETE FROM mesh_events WHERE seq=(SELECT MAX(seq) FROM mesh_events)"
            )
        elif truncation == "suffix":
            connection.execute("DELETE FROM mesh_events WHERE seq>=2")
        else:
            connection.execute("DELETE FROM mesh_events")
        connection.execute(
            """CREATE TRIGGER mesh_events_no_delete BEFORE DELETE ON mesh_events
            BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END"""
        )
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            path, DeviceMeshFeatureGateV1(True), ledger_auth_key=MESH_LEDGER_KEY
        )


@pytest.mark.parametrize("attack", ("truncate", "projection"))
def test_receiver_hmac_rejects_plain_sha_anchor_recomputation(
    tmp_path: Path, attack: str
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert receiver.process(request, payload).status == "accepted"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("DROP TRIGGER receiver_ledger_head_update_guard")
        if attack == "truncate":
            connection.execute("DROP TRIGGER receiver_events_no_delete")
            connection.execute(
                "DELETE FROM receiver_events WHERE seq=(SELECT MAX(seq) FROM receiver_events)"
            )
            connection.execute(
                """CREATE TRIGGER receiver_events_no_delete BEFORE DELETE ON receiver_events
                BEGIN SELECT RAISE(ABORT,'receiver events are immutable'); END"""
            )
        else:
            connection.execute(
                "UPDATE receiver_intents SET response_json='{}' WHERE request_id=?",
                (request.request_id,),
            )
        count, tail_seq = connection.execute(
            "SELECT COUNT(*),COALESCE(MAX(seq),0) FROM receiver_events"
        ).fetchone()
        tail = connection.execute(
            "SELECT event_hash FROM receiver_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        tail_hash = "0" * 64 if tail is None else str(tail[0])
        projection = DeviceMeshReceiverStoreV1._projection_digest(connection)
        connection.execute(
            "UPDATE receiver_ledger_head SET event_count=?,tail_seq=?,tail_hash=?,"
            "projection_digest=?,anchor_hash=?",
            (
                count,
                tail_seq,
                tail_hash,
                projection,
                _plain_anchor(count, tail_seq, tail_hash, projection),
            ),
        )
        connection.execute(DeviceMeshReceiverStoreV1._LEDGER_DDL[1])
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )


@pytest.mark.parametrize("attack", ("truncate", "projection"))
def test_mesh_hmac_rejects_plain_sha_anchor_recomputation(
    tmp_path: Path, attack: str
) -> None:
    path = tmp_path / "mesh.sqlite3"
    _registry(path)
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("DROP TRIGGER mesh_ledger_head_update_guard")
        if attack == "truncate":
            connection.execute("DROP TRIGGER mesh_events_no_delete")
            connection.execute(
                "DELETE FROM mesh_events WHERE seq=(SELECT MAX(seq) FROM mesh_events)"
            )
            connection.execute(
                """CREATE TRIGGER mesh_events_no_delete BEFORE DELETE ON mesh_events
                BEGIN SELECT RAISE(ABORT,'mesh events are immutable'); END"""
            )
        else:
            connection.execute(
                "UPDATE devices SET enabled=0 WHERE device_id='device_source'"
            )
        count, tail_seq = connection.execute(
            "SELECT COUNT(*),COALESCE(MAX(seq),0) FROM mesh_events"
        ).fetchone()
        tail = connection.execute(
            "SELECT event_hash FROM mesh_events ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        tail_hash = "0" * 64 if tail is None else str(tail[0])
        projection = DeviceMeshRegistryV1._projection_digest(connection)
        connection.execute(
            "UPDATE mesh_ledger_head SET event_count=?,tail_seq=?,tail_hash=?,"
            "projection_digest=?,anchor_hash=?",
            (
                count,
                tail_seq,
                tail_hash,
                projection,
                _plain_anchor(count, tail_seq, tail_hash, projection),
            ),
        )
        connection.execute(DeviceMeshRegistryV1._LEDGER_DDL[1])
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            path, DeviceMeshFeatureGateV1(True), ledger_auth_key=MESH_LEDGER_KEY
        )


def test_post_open_receiver_tamper_cannot_be_blessed_by_next_operation(
    tmp_path: Path,
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    first, first_payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert receiver.process(first, first_payload).status == "accepted"
    with sqlite3.connect(path) as connection:
        head_before = connection.execute(
            "SELECT event_count,tail_seq,tail_hash,projection_digest,anchor_hash "
            "FROM receiver_ledger_head"
        ).fetchone()
        connection.execute(
            "UPDATE receiver_intents SET response_json='{}' WHERE request_id=?",
            (first.request_id,),
        )

    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        receiver.store.receipt(first.request_id)
    second, second_payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        receiver.process(second, second_payload)

    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT event_count,tail_seq,tail_hash,projection_digest,anchor_hash "
                "FROM receiver_ledger_head"
            ).fetchone()
            == head_before
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents WHERE request_id=?",
            (second.request_id,),
        ).fetchone() == (0,)
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )


def test_post_open_mesh_tamper_cannot_be_blessed_by_next_operation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mesh.sqlite3"
    registry = _registry(path)
    with sqlite3.connect(path) as connection:
        head_before = connection.execute(
            "SELECT event_count,tail_seq,tail_hash,projection_digest,anchor_hash "
            "FROM mesh_ledger_head"
        ).fetchone()
        connection.execute(
            "UPDATE devices SET enabled=0 WHERE device_id='device_source'"
        )

    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        registry.device("device_source")
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        registry.enroll(_device("device_third", "onyx.third", "third"))

    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT event_count,tail_seq,tail_hash,projection_digest,anchor_hash "
                "FROM mesh_ledger_head"
            ).fetchone()
            == head_before
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM devices WHERE device_id='device_third'"
        ).fetchone() == (0,)
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            path,
            DeviceMeshFeatureGateV1(True),
            ledger_auth_key=MESH_LEDGER_KEY,
        )


def test_projection_ledgers_grow_beyond_wire_budgets_and_remain_mutable(
    tmp_path: Path,
) -> None:
    source, receiver, _adapter, receiver_path = _receiver(
        tmp_path,
        max_source_requests=500,
    )
    issued: list[str] = []
    for _index in range(205):
        request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
        issued.append(request.request_id)
        source._registry.reserve(request, "outbound")
        source._registry.finish(request.request_id, "succeeded", "growth_verified")
        assert receiver.process(request, payload).status == "accepted"

    mesh_path = tmp_path / "mesh.sqlite3"
    with sqlite3.connect(receiver_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = [
            list(row)
            for row in connection.execute(
                "SELECT * FROM receiver_intents ORDER BY request_id"
            )
        ]
        expected_receiver_digest = hashlib.sha256(
            json.dumps(
                rows,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        assert len(rows) == 205
        assert (
            DeviceMeshReceiverStoreV1._projection_digest(connection)
            == expected_receiver_digest
        )
    with sqlite3.connect(mesh_path) as connection:
        connection.row_factory = sqlite3.Row
        projection = {
            "metadata": [
                list(row)
                for row in connection.execute(
                    "SELECT schema_version FROM metadata ORDER BY schema_version"
                )
            ],
            "devices": [
                list(row)
                for row in connection.execute(
                    "SELECT * FROM devices ORDER BY device_id"
                )
            ],
            "mesh_requests": [
                list(row)
                for row in connection.execute(
                    "SELECT * FROM mesh_requests ORDER BY request_id"
                )
            ],
        }
        expected_mesh_digest = hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        assert len(projection["mesh_requests"]) == 205
        assert (
            DeviceMeshRegistryV1._projection_digest(connection) == expected_mesh_digest
        )

    reopened_store = DeviceMeshReceiverStoreV1(
        receiver_path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
    )
    reopened_mesh = DeviceMeshRegistryV1(
        mesh_path,
        DeviceMeshFeatureGateV1(True),
        ledger_auth_key=MESH_LEDGER_KEY,
    )
    assert reopened_store.receipt(issued[-1]).status == "accepted"
    reopened_mesh.enroll(_device("device_third", "onyx.third", "third"))

    target = _mesh(reopened_mesh, "device_target")
    reopened_receiver = DeviceMeshReceiverV1(
        mesh=target,
        store=reopened_store,
        authority=lambda *_args: True,
        outbound_dispatch_lookup=_outbound_lookup,
        max_source_requests=500,
    )
    final_request, final_payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert reopened_receiver.process(final_request, final_payload).status == "accepted"

    DeviceMeshReceiverStoreV1(
        receiver_path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
    )
    DeviceMeshRegistryV1(
        mesh_path,
        DeviceMeshFeatureGateV1(True),
        ledger_auth_key=MESH_LEDGER_KEY,
    )


def test_receiver_anchor_and_projection_tamper_fail_closed(tmp_path: Path) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert receiver.process(request, payload).status == "accepted"
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER receiver_ledger_head_update_guard")
        connection.execute("UPDATE receiver_ledger_head SET anchor_hash=?", ("f" * 64,))
        connection.execute(
            """CREATE TRIGGER receiver_ledger_head_update_guard
            BEFORE UPDATE ON receiver_ledger_head
            WHEN NOT (
              OLD.singleton=1 AND NEW.singleton=1 AND
              NEW.event_count=OLD.event_count+1 AND
              NEW.tail_seq=OLD.tail_seq+1 AND
              NEW.event_count=(SELECT COUNT(*) FROM receiver_events) AND
              NEW.tail_seq=COALESCE((SELECT MAX(seq) FROM receiver_events),0) AND
              NEW.tail_hash=COALESCE((SELECT event_hash FROM receiver_events ORDER BY seq DESC LIMIT 1),printf('%064d',0))
            )
            BEGIN SELECT RAISE(ABORT,'receiver ledger head transition is invalid'); END"""
        )
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )

    projection_path = tmp_path / "receiver-projection.sqlite3"
    projection_store = DeviceMeshReceiverStoreV1(
        projection_path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
    )
    projection_receiver = DeviceMeshReceiverV1(
        mesh=receiver._mesh,
        store=projection_store,
        authority=lambda *_args: True,
    )
    another, another_payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    assert projection_receiver.process(another, another_payload).status == "accepted"
    with sqlite3.connect(projection_path) as connection:
        connection.execute(
            "UPDATE receiver_intents SET response_json='{}' WHERE request_id=?",
            (another.request_id,),
        )
    with pytest.raises(DeviceMeshReceiverError, match="ledger anchor"):
        DeviceMeshReceiverStoreV1(
            projection_path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )


def test_mesh_anchor_and_projection_tamper_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "mesh.sqlite3"
    _registry(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TRIGGER mesh_ledger_head_update_guard")
        connection.execute("UPDATE mesh_ledger_head SET anchor_hash=?", ("f" * 64,))
        connection.execute(
            """CREATE TRIGGER mesh_ledger_head_update_guard
            BEFORE UPDATE ON mesh_ledger_head
            WHEN NOT (
              OLD.singleton=1 AND NEW.singleton=1 AND
              NEW.event_count=OLD.event_count+1 AND
              NEW.tail_seq=OLD.tail_seq+1 AND
              NEW.event_count=(SELECT COUNT(*) FROM mesh_events) AND
              NEW.tail_seq=COALESCE((SELECT MAX(seq) FROM mesh_events),0) AND
              NEW.tail_hash=COALESCE((SELECT event_hash FROM mesh_events ORDER BY seq DESC LIMIT 1),printf('%064d',0))
            )
            BEGIN SELECT RAISE(ABORT,'mesh ledger head transition is invalid'); END"""
        )
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            path, DeviceMeshFeatureGateV1(True), ledger_auth_key=MESH_LEDGER_KEY
        )

    projection_path = tmp_path / "mesh-projection.sqlite3"
    _registry(projection_path)
    with sqlite3.connect(projection_path) as connection:
        connection.execute(
            "UPDATE devices SET enabled=0 WHERE device_id='device_source'"
        )
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            projection_path,
            DeviceMeshFeatureGateV1(True),
            ledger_auth_key=MESH_LEDGER_KEY,
        )


def test_exact_legacy_schemas_gain_empty_ledger_anchors_atomically(
    tmp_path: Path,
) -> None:
    receiver_path = tmp_path / "legacy-receiver.sqlite3"
    with sqlite3.connect(receiver_path) as connection:
        for statement in DeviceMeshReceiverStoreV1._LEGACY_DDL:
            connection.execute(statement)
        connection.execute("PRAGMA user_version=1")
    with pytest.raises(
        DeviceMeshReceiverDenied, match="explicit trusted initialization"
    ):
        DeviceMeshReceiverStoreV1(
            receiver_path,
            DeviceMeshReceiverFeatureGateV1(True),
            ledger_auth_key=RECEIVER_LEDGER_KEY,
        )
    DeviceMeshReceiverStoreV1(
        receiver_path,
        DeviceMeshReceiverFeatureGateV1(True),
        ledger_auth_key=RECEIVER_LEDGER_KEY,
        trust_legacy_ledger=True,
    )
    with sqlite3.connect(receiver_path) as connection:
        assert connection.execute(
            "SELECT event_count,tail_seq,tail_hash FROM receiver_ledger_head"
        ).fetchone() == (0, 0, "0" * 64)
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute(
                "UPDATE receiver_ledger_head SET anchor_hash=?", ("f" * 64,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM receiver_ledger_head")

    mesh_path = tmp_path / "legacy-mesh.sqlite3"
    with sqlite3.connect(mesh_path) as connection:
        for statement in DeviceMeshRegistryV1._LEGACY_DDL:
            connection.execute(statement)
        connection.execute("INSERT INTO metadata(schema_version) VALUES(1)")
        connection.execute("PRAGMA user_version=1")
    with pytest.raises(DeviceMeshDenied, match="explicit trusted initialization"):
        DeviceMeshRegistryV1(
            mesh_path,
            DeviceMeshFeatureGateV1(True),
            ledger_auth_key=MESH_LEDGER_KEY,
        )
    DeviceMeshRegistryV1(
        mesh_path,
        DeviceMeshFeatureGateV1(True),
        ledger_auth_key=MESH_LEDGER_KEY,
        trust_legacy_ledger=True,
    )
    with sqlite3.connect(mesh_path) as connection:
        assert connection.execute(
            "SELECT event_count,tail_seq,tail_hash FROM mesh_ledger_head"
        ).fetchone() == (0, 0, "0" * 64)
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute("UPDATE mesh_ledger_head SET anchor_hash=?", ("f" * 64,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("DELETE FROM mesh_ledger_head")


def test_pairing_claim_contract_cannot_be_used_as_receiver_authority(
    tmp_path: Path,
) -> None:
    source, _receiver_value, adapter, _path = _receiver(
        tmp_path, authority=lambda *_args: False
    )
    request, payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)
    with TestClient(adapter, base_url="https://receiver.test") as client:
        response = _post(client, "/onyx/mesh/v1/health", request, payload)
    assert response.status_code == 403
    assert response.json()["result"] == {"reason": "central_authority_denied"}


def test_store_transaction_rolls_back_if_event_append_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, _payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)

    def fail_event(*_args, **_kwargs) -> None:
        raise sqlite3.OperationalError("simulated event failure")

    monkeypatch.setattr(receiver.store, "_event", fail_event)
    with pytest.raises(sqlite3.OperationalError):
        receiver.store.reserve(request)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (0,)


def test_reserve_rolls_back_intent_and_event_if_ledger_advance_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, receiver, _adapter, path = _receiver(tmp_path)
    request, _payload = _issue(source, CAPABILITY_HEALTH, RECEIVER_RESOURCE)

    def fail_advance(*_args, **_kwargs) -> None:
        raise sqlite3.OperationalError("simulated ledger head failure")

    monkeypatch.setattr(receiver.store, "_advance_ledger_head", fail_advance)
    with pytest.raises(sqlite3.OperationalError, match="ledger head failure"):
        receiver.store.reserve(request)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_intents"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM receiver_events"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT event_count,tail_seq FROM receiver_ledger_head"
        ).fetchone() == (0, 0)
