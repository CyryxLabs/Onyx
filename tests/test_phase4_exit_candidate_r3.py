"""R3 source-boundary, scope-closure, evidence-DAG and rollback tests."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from core.control_plane import ControlPlaneDisabled, ControlPlaneStore
from scripts import verify_phase4_exit_candidate_r3 as gate


def _write(path: Path, body: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))


@pytest.mark.parametrize(
    "source",
    [
        "from core import control_plane_v5 as extension\n",
        "loader=__import__; loader('core.control_plane_v5')\n",
        "import builtins as b; loader=b.__import__; loader('core.control_plane_v5')\n",
        "import importlib as i; i.import_module('core.control_plane_v5')\n",
        "from importlib import import_module as load; load('core.control_plane_v5')\n",
        "import runpy as r; r.run_module('core.control_plane_v5')\n",
        "runner=exec; runner('import core.control_plane_v5')\n",
        "runner=eval; runner(\"__import__('core.control_plane_v5')\")\n",
        "plugins={'service':'control_plane_v5'}\n",
        "getattr(core, 'control_plane_v5')\n",
        "registry['control_plane_v5']\n",
        "Path('core/control_plane_v5.py').read_text()\n",
        "open('core\\\\control_plane_v5.py').read()\n",
        "subprocess.run(['python','-m','core.control_plane_v5'])\n",
        "subprocess.Popen(['python','core/control_plane_v5.py'])\n",
    ],
)
def test_raw_token_policy_rejects_all_r2_bypass_families(
    tmp_path: Path, source: str
) -> None:
    startup = tmp_path / "startup.py"
    _write(startup, source)
    with pytest.raises(RuntimeError, match="authority token forbidden"):
        gate.verify_root_token_policy((startup,))


def test_external_or_missing_startup_path_fails_closed_without_relative_crash() -> None:
    with tempfile.TemporaryDirectory(prefix="onyx-r3-external-") as temporary:
        startup = Path(temporary) / "startup.py"
        _write(startup, "plugins={'service':'control_plane_v5'}\n")
        with pytest.raises(RuntimeError, match="authority token forbidden") as raised:
            gate.verify_root_token_policy((startup,))
        assert startup.resolve().as_posix() in str(raised.value)
    missing = gate.PROJECT.parent / "missing-r3-startup.py"
    with pytest.raises(RuntimeError, match="missing startup source") as raised:
        gate.verify_root_token_policy((missing,))
    assert "ValueError" not in str(raised.value)


def test_static_transitive_closure_rejects_authority_but_allows_native_vault(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "main.py", "import bridge\n")
    _write(tmp_path / "bridge.py", "from core import control_plane_v5\n")
    _write(tmp_path / "core/__init__.py", "")
    _write(tmp_path / "core/control_plane_v5.py", "")
    with pytest.raises(RuntimeError, match="authority-bearing module"):
        gate.verify_static_authority_closure((tmp_path / "main.py",), tmp_path)

    _write(tmp_path / "bridge.py", "from core import native_vault\n")
    _write(tmp_path / "core/native_vault.py", "")
    result = gate.verify_static_authority_closure((tmp_path / "main.py",), tmp_path)
    assert result["native_vault_present"] is True


def test_current_static_closure_and_guarded_fresh_import_are_authority_free() -> None:
    """Retained node ID: the historical verifier must reject the governed host."""

    assert "core.native_vault" not in gate.AUTHORITY_BEARING
    with pytest.raises(RuntimeError, match="authority-bearing module"):
        gate.verify_static_authority_closure()
    with pytest.raises(RuntimeError, match="fresh startup import probe failed"):
        gate.verify_fresh_import_probe()


def test_selection_sources_are_all_in_r10_union_r3_and_missing_source_denies(
    tmp_path: Path,
) -> None:
    result = gate.verify_selection_scope()
    assert result["nodes"] == 17
    r10 = gate._manifest_paths(gate.R10_MANIFEST)
    assert "tests/test_control_plane.py" not in r10
    assert "tests/test_workspace_registry.py" not in r10
    assert {
        "tests/test_control_plane.py",
        "tests/test_workspace_registry.py",
    } <= gate.R3_SOURCE_PATHS

    selection = tmp_path / "selection.txt"
    _write(selection, "tests/test_regressions.py::RegressionTests\n")
    with pytest.raises(RuntimeError, match=r"absent from R10\+R3"):
        gate.verify_selection_scope(selection=selection)


def _records(root: Path, paths: set[str] | frozenset[str]) -> dict[str, str]:
    return {
        relative: hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in paths
    }


def _manifest(path: Path, records: dict[str, str]) -> None:
    _write(
        path,
        "".join(
            f"{digest} *{relative}\n" for relative, digest in sorted(records.items())
        ),
    )


@pytest.fixture
def synthetic_dag(tmp_path: Path):
    evidence_paths = frozenset(
        {
            "out/bundle.json",
            "out/source.json",
            "out/junit.xml",
            "out/pytest.log",
            "out/static.log",
        }
    )
    source_paths = frozenset(
        {
            "src/verifier.py",
            "src/tests.py",
            "src/selection.txt",
            "src/checkpoint.md",
            "src/evidence.sha256",
        }
    )
    for relative in evidence_paths:
        _write(tmp_path / relative, f"artifact:{relative}\n")
    evidence_manifest = tmp_path / "src/evidence.sha256"
    _manifest(evidence_manifest, _records(tmp_path, evidence_paths))
    for relative in source_paths - {"src/evidence.sha256"}:
        _write(tmp_path / relative, f"source:{relative}\n")
    source_manifest = tmp_path / "source.sha256"
    _manifest(source_manifest, _records(tmp_path, source_paths))
    return tmp_path, source_manifest, source_paths, evidence_manifest, evidence_paths


def test_synthetic_two_manifest_dag_reconstructs_without_self_hash(
    synthetic_dag,
) -> None:
    root, source_manifest, source_paths, evidence_manifest, evidence_paths = (
        synthetic_dag
    )
    assert gate.verify_manifest(evidence_manifest, evidence_paths, root=root)[0] == 5
    assert gate.verify_manifest(source_manifest, source_paths, root=root)[0] == 5
    assert "source.sha256" not in source_paths
    assert "src/evidence.sha256" not in evidence_paths


@pytest.mark.parametrize(
    "artifact",
    [
        "out/bundle.json",
        "out/source.json",
        "out/junit.xml",
        "out/pytest.log",
        "out/static.log",
    ],
)
def test_each_evidence_artifact_tamper_fails(synthetic_dag, artifact: str) -> None:
    root, _source_manifest, _source_paths, evidence_manifest, evidence_paths = (
        synthetic_dag
    )
    (root / artifact).write_bytes(b"tampered\n")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        gate.verify_manifest(evidence_manifest, evidence_paths, root=root)


def test_evidence_manifest_tamper_breaks_source_manifest(synthetic_dag) -> None:
    root, source_manifest, source_paths, evidence_manifest, _evidence_paths = (
        synthetic_dag
    )
    evidence_manifest.write_bytes(evidence_manifest.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        gate.verify_manifest(source_manifest, source_paths, root=root)


def test_source_input_tamper_breaks_source_manifest(synthetic_dag) -> None:
    root, source_manifest, source_paths, _evidence_manifest, _evidence_paths = (
        synthetic_dag
    )
    _write(root / "src/verifier.py", "tampered\n")
    with pytest.raises(RuntimeError, match="digest mismatch"):
        gate.verify_manifest(source_manifest, source_paths, root=root)


@pytest.mark.parametrize("which", ["source", "evidence"])
@pytest.mark.parametrize("fault", ["bom", "crlf", "order", "malformed"])
def test_both_manifests_reject_noncanonical_encoding_order_and_format(
    synthetic_dag, which: str, fault: str
) -> None:
    root, source_manifest, source_paths, evidence_manifest, evidence_paths = (
        synthetic_dag
    )
    manifest, paths = (
        (source_manifest, source_paths)
        if which == "source"
        else (evidence_manifest, evidence_paths)
    )
    records = _records(root, paths)
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
    manifest.write_bytes(raw)
    with pytest.raises(RuntimeError, match="manifest"):
        gate.verify_manifest(manifest, paths, root=root)


def test_all_flag_readers_on_off_and_environment_restore() -> None:
    before = {
        name: (name in os.environ, os.environ.get(name))
        for name, _r, _a in gate.FLAG_SPECS
    }
    try:
        for name, reader, accepted in gate.FLAG_SPECS:
            os.environ[name] = sorted(accepted)[0]
            assert reader()
            os.environ[name] = "0"
            assert not reader()
    finally:
        for name, (present, value) in before.items():
            if present:
                assert value is not None
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
    assert {
        name: (name in os.environ, os.environ.get(name))
        for name, _r, _a in gate.FLAG_SPECS
    } == before


def _tree_hashes(root: Path) -> dict[str, str]:
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


def test_v1_disable_preserves_bytes_then_reenable_preserves_logical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "isolated-not-owner"
    monkeypatch.setattr(
        "core.control_plane.private_control_plane_runtime_dir", lambda: root
    )
    before = (
        gate.CONTROL_PLANE_FLAG in os.environ,
        os.environ.get(gate.CONTROL_PLANE_FLAG),
    )
    try:
        os.environ[gate.CONTROL_PLANE_FLAG] = "true"
        first = ControlPlaneStore().initialize()
        first.close()
        sidecar = root / "control_plane.sqlite3"
        raw = _tree_hashes(root)
        logical = _logical_dump(sidecar)
        os.environ[gate.CONTROL_PLANE_FLAG] = "0"
        with pytest.raises(ControlPlaneDisabled):
            ControlPlaneStore().initialize()
        assert _tree_hashes(root) == raw
        os.environ[gate.CONTROL_PLANE_FLAG] = "1"
        reopened = ControlPlaneStore().initialize()
        reopened.close()
        assert _logical_dump(sidecar) == logical
    finally:
        if before[0]:
            assert before[1] is not None
            os.environ[gate.CONTROL_PLANE_FLAG] = before[1]
        else:
            os.environ.pop(gate.CONTROL_PLANE_FLAG, None)


def test_source_only_gate_is_current_and_nonactivating() -> None:
    """Retained node ID: the frozen R3 inventory must reject the current tree."""

    with pytest.raises(RuntimeError, match="manifest closure mismatch"):
        gate.verify_source_only()
