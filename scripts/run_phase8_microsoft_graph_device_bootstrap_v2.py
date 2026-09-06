"""Operator-run corrective device sign-in bootstrap (V2).

Runs the corrected device-code sign-in (see
``core/phase8_microsoft_graph_device_bootstrap_v2.py`` for the recorded frozen
OAuth V1 verification-host defect) and stores the refresh token in the exact
native-vault slot the accepted live-E2E runner restores from. Requires
``ONYX_PHASE8_MS_GRAPH_DEVICE_BOOTSTRAP_V2=true`` plus the same secret-free
onboarding environment as the accepted runner. Prints only the verification
URL and user code — never a token.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from core.phase8_microsoft_graph_device_bootstrap_v2 import (  # noqa: E402
    FEATURE_FLAG,
    DeviceBootstrapFeatureGateV2,
    create_microsoft_graph_device_bootstrap_v2,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (  # noqa: E402
    MicrosoftGraphLiveOnboardingV1,
)


def main() -> int:
    if not DeviceBootstrapFeatureGateV2.from_environ().enabled:
        print(f"Set {FEATURE_FLAG}=true to run the sign-in bootstrap.", file=sys.stderr)
        return 2
    try:
        onboarding = MicrosoftGraphLiveOnboardingV1.from_environ()
    except (PermissionError, ValueError) as exc:
        print(f"Onboarding environment rejected: {exc}", file=sys.stderr)
        return 2
    bootstrap = create_microsoft_graph_device_bootstrap_v2(
        onboarding=onboarding,
        sleeper=lambda seconds: time.sleep(max(1, int(seconds))),
        clock_epoch_s=lambda: int(time.time()),
        now_ms=time.time_ns() // 1_000_000,
    )
    if bootstrap is None:
        return 2
    print("Microsoft device sign-in required.")
    result = bootstrap.sign_in(echo=print)
    print(f"Signed in and verified : {result.account_id}")
    print(f"Refresh token stored   : {result.refresh_token_stored} (native vault)")
    print(
        "Now run scripts\\run_phase8_microsoft_graph_live_read_e2e_v1.py with the "
        "same onboarding environment; restore() will use the stored token."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
