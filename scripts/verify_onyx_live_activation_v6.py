"""Independent cumulative gate for the isolated Onyx Live V6 candidate."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
GATES = (
    ("host", ROOT / "scripts" / "verify_onyx_live_activation_v6_host.py", "ONYX_LIVE_ACTIVATION_V6_REAL_HOST_OK"),
    ("provider", ROOT / "scripts" / "verify_onyx_live_activation_v6_provider.py", "ONYX_LIVE_ACTIVATION_V6_FAKE_PROVIDER_OK"),
    ("qt", ROOT / "scripts" / "verify_onyx_live_activation_v6_qt.py", "ONYX_LIVE_ACTIVATION_V6_QT_OK"),
)
FROZEN = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "core/onyx_live_activation_v4.py": "2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b",
    "core/onyx_live_activation_v5.py": "5c110ae3af5172ba5de5f1f6711a214f24bbaee30b9ea33b863272a83a36bba6",
    "scripts/launch_onyx_live_v5.pyw": "1b468782ad6d1784eaaad5e188a63a84ff00e52505ef1602cca01c6b320c98a1",
    "scripts/verify_onyx_live_activation_v5.py": "84031b50fc16779b9c7690d1080e56cb16f8d327f83ac8c4a0368bbd772d25a3",
    "scripts/verify_onyx_live_activation_v5_host.py": "13abfbc24771d551f37c6a30276823854bbf2ccdcb262fa8294c5f9100a660e6",
    "scripts/verify_onyx_live_activation_v5_provider.py": "9385dc07fb2b4dc8df2898a9efa1f32de9969e9172b8f2edfc77d662c85cfa65",
    "scripts/verify_onyx_live_activation_v5_qt.py": "f816e1c90fcae9295191bc02e99e52770e2b874947232dd6d8fc987ac9410105",
    "tests/test_onyx_live_activation_v5.py": "7fdf6b5dcdf122b351bf5f77c25bfa3784fd8de38876c6790e31719316f2bf64",
    "docs/onyx/checkpoints/onyx-live-activation-v5/ONYX_LIVE_ACTIVATION_V5_CHECKPOINT.md": "e5873466d08df0c27d81768188bf04853abc063c39aae4ed2845a34f9ef9b929",
    "docs/onyx/checkpoints/onyx-live-activation-v5/manifest.json": "c303807772bad3bab16ff6b86c5ab9ec74caa55aa2c33669866cb9a93e898015",
}


def active_environment():
    from core.onyx_live_activation_v6 import exact_activation_environment

    result = dict(os.environ)
    for version in range(4, 7):
        result.pop(f"ONYX_LIVE_ACTIVATION_V{version}", None)
        result.pop(f"ONYX_LIVE_ROLLBACK_V{version}", None)
    result.update(exact_activation_environment())
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
    return result


def run():
    for relative, expected in FROZEN.items():
        observed = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        if observed != expected:
            raise RuntimeError(f"frozen byte drift: {relative}")
    compile_files = [
        ROOT / "core" / "onyx_live_activation_v6.py",
        ROOT / "scripts" / "launch_onyx_live_v6.pyw",
        ROOT / "scripts" / "verify_onyx_live_activation_v6_host.py",
        ROOT / "scripts" / "verify_onyx_live_activation_v6_provider.py",
        ROOT / "scripts" / "verify_onyx_live_activation_v6_qt.py",
        ROOT / "tests" / "test_onyx_live_activation_v6.py",
    ]
    compiled = subprocess.run(
        [str(PYTHON), "-B", "-m", "py_compile", *map(str, compile_files)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=90,
        check=False,
    )
    if compiled.returncode:
        raise RuntimeError(compiled.stderr or compiled.stdout)
    outputs = []
    for name, path, marker in GATES:
        result = subprocess.run(
            [str(PYTHON), "-B", str(path)],
            cwd=ROOT,
            env=active_environment(),
            text=True,
            capture_output=True,
            timeout=300,
            check=False,
        )
        if result.returncode or marker not in result.stdout:
            raise RuntimeError(f"{name} gate failed\n{result.stdout}\n{result.stderr}")
        outputs.append(name)
    print("ONYX_LIVE_ACTIVATION_V6_CUMULATIVE_OK")
    print(
        "gates=" + ",".join(outputs) + " frozen_v5_host=12 "
        "network_calls=0 provider=fake-only live_activation=not_performed"
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    run()
