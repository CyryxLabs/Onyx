from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.device_mesh_v1 import (
    AuthenticatedDeviceMeshV1,
    DeviceMeshDenied,
    DeviceMeshError,
    DeviceMeshFeatureGateV1,
    DeviceMeshRegistryV1,
    DeviceMeshReplay,
    EnrolledDeviceV1,
)
from core.native_vault import SecretReference


OWNER = "owner_primary"
WORKSPACE = "workspace_primary"
SOURCE_SECRET = b"source-device-secret-material-32bytes"
TARGET_SECRET = b"target-device-secret-material-32bytes"
LEDGER_KEY = b"m" * 32


def _device(device_id: str, issuer: str, account: str) -> EnrolledDeviceV1:
    return EnrolledDeviceV1(
        device_id,
        OWNER,
        WORKSPACE,
        issuer,
        SecretReference("Onyx.DeviceMesh.v1", account, f"Onyx device {device_id}"),
        True,
    )


def _registry(path: Path) -> DeviceMeshRegistryV1:
    registry = DeviceMeshRegistryV1(
        path, DeviceMeshFeatureGateV1(True), ledger_auth_key=LEDGER_KEY
    )
    registry.enroll(_device("device_source", "onyx.source", "source"))
    registry.enroll(_device("device_target", "onyx.target", "target"))
    return registry


def _vault(reference: SecretReference) -> bytes | None:
    return {"source": SOURCE_SECRET, "target": TARGET_SECRET}.get(reference.account)


def _runtime(
    registry: DeviceMeshRegistryV1,
    device_id: str,
    *,
    now: float = 1_000.0,
    allowed: bool = True,
) -> AuthenticatedDeviceMeshV1:
    return AuthenticatedDeviceMeshV1(
        local_device_id=device_id,
        registry=registry,
        vault_reader=_vault,
        authority=lambda owner, workspace, capability, resource, source: allowed,
        clock=lambda: now,
    )


def test_feature_is_default_off_and_idle_runtime_has_no_workers(tmp_path: Path) -> None:
    assert DeviceMeshFeatureGateV1.from_environ({}).enabled is False
    with pytest.raises(DeviceMeshDenied, match="disabled"):
        DeviceMeshRegistryV1(tmp_path / "off.sqlite3", DeviceMeshFeatureGateV1(False))
    runtime = _runtime(_registry(tmp_path / "mesh.sqlite3"), "device_source")
    assert runtime.background_workers == 0
    assert runtime.polling_interval is None


def test_enabled_registry_requires_exact_external_ledger_key(tmp_path: Path) -> None:
    for invalid in (None, b"short", b"x" * 33):
        with pytest.raises(DeviceMeshDenied, match="authentication key"):
            DeviceMeshRegistryV1(
                tmp_path / f"invalid-{len(invalid or b'')}.sqlite3",
                DeviceMeshFeatureGateV1(True),
                ledger_auth_key=invalid,
            )


def test_registry_reopen_with_wrong_external_key_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "mesh.sqlite3"
    _registry(path)
    with pytest.raises(DeviceMeshError, match="ledger anchor"):
        DeviceMeshRegistryV1(
            path,
            DeviceMeshFeatureGateV1(True),
            ledger_auth_key=b"w" * 32,
        )


def test_scope_count_never_returns_vault_references(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "mesh.sqlite3")
    assert registry.count_scope(OWNER, WORKSPACE) == 2
    assert registry.count_scope("owner_other", WORKSPACE) == 0


def test_registry_enables_and_disables_enrolled_device(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "mesh.sqlite3")
    disabled = registry.set_enabled("device_source", False)
    assert disabled.enabled is False
    assert registry.device("device_source").enabled is False
    enabled = registry.set_enabled("device_source", True)
    assert enabled.enabled is True


def test_signed_request_is_bound_to_issuer_audience_device_scope_and_payload(
    tmp_path: Path,
) -> None:
    source = _runtime(_registry(tmp_path / "source.sqlite3"), "device_source")
    target = _runtime(_registry(tmp_path / "target.sqlite3"), "device_target")
    request, payload = source.issue(
        target_device_id="device_target",
        capability="read.calendar",
        resource="calendar_primary",
        payload=b'{"range":"today"}',
    )
    calls: list[bytes] = []
    result = target.receive(request, payload, lambda _request, raw: calls.append(raw))
    assert result.status == "succeeded"
    assert calls == [payload]

    wrong_target = _runtime(_registry(tmp_path / "wrong.sqlite3"), "device_source")
    with pytest.raises(DeviceMeshDenied, match="audience device"):
        wrong_target.receive(request, payload, lambda *_args: None)


def test_expiry_payload_tampering_and_missing_vault_secret_fail_closed(
    tmp_path: Path,
) -> None:
    source_registry = _registry(tmp_path / "source.sqlite3")
    request, payload = _runtime(source_registry, "device_source", now=1_000.0).issue(
        target_device_id="device_target",
        capability="read.mail",
        resource="mail_primary",
        payload=b"metadata-only",
        ttl_seconds=30,
    )
    expired = _runtime(
        _registry(tmp_path / "expired.sqlite3"), "device_target", now=1_031.0
    )
    with pytest.raises(DeviceMeshDenied, match="validity window"):
        expired.receive(request, payload, lambda *_args: None)

    target = _runtime(
        _registry(tmp_path / "tampered.sqlite3"), "device_target", now=1_001.0
    )
    with pytest.raises(DeviceMeshDenied, match="payload digest"):
        target.receive(request, b"changed", lambda *_args: None)

    no_vault = AuthenticatedDeviceMeshV1(
        local_device_id="device_target",
        registry=_registry(tmp_path / "novault.sqlite3"),
        vault_reader=lambda _reference: None,
        authority=lambda *_args: True,
        clock=lambda: 1_001.0,
    )
    with pytest.raises(DeviceMeshDenied, match="credential"):
        no_vault.receive(request, payload, lambda *_args: None)


def test_nonce_and_request_replay_are_rejected_before_handler(tmp_path: Path) -> None:
    source = _runtime(_registry(tmp_path / "source.sqlite3"), "device_source")
    target = _runtime(_registry(tmp_path / "target.sqlite3"), "device_target")
    request, payload = source.issue(
        target_device_id="device_target",
        capability="read.calendar",
        resource="calendar_primary",
        payload=b"request",
    )
    calls: list[str] = []
    target.receive(request, payload, lambda *_args: calls.append("first"))
    with pytest.raises(DeviceMeshReplay):
        target.receive(request, payload, lambda *_args: calls.append("replay"))
    assert calls == ["first"]


def test_central_authority_denial_prevents_handler(tmp_path: Path) -> None:
    source = _runtime(_registry(tmp_path / "source.sqlite3"), "device_source")
    target = _runtime(
        _registry(tmp_path / "target.sqlite3"), "device_target", allowed=False
    )
    request, payload = source.issue(
        target_device_id="device_target",
        capability="write.file",
        resource="workspace_document",
        payload=b"operation",
    )
    called = False

    def handler(*_args) -> None:
        nonlocal called
        called = True

    result = target.receive(request, payload, handler)
    assert result.status == "denied"
    assert called is False


def test_outbound_is_durable_before_transport_and_failure_never_auto_retries(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "mesh.sqlite3")
    source = _runtime(registry, "device_source")
    request, payload = source.issue(
        target_device_id="device_target",
        capability="read.calendar",
        resource="calendar_primary",
        payload=b"operation",
    )
    observations: list[str] = []

    class FailingTransport:
        def send(self, sent_request, sent_payload) -> str:
            observations.append(registry.dispatch(sent_request.request_id).status)
            assert sent_payload == payload
            raise OSError("network result is unknown")

    with pytest.raises(OSError, match="unknown"):
        source.send(request, payload, FailingTransport())
    assert observations == ["sending"]
    assert registry.dispatch(request.request_id).status == "reconciliation"
    assert registry.recover_uncertain() == 0


def test_restart_moves_unsent_or_sending_requests_to_reconciliation(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path / "mesh.sqlite3")
    source = _runtime(registry, "device_source")
    request, _payload_value = source.issue(
        target_device_id="device_target",
        capability="read.calendar",
        resource="calendar_primary",
        payload=b"operation",
    )
    registry.reserve(request, "outbound")
    assert registry.recover_uncertain() == 1
    assert registry.dispatch(request.request_id).status == "reconciliation"


def test_database_contains_references_and_digests_but_never_secret_or_payload(
    tmp_path: Path,
) -> None:
    path = tmp_path / "mesh.sqlite3"
    registry = _registry(path)
    source = _runtime(registry, "device_source")
    request, payload = source.issue(
        target_device_id="device_target",
        capability="read.calendar",
        resource="calendar_primary",
        payload=b"uniquely-sensitive-payload-not-for-storage",
    )
    registry.reserve(request, "outbound")
    raw_database = path.read_bytes()
    assert SOURCE_SECRET not in raw_database
    assert TARGET_SECRET not in raw_database
    assert payload not in raw_database
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT vault_account FROM devices WHERE device_id='device_source'"
        ).fetchone() == ("source",)
        assert connection.execute(
            "SELECT payload_digest FROM mesh_requests WHERE request_id=?",
            (request.request_id,),
        ).fetchone() == (request.payload_digest,)
