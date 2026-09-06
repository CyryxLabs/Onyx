from __future__ import annotations

import errno
import json
import multiprocessing
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from core import native_vault
from core.google_workspace_connector_v1 import (
    GMAIL_ORIGIN,
    GMAIL_PROFILE_PATH,
    OAUTH_ORIGIN,
    READ_SCOPES,
    TOKEN_PATH,
    GoogleHttpResponseV1,
    GoogleAuthorizationStartV1,
    GooglePendingAuthorizationV1,
    GoogleTokenBundleV1,
    GoogleWorkspaceBindingV1,
    GoogleWorkspaceFeatureGateV1,
    GoogleWorkspaceV1Denied,
    InMemoryGoogleGrantMetadataStoreV1,
)
from core.google_workspace_host_v1 import (
    GoogleOAuthLoopbackReceiverV1,
    GoogleWorkspaceHostConfigurationV1,
    GoogleWorkspaceHostV1ContractError,
    GoogleWorkspaceHostV1Denied,
    GoogleWorkspaceHostV1UnknownOutcome,
    GoogleWorkspaceRootAuthorityV1,
    NativeGoogleHostLeaseV1,
    _create_google_workspace_host_parts_for_test_v1,
    _create_google_workspace_host_service_for_test_v1,
    _related_state_witness_path,
    _scope_seed,
    _read_related_state_witness_v1,
    _prepare_related_state_witness_v1,
    _commit_related_state_witness_v1,
    _validated_metadata_parent_v1,
    _validated_metadata_path_v1,
    _write_related_state_witness_v1,
    create_google_workspace_host_service_v1,
    read_google_workspace_host_status_v1,
)
from scripts.onyx_google_workspace import (
    EXIT_CONTRACT,
    EXIT_DENIED,
    EXIT_OK,
    EXIT_UNKNOWN,
    run_cli_v1,
)


NOW = 2_000_000_000


def _hold_native_google_lease(queue, release, scope):
    lease = NativeGoogleHostLeaseV1()
    try:
        with lease.hold(scope, timeout_seconds=5.0):
            queue.put("held")
            release.wait(10)
    except Exception as exc:
        queue.put(type(exc).__name__)
    finally:
        lease.close()


def _native_anchor_cas_process(queue, scope, binding_digest, key, store_reference):
    lease = NativeGoogleHostLeaseV1()
    try:
        anchor_type = __import__(
            "core.google_workspace_host_v1",
            fromlist=["NativeGoogleMetadataGenerationAnchorV1"],
        ).NativeGoogleMetadataGenerationAnchorV1
        anchor = anchor_type(
            binding_digest=binding_digest,
            authentication_key=key,
            lease=lease,
            lease_scope=scope,
        )
        queue.put(anchor.compare_and_swap(store_reference, 0, 1))
    except Exception as exc:
        queue.put(type(exc).__name__)
    finally:
        lease.close()


class FakeVault:
    def __init__(self, values, reference, failures=None):
        self.values = values
        self.reference = reference
        self.failures = set() if failures is None else failures

    def get_bytes(self):
        if (self.reference.service, self.reference.account, "get") in self.failures:
            raise RuntimeError("secret-value-was-here")
        return self.values.get((self.reference.service, self.reference.account))

    def set_bytes(self, value):
        if (self.reference.service, self.reference.account, "set") in self.failures:
            raise RuntimeError("secret-value-was-here")
        self.values[(self.reference.service, self.reference.account)] = bytes(value)

    def delete(self):
        if (self.reference.service, self.reference.account, "delete") in self.failures:
            raise RuntimeError("secret-value-was-here")
        return self.values.pop((self.reference.service, self.reference.account), None) is not None


class FakeVaultFactory:
    def __init__(self):
        self.values = {}
        self.references = []
        self.failures = set()

    def __call__(self, reference):
        self.references.append(reference)
        return FakeVault(self.values, reference, self.failures)


class FaultOnceVault(FakeVault):
    def _fail(self, operation):
        fault = self.failures.get("once")
        if fault is not None and fault[0] == operation and fault[1] in self.reference.account:
            self.failures.pop("once")
            raise RuntimeError("secret-fault-detail")

    def get_bytes(self):
        self._fail("get")
        return super().get_bytes()

    def set_bytes(self, value):
        self._fail("set")
        return super().set_bytes(value)

    def delete(self):
        self._fail("delete")
        return super().delete()


class FaultOnceVaultFactory(FakeVaultFactory):
    def __init__(self):
        super().__init__()
        self.failures = {}

    def __call__(self, reference):
        self.references.append(reference)
        return FaultOnceVault(self.values, reference, self.failures)


class FakeLease:
    def __init__(self):
        self.lock = threading.RLock()
        self.holds = 0

    @contextmanager
    def hold(self, scope, *, timeout_seconds):
        assert scope.startswith("google-")
        assert 0 < timeout_seconds <= 30
        with self.lock:
            self.holds += 1
            yield self


class ReleaseFaultLease(FakeLease):
    def __init__(self):
        super().__init__()
        self.fail_release = False

    @contextmanager
    def hold(self, scope, *, timeout_seconds):
        with super().hold(scope, timeout_seconds=timeout_seconds):
            yield self
        if self.fail_release:
            self.fail_release = False
            raise RuntimeError("private-release-detail")


class CloseProbe:
    def __init__(self):
        self.calls = 0

    def close(self):
        self.calls += 1


class Http:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        return outcome(request) if callable(outcome) else outcome


class RoutingHttp:
    def __init__(self):
        self.requests = []
        self.lock = threading.Lock()

    def send(self, request):
        with self.lock:
            self.requests.append(request)
        if request.origin == OAUTH_ORIGIN and request.path == TOKEN_PATH:
            return response(
                OAUTH_ORIGIN, TOKEN_PATH,
                {"access_token": "access", "refresh_token": "refresh",
                 "expires_in": 3600, "scope": " ".join(READ_SCOPES),
                 "token_type": "Bearer"},
            )
        if request.origin == GMAIL_ORIGIN and request.path == GMAIL_PROFILE_PATH:
            return response(
                GMAIL_ORIGIN, GMAIL_PROFILE_PATH,
                {"emailAddress": "sir@example.com"},
            )
        if request.origin == OAUTH_ORIGIN and request.path == "/revoke":
            return response(OAUTH_ORIGIN, "/revoke", {})
        if request.origin == GMAIL_ORIGIN:
            return response(GMAIL_ORIGIN, request.path, {"messages": []})
        return response(request.origin, request.path, {"items": []})


def response(origin, path, payload, *, status=200):
    return GoogleHttpResponseV1(
        status, payload, len(str(payload).encode()), 1, origin, path
    )


def config(port=43871):
    return GoogleWorkspaceHostConfigurationV1(
        GoogleWorkspaceBindingV1("owner-1", "workspace-1", "sir@example.com"),
        "onyx-desktop-client.apps.googleusercontent.com",
        port,
    )


def parts():
    factory = FakeVaultFactory()
    lease = FakeLease()
    selected = _create_google_workspace_host_parts_for_test_v1(
        config(), lease=lease, vault_factory=factory
    )
    return selected, factory, lease


def fault_parts():
    factory = FaultOnceVaultFactory()
    lease = FakeLease()
    selected = _create_google_workspace_host_parts_for_test_v1(
        config(), lease=lease, vault_factory=factory
    )
    return selected, factory, lease


def test_default_off_and_incomplete_factory_are_exactly_side_effect_free(monkeypatch):
    called = []
    monkeypatch.setattr(
        "core.google_workspace_host_v1.NativeGoogleHostLeaseV1",
        lambda: called.append("lease"),
    )
    assert create_google_workspace_host_service_v1(
        gate=GoogleWorkspaceFeatureGateV1(False), configuration=None
    ) is None
    assert create_google_workspace_host_service_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=None
    ) is None
    assert called == []


def test_platform_backend_selection_harnesses_are_explicit_source_simulations():
    reference = native_vault.SecretReference(
        "Onyx.GoogleWorkspace.SourceHarness.v1",
        "source-harness",
        "Onyx Google Workspace source harness",
    )
    assert native_vault.NativeSecretVault(reference, system="Windows").backend_name == "Windows Credential Manager"
    assert native_vault.NativeSecretVault(reference, system="Darwin").backend_name == "macOS Keychain"
    assert native_vault.NativeSecretVault(reference, system="Linux").backend_name == "Secret Service"


@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows host evidence only")
def test_native_windows_credential_manager_read_and_cross_process_lease():
    reference = native_vault.SecretReference(
        "Onyx.GoogleWorkspace.HostEvidence.v1",
        "missing-" + __import__("secrets").token_hex(12),
        "Onyx Google Workspace Windows host evidence",
    )
    assert native_vault.NativeSecretVault(reference).get_bytes() is None
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    release = context.Event()
    scope = "google-host-evidence-" + __import__("secrets").token_hex(8)
    process = context.Process(
        target=_hold_native_google_lease, args=(queue, release, scope)
    )
    process.start()
    assert queue.get(timeout=10) == "held"
    competing = NativeGoogleHostLeaseV1()
    try:
        with pytest.raises(GoogleWorkspaceHostV1Denied):
            with competing.hold(scope, timeout_seconds=0.05):
                pass
    finally:
        competing.close()
        release.set()
        process.join(10)
        if process.is_alive():
            process.terminate()
            process.join(5)
    assert process.exitcode == 0


@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows host evidence only")
def test_native_windows_anchor_exact_cross_process_cas_and_cleanup():
    anchor_type = __import__(
        "core.google_workspace_host_v1",
        fromlist=["NativeGoogleMetadataGenerationAnchorV1"],
    ).NativeGoogleMetadataGenerationAnchorV1
    scope = "google-anchor-diagnostic-" + __import__("secrets").token_hex(8)
    binding_digest = __import__("hashlib").sha256(scope.encode()).hexdigest()
    key = __import__("secrets").token_bytes(32)
    store_reference = __import__("hashlib").sha256(key).hexdigest()
    references = []

    def tracking_factory(reference):
        references.append(reference)
        return native_vault.NativeSecretVault(reference)

    lease = NativeGoogleHostLeaseV1()
    anchor = anchor_type(
        binding_digest=binding_digest, authentication_key=key, lease=lease,
        lease_scope=scope, vault_factory=tracking_factory,
    )
    processes = []
    try:
        assert anchor.compare_and_swap(store_reference, None, 0) is True
        context = multiprocessing.get_context("spawn")
        queue = context.Queue()
        processes = [
            context.Process(
                target=_native_anchor_cas_process,
                args=(queue, scope, binding_digest, key, store_reference),
            )
            for _ in range(4)
        ]
        for process in processes:
            process.start()
        results = [queue.get(timeout=15) for _ in processes]
        for process in processes:
            process.join(15)
        assert results.count(True) == 1
        assert results.count(False) == 3
        assert anchor.read(store_reference) == 1
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(5)
        try:
            anchor.read(store_reference)
        except Exception:
            pass
        lease.close()
        unique = {
            (reference.service, reference.account, reference.label): reference
            for reference in references
        }
        for reference in unique.values():
            vault = native_vault.NativeSecretVault(reference)
            result = vault.delete()
            assert type(result) is bool
            assert vault.get_bytes() is None


@pytest.mark.skipif(platform.system() != "Darwin", reason="native macOS host gate open")
def test_native_macos_keychain_read_observation():
    reference = native_vault.SecretReference(
        "Onyx.GoogleWorkspace.HostEvidence.v1", "missing-source-harness",
        "Onyx Google Workspace macOS host evidence",
    )
    assert native_vault.NativeSecretVault(reference).get_bytes() is None


@pytest.mark.skipif(platform.system() != "Linux", reason="native Linux host gate open")
def test_native_linux_secret_service_read_observation():
    reference = native_vault.SecretReference(
        "Onyx.GoogleWorkspace.HostEvidence.v1", "missing-source-harness",
        "Onyx Google Workspace Linux host evidence",
    )
    assert native_vault.NativeSecretVault(reference).get_bytes() is None


def test_root_provisioning_is_idempotent_and_domains_are_separate():
    selected, factory, lease = parts()
    keys = selected.root.keys()
    assert set(keys) == set(GoogleWorkspaceRootAuthorityV1.DOMAINS)
    assert len(set(keys.values())) == len(keys)
    assert all(len(value) == 32 for value in keys.values())
    assert selected.root.provision() is False
    assert lease.holds >= 3
    aliases = " ".join(
        reference.service + " " + reference.account for reference in factory.references
    )
    assert "owner-1" not in aliases
    assert "workspace-1" not in aliases
    assert "sir@example.com" not in aliases


def test_root_missing_or_malformed_fails_closed_without_rotation():
    factory = FakeVaultFactory()
    lease = FakeLease()
    authority = GoogleWorkspaceRootAuthorityV1(
        config().binding, lease=lease, vault_factory=factory
    )
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        authority.load()
    authority.provision()
    key = next(iter(factory.values))
    factory.values[key] = b"short"
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        authority.load()
    assert factory.values[key] == b"short"


def test_metadata_ancestors_are_validated_before_any_creation(monkeypatch, tmp_path):
    bad_parent = tmp_path / "bad-parent"
    bad_parent.write_text("not-a-directory", encoding="utf-8")
    intended = bad_parent / "runtime"
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: intended,
    )
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        _validated_metadata_path_v1("1" * 64)
    assert not intended.exists()


def test_metadata_parent_identity_is_pinned_and_rejects_directory_swap(
    monkeypatch, tmp_path
):
    runtime = tmp_path / "runtime"
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: runtime,
    )
    authority = _validated_metadata_parent_v1()
    metadata_path = authority.root / ("1" * 64)
    displaced = authority.root.with_name("google-workspace-host-old")
    try:
        # Exact factory window: the final revalidation has completed and the
        # SQLite constructor has not yet been invoked.
        authority.validate()
        try:
            authority.root.rename(displaced)
        except OSError:
            authority.validate()
        else:
            authority.root.mkdir()
            with pytest.raises(GoogleWorkspaceHostV1Denied):
                authority.validate()
        assert not metadata_path.exists()
    finally:
        authority.close()


def test_native_host_lease_close_closes_lease_and_boundary_once():
    lease = object.__new__(NativeGoogleHostLeaseV1)
    lease._closed = False
    lease._lease_closed = False
    lease._boundary_closed = False
    lease_probe = CloseProbe()
    boundary_probe = CloseProbe()
    lease._lease = lease_probe
    lease._boundary = boundary_probe
    lease.close()
    lease.close()
    assert lease_probe.calls == 1
    assert boundary_probe.calls == 1
    assert lease._boundary is None


class UnderlyingLeaseProbe:
    def __init__(self, failure=None):
        self.failure = failure

    @contextmanager
    def hold(self, _scope, *, timeout_seconds):
        del timeout_seconds
        if self.failure == "acquire":
            raise RuntimeError("private-acquire")
        yield self
        if self.failure == "release":
            raise RuntimeError("private-release")


class ExitFailureUnderlyingLease:
    class Context:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            raise RuntimeError("private-release")

    def hold(self, _scope, *, timeout_seconds):
        del timeout_seconds
        return self.Context()


def native_adapter(underlying):
    adapter = object.__new__(NativeGoogleHostLeaseV1)
    adapter._closed = False
    adapter._lease_closed = False
    adapter._boundary_closed = True
    adapter._lease = underlying
    adapter._boundary = None
    return adapter


@pytest.mark.parametrize(
    "error",
    (
        GoogleWorkspaceHostV1ContractError("body-contract"),
        GoogleWorkspaceHostV1Denied("body-denied"),
        GoogleWorkspaceHostV1UnknownOutcome("body-unknown"),
    ),
)
def test_native_host_lease_passthroughs_typed_body_failures(error):
    adapter = native_adapter(UnderlyingLeaseProbe())
    with pytest.raises(type(error)) as raised:
        with adapter.hold("google-adapter-test", timeout_seconds=1):
            raise error
    assert raised.value is error


def test_native_host_lease_translates_only_acquire_release_and_preserves_primary():
    for phase in ("acquire", "release"):
        adapter = native_adapter(UnderlyingLeaseProbe(phase))
        with pytest.raises(GoogleWorkspaceHostV1Denied) as raised:
            with adapter.hold("google-adapter-test", timeout_seconds=1):
                pass
        assert "private" not in str(raised.value)
    primary = GoogleWorkspaceHostV1UnknownOutcome("primary")
    adapter = native_adapter(ExitFailureUnderlyingLease())
    with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome) as raised:
        with adapter.hold("google-adapter-test", timeout_seconds=1):
            raise primary
    assert raised.value is primary


def test_native_host_lease_real_underlying_preserves_body_unknown_outcome():
    adapter = NativeGoogleHostLeaseV1()
    primary = GoogleWorkspaceHostV1UnknownOutcome("body-unknown")
    try:
        with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome) as raised:
            with adapter.hold(
                "google-body-passthrough-" + __import__("secrets").token_hex(8),
                timeout_seconds=2,
            ):
                raise primary
        assert raised.value is primary
    finally:
        adapter.close()


@pytest.mark.parametrize("missing", ("root", "marker", "witness", "root-and-marker"))
def test_root_loss_with_existing_configuration_never_reprovisions(missing):
    selected, factory, _ = parts()
    selected.configuration.configure(config())
    root_key = next(key for key in factory.values if key[0].endswith(".Root.v1"))
    marker_key = next(
        key for key in factory.values if key[0].endswith(".RootMarker.v1")
    )
    witness_key = next(
        key for key in factory.values if key[0].endswith(".StateWitness.v1")
    )
    removed = {
        "root": (root_key,),
        "marker": (marker_key,),
        "witness": (witness_key,),
        "root-and-marker": (root_key, marker_key),
    }[missing]
    for key in removed:
        factory.values.pop(key)
    snapshot = dict(factory.values)
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        selected.root.provision()
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        selected.root.load()
    assert factory.values == snapshot


def test_total_vault_authority_loss_is_detected_by_external_related_state(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    factory = FakeVaultFactory()
    lease = FakeLease()
    selected = _create_google_workspace_host_parts_for_test_v1(
        config(), lease=lease, vault_factory=factory
    )
    selected.configuration.configure(config())
    _write_related_state_witness_v1(selected.root.scope_seed)
    for key in tuple(factory.values):
        if key[0].endswith((".Root.v1", ".RootMarker.v1", ".StateWitness.v1")):
            factory.values.pop(key)
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        selected.root.provision()
    assert _related_state_witness_path(selected.root.scope_seed).is_file()


def test_prepared_witness_crash_states_never_silently_reprovision(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    factory = FakeVaultFactory()
    lease = FakeLease()
    authority = GoogleWorkspaceRootAuthorityV1(
        config().binding, lease=lease, vault_factory=factory
    )
    assert _read_related_state_witness_v1(authority.scope_seed) is None
    parent = _validated_metadata_parent_v1()
    try:
        state, created = _prepare_related_state_witness_v1(
            authority.scope_seed, parent=parent
        )
        assert (state, created) == ("PREPARED", True)
        # Crash after PREPARED and before root: next provisioning fails closed.
        with pytest.raises(GoogleWorkspaceHostV1Denied):
            authority.provision()
        provisioner = GoogleWorkspaceRootAuthorityV1(
            config().binding, lease=lease, vault_factory=factory,
            related_state_probe=lambda: False,
        )
        assert provisioner.provision() is True
        assert authority.load_observable() == provisioner.load_observable()
        selected = _create_google_workspace_host_parts_for_test_v1(
            config(), lease=lease, vault_factory=factory, provision=False
        )
        # Crash after root/before config is resumable without root rotation.
        root_before = authority.load_observable()
        assert selected.configuration.configure(config()) is True
        assert authority.load_observable() == root_before
        # Crash after config/before commit remains PREPARED and fail-closed on
        # total authority loss; intact authority can deterministically commit.
        assert _read_related_state_witness_v1(authority.scope_seed) == "PREPARED"
        _commit_related_state_witness_v1(authority.scope_seed, parent=parent)
        assert _read_related_state_witness_v1(authority.scope_seed) == "COMMITTED"
    finally:
        parent.close()


@pytest.mark.parametrize(
    ("fault", "state_after_fault"),
    (
        ("partial-write", "PREPARED"),
        ("flush", "PREPARED"),
        ("close", "PREPARED"),
        ("before-replace", "PREPARED"),
        ("replace", "PREPARED"),
        ("after-replace", "COMMITTED"),
        ("readback", "COMMITTED"),
        ("parent-fsync", "COMMITTED"),
    ),
)
def test_external_witness_atomic_faults_keep_valid_target_and_retry(
    fault, state_after_fault, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    witness = _related_state_witness_path(scope_seed)
    parent = _validated_metadata_parent_v1()
    restart_expected = False
    try:
        _prepare_related_state_witness_v1(scope_seed, parent=parent)
        assert _read_related_state_witness_v1(scope_seed) == "PREPARED"

        with monkeypatch.context() as injected:
            if fault == "partial-write":
                real_write = os.write
                calls = 0

                def partial_write(descriptor, value):
                    nonlocal calls
                    calls += 1
                    if calls == 1:
                        bound = max(1, len(value) // 2)
                        return real_write(descriptor, value[:bound])
                    raise OSError("injected partial write failure")

                injected.setattr(
                    "core.google_workspace_host_v1.os.write", partial_write
                )
            elif fault == "flush":
                injected.setattr(
                    "core.google_workspace_host_v1.os.fsync",
                    lambda _descriptor: (_ for _ in ()).throw(
                        OSError("injected flush failure")
                    ),
                )
            elif fault == "close":
                real_close = os.close

                def close_once(descriptor):
                    real_close(descriptor)
                    raise OSError(errno.EBADF, "injected close ambiguity")

                injected.setattr(
                    "core.google_workspace_host_v1.os.close", close_once
                )
            elif fault == "before-replace":
                injected.setattr(
                    "core.google_workspace_host_v1._before_external_witness_replace_v1",
                    lambda: (_ for _ in ()).throw(
                        OSError("injected before-replace failure")
                    ),
                )
            elif fault == "replace":
                injected.setattr(
                    "core.google_workspace_host_v1._atomic_replace_external_witness_v1",
                    lambda _source, _destination: (_ for _ in ()).throw(
                        OSError("injected replace failure")
                    ),
                )
            elif fault == "after-replace":
                injected.setattr(
                    "core.google_workspace_host_v1._after_external_witness_replace_v1",
                    lambda: (_ for _ in ()).throw(
                        OSError("injected after-replace failure")
                    ),
                )
            elif fault == "readback":
                reads = 0

                def readback_once(value):
                    nonlocal reads
                    reads += 1
                    if reads == 1:
                        return _read_related_state_witness_v1(value)
                    raise OSError("injected readback failure")

                injected.setattr(
                    "core.google_workspace_host_v1._read_related_state_witness_v1",
                    readback_once,
                )
            elif fault == "parent-fsync":
                injected.setattr(
                    "core.google_workspace_host_v1._sync_external_witness_parent_v1",
                    lambda _path: (_ for _ in ()).throw(
                        OSError("injected parent fsync failure")
                    ),
                )
            else:  # pragma: no cover - the parameter table is closed above.
                raise AssertionError(fault)

            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                _commit_related_state_witness_v1(scope_seed, parent=parent)

        assert _read_related_state_witness_v1(scope_seed) == state_after_fault
        assert witness.is_file()
        pending = tuple(
            entry for entry in parent.root.iterdir() if ".tmp-" in entry.name
        )
        if fault == "close":
            assert len(pending) == 1
            restart_expected = True
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                _commit_related_state_witness_v1(scope_seed, parent=parent)
            assert _read_related_state_witness_v1(scope_seed) == "PREPARED"
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                parent.close()
            assert parent._closed is True
            pending[0].unlink()
            return
        else:
            assert pending == ()

        _commit_related_state_witness_v1(scope_seed, parent=parent)
        assert _read_related_state_witness_v1(scope_seed) == "COMMITTED"
        assert not any(".tmp-" in entry.name for entry in parent.root.iterdir())
    finally:
        if not parent._closed:
            try:
                parent.close()
            except GoogleWorkspaceHostV1UnknownOutcome:
                if not restart_expected:
                    raise


@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows close gate")
def test_persistent_open_temp_requires_process_restart_then_cleans_and_proceeds(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    runtime = tmp_path / "runtime"
    child = r"""
import json
import os
import sys
from pathlib import Path
import core.google_workspace_host_v1 as host

runtime = Path(sys.argv[1])
scope_seed = sys.argv[2]
host.private_control_plane_runtime_dir = lambda: runtime
parent = host._validated_metadata_parent_v1()
host._prepare_related_state_witness_v1(scope_seed, parent=parent)
real_close = os.close
calls = 0
def fail_close(descriptor):
    global calls
    calls += 1
    raise OSError(5, "persistent close failure")
host.os.close = fail_close
try:
    host._commit_related_state_witness_v1(scope_seed, parent=parent)
except host.GoogleWorkspaceHostV1UnknownOutcome:
    pass
else:
    raise AssertionError("close failure was not surfaced")
try:
    parent.close()
except host.GoogleWorkspaceHostV1UnknownOutcome:
    pass
else:
    raise AssertionError("restart requirement was not surfaced")
host.os.close = real_close
pending = [entry.name for entry in parent.root.iterdir() if ".tmp-" in entry.name]
print(json.dumps({"calls": calls, "closed": parent._closed, "pending": pending}))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", child, str(runtime), scope_seed],
        cwd=os.getcwd(),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    observed = json.loads(result.stdout.strip().splitlines()[-1])
    assert observed == {
        "calls": 1,
        "closed": True,
        "pending": observed["pending"],
    }
    assert len(observed["pending"]) == 1
    assert _read_related_state_witness_v1(scope_seed) == "PREPARED"

    retry_parent = _validated_metadata_parent_v1()
    try:
        assert not any(".tmp-" in entry.name for entry in retry_parent.root.iterdir())
        _commit_related_state_witness_v1(scope_seed, parent=retry_parent)
        assert _read_related_state_witness_v1(scope_seed) == "COMMITTED"
    finally:
        retry_parent.close()


def test_temp_close_same_path_same_inode_reuse_survives_parent_close(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    parent = _validated_metadata_parent_v1()
    replacement_descriptor = None
    replacement_path = None
    original_identity = None
    real_close = os.close
    real_open = os.open
    try:
        _prepare_related_state_witness_v1(scope_seed, parent=parent)

        def close_then_reopen_same_path(descriptor):
            nonlocal replacement_descriptor, replacement_path, original_identity
            original_identity = os.fstat(descriptor)
            replacement_path = next(
                entry for entry in parent.root.iterdir() if ".tmp-" in entry.name
            )
            real_close(descriptor)
            replacement_descriptor = real_open(replacement_path, os.O_WRONLY)
            assert replacement_descriptor == descriptor
            raise OSError(errno.EBADF, "injected same-path descriptor reuse")

        with monkeypatch.context() as injected:
            injected.setattr(
                "core.google_workspace_host_v1.os.close",
                close_then_reopen_same_path,
            )
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                _commit_related_state_witness_v1(scope_seed, parent=parent)

        assert replacement_descriptor is not None
        current = os.fstat(replacement_descriptor)
        assert (current.st_dev, current.st_ino) == (
            original_identity.st_dev,
            original_identity.st_ino,
        )
        assert parent._pending_external_witness_temps == [replacement_path]
        assert _read_related_state_witness_v1(scope_seed) == "PREPARED"
        with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
            parent.close()
        assert parent._closed is True
        assert os.fstat(replacement_descriptor).st_ino == current.st_ino
    finally:
        if replacement_descriptor is not None:
            real_close(replacement_descriptor)
        if replacement_path is not None and replacement_path.exists():
            replacement_path.unlink()
        if not parent._closed:
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                parent.close()


def test_temp_close_different_inode_reuse_survives_parent_close(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    parent = _validated_metadata_parent_v1()
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"replacement")
    replacement_descriptor = None
    real_close = os.close
    real_open = os.open
    try:
        _prepare_related_state_witness_v1(scope_seed, parent=parent)

        def close_then_reuse(descriptor):
            nonlocal replacement_descriptor
            real_close(descriptor)
            replacement_descriptor = real_open(replacement, os.O_RDONLY)
            assert replacement_descriptor == descriptor
            raise OSError(errno.EBADF, "injected reused descriptor")

        with monkeypatch.context() as injected:
            injected.setattr(
                "core.google_workspace_host_v1.os.close", close_then_reuse
            )
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                _commit_related_state_witness_v1(scope_seed, parent=parent)

        assert replacement_descriptor is not None
        assert os.fstat(replacement_descriptor).st_size == len(b"replacement")
        assert len(parent._pending_external_witness_temps) == 1
        assert _read_related_state_witness_v1(scope_seed) == "PREPARED"
        with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
            parent.close()
        assert parent._closed is True
        assert os.fstat(replacement_descriptor).st_size == len(b"replacement")
    finally:
        if replacement_descriptor is not None:
            real_close(replacement_descriptor)
        for entry in parent.root.iterdir():
            if ".tmp-" in entry.name:
                entry.unlink()
        if not parent._closed:
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                parent.close()


@pytest.mark.skipif(os.name == "nt", reason="native POSIX dirfd close gate open")
def test_posix_dirfd_same_directory_reuse_is_never_closed_twice(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    parent = _validated_metadata_parent_v1()
    original = parent._dirfd
    replacement = None
    real_close = os.close
    real_open = os.open

    def close_then_reopen_directory(descriptor):
        nonlocal replacement
        assert descriptor == original
        real_close(descriptor)
        replacement = real_open(
            parent.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        assert replacement == descriptor
        raise OSError(errno.EINTR, "injected ambiguous dirfd close")

    with monkeypatch.context() as injected:
        injected.setattr(
            "core.google_workspace_host_v1.os.close",
            close_then_reopen_directory,
        )
        with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
            parent.close()
    try:
        assert parent._closed is True
        assert parent._dirfd is None
        assert os.fstat(replacement).st_ino == parent.identity[1]
        with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
            parent.close()
        assert os.fstat(replacement).st_ino == parent.identity[1]
    finally:
        if replacement is not None:
            real_close(replacement)


def test_new_parent_removes_managed_temp_left_by_process_restart(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    parent = _validated_metadata_parent_v1()
    root = parent.root
    parent.close()
    orphan = root / (
        f".authority-{scope_seed}.state.tmp-" + "a" * 32
    )
    orphan.write_bytes(b"incomplete")
    assert orphan.is_file()

    restarted = _validated_metadata_parent_v1()
    try:
        assert not orphan.exists()
    finally:
        restarted.close()


def test_initial_prepared_atomic_failure_leaves_no_malformed_target_and_retries(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    witness = _related_state_witness_path(scope_seed)
    parent = _validated_metadata_parent_v1()
    try:
        with monkeypatch.context() as injected:
            injected.setattr(
                "core.google_workspace_host_v1._before_external_witness_replace_v1",
                lambda: (_ for _ in ()).throw(
                    OSError("injected before-replace failure")
                ),
            )
            with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
                _prepare_related_state_witness_v1(scope_seed, parent=parent)

        assert _read_related_state_witness_v1(scope_seed) is None
        assert not witness.exists()
        assert not any(".tmp-" in entry.name for entry in parent.root.iterdir())
        assert _prepare_related_state_witness_v1(
            scope_seed, parent=parent
        ) == ("PREPARED", True)
        assert _read_related_state_witness_v1(scope_seed) == "PREPARED"
    finally:
        parent.close()


@pytest.mark.parametrize("state", ("PREPARED", "COMMITTED"))
def test_external_witness_any_state_denies_after_all_vault_authority_deleted(
    state, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    factory = FakeVaultFactory()
    lease = FakeLease()
    selected = _create_google_workspace_host_parts_for_test_v1(
        config(), lease=lease, vault_factory=factory
    )
    parent = _validated_metadata_parent_v1()
    try:
        _prepare_related_state_witness_v1(selected.root.scope_seed, parent=parent)
        if state == "COMMITTED":
            _commit_related_state_witness_v1(
                selected.root.scope_seed, parent=parent
            )
        for key in tuple(factory.values):
            if key[0].endswith(
                (".Root.v1", ".RootMarker.v1", ".StateWitness.v1")
            ):
                factory.values.pop(key)
        with pytest.raises(GoogleWorkspaceHostV1Denied):
            selected.root.provision()
    finally:
        parent.close()


def test_prepared_witness_never_enters_production_factory_or_status(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "core.google_workspace_host_v1.private_control_plane_runtime_dir",
        lambda: tmp_path / "runtime",
    )
    scope_seed = _scope_seed(config().binding)
    parent = _validated_metadata_parent_v1()
    try:
        _prepare_related_state_witness_v1(scope_seed, parent=parent)
    finally:
        parent.close()

    class LeaseProbe:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    probe = LeaseProbe()
    monkeypatch.setattr(
        "core.google_workspace_host_v1.NativeGoogleHostLeaseV1",
        lambda: probe,
    )
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        create_google_workspace_host_service_v1(
            gate=GoogleWorkspaceFeatureGateV1(True), configuration=config()
        )
    assert probe.closed is True
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        read_google_workspace_host_status_v1(config())


def test_authorization_start_and_callback_repr_never_expose_secrets():
    start = GoogleAuthorizationStartV1(
        "https://example.invalid/auth?state=secret-state&code_challenge=secret",
        NOW + 60,
        "1" * 64,
        READ_SCOPES,
    )
    callback_type = __import__(
        "core.google_workspace_host_v1", fromlist=["GoogleLoopbackCallbackV1"]
    ).GoogleLoopbackCallbackV1
    callback_value = callback_type(
        "http://127.0.0.1:43871/oauth2/callback?code=secret-code&state=secret-state"
    )
    assert "secret" not in repr(start)
    assert "secret" not in repr(callback_value)


def test_configuration_is_create_once_and_authenticated():
    selected, factory, _ = parts()
    assert selected.configuration.configure(config()) is True
    assert selected.configuration.configure(config()) is False
    different = config(43872)
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        selected.configuration.configure(different)
    manifest_key = next(
        key for key in factory.values if key[0].endswith(".config") and ".c." not in key[1]
    )
    manifest = json.loads(factory.values[manifest_key])
    manifest["chunks"] = manifest["chunks"] + 1
    factory.values[manifest_key] = json.dumps(manifest).encode()
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        selected.configuration.load()


@pytest.mark.parametrize("account_fragment", (".c.", "b-"))
def test_interrupted_chunk_or_manifest_publish_recovers_without_orphans(
    account_fragment,
):
    selected, factory, _ = fault_parts()
    if account_fragment == ".c.":
        factory.failures["once"] = ("set", ".c.")
    else:
        factory.failures["once"] = ("set", "b-")
    with pytest.raises(
        __import__(
            "core.google_workspace_host_v1",
            fromlist=["GoogleWorkspaceHostV1UnknownOutcome"],
        ).GoogleWorkspaceHostV1UnknownOutcome
    ):
        selected.configuration.configure(config())
    assert selected.configuration.load() is None
    assert not any(account.endswith(".txn") for _, account in factory.values)
    assert not any(".c." in account for _, account in factory.values)


def test_post_manifest_readback_fault_recovers_published_record():
    selected, factory, _ = fault_parts()
    original = factory.__call__
    manifest_sets = 0

    class ReadbackFaultVault(FaultOnceVault):
        def set_bytes(self, value):
            nonlocal manifest_sets
            super().set_bytes(value)
            if self.reference.account.startswith("b-") and ".c." not in self.reference.account and not self.reference.account.endswith(".txn"):
                manifest_sets += 1
                if manifest_sets == 1:
                    factory.failures["once"] = ("get", self.reference.account)

    def factory_call(reference):
        factory.references.append(reference)
        return ReadbackFaultVault(factory.values, reference, factory.failures)

    factory.__call__ = original
    # Special methods are resolved on the class, so pass the explicit callable seam.
    selected = _create_google_workspace_host_parts_for_test_v1(
        config(), lease=FakeLease(), vault_factory=factory_call
    )
    with pytest.raises(
        __import__(
            "core.google_workspace_host_v1",
            fromlist=["GoogleWorkspaceHostV1UnknownOutcome"],
        ).GoogleWorkspaceHostV1UnknownOutcome
    ):
        selected.configuration.configure(config())
    assert selected.configuration.load() == config()


def test_token_vault_supports_large_exact_connector_bundle_cas_and_delete():
    selected, _, _ = parts()
    token = GoogleTokenBundleV1(
        selected.binding_digest,
        "a" * 16_384,
        "r" * 16_384,
        NOW + 3600,
        READ_SCOPES,
        1,
    )
    assert selected.token.compare_and_set(selected.binding_digest, None, token) is True
    observed = selected.token.resolve(selected.binding_digest)
    assert observed is not None and observed.digest == token.digest
    newer = GoogleTokenBundleV1(
        selected.binding_digest, "new-access", "new-refresh", NOW + 7200,
        READ_SCOPES, 2,
    )
    assert selected.token.compare_and_set(selected.binding_digest, "0" * 64, newer) is False
    assert selected.token.compare_and_set(selected.binding_digest, token.digest, newer) is True
    assert selected.token.delete(selected.binding_digest, token.digest) is False
    assert selected.token.delete(selected.binding_digest, newer.digest) is True
    assert selected.token.resolve(selected.binding_digest) is None


@pytest.mark.parametrize(
    "contents",
    (
        "a" * 16_384,
        ('"\\\n\t\r\x00' * 2730) + '"\\\n\t',
        "é" * 8_192,
    ),
    ids=("ascii", "controls", "unicode"),
)
def test_token_vault_round_trips_exact_utf8_budget_for_arbitrary_contents(contents):
    assert len(contents.encode("utf-8")) == 16_384
    selected, _, _ = parts()
    token = GoogleTokenBundleV1(
        selected.binding_digest, contents, contents, NOW + 3600, READ_SCOPES, 1
    )
    assert selected.token.compare_and_set(selected.binding_digest, None, token)
    assert selected.token.resolve(selected.binding_digest) == token


@pytest.mark.parametrize(
    ("operation", "fragment", "deleted"),
    (
        ("set", ".txn", False),
        ("delete", "b-", True),
        ("delete", ".c.", True),
        ("delete", ".txn", True),
    ),
)
def test_authenticated_delete_tombstone_recovers_every_interruption(
    operation, fragment, deleted
):
    selected, factory, _ = fault_parts()
    token = GoogleTokenBundleV1(
        selected.binding_digest, "access", "refresh", NOW + 3600, READ_SCOPES, 1
    )
    assert selected.token.compare_and_set(selected.binding_digest, None, token)
    factory.failures["once"] = (operation, fragment)
    with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
        selected.token.delete(selected.binding_digest, token.digest)
    observed = selected.token.resolve(selected.binding_digest)
    assert (observed is None) is deleted
    assert not any(account.endswith(".txn") for _, account in factory.values)
    if deleted:
        assert not any(
            service.endswith(".token") and (account.startswith("b-") or ".c." in account)
            for service, account in factory.values
        )


def test_oversized_token_and_pending_inputs_fail_before_vault_mutation():
    selected, factory, _ = parts()
    snapshot = dict(factory.values)
    with pytest.raises(Exception):
        GoogleTokenBundleV1(
            selected.binding_digest, "a" * 16_385, "refresh", NOW + 3600,
            READ_SCOPES, 1,
        )
    with pytest.raises(Exception):
        GooglePendingAuthorizationV1(
            selected.binding_digest, "s" * 257, "v" * 64,
            config().redirect_uri, NOW + 600, READ_SCOPES,
        )
    assert factory.values == snapshot


def test_copied_token_record_is_rejected_by_binding_authenticator():
    first, factory, lease = parts()
    token = GoogleTokenBundleV1(
        first.binding_digest, "access", "refresh", NOW + 3600, READ_SCOPES, 1
    )
    first.token.compare_and_set(first.binding_digest, None, token)
    second_config = GoogleWorkspaceHostConfigurationV1(
        GoogleWorkspaceBindingV1("owner-2", "workspace-2", "other@example.com"),
        config().client_id,
        config().callback_port,
    )
    second = _create_google_workspace_host_parts_for_test_v1(
        second_config, lease=lease, vault_factory=factory
    )
    second_manifest_key = next(
        key for key in factory.values
        if key[0].endswith(".token") and key[1].startswith("b-" + first.binding_digest[:48])
        and ".c." not in key[1]
    )
    copied = factory.values[second_manifest_key]
    target_alias = "b-" + second.binding_digest[:48]
    factory.values[(second_manifest_key[0], target_alias)] = copied
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        second.token.resolve(second.binding_digest)


def test_pending_is_single_consume_and_never_exposes_state_in_aliases():
    selected, factory, _ = parts()
    state = "provider-secret-state"
    state_digest = __import__("hashlib").sha256(state.encode()).hexdigest()
    pending = GooglePendingAuthorizationV1(
        selected.binding_digest, state, "v" * 64, config().redirect_uri,
        NOW + 600, READ_SCOPES,
    )
    selected.pending.store(state_digest, pending)
    aliases = " ".join(reference.account for reference in factory.references)
    assert state not in aliases
    assert state_digest not in aliases
    assert selected.pending.consume(state_digest) == pending
    assert selected.pending.consume(state_digest) is None


def test_expired_pending_marker_is_tombstoned_before_new_connection_marker():
    selected, factory, _ = parts()
    old_state = "1" * 64
    new_state = "2" * 64
    selected.pending.mark_active(old_state, NOW + 10, now_epoch_s=NOW)
    assert selected.pending.is_active(NOW + 5)
    selected.pending.mark_active(
        new_state, NOW + 700, now_epoch_s=NOW + 20
    )
    assert selected.pending.is_active(NOW + 20)
    selected.pending.clear_active(new_state)
    assert not selected.pending.is_active(NOW + 20)
    assert not any(account.endswith(".txn") for _, account in factory.values)


def test_anchor_cas_is_monotonic_and_cross_store_bound():
    selected, _, _ = parts()
    store = "1" * 64
    assert selected.anchor.read(store) is None
    assert selected.anchor.compare_and_swap(store, None, 0) is True
    assert selected.anchor.compare_and_swap(store, None, 0) is False
    assert selected.anchor.compare_and_swap(store, 0, 1) is True
    assert selected.anchor.read(store) == 1
    with pytest.raises(GoogleWorkspaceHostV1ContractError):
        selected.anchor.compare_and_swap(store, 1, 3)
    assert selected.anchor.read("2" * 64) is None


def test_concurrent_anchor_and_token_cas_have_one_winner():
    selected, _, _ = parts()
    store = "3" * 64
    assert selected.anchor.compare_and_swap(store, None, 0)
    anchor_results = []

    def advance():
        anchor_results.append(selected.anchor.compare_and_swap(store, 0, 1))

    threads = [threading.Thread(target=advance) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert anchor_results.count(True) == 1
    assert anchor_results.count(False) == 7


def test_concurrent_configuration_is_linearized_and_never_overwritten():
    selected, _, _ = parts()
    results = []
    errors = []

    def configure():
        try:
            results.append(selected.configuration.configure(config()))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=configure) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert selected.configuration.load() == config()


def test_vault_failure_traceback_is_fixed_and_secret_free():
    selected, factory, _ = parts()
    selected.configuration.configure(config())
    config_record = next(
        reference for reference in factory.references
        if reference.service.endswith(".config") and ".c." not in reference.account
    )
    factory.failures.add((config_record.service, config_record.account, "get"))
    try:
        selected.configuration.load()
    except Exception as exc:
        rendered = "".join(traceback.format_exception(exc))
        assert exc.__cause__ is None
        assert exc.__context__ is None
        assert "secret-value-was-here" not in rendered
        assert "sir@example.com" not in rendered
    else:
        pytest.fail("expected fixed public failure")


def _free_port():
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _send_callback(port, target, *, method="GET", host=None):
    deadline = time.monotonic() + 2
    while True:
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    with client:
        request = (
            f"{method} {target} HTTP/1.1\r\n"
            f"Host: {host or f'127.0.0.1:{port}'}\r\nConnection: close\r\n\r\n"
        ).encode("ascii")
        client.sendall(request)
        return client.recv(4096)


def _send_raw(port, request):
    deadline = time.monotonic() + 2
    while True:
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=1)
            break
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    with client:
        client.sendall(request)
        try:
            return client.recv(4096)
        except OSError:
            return b""


def test_loopback_accepts_one_exact_request_and_closes_listener():
    port = _free_port()
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback",
        epoch_clock=lambda: NOW,
    )
    result = []
    worker = threading.Thread(
        target=lambda: result.append(
            receiver.receive(
                "https://accounts.google.com/o/oauth2/v2/auth",
                expires_at_epoch_s=NOW + 30,
                browser_open=lambda _url: True,
            )
        )
    )
    worker.start()
    response_bytes = _send_callback(port, "/oauth2/callback?code=abc&state=def")
    worker.join(3)
    assert not worker.is_alive()
    assert response_bytes.startswith(b"HTTP/1.1 200")
    assert b"Cache-Control: no-store" in response_bytes
    assert result[0].callback_uri.endswith("code=abc&state=def")
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.1)


@pytest.mark.parametrize(
    ("method", "target", "host"),
    (
        ("POST", "/oauth2/callback?code=a&state=b", None),
        ("GET", "/wrong?code=a&state=b", None),
        ("GET", "/oauth2/callback?code=a&state=b&state=c", None),
        ("GET", "/oauth2/callback?code=a&state=b", "localhost:1234"),
        ("GET", "/oauth2/callback?code=a&error=x&state=b", None),
    ),
)
def test_loopback_rejects_method_path_duplicate_host_and_forbidden_fields(
    method, target, host
):
    port = _free_port()
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback", epoch_clock=lambda: NOW
    )
    errors = []

    def run():
        try:
            receiver.receive(
                "https://accounts.google.com/o/oauth2/v2/auth",
                expires_at_epoch_s=NOW + 30,
                browser_open=lambda _url: True,
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    _send_callback(port, target, method=method, host=host)
    worker.join(3)
    assert not worker.is_alive()
    assert type(errors[0]) is GoogleWorkspaceHostV1Denied


def test_loopback_deadline_and_cancel_do_not_open_provider_transport():
    receiver = GoogleOAuthLoopbackReceiverV1(
        "http://127.0.0.1:43871/oauth2/callback", epoch_clock=lambda: NOW
    )
    opened = []
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        receiver.receive(
            "https://accounts.google.com/o/oauth2/v2/auth",
            expires_at_epoch_s=NOW,
            browser_open=lambda url: opened.append(url) or True,
        )
    assert opened == []


@pytest.mark.parametrize(
    "raw_request",
    (
        b"GET /oauth2/callback?code=" + b"a" * 5000 + b"&state=b HTTP/1.1\r\nHost: 127.0.0.1:PORT\r\n\r\n",
        b"GET /oauth2/callback?code=a&state=b HTTP/1.1\r\nHost: 127.0.0.1:PORT\r\nX-Large: " + b"a" * 13000 + b"\r\n\r\n",
        b"GET /oauth2/callback?code=a&state=b HTTP/1.1\r\nHost: 127.0.0.1:PORT\r\nContent-Length: 1\r\n\r\nx",
    ),
)
def test_loopback_separately_bounds_request_headers_and_rejects_body(raw_request):
    port = _free_port()
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback", epoch_clock=lambda: NOW
    )
    errors = []

    def run():
        try:
            receiver.receive(
                "https://accounts.google.com/o/oauth2/v2/auth",
                expires_at_epoch_s=NOW + 30,
                browser_open=lambda _url: True,
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    _send_raw(port, raw_request.replace(b"PORT", str(port).encode("ascii")))
    worker.join(3)
    assert not worker.is_alive()
    assert type(errors[0]) is GoogleWorkspaceHostV1Denied
    assert errors[0].__cause__ is None and errors[0].__context__ is None


def test_loopback_slowloris_obeys_absolute_deadline_and_cleans_socket():
    port = _free_port()
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback", epoch_clock=lambda: NOW
    )
    errors = []
    def capture():
        try:
            receiver.receive(
                "https://accounts.google.com/o/oauth2/v2/auth",
                expires_at_epoch_s=NOW + 1,
                browser_open=lambda _url: True,
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=capture)
    worker.start()
    client = None
    deadline = time.monotonic() + 2
    while client is None:
        try:
            client = socket.create_connection(("127.0.0.1", port), timeout=1)
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.01)
    with client:
        client.sendall(b"GET /oauth2/callback?")
        worker.join(3)
    assert not worker.is_alive()
    assert type(errors[0]) is GoogleWorkspaceHostV1Denied
    assert "deadline" in str(errors[0])


def test_loopback_bind_failure_never_opens_browser_and_is_redacted():
    port = _free_port()
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    opened = []
    secret = "provider-" + "secret"
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback", epoch_clock=lambda: NOW
    )
    try:
        with pytest.raises(GoogleWorkspaceHostV1Denied) as raised:
            receiver.receive(
                "https://example.invalid/?secret=" + secret,
                expires_at_epoch_s=NOW + 30,
                browser_open=lambda url: opened.append(url) or True,
            )
    finally:
        blocker.close()
    assert opened == []
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(raised.value))


def test_loopback_release_failure_is_unknown_and_cause_free():
    class CloseFailSocket:
        def __init__(self):
            self.bind_detail = "secret-" + "bind-detail"
            self.close_detail = "secret-" + "close-detail"

        def setsockopt(self, *_args):
            return None

        def bind(self, *_args):
            raise OSError(self.bind_detail)

        def close(self):
            raise OSError(self.close_detail)

    receiver = GoogleOAuthLoopbackReceiverV1(
        "http://127.0.0.1:43871/oauth2/callback",
        epoch_clock=lambda: NOW,
        socket_factory=lambda *_args: CloseFailSocket(),
    )
    unknown_type = __import__(
        "core.google_workspace_host_v1",
        fromlist=["GoogleWorkspaceHostV1UnknownOutcome"],
    ).GoogleWorkspaceHostV1UnknownOutcome
    with pytest.raises(unknown_type) as raised:
        receiver.receive(
            "https://example.invalid/", expires_at_epoch_s=NOW + 30,
            browser_open=lambda _url: True,
        )
    assert raised.value.__cause__ is None and raised.value.__context__ is None
    rendered = "".join(traceback.format_exception(raised.value))
    assert "secret-bind-detail" not in rendered
    assert "secret-close-detail" not in rendered


def test_loopback_real_listener_close_failure_retains_resource_for_retry():
    port = _free_port()

    class FailOnceRealSocket:
        def __init__(self, *args):
            self.inner = socket.socket(*args)
            self.close_calls = 0

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("private-close-once")
            self.inner.close()

    listener = FailOnceRealSocket(socket.AF_INET, socket.SOCK_STREAM)
    receiver = GoogleOAuthLoopbackReceiverV1(
        f"http://127.0.0.1:{port}/oauth2/callback",
        epoch_clock=lambda: NOW,
        socket_factory=lambda *_args: listener,
    )
    errors = []

    def receive():
        try:
            receiver.receive(
                "https://accounts.google.com/o/oauth2/v2/auth",
                expires_at_epoch_s=NOW + 30,
                browser_open=lambda _url: True,
            )
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=receive)
    worker.start()
    response_bytes = _send_callback(port, "/oauth2/callback?code=a&state=b")
    worker.join(3)
    assert response_bytes.startswith(b"HTTP/1.1 200")
    assert type(errors[0]) is GoogleWorkspaceHostV1UnknownOutcome
    assert receiver._lifecycle == "closing"
    assert receiver._listener is listener
    assert listener.inner.fileno() >= 0
    receiver.close()
    assert receiver._lifecycle == "closed"
    assert receiver._listener is None
    assert listener.inner.fileno() == -1


class CallbackReceiver:
    def __init__(self, configuration):
        self.configuration = configuration

    def receive(self, authorization_url, *, expires_at_epoch_s, browser_open):
        query = parse_qs(urlsplit(authorization_url).query)
        callback = self.configuration.redirect_uri + "?" + urlencode(
            {"code": "provider-code", "state": query["state"][0]}
        )
        return type("Callback", (), {"callback_uri": callback})()


class BlockingDeniedReceiver:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()

    def receive(self, authorization_url, *, expires_at_epoch_s, browser_open):
        del authorization_url, expires_at_epoch_s, browser_open
        self.started.set()
        self.release.wait(5)
        raise GoogleWorkspaceHostV1Denied("OAuth callback cancelled")

    def close(self):
        self.release.set()


class RetryCloseReceiver(CallbackReceiver):
    def __init__(self, configuration):
        super().__init__(configuration)
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("private-receiver-close")


class RetryCloseLease(FakeLease):
    def __init__(self):
        super().__init__()
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("private-lease-close")


class RetryCloseParent:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1
        if self.close_calls == 1:
            raise RuntimeError("private-parent-close")


def test_host_service_connect_status_gmail_and_calendar_use_connector_contracts():
    selected_config = config()
    transport = Http(
        (
            response(
                OAUTH_ORIGIN,
                TOKEN_PATH,
                {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_in": 3600,
                    "scope": " ".join(READ_SCOPES),
                    "token_type": "Bearer",
                },
            ),
            response(GMAIL_ORIGIN, GMAIL_PROFILE_PATH, {"emailAddress": "sir@example.com"}),
            response(GMAIL_ORIGIN, "/gmail/v1/users/me/messages", {"messages": []}),
            response("https://www.googleapis.com", "/calendar/v3/calendars/primary/events", {"items": []}),
        )
    )
    factory = FakeVaultFactory()
    lease = FakeLease()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True),
        configuration=selected_config,
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(),
        transport=transport,
        receiver=CallbackReceiver(selected_config),
        browser_open=lambda _url: True,
        lease=lease,
        vault_factory=factory,
        epoch_clock=lambda: NOW,
    )
    assert service is not None
    receipt = service.connect()
    assert receipt.status == "connected"
    assert service.status().connected is True
    assert service.status().trust_limit == "cooperating-process-cas-only"
    assert service.test_gmail().items == ()
    assert service.test_calendar(
        time_min="2033-05-18T00:00:00Z",
        time_max="2033-05-19T00:00:00Z",
    ).items == ()
    assert all(request.method in {"GET", "POST"} for request in transport.requests)


def test_status_only_read_does_not_acquire_held_operation_lease():
    selected, factory, lease = parts()
    selected.configuration.configure(config())
    selected.pending.mark_active("3" * 64, NOW + 600, now_epoch_s=NOW)
    result = []
    finished = threading.Event()

    def read_status():
        result.append(
            read_google_workspace_host_status_v1(
                config(), epoch_clock=lambda: NOW, vault_factory=factory
            )
        )
        finished.set()

    with lease.hold(selected.root.scope, timeout_seconds=1):
        worker = threading.Thread(target=read_status)
        worker.start()
        assert finished.wait(1)
    worker.join(2)
    assert result[0].pending_loopback is True
    selected.pending.clear_active("3" * 64)


@pytest.mark.skipif(platform.system() != "Windows", reason="native Windows CLI host evidence only")
def test_spawned_cli_observes_pending_while_parent_service_holds_native_lease():
    unique = __import__("secrets").token_hex(8)
    selected_config = GoogleWorkspaceHostConfigurationV1(
        GoogleWorkspaceBindingV1(
            f"owner-{unique}", f"workspace-{unique}", f"{unique}@example.com"
        ),
        f"onyx-{unique}.apps.googleusercontent.com",
        43871,
    )
    references = []

    def tracking_factory(reference):
        references.append(reference)
        return native_vault.NativeSecretVault(reference)

    receiver = BlockingDeniedReceiver()
    lease = NativeGoogleHostLeaseV1()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=selected_config,
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=Http(()),
        receiver=receiver, browser_open=lambda _url: True,
        lease=lease, vault_factory=tracking_factory, epoch_clock=lambda: NOW,
    )
    assert service is not None
    scope_seed = _scope_seed(selected_config.binding)
    _write_related_state_witness_v1(scope_seed)
    failures = []

    def connect():
        try:
            service.connect()
        except Exception as exc:
            failures.append(exc)

    arguments = [
        sys.executable,
        "-B",
        "scripts/onyx_google_workspace.py",
        "status", "--enabled",
        "--owner-id", selected_config.binding.owner_id,
        "--workspace-id", selected_config.binding.workspace_id,
        "--account-id", selected_config.binding.account_id,
        "--client-id", selected_config.client_id,
        "--callback-port", str(selected_config.callback_port),
        "--json",
    ]
    worker = threading.Thread(target=connect)
    worker.start()
    try:
        assert receiver.started.wait(3)
        active = subprocess.run(
            arguments, cwd=str(__import__("pathlib").Path(__file__).parents[1]),
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert active.returncode == 0, active.stderr
        assert json.loads(active.stdout)["result"]["pending_loopback"] is True
        receiver.release.set()
        worker.join(5)
        assert not worker.is_alive()
        cleared = subprocess.run(
            arguments, cwd=str(__import__("pathlib").Path(__file__).parents[1]),
            capture_output=True, text=True, timeout=10, check=False,
        )
        assert cleared.returncode == 0, cleared.stderr
        assert json.loads(cleared.stdout)["result"]["pending_loopback"] is False
        assert len(failures) == 1
    finally:
        receiver.release.set()
        worker.join(5)
        service.close()
        witness_path = _related_state_witness_path(scope_seed)
        if witness_path.exists():
            witness_path.unlink()
        unique_references = {
            (reference.service, reference.account): reference
            for reference in references
        }
        for reference in unique_references.values():
            vault = native_vault.NativeSecretVault(reference)
            vault.delete()
            assert vault.get_bytes() is None


def test_concurrent_connect_and_disconnect_are_serialized_without_duplicate_provider_attempts():
    transport = RoutingHttp()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=transport,
        receiver=CallbackReceiver(config()), browser_open=lambda _url: True,
        lease=FakeLease(), vault_factory=FakeVaultFactory(), epoch_clock=lambda: NOW,
    )
    connect_results = []

    def connect():
        try:
            connect_results.append(service.connect().status)
        except Exception as exc:
            connect_results.append(type(exc).__name__)

    threads = [threading.Thread(target=connect) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert connect_results.count("connected") == 1
    assert connect_results.count("GoogleWorkspaceV1Denied") == 1
    assert sum(request.path == TOKEN_PATH for request in transport.requests) == 1

    disconnect_results = []

    def disconnect():
        try:
            disconnect_results.append(service.disconnect().status)
        except Exception as exc:
            disconnect_results.append(type(exc).__name__)

    threads = [threading.Thread(target=disconnect) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert disconnect_results.count("revoked") == 1
    assert disconnect_results.count("GoogleWorkspaceV1Denied") == 1
    assert sum(request.path == "/revoke" for request in transport.requests) == 1


def test_distinct_services_share_host_lease_and_revoke_exactly_once():
    transport = RoutingHttp()
    lease = FakeLease()
    factory = FakeVaultFactory()
    metadata = InMemoryGoogleGrantMetadataStoreV1()

    def service():
        return _create_google_workspace_host_service_for_test_v1(
            gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
            metadata_store=metadata, transport=transport,
            receiver=CallbackReceiver(config()), browser_open=lambda _url: True,
            lease=lease, vault_factory=factory, epoch_clock=lambda: NOW,
        )

    first = service()
    second = service()
    assert first is not None and second is not None
    assert first.connect().status == "connected"
    outcomes = []

    def revoke(selected):
        try:
            outcomes.append(selected.disconnect().status)
        except Exception as exc:
            outcomes.append(type(exc).__name__)

    workers = [threading.Thread(target=revoke, args=(value,)) for value in (first, second)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(3)
    assert all(not worker.is_alive() for worker in workers)
    assert outcomes.count("revoked") == 1
    assert outcomes.count("GoogleWorkspaceV1Denied") == 1
    assert sum(request.path == "/revoke" for request in transport.requests) == 1


def test_operation_release_failures_are_typed_and_never_mask_primary():
    lease = ReleaseFaultLease()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=Http(()),
        receiver=CallbackReceiver(config()), browser_open=lambda _url: True,
        lease=lease, vault_factory=FakeVaultFactory(), epoch_clock=lambda: NOW,
    )
    assert service is not None
    lease.fail_release = True
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        with service._operation():
            pass
    lease.fail_release = True
    with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
        with service._operation() as operation:
            operation.mutation_possible = True

    class PrimaryFailure(Exception):
        pass

    lease.fail_release = True
    with pytest.raises(PrimaryFailure):
        with service._operation() as operation:
            operation.mutation_possible = True
            raise PrimaryFailure("primary")


def test_wrong_account_after_provider_attempt_is_not_retried():
    selected_config = config()
    transport = Http(
        (
            response(
                OAUTH_ORIGIN, TOKEN_PATH,
                {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
                 "scope": " ".join(READ_SCOPES), "token_type": "Bearer"},
            ),
            response(GMAIL_ORIGIN, GMAIL_PROFILE_PATH, {"emailAddress": "wrong@example.com"}),
            response(OAUTH_ORIGIN, "/revoke", {}),
        )
    )
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=selected_config,
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=transport,
        receiver=CallbackReceiver(selected_config), browser_open=lambda _url: True,
        lease=FakeLease(), vault_factory=FakeVaultFactory(), epoch_clock=lambda: NOW,
    )
    with pytest.raises(GoogleWorkspaceV1Denied):
        service.connect()
    assert len(transport.requests) == 3


def test_pending_loopback_status_cleanup_cancel_and_idempotent_service_close():
    receiver = BlockingDeniedReceiver()
    factory = FakeVaultFactory()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=Http(()),
        receiver=receiver, browser_open=lambda _url: True,
        lease=FakeLease(), vault_factory=factory, epoch_clock=lambda: NOW,
    )
    errors = []

    def connect():
        try:
            service.connect()
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=connect)
    worker.start()
    assert receiver.started.wait(2)
    assert service.status().pending_loopback is True
    receiver.release.set()
    worker.join(3)
    assert not worker.is_alive()
    assert type(errors[0]) is GoogleWorkspaceHostV1Denied
    assert service.status().pending_loopback is False
    assert not any(
        service_name.endswith(".pending") for service_name, _account in factory.values
    )
    service.close()
    service.close()
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        service.status()


def test_pending_marker_is_visible_to_sibling_service_and_close_waits_cleanup():
    receiver = BlockingDeniedReceiver()
    factory = FakeVaultFactory()
    lease = FakeLease()
    metadata = InMemoryGoogleGrantMetadataStoreV1()
    first = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=metadata, transport=Http(()), receiver=receiver,
        browser_open=lambda _url: True, lease=lease, vault_factory=factory,
        epoch_clock=lambda: NOW,
    )
    sibling = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=metadata, transport=Http(()),
        receiver=CallbackReceiver(config()), browser_open=lambda _url: True,
        lease=lease, vault_factory=factory, epoch_clock=lambda: NOW,
    )
    assert first is not None and sibling is not None
    failures = []

    def connect():
        try:
            first.connect()
        except Exception as exc:
            failures.append(exc)

    worker = threading.Thread(target=connect)
    worker.start()
    assert receiver.started.wait(2)
    assert sibling.status().pending_loopback is True
    first.close()
    worker.join(3)
    assert not worker.is_alive()
    assert len(failures) == 1
    assert sibling.status().pending_loopback is False
    assert not any(
        service_name.endswith((".pending", ".pending-status"))
        for service_name, _account in factory.values
    )


def test_service_close_failure_stays_retryable_until_cleanup_and_lease_succeed():
    receiver = RetryCloseReceiver(config())
    lease = RetryCloseLease()
    parent = RetryCloseParent()
    service = _create_google_workspace_host_service_for_test_v1(
        gate=GoogleWorkspaceFeatureGateV1(True), configuration=config(),
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=Http(()),
        receiver=receiver, browser_open=lambda _url: True,
        lease=lease, vault_factory=FakeVaultFactory(), epoch_clock=lambda: NOW,
        parent_authority=parent,
    )
    assert service is not None
    with pytest.raises(GoogleWorkspaceHostV1UnknownOutcome):
        service.close()
    assert service._lifecycle == "closing"
    with pytest.raises(GoogleWorkspaceHostV1Denied):
        service.status()
    service.close()
    assert service._lifecycle == "closed"
    assert receiver.close_calls == 2
    assert lease.close_calls == 2
    assert parent.close_calls == 2


class CliService:
    def __init__(self):
        self.calls = []
        self.close_calls = 0
        self.receipt = __import__(
            "core.google_workspace_connector_v1", fromlist=["GoogleProviderReceiptV1"]
        ).GoogleProviderReceiptV1(
            "test", "complete", "1" * 64, "2" * 64, "3" * 64,
            "4" * 64, 0, 1,
        )

    def status(self):
        return __import__(
            "core.google_workspace_host_v1", fromlist=["GoogleWorkspaceHostStatusV1"]
        ).GoogleWorkspaceHostStatusV1(
            True, True, True, "source-vault", "1" * 64, 2, "available",
            READ_SCOPES, False, "connected",
        )

    def connect(self):
        self.calls.append("connect")
        return self.receipt

    def disconnect(self):
        self.calls.append("disconnect")
        return self.receipt

    def test_gmail(self):
        self.calls.append("gmail")
        return __import__(
            "core.google_workspace_connector_v1", fromlist=["GoogleReadResultV1"]
        ).GoogleReadResultV1((), False, self.receipt)

    def test_calendar(self, *, time_min, time_max):
        self.calls.append(("calendar", time_min, time_max))
        return __import__(
            "core.google_workspace_connector_v1", fromlist=["GoogleReadResultV1"]
        ).GoogleReadResultV1((), False, self.receipt)

    def close(self):
        self.close_calls += 1


def _cli_host_args(command):
    return [
        command,
        "--enabled",
        "--owner-id", "owner-1",
        "--workspace-id", "workspace-1",
        "--account-id", "sir@example.com",
        "--client-id", "onyx-desktop-client.apps.googleusercontent.com",
        "--callback-port", "43871",
        "--json",
    ]


def test_cli_disabled_status_is_json_provider_free_and_needs_no_identity():
    output = []
    calls = []
    exit_code = run_cli_v1(
        ["status", "--json"], output=output.append,
        _factory_port=lambda **kwargs: calls.append(kwargs),
    )
    assert exit_code == EXIT_OK
    value = json.loads(output[0])
    assert value["schema"] == "OnyxGoogleWorkspaceCliResult.v1"
    assert value["result"]["enabled"] is False
    assert calls == []
    assert "sir@example.com" not in output[0]


def test_cli_configure_is_redacted_and_idempotence_is_reported():
    output = []
    arguments = [value for value in _cli_host_args("connect") if value != "--enabled"]
    arguments[0] = "configure"
    exit_code = run_cli_v1(
        arguments, output=output.append, _configure_port=lambda _config: True
    )
    assert exit_code == EXIT_OK
    value = json.loads(output[0])
    assert value["result"] == {"configured": True, "created": True}
    assert "sir@example.com" not in output[0]
    assert "onyx-desktop-client" not in output[0]


@pytest.mark.parametrize(
    "command",
    ("status", "connect", "disconnect", "test-gmail", "test-calendar"),
)
def test_cli_commands_delegate_once_and_emit_only_redacted_results(command):
    service = CliService()
    output = []
    arguments = _cli_host_args(command)
    if command == "test-calendar":
        arguments.extend(
            ["--time-min", "2033-05-18T00:00:00Z", "--time-max", "2033-05-19T00:00:00Z"]
        )
    exit_code = run_cli_v1(
        arguments, output=output.append, _factory_port=lambda **_kwargs: service
    )
    assert exit_code == EXIT_OK
    value = json.loads(output[0])
    assert value["ok"] is True
    assert service.close_calls == 1
    assert "sir@example.com" not in output[0]
    assert "onyx-desktop-client" not in output[0]


@pytest.mark.parametrize(
    ("error", "exit_code", "code"),
    (
        (GoogleWorkspaceHostV1ContractError("secret"), EXIT_CONTRACT, "invalid-input"),
        (GoogleWorkspaceHostV1Denied("secret"), EXIT_DENIED, "denied"),
        (
            __import__(
                "core.google_workspace_host_v1",
                fromlist=["GoogleWorkspaceHostV1UnknownOutcome"],
            ).GoogleWorkspaceHostV1UnknownOutcome("secret"),
            EXIT_UNKNOWN,
            "unknown-outcome",
        ),
    ),
)
def test_cli_error_taxonomy_is_deterministic_and_secret_free(error, exit_code, code):
    output = []

    def failed(**_kwargs):
        raise error

    assert run_cli_v1(
        _cli_host_args("connect"), output=output.append, _factory_port=failed
    ) == exit_code
    assert json.loads(output[0])["result"] == {"code": code}
    assert "secret" not in output[0]


def test_cli_json_parse_errors_never_echo_unknown_secret_arguments(capsys):
    output = []
    secret = "authorization-code-super-secret"
    exit_code = run_cli_v1(
        ["connect", "--json", "--unknown", secret], output=output.append
    )
    assert exit_code == EXIT_CONTRACT
    assert json.loads(output[0])["result"] == {"code": "invalid-input"}
    captured = capsys.readouterr()
    rendered = output[0] + captured.out + captured.err
    assert secret not in rendered


def test_cli_unknown_command_is_invalid_and_never_echoed(capsys):
    output = []
    secret_command = "private-command-name"
    assert run_cli_v1(
        [secret_command, "--json"], output=output.append
    ) == EXIT_CONTRACT
    value = json.loads(output[0])
    assert value["command"] == "invalid"
    assert value["result"] == {"code": "invalid-input"}
    captured = capsys.readouterr()
    assert secret_command not in output[0] + captured.out + captured.err


def test_cli_service_close_failure_is_classified_without_masking_details():
    class CloseFailureService(CliService):
        def close(self):
            raise GoogleWorkspaceHostV1UnknownOutcome("private-close-detail")

    output = []
    assert run_cli_v1(
        _cli_host_args("status"), output=output.append,
        _factory_port=lambda **_kwargs: CloseFailureService(),
    ) == EXIT_UNKNOWN
    assert json.loads(output[-1])["result"] == {"code": "unknown-outcome"}
    assert "private-close-detail" not in "".join(output)
