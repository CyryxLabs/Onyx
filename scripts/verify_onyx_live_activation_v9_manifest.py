"""Verify the frozen Onyx Live Activation V9 candidate manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = (
    ROOT / "docs" / "onyx" / "checkpoints" / "onyx-live-activation-v9" / "manifest.json"
)
EXPECTED_MANIFEST_SHA256 = (
    "38de625b7725dab7aa9c7906f7f3164687f1f20a0cca6e683fe64145bb53142a"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    if sha256(MANIFEST) != EXPECTED_MANIFEST_SHA256:
        raise RuntimeError("V9 candidate manifest drift")
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if document.get("schema") != "onyx.live-activation.v9":
        raise RuntimeError("unexpected V9 manifest schema")
    if document.get("status") != "candidate-ready-for-independent-gate":
        raise RuntimeError("V9 candidate status is not gate-ready")
    if document.get("default_off") is not True:
        raise RuntimeError("V9 candidate must remain default-off")
    if document.get("live_activated") is not False:
        raise RuntimeError("V9 candidate records an unexpected live activation")
    for record in document.get("files", ()):
        path = ROOT / record["path"]
        if not path.is_file() or sha256(path) != record["sha256"]:
            raise RuntimeError(f"V9 manifest file drift: {record['path']}")
    print("ONYX_LIVE_ACTIVATION_V9_MANIFEST_OK")
    print(f"manifest_sha256={EXPECTED_MANIFEST_SHA256} files={len(document['files'])}")


if __name__ == "__main__":
    run()
