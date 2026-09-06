"""Canonical pre-import launcher for persistent DayOps Onyx Live V19."""
from __future__ import annotations

import hashlib
import json
import os
import runpy
import sys
import traceback
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from core.paths import data_root, runtime_dir


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
LOG_PATH = data_root() / "runtime/logs/onyx-live-v19-startup.log"
_UNSET = object()


def _acquire_gui_mutex(arguments: tuple[str, ...], *, factory=None):
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "launch_onyx_live_v18.pyw"),
        run_name="onyx_v18_single_instance_contract",
    )
    acquire = namespace.get("_acquire_gui_mutex_for_mode_v18")
    if not callable(acquire):
        raise RuntimeError("Onyx V18 single-instance contract is unavailable")
    return acquire(arguments, factory=factory)


class _BoundedNativeSmokeMutexV19:
    """Exercise the accepted mutex lifecycle without contending with live UI."""

    def __init__(self) -> None:
        self._boundary = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        from core.control_plane import _WindowsNamedMutex

        target = data_root() / "runtime" / "native-startup-smoke-v1.lock"
        self._boundary = _WindowsNamedMutex(target)
        self._boundary.acquire()
        return True

    def close(self) -> None:
        if self._boundary is None:
            return
        boundary = self._boundary
        self._boundary = None
        boundary.release()


def _run_native_startup_diagnostic() -> dict[str, object]:
    """Traverse launcher logging before invoking the component smoke."""

    from core.native_startup_smoke_v1 import run_terminal_native_startup_smoke_v1

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
        print(
            f"\n[{datetime.now(timezone.utc).isoformat()}] "
            "Onyx native startup smoke entering stable V19 launcher",
            file=log,
        )
        payload = run_terminal_native_startup_smoke_v1()
        print(
            "Onyx native startup smoke passed "
            f"contract={payload.get('contract')} status={payload.get('status')}",
            file=log,
        )
        return payload


def _acquire_governance_runtime_mutex():
    """Serialize every V19 host around its fixed per-user Governance store."""

    if os.name != "nt":
        return None
    from core.control_plane import (
        ControlPlaneLockAbandoned,
        _WindowsNamedMutex,
    )
    from core.paths import private_control_plane_runtime_dir

    target = (
        private_control_plane_runtime_dir()
        / "governance-v1"
        / "governance.sqlite3"
    )
    for attempt in range(2):
        boundary = _WindowsNamedMutex(target)
        try:
            boundary.acquire()
        except ControlPlaneLockAbandoned:
            if attempt == 0:
                continue
            raise
        return boundary
    raise RuntimeError("V19 Governance runtime mutex is unavailable")


def _diagnostic_governance_root_v19(
    arguments: tuple[str, ...],
) -> dict[str, object]:
    """Create and retain a descriptor/handle-pinned diagnostic root."""

    if arguments not in (("--preflight-only",), ("--dayops-smoke-test",)):
        raise RuntimeError("V19 diagnostic Governance mode is invalid")
    mode = arguments[0].removeprefix("--").replace("-", "_")
    owned = runtime_dir() / "diagnostic-owned-v19"
    root = owned / f"{mode}-{os.getpid()}-{uuid.uuid4().hex}"
    if os.name == "nt":
        from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

        boundary = WindowsTrustedDirectoryV1(
            root=root,
            enabled=True,
            allow_root_quarantine=True,
        )
    else:
        from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

        boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    if os.name == "nt":
        identity = boundary.root_identity
        expected_identity = (
            "windows",
            identity.volume_serial,
            identity.file_id,
            identity.volume_guid,
            identity.resolved_path,
        )
    else:
        expected_identity = ("posix", *boundary._root_identity)
    lease = None
    try:
        if os.name == "posix":
            with boundary.session() as session:
                lease = session.descriptor_path("governance.sqlite3")
            governance_path = Path(lease.path)
        else:
            governance_path = root / "governance.sqlite3"
        return {
            "boundary": boundary,
            "canonical_path": root / "governance.sqlite3",
            "expected_identity": expected_identity,
            "lease": lease,
            "path": governance_path,
        }
    except BaseException as exc:
        try:
            boundary.close()
        except BaseException as cleanup_exc:
            exc.add_note(
                "V19 diagnostic root boundary close failed: "
                f"{type(cleanup_exc).__name__}"
            )
        cleanup = _cleanup_diagnostic_governance_v19(
            root / "governance.sqlite3",
            (),
            expected_identity=expected_identity,
        )
        if cleanup:
            exc.add_note(f"V19 diagnostic root cleanup failed: {','.join(cleanup)}")
        raise


def _diagnostic_governance_path_v19(arguments: tuple[str, ...]) -> Path:
    """Compatibility probe that validates root creation without retaining it."""

    resources = _diagnostic_governance_root_v19(arguments)
    lease = resources["lease"]
    boundary = resources["boundary"]
    if lease is not None:
        lease.close()
    boundary.close()
    return resources["canonical_path"]


def _install_diagnostic_native_vault_namespace_v19(
    root: Path,
) -> tuple[list[object], object]:
    """Scope every diagnostic-created native vault away from live services."""

    from core import native_vault

    original = native_vault.NativeSecretVault
    scope = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
    created: list[object] = []

    class DiagnosticNativeSecretVaultV19(original):
        def __init__(self, reference, *args, **kwargs):
            service_suffix = f".Diagnostic.{scope}"
            account_suffix = f".diagnostic.{scope}"
            service = f"{reference.service[:127 - len(service_suffix)]}{service_suffix}"
            account = f"{reference.account[:127 - len(account_suffix)]}{account_suffix}"
            scoped = native_vault.SecretReference(
                service,
                account,
                reference.label,
            )
            super().__init__(scoped, *args, **kwargs)
            self._diagnostic_materialization_v19 = "fresh"
            created.append(self)

        def get_bytes(self):
            try:
                value = super().get_bytes()
            except BaseException:
                self._diagnostic_materialization_v19 = "unknown"
                raise
            self._diagnostic_materialization_v19 = (
                "absent" if value is None else "materialized"
            )
            return value

        def set_bytes(self, secret):
            self._diagnostic_materialization_v19 = "unknown"
            super().set_bytes(secret)
            self._diagnostic_materialization_v19 = "materialized"

        def delete(self):
            self._diagnostic_materialization_v19 = "unknown"
            deleted = super().delete()
            self._diagnostic_materialization_v19 = "absent"
            return deleted

    patched: list[tuple[object, str, object]] = []
    try:
        native_vault.NativeSecretVault = DiagnosticNativeSecretVaultV19
        patched.append((native_vault, "NativeSecretVault", original))
        for module in tuple(sys.modules.values()):
            if module is None:
                continue
            try:
                if getattr(module, "NativeSecretVault", None) is original:
                    setattr(module, "NativeSecretVault", DiagnosticNativeSecretVaultV19)
                    patched.append((module, "NativeSecretVault", original))
            except (AttributeError, TypeError):
                continue
    except BaseException:
        for owner, name, value in reversed(patched):
            setattr(owner, name, value)
        raise

    def restore() -> None:
        for module in tuple(sys.modules.values()):
            if module is None:
                continue
            try:
                if getattr(module, "NativeSecretVault", None) is DiagnosticNativeSecretVaultV19:
                    setattr(module, "NativeSecretVault", original)
            except (AttributeError, TypeError):
                continue
        while patched:
            owner, name, value = patched.pop()
            setattr(owner, name, value)

    return created, restore


def _cleanup_diagnostic_native_vaults_v19(
    vaults: list[object],
) -> tuple[str, ...]:
    failures: list[str] = []
    seen: set[tuple[str, str]] = set()
    for vault in vaults:
        reference = getattr(vault, "reference", None)
        identity = (
            getattr(reference, "service", ""),
            getattr(reference, "account", ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        state = getattr(vault, "_diagnostic_materialization_v19", None)
        if state in {"fresh", "absent"}:
            # A fresh reference is derived from this run's unpredictable UUID
            # and has never crossed a backend write boundary.  Absence after a
            # successful get/delete is likewise canonical.  No backend probe
            # is needed for either state; unknown/materialized must delete.
            continue
        try:
            vault.delete()
        except BaseException as exc:
            failures.append(
                f"diagnostic.scoped_vault.{len(seen) - 1}:{type(exc).__name__}"
            )
    return tuple(failures)


def _diagnostic_governance_factory_v19(path: Path):
    """Bind diagnostic Governance to isolated native-vault references."""

    from core.governance_nucleus_v1 import create_governance_nucleus_v1
    from core.onyx_live_activation_v16 import (
        ActivationFlagsV16,
        _governance_smoke_native_vaults_v1,
        governance_workspace_bindings_v1,
    )

    flags = ActivationFlagsV16.from_canonical_environ(os.environ)
    identity, records = governance_workspace_bindings_v1(
        flags.base.workspace_roots
    )
    vaults = _governance_smoke_native_vaults_v1(path.parent)

    def trusted_directory_factory(**kwargs):
        from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

        return WindowsTrustedDirectoryV1(
            **kwargs,
            share_root_delete=True,
        )

    def factory():
        return create_governance_nucleus_v1(
            path=path,
            principal_id=identity.principal_id,
            workspace_id=identity.workspace_id,
            account_id=identity.account_id,
            profile_id=identity.profile_id,
            workspace_display=identity.workspace_display,
            key_vault=vaults[0],
            head_vault=vaults[1],
            pending_vault=vaults[2],
            workspace_records=records,
            trusted_directory_factory=trusted_directory_factory,
        )

    return factory, vaults


def _diagnostic_private_directory_v19(
    governance_path: Path,
    name: str,
) -> Path:
    """Create one private namespace inside this exact diagnostic run."""

    if name not in {
        "audit",
        "config",
        "control-plane",
        "memory",
        "phase11-authority-v1",
        "workspace",
    }:
        raise RuntimeError("V19 diagnostic private directory is invalid")
    root = governance_path.parent / name
    root.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == "nt":
        from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

        boundary = WindowsTrustedDirectoryV1(root=root, enabled=True)
        boundary.close()
    else:
        root.chmod(0o700)
    return root


def _diagnostic_phase11_runtime_v19(governance_path: Path) -> Path:
    return _diagnostic_private_directory_v19(
        governance_path,
        "phase11-authority-v1",
    )


def _cleanup_diagnostic_governance_v19(
    path: Path,
    vaults: tuple[object, ...],
    *,
    expected_identity: tuple[object, ...] | None = None,
) -> tuple[str, ...]:
    """Remove only exact diagnostic-owned files and native-vault values."""

    failures = list(_cleanup_diagnostic_native_vaults_v19(list(vaults)))
    if os.name == "nt":
        from core.phase11_windows_namespace_v1 import WindowsTrustedDirectoryV1

        boundary = None
        try:
            boundary = WindowsTrustedDirectoryV1(
                root=path.parent,
                enabled=True,
                allow_root_quarantine=True,
            )
            if expected_identity is not None:
                identity = boundary.root_identity
                observed = (
                    "windows",
                    identity.volume_serial,
                    identity.file_id,
                    identity.volume_guid,
                    identity.resolved_path,
                )
                if observed != expected_identity:
                    raise RuntimeError(
                        "diagnostic_windows_root_identity_mismatch"
                    )
            boundary.remove_root_tree(
                max_entries=4_096,
                max_bytes=64 * 1024 * 1024,
            )
        except BaseException as exc:
            failures.append(f"diagnostic.directory:{type(exc).__name__}")
        finally:
            if boundary is not None:
                try:
                    boundary.close()
                except BaseException as exc:
                    failures.append(
                        f"diagnostic.directory.close:{type(exc).__name__}"
                    )
        return tuple(failures)
    from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1

    boundary = None
    try:
        boundary = PosixTrustedDirectoryV1(
            root=path.parent.parent,
            enabled=True,
        )
        with boundary.session() as session:
            session.remove_tree(
                path.parent.name,
                max_entries=4_096,
                max_bytes=64 * 1024 * 1024,
                expected_identity=(
                    None
                    if expected_identity is None
                    else expected_identity[1:]
                ),
            )
    except BaseException as exc:
        failures.append(f"diagnostic.directory:{type(exc).__name__}")
    finally:
        if boundary is not None:
            try:
                boundary.close()
            except BaseException as exc:
                failures.append(
                    f"diagnostic.directory.close:{type(exc).__name__}"
                )
    return tuple(failures)


def _cleanup_diagnostic_activation_base_v19(
    controller: object | None,
) -> tuple[str, ...]:
    """Close V17 then V16, which live rollback intentionally preserves."""

    if controller is None:
        return ()
    failures: list[str] = []
    v18 = getattr(controller, "_base", None)
    v17 = getattr(v18, "_base", None)
    v16 = getattr(v17, "_base", None)
    rollback_v17 = getattr(v17, "rollback_all", None)
    rollback_v16 = getattr(v16, "rollback_all", None)
    if not callable(rollback_v17) or not callable(rollback_v16):
        return ("diagnostic.activation.base:Unavailable",)
    try:
        rollback_v17()
    except BaseException as exc:
        failures.append(f"diagnostic.activation.v17:{type(exc).__name__}")
    try:
        rollback_v16()
    except BaseException as exc:
        failures.append(f"diagnostic.activation.v16:{type(exc).__name__}")
    return tuple(failures)


def _install_diagnostic_path_namespace_v19(
    governance_path: Path,
    *,
    root_boundary: object | None = None,
) -> tuple[dict[str, Path], object]:
    """Redirect already-imported path aliases and bound path constants."""

    from core import paths

    names = {
        "audit": "audit",
        "config": "config",
        "control_plane": "control-plane",
        "memory": "memory",
        "phase11": "phase11-authority-v1",
        "workspace": "workspace",
    }
    if os.name == "posix" and root_boundary is not None:
        with root_boundary.session() as session:
            for name in names.values():
                session.ensure_directory(name)
        locations = {
            key: governance_path.parent / name for key, name in names.items()
        }
    else:
        locations = {
            key: _diagnostic_private_directory_v19(governance_path, name)
            for key, name in names.items()
        }
    replacements = {
        "config_dir": lambda: locations["config"],
        "config_file": lambda: locations["config"] / "api_keys.json",
        "memory_dir": lambda: locations["memory"],
        "private_control_plane_runtime_dir": lambda: locations["control_plane"],
        "runtime_dir": lambda: locations["phase11"],
    }
    constant_specs = (
        (
            "main",
            "API_CONFIG_PATH",
            locations["config"] / "api_keys.json",
            lambda: originals["config_file"](),
        ),
        (
            "memory.config_manager",
            "CONFIG_FILE",
            locations["config"] / "api_keys.json",
            lambda: originals["config_file"](),
        ),
        (
            "core.credentials",
            "CONFIG_PATH",
            locations["config"] / "api_keys.json",
            lambda: originals["config_file"](),
        ),
        (
            "core.llm_client",
            "CONFIG_PATH",
            locations["config"] / "api_keys.json",
            lambda: originals["config_file"](),
        ),
        (
            "core.readiness",
            "CONFIG_PATH",
            locations["config"] / "api_keys.json",
            lambda: originals["config_file"](),
        ),
        (
            "core.missions",
            "DEFAULT_DB",
            locations["memory"] / "onyx_missions.sqlite3",
            lambda: originals["memory_dir"]() / "onyx_missions.sqlite3",
        ),
        (
            "core.tool_audit",
            "AUDIT_PATH",
            locations["audit"] / "tool_audit.sqlite3",
            lambda: originals["runtime_dir"]() / "audit" / "tool_audit.sqlite3",
        ),
    )
    patched: list[tuple[object, str, object]] = []
    originals = {name: getattr(paths, name) for name in replacements}
    try:
        for name, replacement in replacements.items():
            original = originals[name]
            setattr(paths, name, replacement)
            patched.append((paths, name, original))
            for module in tuple(sys.modules.values()):
                if module is None or module is paths:
                    continue
                try:
                    if getattr(module, name, None) is original:
                        setattr(module, name, replacement)
                        patched.append((module, name, original))
                except (AttributeError, TypeError):
                    continue

        memory_manager = sys.modules.get("memory.memory_manager")
        if memory_manager is not None:
            for name, value in (
                ("MEMORY_PATH", locations["memory"] / "long_term.json"),
                ("DATABASE_PATH", locations["memory"] / "onyx_memory.sqlite3"),
                ("_store", None),
            ):
                original = getattr(memory_manager, name)
                setattr(memory_manager, name, value)
                patched.append((memory_manager, name, original))

        for module_name, name, diagnostic, _production in constant_specs:
            module = sys.modules.get(module_name)
            if module is None or not hasattr(module, name):
                continue
            original = getattr(module, name)
            setattr(module, name, diagnostic)
            patched.append((module, name, original))
    except BaseException:
        while patched:
            owner, name, value = patched.pop()
            setattr(owner, name, value)
        raise

    def restore() -> None:
        for name, replacement in replacements.items():
            original = originals[name]
            for module in tuple(sys.modules.values()):
                if module is None:
                    continue
                try:
                    if getattr(module, name, None) is replacement:
                        setattr(module, name, original)
                except (AttributeError, TypeError):
                    continue
        memory_manager = sys.modules.get("memory.memory_manager")
        if memory_manager is not None:
            if getattr(memory_manager, "MEMORY_PATH", None) == (
                locations["memory"] / "long_term.json"
            ):
                memory_manager.MEMORY_PATH = originals["memory_dir"]() / "long_term.json"
            if getattr(memory_manager, "DATABASE_PATH", None) == (
                locations["memory"] / "onyx_memory.sqlite3"
            ):
                memory_manager.DATABASE_PATH = (
                    originals["memory_dir"]() / "onyx_memory.sqlite3"
                )
            diagnostic_store = getattr(memory_manager, "_store", None)
            diagnostic_store_path = getattr(diagnostic_store, "path", None)
            if diagnostic_store_path is not None:
                try:
                    is_diagnostic_store = Path(diagnostic_store_path).is_relative_to(
                        locations["memory"]
                    )
                except (OSError, ValueError):
                    is_diagnostic_store = False
                if is_diagnostic_store:
                    memory_manager._store = None
        for module_name, name, diagnostic, production in constant_specs:
            module = sys.modules.get(module_name)
            if module is not None and getattr(module, name, None) == diagnostic:
                setattr(module, name, production())
        while patched:
            owner, name, value = patched.pop()
            setattr(owner, name, value)

    return locations, restore


class _DiagnosticChainHeadStoreV19:
    """Process-local CAS used only by a disposable diagnostic authority."""

    def __init__(self) -> None:
        self._heads: dict[str, object] = {}

    def load(self, owner_profile_id: str) -> object | None:
        return self._heads.get(owner_profile_id)

    def compare_and_set(
        self,
        owner_profile_id: str,
        expected: object | None,
        desired: object,
    ) -> bool:
        if self._heads.get(owner_profile_id) != expected:
            return False
        self._heads[owner_profile_id] = desired
        return True


class _DiagnosticOwnerLeaseV19:
    cross_session_guaranteed = True

    @contextmanager
    def hold(self, _owner_profile_id: str, *, timeout_seconds: float):
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise RuntimeError("V19 diagnostic owner lease timeout is invalid")
        yield self


def _diagnostic_authority_factory_v19(
    locations: dict[str, Path],
) -> tuple[object, object]:
    """Build V4 owner authority without production files or credentials."""

    from core.native_vault import NativeSecretVault, SecretReference
    from core.onyx_live_activation_v4 import (
        OWNER_KEY_ACCOUNT,
        OWNER_KEY_SERVICE,
        provision_owner_authority,
    )
    from memory.store import MemoryStore

    memory = MemoryStore(locations["memory"] / "owner-memory.sqlite3")
    memory.initialize()
    vault = NativeSecretVault(
        SecretReference(
            OWNER_KEY_SERVICE,
            OWNER_KEY_ACCOUNT,
            "Onyx diagnostic owner authentication key",
        )
    )
    heads = _DiagnosticChainHeadStoreV19()
    lease = _DiagnosticOwnerLeaseV19()

    def factory():
        return provision_owner_authority(
            journal_path=locations["control_plane"]
            / "owner-profile-v8.journal.json",
            vault=vault,
            memory=memory,
            config_path=locations["config"] / "api_keys.json",
            chain_head_store=heads,
            transaction_lease=lease,
        )

    return factory, memory


def _diagnostic_dayops_component_factory_v19(locations: dict[str, Path]):
    """Bind DayOps profile and every exact control-plane store privately."""

    from core.control_plane import ControlPlaneStore
    from core.dayops_connection_v19 import DayOpsConnectionControllerV19
    from core.dayops_graph_factory_v19 import PersistentDayOpsGraphFactoryV19
    from core.dayops_identity_provisioning_v19 import DayOpsIdentityProvisionerV19
    from core.dayops_profile_v19 import DayOpsProfileStoreV19

    def store_factory() -> ControlPlaneStore:
        return ControlPlaneStore(enabled=True)

    def component_factory(_instance, identity):
        profile = DayOpsProfileStoreV19(
            identity,
            path=locations["config"] / "dayops-profile-v19.json",
        )
        graph = PersistentDayOpsGraphFactoryV19(
            identity,
            profile,
            graph_factory_options={
                "project_root": ROOT,
                "store_factory": store_factory,
            },
        )
        provisioner = DayOpsIdentityProvisionerV19(
            identity,
            profile,
            project_root=ROOT,
            store_factory=store_factory,
        )
        controller = DayOpsConnectionControllerV19(
            identity,
            profile,
            provisioner,
            graph,
        )
        return controller, graph

    return component_factory


@contextmanager
def _diagnostic_resources_v19(arguments: tuple[str, ...]):
    """Own every diagnostic mutation from first creation through teardown."""

    def no_restore() -> None:
        pass

    governance_path: Path | None = None
    cleanup_path: Path | None = None
    expected_root_identity: tuple[object, ...] | None = None
    root_boundary = None
    root_lease = None
    governance_vaults: tuple[object, ...] = ()
    diagnostic_vaults: list[object] = []
    restore_native = no_restore
    restore_paths = no_restore
    memory = None
    workspace_flag = None
    previous_workspace = _UNSET
    active_error: BaseException | None = None
    try:
        root_resources = _diagnostic_governance_root_v19(arguments)
        governance_path = root_resources["path"]
        cleanup_path = root_resources["canonical_path"]
        expected_root_identity = root_resources["expected_identity"]
        root_boundary = root_resources["boundary"]
        root_lease = root_resources["lease"]
        diagnostic_vaults, restore_native = (
            _install_diagnostic_native_vault_namespace_v19(
                cleanup_path.parent,
            )
        )
        locations, restore_paths = _install_diagnostic_path_namespace_v19(
            governance_path,
            root_boundary=root_boundary,
        )
        from core.onyx_live_activation_v15 import WORKSPACE_ROOTS_FLAG

        workspace_flag = WORKSPACE_ROOTS_FLAG
        previous_workspace = os.environ.get(workspace_flag, _UNSET)
        os.environ[workspace_flag] = str(locations["workspace"])
        governance_factory, governance_vaults = (
            _diagnostic_governance_factory_v19(governance_path)
        )
        authority_factory, memory = _diagnostic_authority_factory_v19(locations)
        yield {
            "authority_factory": authority_factory,
            "component_factory": _diagnostic_dayops_component_factory_v19(locations),
            "governance_factory": governance_factory,
            "governance_path": governance_path,
            "locations": locations,
        }
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        failures: list[str] = []
        if workspace_flag is not None:
            try:
                if previous_workspace is _UNSET:
                    os.environ.pop(workspace_flag, None)
                else:
                    os.environ[workspace_flag] = previous_workspace
            except BaseException as exc:
                failures.append(f"diagnostic.workspace.restore:{type(exc).__name__}")
        if memory is not None:
            close_memory = getattr(memory, "close", None)
            if callable(close_memory):
                try:
                    close_memory()
                except BaseException as exc:
                    failures.append(
                        f"diagnostic.memory.close:{type(exc).__name__}"
                    )
        failures.extend(_cleanup_diagnostic_native_vaults_v19(diagnostic_vaults))
        try:
            restore_paths()
        except BaseException as exc:
            failures.append(f"diagnostic.paths.restore:{type(exc).__name__}")
        try:
            restore_native()
        except BaseException as exc:
            failures.append(f"diagnostic.vault_namespace.restore:{type(exc).__name__}")
        if root_lease is not None:
            try:
                root_lease.close()
            except BaseException as exc:
                failures.append(f"diagnostic.root_lease.close:{type(exc).__name__}")
        if (
            os.name == "nt"
            and root_boundary is not None
            and cleanup_path is not None
        ):
            try:
                root_boundary.remove_root_tree(
                    max_entries=4_096,
                    max_bytes=64 * 1024 * 1024,
                )
            except BaseException as exc:
                failures.append(
                    f"diagnostic.directory.retained:{type(exc).__name__}"
                )
            else:
                cleanup_path = None
        if root_boundary is not None:
            try:
                root_boundary.close()
            except BaseException as exc:
                failures.append(f"diagnostic.root_boundary.close:{type(exc).__name__}")
        if cleanup_path is not None:
            failures.extend(
                _cleanup_diagnostic_governance_v19(
                    cleanup_path,
                    governance_vaults,
                    expected_identity=expected_root_identity,
                )
            )
        if failures:
            detail = ",".join(failures)
            if active_error is not None:
                active_error.add_note(f"V19 diagnostic cleanup failures: {detail}")
            else:
                raise RuntimeError(f"V19 diagnostic cleanup failed: {detail}")


class _PreflightUI:
    def __init__(self) -> None:
        self.muted = True
        self.current_file = None
        self.trusted_ui_prompts = 0

    def write_log(self, _value: str) -> None:
        pass

    def set_state(self, _value: str) -> None:
        pass


@contextmanager
def _diagnostic_main_aliases_v19(module: object, locations: dict[str, Path]):
    """Patch imported host paths outside every fallible provider boundary."""

    originals = {
        "config_file": getattr(module, "config_file", _UNSET),
        "memory_dir": getattr(module, "memory_dir", _UNSET),
        "runtime_dir": getattr(module, "runtime_dir", _UNSET),
    }
    active_error: BaseException | None = None
    try:
        module.runtime_dir = lambda: locations["phase11"].resolve()
        module.memory_dir = lambda: locations["memory"].resolve()
        module.config_file = lambda: (
            locations["config"] / "api_keys.json"
        ).resolve()
        yield originals
    except BaseException as exc:
        active_error = exc
        raise
    finally:
        failures: list[str] = []
        for name in ("runtime_dir", "memory_dir", "config_file"):
            try:
                original = originals[name]
                if original is _UNSET:
                    delattr(module, name)
                else:
                    setattr(module, name, original)
            except BaseException as exc:
                failures.append(f"diagnostic.{name}.restore:{type(exc).__name__}")
        if failures:
            detail = ",".join(failures)
            if active_error is not None:
                active_error.add_note(
                    f"V19 diagnostic main alias restore failures: {detail}"
                )
            else:
                raise RuntimeError(
                    f"V19 diagnostic main alias restore failed: {detail}"
                )


def _run_bounded_diagnostic(arguments: tuple[str, ...]) -> None:
    """Run V19 diagnostics under an enumerated best-effort I/O fence."""

    from core.native_startup_smoke_v1 import (
        ExternalCallCountersV1,
        INTERCEPTION_SCOPE,
        _cleanup_host,
        _external_agent_unavailable,
        _provider_call_boundary_v1,
        external_call_boundary_v1,
    )

    calls = ExternalCallCountersV1()
    controller = None
    instance = None
    ui = None
    onyx_main = None
    original_runtime_dir = None
    # One reversible lifecycle owns every mutation, including failures before
    # host import or activation.  The external fence remains nested within it.
    with _diagnostic_resources_v19(arguments) as resources, \
            external_call_boundary_v1(counters=calls):
        from core.onyx_live_activation_v15 import verify_activation_prerequisites
        from core.onyx_live_activation_v19 import activate_main

        verify_activation_prerequisites(ROOT, os.environ)
        import main as imported_main

        onyx_main = imported_main
        locations = resources["locations"]
        with _diagnostic_main_aliases_v19(
            imported_main,
            locations,
        ) as original_aliases, _provider_call_boundary_v1(imported_main, calls):
            original_runtime_dir = original_aliases["runtime_dir"]
            active_error: BaseException | None = None
            try:
                controller = activate_main(
                    imported_main,
                    external_agent_factory=_external_agent_unavailable,
                    governance_path=resources["governance_path"],
                    nucleus_factory=resources["governance_factory"],
                    authority_factory=resources["authority_factory"],
                    component_factory=resources["component_factory"],
                )
                ui = _PreflightUI()
                instance = controller.instantiate_live(ui)
                status = getattr(
                    instance,
                    "_dayops_connection_controller_v19",
                ).status()
                if arguments == ("--dayops-smoke-test",):
                    payload = {
                        "contract": "OnyxDayOpsSmoke.v19",
                        "status": "passed",
                        "connection_status": status.get("status"),
                        "read_only": status.get("read_only"),
                        "callbacks_bound": all(
                            callable(getattr(ui, name, None))
                            for name in (
                                "on_dayops_status",
                                "on_dayops_connect",
                                "on_dayops_sign_in",
                                "on_dayops_disconnect",
                                "on_dayops_today_brief",
                            )
                        ),
                        "interception": calls.evidence(),
                        "network_calls": calls.network,
                        "provider_calls": calls.provider,
                        "process_calls": calls.process,
                        "trusted_ui_prompts": ui.trusted_ui_prompts,
                    }
                    required = {
                        "contract": "OnyxDayOpsSmoke.v19",
                        "status": "passed",
                        "connection_status": "configuration_required",
                        "read_only": True,
                        "callbacks_bound": True,
                        "network_calls": 0,
                        "provider_calls": 0,
                        "process_calls": 0,
                        "trusted_ui_prompts": 0,
                    }
                    if any(payload.get(key) != value for key, value in required.items()):
                        raise RuntimeError("DayOps V19 disconnected smoke failed")
                    print(json.dumps(payload, sort_keys=True), flush=True)
                else:
                    print(
                        "ONYX_LIVE_V19_HOST_PREFLIGHT_OK "
                        "hud=v19-pinned qml=5 rays=22 equalizer=48 arcs=0 "
                        "dayops=persistent-read-only document_intake=provider-free "
                        "governance=v16-authority founder=v17 "
                        f"network_calls={calls.network} "
                        f"provider_calls={calls.provider} "
                        f"process_calls={calls.process} "
                        f"interception_scope={INTERCEPTION_SCOPE}",
                        flush=True,
                    )
            except BaseException as exc:
                active_error = exc
                raise
            finally:
                cleanup_failures = _cleanup_host(
                    ui=ui,
                    controller=controller,
                    onyx_main=onyx_main,
                    original_runtime_dir=original_runtime_dir,
                    instance=instance,
                )
                cleanup_failures += _cleanup_diagnostic_activation_base_v19(
                    controller,
                )
                if cleanup_failures:
                    detail = ",".join(cleanup_failures)
                    if active_error is not None:
                        active_error.add_note(
                            f"V19 diagnostic cleanup failures: {detail}"
                        )
                    else:
                        raise RuntimeError(
                            f"V19 diagnostic cleanup failed: {detail}"
                        )


def run() -> None:
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if sys.argv[1:] not in (
        [],
        ["--preflight-only"],
        ["--dayops-smoke-test"],
        ["--native-startup-smoke-test"],
    ):
        raise RuntimeError("Onyx Live V19 launcher arguments are invalid")
    native_smoke = sys.argv[1:] == ["--native-startup-smoke-test"]
    single_instance, proceed = _acquire_gui_mutex(
        () if native_smoke else tuple(sys.argv[1:]),
        factory=_BoundedNativeSmokeMutexV19 if native_smoke else None,
    )
    if not proceed:
        return
    governance_mutex = (
        _acquire_governance_runtime_mutex()
        if not sys.argv[1:]
        else None
    )
    controller = None
    frozen_diagnostic = False
    try:
        if native_smoke:
            _run_native_startup_diagnostic()
            frozen_diagnostic = bool(
                getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
            )
        elif sys.argv[1:]:
            _run_bounded_diagnostic(tuple(sys.argv[1:]))
            frozen_diagnostic = bool(
                getattr(sys, "frozen", False) or getattr(sys, "_MEIPASS", None)
            )
        else:
            from core.onyx_live_activation_v15 import verify_activation_prerequisites
            from core.onyx_live_activation_v19 import activate_main

            verify_activation_prerequisites(ROOT, os.environ)
            phase11_runtime = runtime_dir() / "phase11-authority-v1"
            phase11_runtime.mkdir(parents=True, exist_ok=True)
            import main as onyx_main

            onyx_main.runtime_dir = lambda: phase11_runtime.resolve()
            controller = activate_main(onyx_main)
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8", buffering=1) as log:
                sys.stdout = log
                sys.stderr = log
                print(
                    f"\n[{datetime.now(timezone.utc).isoformat()}] "
                    "Onyx Live V19 starting"
                )
                print(f"DayOps capability: {controller.dayops_capability}")
                try:
                    onyx_main.main()
                except BaseException:
                    traceback.print_exc()
                    raise
    finally:
        try:
            if controller is not None:
                controller.rollback_all()
        finally:
            try:
                if governance_mutex is not None:
                    governance_mutex.release()
            finally:
                if single_instance is not None:
                    single_instance.close()
    if frozen_diagnostic:
        if sys.stdout is not None:
            sys.stdout.flush()
        if sys.stderr is not None:
            sys.stderr.flush()
        os._exit(0)


if __name__ == "__main__":
    run()
