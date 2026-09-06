"""Focused and adversarial tests for the voice-opened session authority V1."""

from __future__ import annotations

import pytest

from core import voice_session_authority_v1 as mod

TRIGGER = "liberar trabalho onyx"
ROOT = r"C:\Work"
NOW = 1_000_000
HOUR = 60 * 60 * 1000


def _authority(trigger=TRIGGER):
    return mod.create_voice_session_authority_v1(trigger)


def _opened(roots=(ROOT,), now=NOW, lifetime=2 * HOUR, cap=100,
            transcript=f"onyx, {TRIGGER} por duas horas"):
    a = _authority()
    a.open_from_transcript(transcript, list(roots), envelope_id="env1",
                           now_ms=now, lifetime_ms=lifetime, operation_cap=cap)
    return a


# ── feature gate ────────────────────────────────────────────────────────────

def test_feature_gate_default_off():
    assert mod.VoiceSessionAuthorityFeatureGateV1.from_environ({}).enabled is False


def test_feature_gate_on():
    assert mod.VoiceSessionAuthorityFeatureGateV1.from_environ(
        {mod.FEATURE_FLAG: mod.ENABLED_VALUE}).enabled is True


def test_sealed_factory_rejects_direct_construction():
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        mod.VoiceSessionAuthorityV1(construction_key=object(), trigger_phrase=TRIGGER)


# ── trigger phrase must be unambiguous ──────────────────────────────────────

@pytest.mark.parametrize("phrase", ["libera", "onyx", "vai", "ok liberar"])
def test_short_trigger_rejected(phrase):
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        mod.create_voice_session_authority_v1(phrase)


def test_transcript_without_trigger_cannot_open():
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript("onyx abra a pasta de projetos", [ROOT],
                               envelope_id="e", now_ms=NOW,
                               lifetime_ms=HOUR, operation_cap=10)


def test_partial_trigger_cannot_open():
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript("liberar trabalho", [ROOT], envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


def test_trigger_is_case_and_whitespace_insensitive():
    a = _authority()
    env = a.open_from_transcript("ONYX,   Liberar   Trabalho   Onyx  agora",
                                 [ROOT], envelope_id="e", now_ms=NOW,
                                 lifetime_ms=HOUR, operation_cap=10)
    assert env.envelope_id == "e"


# ── envelope bounds ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("lifetime", [0, 59_999, mod.MAX_LIFETIME_MS + 1, -1, "1h"])
def test_lifetime_bounds_enforced(lifetime):
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [ROOT], envelope_id="e",
                               now_ms=NOW, lifetime_ms=lifetime, operation_cap=10)


@pytest.mark.parametrize("cap", [0, -1, mod.MAX_OPERATIONS + 1, "10"])
def test_operation_cap_bounds_enforced(cap):
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [ROOT], envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=cap)


def test_empty_roots_rejected():
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [], envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


@pytest.mark.parametrize("root", [r"Work", r"..\Work", r"C:\Work\..\Other", "", 5])
def test_bad_roots_rejected(root):
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [root], envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


def test_duplicate_root_rejected():
    a = _authority()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [ROOT, ROOT], envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


def test_too_many_roots_rejected():
    a = _authority()
    roots = [rf"C:\R{i}" for i in range(mod.MAX_ROOTS + 1)]
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", roots, envelope_id="e",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


# ── happy path: the fluency the owner asked for ─────────────────────────────

def test_read_inside_root_allowed_without_prompt():
    a = _opened()
    d = a.evaluate("file_controller", "read", {"path": rf"{ROOT}\a\b.txt"}, NOW)
    assert d.outcome == "allow"


def test_write_inside_root_allowed():
    a = _opened()
    d = a.evaluate("file_controller", "write", {"path": rf"{ROOT}\out.txt"}, NOW)
    assert d.outcome == "allow"


def test_local_dev_run_allowed():
    a = _opened()
    d = a.evaluate("code_helper", "run", {"path": rf"{ROOT}\proj"}, NOW)
    assert d.outcome == "allow"


def test_web_search_allowed_without_path():
    a = _opened()
    assert a.evaluate("web_search", "search", {"query": "x"}, NOW).outcome == "allow"


def test_root_itself_is_inside():
    a = _opened()
    assert a.evaluate("file_controller", "list", {"path": ROOT}, NOW).outcome == "allow"


def test_multiple_roots_each_allowed():
    a = _opened(roots=(ROOT, r"C:\Other"))
    assert a.evaluate("file_controller", "read", {"path": r"C:\Other\f"}, NOW).outcome == "allow"


# ── always-explicit is absolute ─────────────────────────────────────────────

@pytest.mark.parametrize("tool,action", [
    ("file_controller", "delete"),
    ("file_controller", "organize_desktop"),
    ("browser_control", "go_to"),
    ("computer_control", "click"),
    ("desktop_control", "wallpaper"),
    ("computer_settings", "set"),
    ("send_message", "send"),
    ("dev_agent", "run"),
])
def test_always_explicit_defers_even_inside_root(tool, action):
    a = _opened()
    d = a.evaluate(tool, action, {"path": rf"{ROOT}\x"}, NOW)
    assert d.outcome == "defer"
    assert "always-explicit" in d.reason


def test_delete_inside_root_still_defers():
    """Deletion is explicit even in an authorized root — by design."""
    a = _opened()
    assert a.evaluate("file_controller", "delete",
                      {"path": rf"{ROOT}\x.txt"}, NOW).outcome == "defer"


# ── root containment ────────────────────────────────────────────────────────

def test_path_outside_root_defers():
    a = _opened()
    d = a.evaluate("file_controller", "read", {"path": r"C:\Windows\system.ini"}, NOW)
    assert d.outcome == "defer"


def test_sibling_prefix_root_defers():
    """C:\\Work2 must never count as inside C:\\Work."""
    a = _opened()
    d = a.evaluate("file_controller", "read", {"path": r"C:\Work2\secret.txt"}, NOW)
    assert d.outcome == "defer"


@pytest.mark.parametrize("path", [
    r"C:\Work\..\Windows\x", r"..\x", "relative.txt", "", 7, None,
])
def test_unsafe_path_arguments_defer(path):
    a = _opened()
    assert a.evaluate("file_controller", "read", {"path": path}, NOW).outcome == "defer"


def test_destination_outside_root_defers():
    a = _opened()
    d = a.evaluate("file_controller", "move",
                   {"source": rf"{ROOT}\a", "destination": r"C:\Elsewhere\a"}, NOW)
    assert d.outcome == "defer"


def test_all_path_keys_are_checked():
    a = _opened()
    for key in ("path", "source", "destination", "target", "directory",
                "folder", "file", "output", "input"):
        d = a.evaluate("file_controller", "read", {key: r"C:\Outside\x"}, NOW)
        assert d.outcome == "defer", key


def test_non_dict_arguments_defer():
    a = _opened()
    assert a.evaluate("file_controller", "read", ["path"], NOW).outcome == "defer"


# ── expiry and cap ──────────────────────────────────────────────────────────

def test_expired_envelope_defers():
    a = _opened(lifetime=HOUR)
    assert a.evaluate("file_controller", "read", {"path": ROOT}, NOW + HOUR).outcome == "defer"


def test_operation_cap_exhaustion_defers():
    a = _opened(cap=2)
    for _ in range(2):
        assert a.evaluate("file_controller", "read", {"path": ROOT}, NOW).outcome == "allow"
        a.consume(NOW)
    assert a.evaluate("file_controller", "read", {"path": ROOT}, NOW).outcome == "defer"
    assert a.operations_used == 2


def test_no_envelope_defers():
    a = _authority()
    assert a.evaluate("file_controller", "read", {"path": ROOT}, NOW).outcome == "defer"


def test_close_returns_to_asking():
    a = _opened()
    a.close()
    assert a.evaluate("file_controller", "read", {"path": ROOT}, NOW).outcome == "defer"


def test_out_of_scope_operation_defers():
    a = _opened()
    assert a.evaluate("file_controller", "compress",
                      {"path": ROOT}, NOW).outcome == "defer"


# ── kill switch ─────────────────────────────────────────────────────────────

def test_kill_switch_denies_everything():
    a = _opened()
    a.engage_kill_switch()
    d = a.evaluate("file_controller", "read", {"path": ROOT}, NOW)
    assert d.outcome == "deny"
    assert a.kill_switch_engaged is True


def test_kill_switch_closes_envelope():
    a = _opened()
    a.engage_kill_switch()
    assert a.active_envelope(NOW) is None


def test_kill_switch_blocks_reopening():
    a = _opened()
    a.engage_kill_switch()
    with pytest.raises(mod.VoiceSessionAuthorityV1ContractError):
        a.open_from_transcript(f"x {TRIGGER}", [ROOT], envelope_id="e2",
                               now_ms=NOW, lifetime_ms=HOUR, operation_cap=10)


def test_kill_switch_precedes_always_explicit():
    a = _opened()
    a.engage_kill_switch()
    assert a.evaluate("browser_control", "go_to", {}, NOW).outcome == "deny"


# ── broker hook adapter ─────────────────────────────────────────────────────

def test_hook_allows_in_scope_and_consumes():
    a = _opened()
    result = a.governance_hook(
        "file_controller", {"action": "read", "path": rf"{ROOT}\f", "__now_ms": NOW})
    assert result is not None and result[0] is True
    assert a.operations_used == 1


def test_hook_returns_none_for_deferred():
    a = _opened()
    assert a.governance_hook(
        "file_controller", {"action": "delete", "path": rf"{ROOT}\f",
                            "__now_ms": NOW}) is None


def test_hook_denies_when_killed():
    a = _opened()
    a.engage_kill_switch()
    result = a.governance_hook(
        "file_controller", {"action": "read", "path": ROOT, "__now_ms": NOW})
    assert result is not None and result[0] is False


def test_hook_never_raises_on_bad_input():
    a = _opened()
    assert a.governance_hook("", {"action": "read"}) is None
    assert a.governance_hook("file_controller", "not-a-dict") is None


def test_hook_defers_unknown_tool():
    a = _opened()
    assert a.governance_hook(
        "unknown_tool", {"action": "read", "__now_ms": NOW}) is None
