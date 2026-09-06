"""Verify the isolated Gemini Live compatibility V1 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/checkpoints/phase6-gemini-live-compat-v1/manifest.json"
FROZEN = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "core/live_model.py": "57e9b99a31d82a7ed157968a78669b148c877de3cc803616219c6e8406647b72",
    "core/phase6_agentic_core_v6.py": "38f68d7dd8eb04fe7c9caa956db5a52d0a96426bab6a45f07b96e67e45d8001a",
    "core/phase6_live_integration_v2.py": "e3194a0d8e206d33218bc8291cbd518788e8dfb3931adfd2f067908655d409b5",
    "core/phase6_live_wiring_v1.py": "a658f430c10bb992724ad7bbd2ddae94b3c83f8893608fe724b241302b55d55f",
    "core/onyx_live_activation_v9.py": "deb26314ef3871cb12fc8e3cee936f88e385122fad242c830580421ccb22a9d2",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_root(items: list[dict[str, object]]) -> str:
    payload = "".join(
        f"{item['path']}\0{item['sha256']}\n"
        for item in sorted(items, key=lambda item: str(item["path"]))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify() -> dict[str, object]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert data["schema"] == "OnyxPhase6GeminiLiveCompat.v1"
    assert data["candidate"] == "phase6-gemini-live-compat-candidate-003"
    assert data["supersedes"]["candidate"] == "phase6-gemini-live-compat-candidate-002"
    assert data["supersedes"]["disposition"] == "rejected_before_e6_never_live"
    assert data["status"] == "candidate_default_off_not_live"
    assert data["activation"]["exact"] == "ONYX_PHASE6_GEMINI_LIVE_COMPAT_V1=1"
    for path, expected in FROZEN.items():
        assert digest(ROOT / path) == expected
    for item in data["artifacts"]:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert digest(path) == item["sha256"]
    assert data["artifact_root_algorithm"] == "sha256-sorted-path-nul-digest-lf-v1"
    assert artifact_root(data["artifacts"]) == data["artifact_root_sha256"]
    assert data["contracts"]["host_config_identity_passthrough"] is True
    assert data["contracts"]["system_instruction_content_persisted"] is False
    assert data["contracts"]["send_realtime_input_keyword"] == "media"
    assert data["verification"]["network_calls"] == 0
    assert data["verification"]["live_activation"] is False
    assert data["verification"]["e6"] == "not_performed"
    source = (ROOT / "core/phase6_gemini_live_compat_v1.py").read_text(encoding="utf-8")
    assert "llm_client" not in source and "client.aio.live.connect" in source
    assert "config=self.config" in source
    assert "system_instruction" in source and "repr(event)" not in source
    host_tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    wrapper_tree = ast.parse(source)
    host_realtime = [
        node
        for node in ast.walk(host_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_realtime_input"
    ]
    wrappers = [
        node
        for node in ast.walk(wrapper_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "send_realtime_input"
    ]
    assert host_realtime and len(wrappers) == 1
    host_keywords = {keyword.arg for keyword in host_realtime[0].keywords}
    wrapper = wrappers[0]
    assert [argument.arg for argument in wrapper.args.kwonlyargs] == ["media"]
    assert not wrapper.args.args[1:]
    wrapper_calls = [
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "send_realtime_input"
    ]
    assert len(wrapper_calls) == 1
    wrapper_keywords = {keyword.arg for keyword in wrapper_calls[0].keywords}
    assert host_keywords == wrapper_keywords == {"media"}
    assert "audio" not in host_keywords | wrapper_keywords
    result = subprocess.run(
        [
            str(ROOT / ".venv/Scripts/python.exe"),
            "-B",
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            ".pytest-gemini-live-v1-verify",
            "tests/test_phase6_gemini_live_compat_v1.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0 and "11 passed" in result.stdout
    return {"artifacts": len(data["artifacts"]), "network_calls": 0, "live": False}


if __name__ == "__main__":
    print("P6_GEMINI_LIVE_COMPAT_V1_OK", json.dumps(verify(), sort_keys=True))
