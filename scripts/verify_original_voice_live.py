"""Verify the exact installed Onyx native-audio voice contract against Gemini.

The verifier uses the production ``OnyxLive._build_config`` rather than a
reduced probe, requests one bounded spoken sentence, and can persist the raw
24 kHz PCM response as a WAV file for human acoustic acceptance.  It never
prints or writes the provider credential.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
import wave
from pathlib import Path

from google import genai

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main  # noqa: E402
from core.audio_contract import LIVE_VOICE, RECEIVE_SAMPLE_RATE  # noqa: E402


def _build_production_config(*, state_dir: Path) -> object:
    """Build the real live config without reading or mutating owner memory."""

    host = main.OnyxLive.__new__(main.OnyxLive)
    host._phase5 = None
    host._live_session_resume_handle = None
    host._assistant_identity_profile_v1 = main.AssistantIdentityProfileV1(
        state_dir / "assistant-identity-profile-v1.json"
    )
    host._spoken_language_memory_v1 = main.SpokenLanguageMemoryV1(
        state_dir / "spoken-language-memory-v1.json"
    )
    return main.OnyxLive._build_config(host)


async def _verify(*, timeout: float) -> tuple[bytes, str, str | None]:
    with tempfile.TemporaryDirectory(prefix="onyx-live-voice-verifier-") as temporary:
        config = _build_production_config(state_dir=Path(temporary))
    model = main.resolve_live_model(main.API_CONFIG_PATH)
    audio = bytearray()
    transcript: list[str] = []
    resume_handle: str | None = None

    client = genai.Client(
        api_key=main._get_api_key(),
        http_options={"api_version": "v1beta"},
    )

    async with client.aio.live.connect(model=model, config=config) as session:
        await session.send_client_content(
            turns={
                "parts": [
                    {
                        "text": (
                            "Voice identity verification. Say exactly one short, natural "
                            "sentence in Brazilian Portuguese confirming that Onyx is online."
                        )
                    }
                ]
            },
            turn_complete=True,
        )

        async def receive_turn() -> None:
            nonlocal resume_handle
            async for response in session.receive():
                if response.data:
                    audio.extend(response.data)
                update = response.session_resumption_update
                if update and update.resumable and update.new_handle:
                    resume_handle = str(update.new_handle)
                content = response.server_content
                if content and content.output_transcription:
                    text = str(content.output_transcription.text or "").strip()
                    if text:
                        transcript.append(text)
                if content and content.turn_complete:
                    return

        await asyncio.wait_for(receive_turn(), timeout=timeout)
    return bytes(audio), " ".join(transcript).strip(), resume_handle


def _write_wav(path: Path, pcm: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RECEIVE_SAMPLE_RATE)
        stream.writeframes(pcm)


def main_cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    audio, transcript, resume_handle = asyncio.run(_verify(timeout=args.timeout))
    if not audio:
        raise RuntimeError("Gemini Live returned no native audio")
    if args.output is not None:
        _write_wav(args.output.resolve(), audio)
    print(
        json.dumps(
            {
                "ok": True,
                "provider": "gemini-live",
                "model": main.resolve_live_model(main.API_CONFIG_PATH),
                "voice": LIVE_VOICE,
                "audio_bytes": len(audio),
                "sample_rate_hz": RECEIVE_SAMPLE_RATE,
                "transcript": transcript,
                "resumption_handle_received": bool(resume_handle),
                "output": str(args.output.resolve()) if args.output else None,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
