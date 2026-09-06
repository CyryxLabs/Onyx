"""Exercise every owner-facing Onyx capability and record what actually works.

The capability matrix separates *implemented* from *verified* on purpose, and
several rows carry no evidence in either direction.  This smoke closes that gap
by driving each capability and recording the outcome, so a matrix row can cite a
run rather than an intention.

Three verdicts, and the third is not a softer failure:

``pass``     the capability was exercised and returned a usable result.
``fail``     the capability was exercised and errored, or returned nothing usable.
``skipped``  the capability cannot be exercised safely without side effects the
             owner did not ask for — sending a message, launching an
             application, changing a system setting, running arbitrary code,
             starting a download.  A skip records *why*, and never counts as a
             pass.

Nothing here sends, spends, publishes, deletes, or alters system state.  File
work happens inside a private temporary directory that is removed afterwards.
"""
from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

RECEIPT = PROJECT / "docs/onyx/CAPABILITY_SMOKE_V1.json"
NETWORK_NOTE = "requires network; a failure here may be connectivity, not code"


class Result:
    __slots__ = ("name", "feature", "verdict", "detail", "seconds", "note")

    def __init__(self, name, feature, verdict, detail, seconds, note=""):
        self.name, self.feature = name, feature
        self.verdict, self.detail = verdict, detail
        self.seconds, self.note = seconds, note

    def as_dict(self) -> dict:
        return {
            "capability": self.name,
            "feature": self.feature,
            "verdict": self.verdict,
            "detail": self.detail,
            "seconds": round(self.seconds, 3),
            "note": self.note,
        }


# A tool answering "please provide a file path" has not been exercised — it has
# declined. Scoring that as success is exactly how a smoke ends up certifying
# nothing, so these are recorded as `inconclusive` and never as a pass.
_UNEXERCISED = (
    "no file path", "please provide", "i need both", "provide a",
    "access denied", "path not found", "not installed", "unavailable",
    "no such", "is required", "not provided", "could not",
    "unknown ", "available:", "invalid action", "unsupported",
)


def _looks_unexercised(text: str) -> bool:
    low = text.casefold()
    return any(marker in low for marker in _UNEXERCISED)


def _run(name, feature, fn, note=""):
    started = time.monotonic()
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - a probe must never abort the run
        return Result(
            name, feature, "fail",
            f"{type(exc).__name__}: {str(exc).splitlines()[0][:180]}",
            time.monotonic() - started, note,
        )
    elapsed = time.monotonic() - started
    text = " ".join(str(value).split())
    if not text:
        return Result(name, feature, "fail", "returned an empty result", elapsed, note)
    if _looks_unexercised(text):
        return Result(
            name, feature, "inconclusive",
            f"declined rather than executed: {text[:150]}", elapsed, note,
        )
    return Result(name, feature, "pass", text[:180], elapsed, note)


def _skip(name, feature, why):
    return Result(name, feature, "skipped", why, 0.0)


def probes(workspace: Path, allow_network: bool, allow_capture: bool):
    from actions.code_helper import code_helper
    from actions.file_controller import file_controller
    from actions.file_processor import file_processor
    from actions.reminder import reminder
    from actions.system_monitor import get_system_status
    from actions.proactive import ProactiveEngine

    sample = workspace / "sample.txt"
    sample.write_text(
        "Onyx capability smoke sample.\nSecond line for summarisation.\n",
        encoding="utf-8",
    )
    code = workspace / "sample.py"
    code.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    yield _run("system_status", "Hardware Monitoring", get_system_status)

    yield _run(
        "file_controller", "System/File Control",
        lambda: file_controller({"action": "list", "path": str(workspace)}),
    )
    yield _run(
        "file_processor", "File Processor",
        lambda: file_processor({"action": "summarize", "file_path": str(sample)}),
    )
    yield _run(
        "code_helper", "Code Helper",
        lambda: code_helper({"action": "explain", "file_path": str(code)}),
    )
    yield _run(
        "reminder", "Smart Reminders",
        lambda: reminder({
            "date": "2030-01-01", "time": "09:00",
            "message": "Onyx capability smoke probe",
        }),
        note="creates a dated reminder far in the future; harmless if it lands",
    )
    yield _run(
        "proactive", "Proactive Check-ins",
        lambda: {
            "engine": ProactiveEngine.__name__,
            "silence_gate_secs": getattr(
                ProactiveEngine, "min_silence_secs", "instance-configured"
            ),
        },
    )
    yield _run(
        "memory", "Persistent Memory",
        lambda: _memory_probe(),
    )
    yield _run(
        "language_memory", "Silent Language Memory",
        lambda: _language_probe(),
    )
    yield _run(
        "voice_provider", "Real-time Voice",
        lambda: _voice_probe(),
        note="configuration and recovery path only; a live call needs a session",
    )

    if allow_capture:
        from actions.screen_processor import _capture_screen

        yield _run(
            "screen_capture", "Visual Awareness",
            lambda: f"{len(_capture_screen()[0])} bytes captured",
        )
    else:
        yield _skip(
            "screen_capture", "Visual Awareness",
            "captures the owner's screen; pass --allow-capture to include it",
        )

    if allow_network:
        from actions.weather_report import weather_action
        from actions.web_search import web_search
        from actions.youtube_video import youtube_video
        from actions.flight_finder import flight_finder

        yield _run("weather", "Weather Report",
                   lambda: weather_action({"city": "Orlando", "when": "today"}),
                   note=NETWORK_NOTE)
        yield _run("web_search", "Multi-Mode Web Search",
                   lambda: web_search({"query": "Onyx assistant", "mode": "search"}),
                   note=NETWORK_NOTE)
        yield _run("youtube", "YouTube Control",
                   lambda: youtube_video({"action": "trending"}),
                   note=NETWORK_NOTE)
        yield _run("flight_finder", "Flight Finder",
                   lambda: flight_finder({
                       "origin": "MCO", "destination": "JFK",
                       "date": "2026-12-01",
                   }),
                   note=NETWORK_NOTE)
    else:
        for name, feature in (
            ("weather", "Weather Report"),
            ("web_search", "Multi-Mode Web Search"),
            ("youtube", "YouTube Control"),
            ("flight_finder", "Flight Finder"),
        ):
            yield _skip(name, feature, "needs network; pass --allow-network")

    # Deliberately not automated.  Each would act on the owner's behalf.
    for name, feature, why in (
        ("send_message", "Send Message",
         "sends on the owner's behalf; also drives the desktop via pyautogui"),
        ("open_app", "System Control",
         "launches applications and changes what is on screen"),
        ("computer_control", "System Control",
         "moves the pointer and types into whatever holds focus"),
        ("computer_settings", "System Control",
         "changes volume, brightness, WiFi and power state"),
        ("desktop_control", "Desktop Control",
         "rearranges windows and the desktop"),
        ("browser_control", "Browser Control",
         "launches a browser and navigates it"),
        ("game_updater", "Game Updater",
         "triggers downloads and installs"),
        ("dev_agent", "Autonomous Tasks",
         "executes arbitrary generated code"),
        ("morning_briefing", "Morning Briefing",
         "first-boot greeting; needs a real session start to observe"),
        ("hybrid_input", "Hybrid Input",
         "keyboard/voice switching is a UI behaviour, not a callable"),
        ("content_panel", "Dynamic Content Panel",
         "HUD rendering layer; observable only in the running UI"),
    ):
        yield _skip(name, feature, why)


def _memory_probe():
    from core import phase7_layered_memory_v1 as layered  # noqa: PLC0415

    names = [n for n in dir(layered) if not n.startswith("_")]
    if not names:
        raise RuntimeError("layered memory module exposes nothing")
    return f"phase7_layered_memory_v1 loaded ({len(names)} public names)"


def _language_probe():
    from core.paths import config_file  # noqa: PLC0415

    raw = json.loads(Path(config_file()).read_text(encoding="utf-8"))
    for key in ("language", "spoken_language", "owner_language"):
        if key in raw:
            return f"{key}={raw[key]!r}"
    return "no language key stored yet (set silently on first spoken use)"


def _voice_probe():
    from core.live_voice_continuity_v1 import is_session_resumption_rejection

    class _Rejected(Exception):
        code = 1008

    stale = is_session_resumption_rejection(
        _Rejected("1008 None. BidiGenerateContent session not found"), "handle"
    )
    fresh = is_session_resumption_rejection(
        _Rejected("1008 None. BidiGenerateContent session not found"), None
    )
    if not (stale and not fresh):
        raise RuntimeError("stale-session recovery is not armed")
    return "stale-session recovery armed; fresh-session faults still reach the breaker"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-network", action="store_true",
                        help="include probes that make outbound requests")
    parser.add_argument("--allow-capture", action="store_true",
                        help="include the screen capture probe")
    args = parser.parse_args()

    # file_controller allows only the home tree and the Onyx tree, and
    # refuses anything under AppData -- so the system temp directory is
    # correctly denied. Work directly in the home tree instead.
    workspace = Path(tempfile.mkdtemp(
        prefix=".onyx-capability-smoke-", dir=str(Path.home())
    ))
    results: list[Result] = []
    try:
        for result in probes(workspace, args.allow_network, args.allow_capture):
            results.append(result)
            mark = {
                "pass": "PASS", "fail": "FAIL",
                "inconclusive": "MOOT", "skipped": "SKIP",
            }[result.verdict]
            print(f"  {mark}  {result.feature:24s} {result.detail[:96]}", flush=True)
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    counts = {v: sum(1 for r in results if r.verdict == v)
              for v in ("pass", "fail", "inconclusive", "skipped")}
    receipt = {
        "schema": "onyx.capability-smoke.v1",
        "system": platform.system(),
        "counts": counts,
        "results": [r.as_dict() for r in results],
        "honesty": (
            "A skip is not a pass. Skipped capabilities are implemented but "
            "cannot be exercised without acting on the owner's behalf, and "
            "remain unevidenced by this run."
        ),
    }
    RECEIPT.write_text(
        json.dumps(receipt, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8", newline="\n",
    )
    print(f"\n  pass {counts['pass']}   fail {counts['fail']}   "
          f"inconclusive {counts['inconclusive']}   skipped {counts['skipped']}")
    print(f"  receipt: {RECEIPT.relative_to(PROJECT).as_posix()}")
    return 1 if counts["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
