"""Independent cumulative gate for the isolated Onyx Live V5 candidate."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
GATES = (
    ("host", ROOT / "scripts" / "verify_onyx_live_activation_v5_host.py", "ONYX_LIVE_ACTIVATION_V5_REAL_HOST_OK"),
    ("provider", ROOT / "scripts" / "verify_onyx_live_activation_v5_provider.py", "ONYX_LIVE_ACTIVATION_V5_FAKE_PROVIDER_OK"),
    ("qt", ROOT / "scripts" / "verify_onyx_live_activation_v5_qt.py", "ONYX_LIVE_ACTIVATION_V5_QT_OK"),
)
FROZEN = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
    "core/onyx_live_activation_v4.py": "2521b5dcf53172e73e23219e9266037f7312a233ef135281a1a2ac3660aec05b",
    "scripts/launch_onyx_live_v4.pyw": "a7bfc190cb95d49e871fcd312f32badbd1a5a6d18393ca725d214f1f66769af8",
    "scripts/verify_onyx_live_activation_v4.py": "20426a7fd2e592dfa54b2a352928a941e01bd7798314bb3d21363a9c0e6bd597",
    "scripts/verify_onyx_live_activation_v4_host.py": "e1e53cee11d1fbaf460d8690f9131da56c9773e75ffbd286345395c969fe2105",
    "scripts/verify_onyx_live_activation_v4_qt.py": "19015ebf96a32e449709831d86d90465e612ba63f770bea917f01dd21ab3b95b",
    "tests/test_onyx_live_activation_v4.py": "4c776af560a7f3bfd470bef91d205fddbe509c6c767cbaad2b754f3023068783",
    "docs/onyx/checkpoints/onyx-live-activation-v4/ONYX_LIVE_ACTIVATION_V4_CHECKPOINT.md": "3ea17bf227025f7dbe2ce4f91e15801151c6262efc01173657e7c3ce481d638f",
    "docs/onyx/checkpoints/onyx-live-activation-v4/manifest.json": "ebe3b24e641d1148e3ddb3767705b593a0d9df0898ba2654b53cd7820e0d6c09",
}


def active_environment():
    from core.onyx_live_activation_v5 import exact_activation_environment

    result = dict(os.environ)
    for name in (
        "ONYX_LIVE_ACTIVATION_V4",
        "ONYX_LIVE_ROLLBACK_V4",
        "ONYX_LIVE_ACTIVATION_V5",
        "ONYX_LIVE_ROLLBACK_V5",
    ):
        result.pop(name, None)
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
        ROOT / "core" / "onyx_live_activation_v5.py",
        ROOT / "scripts" / "launch_onyx_live_v5.pyw",
        ROOT / "scripts" / "verify_onyx_live_activation_v5_host.py",
        ROOT / "scripts" / "verify_onyx_live_activation_v5_provider.py",
        ROOT / "scripts" / "verify_onyx_live_activation_v5_qt.py",
        ROOT / "tests" / "test_onyx_live_activation_v5.py",
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
            timeout=180,
            check=False,
        )
        if result.returncode or marker not in result.stdout:
            raise RuntimeError(f"{name} gate failed\n{result.stdout}\n{result.stderr}")
        outputs.append(name)

    print("ONYX_LIVE_ACTIVATION_V5_CUMULATIVE_OK")
    print(
        "gates=" + ",".join(outputs) + " frozen_v4_host=10 "
        "network_calls=0 provider=fake-only live_activation=not_performed"
    )


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    run()
