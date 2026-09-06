from __future__ import annotations

import hashlib
import inspect
import json
import os
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import core.phase11_governed_away_v1 as away_module
from core.phase11_governed_away_v1 import (
    BrowserActionEnvelopeV1,
    BrowserRuntimeDeadlineV1,
    GovernedAwayError,
    GovernedAwayModeV1,
    GovernedAwayUnavailable,
    GovernedAwayWaiting,
    PlaywrightBrowserDriverV1,
    _ProfileIdentityGuardV1,
    _SecureAwayStoreV1,
    _chromium_resolver_args,
    _resolve_public_host,
)


KEY = b"a" * 32


def _envelope(**changes: object) -> BrowserActionEnvelopeV1:
    values: dict[str, object] = {
        "signing_key": KEY,
        "mission_id": "mis_unit",
        "principal_id": "owner-local",
        "away_session_id": "away_" + "12" * 16,
        "lease_generation": 1,
        "workspace_id": "cyryx-labs",
        "workspace_root": str(Path.cwd()),
        "profile_id": "profile-public-v1",
        "provider_id": "playwright-chromium",
        "account_id": "none",
        "action": "observe",
        "target_url": "https://example.com/reference",
        "allowed_domains": ["example.com"],
        "capture_screenshot": True,
        "max_seconds": 30,
        "max_uses": 1,
        "network_request_budget": 64,
        "output_byte_budget": 16_384,
        "screenshot_budget": 1,
        "paid_cost_budget": 0,
        "approval_policy_id": "missionstore.exact-plan.v1",
        "approval_digest": "9" * 64,
        "key_epoch": 1,
        "stop_policy": (
            "cancel",
            "domain_drift",
            "dialog",
            "download",
            "global_kill",
            "mfa",
            "popup",
            "target_drift",
            "timeout",
        ),
        "issued_at_ns": 1_000_000_000_000,
        "not_before_ns": 1_000_000_000_000,
        "nonce": "ab" * 16,
    }
    values.update(changes)
    if changes.get("issued_at_ns", object()) is None and "not_before_ns" not in changes:
        values["not_before_ns"] = None
    return BrowserActionEnvelopeV1.build(**values)


def _execute(
    mode: GovernedAwayModeV1,
    *,
    envelope: BrowserActionEnvelopeV1,
    binding_digest: str,
    cancel,
    approved_deadline_ns: int | None = None,
):
    return mode.execute(
        envelope=envelope,
        binding_digest=binding_digest,
        execution_id_digest="f" * 64,
        approved_deadline_ns=(
            time.time_ns() + 30_000_000_000
            if approved_deadline_ns is None
            else approved_deadline_ns
        ),
        cancel=cancel,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mission_id", "mis_other"),
        ("principal_id", "attacker"),
        ("away_session_id", "away_" + "34" * 16),
        ("lease_generation", 2),
        ("workspace_id", "personal"),
        ("workspace_root", str(Path.cwd().parent)),
        ("profile_id", "profile-other"),
        ("provider_id", "other-provider"),
        ("account_id", "other-account"),
        ("action", "click"),
        ("target_url", "https://other.example/path"),
        ("target_origin", "https://other.example"),
        ("target_domain", "other.example"),
        ("allowed_domains", ("other.example",)),
        ("capture_screenshot", False),
        ("max_seconds", 31),
        ("max_uses", 2),
        ("network_request_budget", 65),
        ("output_byte_budget", 8_192),
        ("screenshot_budget", 0),
        ("paid_cost_budget", 1),
        ("approval_policy_id", "other.policy"),
        ("approval_digest", "8" * 64),
        ("key_epoch", 2),
        ("stop_policy", ("cancel",)),
        ("intent_digest", "0" * 64),
        ("issued_at_ns", 2_000_000_000_000),
        ("not_before_ns", 2_000_000_000_000),
        ("expires_at_ns", 2_030_000_000_000),
        ("nonce", "cd" * 16),
        ("signature", "0" * 64),
    ],
)
def test_every_meaningful_envelope_field_is_authenticated(
    field: str, value: object
) -> None:
    envelope = _envelope()
    tampered = replace(envelope, **{field: value})
    with pytest.raises((GovernedAwayError, GovernedAwayWaiting)):
        tampered.authenticate(KEY, now_ns=1_001_000_000_000)


@pytest.mark.parametrize(
    "target",
    [
        "http://example.com",
        "https://127.0.0.1",
        "https://user:pass@example.com",
        "https://example.com/?access_token=abc",
        "https://example.com/?auth=abc",
        "https://example.com/?sessionid=abc",
        "https://example.com/?signature=abc",
        "https://example.com/?credential=abc",
        "https://example.com/?public=ambiguous",
        "https://example.com/#section",
        "file:///etc/passwd",
    ],
)
def test_unsafe_targets_fail_before_envelope_creation(target: str) -> None:
    with pytest.raises(GovernedAwayError):
        _envelope(target_url=target)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "169.254.1.8",
        "192.0.2.10",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_dns_guard_rejects_every_non_global_address(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (family, socket.SOCK_STREAM, 6, "", (address, 443))
        ],
    )
    with pytest.raises(GovernedAwayWaiting, match="non-public"):
        _resolve_public_host("example.com")


def test_dns_guard_rejects_mixed_public_and_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(GovernedAwayWaiting, match="non-public"):
        _resolve_public_host("example.com")


def test_dns_guard_fails_closed_when_resolution_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args, **_kwargs):
        raise socket.gaierror("no answer")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(GovernedAwayWaiting, match="failed closed"):
        _resolve_public_host("example.com")


def test_chromium_dns_pin_remains_fixed_when_dns_rebinds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ],
    )
    pinned = {"example.com": _resolve_public_host("example.com")}
    arguments = _chromium_resolver_args(pinned)
    assert "MAP example.com 93.184.216.34" in arguments[0]
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(GovernedAwayWaiting, match="non-public"):
        _resolve_public_host("example.com")
    assert "MAP example.com 93.184.216.34" in arguments[0]


def test_runtime_deadline_is_host_signed_and_not_create_time_expiry() -> None:
    envelope = _envelope()
    now = time.time_ns()
    runtime = BrowserRuntimeDeadlineV1.build(
        signing_key=KEY,
        envelope=envelope,
        binding_digest="1" * 64,
        execution_id_digest="2" * 64,
        dns_pin_digest="3" * 64,
        approved_deadline_ns=now + 5_000_000_000,
        issued_at_ns=now,
    )
    runtime.authenticate(KEY, envelope, now_ns=now + 1)
    assert envelope.expires_at_ns < now
    with pytest.raises(GovernedAwayError, match="authentication"):
        replace(runtime, approval_digest="4" * 64).authenticate(
            KEY,
            envelope,
            now_ns=now + 1,
        )


def test_away_contract_refuses_deadline_longer_than_worker_lease() -> None:
    with pytest.raises(GovernedAwayError, match="from 5 to 60"):
        _envelope(max_seconds=61)


def test_profile_cleanup_never_falls_back_to_path_rmtree_after_quarantine_error(
    tmp_path: Path,
) -> None:
    guard = object.__new__(_ProfileIdentityGuardV1)
    guard.path = tmp_path / "profile"
    guard.path.mkdir()
    guard._portable_identity = None
    guard._windows_boundary = MagicMock()
    guard._windows_boundary.quarantine_root.side_effect = RuntimeError(
        "identity changed"
    )
    with (
        patch(
            "core.phase11_governed_away_v1.shutil.rmtree"
        ) as unsafe_delete,
        pytest.raises(RuntimeError, match="identity changed"),
    ):
        guard.close_and_discard()
    unsafe_delete.assert_not_called()
    guard._windows_boundary.close.assert_not_called()


@pytest.mark.skipif(os.name != "nt", reason="Windows trusted-root classification")
def test_busy_away_root_is_classified_unavailable_before_startup_crash(
    tmp_path: Path,
) -> None:
    from core.phase11_windows_clone_cleanup_v1 import CloneCleanupWaiting

    with (
        patch(
            "core.phase11_windows_namespace_v1.WindowsTrustedDirectoryV1",
            side_effect=CloneCleanupWaiting("cleanup_root_handle_busy"),
        ),
        patch(
            "core.phase11_governed_away_v1.time.monotonic",
            side_effect=(0.0, 6.0),
        ),
        pytest.raises(
            GovernedAwayUnavailable,
            match="away_storage_transient_busy",
        ),
    ):
        _SecureAwayStoreV1(tmp_path / "away")


def test_transport_policy_registers_and_closes_every_websocket() -> None:
    context = MagicMock()
    flags: set[str] = set()
    PlaywrightBrowserDriverV1._install_transport_policy(context, flags)
    context.route_web_socket.assert_called_once()
    pattern, handler = context.route_web_socket.call_args.args
    assert pattern == "**/*"
    route = MagicMock()
    handler(route)
    route.close.assert_called_once_with()
    assert flags == {"websocket_blocked"}


def test_adversarial_local_page_denies_webrtc_and_webtransport(
    tmp_path: Path,
) -> None:
    from playwright.sync_api import sync_playwright

    flags: set[str] = set()
    driver = PlaywrightBrowserDriverV1()
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(tmp_path / "transport-profile"),
            headless=True,
            args=["--disable-quic", "--disable-webrtc"],
        )
        try:
            driver._install_transport_policy(context, flags)
            page = context.new_page()
            page.set_content(
                """
<script>
globalThis.results = {};
for (const name of ["RTCPeerConnection", "WebTransport"]) {
  try { new globalThis[name]("https://example.invalid"); results[name] = "open"; }
  catch (error) { results[name] = error.name; }
}
</script>
"""
            )
            results = page.evaluate("globalThis.results")
            assert results["RTCPeerConnection"] == "SecurityError"
            assert results["WebTransport"] == "SecurityError"
        finally:
            context.close()


def test_availability_cache_is_bounded_but_dispatch_preflight_reprobes() -> None:
    driver = PlaywrightBrowserDriverV1()
    envelope = _envelope()
    pins = {"example.com": ("93.184.216.34",)}
    with patch.object(
        driver,
        "_probe_available",
        side_effect=((True, "ready"), (True, "dispatch-ready")),
    ) as probe:
        assert driver.available() == (True, "ready")
        assert driver.available() == (True, "ready")
        assert probe.call_count == 1
        driver.preflight(envelope=envelope, dns_pins=pins)
        assert probe.call_count == 2


def test_availability_probe_uses_packaged_full_chromium(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "chrome.exe"
    executable.write_bytes(b"full-chromium")
    browser = MagicMock()
    playwright = MagicMock()
    playwright.chromium.executable_path = str(executable)
    playwright.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.start.return_value = playwright
    with patch(
        "playwright.sync_api.sync_playwright",
        return_value=manager,
    ):
        assert PlaywrightBrowserDriverV1._probe_available() == (
            True,
            "ready-dns-pin-capable",
        )
    playwright.chromium.launch.assert_called_once_with(
        headless=True,
        executable_path=str(executable),
        args=[
            "--host-resolver-rules=MAP onyx.invalid 127.0.0.1",
            "--no-proxy-server",
        ],
    )
    browser.close.assert_called_once_with()
    playwright.stop.assert_called_once_with()


def test_playwright_guard_is_context_wide_and_blocks_service_workers() -> None:
    source = inspect.getsource(PlaywrightBrowserDriverV1.execute)
    assert "executable_path=str(executable)" in source
    assert 'service_workers="block"' in source
    assert 'context.route("**/*", route_guard)' in source
    assert 'context.on("page", on_page)' in source
    assert 'page.route("**/*", route_guard)' not in source


def test_runtime_preflight_failure_occurs_before_durable_intent(
    tmp_path: Path,
) -> None:
    class PreflightFailureDriver(_Driver):
        def preflight(self, *, envelope, dns_pins):
            raise GovernedAwayWaiting("Chromium runtime unavailable")

    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=PreflightFailureDriver(),
    )
    with pytest.raises(GovernedAwayWaiting, match="runtime unavailable"):
        _execute(
            mode,
            envelope=_envelope(),
            binding_digest="4" * 64,
            cancel=lambda: False,
        )
    assert not (
        tmp_path / "away" / "attempts" / "mis_unit.intent.json"
    ).exists()


class _Driver:
    def __init__(self, *, wrong_target: bool = False) -> None:
        self.calls = 0
        self.wrong_target = wrong_target
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False

    def resolve_public_host(self, host):
        return ("93.184.216.34",)

    def preflight(self, *, envelope, dns_pins):
        assert set(dns_pins) == set(envelope.allowed_domains)

    def execute(
        self,
        *,
        envelope,
        profile_dir,
        publish_artifact,
        cancel,
        control,
        runtime_deadline,
        dns_pins,
    ):
        self.calls += 1
        self.started.set()
        control.wait_until_running(cancel)
        if self.block:
            self.release.wait(5)
        domain = "wrong.example" if self.wrong_target else envelope.target_domain
        origin = f"https://{domain}"
        screenshot = b"redacted screenshot"
        artifact_ref = publish_artifact("screenshot", screenshot)
        text = b"redacted public observation"
        return {
            "status": "succeeded",
            "final_url": (
                origin + "/reference"
                if self.wrong_target
                else envelope.target_url
            ),
            "final_origin": origin,
            "final_domain": domain,
            "text_sha256": hashlib.sha256(text).hexdigest(),
            "text_bytes": len(text),
            "artifact_ref": artifact_ref,
            "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
            "screenshot_bytes": len(screenshot),
            "policy_flags": [],
            "clipboard": "not_accessed",
            "downloads": "blocked",
            "uploads": "unsupported",
            "headed_preview": True,
        }

    def stop(self, mission_id: str, *, timeout: float) -> bool:
        self.release.set()
        return True


def test_wrong_driver_target_fails_closed(tmp_path: Path) -> None:
    driver = _Driver(wrong_target=True)
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=driver,
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="3" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert result["waiting_for"] == "browser driver reported the wrong target"


def test_receipt_and_output_are_redacted_and_content_bounded(
    tmp_path: Path,
) -> None:
    driver = _Driver()
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=driver,
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="4" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "succeeded"
    payload = json.dumps(result, sort_keys=True)
    assert "owner@example.com" not in payload
    assert "super-secret" not in payload
    receipt = result["data"]["receipt"]
    assert receipt["clipboard"] == "not_accessed"
    assert receipt["downloads"] == "blocked"
    assert receipt["uploads"] == "unsupported"
    assert receipt["target_domain"] == "example.com"
    assert len(receipt["receipt_hmac_sha256"]) == 64
    assert set(result["data"]) == {"observation", "receipt"}
    assert "text" not in result["data"]["observation"]
    assert "screenshot_ref" not in result["data"]["observation"]
    assert not any(
        str(tmp_path) in str(value)
        for value in result["data"]["observation"].values()
    )


class _AlteredOutputDriver(_Driver):
    def __init__(self, mutation) -> None:
        super().__init__()
        self.mutation = mutation

    def execute(self, **kwargs):
        result = dict(super().execute(**kwargs))
        self.mutation(result, kwargs)
        return result


def test_raw_text_or_screenshot_path_from_driver_is_rejected(
    tmp_path: Path,
) -> None:
    def mutate(result, _kwargs):
        result["text"] = "raw page text"
        result["screenshot_ref"] = str(tmp_path / "leak.png")

    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_AlteredOutputDriver(mutate),
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="7" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert "attempted_unknown" in result["waiting_for"]
    assert "raw page text" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_artifact_is_revalidated_for_containment_size_and_digest(
    tmp_path: Path,
) -> None:
    def mutate(_result, kwargs):
        mission_id = kwargs["envelope"].mission_id
        artifact = (
            kwargs["profile_dir"].parent.parent
            / "artifacts"
            / f"{mission_id}.redacted.png"
        )
        artifact.write_bytes(b"tampered after protected publication")

    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_AlteredOutputDriver(mutate),
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="8" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert "attempted_unknown" in result["waiting_for"]


def test_late_cancel_and_policy_event_cannot_commit_success(
    tmp_path: Path,
) -> None:
    cancelled = threading.Event()

    def mutate(result, _kwargs):
        result["policy_flags"] = ["unexpected_dialog"]
        cancelled.set()

    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_AlteredOutputDriver(mutate),
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="a" * 64,
        cancel=cancelled.is_set,
    )
    assert result["status"] == "waiting"
    assert "late browser result discarded" in result["waiting_for"]
    assert not (tmp_path / "away" / "attempts" / "mis_unit.receipt.json").exists()


def test_late_same_origin_url_drift_cannot_commit_success(
    tmp_path: Path,
) -> None:
    def mutate(result, _kwargs):
        result["final_url"] = "https://example.com/other"

    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_AlteredOutputDriver(mutate),
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="b" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert "wrong target" in result["waiting_for"]


def test_expiry_after_driver_result_is_rechecked_before_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired = threading.Event()
    issued = 9_000_000_000_000
    envelope = _envelope(
        issued_at_ns=issued,
        not_before_ns=issued,
        max_seconds=5,
    )

    def mutate(_result, _kwargs):
        expired.set()

    monkeypatch.setattr(
        away_module.time,
        "time_ns",
        lambda: (
            envelope.expires_at_ns + 1
            if expired.is_set()
            else envelope.issued_at_ns + 1
        ),
    )
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_AlteredOutputDriver(mutate),
    )
    result = _execute(
        mode,
        envelope=envelope,
        binding_digest="c" * 64,
        approved_deadline_ns=issued + 2,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert "fresh approval" in result["waiting_for"]


def test_takeover_is_terminal_durable_and_authenticated(
    tmp_path: Path,
) -> None:
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    assert mode.control("mis_unit", "takeover")["away_control_state"] == "takeover"
    with pytest.raises(GovernedAwayError, match="terminal"):
        mode.control("mis_unit", "running")
    restarted = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    assert restarted.status("mis_unit")["control_state"] == "takeover"
    journal = (
        tmp_path
        / "away"
        / "controls"
        / "mis_unit"
        / "00000001.json"
    )
    document = json.loads(journal.read_text(encoding="utf-8"))
    document["state"] = "running"
    journal.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(GovernedAwayError, match="authentication"):
        GovernedAwayModeV1(
            root=tmp_path / "away",
            signing_key=KEY,
            enabled=True,
            driver=_Driver(),
        ).status("mis_unit")


def test_pause_is_terminal_and_resume_is_refused(tmp_path: Path) -> None:
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    assert mode.control("mis_unit", "paused")["away_control_state"] == "paused"
    with pytest.raises(GovernedAwayError, match="terminal"):
        mode.control("mis_unit", "running")


def test_global_kill_is_durable_and_blocks_new_dispatch(tmp_path: Path) -> None:
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    mode.latch_global_kill()
    assert mode.availability()["browser"] is False
    restarted = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    assert restarted.availability()["browser_reason"] == "global_kill_latched"
    with pytest.raises(GovernedAwayWaiting, match="global Away kill"):
        _execute(
            restarted,
            envelope=_envelope(issued_at_ns=None),
            binding_digest="5" * 64,
            cancel=lambda: False,
        )


def test_corrupt_global_kill_latch_fails_closed(tmp_path: Path) -> None:
    mode = GovernedAwayModeV1(
        root=tmp_path / "away",
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    mode.latch_global_kill()
    latch = tmp_path / "away" / "global-kill.json"
    latch.write_text("{}", encoding="utf-8")
    assert mode.availability()["browser"] is False
    assert (
        mode.availability()["browser_reason"]
        == "global_kill_invalid_fail_closed"
    )
    with pytest.raises(GovernedAwayError, match="authentication"):
        _execute(
            mode,
            envelope=_envelope(issued_at_ns=None),
            binding_digest="d" * 64,
            cancel=lambda: False,
        )


def test_windows_trusted_artifact_directory_rejects_reparse_escape(
    tmp_path: Path,
) -> None:
    if os.name != "nt":
        pytest.skip("Windows trusted-directory boundary")
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "away"
    mode = GovernedAwayModeV1(
        root=root,
        signing_key=KEY,
        enabled=True,
        driver=_Driver(),
    )
    artifacts = root / "artifacts"
    try:
        os.symlink(outside, artifacts, target_is_directory=True)
    except OSError:
        mode.close()
        pytest.skip("Windows symlink creation is unavailable")
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="e" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert not any(outside.iterdir())


@pytest.mark.skipif(
    os.environ.get("ONYX_PHASE11_BROWSER_SMOKE") != "1",
    reason="requires a real headed Playwright browser and network",
)
def test_real_headed_playwright_observes_exact_public_target(
    tmp_path: Path,
) -> None:
    mode = GovernedAwayModeV1(
        root=tmp_path / "away-real",
        signing_key=KEY,
        enabled=True,
    )
    result = _execute(
        mode,
        envelope=_envelope(issued_at_ns=None),
        binding_digest="6" * 64,
        cancel=lambda: False,
    )
    assert result["status"] == "succeeded"
    assert result["data"]["receipt"]["final_domain"] == "example.com"
    assert (
        result["data"]["observation"]["artifact_ref"]
        == "away-artifact-v1:mis_unit:screenshot"
    )
