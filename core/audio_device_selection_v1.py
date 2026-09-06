"""Measured, name-stable audio-device selection for Onyx."""
from __future__ import annotations

import json
import os
import platform
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from core.audio_contract import CHANNELS, CHUNK_SIZE, RECEIVE_SAMPLE_RATE, SEND_SAMPLE_RATE

SCHEMA: Final = "onyx.audio-device-selection/v1"
_PREFERRED_APIS: Final = {
    "Windows": ("directsound", "mme", "wasapi"),
    "Darwin": ("core audio",),
    "Linux": ("pulse", "pipewire", "jack", "alsa"),
}


class AudioDeviceSelectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioDeviceV1:
    index: int
    name: str
    direction: str
    hostapi: int
    default_samplerate: float


class AudioDeviceSelectionV1:
    def __init__(self, path: Path | str, backend: object) -> None:
        self.path = Path(path)
        self.backend = backend

    def _probe_stream(self, direction: str, index: int) -> bool:
        """Measure frames through the exact callback stream mode Onyx ships."""

        rate = SEND_SAMPLE_RATE if direction == "input" else RECEIVE_SAMPLE_RATE
        delivered = 0
        threshold = max(CHUNK_SIZE, int(rate * 0.04))
        ready = threading.Event()

        def callback(buffer, frames, *_args) -> None:
            nonlocal delivered
            if direction == "output":
                output = memoryview(buffer).cast("B")
                output[:] = b"\x00" * len(output)
            delivered += int(frames)
            if delivered >= threshold:
                ready.set()

        factory = (
            self.backend.InputStream
            if direction == "input"
            else self.backend.RawOutputStream
        )
        stream = None
        try:
            stream = factory(
                device=index,
                samplerate=rate,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            )
            stream.start()
            return ready.wait(0.35)
        except Exception:
            return False
        finally:
            if stream is not None:
                for operation_name in ("abort", "close"):
                    operation = getattr(stream, operation_name, None)
                    if callable(operation):
                        try:
                            operation()
                        except Exception:
                            pass

    def _configured_names(self) -> dict[str, str]:
        if not self.path.exists():
            return {"input": "", "output": ""}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise AudioDeviceSelectionError("audio device profile is malformed") from exc
        if raw.get("schema") != SCHEMA:
            raise AudioDeviceSelectionError("audio device profile schema is invalid")
        return {key: str(raw.get(key, "")).strip() for key in ("input", "output")}

    def list_usable(self, direction: str) -> tuple[AudioDeviceV1, ...]:
        if direction not in {"input", "output"}:
            raise ValueError("direction must be input or output")
        channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
        devices = list(self.backend.query_devices())
        try:
            api_names = [str(item.get("name", "")) for item in self.backend.query_hostapis()]
        except (AttributeError, TypeError):
            api_names = []

        def collect(api_marker: str | None) -> tuple[AudioDeviceV1, ...]:
            seen: set[str] = set()
            result: list[AudioDeviceV1] = []
            for index, raw in enumerate(devices):
                name = " ".join(str(raw.get("name", "")).split())
                key = name.casefold()
                hostapi = int(raw.get("hostapi", -1))
                api_name = (
                    api_names[hostapi].casefold()
                    if 0 <= hostapi < len(api_names)
                    else ""
                )
                if api_marker is not None and api_marker not in api_name:
                    continue
                if not name or key in seen or int(raw.get(channel_key, 0) or 0) < 1:
                    continue
                if any(
                    marker in key
                    for marker in (
                        "sound mapper",
                        "primary sound",
                        "sysdefault",
                        "dmix",
                    )
                ):
                    continue
                rate = float(raw.get("default_samplerate", 0) or 0)
                if not self._probe_stream(direction, index):
                    continue
                seen.add(key)
                result.append(
                    AudioDeviceV1(index, name, direction, hostapi, rate)
                )
            return tuple(result)

        preferred = _PREFERRED_APIS.get(platform.system(), ()) if api_names else ()
        for marker in (*preferred, None):
            result = collect(marker)
            if result:
                return result
        return ()

    def select(self, direction: str, name: str) -> AudioDeviceV1:
        normalized = " ".join(str(name).split())
        matches = [item for item in self.list_usable(direction) if item.name.casefold() == normalized.casefold()]
        if len(matches) != 1:
            raise AudioDeviceSelectionError("selected audio device is unavailable")
        current = self._configured_names()
        current[direction] = matches[0].name
        document = {"schema": SCHEMA, **current}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return matches[0]

    def resolve(self, direction: str) -> tuple[int | None, str]:
        selected = self._configured_names()[direction]
        if not selected:
            return None, "system-default"
        for item in self.list_usable(direction):
            if item.name.casefold() == selected.casefold():
                return item.index, "owner-selected"
        return None, "saved-device-unavailable; system-default"

    def configured_name(self, direction: str) -> str:
        if direction not in {"input", "output"}:
            raise ValueError("direction must be input or output")
        return self._configured_names()[direction]

    def status(self) -> dict[str, object]:
        selected = self._configured_names()
        return {
            "schema": SCHEMA,
            "selected": selected,
            "input": [asdict(item) for item in self.list_usable("input")],
            "output": [asdict(item) for item in self.list_usable("output")],
        }
