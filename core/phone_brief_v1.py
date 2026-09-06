"""Compile call-safe Onyx briefs, without dialing or exposing assistant tools.

This CLI is a preparation surface, not an operational telephony connector.
Only exact reviewed fields enter the brief; vault/mail/session context is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from memory.store import contains_secret

RULES = (
    "Identify yourself honestly as Onyx, an AI assistant calling for the owner.",
    "Use only the approved brief. Ask one question at a time; keep replies brief.",
    "Never accept another date, time, party size, service, deposit, fee or upsell. "
    "Record alternatives and ask the owner to decide after the call.",
    "Do not disclose payment details, credentials, private addresses or unrelated information.",
    "Wait quietly on hold. Use IVR only toward this approved purpose. "
    "Leave at most one brief voicemail; end after two unanswered greetings.",
    "Read back the exact answer or booking once. A call ending is not proof of a booking.",
)


def _safe(value, name, max_chars=500):
    if not isinstance(value, str) or not value.strip() or len(value) > max_chars:
        raise ValueError(f"Invalid {name}")
    if contains_secret(value) or "{{" in value or "}}" in value or "\0" in value:
        raise ValueError(f"Unsafe or unresolved {name}")
    return value.strip()


def compile_brief(raw):
    if not isinstance(raw, dict):
        raise ValueError("Expected a structured brief")
    allowed = {"mode", "to_number", "owner_name", "purpose", "constraints", "max_seconds"}
    if set(raw) - allowed:
        raise ValueError("Unexpected fields; do not attach vault, mail or session context")
    mode = raw.get("mode")
    if mode not in {"booking", "inquiry"}:
        raise ValueError("Choose booking or inquiry")
    number = _safe(raw.get("to_number"), "phone number", 16)
    if not re.fullmatch(r"\+[1-9]\d{7,14}", number):
        raise ValueError("An explicit E.164 destination is required")
    duration = raw.get("max_seconds", 90)
    if type(duration) is not int or not 15 <= duration <= 300:
        raise ValueError("Duration must be 15 to 300 seconds")
    constraints = raw.get("constraints", {})
    if not isinstance(constraints, dict):
        raise ValueError("Invalid booking constraints")
    expected = {"date", "time", "timezone", "service", "party_size"}
    if set(constraints) - expected:
        raise ValueError("Unexpected constraint")
    if mode == "booking" and not {"date", "time", "timezone", "service"} <= set(constraints):
        raise ValueError("Booking requires exact date, time, timezone and service")
    clean = {key: _safe(value, key, 100) for key, value in constraints.items()}
    if mode == "booking":
        from datetime import date, time
        from zoneinfo import ZoneInfo
        date.fromisoformat(clean["date"])
        time.fromisoformat(clean["time"])
        ZoneInfo(clean["timezone"])
    if "party_size" in clean and not re.fullmatch(r"[1-9]\d?", clean["party_size"]):
        raise ValueError("Party size must be 1 to 99")
    brief = {"mode": mode, "to_number": number,
             "owner_name": _safe(raw.get("owner_name"), "owner name", 100),
             "purpose": _safe(raw.get("purpose"), "purpose"),
             "constraints": clean, "max_seconds": duration, "rules": list(RULES)}
    digest = hashlib.sha256(json.dumps(brief, sort_keys=True).encode()).hexdigest()
    return {"status": "preview_only", "brief": brief, "digest": digest,
            "dialed": False, "requires": ["owner approval of exact brief", "owned provider number",
            "reviewed isolated phone agent", "approved provider cost ceiling",
            "durable dispatch/reconciliation integration", "owner self-call qualification"]}


def receptionist_answer(question, approved_faq):
    """Exact FAQ lookup only. No PIN-based escalation or attached live tools."""
    if not isinstance(approved_faq, dict) or len(approved_faq) > 30:
        raise ValueError("Use a curated FAQ with at most 30 entries")
    clean = {_safe(key, "FAQ question", 200).casefold(): _safe(value, "FAQ answer", 500)
             for key, value in approved_faq.items()}
    query = _safe(question, "question", 200).casefold()
    return {"role": "guest", "answer": clean.get(query,
            "I am Onyx, an AI receptionist. I can take a callback message for the owner."),
            "tools_available": [], "owner_authenticated": False}


def cli(argv=None):
    parser = argparse.ArgumentParser(description="Onyx phone brief preview — does not dial")
    parser.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.input.open("rb") as source:
            data = source.read(16385)
        if len(data) > 16384:
            raise ValueError("Brief exceeds 16 KiB")
        print(json.dumps(compile_brief(json.loads(data)), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(cli())
