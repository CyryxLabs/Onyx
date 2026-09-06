from __future__ import annotations

import os
import runpy
from pathlib import Path

import pytest

from core.host_security_boundary_v1 import (
    HostSecurityBoundaryBusy,
    HostSecurityBoundaryError,
)
from core.posix_trusted_directory_v1 import PosixTrustedDirectoryV1, _components


@pytest.mark.parametrize(
    "relative",
    ["", ".", "..", "../escape", "/absolute", "nested//file", "with space"],
)
def test_relative_path_validation_is_platform_independent(relative: str) -> None:
    with pytest.raises(HostSecurityBoundaryError, match="relative_path_invalid"):
        _components(relative)


def test_disabled_boundary_performs_no_host_io(tmp_path: Path) -> None:
    root = tmp_path / "unused"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=False)
    assert root.exists() is False
    boundary.close()
    boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_native_directory_publishes_without_replace_and_reads(tmp_path: Path) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    try:
        assert root.stat().st_mode & 0o777 == 0o700
        with boundary.session() as session:
            session.publish_create("missions/receipt.json", b"receipt")
            assert session.exists("missions/receipt.json", directory=False)
            assert session.read("missions/receipt.json", max_bytes=7) == b"receipt"
            with pytest.raises(HostSecurityBoundaryBusy, match="artifact_exists"):
                session.publish_create("missions/receipt.json", b"replacement")
        assert (root / "missions").stat().st_mode & 0o777 == 0o700
        assert (root / "missions" / "receipt.json").stat().st_mode & 0o777 == 0o600
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_native_directory_rejects_linked_ancestor(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(HostSecurityBoundaryError, match="open_failed"):
        PosixTrustedDirectoryV1(root=linked / "trusted", enabled=True)


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_native_directory_detects_name_to_inode_drift(tmp_path: Path) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    moved = tmp_path / "moved"
    root.rename(moved)
    root.mkdir(mode=0o700)
    try:
        with pytest.raises(HostSecurityBoundaryError, match="identity_changed"):
            with boundary.session():
                pass
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_remove_tree_deletes_only_descriptor_bound_private_tree(
    tmp_path: Path,
) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    try:
        with boundary.session() as session:
            session.publish_create("diagnostic/nested/result.json", b"result")
            entries, total_bytes = session.remove_tree(
                "diagnostic",
                max_entries=16,
                max_bytes=1024,
            )
        assert entries == 2
        assert total_bytes == 6
        assert not (root / "diagnostic").exists()
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_remove_tree_rejects_symlink_without_touching_tree_or_target(
    tmp_path: Path,
) -> None:
    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    target = tmp_path / "outside.txt"
    target.write_bytes(b"outside")
    try:
        diagnostic = root / "diagnostic"
        diagnostic.mkdir(mode=0o700)
        (diagnostic / "escape").symlink_to(target)
        with boundary.session() as session:
            with pytest.raises(
                HostSecurityBoundaryError,
                match="(cleanup_entry_invalid|posix_trusted_file_invalid)",
            ):
                session.remove_tree(
                    "diagnostic",
                    max_entries=16,
                    max_bytes=1024,
                )
        assert diagnostic.is_dir()
        assert (diagnostic / "escape").is_symlink()
        assert target.read_bytes() == b"outside"
    finally:
        boundary.close()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_diagnostic_root_creation_rejects_symlinked_owned_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(project / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_posix_parent_attack",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    (runtime / "diagnostic-owned-v19").symlink_to(
        external,
        target_is_directory=True,
    )
    globals_ = namespace["_diagnostic_governance_path_v19"].__globals__
    monkeypatch.setitem(globals_, "runtime_dir", lambda: runtime)

    with pytest.raises(HostSecurityBoundaryError, match="open_failed"):
        namespace["_diagnostic_governance_path_v19"](("--preflight-only",))

    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_diagnostic_descriptor_paths_survive_root_swap_without_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(project / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_posix_root_swap",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    external = tmp_path / "external"
    external.mkdir(mode=0o700)
    root_globals = namespace["_diagnostic_governance_root_v19"].__globals__
    monkeypatch.setitem(root_globals, "runtime_dir", lambda: runtime)
    resources = namespace["_diagnostic_governance_root_v19"](
        ("--preflight-only",)
    )
    def restore() -> None:
        pass

    try:
        locations, restore = namespace[
            "_install_diagnostic_path_namespace_v19"
        ](
            resources["path"],
            root_boundary=resources["boundary"],
        )
        canonical_root = resources["canonical_path"].parent
        moved = canonical_root.with_name(f"{canonical_root.name}-moved")
        canonical_root.rename(moved)
        canonical_root.symlink_to(external, target_is_directory=True)

        (locations["memory"] / "sentinel").write_bytes(b"pinned")

        assert (moved / "memory" / "sentinel").read_bytes() == b"pinned"
        assert list(external.iterdir()) == []
    finally:
        restore()
        lease = resources["lease"]
        if lease is not None:
            lease.close()
        resources["boundary"].close()

    failures = namespace["_cleanup_diagnostic_governance_v19"](
        resources["canonical_path"],
        (),
        expected_identity=resources["expected_identity"],
    )
    assert failures
    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_diagnostic_cleanup_rejects_regular_directory_identity_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(project / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_posix_regular_root_swap",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    root_globals = namespace["_diagnostic_governance_root_v19"].__globals__
    monkeypatch.setitem(root_globals, "runtime_dir", lambda: runtime)
    resources = namespace["_diagnostic_governance_root_v19"](
        ("--preflight-only",)
    )
    canonical_root = resources["canonical_path"].parent
    moved = canonical_root.with_name(f"{canonical_root.name}-moved")
    canonical_root.rename(moved)
    canonical_root.mkdir(mode=0o700)
    replacement = canonical_root / "replacement.txt"
    replacement.write_bytes(b"replacement")
    os.chmod(replacement, 0o600)
    lease = resources["lease"]
    if lease is not None:
        lease.close()
    resources["boundary"].close()

    failures = namespace["_cleanup_diagnostic_governance_v19"](
        resources["canonical_path"],
        (),
        expected_identity=resources["expected_identity"],
    )

    assert failures == ("diagnostic.directory:HostSecurityBoundaryError",)
    assert replacement.read_bytes() == b"replacement"
    assert moved.is_dir()


@pytest.mark.skipif(os.name != "posix", reason="requires native POSIX dirfd")
def test_darwin_descriptor_contract_selects_validated_dev_fd_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.posix_trusted_directory_v1 as posix_directory

    root = tmp_path / "trusted"
    boundary = PosixTrustedDirectoryV1(root=root, enabled=True)
    monkeypatch.setattr(posix_directory.platform, "system", lambda: "Darwin")
    lease = None
    try:
        with boundary.session() as session:
            lease = session.descriptor_path("governance.sqlite3")
        assert lease.path.startswith("/dev/fd/")
        assert lease.path.endswith("/governance.sqlite3")
    finally:
        if lease is not None:
            lease.close()
        boundary.close()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows reparse handling")
def test_diagnostic_root_creation_rejects_windows_reparse_owned_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.phase11_windows_clone_cleanup_v1 import CloneCleanupContractError

    project = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(project / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_windows_parent_attack",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    try:
        (runtime / "diagnostic-owned-v19").symlink_to(
            external,
            target_is_directory=True,
        )
    except OSError as exc:
        pytest.skip(f"Windows symlink privilege unavailable: {exc}")
    globals_ = namespace["_diagnostic_governance_path_v19"].__globals__
    monkeypatch.setitem(globals_, "runtime_dir", lambda: runtime)

    with pytest.raises(CloneCleanupContractError, match="reparse_point_refused"):
        namespace["_diagnostic_governance_path_v19"](("--preflight-only",))

    assert list(external.iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="requires Windows file identity")
def test_diagnostic_cleanup_rejects_windows_regular_directory_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = Path(__file__).resolve().parents[1]
    namespace = runpy.run_path(
        str(project / "scripts" / "launch_onyx_live_v19.pyw"),
        run_name="onyx_v19_windows_regular_root_swap",
    )
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    root_globals = namespace["_diagnostic_governance_root_v19"].__globals__
    monkeypatch.setitem(root_globals, "runtime_dir", lambda: runtime)
    resources = namespace["_diagnostic_governance_root_v19"](
        ("--preflight-only",)
    )
    canonical_root = resources["canonical_path"].parent
    moved = canonical_root.with_name(f"{canonical_root.name}-moved")
    resources["boundary"].close()
    canonical_root.rename(moved)
    canonical_root.mkdir()
    replacement = canonical_root / "replacement.txt"
    replacement.write_bytes(b"replacement")

    failures = namespace["_cleanup_diagnostic_governance_v19"](
        resources["canonical_path"],
        (),
        expected_identity=resources["expected_identity"],
    )

    assert failures
    assert replacement.read_bytes() == b"replacement"
    assert moved.is_dir()
