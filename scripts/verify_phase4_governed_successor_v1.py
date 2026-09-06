"""Verify the current governed successor to the historical Phase 4 R3 gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from scripts import verify_phase4_exit_candidate_r3 as historical
from scripts.verify_legacy_evidence_retirement_v1 import (
    LegacyEvidenceRetirementError,
    classify_historical_artifact,
    verify_phase4_authority_succession,
)


PROJECT = Path(__file__).resolve().parents[1]
STATUS = "P4_GOVERNED_SUCCESSOR_V1_OK"


def _static_authority() -> list[str]:
    closure = historical.static_import_closure(
        historical.STARTUP_SOURCES, historical.PROJECT
    )
    modules = sorted(
        historical._module_name(path, historical.PROJECT) for path in closure
    )
    return sorted(module for module in modules if historical._is_authority(module))


def _fresh_import_authority(timeout_seconds: int = 45) -> list[str]:
    dependency_paths = sorted(
        {
            str(Path(value).resolve())
            for value in sys.path
            if value
            and Path(value).exists()
            and Path(value).resolve() != PROJECT.resolve()
        }
    )
    child = (
        "import importlib,json,socket,subprocess,sys\n"
        f"sys.path.insert(0,{str(PROJECT)!r})\n"
        f"sys.path[1:1]={dependency_paths!r}\n"
        "def blocked(*a,**k): raise RuntimeError('offline import probe blocked side effect')\n"
        "socket.create_connection=blocked\n"
        "socket.socket.connect=blocked\n"
        "class OfflinePopen(subprocess.Popen):\n"
        " def __init__(self,*a,**k): blocked(*a,**k)\n"
        "subprocess.Popen=OfflinePopen\n"
        f"targets={list(historical.STARTUP_MODULES)!r}\n"
        f"authority={sorted(historical.AUTHORITY_BEARING)!r}\n"
        "[importlib.import_module(name) for name in targets]\n"
        "seen=sorted(name for name in sys.modules if name in authority or any(name.startswith(x+'.') for x in authority))\n"
        "print('ONYX_P4_GOVERNED_SUCCESSOR '+json.dumps({'authority':seen},sort_keys=True))\n"
    )
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["QT_QPA_PLATFORM"] = "offscreen"
    for name, _reader, _accepted in historical.FLAG_SPECS:
        environment[name] = "0"
    result = subprocess.run(
        [sys.executable, "-I", "-c", child],
        cwd=PROJECT,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    marker = "ONYX_P4_GOVERNED_SUCCESSOR "
    line = next(
        (value for value in result.stdout.splitlines() if value.startswith(marker)),
        None,
    )
    if result.returncode or line is None:
        raise LegacyEvidenceRetirementError(
            f"governed successor import probe failed: exit={result.returncode}"
        )
    payload = json.loads(line[len(marker) :])
    authority = payload.get("authority")
    if type(authority) is not list or any(type(value) is not str for value in authority):
        raise LegacyEvidenceRetirementError("governed successor import shape drifted")
    return authority


def verify() -> dict[str, object]:
    historical_verifier = classify_historical_artifact(
        PROJECT,
        "scripts/verify_phase4_exit_candidate_r3.py",
        "763f5ad024ea9818e79a2dc581fab3a2fd873c97f1218e94db12d2b98439be52",
        historical_bytes=23165,
    )
    historical_tests = classify_historical_artifact(
        PROJECT,
        "tests/test_phase4_exit_candidate_r3.py",
        "d47e8e307738cc1e316d821f05b94d6b4458b2d5f8b4e0a276235a5e9c55c7af",
        historical_bytes=11070,
    )
    static = _static_authority()
    fresh = _fresh_import_authority()
    succession = verify_phase4_authority_succession(
        PROJECT,
        static_modules=static,
        fresh_import_modules=fresh,
    )
    return {
        "status": STATUS,
        "historical_gate": "P4_EXIT_CANDIDATE_R3_RETIRED",
        "historical_verifier_state": historical_verifier["state"],
        "historical_tests_state": historical_tests["state"],
        "static_authority": static,
        "fresh_import_authority": fresh,
        "succession": succession,
        "network_calls": 0,
        "offline_probe_processes": 1,
    }


def main() -> int:
    try:
        result = verify()
    except (LegacyEvidenceRetirementError, RuntimeError, OSError, ValueError) as exc:
        print(f"P4_GOVERNED_SUCCESSOR_V1_FAILED {exc}", file=sys.stderr)
        return 1
    print(f"{STATUS} {json.dumps(result, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
