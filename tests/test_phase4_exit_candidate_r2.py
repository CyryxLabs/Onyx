"""Adversarial and rollback tests for the Phase 4 E1-E5 R2 candidate."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.control_plane import ControlPlaneDisabled, ControlPlaneStore
from scripts import verify_phase4_exit_candidate_r2 as gate


def _startup_file(root: Path, source: str) -> Path:
    path = root / "startup_probe.py"
    path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "source",
    [
        "from core import control_plane_v5 as extension\n",
        "loader = __import__\nloader('core.control_plane_v5')\n",
        "import builtins as b\nloader = b.__import__\nloader('core.control_plane_v5')\n",
        "from builtins import __import__ as loader\nloader('core.control_plane_v5')\n",
        "import importlib as il\nloader = il.import_module\nloader('core.control_plane_v5')\n",
        "from importlib import import_module as loader\nloader('core.control_plane_v5')\n",
        "import runpy as rp\nrp.run_module('core.control_plane_v5')\n",
        "from runpy import run_module as run\nrun('core.control_plane_v5')\n",
        "runner = exec\nrunner('import core.control_plane_v5')\n",
        "import builtins as b\nrunner = b.eval\nrunner('1 + 1')\n",
        "from pathlib import Path as P\nP('core/control_plane_v5.py').read_text()\n",
        "import pathlib as p\np.Path('core') / 'control_plane_v5.py'\nopen(p.Path('core') / 'control_plane_v5.py')\n",
    ],
)
def test_startup_scanner_rejects_every_reported_bypass(tmp_path: Path, source: str) -> None:
    startup = _startup_file(tmp_path, source)
    with pytest.raises(RuntimeError, match="startup policy violation"):
        gate.verify_startup_boundary((startup,))


def test_startup_scanner_external_path_is_fail_closed_without_relative_crash() -> None:
    with tempfile.TemporaryDirectory(prefix="onyx-p4-r2-external-") as temporary:
        startup = _startup_file(
            Path(temporary),
            "from core import control_plane_v5 as extension\n",
        )
        assert not startup.resolve().is_relative_to(gate.PROJECT.resolve())
        with pytest.raises(RuntimeError, match="startup policy violation") as raised:
            gate.verify_startup_boundary((startup,))
        assert startup.resolve().as_posix() in str(raised.value)

    missing = gate.PROJECT.parent / "missing-r2-startup-probe.py"
    with pytest.raises(RuntimeError, match="missing startup source") as raised:
        gate.verify_startup_boundary((missing,))
    assert "ValueError" not in str(raised.value)


def test_current_startup_sources_pass_explicit_no_dynamic_execution_policy() -> None:
    assert gate.verify_startup_boundary() == [gate.display_path(path) for path in gate.STARTUP_SOURCES]


def _write_manifest(path: Path, records: dict[str, str]) -> None:
    body = "".join(f"{digest} *{relative}\n" for relative, digest in sorted(records.items()))
    path.write_bytes(body.encode("utf-8"))


def _current_records() -> dict[str, str]:
    return {
        relative: hashlib.sha256((gate.PROJECT / relative).read_bytes()).hexdigest()
        for relative in gate.EXPECTED_R2_PATHS
    }


def test_r2_manifest_reconstructs_exact_set_and_current_bytes() -> None:
    count, digest = gate.verify_r2_manifest()
    assert count == len(gate.EXPECTED_R2_PATHS) == 6
    assert len(digest) == 64


@pytest.mark.parametrize("fault", ["missing", "extra", "mismatch"])
def test_r2_manifest_negative_exact_set_and_hash(
    tmp_path: Path, fault: str
) -> None:
    records = _current_records()
    if fault == "missing":
        records.pop("scripts/verify_phase4_exit_candidate_r2.py")
        match = "exact-set mismatch"
    elif fault == "extra":
        records["unexpected-r2-input.txt"] = "0" * 64
        match = "exact-set mismatch"
    else:
        records["scripts/verify_phase4_exit_candidate_r2.py"] = "0" * 64
        match = "digest mismatch"
    manifest = tmp_path / f"{fault}.sha256"
    _write_manifest(manifest, records)
    with pytest.raises(RuntimeError, match=match):
        gate.verify_r2_manifest(manifest)


@pytest.mark.parametrize("fault", ["bom", "crlf", "order", "malformed"])
def test_r2_manifest_rejects_noncanonical_format(tmp_path: Path, fault: str) -> None:
    records = _current_records()
    lines = [f"{digest} *{relative}" for relative, digest in sorted(records.items())]
    if fault == "bom":
        raw = b"\xef\xbb\xbf" + ("\n".join(lines) + "\n").encode()
    elif fault == "crlf":
        raw = ("\r\n".join(lines) + "\r\n").encode()
    elif fault == "order":
        lines[0], lines[1] = lines[1], lines[0]
        raw = ("\n".join(lines) + "\n").encode()
    else:
        lines[0] = lines[0].replace(" *", "  ", 1)
        raw = ("\n".join(lines) + "\n").encode()
    manifest = tmp_path / f"{fault}.sha256"
    manifest.write_bytes(raw)
    with pytest.raises(RuntimeError, match="manifest"):
        gate.verify_r2_manifest(manifest)


def test_all_eight_flag_readers_enable_disable_and_restore_environment() -> None:
    before = {name: (name in os.environ, os.environ.get(name)) for name, _reader, _accepted in gate.FLAG_SPECS}
    try:
        for name, reader, accepted in gate.FLAG_SPECS:
            os.environ[name] = sorted(accepted)[0]
            assert reader() is True
            os.environ[name] = "0"
            assert reader() is False
    finally:
        for name, (present, value) in before.items():
            if present:
                assert value is not None
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
    assert {
        name: (name in os.environ, os.environ.get(name))
        for name, _reader, _accepted in gate.FLAG_SPECS
    } == before


def _tree_bytes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _logical_dump(path: Path) -> tuple[str, ...]:
    connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return tuple(connection.iterdump())
    finally:
        connection.close()


def test_v1_enable_disable_reenable_preserves_exact_isolated_sidecar_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_root = tmp_path / "isolated-not-owner"
    monkeypatch.setattr(
        "core.control_plane.private_control_plane_runtime_dir",
        lambda: isolated_root,
    )
    original = os.environ.get(gate.CONTROL_PLANE_FLAG)
    originally_present = gate.CONTROL_PLANE_FLAG in os.environ
    try:
        os.environ[gate.CONTROL_PLANE_FLAG] = "true"
        first = ControlPlaneStore()
        first.initialize()
        assert first.is_open
        first.close()
        sidecar = isolated_root / "control_plane.sqlite3"
        assert sidecar.is_file()
        enabled_bytes = _tree_bytes(isolated_root)
        enabled_logical = _logical_dump(sidecar)

        os.environ[gate.CONTROL_PLANE_FLAG] = "false"
        disabled = ControlPlaneStore()
        with pytest.raises(ControlPlaneDisabled):
            disabled.initialize()
        disabled.close()
        assert sidecar.is_file()
        assert _tree_bytes(isolated_root) == enabled_bytes

        os.environ[gate.CONTROL_PLANE_FLAG] = "1"
        reopened = ControlPlaneStore()
        reopened.initialize()
        assert reopened.is_open
        reopened.close()
        assert sidecar.is_file()
        assert set(_tree_bytes(isolated_root)) == set(enabled_bytes)
        assert _logical_dump(sidecar) == enabled_logical
        assert first.path.parent == disabled.path.parent == reopened.path.parent == isolated_root
    finally:
        if originally_present:
            assert original is not None
            os.environ[gate.CONTROL_PLANE_FLAG] = original
        else:
            os.environ.pop(gate.CONTROL_PLANE_FLAG, None)


def test_r2_manifest_is_explicitly_non_self_hashing() -> None:
    assert gate.R2_MANIFEST.relative_to(gate.PROJECT).as_posix() not in gate.EXPECTED_R2_PATHS


def test_source_gate_passes_without_activation_or_external_anchor() -> None:
    result = gate.verify_all(require_process_flags_off=True)
    assert result["status"] == "P4_EXIT_CANDIDATE_R2_SOURCE_OK"
    assert result["activation"] is False
    assert result["e6_accepted"] is False
    assert result["r2_manifest_external_anchor"] is False
    assert len(result["flags_default_off"]) == 8
