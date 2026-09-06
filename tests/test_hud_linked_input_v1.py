"""Physical input rejection over authentic HUD48/package17 temporary closures.

No historical pins, verifier functions, UI selectors or host capabilities are
patched. Every negative starts with a successful real verification of the same
temporary copy. Link tests report a skip only for OS capability/permission
refusals; missing and replaced-byte tests do not require symlink privileges.
These tests exercise changes between invocations, not concurrent TOCTOU safety.
"""

from __future__ import annotations

import errno
import json
import shutil
from pathlib import Path

import pytest

from core import onyx_hud_current_acceptance_v48 as hud
from core import onyx_packaged_runtime_hud_contract_v17 as packaged


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path("qml/OnyxLiveShellV16.qml")


@pytest.fixture(
    params=[
        pytest.param(
            (hud, hud.verify_current_hud_acceptance, hud.CurrentHudAcceptanceV48Error),
            id="hud48",
        ),
        pytest.param(
            (
                packaged,
                packaged.verify_packaged_runtime_hud_contract,
                packaged.PackagedRuntimeHudContractV17Error,
            ),
            id="package17",
        ),
    ]
)
def accepted_copy(request, tmp_path):
    module, verify, error = request.param
    manifest = json.loads((ROOT / module.MANIFEST_RELATIVE).read_bytes())
    inputs = tuple(Path(row["path"]) for row in manifest["runtime_inputs"])
    assert len(inputs) == len(set(inputs)) == 10
    assert RUNTIME in inputs
    predecessor = (
        module.PREDECESSOR_ACCEPTANCE if module is hud else module.PREDECESSOR_MODULE
    )
    paths = {
        module.MANIFEST_RELATIVE,
        module.PREDECESSOR_MANIFEST,
        predecessor,
        *inputs,
    }
    root = tmp_path / "accepted"
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    result = verify(root)
    assert result["runtime_inputs"] == 10
    assert result["primary_layout_changed"] is False
    assert result["live_renderer"] == "three.js-webgl"
    assert result["published" if module is hud else "formal_release_ready"] is False
    return root, verify, error, inputs


def _physical_link(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        # Never turn path bugs, collisions or arbitrary IO errors into a pass.
        if getattr(exc, "winerror", None) in {1, 5, 50, 1314} or exc.errno in {
            errno.EACCES,
            errno.EPERM,
            errno.ENOSYS,
            errno.ENOTSUP,
        }:
            pytest.skip(
                "physical symlink capability unavailable: "
                f"errno={exc.errno}, winerror={getattr(exc, 'winerror', None)}"
            )
        raise
    assert link.is_symlink()


@pytest.mark.parametrize("runtime_index", range(10))
def test_rejects_each_linked_runtime_input_after_real_acceptance(
    accepted_copy, runtime_index
):
    root, verify, error, inputs = accepted_copy
    runtime = root / inputs[runtime_index]
    original = runtime.read_bytes()
    relocated = root / "relocated-runtime.bin"
    runtime.rename(relocated)
    _physical_link(runtime, relocated)
    assert relocated.read_bytes() == original
    with pytest.raises(error, match="input is linked"):
        verify(root)


def test_rejects_linked_runtime_ancestor_after_real_acceptance(accepted_copy):
    root, verify, error, _inputs = accepted_copy
    qml = root / "qml"
    relocated = root / "relocated-qml"
    qml.rename(relocated)
    _physical_link(qml, relocated, directory=True)
    assert not (root / RUNTIME).is_symlink()  # Only the ancestor is linked.
    with pytest.raises(error, match="input is linked"):
        verify(root)


def test_rejects_runtime_link_escaping_copy_after_real_acceptance(accepted_copy):
    root, verify, error, _inputs = accepted_copy
    runtime = root / RUNTIME
    outside = root.parent / "outside-runtime.qml"
    runtime.rename(outside)
    _physical_link(runtime, outside)
    with pytest.raises(error, match="input unavailable"):
        verify(root)


def test_rejects_dangling_runtime_link_after_real_acceptance(accepted_copy):
    root, verify, error, _inputs = accepted_copy
    runtime = root / RUNTIME
    runtime.rename(root / "preserved-runtime.qml")
    _physical_link(runtime, root / "nonexistent-runtime.qml")
    with pytest.raises(error, match="input unavailable"):
        verify(root)


def test_rejects_missing_runtime_input_after_real_acceptance(accepted_copy):
    root, verify, error, _inputs = accepted_copy
    (root / RUNTIME).rename(root / "preserved-runtime.qml")
    with pytest.raises(error, match="input unavailable"):
        verify(root)


def test_rejects_replaced_runtime_bytes_after_prior_pass(accepted_copy):
    root, verify, error, _inputs = accepted_copy
    runtime = root / RUNTIME
    original = runtime.read_bytes()
    runtime.rename(root / "preserved-runtime.qml")
    runtime.write_bytes(original + b"\n// synthetic replacement\n")
    assert not runtime.is_symlink()
    with pytest.raises(error, match="input drifted: qml/OnyxLiveShellV16.qml"):
        verify(root)
