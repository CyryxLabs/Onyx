"""Console-free source launcher with durable local startup diagnostics."""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "runtime" / "logs"
LOG_PATH = LOG_DIR / "onyx-startup.log"


def _open_log():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_PATH.open("a", encoding="utf-8", buffering=1)


def run() -> None:
    log = _open_log()
    sys.stdout = log
    sys.stderr = log
    os.chdir(ROOT)
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    print(
        f"\n[{datetime.now(timezone.utc).isoformat()}] Onyx launcher starting "
        f"with {sys.executable}"
    )
    try:
        import main as onyx_main

        onyx_main.main()
    except BaseException:
        traceback.print_exc()
        raise
    finally:
        print(f"[{datetime.now(timezone.utc).isoformat()}] Onyx launcher stopped")
        log.flush()
        log.close()


if __name__ == "__main__":
    run()
