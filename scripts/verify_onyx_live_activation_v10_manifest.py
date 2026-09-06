"""Verify the frozen default-off Activation V10 C002 candidate manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/onyx/checkpoints/onyx-live-activation-v10/manifest.json"
EXPECTED = "b22459a5315370f179089cf67d501a687305c2147d2c68ef132575326d47e236"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run() -> None:
    if digest(MANIFEST) != EXPECTED:
        raise RuntimeError("V10 candidate manifest drift")
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if (
        payload.get("candidate") != "onyx-live-activation-v10-c003"
        or payload.get("status") != "candidate-ready-external-gate"
        or payload.get("default_off") is not True
        or payload.get("live_activated") is not False
        or payload.get("live_wiring") is not False
        or payload.get("planned_composition", {}).get("total_transactional_seams") != 35
        or payload.get("verification", {}).get("focused") != {"passed": 33, "failed": 0}
    ):
        raise RuntimeError("V10 C003 status drift")
    for record in payload["files"]:
        path = ROOT / record["path"]
        if not path.is_file() or digest(path) != record["sha256"]:
            raise RuntimeError(f"V10 manifest file drift: {record['path']}")
    rows = sorted(payload["files"], key=lambda record: record["path"])
    material = "".join(
        f"{record['path']}\0{record['sha256']}\n" for record in rows
    ).encode()
    artifact_root = hashlib.sha256(material).hexdigest()
    if (
        payload.get("artifact_root_algorithm") != "sha256-sorted-path-nul-digest-lf-v1"
        or payload.get("artifact_root_sha256") != artifact_root
    ):
        raise RuntimeError("V10 C003 artifact root drift")
    hud = payload.get("accepted_hud_v7_c003")
    if (
        type(hud) is not dict
        or hud.get("binding_count") != 4
        or hud.get("exact_true_required") is not True
        or hud.get("decision") != "accepted"
        or hud.get("findings") != {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    ):
        raise RuntimeError("accepted HUD V7 C003 envelope drift")
    print("ONYX_LIVE_ACTIVATION_V10_C003_MANIFEST_OK")
    print(
        f"manifest_sha256={EXPECTED} files={len(payload['files'])} "
        f"artifact_root_sha256={artifact_root} "
        "status=candidate-ready-external-gate live_activation=not_performed"
    )


if __name__ == "__main__":
    run()
