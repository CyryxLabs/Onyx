"""Generate the additive packaged-runtime HUD contract V2 manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.onyx_packaged_runtime_hud_contract_v2 import (  # noqa: E402
    MANIFEST_RELATIVE,
    REQUIRED_HOST_PORTS,
)

V1 = ROOT / "core/onyx_packaged_runtime_hud_contract_v1.manifest.json"
V1_SHA256 = "ffcd839564e211f62fc446858eb915eb60182725287cadae8f286a9a3aeb5360"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_root(records: list[dict[str, str]]) -> str:
    material = "".join(f"{item['path']}\0{item['sha256']}\n" for item in sorted(records, key=lambda item: item["path"])).encode()
    return hashlib.sha256(material).hexdigest()


def main() -> None:
    if sha(V1) != V1_SHA256:
        raise RuntimeError("packaged-runtime V1 predecessor drifted")
    prior = json.loads(V1.read_text(encoding="utf-8"))
    paths = {item["path"] for item in prior["required_files"] if "tests" not in Path(item["path"]).parts}
    paths.update(REQUIRED_HOST_PORTS)
    paths.add("core/onyx_packaged_runtime_hud_contract_v2.manifest.json")
    paths.discard("core/onyx_packaged_runtime_hud_contract_v2.manifest.json")
    records = []
    for relative in sorted(paths):
        source = ROOT / relative
        if relative == ".venv/Scripts/pythonw.exe":
            source = ROOT / "packaging/compat/venvwlauncher-python313-x64.exe"
        if relative == ".venv/PSF-LICENSE.txt":
            source = ROOT / "packaging/compat/PSF-LICENSE.txt"
        records.append({"path": relative, "sha256": sha(source)})
    payload = {"schema": "onyx.packaged-runtime-hud.v2", "predecessor": {"path": "core/onyx_packaged_runtime_hud_contract_v1.manifest.json", "sha256": V1_SHA256}, "required_files": records, "required_host_ports": sorted(REQUIRED_HOST_PORTS), "artifact_root_sha256": artifact_root(records), "semantics": {"capability_smoke": "provider-free-explicit", "checkout_fallback": False, "provider_dispatch": False, "tests_in_runtime": False}}
    (ROOT / MANIFEST_RELATIVE).write_text(json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
