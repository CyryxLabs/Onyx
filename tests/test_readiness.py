import asyncio
import io
import inspect
import json
import subprocess
import sys
import tempfile
import time
import types
import unittest
from contextlib import nullcontext, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch
import psutil

from core import readiness
from core import readiness_probe
from core.audio_contract import VoiceContractError
from core.live_model import (
    DEFAULT_LIVE_MODEL,
    _live_input_kwargs,
    adapt_live_audio_transport,
    install_live_audio_transport_compat,
    resolve_live_model,
    unwrap_live_audio_transport,
)


class IntegratedVoiceLoopTests(unittest.TestCase):
    class Sample:
        def __init__(self, data):
            self.data = data

        def tobytes(self):
            return self.data

    class Output:
        def __init__(self, owner):
            self.owner = owner

        def start(self):
            self.owner.events.append("output-start")

        def write(self, data):
            if self.owner.fail_output and self.owner.outputs > 1:
                raise RuntimeError("speaker failed")
            self.owner.written += len(data)

        def stop(self):
            self.owner.events.append("output-stop")

        def close(self):
            self.owner.events.append("output-close")

    class Input:
        def __init__(self, owner, callback):
            self.owner = owner
            self.callback = callback

        def start(self):
            self.owner.events.append("input-start")
            self.callback(self.owner.data, 1024, None, None)

        def stop(self):
            self.owner.events.append("input-stop")

        def close(self):
            self.owner.events.append("input-close")

    class Audio:
        def __init__(self, data=b"\x01\x00" * 1024, fail_output=False):
            self.data = data
            self.fail_output = fail_output
            self.written = 0
            self.outputs = 0
            self.events = []

        def InputStream(self, **kwargs):
            return IntegratedVoiceLoopTests.Input(self, kwargs["callback"])

        def RawOutputStream(self, **k):
            self.outputs += 1
            return IntegratedVoiceLoopTests.Output(self)

    class Session:
        def __init__(self, responses):
            self.responses = responses
            self.sent = []

        async def send_realtime_input(self, **kw):
            self.sent.append(kw)

        async def send_client_content(self, **kw):
            self.sent.append(kw)

        async def receive(self):
            while not any("media" in item for item in self.sent):
                await asyncio.sleep(0)
            for item in self.responses:
                yield item

    class Connect:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, *a):
            pass

    class Client:
        def __init__(self, session):
            self.aio = types.SimpleNamespace(
                live=types.SimpleNamespace(
                    connect=lambda **k: IntegratedVoiceLoopTests.Connect(session)
                )
            )

        def close(self):
            pass

    def response(
        self, audio=b"\x02\x00" * 100, complete=True, transcript="Onyx readiness check"
    ):
        return types.SimpleNamespace(
            data=audio,
            server_content=types.SimpleNamespace(
                turn_complete=complete,
                input_transcription=types.SimpleNamespace(text=transcript),
            ),
        )

    def test_success_and_no_speech(self):
        audio = self.Audio()
        session = self.Session([self.response()])
        facts = asyncio.run(
            readiness_probe._integrated_voice_loop(
                "key",
                "model",
                client_factory=lambda **k: self.Client(session),
                sd_module=audio,
                capture_seconds=0.1,
            )
        )
        self.assertTrue(facts["ok"])
        self.assertTrue(facts["transcript_matched"])
        self.assertTrue(facts["cue_played"])
        self.assertTrue(facts["turn_complete_before_stream_end"])
        self.assertGreater(facts["mic_bytes_sent"], 0)
        self.assertGreater(facts["speaker_frames_written"], 0)
        self.assertFalse(
            any(
                "audio_stream_end" in x
                or "activity_start" in x
                or "activity_end" in x
                or "turns" in x
                for x in session.sent
            )
        )
        self.assertTrue(
            all(len(x["media"]["data"]) <= 2048 for x in session.sent if "media" in x)
        )
        self.assertLess(
            audio.events.index("output-start"), audio.events.index("input-start")
        )
        self.assertEqual(audio.events.count("input-close"), 1)
        self.assertEqual(audio.events.count("output-close"), 2)
        silent = asyncio.run(
            readiness_probe._integrated_voice_loop(
                "key",
                "model",
                client_factory=lambda **k: self.Client(session),
                sd_module=self.Audio(b"\0" * 20),
            )
        )
        self.assertFalse(silent["ok"])
        self.assertEqual(silent["mic_bytes_sent"], 0)

    def test_transcript_completion_and_audio_are_all_required(self):
        for response in (
            self.response(transcript="ambient noise"),
            self.response(audio=b""),
            self.response(complete=False),
        ):
            with self.subTest(response=response):
                facts = asyncio.run(
                    readiness_probe._integrated_voice_loop(
                        "key",
                        "model",
                        client_factory=lambda **k: self.Client(
                            self.Session([response])
                        ),
                        sd_module=self.Audio(),
                        capture_seconds=0.1,
                    )
                )
                self.assertFalse(facts["ok"])

    def test_speaker_failure_is_failure(self):
        audio = self.Audio(fail_output=True)
        with self.assertRaises(RuntimeError):
            asyncio.run(
                readiness_probe._integrated_voice_loop(
                    "key",
                    "model",
                    client_factory=lambda **k: self.Client(
                        self.Session([self.response()])
                    ),
                    sd_module=audio,
                    capture_seconds=0.1,
                )
            )
        self.assertEqual(audio.events.count("output-close"), 2)

    def test_each_stream_failure_still_closes_target_once(self):
        owner = self

        class FaultAudio(self.Audio):
            def __init__(self, target, method):
                super().__init__()
                self.target = target
                self.method = method
                self.target_closes = 0

            def _wrap(self, stream, name):
                audio = self

                class Wrapped:
                    def start(w):
                        if audio.target == name and audio.method == "start":
                            raise RuntimeError("start")
                        return stream.start()

                    def write(w, data):
                        if audio.target == name and audio.method == "write":
                            raise RuntimeError("write")
                        return stream.write(data)

                    def stop(w):
                        if audio.target == name and audio.method == "stop":
                            raise RuntimeError("stop")
                        return stream.stop()

                    def close(w):
                        if audio.target == name:
                            audio.target_closes += 1
                        if audio.target == name and audio.method == "close":
                            raise RuntimeError("close")
                        return stream.close()

                return Wrapped()

            def RawOutputStream(self, **kwargs):
                self.outputs += 1
                name = "cue" if self.outputs == 1 else "speaker"
                return self._wrap(owner.Output(self), name)

            def InputStream(self, **kwargs):
                return self._wrap(owner.Input(self, kwargs["callback"]), "input")

        for target, methods in (
            ("cue", ("start", "write", "stop", "close")),
            ("input", ("start", "stop", "close")),
            ("speaker", ("start", "write", "stop", "close")),
        ):
            for method in methods:
                with self.subTest(target=target, method=method):
                    audio = FaultAudio(target, method)
                    with self.assertRaises(RuntimeError):
                        asyncio.run(
                            readiness_probe._integrated_voice_loop(
                                "key",
                                "model",
                                client_factory=lambda **k: self.Client(
                                    self.Session([self.response()])
                                ),
                                sd_module=audio,
                                capture_seconds=0.1,
                            )
                        )
                    self.assertEqual(audio.target_closes, 1)

    def test_response_timeout_and_hostile_frames_fail_closed(self):
        class Hanging(self.Session):
            async def receive(self):
                await asyncio.sleep(1)
                if False:
                    yield None

        diagnostics = {}
        with self.assertRaises(asyncio.TimeoutError):
            asyncio.run(
                readiness_probe._integrated_voice_loop(
                    "key",
                    "model",
                    client_factory=lambda **k: self.Client(Hanging([])),
                    sd_module=self.Audio(),
                    capture_seconds=0.1,
                    response_timeout=0.01,
                    diagnostics=diagnostics,
                )
            )
        self.assertEqual(diagnostics["stage"], "receive")
        self.assertGreater(diagnostics["mic_bytes_sent"], 0)
        self.assertFalse(diagnostics["turn_complete"])
        for data, transcript in (
            (object(), "Onyx readiness"),
            (b"x" * 144001, "Onyx readiness"),
            (b"ok", object()),
            (b"ok", "x" * 501),
        ):
            with self.subTest(data=type(data), transcript=type(transcript)):
                with self.assertRaises(ValueError):
                    asyncio.run(
                        readiness_probe._integrated_voice_loop(
                            "key",
                            "model",
                            client_factory=lambda **k: self.Client(
                                self.Session(
                                    [self.response(audio=data, transcript=transcript)]
                                )
                            ),
                            sd_module=self.Audio(),
                            capture_seconds=0.1,
                        )
                    )

    def test_audio_contract_cannot_drift_from_main(self):
        import main
        from core import audio_contract

        self.assertEqual(
            (
                main.SEND_SAMPLE_RATE,
                main.RECEIVE_SAMPLE_RATE,
                main.CHUNK_SIZE,
                main.CHANNELS,
            ),
            (
                audio_contract.SEND_SAMPLE_RATE,
                audio_contract.RECEIVE_SAMPLE_RATE,
                audio_contract.CHUNK_SIZE,
                audio_contract.CHANNELS,
            ),
        )
        self.assertEqual(main.LIVE_VOICE, audio_contract.LIVE_VOICE)
        from google.genai.live import AsyncSession

        parameters = inspect.signature(AsyncSession.send_realtime_input).parameters
        self.assertIn("activity_start", parameters)
        self.assertIn("activity_end", parameters)

    def test_no_transcript_is_specific_failure_stage(self):
        facts = asyncio.run(
            readiness_probe._integrated_voice_loop(
                "key",
                "model",
                client_factory=lambda **k: self.Client(
                    self.Session([self.response(transcript="")])
                ),
                sd_module=self.Audio(),
                capture_seconds=0.1,
            )
        )
        self.assertFalse(facts["ok"])
        self.assertEqual(facts["stage"], "transcript")
        self.assertEqual(facts["speaker_frames_written"], 0)

    def test_manual_transport_uses_explicit_vad_order(self):
        session = self.Session([self.response()])
        facts = asyncio.run(
            readiness_probe._integrated_voice_loop(
                "key",
                "model",
                client_factory=lambda **k: self.Client(session),
                sd_module=self.Audio(),
                capture_seconds=0.1,
                manual_vad=True,
            )
        )
        self.assertTrue(facts["ok"])
        self.assertEqual(session.sent[0], {"activity_start": {}})
        self.assertEqual(session.sent[-1], {"activity_end": {}})
        self.assertFalse(any("audio_stream_end" in item for item in session.sent))

    def test_callback_flood_and_partial_chunks_stay_bounded_and_exact(self):
        from core.audio_contract import MAX_VOICE_ACCEPTANCE_MIC_BYTES

        class FloodInput(self.Input):
            def start(stream):
                stream.owner.events.append("input-start")
                for _ in range(200):
                    stream.callback(stream.owner.data, 1024, None, None)

        class FloodAudio(self.Audio):
            def InputStream(audio, **kwargs):
                return FloodInput(audio, kwargs["callback"])

        audio = FloodAudio(b"\x01" * 2047)
        session = self.Session([self.response()])
        facts = asyncio.run(
            readiness_probe._integrated_voice_loop(
                "key",
                "model",
                client_factory=lambda **k: self.Client(session),
                sd_module=audio,
                capture_seconds=0.1,
                manual_vad=True,
            )
        )
        sent = sum(
            len(item["media"]["data"]) for item in session.sent if "media" in item
        )
        self.assertLessEqual(
            facts["mic_bytes_accepted"], MAX_VOICE_ACCEPTANCE_MIC_BYTES
        )
        self.assertEqual(facts["mic_bytes_sent"], sent)
        self.assertEqual(sent, facts["mic_bytes_accepted"])
        self.assertEqual(facts["mic_bytes_accepted"] % 2, 0)
        self.assertGreater(facts["callback_chunks_dropped"], 0)


class ReadinessSemanticsTests(unittest.TestCase):
    def test_integrated_voice_success_is_the_only_operational_acceptance(self):
        facts = {
            "mic_bytes_accepted": 32000,
            "mic_bytes_sent": 32000,
            "model_audio_bytes_received": 4800,
            "speaker_frames_written": 2400,
            "turn_complete": True,
            "transcript_matched": True,
            "cue_played": True,
            "vad_mode": "automatic",
            "activity_markers_sent": False,
            "turn_complete_before_stream_end": True,
        }
        results = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result(
                "integrated_voice",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=facts,
            ),
        ]
        state = readiness.readiness_state(results)
        payload = json.loads(readiness.render_json(results))
        self.assertTrue(state["ready"])
        self.assertTrue(state["operationally_verified"])
        self.assertTrue(state["capabilities"]["integrated_voice_loop_verified"])
        self.assertEqual(payload["results"][1]["facts"], facts)
        self.assertEqual(readiness.exit_code(results), 0)

    def test_integrated_evidence_is_required_and_other_selected_failure_stays_not_ready(
        self,
    ):
        valid = {
            "mic_bytes_accepted": 2048,
            "mic_bytes_sent": 2048,
            "model_audio_bytes_received": 200,
            "speaker_frames_written": 100,
            "turn_complete": True,
            "transcript_matched": True,
            "cue_played": True,
            "vad_mode": "automatic",
            "activity_markers_sent": False,
            "turn_complete_before_stream_end": True,
        }
        for changed in (
            {},
            {"cue_played": False},
            {"mic_bytes_sent": 0},
            {"model_audio_bytes_received": 144001},
            {"speaker_frames_written": 72001},
        ):
            facts = {**valid, **changed}
            results = [
                readiness.Result("runtime", "PASS", "ok", required=True),
                readiness.Result(
                    "integrated_voice",
                    "PASS",
                    "ok",
                    required=True,
                    selected=True,
                    facts=facts,
                ),
            ]
            state = readiness.readiness_state(results)
            self.assertEqual(state["ready"], not changed)
            self.assertEqual(
                state["capabilities"]["integrated_voice_loop_verified"], not changed
            )
        mixed = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result(
                "integrated_voice",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=valid,
            ),
            readiness.Result(
                "camera_probe", "FAIL", "bad", required=True, selected=True
            ),
        ]
        state = readiness.readiness_state(mixed)
        self.assertTrue(state["capabilities"]["integrated_voice_loop_verified"])
        self.assertFalse(state["selected_probes_verified"])
        self.assertFalse(state["ready"])
        self.assertEqual(readiness.exit_code(mixed), 1)
        self.assertIn(
            "NOT READY; INTEGRATED VOICE VERIFIED BUT SELECTED SCOPE FAILED",
            readiness.render_human(mixed),
        )
        warned = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result("config", "WARN", "optional", required=False),
            readiness.Result(
                "integrated_voice",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=valid,
            ),
        ]
        capabilities = readiness.readiness_state(warned)["capabilities"]
        self.assertTrue(capabilities["voice_prerequisites_verified"])
        self.assertTrue(capabilities["core_voice_components_verified"])
        manual = {
            **valid,
            "vad_mode": "manual",
            "activity_markers_sent": True,
            "turn_complete_before_stream_end": False,
        }
        transport = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result(
                "voice_transport",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=manual,
            ),
        ]
        transport_state = readiness.readiness_state(transport)
        self.assertTrue(transport_state["capabilities"]["voice_transport_verified"])
        self.assertFalse(
            transport_state["capabilities"]["integrated_voice_loop_verified"]
        )
        self.assertFalse(transport_state["ready"])
        self.assertFalse(transport_state["operationally_verified"])
        swapped_integrated = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result(
                "integrated_voice",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=manual,
            ),
        ]
        swapped_transport = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result(
                "voice_transport",
                "PASS",
                "ok",
                required=True,
                selected=True,
                facts=valid,
            ),
        ]
        self.assertFalse(
            readiness.readiness_state(swapped_integrated)["capabilities"][
                "integrated_voice_loop_verified"
            ]
        )
        self.assertFalse(
            readiness.readiness_state(swapped_transport)["capabilities"][
                "voice_transport_verified"
            ]
        )

    def test_required_warn_or_fail_makes_install_not_ready(self):
        for status in ("WARN", "FAIL"):
            with self.subTest(status=status):
                results = [readiness.Result("runtime", status, "bad", required=True)]
                state = readiness.readiness_state(results)
                self.assertFalse(state["install_ready"])
                self.assertFalse(state["ready"])
                self.assertEqual(readiness.exit_code(results), 1)

    def test_selected_failure_is_never_false_ready(self):
        results = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result("live_api", "FAIL", "bad", required=True, selected=True),
        ]
        state = readiness.readiness_state(results)
        self.assertTrue(state["install_ready"])
        self.assertFalse(state["selected_ready"])
        self.assertFalse(state["operationally_verified"])
        self.assertFalse(state["ready"])
        self.assertEqual(readiness.exit_code(results), 1)

    def test_unselected_install_can_be_ready_but_not_operationally_verified(self):
        results = [readiness.Result("runtime", "PASS", "ok", required=True)]
        state = readiness.readiness_state(results)
        self.assertTrue(state["install_ready"])
        self.assertIsNone(state["selected_ready"])
        self.assertFalse(state["operationally_verified"])
        self.assertFalse(state["ready"])
        self.assertEqual(readiness.exit_code(results), 0)

    def test_json_and_human_have_explicit_verdicts(self):
        results = [readiness.Result("runtime", "PASS", "ok", required=True)]
        payload = json.loads(readiness.render_json(results))
        human = readiness.render_human(results)
        self.assertEqual(payload["schema_version"], 4)
        self.assertTrue(payload["install_ready"])
        self.assertFalse(payload["operationally_verified"])
        self.assertIn("Install verdict: READY", human)
        self.assertIn("Selected probe verdict: NOT REQUESTED", human)
        self.assertIn("Capabilities: voice prerequisites=NOT VERIFIED", human)
        self.assertIn("COMPONENTS NOT VERIFIED / INTEGRATED VOICE NOT VERIFIED", human)
        self.assertIn("Full voice operational verdict: NOT VERIFIED", human)
        self.assertIn(
            "Overall verdict (installation scope): INSTALL READY; OPERATION NOT VERIFIED",
            human,
        )

    def test_core_voice_and_optional_camera_combinations(self):
        def result(check, selected=False, status="PASS", required=True):
            return readiness.Result(
                check, status, "test", required=required, selected=selected
            )

        install = [
            result("runtime"),
            result("dashboard"),
            result("config", required=False),
        ]
        live = result("live_api", selected=True)
        audio = result("audio_devices", selected=True)
        mic = result("microphone_probe", selected=True)
        camera = result("camera_probe", selected=True)
        cases = (
            ("none", install, False, None, False),
            ("live", install + [live], False, True, False),
            ("hardware", install + [audio, mic], False, True, False),
            ("camera", install + [camera], False, True, True),
            ("voice", install + [live, audio, mic], True, True, False),
            ("voice-camera", install + [live, audio, mic, camera], True, True, True),
        )
        for name, results, voice, selected, vision in cases:
            with self.subTest(name=name):
                state = readiness.readiness_state(results)
                self.assertFalse(state["ready"])
                self.assertEqual(state["selected_probes_verified"], selected)
                self.assertEqual(
                    state["capabilities"]["voice_prerequisites_verified"], voice
                )
                self.assertEqual(state["capabilities"]["camera_verified"], vision)
                self.assertFalse(
                    state["capabilities"]["integrated_voice_loop_verified"]
                )
                self.assertEqual(readiness.exit_code(results), 0)

        failed_camera = install + [
            live,
            audio,
            mic,
            result("camera_probe", selected=True, status="FAIL"),
        ]
        state = readiness.readiness_state(failed_camera)
        self.assertFalse(state["ready"])
        self.assertFalse(state["selected_probes_verified"])
        self.assertFalse(state["capabilities"]["camera_verified"])
        self.assertTrue(state["capabilities"]["voice_prerequisites_verified"])
        self.assertEqual(readiness.exit_code(failed_camera), 1)

    def test_exit_requires_install_baseline_and_any_selected_probes(self):
        def result(check, status, *, selected=False):
            return readiness.Result(
                check, status, "test", required=True, selected=selected
            )

        cases = (
            ("install-pass-none", [result("runtime", "PASS")], True, None, 0),
            ("install-fail-none", [result("runtime", "FAIL")], False, None, 1),
            (
                "install-pass-selected-pass",
                [result("runtime", "PASS"), result("camera", "PASS", selected=True)],
                True,
                True,
                0,
            ),
            (
                "install-pass-selected-fail",
                [result("runtime", "PASS"), result("camera", "FAIL", selected=True)],
                True,
                False,
                1,
            ),
            (
                "install-fail-selected-pass",
                [result("runtime", "FAIL"), result("camera", "PASS", selected=True)],
                False,
                True,
                1,
            ),
        )
        for name, results, install_ready, selected_verified, expected_exit in cases:
            with self.subTest(name=name):
                state = readiness.readiness_state(results)
                self.assertEqual(state["install_ready"], install_ready)
                self.assertEqual(state["selected_probes_verified"], selected_verified)
                self.assertEqual(readiness.exit_code(results), expected_exit)

    def test_human_verdict_never_masks_failed_install_with_selected_success(self):
        results = [
            readiness.Result("runtime", "FAIL", "bad", required=True),
            readiness.Result(
                "camera_probe", "PASS", "ok", required=True, selected=True
            ),
        ]
        human = readiness.render_human(results)
        self.assertIn("Install verdict: NOT READY", human)
        self.assertIn("Selected probe verdict: VERIFIED", human)
        self.assertIn(
            "Overall verdict (installation and selected probes scope): "
            "NOT READY; INSTALL BASELINE FAILED",
            human,
        )

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            readiness.Result("bad", "UNKNOWN", "invalid")


class ReadinessSafetyTests(unittest.TestCase):
    def test_live_probe_never_falls_back_to_plaintext_config_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text(
                json.dumps(
                    {"gemini_api_key": "plaintext", "live_model": "models/test"}
                ),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    "os.environ", {"ONYX_READINESS_CONFIG": str(path)}, clear=True
                ),
                patch.object(
                    readiness_probe, "get_gemini_credential", return_value=None
                ),
            ):
                with self.assertRaisesRegex(ValueError, "absent"):
                    readiness_probe._read_live_config()

    def test_config_output_never_contains_secret_value(self):
        secret = "do-not-print-this-api-key"
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "api_keys.json"
            config_path.write_text(
                json.dumps({"os_system": "Windows", "live_model": "models/test"}),
                encoding="utf-8",
            )
            config, result = readiness._load_config_shape(config_path)
        self.assertNotIn("gemini_api_key", config)
        rendered = readiness.render_human([result]) + readiness.render_json([result])
        self.assertNotIn(secret, rendered)
        self.assertIn("Non-secret config shape valid", rendered)

    def test_malformed_model_is_required_failure_without_echo(self):
        bad_model = "secret?invalid/model"
        with patch.dict("os.environ", {"ONYX_LIVE_MODEL": bad_model}):
            result = readiness.check_model(None)
        self.assertEqual(result.status, "FAIL")
        self.assertTrue(result.required)
        self.assertNotIn(bad_model, result.summary)

    def test_runtime_dir_probe_removes_transient_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(readiness, "ROOT", root):
                result = readiness.check_runtime_dirs()
            self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(result.status, "PASS")

    def test_probe_stdout_noise_never_reaches_structured_result(self):
        payload = {"ok": True, "summary": "clean", "kind": ""}
        process = MagicMock()
        process.returncode = 0
        process.communicate.return_value = (
            "third party noise\n"
            + readiness.SENTINEL
            + json.dumps(payload)
            + "\nmore noise",
            "sensitive stderr",
        )
        stdin = MagicMock()
        process.stdin = stdin
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(
                readiness, "_terminate_retained_tree", return_value=True
            ) as release,
        ):
            result = readiness._run_isolated_probe("runtime_import", 1)
        self.assertEqual(result, payload)
        self.assertEqual(stdin.write.call_count, 2)
        release.assert_called_once_with(identity)

    def test_isolated_probe_environment_is_allowlisted(self):
        payload = {"ok": True, "summary": "clean", "kind": ""}
        process = MagicMock()
        process.returncode = 0
        process.communicate.return_value = (
            readiness.SENTINEL + json.dumps(payload),
            "",
        )
        stdin = MagicMock()
        process.stdin = stdin
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.dict(
                "os.environ",
                {"PATH": "safe-path", "UNRELATED_SECRET": "leak-me",
                 "APPDATA": "owner-roaming", "LOCALAPPDATA": "owner-local",
                 "PYTHONPATH": "unapproved-import-path"},
                clear=True,
            ),
            patch.object(readiness.subprocess, "Popen", return_value=process) as popen,
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(readiness, "_terminate_retained_tree", return_value=True),
        ):
            readiness._run_isolated_probe("runtime_import", 1)
        child_env = popen.call_args.kwargs["env"]
        self.assertEqual(child_env["PATH"], "safe-path")
        self.assertNotIn("UNRELATED_SECRET", child_env)
        self.assertNotIn("PYTHONPATH", child_env)
        self.assertEqual(child_env["APPDATA"], "owner-roaming")
        self.assertEqual(child_env["LOCALAPPDATA"], "owner-local")

    def test_live_secret_is_sent_only_in_parent_payload(self):
        payload = {"ok": True, "summary": "clean", "kind": ""}
        process = MagicMock()
        process.returncode = 0
        process.communicate.return_value = (
            readiness.SENTINEL + json.dumps(payload),
            "",
        )
        stdin = MagicMock()
        process.stdin = stdin
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "keys.json"
            config.write_text(
                json.dumps({"live_model": DEFAULT_LIVE_MODEL}),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    "os.environ", {"UNRELATED_TOKEN": "do-not-pass"}, clear=True
                ),
                patch.object(
                    readiness, "get_gemini_credential", return_value="required-key"
                ),
                patch.object(
                    readiness.subprocess, "Popen", return_value=process
                ) as popen,
                patch.object(
                    readiness, "_capture_process_tree_identity", return_value=identity
                ),
                patch.object(readiness, "_terminate_retained_tree", return_value=True),
            ):
                readiness._run_isolated_probe("live_api", 1, config_path=config)
        child_env = popen.call_args.kwargs["env"]
        self.assertNotIn("required-key", child_env.values())
        self.assertNotIn("UNRELATED_TOKEN", child_env)
        written = "".join(call.args[0] for call in stdin.write.call_args_list)
        self.assertIn('"api_key":"required-key"', written)
        self.assertIn(f'"model":"{DEFAULT_LIVE_MODEL}"', written)
        self.assertNotIn("do-not-pass", written)

    def test_probe_pass_sentinel_requires_zero_exit(self):
        payload = {"ok": True, "summary": "clean", "kind": ""}
        process = MagicMock()
        process.returncode = 7
        process.communicate.return_value = (
            readiness.SENTINEL + json.dumps(payload) + "\nsecret worker output",
            "secret worker error",
        )
        process.stdin = MagicMock()
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(readiness, "_terminate_retained_tree", return_value=True),
        ):
            result = readiness._run_isolated_probe("runtime_import", 1)
        self.assertEqual(
            result,
            {
                "ok": False,
                "kind": "process_exit",
                "summary": "Probe runtime_import exited with code 7",
            },
        )
        self.assertNotIn("secret", result["summary"])

    def test_probe_zero_exit_accepts_valid_pass_sentinel(self):
        payload = {"ok": True, "summary": "clean", "kind": ""}
        process = MagicMock()
        process.returncode = 0
        process.communicate.return_value = (
            readiness.SENTINEL + json.dumps(payload),
            "",
        )
        process.stdin = MagicMock()
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(readiness, "_terminate_retained_tree", return_value=True),
        ):
            result = readiness._run_isolated_probe("runtime_import", 1)
        self.assertEqual(result, payload)

    def test_probe_nonzero_without_sentinel_is_structured_failure(self):
        process = MagicMock()
        process.returncode = -9
        process.communicate.return_value = ("untrusted output", "untrusted error")
        process.stdin = MagicMock()
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(readiness, "_terminate_retained_tree", return_value=True),
        ):
            result = readiness._run_isolated_probe("runtime_import", 1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["kind"], "process_exit")
        self.assertEqual(result["summary"], "Probe runtime_import exited with code -9")

    def test_subprocess_timeout_terminates_and_reaps(self):
        process = MagicMock()
        process.communicate.side_effect = subprocess.TimeoutExpired("probe", 0.1)
        process.stdin = MagicMock()
        identity = ("job", 123) if sys.platform == "win32" else ("process_group", 123)
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=identity
            ),
            patch.object(readiness, "_terminate_process_tree") as terminate,
            patch.object(readiness, "_terminate_retained_tree"),
        ):
            with self.assertRaises(subprocess.TimeoutExpired):
                readiness._run_isolated_probe("runtime_import", 0.1)
        terminate.assert_called_once_with(process)

    def test_assignment_failure_never_releases_start_gate(self):
        process = MagicMock()
        process.stdin = MagicMock()
        with (
            patch.object(readiness.subprocess, "Popen", return_value=process),
            patch.object(
                readiness, "_capture_process_tree_identity", return_value=None
            ),
            patch.object(readiness, "_terminate_process_tree") as terminate,
        ):
            with self.assertRaisesRegex(RuntimeError, "retain readiness"):
                readiness._run_isolated_probe("runtime_import", 1)
        process.stdin.write.assert_not_called()
        terminate.assert_called_once_with(process)

    def test_exited_child_with_descendant_held_pipes_never_communicates(self):
        process = MagicMock()
        process.poll.return_value = 0
        process.stdout = MagicMock()
        process.stderr = MagicMock()
        readiness._terminate_process_tree(process)
        process.stdout.close.assert_called_once()
        process.stderr.close.assert_called_once()
        process.wait.assert_called()
        process.communicate.assert_not_called()

    def test_last_resort_reap_is_bounded_when_kill_cannot_finish(self):
        process = MagicMock()
        process.wait.side_effect = subprocess.TimeoutExpired("probe", 1)
        readiness._bounded_reap(process, timeout=0.01)
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_real_descendant_inherited_pipe_cleanup_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            go = root / "go"
            pid_file = root / "pid"
            child_code = (
                "import pathlib,subprocess,sys,time;"
                f"go=pathlib.Path({str(go)!r});pid=pathlib.Path({str(pid_file)!r});"
                "\nwhile not go.exists(): time.sleep(.01)\n"
                "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                "pid.write_text(str(p.pid))"
            )
            options = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
            }
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                options["start_new_session"] = True
            process = subprocess.Popen([sys.executable, "-c", child_code], **options)
            process._onyx_tree_identity = readiness._capture_process_tree_identity(
                process
            )
            self.assertIsNotNone(process._onyx_tree_identity)
            if sys.platform == "win32":
                self.assertEqual(process._onyx_tree_identity[0], "job")
            go.touch()
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            descendant_pid = int(pid_file.read_text())
            descendant = psutil.Process(descendant_pid)
            created = descendant.create_time()
            process.wait(timeout=5)
            started = time.monotonic()
            guard = (
                patch.object(
                    readiness.os,
                    "killpg",
                    side_effect=AssertionError("Windows must not call os.killpg"),
                    create=True,
                )
                if sys.platform == "win32"
                else nullcontext()
            )
            with guard:
                readiness._terminate_process_tree(process)
            self.assertLess(time.monotonic() - started, 3.0)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    current = psutil.Process(descendant_pid)
                    alive = current.create_time() == created and current.is_running()
                    alive = alive and current.status() != psutil.STATUS_ZOMBIE
                except psutil.NoSuchProcess:
                    alive = False
                if not alive:
                    break
                time.sleep(0.05)
            self.assertFalse(alive, "retained tree identity did not kill descendant")

    def test_offline_runtime_import_blocks_http(self):
        original_import = __import__
        observed = {"blocked": False}

        def controlled_import(name, *args, **kwargs):
            if name == "main":
                import requests

                try:
                    requests.get("https://example.invalid")
                except RuntimeError:
                    observed["blocked"] = True
                return types.ModuleType("main")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=controlled_import):
            ok, _ = readiness_probe.probe_runtime_import()
        self.assertTrue(ok)
        self.assertTrue(observed["blocked"])

    def test_offline_runtime_import_blocks_socket_dns_and_client_styles(self):
        original_import = __import__
        observed = set()

        def controlled_import(name, *args, **kwargs):
            if name == "main":
                import socket

                def socket_attempt(method):
                    sock = socket.socket()
                    try:
                        return getattr(sock, method)(("127.0.0.1", 9))
                    finally:
                        sock.close()

                attempts = {
                    "raw": lambda: socket_attempt("connect"),
                    "dns": lambda: socket.getaddrinfo("example.invalid", 443),
                    "httpx_style": lambda: socket.create_connection(("127.0.0.1", 9)),
                    "aiohttp_style": lambda: socket_attempt("connect_ex"),
                }
                for label, attempt in attempts.items():
                    try:
                        attempt()
                    except RuntimeError:
                        observed.add(label)
                return types.ModuleType("main")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=controlled_import):
            ok, _ = readiness_probe.probe_runtime_import()
        self.assertTrue(ok)
        self.assertEqual(observed, {"raw", "dns", "httpx_style", "aiohttp_style"})


class LiveHandshakeTests(unittest.TestCase):
    def test_current_live_transport_maps_only_legacy_audio_media(self):
        audio = {"data": b"pcm", "mime_type": "audio/pcm;rate=16000"}
        image = {"data": b"png", "mime_type": "image/png"}
        self.assertEqual(_live_input_kwargs(media=audio), {"audio": audio})
        self.assertEqual(_live_input_kwargs(media=image), {"media": image})
        self.assertEqual(_live_input_kwargs(text="hello"), {"text": "hello"})

    def test_live_audio_compat_is_session_local_and_preserves_images(self):
        class Session:
            async def send_realtime_input(self, **kwargs):
                self.sent = kwargs

        original = Session.send_realtime_input
        session = Session()
        adapted = install_live_audio_transport_compat(session)
        self.assertIs(adapt_live_audio_transport(adapted), adapted)
        self.assertIs(Session.send_realtime_input, original)
        audio = {"data": b"pcm", "mime_type": "audio/pcm"}
        asyncio.run(adapted.send_realtime_input(media=audio))
        self.assertEqual(session.sent, {"audio": audio})
        image = {"data": b"png", "mime_type": "image/png"}
        asyncio.run(adapted.send_realtime_input(media=image))
        self.assertEqual(session.sent, {"media": image})
        restored = unwrap_live_audio_transport(adapted)
        self.assertIs(restored, session)
        self.assertIs(unwrap_live_audio_transport(restored), session)
        self.assertIs(Session.send_realtime_input, original)

    def test_model_resolution_never_mutates_google_sdk_transport(self):
        from google.genai.live import AsyncSession

        original = AsyncSession.send_realtime_input
        self.assertEqual(resolve_live_model(config={}, environ={}), DEFAULT_LIVE_MODEL)
        self.assertIs(AsyncSession.send_realtime_input, original)

    def test_original_voice_model_is_pinned_and_runtime_probe_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "api_keys.json"
            path.write_text(
                json.dumps({"live_model": "models/config-live"}),
                encoding="utf-8",
            )
            with (
                patch.dict(
                    "os.environ", {"ONYX_READINESS_CONFIG": str(path)}, clear=True
                ),
                patch.object(
                    readiness_probe, "get_gemini_credential", return_value="key"
                ),
            ):
                with self.assertRaisesRegex(
                    VoiceContractError, "original voice requires"
                ):
                    resolve_live_model(path)
                with self.assertRaisesRegex(
                    VoiceContractError, "original voice requires"
                ):
                    readiness_probe._read_live_config()
            with (
                patch.dict(
                    "os.environ",
                    {
                        "ONYX_READINESS_CONFIG": str(path),
                        "ONYX_LIVE_MODEL": "models/environment-live",
                    },
                    clear=True,
                ),
                patch.object(
                    readiness_probe, "get_gemini_credential", return_value="key"
                ),
            ):
                with self.assertRaisesRegex(
                    VoiceContractError, "original voice requires"
                ):
                    resolve_live_model(path)
                with self.assertRaisesRegex(
                    VoiceContractError, "original voice requires"
                ):
                    readiness_probe._read_live_config()
        self.assertEqual(resolve_live_model(config={}, environ={}), DEFAULT_LIVE_MODEL)
        self.assertEqual(
            DEFAULT_LIVE_MODEL,
            "models/gemini-2.5-flash-native-audio-preview-12-2025",
        )

    def test_both_runtime_call_sites_use_only_shared_model_resolver(self):
        root = Path(__file__).resolve().parents[1]
        for relative in ("main.py", "actions/screen_processor.py"):
            source = (root / relative).read_text(encoding="utf-8")
            self.assertIn("resolve_live_model(", source)
            self.assertNotIn("gemini-3.1-flash-live-preview", source)

    def test_actual_live_transport_sends_turn_receives_and_closes(self):
        calls = {}

        class Session:
            async def send_client_content(self, **kwargs):
                calls["send"] = kwargs

            async def receive(self):
                yield types.SimpleNamespace(
                    data=b"audio", server_content=types.SimpleNamespace()
                )
                yield types.SimpleNamespace(
                    data=None,
                    server_content=types.SimpleNamespace(turn_complete=True),
                )

        class Connection:
            async def __aenter__(self):
                calls["entered"] = True
                return Session()

            async def __aexit__(self, *_args):
                calls["exited"] = True

        class Live:
            def connect(self, **kwargs):
                calls["connect"] = kwargs
                return Connection()

        class Client:
            def __init__(self, **kwargs):
                calls["client"] = kwargs
                self.aio = types.SimpleNamespace(live=Live())

            def close(self):
                calls["closed"] = True

        ok = asyncio.run(
            readiness_probe._live_handshake(
                "test-key", "models/test-live", client_factory=Client
            )
        )
        self.assertTrue(ok)
        self.assertEqual(calls["connect"]["model"], "models/test-live")
        self.assertEqual(calls["connect"]["config"].response_modalities, ["AUDIO"])
        self.assertEqual(
            calls["connect"][
                "config"
            ].speech_config.voice_config.prebuilt_voice_config.voice_name,
            "Charon",
        )
        self.assertTrue(calls["entered"] and calls["exited"] and calls["closed"])
        self.assertTrue(calls["send"]["turn_complete"])
        self.assertEqual(calls["send"]["turns"]["role"], "user")

    def test_live_turn_fails_when_response_stream_ends_empty(self):
        class Session:
            async def send_client_content(self, **_kwargs):
                pass

            async def receive(self):
                if False:
                    yield None

        class Connection:
            async def __aenter__(self):
                return Session()

            async def __aexit__(self, *_args):
                pass

        class Client:
            def __init__(self, **_kwargs):
                self.aio = types.SimpleNamespace(
                    live=types.SimpleNamespace(connect=lambda **_kwargs: Connection())
                )

            def close(self):
                pass

        self.assertFalse(
            asyncio.run(
                readiness_probe._live_handshake(
                    "test-key", "models/test-live", client_factory=Client
                )
            )
        )

    def _run_handshake_frames(self, frames):
        class Session:
            async def send_client_content(self, **_kwargs):
                pass

            async def receive(self):
                for frame in frames:
                    yield frame

        class Connection:
            async def __aenter__(self):
                return Session()

            async def __aexit__(self, *_args):
                pass

        class Client:
            def __init__(self, **_kwargs):
                self.aio = types.SimpleNamespace(
                    live=types.SimpleNamespace(connect=lambda **_kwargs: Connection())
                )

            def close(self):
                pass

        return asyncio.run(
            readiness_probe._live_handshake(
                "test-key", "models/test-live", client_factory=Client
            )
        )

    def test_live_turn_requires_audio_before_or_with_explicit_completion(self):
        intermediate = types.SimpleNamespace(
            data=None,
            server_content=types.SimpleNamespace(
                input_transcription=types.SimpleNamespace(text="ready")
            ),
        )
        audio = types.SimpleNamespace(data=b"audio", server_content=None)
        complete = types.SimpleNamespace(
            data=None, server_content=types.SimpleNamespace(turn_complete=True)
        )
        self.assertTrue(self._run_handshake_frames([intermediate, audio, complete]))
        same_frame = types.SimpleNamespace(
            data=b"audio", server_content=types.SimpleNamespace(turn_complete=True)
        )
        self.assertTrue(self._run_handshake_frames([same_frame]))
        self.assertFalse(self._run_handshake_frames([complete, intermediate, audio]))

    def test_live_turn_rejects_partial_empty_and_safety_only_streams(self):
        complete = types.SimpleNamespace(
            data=None, server_content=types.SimpleNamespace(turn_complete=True)
        )
        audio = types.SimpleNamespace(data=b"audio", server_content=None)
        empty_part = types.SimpleNamespace(
            data=None,
            server_content=types.SimpleNamespace(
                model_turn=types.SimpleNamespace(
                    parts=[
                        types.SimpleNamespace(
                            inline_data=types.SimpleNamespace(
                                data=b"", mime_type="audio/pcm"
                            )
                        )
                    ]
                )
            ),
        )
        safety = types.SimpleNamespace(
            data=None,
            server_content=types.SimpleNamespace(
                model_turn=None, turn_complete=True, generation_complete=True
            ),
            prompt_feedback=types.SimpleNamespace(block_reason="SAFETY"),
        )
        transcription = types.SimpleNamespace(
            data=None,
            server_content=types.SimpleNamespace(
                output_transcription=types.SimpleNamespace(text="ready"),
                turn_complete=True,
            ),
        )
        for frames in (
            [complete],
            [audio],
            [empty_part, complete],
            [safety],
            [transcription],
        ):
            with self.subTest(frames=frames):
                self.assertFalse(self._run_handshake_frames(frames))

    def test_selected_live_and_hardware_probes_are_required(self):
        failed = {"ok": False, "summary": "failed", "kind": "ValueError"}
        with patch.object(readiness, "_run_isolated_probe", return_value=failed):
            live = readiness.check_live_api(True, 1)
            audio = readiness.check_audio_devices(1, selected=True)
            mic = readiness.check_microphone(True, 1)
            camera = readiness.check_camera(True, 1)
        for result in (live, audio, mic, camera):
            self.assertEqual(result.status, "FAIL")
            self.assertTrue(result.required)
            self.assertTrue(result.selected)


class CompatibilityTests(unittest.TestCase):
    def test_python_support_is_exactly_311_through_313(self):
        for version, expected in (
            ((3, 10), "FAIL"),
            ((3, 11), "PASS"),
            ((3, 13), "PASS"),
            ((3, 14), "FAIL"),
        ):
            with (
                self.subTest(version=version),
                patch.object(readiness.sys, "version_info", version),
            ):
                self.assertEqual(readiness.check_python().status, expected)

    def test_windows_macos_and_linux_platforms_pass(self):
        for name in ("Windows", "Darwin", "Linux"):
            with (
                self.subTest(name=name),
                patch.object(readiness.platform, "system", return_value=name),
            ):
                self.assertEqual(readiness.check_platform().status, "PASS")

    def test_linux_optional_inventory_has_wmctrl_and_xrandr(self):
        with (
            patch.object(readiness.platform, "system", return_value="Linux"),
            patch.object(readiness.shutil, "which", return_value=None),
        ):
            result = readiness.check_optional_tools()
        self.assertIn("wmctrl", result.summary)
        self.assertIn("xrandr", result.summary)


class DashboardReadinessTests(unittest.TestCase):
    def test_real_dashboard_is_ephemeral_and_exercises_routes_and_auth(self):
        ok, summary = readiness_probe.probe_dashboard()
        self.assertTrue(ok, summary)
        self.assertIn("Loopback HTTPS dashboard", summary)

    def test_dashboard_probe_fails_when_required_static_asset_is_missing(self):
        from dashboard.server import DashboardServer

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            static = root / "static"
            static.mkdir()
            (static / "login.html").write_text("login", encoding="utf-8")
            with self.assertRaises(FileNotFoundError):
                DashboardServer(
                    local_ip="127.0.0.1",
                    cert_dir=root / "certs",
                    uploads_dir=root / "uploads",
                    static_dir=static,
                )

    def test_dashboard_tls_validator_requires_exact_host_identity(self):
        from dashboard.security import ensure_local_certificate

        with tempfile.TemporaryDirectory() as tmp:
            cert_dir = Path(tmp) / "certs"
            _key, wrong_cert = ensure_local_certificate(cert_dir, ["127.0.0.2"])
            with self.assertRaisesRegex(ValueError, "identify"):
                readiness_probe._validate_dashboard_certificate(wrong_cert, "127.0.0.1")
            self.assertEqual(
                readiness_probe._validate_dashboard_certificate(
                    wrong_cert, "127.0.0.2"
                ),
                str(wrong_cert),
            )


class ReadinessCliTests(unittest.TestCase):
    def test_main_emits_json_and_returns_selected_failure(self):
        results = [
            readiness.Result("runtime", "PASS", "ok", required=True),
            readiness.Result("live", "FAIL", "bad", required=True, selected=True),
        ]
        output = io.StringIO()
        with (
            patch.object(readiness, "run_checks", return_value=results),
            redirect_stdout(output),
        ):
            code = readiness.main(["--json"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())["ready"])

    def test_main_forwards_explicit_opt_in_flags(self):
        results = [readiness.Result("python", "PASS", "ok", required=True)]
        with (
            patch.object(readiness, "run_checks", return_value=results) as run,
            redirect_stdout(io.StringIO()),
        ):
            code = readiness.main(
                ["--live-api", "--hardware", "--camera", "--timeout", "3", "--json"]
            )
        self.assertEqual(code, 0)
        run.assert_called_once_with(
            live_api=True,
            hardware=True,
            camera=True,
            integrated_voice=False,
            voice_transport=False,
            timeout=3.0,
        )

    def test_main_forwards_integrated_voice_only(self):
        results = [readiness.Result("python", "PASS", "ok", required=True)]
        with (
            patch.object(readiness, "run_checks", return_value=results) as run,
            redirect_stdout(io.StringIO()),
        ):
            readiness.main(["--integrated-voice", "--json"])
        run.assert_called_once_with(
            live_api=False,
            hardware=False,
            camera=False,
            integrated_voice=True,
            voice_transport=False,
            timeout=30.0,
        )

    def test_integrated_instruction_is_stderr_and_json_stdout_remains_pure(self):
        results = [readiness.Result("runtime", "PASS", "ok", required=True)]
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(readiness, "run_checks", return_value=results),
            patch.object(readiness, "check_integrated_voice") as check,
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            check.side_effect = lambda enabled, timeout: (
                print(
                    "Speak exactly: Onyx readiness check (after the tone).",
                    file=sys.stderr,
                )
                or readiness.Result("integrated_voice", "SKIP", "test")
            )
            readiness.check_integrated_voice(True, 30)
            readiness.main(["--integrated-voice", "--json"])
        json.loads(out.getvalue())
        self.assertEqual(
            err.getvalue().strip(),
            "Speak exactly: Onyx readiness check (after the tone).",
        )

    def test_default_timeout_is_realistic_for_cold_windows_startup(self):
        results = [readiness.Result("python", "PASS", "ok", required=True)]
        with (
            patch.object(readiness, "run_checks", return_value=results) as run,
            redirect_stdout(io.StringIO()),
        ):
            readiness.main(["--json"])
        run.assert_called_once_with(
            live_api=False,
            hardware=False,
            camera=False,
            integrated_voice=False,
            voice_transport=False,
            timeout=30.0,
        )

    def test_nonfinite_and_nonpositive_timeouts_are_rejected(self):
        for value in ("0", "-1", "nan", "inf", "-inf"):
            with self.subTest(value=value), redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    readiness.main(["--timeout", value])
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
