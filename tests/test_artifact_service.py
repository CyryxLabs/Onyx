from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import gc
import hashlib
import inspect
import io
import multiprocessing
import os
from pathlib import Path
import sys
import threading
import time
import weakref

import pytest

from core import artifact_service as artifacts


def _root(
    tmp_path: Path, *, workspace_id: str = "workspace-alpha",
) -> tuple[Path, artifacts.ArtifactRootCapability]:
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    capability = artifacts._authorize_root_for_testing(
        root, allowlisted_roots=(root,), workspace_id=workspace_id,
    )
    return root, capability


def _service(
    tmp_path: Path, *, workspace_id: str = "workspace-alpha",
    enabled: bool = True, max_bytes: int = 4096,
) -> tuple[Path, artifacts.ArtifactService]:
    root, capability = _root(tmp_path, workspace_id=workspace_id)
    return root, artifacts.ArtifactService(
        capability, workspace_id=workspace_id, enabled=enabled,
        max_bytes=max_bytes,
    )


def _publish(service: artifacts.ArtifactService, data: bytes = b"onyx") -> artifacts.ArtifactRecord:
    return service.publish_bytes(
        data,
        media_type="application/octet-stream",
        data_class="internal",
        source_provenance={"kind": "unit-test", "source": "local"},
        display_name="result.bin",
    )


def _multiprocess_publish_worker(
    root_value: str, payload: bytes, start, results,
) -> None:
    try:
        root = Path(root_value)
        capability = artifacts._authorize_root_for_testing(
            root, allowlisted_roots=(root,), workspace_id="workspace-alpha"
        )
        service = artifacts.ArtifactService(
            capability, workspace_id="workspace-alpha", enabled=True,
            max_bytes=4096,
        )
        if not start.wait(10):
            raise RuntimeError("multiprocess start gate timed out")
        record = _publish(service, payload)
        results.put(("ok", record.sha256))
    except BaseException as exc:
        results.put(("error", f"{type(exc).__name__}: {exc}"))


def _assert_bounded_failure_quarantine(root: Path, *, max_bytes: int) -> None:
    del max_bytes
    retained = list(root.rglob(".onyx-artifact-*.tmp"))
    # Stream ingestion now occurs in an anonymous bounded spool.  Validation,
    # source failures and CAS replays never allocate the publication slot.
    assert retained == []


def _linux_otmpfile_supported(root: Path) -> bool:
    if not sys.platform.startswith("linux") or not hasattr(os, "O_TMPFILE"):
        return False
    try:
        descriptor = os.open(root, os.O_RDWR | os.O_TMPFILE, 0o600)
    except OSError:
        return False
    os.close(descriptor)
    return True


def test_default_off_performs_no_write(tmp_path: Path) -> None:
    root, service = _service(tmp_path, enabled=False)
    before = list(root.iterdir())
    with pytest.raises(artifacts.ArtifactDisabled):
        _publish(service)
    assert list(root.iterdir()) == before == []


def test_publish_lookup_read_and_manifest_are_canonical(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    payload = b"content-addressed Onyx artifact"
    record = _publish(service, payload)
    digest = hashlib.sha256(payload).hexdigest()

    assert record.schema_version == 1
    assert record.sha256 == digest
    assert record.relative_path == f"{digest[:2]}/{digest}"
    assert record.workspace_id == "workspace-alpha"
    assert record.status == "available"
    assert record.data_class == "internal"
    assert record.size == len(payload)
    assert (root / digest[:2] / digest).read_bytes() == payload
    assert service.lookup(record) is record
    assert service.read(record) == payload
    with service.open(record) as handle:
        assert handle.read() == payload
    manifest = record.canonical_manifest()
    assert payload not in manifest
    assert artifacts.ArtifactRecord.from_manifest(manifest) == record
    assert record.manifest_sha256 == hashlib.sha256(manifest).hexdigest()


def test_recover_indexed_record_uses_pinned_cas_and_exact_index_metadata(
    tmp_path: Path,
) -> None:
    _root_path, service = _service(tmp_path)
    published = _publish(service, b"indexed document")
    recovered = service.recover_indexed_record(
        artifact_id=published.artifact_id,
        sha256=published.sha256,
        relative_path=published.relative_path,
        media_type=published.media_type,
        created_at=published.created_at,
    )
    assert recovered.artifact_id == published.artifact_id
    assert recovered.sha256 == published.sha256
    assert recovered.size == published.size
    assert service.read(recovered) == b"indexed document"


@pytest.mark.parametrize("digest", ["../escape", "g" * 64, "a" * 63, ""])
def test_recover_indexed_record_rejects_noncanonical_digest_before_open(
    tmp_path: Path, digest: str,
) -> None:
    _root_path, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError, match="identity is invalid"):
        service.recover_indexed_record(
            artifact_id="artifact-invalid",
            sha256=digest,
            relative_path=f"{digest[:2]}/{digest}",
            media_type="text/plain",
            created_at="2026-07-31T00:00:00.000000Z",
        )


def test_recover_indexed_record_enforces_service_size_before_hash(
    tmp_path: Path,
) -> None:
    _root_path, publisher = _service(tmp_path, max_bytes=4096)
    record = _publish(publisher, b"x" * 128)
    # A separately-authorized reader with a tighter envelope must refuse the
    # indexed object before attempting a full hash/read.
    root = _root_path
    capability = artifacts._authorize_root_for_testing(
        root, allowlisted_roots=(root,), workspace_id="workspace-alpha"
    )
    reader = artifacts.ArtifactService(
        capability,
        workspace_id="workspace-alpha",
        enabled=True,
        max_bytes=64,
    )
    try:
        with pytest.raises(artifacts.ArtifactTooLarge, match="indexed artifact"):
            reader.recover_indexed_record(
                artifact_id=record.artifact_id,
                sha256=record.sha256,
                relative_path=record.relative_path,
                media_type=record.media_type,
                created_at=record.created_at,
            )
    finally:
        reader.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_owns_and_releases_trusted_boundary(
    tmp_path: Path,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )
    service = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True
    )
    record = _publish(service, b"host-bound")
    assert service.read(record) == b"host-bound"
    service.close()
    assert boundary._closed is True
    with pytest.raises(artifacts.ArtifactIntegrityError):
        service.read(record)


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_propagates_boundary_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )

    def fail_close(_self) -> None:
        raise RuntimeError("injected boundary close failure")

    monkeypatch.setattr(WindowsTrustedDirectoryV1, "close", fail_close)
    with pytest.raises(
        artifacts.ArtifactIntegrityError, match="host boundary close failed"
    ):
        capability.close()
    assert capability._host_boundary is boundary
    with artifacts._CAPABILITIES_LOCK:
        assert capability not in artifacts._CAPABILITIES
    assert capability._finalizer is not None
    assert capability._finalizer.alive is True
    monkeypatch.undo()
    capability.close()
    assert capability._host_boundary is None
    assert capability._finalizer.alive is False
    assert boundary._closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_serializes_boundary_close_across_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )
    entered = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []
    calls = 0
    original_close = WindowsTrustedDirectoryV1.close

    def blocking_close(self) -> None:
        nonlocal calls
        if self is boundary:
            calls += 1
            entered.set()
            assert release.wait(5)
        original_close(self)

    def close_capability() -> None:
        try:
            capability.close()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(WindowsTrustedDirectoryV1, "close", blocking_close)
    first = threading.Thread(target=close_capability)
    second = threading.Thread(target=close_capability)
    first.start()
    assert entered.wait(5)
    second.start()
    time.sleep(0.05)
    assert calls == 1
    release.set()
    first.join(5)
    second.join(5)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert calls == 1
    assert capability._host_boundary is None
    assert boundary._closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_preserves_every_owner_for_os_close_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )
    with artifacts._CAPABILITIES_LOCK:
        state = artifacts._CAPABILITIES[capability]
    assert state.pinned._windows is not None
    assert state.pinned._root_handle is not None
    original_close = artifacts._WindowsAPI.close
    expected_api = state.pinned._windows
    expected_handle = state.pinned._root_handle
    attempts = 0

    def fail_first_os_close(self, handle: int) -> None:
        nonlocal attempts
        if self is expected_api and handle == expected_handle:
            attempts += 1
            if attempts == 1:
                raise RuntimeError("injected Windows handle close failure")
        original_close(self, handle)

    monkeypatch.setattr(artifacts._WindowsAPI, "close", fail_first_os_close)
    with pytest.raises(RuntimeError, match="injected Windows handle close failure"):
        capability.close()
    with artifacts._CAPABILITIES_LOCK:
        assert artifacts._CAPABILITIES.get(capability) is state
    assert state._closing is False
    assert state._closed is False
    assert state.pinned._closed is False
    assert state.pinned._root_handle == expected_handle
    assert capability._host_boundary is boundary
    assert capability._finalizer is not None
    assert capability._finalizer.alive is True
    assert boundary._closed is False

    capability.close()
    assert attempts == 2
    with artifacts._CAPABILITIES_LOCK:
        assert capability not in artifacts._CAPABILITIES
    assert capability._host_boundary is None
    assert capability._finalizer.alive is False
    assert boundary._closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_gc_finalizer_releases_state_then_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )
    with artifacts._CAPABILITIES_LOCK:
        state = artifacts._CAPABILITIES[capability]
    events: list[str] = []
    original_state_close = artifacts._CapabilityState.close
    original_boundary_close = WindowsTrustedDirectoryV1.close

    def record_state_close(self) -> None:
        if self is state:
            events.append("state")
        original_state_close(self)

    def record_boundary_close(self) -> None:
        if self is boundary:
            events.append("boundary")
        original_boundary_close(self)

    monkeypatch.setattr(artifacts._CapabilityState, "close", record_state_close)
    monkeypatch.setattr(WindowsTrustedDirectoryV1, "close", record_boundary_close)
    capability_ref = weakref.ref(capability)
    del capability
    gc.collect()

    assert capability_ref() is None
    assert events == ["state", "boundary"]
    assert state._closed is True
    assert boundary._closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_finalizer_keeps_boundary_if_state_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    capability = artifacts.authorize_host_root_v1(
        boundary, workspace_id="workspace-alpha"
    )
    with artifacts._CAPABILITIES_LOCK:
        state = artifacts._CAPABILITIES[capability]
    original_state_close = artifacts._CapabilityState.close
    boundary_close_calls = 0
    original_boundary_close = WindowsTrustedDirectoryV1.close

    def fail_state_close(self) -> None:
        if self is state:
            raise RuntimeError("injected finalizer state close failure")
        original_state_close(self)

    def record_boundary_close(self) -> None:
        nonlocal boundary_close_calls
        if self is boundary:
            boundary_close_calls += 1
        original_boundary_close(self)

    monkeypatch.setattr(artifacts._CapabilityState, "close", fail_state_close)
    monkeypatch.setattr(WindowsTrustedDirectoryV1, "close", record_boundary_close)
    assert capability._finalizer is not None
    with pytest.raises(RuntimeError, match="finalizer state close failure"):
        capability._finalizer()
    assert boundary_close_calls == 0
    assert boundary._closed is False
    assert capability._host_boundary is boundary

    monkeypatch.setattr(artifacts._CapabilityState, "close", original_state_close)
    capability.close()
    assert boundary_close_calls == 1
    assert boundary._closed is True


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted boundary required")
def test_public_host_authority_rejects_trusted_identity_drift(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

    root = tmp_path / "host-artifacts"
    root.mkdir()
    boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
    assert boundary.root_identity is not None
    boundary.root_identity = replace(
        boundary.root_identity,
        resolved_path=str(tmp_path / "different"),
    )
    try:
        with pytest.raises(Exception, match="identity"):
            artifacts.authorize_host_root_v1(
                boundary, workspace_id="workspace-alpha"
            )
    finally:
        try:
            boundary.close()
        except Exception:
            # The intentionally drifted attestation makes normal close refuse;
            # release the held handles explicitly in this isolated test.
            if boundary.root is not None:
                boundary.root.close()
            if boundary.parent is not None:
                boundary.parent.close()


def test_publish_is_idempotent_and_never_overwrites(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    first = _publish(service, b"same")
    second = _publish(service, b"same")
    assert second == first
    files = [item for item in root.rglob("*") if item.is_file()]
    assert files == [root / first.relative_path]
    assert files[0].read_bytes() == b"same"


def test_same_bytes_with_changed_metadata_conflicts(tmp_path: Path) -> None:
    _root_path, service = _service(tmp_path)
    _publish(service, b"same")
    with pytest.raises(artifacts.ArtifactContractError, match="changed artifact metadata"):
        service.publish_bytes(
            b"same", media_type="text/plain", data_class="public",
            source_provenance="different-source", display_name="different.txt",
        )


def test_record_cache_is_bounded_and_eviction_does_not_break_durable_lookup(
    tmp_path: Path,
) -> None:
    _root_path, service = _service(tmp_path, max_bytes=4096)
    records = [
        _publish(service, f"bounded-cache-{index}".encode("ascii"))
        for index in range(artifacts._MAX_RECORD_CACHE + 32)
    ]
    assert len(service._records) == artifacts._MAX_RECORD_CACHE
    assert records[0].sha256 not in service._records
    assert service.lookup(records[0]) == records[0]
    assert service.read(records[0]) == b"bounded-cache-0"


def test_size_bound_is_incremental_and_temp_is_cleaned(tmp_path: Path) -> None:
    root, service = _service(tmp_path, max_bytes=5)
    with pytest.raises(artifacts.ArtifactTooLarge):
        service.publish_stream(
            io.BytesIO(b"123456"), media_type="text/plain",
            data_class="internal", source_provenance="bounded-test",
        )
    _assert_bounded_failure_quarantine(root, max_bytes=5)


class _FailingStream:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, _size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"partial"
        raise OSError("injected source failure")


def test_stream_failure_does_not_leave_temp(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactIOError):
        service.publish_stream(
            _FailingStream(), media_type="text/plain", data_class="internal",
            source_provenance="failure-test",
        )
    _assert_bounded_failure_quarantine(root, max_bytes=4096)


@pytest.mark.parametrize("name", ["../secret", "folder/name", r"folder\name", ".", ".."])
def test_display_name_is_metadata_only_and_rejects_traversal(
    tmp_path: Path, name: str,
) -> None:
    _root_path, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError):
        service.publish_bytes(
            b"x", media_type="text/plain", data_class="public",
            source_provenance="name-test", display_name=name,
        )


@pytest.mark.parametrize("classification", ["restricted", "PRIVATE", ""])
def test_restricted_or_unknown_data_class_is_rejected(
    tmp_path: Path, classification: str,
) -> None:
    root, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError):
        service.publish_bytes(
            b"x", media_type="text/plain", data_class=classification,
            source_provenance="classification-test",
        )
    assert not [item for item in root.rglob("*") if item.is_file()]


@pytest.mark.parametrize(
    "provenance",
    [
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789",
        {"api_key": "not-even-needed"},
        {"source": "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"},
    ],
)
def test_secret_source_metadata_is_rejected(tmp_path: Path, provenance: object) -> None:
    root, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError):
        service.publish_bytes(
            b"x", media_type="text/plain", data_class="internal",
            source_provenance=provenance,  # type: ignore[arg-type]
        )
    assert not [item for item in root.rglob("*") if item.is_file()]


def test_secret_display_name_is_rejected(tmp_path: Path) -> None:
    _root_path, service = _service(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError):
        service.publish_bytes(
            b"x", media_type="text/plain", data_class="internal",
            source_provenance="display-test",
            display_name="api_key=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.txt",
        )


def test_record_rejects_external_noncanonical_digest_path_and_id(tmp_path: Path) -> None:
    _root_path, service = _service(tmp_path)
    record = _publish(service)
    bad_digest = "A" * 64
    for changed in (
        replace(record, sha256=bad_digest),
        replace(record, relative_path=f"../{record.sha256}"),
        replace(record, relative_path=record.relative_path.replace("/", "\\")),
        replace(record, artifact_id="artifact-user-supplied"),
    ):
        with pytest.raises(artifacts.ArtifactContractError):
            service.lookup(changed)


def test_public_publish_api_has_no_destination_path_or_digest_parameter() -> None:
    for method in (
        artifacts.ArtifactService.publish_bytes,
        artifacts.ArtifactService.publish_stream,
    ):
        names = set(inspect.signature(method).parameters)
        assert "path" not in names
        assert "digest" not in names
        assert "sha256" not in names


def test_workspace_scope_is_explicit_and_cross_workspace_leaks_nothing(tmp_path: Path) -> None:
    root, capability = _root(tmp_path)
    alpha = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    with pytest.raises(artifacts.ArtifactIsolationError, match="another workspace"):
        artifacts.ArtifactService(
            capability, workspace_id="workspace-beta", enabled=True, max_bytes=4096,
        )
    record = _publish(alpha, b"alpha-only")
    beta_root = tmp_path / "artifacts-beta"
    beta_root.mkdir(mode=0o700)
    if os.name != "nt":
        beta_root.chmod(0o700)
    beta_capability = artifacts._authorize_root_for_testing(
        beta_root, allowlisted_roots=(beta_root,), workspace_id="workspace-beta",
    )
    beta = artifacts.ArtifactService(
        beta_capability, workspace_id="workspace-beta", enabled=True, max_bytes=4096,
    )
    with pytest.raises(artifacts.ArtifactIsolationError):
        beta.lookup(record)
    with pytest.raises(artifacts.ArtifactIsolationError):
        beta.read(record)
    assert (root / record.relative_path).read_bytes() == b"alpha-only"


@pytest.mark.parametrize("workspace_id", ["all", "all-workspaces", "legacy-default", "*"])
def test_legacy_or_all_workspace_modes_do_not_exist(
    tmp_path: Path, workspace_id: str,
) -> None:
    _root_path, capability = _root(tmp_path)
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts.ArtifactService(
            capability, workspace_id=workspace_id, enabled=True,
        )


def test_root_must_exist_be_private_and_be_exactly_allowlisted(tmp_path: Path) -> None:
    root = tmp_path / "root"
    with pytest.raises(artifacts.ArtifactIsolationError):
        artifacts._authorize_root_for_testing(root, allowlisted_roots=(tmp_path,))
    with pytest.raises(artifacts.ArtifactIntegrityError):
        artifacts._authorize_root_for_testing(root, allowlisted_roots=(root,))
    root.mkdir()
    if os.name != "nt":
        root.chmod(0o755)
        with pytest.raises(artifacts.ArtifactIsolationError):
            artifacts._authorize_root_for_testing(root, allowlisted_roots=(root,))


def test_capability_is_opaque_noncopyable_and_nonserializable(tmp_path: Path) -> None:
    import copy
    import pickle

    _root_path, capability = _root(tmp_path)
    with pytest.raises(TypeError):
        artifacts.ArtifactRootCapability(object())
    with pytest.raises(TypeError):
        copy.copy(capability)
    with pytest.raises(TypeError):
        pickle.dumps(capability)
    capability.close()
    with pytest.raises(artifacts.ArtifactIntegrityError, match="closed"):
        artifacts.ArtifactService(
            capability, workspace_id="workspace-alpha", enabled=True,
        )


def test_concurrent_publishers_converge_on_one_file_and_record(tmp_path: Path) -> None:
    root, capability = _root(tmp_path)
    services = [
        artifacts.ArtifactService(
            capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
        )
        for _ in range(8)
    ]
    payload = b"concurrent-content"
    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(lambda service: _publish(service, payload), services))
    assert records == [records[0]] * 8
    files = [item for item in root.rglob("*") if item.is_file()]
    assert files == [root / records[0].relative_path]
    assert files[0].read_bytes() == payload
    _assert_bounded_failure_quarantine(root, max_bytes=16)


@pytest.mark.skipif(os.name == "nt", reason="POSIX inter-process flock required")
def test_posix_multiprocess_publishers_converge_without_temp_poisoning(
    tmp_path: Path,
) -> None:
    root, _capability = _root(tmp_path)
    payload = b"multiprocess-content"
    digest = hashlib.sha256(payload).hexdigest()
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_multiprocess_publish_worker,
            args=(str(root), payload, start, results),
        )
        for _ in range(6)
    ]
    for worker in workers:
        worker.start()
    start.set()
    observed = [results.get(timeout=20) for _ in workers]
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0
    assert observed == [("ok", digest)] * len(workers)
    assert (root / digest[:2] / digest).read_bytes() == payload
    assert not list(root.glob(".onyx-artifact-*.tmp"))


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux O_TMPFILE required"
)
def test_linux_otmpfile_exact_winner_closes_anonymous_loser_as_unpublished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path)
    if not _linux_otmpfile_supported(root):
        pytest.skip("test filesystem does not support O_TMPFILE")
    payload = b"deterministic-exact-winner"
    digest = hashlib.sha256(payload).hexdigest()
    original_link = service._pinned._linux_link_descriptor
    original_publish = service._pinned.publish
    outcomes: list[artifacts._PublicationOutcome] = []
    installed_peer = False

    def exact_peer_wins(descriptor: int, prefix: int, name: str) -> None:
        nonlocal installed_peer
        if installed_peer:
            original_link(descriptor, prefix, name)
            return
        installed_peer = True
        flags = os.O_RDWR | os.O_TMPFILE | getattr(os, "O_CLOEXEC", 0)
        peer = os.open(root, flags, 0o600)
        try:
            assert service._pinned.descriptor_identity(peer) != (
                service._pinned.descriptor_identity(descriptor)
            )
            written = os.write(peer, payload)
            assert written == len(payload)
            os.fsync(peer)
            original_link(peer, prefix, name)
            os.fsync(prefix)
        finally:
            os.close(peer)
        original_link(descriptor, prefix, name)

    def capture_publish(*args, **kwargs):
        outcome = original_publish(*args, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(service._pinned, "_linux_link_descriptor", exact_peer_wins)
    monkeypatch.setattr(service._pinned, "publish", capture_publish)

    record = _publish(service, payload)

    assert outcomes == [artifacts._PublicationOutcome.EXACT_EXISTING]
    assert record.sha256 == digest
    assert service.read(record) == payload
    assert (root / record.relative_path).stat().st_nlink == 1
    assert [item for item in root.rglob("*") if item.is_file()] == [
        root / record.relative_path
    ]
    assert not list(root.rglob(".onyx-artifact-*.tmp"))


def test_existing_different_bytes_at_digest_path_fails_closed(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    payload = b"expected"
    digest = hashlib.sha256(payload).hexdigest()
    prefix = root / digest[:2]
    prefix.mkdir(mode=0o700)
    (prefix / digest).write_bytes(b"tampered collision")
    with pytest.raises(artifacts.ArtifactIntegrityError, match="size|sha256"):
        _publish(service, payload)
    assert (prefix / digest).read_bytes() == b"tampered collision"


def test_reopen_detects_content_tamper(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    record = _publish(service, b"original")
    target = root / record.relative_path
    target.write_bytes(b"tampered")
    with pytest.raises(artifacts.ArtifactIntegrityError):
        service.lookup(record)
    with pytest.raises(artifacts.ArtifactIntegrityError):
        service.read(record)


def test_final_name_swap_during_hash_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, service = _service(tmp_path)
    record = _publish(service, b"identity-bound")
    target = root / record.relative_path
    replacement = target.with_name("replacement")
    replacement.write_bytes(b"evil-replacement")
    original_hash = service._hash_descriptor
    swapped = False
    blocked = False

    def hash_then_swap(descriptor: int, *, expected_size: int) -> str:
        nonlocal swapped, blocked
        result = original_hash(descriptor, expected_size=expected_size)
        if not swapped:
            try:
                os.replace(replacement, target)
                swapped = True
            except PermissionError:
                # Windows holds a no-delete final handle, so the attack is
                # prevented before the explicit post-hash identity check.
                blocked = True
        return result

    monkeypatch.setattr(service, "_hash_descriptor", hash_then_swap)
    if os.name == "nt":
        assert service.lookup(record) == record
        assert blocked and not swapped
    else:
        with pytest.raises(
            artifacts.ArtifactIntegrityError,
            match="identity.*changed|identity, size, or timestamp",
        ):
            service.lookup(record)
        assert swapped


def test_temp_name_replacement_cannot_redirect_bytes_or_delete_other_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path)
    original_create = service._pinned.create_temp
    original_publish = service._pinned.publish
    replacement_path: Path | None = None
    replacement_blocked = False

    def replace_name_then_publish(
        temp_name: str, descriptor: int, prefix: int, digest: str,
        expected: tuple[int, ...],
    ) -> None:
        nonlocal replacement_path, replacement_blocked
        replacement_path = root / temp_name
        other_writer = root / "other-writer"
        other_writer.write_bytes(b"other-writer-bytes")
        try:
            os.replace(other_writer, replacement_path)
        except PermissionError:
            # Windows temporary handles deny delete sharing, which prevents the
            # pathname replacement before native handle-relative publication.
            replacement_blocked = True
            replacement_path = other_writer
        return original_publish(temp_name, descriptor, prefix, digest, expected)

    if os.name != "nt" and hasattr(artifacts.os, "O_TMPFILE"):
        def named_fallback_temp():
            original_flag = artifacts.os.O_TMPFILE
            try:
                delattr(artifacts.os, "O_TMPFILE")
                return original_create()
            finally:
                setattr(artifacts.os, "O_TMPFILE", original_flag)

        monkeypatch.setattr(service._pinned, "create_temp", named_fallback_temp)
    monkeypatch.setattr(service._pinned, "publish", replace_name_then_publish)
    if os.name == "nt":
        record = _publish(service, b"trusted-original")
        assert service.read(record) == b"trusted-original"
    else:
        with pytest.raises(artifacts.ArtifactIntegrityError, match="identity"):
            _publish(service, b"trusted-original")
    assert replacement_path is not None
    assert replacement_path.read_bytes() == b"other-writer-bytes"
    assert replacement_blocked is (os.name == "nt")


def test_publish_file_uses_a_pinned_regular_source_and_name_only_as_metadata(
    tmp_path: Path,
) -> None:
    root, service = _service(tmp_path)
    source = tmp_path / "report.txt"
    source.write_bytes(b"report")
    record = service.publish_file(
        source, media_type="text/plain", data_class="internal",
        source_provenance={"kind": "local-file"},
    )
    assert record.display_name == "report.txt"
    assert record.relative_path != source.name
    assert service.read(record) == b"report"
    assert (root / record.relative_path).is_file()


def test_symlink_source_is_rejected_when_supported(tmp_path: Path) -> None:
    _root_path, service = _service(tmp_path)
    target = tmp_path / "target.txt"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "source-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(artifacts.ArtifactIntegrityError):
        service.publish_file(
            link, media_type="text/plain", data_class="internal",
            source_provenance="symlink-test",
        )


def test_symlink_or_reparse_prefix_is_rejected(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    payload = b"prefix-link"
    digest = hashlib.sha256(payload).hexdigest()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / digest[:2]
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlink/reparse creation is unavailable")
    with pytest.raises(artifacts.ArtifactError):
        _publish(service, payload)
    assert list(outside.iterdir()) == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is unavailable")
def test_special_file_at_destination_is_rejected_without_blocking(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    payload = b"fifo-destination"
    digest = hashlib.sha256(payload).hexdigest()
    prefix = root / digest[:2]
    prefix.mkdir(mode=0o700)
    os.mkfifo(prefix / digest, 0o600)
    with pytest.raises(artifacts.ArtifactError):
        _publish(service, payload)


@pytest.mark.skipif(os.name == "nt", reason="POSIX link-count contract")
def test_hardlinked_destination_is_rejected(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    record = _publish(service, b"linked")
    os.link(root / record.relative_path, root / "alias")
    with pytest.raises(artifacts.ArtifactIntegrityError, match="linked"):
        service.lookup(record)


def test_root_path_replacement_cannot_redirect_publication(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    original = tmp_path / "pinned-original"
    root.rename(original)
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="path binding"):
        _publish(service, b"pinned")
    assert list(root.iterdir()) == []
    assert not [item for item in original.rglob("*") if item.is_file()]


def test_authorization_rejects_swap_between_path_identity_and_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "authorization-root"
    root.mkdir(mode=0o700)
    if os.name != "nt":
        root.chmod(0o700)
    moved = tmp_path / "authorization-root-moved"
    original_pinned = artifacts._PinnedDirectory

    def swap_then_pin(path: Path, *, authorized_identity: tuple[int, ...]):
        Path(path).rename(moved)
        Path(path).mkdir(mode=0o700)
        if os.name != "nt":
            Path(path).chmod(0o700)
        return original_pinned(path, authorized_identity=authorized_identity)

    monkeypatch.setattr(artifacts, "_PinnedDirectory", swap_then_pin)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="changed while"):
        artifacts._authorize_root_for_testing(
            root, allowlisted_roots=(root,), workspace_id="workspace-alpha",
        )
    assert list(root.iterdir()) == []
    assert list(moved.iterdir()) == []


def test_capability_object_binding_rejects_nonce_relabel(tmp_path: Path) -> None:
    _root_path, capability = _root(tmp_path)
    original_nonce = capability._nonce
    capability._nonce = b"x" * 32
    try:
        with pytest.raises(artifacts.ArtifactIntegrityError, match="object binding"):
            artifacts.ArtifactService(
                capability, workspace_id="workspace-alpha", enabled=True,
            )
    finally:
        capability._nonce = original_nonce
        capability.close()


def test_close_waits_for_inflight_and_rejects_new_operations(tmp_path: Path) -> None:
    _root_path, capability = _root(tmp_path)
    service = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    entered = threading.Event()
    release = threading.Event()

    class BlockingStream:
        done = False

        def read(self, _size: int):
            if self.done:
                return b""
            self.done = True
            entered.set()
            assert release.wait(timeout=5)
            return b"in-flight"

    with ThreadPoolExecutor(max_workers=2) as pool:
        publishing = pool.submit(
            service.publish_stream,
            BlockingStream(),
            media_type="application/octet-stream",
            data_class="internal",
            source_provenance="lease-test",
        )
        assert entered.wait(timeout=5)
        closing = pool.submit(capability.close)
        deadline = time.monotonic() + 5
        while not service._state._closing and time.monotonic() < deadline:
            time.sleep(0.005)
        assert service._state._closing
        assert not closing.done()
        with pytest.raises(artifacts.ArtifactIntegrityError, match="clos"):
            _publish(service, b"rejected-after-close-start")
        release.set()
        record = publishing.result(timeout=5)
        closing.result(timeout=5)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="closed|closing"):
        service.lookup(record)


def test_underlying_pinned_close_failure_is_retryable_and_preserves_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root_path, capability = _root(tmp_path)
    service = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    state = service._state
    attempts = 0
    if os.name == "nt":
        assert state.pinned._windows is not None
        assert state.pinned._root_handle is not None
        expected_api = state.pinned._windows
        expected_handle = state.pinned._root_handle
        original_os_close = artifacts._WindowsAPI.close

        def fail_first_close(self, handle: int) -> None:
            nonlocal attempts
            if self is expected_api and handle == expected_handle:
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("injected underlying close failure")
            original_os_close(self, handle)

        monkeypatch.setattr(artifacts._WindowsAPI, "close", fail_first_close)
    else:
        assert state.pinned._fd_chain
        expected_handle = state.pinned._fd_chain[0]
        original_os_close = artifacts.os.close

        def fail_first_close(handle: int) -> None:
            nonlocal attempts
            if handle == expected_handle:
                attempts += 1
                if attempts == 1:
                    raise RuntimeError("injected underlying close failure")
            original_os_close(handle)

        monkeypatch.setattr(artifacts.os, "close", fail_first_close)

    with pytest.raises(RuntimeError, match="injected underlying close failure"):
        capability.close()

    assert state._closing is False
    assert state._closed is False
    assert state.pinned._closed is False
    if os.name == "nt":
        assert state.pinned._root_handle == expected_handle
    else:
        assert state.pinned._fd_chain[0] == expected_handle
        assert state.pinned._root_fd == state.pinned._fd_chain[-1]
    with artifacts._CAPABILITIES_LOCK:
        assert artifacts._CAPABILITIES.get(capability) is state
    assert capability._finalizer is not None
    assert capability._finalizer.alive is True

    # The failed close did not create a half-closed authority.  Operations may
    # resume until the host explicitly retries the release.
    assert service.read(_publish(service, b"usable-after-failed-close")) == (
        b"usable-after-failed-close"
    )
    capability.close()
    assert attempts == 2
    assert state._closing is False
    assert state._closed is True
    with artifacts._CAPABILITIES_LOCK:
        assert capability not in artifacts._CAPABILITIES
    assert capability._finalizer.alive is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor chain required")
def test_posix_partial_close_retry_never_double_closes_confirmed_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root_path, capability = _root(tmp_path)
    service = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    state = service._state
    original_chain = list(state.pinned._fd_chain)
    assert len(original_chain) >= 3
    released_before_failure = original_chain[0]
    failed_handle = original_chain[1]
    root_handle = original_chain[-1]
    original_os_close = artifacts.os.close
    descriptor_identities = {
        handle: (status.st_dev, status.st_ino)
        for handle in original_chain
        for status in (os.fstat(handle),)
    }
    close_events: list[tuple[int, tuple[int, int]]] = []
    failed_once = False

    def fail_after_one_confirmed_release(handle: int) -> None:
        nonlocal failed_once
        status = os.fstat(handle)
        identity = (status.st_dev, status.st_ino)
        if identity in descriptor_identities.values():
            close_events.append((handle, identity))
        if identity == descriptor_identities[failed_handle] and not failed_once:
            failed_once = True
            raise RuntimeError("injected second descriptor close failure")
        original_os_close(handle)

    monkeypatch.setattr(artifacts.os, "close", fail_after_one_confirmed_release)
    with pytest.raises(RuntimeError, match="second descriptor close failure"):
        capability.close()

    assert close_events[:2] == [
        (released_before_failure, descriptor_identities[released_before_failure]),
        (failed_handle, descriptor_identities[failed_handle]),
    ]
    assert state.pinned._fd_chain == original_chain[1:]
    assert state.pinned._root_fd == root_handle
    assert state.pinned._closed is False
    assert service.read(_publish(service, b"root-remains-authoritative")) == (
        b"root-remains-authoritative"
    )

    capability.close()
    released_identity = descriptor_identities[released_before_failure]
    failed_identity = descriptor_identities[failed_handle]
    assert sum(identity == released_identity for _handle, identity in close_events) == 1
    assert sum(identity == failed_identity for _handle, identity in close_events) == 2
    assert state.pinned._fd_chain == []
    assert state.pinned._root_fd is None
    assert state.pinned._closed is True


def test_read_hashes_and_returns_bytes_from_one_open_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root_path, service = _service(tmp_path)
    record = _publish(service, b"single-descriptor")
    original_open = service._pinned.open_existing
    opened: list[int] = []

    def counted_open(prefix: int, digest: str) -> int:
        descriptor = original_open(prefix, digest)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(service._pinned, "open_existing", counted_open)
    assert service.read(record) == b"single-descriptor"
    assert len(opened) == 1


@pytest.mark.parametrize(
    "created_at",
    [
        "2026-07-18T01:02:03Z",
        "2026-07-18T01:02:03.123Z",
        "2026-07-18T01:02:03.1234567Z",
        "2026-07-18T01:02:03.123456+00:00",
        "2026-07-18t01:02:03.123456z",
    ],
)
def test_record_timestamp_requires_exact_canonical_microsecond_utc_form(
    tmp_path: Path, created_at: str,
) -> None:
    _root_path, service = _service(tmp_path)
    record = _publish(service)
    with pytest.raises(artifacts.ArtifactContractError, match="created_at"):
        service.lookup(replace(record, created_at=created_at))


@pytest.mark.skipif(os.name != "nt", reason="Windows hardlink defense")
def test_windows_hardlink_defense_makes_real_conditional_attempt(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    record = _publish(service, b"windows-hardlink")
    target = root / record.relative_path
    alias = root / "real-hardlink-attempt"
    try:
        os.link(target, alias)
    except OSError as exc:
        assert exc.winerror is not None or exc.errno is not None
        assert int(target.stat().st_nlink) == 1
    else:
        assert alias.samefile(target)
        assert int(target.stat().st_nlink) >= 2
        with pytest.raises(artifacts.ArtifactIntegrityError, match="multiple|linked"):
            service.lookup(record)


def test_publish_bytes_uses_bounded_views_without_full_input_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root_path, service = _service(tmp_path, max_bytes=3 * 1024 * 1024)
    sentinel = _publish(service, b"sentinel")
    payload = bytearray(b"x" * (2 * 1024 * 1024))
    observed: list[memoryview] = []

    def inspect_source(source, **_kwargs):
        first = source.read(1024 * 1024)
        observed.append(first)
        return sentinel

    monkeypatch.setattr(service, "_publish_stream_impl", inspect_source)
    assert service.publish_bytes(
        payload, media_type="application/octet-stream", data_class="internal",
        source_provenance="zero-copy-test",
    ) is sentinel
    assert len(observed) == 1
    assert isinstance(observed[0], memoryview)
    assert observed[0].obj is payload
    assert observed[0].nbytes == 1024 * 1024


def test_stream_overlimit_is_rejected_before_any_payload_copy_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path, max_bytes=16)
    payload = bytearray(b"x" * 4096)
    writes = 0
    original_write = artifacts.os.write

    def counted_write(descriptor: int, data) -> int:
        nonlocal writes
        writes += 1
        return original_write(descriptor, data)

    class OversizedStream:
        def read(self, _size: int):
            return memoryview(payload)

    monkeypatch.setattr(artifacts.os, "write", counted_write)
    with pytest.raises(artifacts.ArtifactTooLarge):
        service.publish_stream(
            OversizedStream(), media_type="application/octet-stream",
            data_class="internal", source_provenance="pre-copy-bound",
        )
    assert writes == 0
    assert not list(root.rglob(".onyx-artifact-*.tmp"))


def test_linux_publication_is_descriptor_bound_not_temp_name_bound() -> None:
    create_source = inspect.getsource(artifacts._PinnedDirectory.create_temp)
    publish_source = inspect.getsource(artifacts._PinnedDirectory.publish)
    assert "O_TMPFILE" in create_source
    assert "anonymous" in publish_source
    assert "_linux_link_descriptor" in publish_source
    helper = inspect.getsource(artifacts._PinnedDirectory._linux_link_descriptor)
    assert "linkat" in helper
    assert "AT_EMPTY_PATH" in helper
    pinned_source = inspect.getsource(artifacts._PinnedDirectory)
    assert "os.unlink(" not in pinned_source


def test_manifest_rejects_extra_fields_and_noncanonical_json(tmp_path: Path) -> None:
    _root_path, service = _service(tmp_path)
    record = _publish(service)
    canonical = record.canonical_manifest()
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts.ArtifactRecord.from_manifest(canonical + b" ")
    decoded = __import__("json").loads(canonical)
    decoded["raw_content"] = "forbidden"
    with pytest.raises(artifacts.ArtifactContractError):
        artifacts.ArtifactRecord.from_manifest(
            __import__("json").dumps(decoded, sort_keys=True, separators=(",", ":"))
        )


@pytest.mark.skipif(os.name == "nt", reason="POSIX quarantine race contract")
def test_posix_failure_never_unlinks_replacement_and_quarantine_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path, max_bytes=32)
    original_create = service._pinned.create_temp
    original_publish = service._pinned.publish
    attacker = b"attacker replacement must survive"

    observed_temp: Path | None = None

    def replace_then_fail(temp_name, descriptor, prefix, digest, expected):
        nonlocal observed_temp
        del descriptor, prefix, digest, expected
        source = root / temp_name
        observed_temp = source
        retained_original = root / "attacker-moved-original"
        source.rename(retained_original)
        source.write_bytes(attacker)
        raise artifacts.ArtifactIntegrityError("injected publication race")

    if hasattr(artifacts.os, "O_TMPFILE"):
        def named_fallback_temp():
            original_flag = artifacts.os.O_TMPFILE
            try:
                delattr(artifacts.os, "O_TMPFILE")
                return original_create()
            finally:
                setattr(artifacts.os, "O_TMPFILE", original_flag)

        monkeypatch.setattr(service._pinned, "create_temp", named_fallback_temp)
    monkeypatch.setattr(service._pinned, "publish", replace_then_fail)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="publication race"):
        _publish(service, b"owner-created-bytes")
    assert observed_temp is not None
    assert observed_temp.read_bytes() == attacker
    assert (root / "attacker-moved-original").read_bytes() == b"owner-created-bytes"
    monkeypatch.setattr(service._pinned, "publish", original_publish)


@pytest.mark.skipif(os.name == "nt", reason="POSIX restart/idempotency contract")
def test_posix_duplicate_stream_bypasses_retained_quarantine_across_restart(
    tmp_path: Path,
) -> None:
    root, capability = _root(tmp_path)
    first = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    payload = b"restart-idempotent-stream"
    record = first.publish_stream(
        io.BytesIO(payload), media_type="application/octet-stream",
        data_class="internal", source_provenance="restart-stream",
        display_name="stream.bin",
    )
    attacker = b"do not delete replacement"
    (root / ".onyx-artifact-quarantine.tmp").write_bytes(attacker)
    restarted = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    replay = restarted.publish_stream(
        io.BytesIO(payload), media_type="application/octet-stream",
        data_class="internal", source_provenance="restart-stream",
        display_name="stream.bin",
    )
    assert replay == record
    assert (root / ".onyx-artifact-quarantine.tmp").read_bytes() == attacker


@pytest.mark.skipif(os.name == "nt", reason="POSIX restart/idempotency contract")
def test_posix_duplicate_file_bypasses_retained_quarantine_across_restart(
    tmp_path: Path,
) -> None:
    root, capability = _root(tmp_path)
    source = tmp_path / "same-file.bin"
    source.write_bytes(b"restart-idempotent-file")
    first = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    record = first.publish_file(
        source, media_type="application/octet-stream", data_class="internal",
        source_provenance="restart-file",
    )
    attacker = b"retained quarantine replacement"
    (root / ".onyx-artifact-quarantine.tmp").write_bytes(attacker)
    restarted = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    replay = restarted.publish_file(
        source, media_type="application/octet-stream", data_class="internal",
        source_provenance="restart-file",
    )
    assert replay == record
    assert (root / ".onyx-artifact-quarantine.tmp").read_bytes() == attacker


@pytest.mark.skipif(os.name == "nt", reason="POSIX crash/restart contract")
def test_posix_commit_then_crash_replays_existing_bytes_without_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, capability = _root(tmp_path)
    first = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    original_publish = first._pinned.publish

    def publish_then_interrupt(temp_name, descriptor, prefix, digest, expected):
        original_publish(temp_name, descriptor, prefix, digest, expected)
        raise artifacts.ArtifactIOError("simulated process interruption")

    monkeypatch.setattr(first._pinned, "publish", publish_then_interrupt)
    with pytest.raises(artifacts.ArtifactIOError, match="interruption"):
        first.publish_stream(
            io.BytesIO(b"committed-before-crash"),
            media_type="application/octet-stream", data_class="internal",
            source_provenance="crash-restart", display_name="crash.bin",
        )
    monkeypatch.setattr(first._pinned, "publish", original_publish)
    restarted = artifacts.ArtifactService(
        capability, workspace_id="workspace-alpha", enabled=True, max_bytes=4096,
    )
    replay = restarted.publish_stream(
        io.BytesIO(b"committed-before-crash"),
        media_type="application/octet-stream", data_class="internal",
        source_provenance="crash-restart", display_name="crash.bin",
    )
    assert replay.sha256 == hashlib.sha256(b"committed-before-crash").hexdigest()
    assert (root / replay.relative_path).read_bytes() == b"committed-before-crash"
    assert not (root / ".onyx-artifact-quarantine.tmp").exists()


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux descriptor publication required"
)
def test_linux_final_swap_during_descriptor_publication_is_retained_and_typed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path)
    if not _linux_otmpfile_supported(root):
        pytest.skip("test filesystem does not support O_TMPFILE")
    payload = b"descriptor-authoritative"
    digest = hashlib.sha256(payload).hexdigest()
    original_link = service._pinned._linux_link_descriptor

    def link_then_swap(descriptor: int, prefix: int, name: str) -> None:
        original_link(descriptor, prefix, name)
        replacement = root / "same-uid-replacement"
        replacement.write_bytes(b"poison")
        os.replace(replacement, root / digest[:2] / digest)

    monkeypatch.setattr(service._pinned, "_linux_link_descriptor", link_then_swap)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="canonical artifact"):
        _publish(service, payload)
    assert (root / digest[:2] / digest).read_bytes() == b"poison"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux descriptor publication required"
)
def test_linux_swap_after_final_identity_observation_never_deletes_peer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path)
    if not _linux_otmpfile_supported(root):
        pytest.skip("test filesystem does not support O_TMPFILE")
    payload = b"final-stat-unlink-window"
    digest = hashlib.sha256(payload).hexdigest()
    target = root / digest[:2] / digest
    peer = root / "same-uid-peer"
    peer.write_bytes(b"peer-must-survive")
    original_named_identity = service._pinned._named_identity
    swapped = False

    def observe_then_swap(directory: int, name: str):
        nonlocal swapped
        observed = original_named_identity(directory, name)
        if name == digest and observed is not None and not swapped:
            os.replace(peer, target)
            swapped = True
        return observed

    monkeypatch.setattr(service._pinned, "_named_identity", observe_then_swap)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="hardlink|linked"):
        _publish(service, payload)
    assert swapped
    assert target.read_bytes() == b"peer-must-survive"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor identity required")
def test_posix_discard_rejects_reused_fd_by_inode_identity(
    tmp_path: Path,
) -> None:
    root, service = _service(tmp_path)
    with service._pinned.publication_lock():
        name, descriptor, identity = service._pinned.create_temp()
        os.close(descriptor)
        other = root / "fd-reuse-sentinel"
        other.write_bytes(b"sentinel")
        reused = os.open(other, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
        try:
            with pytest.raises(
                artifacts.ArtifactIntegrityError, match="identity changed"
            ):
                service._pinned.discard_temp(
                    name, reused, identity, published=False
                )
        finally:
            os.close(reused)
    assert other.read_bytes() == b"sentinel"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux hardlink publication required"
)
def test_linux_temp_hardlink_injection_fails_without_canonical_poisoning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, service = _service(tmp_path)
    payload = b"hardlink-contained"
    digest = hashlib.sha256(payload).hexdigest()
    original_create = service._pinned.create_temp
    original_publish = service._pinned.publish

    def named_fallback_temp():
        original_flag = getattr(artifacts.os, "O_TMPFILE")
        try:
            delattr(artifacts.os, "O_TMPFILE")
            return original_create()
        finally:
            setattr(artifacts.os, "O_TMPFILE", original_flag)

    def hardlink_then_publish(temp_name, descriptor, prefix, name, expected):
        os.link(root / temp_name, root / "attacker-hardlink")
        original_publish(temp_name, descriptor, prefix, name, expected)

    monkeypatch.setattr(service._pinned, "create_temp", named_fallback_temp)
    monkeypatch.setattr(service._pinned, "publish", hardlink_then_publish)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="hardlink|linked"):
        _publish(service, payload)
    assert (root / digest[:2] / digest).read_bytes() == payload
    assert (root / "attacker-hardlink").read_bytes() == payload


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux crash recovery required"
)
def test_linux_legacy_crash_residue_is_retained_and_reported(tmp_path: Path) -> None:
    root, service = _service(tmp_path)
    stale = root / f".onyx-artifact-{'a' * 64}.tmp"
    stale.write_bytes(b"crashed-private-bytes")
    stale.chmod(0o600)
    if _linux_otmpfile_supported(root):
        # Anonymous staging does not need to inspect legacy residue.
        record = _publish(service, b"replay-after-crash")
        assert service.read(record) == b"replay-after-crash"
    else:
        with pytest.raises(
            artifacts.ArtifactIntegrityError, match="offline reconciliation"
        ):
            _publish(service, b"replay-after-crash")
    assert stale.read_bytes() == b"crashed-private-bytes"


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="Linux O_TMPFILE required"
)
def test_linux_anonymous_crash_residue_disappears_on_descriptor_close(
    tmp_path: Path,
) -> None:
    root, service = _service(tmp_path)
    if not _linux_otmpfile_supported(root):
        pytest.skip("test filesystem does not support O_TMPFILE")
    with service._pinned.publication_lock():
        name, descriptor, identity = service._pinned.create_temp()
        assert name == ""
        assert service._pinned.descriptor_identity(descriptor) == identity
        os.write(descriptor, b"process-died-before-publication")
        os.close(descriptor)
    assert not list(root.glob(".onyx-artifact-*.tmp"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO race contract")
def test_posix_source_swap_to_fifo_is_nonblocking_and_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root_path, service = _service(tmp_path)
    source = tmp_path / "source-race"
    source.write_bytes(b"regular-before-open")
    original_open = artifacts.os.open
    swapped = False

    def swap_then_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path) == source:
            swapped = True
            source.unlink()
            os.mkfifo(source, 0o600)
            assert flags & getattr(os, "O_NONBLOCK", 0)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(artifacts.os, "open", swap_then_open)
    with pytest.raises(artifacts.ArtifactIntegrityError, match="regular"):
        service.publish_file(
            source, media_type="application/octet-stream", data_class="internal",
            source_provenance="fifo-race",
        )
    assert swapped
