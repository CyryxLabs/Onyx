from __future__ import annotations

import pytest

from core.audio_device_selection_v1 import AudioDeviceSelectionError, AudioDeviceSelectionV1
from core.live_voice_preference_v1 import LiveVoicePreferenceV1, VOICES, parse_voice_intent


class Backend:
    class _Stream:
        def __init__(self, *, device, callback, blocksize, **_kwargs):
            if device == 4:
                raise RuntimeError("unusable")
            self.callback = callback
            self.blocksize = blocksize

        def start(self):
            self.callback(bytearray(self.blocksize * 2), self.blocksize, None, None)

        def abort(self):
            return None

        def close(self):
            return None

    InputStream = _Stream
    RawOutputStream = _Stream

    def query_devices(self):
        return [
            {"name": "Primary Sound Driver", "max_input_channels": 1, "max_output_channels": 1, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Studio Mic", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 1, "default_samplerate": 48000},
            {"name": "Studio Mic", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 2, "default_samplerate": 48000},
            {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0, "default_samplerate": 48000},
            {"name": "Broken", "max_input_channels": 1, "max_output_channels": 1, "hostapi": 0, "default_samplerate": 48000},
        ]

def test_all_supported_voices_persist_and_commands_are_bounded(tmp_path) -> None:
    profile = LiveVoicePreferenceV1(tmp_path / "voice.json")
    assert profile.get() == "Charon"
    for voice in VOICES:
        assert profile.set(voice.lower()) == voice
        assert LiveVoicePreferenceV1(profile.path).get() == voice
    assert parse_voice_intent("Onyx, change your voice to Kore").voice == "Kore"
    assert parse_voice_intent("delete files").matched is False
    assert parse_voice_intent("use voice Unknown").matched is True
    assert parse_voice_intent("use voice Unknown").voice is None


def test_audio_devices_are_measured_deduplicated_and_name_stable(tmp_path) -> None:
    selector = AudioDeviceSelectionV1(tmp_path / "devices.json", Backend())
    assert [item.name for item in selector.list_usable("input")] == ["Studio Mic"]
    assert [item.name for item in selector.list_usable("output")] == ["Speakers"]
    selected = selector.select("input", "studio mic")
    assert selected.index == 1
    assert selector.resolve("input") == (1, "owner-selected")


def test_missing_saved_device_falls_back_observably(tmp_path) -> None:
    selector = AudioDeviceSelectionV1(tmp_path / "devices.json", Backend())
    selector.select("output", "Speakers")
    selector.backend.query_devices = lambda: []
    assert selector.resolve("output") == (None, "saved-device-unavailable; system-default")


def test_unknown_device_is_refused(tmp_path) -> None:
    selector = AudioDeviceSelectionV1(tmp_path / "devices.json", Backend())
    with pytest.raises(AudioDeviceSelectionError):
        selector.select("input", "Webcam")


def test_audio_probe_uses_shipping_callback_stream_mode(tmp_path) -> None:
    backend = Backend()
    selector = AudioDeviceSelectionV1(tmp_path / "devices.json", backend)
    assert selector.list_usable("input")[0].name == "Studio Mic"
    assert selector.list_usable("output")[0].name == "Speakers"
