"""Direct current-release verifier for the source-to-frozen HUD closure."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))


def verify_runtime_inputs(project: Path = PROJECT) -> dict[str, object]:
    """Authenticate every V26 source input, including the anchored manifest."""

    from core.onyx_hud_current_acceptance_v26 import verify_current_hud_acceptance

    return verify_current_hud_acceptance(Path(project))


def verify_current_release() -> dict[str, object]:
    """Authenticate the current release receipt and its transitive runtime."""

    from scripts.verify_release_workflow_v33 import verify_release_workflow_v33

    verified = verify_release_workflow_v33(PROJECT)
    transition = verified["transition"]
    runtime = verified["runtime"]
    return {
        "release_schema": transition["schema"],
        "release_root_sha256": transition["current_root_sha256"],
        "runtime_manifest_sha256": runtime["manifest_sha256"],
        "runtime_root_sha256": runtime["artifact_root_sha256"],
    }


if __name__ == "__main__":
    print(json.dumps(verify_current_release(), sort_keys=True))
