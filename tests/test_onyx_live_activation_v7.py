from __future__ import annotations

import hashlib
import os
import runpy
import subprocess
from pathlib import Path

import pytest

from core import onyx_live_activation_v7 as live


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v7.pyw"
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v7_host.py"
PHASE5_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v7_provider.py"


def clean_environment() -> dict[str, str]:
    result = dict(os.environ)
    for version in range(4, 8):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    for name in (*live.PHASE5_IDENTITY_FLAGS, *live.PHASE5_IDENTITY_ALIASES):
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def active_environment() -> dict[str, str]:
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_v7_launcher_requires_exact_four_identities_and_rejects_aliases():
    mode = runpy.run_path(str(LAUNCHER), run_name="v7_launcher_test")["_launch_mode"]
    active = live.exact_activation_environment()
    assert mode({}) == "legacy"
    assert mode(active) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    for name in (
        live.LIVE_MASTER_FLAG,
        *live.CHILD_FLAGS,
        *live.PHASE5_IDENTITY_FLAGS,
    ):
        partial = dict(active)
        partial.pop(name)
        assert mode(partial) == "refuse"
    for name in live.PHASE5_IDENTITY_FLAGS:
        wrong = dict(active)
        wrong[name] += "-wrong"
        assert mode(wrong) == "refuse"
        with pytest.raises(live.ActivationV7Error):
            live.ActivationFlagsV7.from_canonical_environ(wrong)
    for alias in live.PHASE5_IDENTITY_ALIASES:
        aliased = dict(active)
        aliased[alias] = "onyx-owner"
        assert mode(aliased) == "refuse"
        with pytest.raises(live.ActivationV7Error):
            live.ActivationFlagsV7.from_canonical_environ(aliased)


def test_v7_preimport_refusal_is_clean():
    environment = clean_environment()
    environment[live.LIVE_MASTER_FLAG] = "1"
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert "ONYX_LIVE_V7_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_v7_actual_host_preflight_materializes_real_phase5_bridge_without_network():
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ONYX_LIVE_V7_HOST_PREFLIGHT_OK" in result.stdout
    assert "bridge=core.phase5_integration_v3.Phase5IntegrationV3" in result.stdout
    assert "network_calls=0" in result.stdout


def _run_gate(path: Path, marker: str, detail: str) -> None:
    result = subprocess.run(
        [str(PYTHON), "-B", str(path)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout
    assert detail in result.stdout


def test_v7_host_gate():
    _run_gate(HOST_GATE, "ONYX_LIVE_ACTIVATION_V7_HOST_OK", "canonical_identities=4")


def test_v7_phase5_ready_local_catalog_read_survives_reconnect():
    _run_gate(
        PHASE5_GATE,
        "ONYX_LIVE_ACTIVATION_V7_PHASE5_E2E_OK",
        "local_catalog_reads=1",
    )


def test_v6_bytes_are_frozen():
    expected = {
        "core/onyx_live_activation_v6.py": "68d75e89728355b6b26b153f19ec5d732f26369b79d7e03e700bc8b00ee95f54",
        "scripts/launch_onyx_live_v6.pyw": "de6aff494b5c9c22dc93e209c50cfa5710a6d7012b217d263c22bca3076eeb0f",
        "scripts/launch_onyx_live_v6_active.cmd": "525aa4d5e156dcda0bdd72fe3dfe5d429d3d658a495e249ef9235940528e587e",
        "scripts/launch_onyx_live_v6_rollback.cmd": "05818c5fd17e923d009fc408a834dbb2dd53dc48b9a296cd141ab1a4da40eb94",
        "scripts/verify_onyx_live_activation_v6.py": "58d94c7f2ef3e37b64494da07102a765575bb512a0c250c7c9b4d806dd463c02",
        "scripts/verify_onyx_live_activation_v6_manifest.py": "685bcf55f7baa688c32dfd348f9085e3edd6deef25b2109b83d16a9a9923e88a",
        "scripts/verify_onyx_live_activation_v6_host.py": "9601395112ef21cacd09bfb9b52dbcce378757dbcb3fd5b9d87ea86ff41889b9",
        "scripts/verify_onyx_live_activation_v6_provider.py": "beabad244a69372fcb19de2d1229d4d9882aa49d83948b3c5d336d86e2f7a510",
        "scripts/verify_onyx_live_activation_v6_qt.py": "881c8ee51537f18c2b83f7bf8f77a8783482a735a05bf1f926a0f4649407b9e9",
        "tests/test_onyx_live_activation_v6.py": "0eed5cad48d30d38523e50b0ce6081762175d84b29e0e062ad2400b26a1bd565",
        "docs/onyx/checkpoints/onyx-live-activation-v6/ONYX_LIVE_ACTIVATION_V6_CHECKPOINT.md": "51cb9fd819b89f5e70eed4f7275c05a8a4b6a9557ae7985ea12982a5a7780495",
        "docs/onyx/checkpoints/onyx-live-activation-v6/manifest.json": "4b7b3bcdb7c87043e97baa952b883dcfc9f498026c272099f5222de7decb4453",
    }
    for relative, digest in expected.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
