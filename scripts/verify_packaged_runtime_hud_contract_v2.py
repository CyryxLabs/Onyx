"""CLI verifier for packaged-runtime HUD contract V2 staging."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core.onyx_packaged_runtime_hud_contract_v2 import verify_packaged_runtime_hud_contract_v2  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(verify_packaged_runtime_hud_contract_v2(Path(sys.argv[1])), sort_keys=True))
