"""Isolated probe worker for :mod:`core.readiness`.

The parent process captures all output and consumes only the final sentinel JSON
record.  This keeps diagnostic JSON clean even when third-party libraries print.
"""

from __future__ import annotations

import argparse
import asyncio
import _socket
import hmac
import ipaddress
import json
import multiprocessing
import os
import socket
import sys
import tempfile
import time
import math
import re
import struct
import threading
from pathlib import Path
from unittest.mock import patch

from core.credentials import get as get_gemini_credential
from core.audio_contract import (
    CHANNELS,
    CHUNK_SIZE,
    LIVE_VOICE,
    MAX_VOICE_ACCEPTANCE_MIC_BYTES,
    PCM_CHUNK_BYTES,
    RECEIVE_SAMPLE_RATE,
    SEND_SAMPLE_RATE,
    assert_original_live_voice,
)
from core.live_model import resolve_live_model
from core.paths import config_file, resource_root
from dashboard.security import ONYX_CERT_NAME, ONYX_KEY_NAME

MAX_MIC_BYTES = MAX_VOICE_ACCEPTANCE_MIC_BYTES
MAX_MODEL_AUDIO_BYTES = 144_000
MAX_TRANSCRIPT_CHARS = 500
MAX_TRANSCRIPT_BYTES = 2_000
MAX_RESPONSE_MESSAGES = 128


SENTINEL = "__ONYX_READINESS_RESULT__="
READINESS_CONFIG_ENV = "ONYX_READINESS_CONFIG"
READINESS_GO_TOKEN_ENV = "ONYX_READINESS_GO_TOKEN"
ROOT = resource_root()


def _emit(ok: bool, summary: str, *, kind: str = "", facts: dict | None = None) -> None:
    print(
        SENTINEL
        + json.dumps(
            {"ok": bool(ok), "summary": summary, "kind": kind, "facts": facts or {}},
            separators=(",", ":"),
        )
    )


def _error_kind(exc: BaseException) -> str:
    message = str(exc).lower()
    if isinstance(exc, PermissionError) or any(
        marker in message
        for marker in (
            "access is denied",
            "eperm",
            "operation not permitted",
            "permission denied",
        )
    ):
        return "permission"
    return type(exc).__name__


def probe_runtime_import() -> tuple[bool, str]:
    """Import the app behind a best-effort Python networking guard.

    This is not process containment: native code loaded via ctypes and child
    processes can bypass monkey-patched Python networking APIs.
    """

    def offline(*_args, **_kwargs):
        raise RuntimeError("network disabled during offline readiness")

    import requests
    import urllib.request

    with (
        patch.object(requests.sessions.Session, "request", offline),
        patch.object(urllib.request, "urlopen", offline),
        patch.object(urllib.request, "urlretrieve", offline),
        patch.object(socket, "create_connection", offline),
        patch.object(socket, "getaddrinfo", offline),
        patch.object(socket, "gethostbyname", offline),
        patch.object(socket, "gethostbyname_ex", offline),
        patch.object(_socket, "getaddrinfo", offline),
        patch.object(_socket, "gethostbyname", offline),
        patch.object(_socket, "gethostbyname_ex", offline),
        patch.object(socket.socket, "connect", offline),
        patch.object(socket.socket, "connect_ex", offline),
        patch.object(socket.socket, "send", offline),
        patch.object(socket.socket, "sendall", offline),
        patch.object(socket.socket, "sendto", offline),
    ):
        __import__("main")
    return (
        True,
        "Full Onyx runtime imported behind a best-effort Python networking guard",
    )


def _await_parent_gate() -> dict[str, str]:
    expected = os.environ.get(READINESS_GO_TOKEN_ENV, "")
    supplied = sys.stdin.readline().rstrip("\r\n")
    if not expected or not hmac.compare_digest(supplied, expected):
        raise RuntimeError("Readiness start gate was not authorized")
    raw_payload = sys.stdin.readline()
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in payload.items()
    ):
        raise RuntimeError("Readiness parent payload was malformed")
    return payload


def probe_audio_devices() -> tuple[bool, str]:
    import sounddevice as sd

    devices = sd.query_devices()
    inputs = sum(int(device.get("max_input_channels", 0)) > 0 for device in devices)
    outputs = sum(int(device.get("max_output_channels", 0)) > 0 for device in devices)
    return bool(
        inputs and outputs
    ), f"Detected {inputs} input and {outputs} output devices"


def probe_microphone() -> tuple[bool, str]:
    import numpy as np
    import sounddevice as sd

    sample = sd.rec(1600, samplerate=16000, channels=1, dtype="float32")
    sd.wait()
    ok = bool(np.isfinite(sample).all() and sample.shape == (1600, 1))
    return ok, "Captured and discarded a 100 ms ambient microphone sample"


def probe_camera() -> tuple[bool, str]:
    import cv2

    camera = cv2.VideoCapture(0)
    try:
        if not camera.isOpened():
            return False, "No camera opened"
        available, frame = camera.read()
        ok = bool(available and frame is not None and frame.size)
        return (
            ok,
            "Captured and discarded one camera frame"
            if ok
            else "No camera frame available",
        )
    finally:
        camera.release()


def probe_chromium() -> tuple[bool, str]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        # The release intentionally omits Playwright's duplicate
        # chromium-headless-shell payload. The "chromium" channel uses the
        # complete bundled browser in modern headless mode.
        browser = playwright.chromium.launch(channel="chromium", headless=True)
        try:
            version = browser.version
        finally:
            browser.close()
    return True, f"Headless Chromium {version} launched"


def _serve_dashboard_probe(
    listener: socket.socket, root_text: str, key: str, stop_event
) -> None:
    """Run the production ASGI app in a separately reapable local process."""
    import uvicorn
    from dashboard.server import DashboardServer

    root = Path(root_text)
    dashboard = DashboardServer(
        local_ip="127.0.0.1",
        cert_dir=root / "certs",
        uploads_dir=root / "uploads",
        static_dir=ROOT / "dashboard" / "static",
    )
    dashboard._pending_keys[key] = time.time() + 60
    uvicorn_server = uvicorn.Server(
        uvicorn.Config(
            dashboard.app,
            log_level="critical",
            lifespan="off",
            timeout_graceful_shutdown=1,
            timeout_keep_alive=0,
            ssl_keyfile=str(root / "certs" / ONYX_KEY_NAME),
            ssl_certfile=str(root / "certs" / ONYX_CERT_NAME),
        )
    )

    async def run() -> None:
        async def stop_watcher() -> None:
            while not stop_event.is_set():
                await asyncio.sleep(0.05)
            uvicorn_server.should_exit = True

        watcher = asyncio.create_task(stop_watcher())
        try:
            await uvicorn_server.serve(sockets=[listener])
        finally:
            watcher.cancel()

    asyncio.run(run())


def _validate_dashboard_certificate(cert_path: Path, expected_host: str) -> str:
    """Return the exact trust-bundle path only when its SAN matches the URL."""
    from cryptography import x509

    certificate = x509.load_pem_x509_certificate(cert_path.read_bytes())
    san = certificate.extensions.get_extension_for_class(
        x509.SubjectAlternativeName
    ).value
    expected_ip = ipaddress.ip_address(expected_host)
    if expected_ip not in san.get_values_for_type(x509.IPAddress):
        raise ValueError("Dashboard certificate does not identify the requested host")
    return str(cert_path)


def probe_dashboard() -> tuple[bool, str]:
    import requests

    with tempfile.TemporaryDirectory(prefix="onyx-readiness-dashboard-") as tmp:
        root = Path(tmp)
        (root / "uploads").mkdir()
        key = "ONYX42"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        context = multiprocessing.get_context("spawn")
        stop_event = context.Event()
        process = context.Process(
            target=_serve_dashboard_probe,
            args=(listener, str(root), key, stop_event),
            name="onyx-readiness-dashboard",
        )
        process.start()
        listener.close()
        session = None
        try:
            base = f"https://127.0.0.1:{port}"
            cert_path = root / "certs" / ONYX_CERT_NAME
            certificate_deadline = time.monotonic() + 8
            while not cert_path.is_file():
                if not process.is_alive():
                    return False, "Dashboard HTTPS server exited during startup"
                if time.monotonic() >= certificate_deadline:
                    return False, "Dashboard generated certificate was not found"
                time.sleep(0.05)
            try:
                trust_path = _validate_dashboard_certificate(cert_path, "127.0.0.1")
            except (OSError, ValueError):
                return False, "Dashboard certificate identity validation failed"
            session = requests.Session()
            session.verify = trust_path
            deadline = time.monotonic() + 8
            while True:
                if not process.is_alive():
                    return False, "Dashboard HTTPS server exited during startup"
                try:
                    login_page = session.get(base + "/login", timeout=0.5)
                    break
                except requests.RequestException:
                    if time.monotonic() >= deadline:
                        return False, "Dashboard HTTPS server did not start"
                    time.sleep(0.05)
            required_headers = {
                "content-security-policy",
                "x-content-type-options",
                "strict-transport-security",
                "permissions-policy",
            }
            if login_page.status_code != 200 or not required_headers <= {
                name.lower() for name in login_page.headers
            }:
                return False, "Dashboard HTTPS/security-header check failed"
            login = session.post(base + "/login", json={"pin": key}, timeout=3)
            token = login.json().get("token")
            if login.status_code != 200 or not isinstance(token, str):
                return False, "Dashboard bearer-auth initialization failed"
            headers = {"Authorization": f"Bearer {token}"}
            payload = b"Onyx readiness exact-byte roundtrip\x00\xff"
            upload = session.post(
                base + "/api/upload",
                headers=headers,
                files={"file": ("readiness.bin", payload, "application/octet-stream")},
                timeout=3,
            )
            if upload.status_code != 200:
                return False, "Dashboard authenticated upload failed"
            name = upload.json().get("name")
            listing = session.get(base + "/api/files", headers=headers, timeout=3)
            files = (
                listing.json().get("files", []) if listing.status_code == 200 else []
            )
            if not any(
                item.get("name") == name for item in files if isinstance(item, dict)
            ):
                return False, "Dashboard authenticated file listing failed"
            download = session.get(
                base + "/uploads/" + str(name), headers=headers, timeout=3
            )
            if download.status_code != 200 or download.content != payload:
                return False, "Dashboard authenticated exact-byte download failed"
        finally:
            if session is not None:
                session.close()
            stop_event.set()
            process.join(timeout=5)
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if process.is_alive():
                process.kill()
                process.join(timeout=2)
            if process.is_alive():
                return False, "Dashboard HTTPS server did not stop cleanly"
    return (
        True,
        "Loopback HTTPS dashboard passed TLS, headers, auth, and file roundtrip",
    )


async def _live_handshake(
    api_key: str, model: str, client_factory=None, response_timeout: float = 8.0
) -> bool:
    """Complete one tiny text-to-audio Live turn without reading private media."""
    from google import genai
    from google.genai import types

    factory = client_factory or genai.Client
    client = factory(api_key=api_key, http_options={"api_version": "v1beta"})
    try:
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=LIVE_VOICE
                    )
                )
            ),
        )
        assert_original_live_voice(config)
        async with client.aio.live.connect(model=model, config=config) as session:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": "Reply briefly: ready."}]},
                turn_complete=True,
            )

            def field(value, name: str):
                return (
                    value.get(name)
                    if isinstance(value, dict)
                    else getattr(value, name, None)
                )

            def nonempty_audio(response) -> bool:
                data = field(response, "data")
                if isinstance(data, (bytes, bytearray, memoryview)) and bool(data):
                    return True
                server_content = field(response, "server_content")
                model_turn = field(server_content, "model_turn")
                parts = field(model_turn, "parts") or ()
                for part in parts:
                    inline_data = field(part, "inline_data")
                    payload = field(inline_data, "data")
                    mime_type = field(inline_data, "mime_type")
                    if (
                        isinstance(payload, (bytes, bytearray, memoryview))
                        and bool(payload)
                        and isinstance(mime_type, str)
                        and mime_type.lower().startswith("audio/")
                    ):
                        return True
                return False

            async def received_response() -> bool:
                heard_audio = False
                async for response in session.receive():
                    heard_audio = heard_audio or nonempty_audio(response)
                    server_content = field(response, "server_content")
                    if field(server_content, "turn_complete") is True:
                        return heard_audio
                return False

            return await asyncio.wait_for(received_response(), response_timeout)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def _read_live_config(payload: dict[str, str] | None = None) -> tuple[str, str]:
    if payload is not None:
        key = payload.get("api_key")
        model = payload.get("model")
        if not key or not model:
            raise ValueError("Gemini Live readiness payload incomplete")
        return key, model
    configured_path = os.environ.get(READINESS_CONFIG_ENV)
    if not configured_path:
        configured_path = str(config_file())
    config_path = Path(configured_path)
    config = json.loads(config_path.read_text(encoding="utf-8"))
    key = get_gemini_credential(required=False)
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Gemini API key absent")
    return key.strip(), resolve_live_model(config=config)


def probe_live_api(payload: dict[str, str] | None = None) -> tuple[bool, str]:
    key, model = _read_live_config(payload)
    ok = asyncio.run(_live_handshake(key, model))
    return ok, "Gemini Live completed one minimal text-to-audio response turn"


async def _integrated_voice_loop(
    api_key: str,
    model: str,
    *,
    client_factory=None,
    sd_module=None,
    capture_seconds: float = 6.0,
    response_timeout: float = 12.0,
    diagnostics: dict[str, object] | None = None,
    manual_vad: bool = False,
) -> dict[str, object]:
    """Capture live speech, obtain model audio, and play it; retain no audio."""
    import sounddevice as sd
    from google import genai
    from google.genai import types

    audio = sd_module or sd
    factory = client_factory or genai.Client
    sent_bytes = 0
    accepted_bytes = 0
    accepted_lock = threading.Lock()
    nonzero_sent = False
    facts = diagnostics if diagnostics is not None else {}
    facts.update(
        {
            "stage": "cue",
            "mic_bytes_accepted": 0,
            "mic_bytes_sent": 0,
            "model_audio_bytes_received": 0,
            "speaker_frames_written": 0,
            "turn_complete": False,
            "turn_complete_before_stream_end": False,
            "transcript_matched": False,
            "cue_played": False,
            "vad_mode": "manual" if manual_vad else "automatic",
            "activity_markers_sent": False,
            "callback_chunks_dropped": 0,
        }
    )
    cue = bytearray()
    for index in range(RECEIVE_SAMPLE_RATE // 10):
        sample = int(3500 * math.sin(2 * math.pi * 660 * index / RECEIVE_SAMPLE_RATE))
        cue.extend(struct.pack("<h", sample))
    cue_played = False

    def play_cue() -> None:
        nonlocal cue_played
        cue_stream = audio.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        try:
            cue_stream.start()
            cue_stream.write(bytes(cue))
            cue_played = True
            facts["cue_played"] = True
        finally:
            try:
                cue_stream.stop()
            finally:
                cue_stream.close()

    loop = asyncio.get_running_loop()
    pending: asyncio.Queue[bytes] = asyncio.Queue(maxsize=80)
    reservations = threading.BoundedSemaphore(80)
    accepting = threading.Event()
    accepting.set()

    def enqueue(chunk: bytes) -> None:
        if not accepting.is_set():
            reservations.release()
            return
        pending.put_nowait(chunk)

    def callback(indata, frames, time_info, status):
        nonlocal accepted_bytes
        del frames, time_info, status
        try:
            view = memoryview(indata).cast("B")
        except TypeError:
            return
        if len(view) > PCM_CHUNK_BYTES:
            return
        if not accepting.is_set() or not reservations.acquire(blocking=False):
            facts["callback_chunks_dropped"] = min(
                80, int(facts["callback_chunks_dropped"]) + 1
            )
            return
        with accepted_lock:
            remaining = MAX_MIC_BYTES - accepted_bytes
            allowed = min(len(view), remaining) & ~1
            if allowed <= 0:
                reservations.release()
                facts["callback_chunks_dropped"] = min(
                    80, int(facts["callback_chunks_dropped"]) + 1
                )
                return
            accepted_bytes += allowed
            facts["mic_bytes_accepted"] = accepted_bytes
        loop.call_soon_threadsafe(enqueue, bytes(view[:allowed]))

    facts["stage"] = "connect"
    client = factory(api_key=api_key, http_options={"api_version": "v1beta"})
    received = bytearray()
    complete = False
    transcript = ""
    message_count = 0
    try:
        realtime_config = (
            types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=True
                )
            )
            if manual_vad
            else None
        )
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            input_audio_transcription={},
            output_audio_transcription={},
            realtime_input_config=realtime_config,
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=LIVE_VOICE
                    )
                )
            ),
        )
        assert_original_live_voice(config)
        async with client.aio.live.connect(model=model, config=config) as session:

            async def collect() -> None:
                nonlocal complete, transcript, message_count
                iterator = session.receive().__aiter__()
                deadline = asyncio.get_running_loop().time() + response_timeout
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    try:
                        response = await asyncio.wait_for(
                            anext(iterator), min(5.0, remaining)
                        )
                    except StopAsyncIteration:
                        return
                    message_count += 1
                    if message_count > MAX_RESPONSE_MESSAGES:
                        raise ValueError("Live response message limit exceeded")
                    data = getattr(response, "data", None)
                    if data is not None:
                        try:
                            view = memoryview(data).cast("B")
                        except TypeError:
                            raise ValueError(
                                "Live audio response was not a byte buffer"
                            ) from None
                        if (
                            len(view) > MAX_MODEL_AUDIO_BYTES
                            or len(received) + len(view) > MAX_MODEL_AUDIO_BYTES
                        ):
                            raise ValueError(
                                "Live audio response exceeded the safety cap"
                            )
                        received.extend(view)
                        facts["model_audio_bytes_received"] = len(received)
                    content = getattr(response, "server_content", None)
                    input_tx = getattr(content, "input_transcription", None)
                    text = getattr(input_tx, "text", "")
                    if text:
                        if not isinstance(text, str):
                            raise ValueError("Live input transcript was not text")
                        encoded = text.encode("utf-8")
                        if (
                            len(text) > MAX_TRANSCRIPT_CHARS
                            or len(encoded) > MAX_TRANSCRIPT_BYTES
                            or len(transcript) + len(text) + 1 > MAX_TRANSCRIPT_CHARS
                        ):
                            raise ValueError(
                                "Live input transcript exceeded the safety cap"
                            )
                        transcript = (transcript + " " + text).strip()
                        facts["stage"] = "transcript"
                    if getattr(content, "turn_complete", False):
                        complete = True
                        facts["turn_complete"] = True
                        return

            facts["stage"] = "receive"
            receiver = asyncio.create_task(collect())
            try:
                await asyncio.sleep(0)
                facts["stage"] = "cue"
                play_cue()
                facts["stage"] = "send"
                if manual_vad:
                    await session.send_realtime_input(activity_start={})
                    facts["activity_markers_sent"] = True
                facts["stage"] = "capture"
                input_stream = audio.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    callback=callback,
                )
                deadline = loop.time() + max(0.1, min(capture_seconds, 6.0))
                try:
                    input_stream.start()
                    while loop.time() < deadline and (
                        manual_vad or not receiver.done()
                    ):
                        try:
                            chunk = await asyncio.wait_for(
                                pending.get(), min(0.05, deadline - loop.time())
                            )
                        except asyncio.TimeoutError:
                            continue
                        reservations.release()
                        facts["stage"] = "send"
                        await session.send_realtime_input(
                            media={
                                "data": chunk,
                                "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                            }
                        )
                        sent_bytes += len(chunk)
                        nonzero_sent = nonzero_sent or any(chunk)
                        facts["mic_bytes_sent"] = sent_bytes
                finally:
                    accepting.clear()
                    try:
                        input_stream.stop()
                    finally:
                        input_stream.close()
                barrier = asyncio.Event()
                loop.call_soon_threadsafe(barrier.set)
                await barrier.wait()
                while not pending.empty():
                    chunk = pending.get_nowait()
                    reservations.release()
                    if not manual_vad and receiver.done():
                        continue
                    await session.send_realtime_input(
                        media={
                            "data": chunk,
                            "mime_type": f"audio/pcm;rate={SEND_SAMPLE_RATE}",
                        }
                    )
                    sent_bytes += len(chunk)
                    nonzero_sent = nonzero_sent or any(chunk)
                    facts["mic_bytes_sent"] = sent_bytes
                if not sent_bytes or not nonzero_sent:
                    return {**facts, "ok": False}
                facts["stage"] = "end"
                if manual_vad:
                    await session.send_realtime_input(activity_end={})
                    facts["stage"] = "receive"
                    await receiver
                elif receiver.done():
                    facts["stage"] = "receive"
                    await receiver
                    facts["turn_complete_before_stream_end"] = bool(complete)
                else:
                    facts["stage"] = "receive"
                    return {**facts, "ok": False}
            finally:
                if not receiver.done():
                    receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    facts["stage"] = "transcript"
    words = re.findall(r"[a-z0-9]+", transcript.casefold())
    matched = "onyx" in words and "readiness" in words
    facts["transcript_matched"] = matched
    written = 0
    if received and complete and matched:
        facts["stage"] = "playback"
        stream = audio.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        try:
            stream.start()
            for offset in range(0, len(received), PCM_CHUNK_BYTES):
                block = memoryview(received)[offset : offset + PCM_CHUNK_BYTES]
                stream.write(block)
                written += len(block) // 2
        finally:
            try:
                stream.stop()
            finally:
                stream.close()
    facts.update(
        {
            "ok": bool(
                received
                and complete
                and written
                and matched
                and cue_played
                and (manual_vad or facts["turn_complete_before_stream_end"])
            ),
            "mic_bytes_sent": sent_bytes,
            "model_audio_bytes_received": len(received),
            "speaker_frames_written": written,
            "turn_complete": complete,
            "transcript_matched": matched,
            "cue_played": cue_played,
        }
    )
    return facts


def probe_integrated_voice(
    payload: dict[str, str] | None = None, *, manual_vad: bool = False
) -> tuple[bool, str, dict[str, object]]:
    key, model = _read_live_config(payload)
    facts: dict[str, object] = {}
    try:
        facts = asyncio.run(
            _integrated_voice_loop(key, model, diagnostics=facts, manual_vad=manual_vad)
        )
    except BaseException as exc:
        stage = facts.get("stage", "connect")
        facts["ok"] = False
        return (
            False,
            f"Integrated voice probe failed ({type(exc).__name__}) at {stage}",
            facts,
        )
    return (
        bool(facts["ok"]),
        (
            "Integrated microphone to Gemini Live to speaker loop completed"
            if facts["ok"]
            else f"Integrated voice loop did not complete at {facts.get('stage', 'receive')}"
        ),
        facts,
    )


def probe_voice_transport(
    payload: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, object]]:
    return probe_integrated_voice(payload, manual_vad=True)


PROBES = {
    "runtime_import": probe_runtime_import,
    "audio_devices": probe_audio_devices,
    "microphone": probe_microphone,
    "camera": probe_camera,
    "chromium": probe_chromium,
    "dashboard": probe_dashboard,
    "live_api": probe_live_api,
    "integrated_voice": probe_integrated_voice,
    "voice_transport": probe_voice_transport,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("probe", choices=sorted(PROBES))
    args = parser.parse_args(argv)
    try:
        payload = _await_parent_gate()
        if args.probe in {"integrated_voice", "voice_transport"}:
            function = (
                probe_integrated_voice
                if args.probe == "integrated_voice"
                else probe_voice_transport
            )
            ok, summary, facts = function(payload)
            _emit(ok, summary, facts=facts)
            return 0
        if args.probe == "live_api":
            ok, summary = probe_live_api(payload)
        else:
            ok, summary = PROBES[args.probe]()
        _emit(ok, summary)
    except BaseException as exc:
        _emit(False, f"Probe failed ({type(exc).__name__})", kind=_error_kind(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
