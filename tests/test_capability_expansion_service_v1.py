from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

import main
from core import permission_broker
from core.camera_gesture_attention_v1 import CameraGestureAttention
from core.capability_expansion_runtime_v1 import CapabilityExpansionDenied
from core.capability_expansion_service_v1 import CapabilityExpansionServiceV1
from core.capability_expansion_service_v1 import with_installed_local_capabilities_v1
from core.tool_audit import AuditReference
from core.vision_repetition_counter_v1 import VisionRepetitionContractError


@pytest.fixture(autouse=True)
def healthy_audit():
    permission_broker._audit_healthy = True
    yield
    permission_broker._audit_healthy = True


def _service(tmp_path: Path, **flags: object) -> CapabilityExpansionServiceV1:
    return CapabilityExpansionServiceV1(
        tmp_path,
        owner_profile_id="owner",
        workspace_id="workspace",
        config=flags,
        environ={},
    )


def _authorize():
    return patch(
        "core.capability_expansion_runtime_v1.permission_broker.authorize_capability_operation",
        return_value=(True, "owner-approved"),
    )


def _audit():
    return patch(
        "core.capability_expansion_runtime_v1.append_tool_audit_reference",
        return_value=AuditReference("trace", "event-hash"),
    )


def test_default_off_and_social_local_tools_available_without_publish_adapter(tmp_path: Path):
    service = _service(tmp_path, ONYX_SOCIAL_PUBLISH_V1=True)
    status = service.redacted_status()
    assert all(item["enabled"] is False for name, item in status.items() if name != "social")
    assert status["social"]["enabled"] is True
    assert status["social"]["available"] is True
    assert status["social"]["status"] == "approved"
    assert service.social is None
    assert all(str(store.path).startswith(str(tmp_path)) for store in (service.clipboard, service.wellness))
    assert str(service.plugin.registry_path).startswith(str(tmp_path))


def test_installed_local_profile_is_operational_and_preserves_explicit_opt_out(
    tmp_path: Path,
):
    config = with_installed_local_capabilities_v1(
        {"ONYX_PLUGIN_RUNTIME_V1": False}
    )
    service = _service(tmp_path, **config)
    status = service.redacted_status()
    assert status["wellness"]["status"] == "approved"
    assert status["clipboard"]["status"] == "approved"
    assert status["plugin"]["status"] == "disabled"
    assert status["social"]["status"] == "approved"


def test_service_normalizes_absolute_string_social_video_roots(tmp_path: Path):
    configured_root = tmp_path / "owner-workspace"
    configured_root.mkdir()

    service = CapabilityExpansionServiceV1(
        tmp_path / "memory",
        owner_profile_id="owner",
        workspace_id="workspace",
        config={"ONYX_SOCIAL_PUBLISH_V1": True},
        environ={},
        social_video_roots=(str(configured_root),),
    )

    assert service.social_video.controlled_roots == (configured_root.resolve(),)


def test_social_caption_is_model_callable_but_live_publish_remains_truthful(
    tmp_path: Path,
):
    service = _service(tmp_path, ONYX_SOCIAL_PUBLISH_V1=True)
    with _authorize(), _audit():
        generated = service.dispatch_model(
            {
                "capability": "social",
                "operation": "generate",
                "brief": "Explain governed AI operations",
                "brand": "Cyryx Labs",
                "platform": "linkedin",
                "source_refs": ["owner-brief"],
            }
        )
        status = service.dispatch_model(
            {"capability": "social", "operation": "status"}
        )
    assert "Cyryx Labs" in generated["result"]["caption"]
    assert status["result"]["caption_generation"] == "available"
    assert status["result"]["publishing"] == "oauth-adapter-required"


def test_model_can_list_and_execute_an_already_governed_plugin(tmp_path: Path):
    service = _service(tmp_path, ONYX_PLUGIN_RUNTIME_V1=True)
    service.plugin.list = Mock(return_value=[{"plugin_id": "cyryx.test"}])
    service.plugin.execute = Mock(return_value={"result": "ok"})
    with _authorize(), _audit():
        listed = service.dispatch_model(
            {"capability": "plugin", "operation": "list"}
        )
        executed = service.dispatch_model(
            {
                "capability": "plugin",
                "operation": "execute",
                "plugin_id": "cyryx.test",
                "plugin_operation": "echo",
                "payload": {"message": "hello"},
            }
        )
    assert listed["result"] == [{"plugin_id": "cyryx.test"}]
    assert executed["result"] == {"result": "ok"}
    service.plugin.execute.assert_called_once_with(
        "cyryx.test", "echo", {"message": "hello"}
    )


def test_model_repetition_counter_consumes_normalized_camera_attention(
    tmp_path: Path,
):
    service = _service(tmp_path, ONYX_WELLNESS_TRACKER_V1=True)
    with _authorize(), _audit():
        started = service.dispatch_model(
            {
                "capability": "wellness",
                "operation": "repetition_start",
                "activity": "squat",
            }
        )
    assert started["result"]["status"] == "calibrating"
    assert service.repetition_active is True
    for index, y in enumerate((-0.8, -0.4, 0.1, 0.6, 0.8, 0.2, -0.6, -0.8)):
        service.observe_camera_repetition_from_host(
            _attention(y), observed_at=index * 0.25
        )
    with _authorize(), _audit():
        status = service.dispatch_model(
            {"capability": "wellness", "operation": "repetition_status"}
        )
        stopped = service.dispatch_model(
            {
                "capability": "wellness",
                "operation": "repetition_stop",
                "occurred_at": "2026-09-04T12:00:00-04:00",
                "timezone_name": "America/New_York",
                "idempotency_key": "squat-live-1",
            }
        )
    assert status["result"]["activity"] == "squat"
    assert stopped["result"]["estimate"]["status"] == "draft"
    assert service.repetition_active is False


def test_model_dispatch_goes_runtime_broker_then_wellness_module(tmp_path: Path):
    service = _service(tmp_path, ONYX_WELLNESS_TRACKER_V1=True)
    call = {
        "capability": "wellness",
        "operation": "create",
        "kind": "calorie",
        "calories": 500,
        "occurred_at": "2026-08-23T12:00:00-04:00",
        "timezone_name": "America/New_York",
        "idempotency_key": "meal-1",
    }
    with _authorize() as broker, _audit():
        response = service.dispatch_model(call, trace_id="model-trace")
    broker.assert_called_once()
    assert response["result"]["kind"] == "calorie"
    assert service.wellness.list_entries("owner", "workspace")[0].value == 500


def test_disabled_audit_unhealthy_and_kill_all_deny_before_module(tmp_path: Path):
    disabled = _service(tmp_path / "disabled")
    with pytest.raises(CapabilityExpansionDenied, match="disabled"):
        disabled.dispatch_model({"capability": "plugin", "operation": "status"})

    service = _service(tmp_path / "enabled", ONYX_PLUGIN_RUNTIME_V1=True)
    with patch.object(service.plugin, "status") as module:
        permission_broker.mark_audit_unhealthy()
        with pytest.raises(CapabilityExpansionDenied, match="audit"):
            service.dispatch_model({"capability": "plugin", "operation": "status"})
        module.assert_not_called()
    permission_broker._audit_healthy = True
    service.kill()
    with pytest.raises(CapabilityExpansionDenied, match="kill"):
        service.dispatch_model({"capability": "plugin", "operation": "status"})


def test_revoke_denies_and_redacted_status_contains_no_paths_or_secrets(tmp_path: Path):
    service = _service(tmp_path, ONYX_PLUGIN_RUNTIME_V1=True)
    service.revoke("plugin")
    status = service.redacted_status("plugin")
    encoded = repr(status)
    assert status["plugin"]["revoked"] is True
    assert str(tmp_path) not in encoded
    assert "token" not in encoded.casefold()
    with pytest.raises(CapabilityExpansionDenied, match="revoked"):
        service.dispatch_model({"capability": "plugin", "operation": "status"})


def test_clipboard_voice_rejects_raw_content_and_host_gesture_reads_once(tmp_path: Path):
    service = _service(tmp_path, ONYX_CLIPBOARD_INTELLIGENCE_V1=True)
    with pytest.raises(PermissionError, match="raw clipboard"):
        service.dispatch_model(
            {"capability": "clipboard", "operation": "status", "text": "private"}
        )
    reader = Mock(return_value="safe clipboard text")
    with _authorize(), _audit():
        service.dispatch_model({"capability": "clipboard", "operation": "opt_in"})
        preview = service.clipboard_preview_from_host_gesture(
            reader, gesture_confirmed=True
        )
    reader.assert_called_once_with()
    assert preview["result"]["text"] == "safe clipboard text"


def test_main_dispatcher_reaches_composed_service(tmp_path: Path):
    service = _service(tmp_path, ONYX_PLUGIN_RUNTIME_V1=True)
    host = main.OnyxLive.__new__(main.OnyxLive)
    host.ui = SimpleNamespace(
        muted=True,
        set_state=Mock(),
        write_log=Mock(),
    )
    host._capability_expansion_v1 = service
    host._governance_nucleus_v1 = None
    host._shutdown_requested = __import__("threading").Event()
    host._shutdown_sequence_started = __import__("threading").Event()
    host._shutdown_input_quiesced = __import__("threading").Event()
    host._installer_shutdown_active = __import__("threading").Event()
    host._run_external_action = lambda action, *args, **kwargs: asyncio.to_thread(
        action, *args, **kwargs
    )
    call = SimpleNamespace(
        id="call-1",
        name="capability_expansion",
        args={"capability": "plugin", "operation": "status"},
    )
    with _authorize() as broker, _audit(), patch.object(main, "append_tool_audit"):
        response = asyncio.run(host._execute_tool_unbarriered(call))
    broker.assert_called_once()
    assert response.response["result"]["result"]["plugins"] == []


def _attention(y: float, confidence: float = 0.9) -> CameraGestureAttention:
    return CameraGestureAttention(
        x=0.0,
        y=y,
        confidence=confidence,
        foreground_ratio=0.04,
    )


def test_camera_attention_materializes_only_a_confirmable_repetition_draft(
    tmp_path: Path,
):
    service = _service(tmp_path, ONYX_WELLNESS_TRACKER_V1=True)
    with _authorize(), _audit():
        started = service.start_camera_repetition_from_host(
            "squat", owner_confirmed=True, trace_id="start"
        )
    assert started["result"]["status"] == "calibrating"

    samples = [-0.8, -0.6, -0.2, 0.2, 0.6, 0.8, 0.4, -0.4]
    samples += [0.8, -0.8, 0.8]
    for index, y in enumerate(samples):
        observed = service.observe_camera_repetition_from_host(
            _attention(y), observed_at=index * 0.2
        )
        assert observed["frame_retained"] is False
        assert observed["identity_processed"] is False

    with _authorize(), _audit():
        stopped = service.stop_camera_repetition_from_host(
            occurred_at="2026-09-01T12:00:00-04:00",
            timezone_name="America/New_York",
            idempotency_key="camera-squat-session-1",
            trace_id="stop",
        )
    draft = stopped["result"]["draft"]
    assert stopped["result"]["confirmation_required"] is True
    assert draft["status"] == "draft"
    assert draft["source"] == "vision_estimate"
    assert draft["unit"] == "repetitions"
    assert service.wellness.totals(
        "owner", "workspace", day="2026-09-01", timezone_name="America/New_York"
    )["exercise"] == {}


def test_camera_repetition_requires_owner_and_rejects_frames(tmp_path: Path):
    service = _service(tmp_path, ONYX_WELLNESS_TRACKER_V1=True)
    with pytest.raises(PermissionError, match="owner confirmation"):
        service.start_camera_repetition_from_host("squat", owner_confirmed=False)
    with _authorize(), _audit():
        service.start_camera_repetition_from_host("squat", owner_confirmed=True)
    with pytest.raises(VisionRepetitionContractError, match="normalized"):
        service.observe_camera_repetition_from_host(
            object(),  # type: ignore[arg-type]
            observed_at=1.0,
        )


def test_kill_prevents_camera_sample_before_counter_update(tmp_path: Path):
    service = _service(tmp_path, ONYX_WELLNESS_TRACKER_V1=True)
    with _authorize(), _audit():
        service.start_camera_repetition_from_host("squat", owner_confirmed=True)
    before = service._repetition.snapshot()
    service.kill()
    with pytest.raises(CapabilityExpansionDenied, match="kill"):
        service.observe_camera_repetition_from_host(_attention(0.8), observed_at=1.0)
    assert service._repetition.snapshot() == before
