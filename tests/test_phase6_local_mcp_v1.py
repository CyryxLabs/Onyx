from __future__ import annotations

from dataclasses import replace
import hashlib
import inspect
from pathlib import Path
import subprocess
import sys
import time

import pytest

from core import phase6_local_mcp_v1 as mcp


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "phase6_local_mcp_server.py"


def command(mode: str = "normal") -> mcp.LocalMCPServerCommandV1:
    return mcp.LocalMCPServerCommandV1(
        server_id="onyx-local-catalog",
        workspace_id="onyx-local-workspace",
        executable=Path(sys.executable),
        executable_sha256=hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        arguments=("-I", str(FIXTURE), mode),
        server_artifact=FIXTURE,
        server_sha256=hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        credential_env_name="ONYX_TEST_MCP_TOKEN",
    )


def identity(
    workspace: str = "onyx-local-workspace",
) -> mcp.LocalMCPIdentityV1:
    return mcp.LocalMCPIdentityV1(workspace, "onyx-owner")


def create(mode: str = "normal", timeout: float = 1.5) -> mcp.LocalReadOnlyMCPAdapterV1:
    value = mcp.create_local_read_only_mcp_v1(
        gate=mcp.LocalMCPFeatureGateV1(True),
        command=command(mode),
        identity=identity(),
        credential="fixture-secret",
        timeout_seconds=timeout,
    )
    assert type(value) is mcp.LocalReadOnlyMCPAdapterV1
    return value


def request(request_id: str = "request-one") -> mcp.LocalCatalogMCPRequestV1:
    return mcp.LocalCatalogMCPRequestV1(request_id, identity(), 17)


def test_gate_is_exact_and_off_short_circuits() -> None:
    for enabled in ("1", "TRUE", "True", " true ", "yes"):
        assert not mcp.LocalMCPFeatureGateV1.from_environ(
            {mcp.FEATURE_FLAG: enabled}
        ).enabled
    assert mcp.LocalMCPFeatureGateV1.from_environ({mcp.FEATURE_FLAG: "true"}).enabled
    assert (
        mcp.create_local_read_only_mcp_v1(gate=mcp.LocalMCPFeatureGateV1(False)) is None
    )


def test_pinned_artifact_and_workspace_are_attested_before_launch(
    tmp_path: Path,
) -> None:
    copied = tmp_path / "server.py"
    copied.write_bytes(FIXTURE.read_bytes())
    spec = replace(
        command(),
        server_artifact=copied,
        arguments=("-I", str(copied), "normal"),
    )
    copied.write_text("raise SystemExit(1)\n", encoding="utf-8")
    with pytest.raises(mcp.Phase6LocalMCPDenied, match="artifact drifted"):
        mcp.create_local_read_only_mcp_v1(
            gate=mcp.LocalMCPFeatureGateV1(True),
            command=spec,
            identity=identity(),
            credential="fixture-secret",
        )
    with pytest.raises(mcp.Phase6LocalMCPDenied, match="workspace diverged"):
        mcp.create_local_read_only_mcp_v1(
            gate=mcp.LocalMCPFeatureGateV1(True),
            command=command(),
            identity=identity("other-workspace"),
            credential="fixture-secret",
        )


def test_lifecycle_list_call_receipt_and_idempotent_replay() -> None:
    with create() as adapter:
        declaration = adapter.tool_declaration
        assert declaration["name"] == mcp.TOOL_NAME
        assert declaration["annotations"] == {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        }
        first, receipt = adapter.call_catalog(request())
        second, replayed = adapter.call_catalog(request())
        assert first == second
        assert receipt == replayed
        assert first["page_size"] == 17
        assert receipt.protocol_version == "2025-11-25"
        assert receipt.transport == "stdio"
        assert receipt.egress == receipt.mutation == "none"
        assert declaration["outputSchema"]["additionalProperties"] is False


def test_request_id_conflict_and_cross_identity_are_denied() -> None:
    with create() as adapter:
        adapter.call_catalog(request())
        with pytest.raises(mcp.Phase6LocalMCPDenied, match="different input"):
            adapter.call_catalog(
                mcp.LocalCatalogMCPRequestV1("request-one", identity(), 18)
            )
        with pytest.raises(mcp.Phase6LocalMCPDenied, match="identity diverged"):
            adapter.call_catalog(
                mcp.LocalCatalogMCPRequestV1(
                    "request-two",
                    mcp.LocalMCPIdentityV1("other-workspace", "onyx-owner"),
                    17,
                )
            )


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("wrong-version", "negotiation failed"),
        ("duplicate-tools", "absent or duplicated"),
    ],
)
def test_initialization_and_tool_discovery_fail_closed(mode: str, message: str) -> None:
    with pytest.raises(mcp.Phase6LocalMCPUnavailable, match=message):
        create(mode)


def test_server_instructions_and_extra_tools_never_expand_authority() -> None:
    for mode in ("instructions", "extra-tool"):
        with create(mode) as adapter:
            declaration = adapter.tool_declaration
            encoded = repr(declaration).lower()
            assert "ignore the host" not in encoded
            assert "delete_everything" not in encoded
            assert declaration["name"] == mcp.TOOL_NAME
            result, _ = adapter.call_catalog(request(f"request-{mode}"))
            assert result["items"][0]["mode"] == "read-only"


def test_paginated_discovery_selects_one_tool_and_rejects_cross_page_duplicate():
    with create("paginated") as adapter:
        result, _ = adapter.call_catalog(request("request-paginated"))
        assert result["items"][0]["capability_id"] == "local-catalog"
    for mode, message in (
        ("duplicate-paginated", "absent or duplicated"),
        ("cursor-cycle", "cursor is malformed"),
    ):
        with pytest.raises(mcp.Phase6LocalMCPUnavailable, match=message):
            create(mode)


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("malformed", "malformed JSON-RPC"),
        ("oversize", "exceeds the message limit"),
        ("server-request", "server-initiated MCP requests"),
        ("tool-error", "reported an error"),
    ],
)
def test_protocol_and_tool_failures_are_denied(mode: str, message: str) -> None:
    with create(mode) as adapter:
        with pytest.raises(mcp.Phase6LocalMCPUnavailable, match=message):
            adapter.call_catalog(request(f"request-{mode}"))


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("duplicate-id-key", "duplicate key"),
        ("bool-id", "response ID type"),
        ("unknown-notification", "unexpected MCP server notification"),
        ("structured-extra", "structured MCP result fields"),
    ],
)
def test_adversarial_jsonrpc_and_structured_result_attacks_fail_closed(
    mode: str, message: str
) -> None:
    with create(mode) as adapter:
        with pytest.raises(mcp.Phase6LocalMCPUnavailable, match=message):
            adapter.call_catalog(request(f"request-{mode}"))


def test_message_without_newline_times_out_and_process_is_closed() -> None:
    adapter = create("no-newline")
    adapter._timeout = 0.2
    with pytest.raises(mcp.Phase6LocalMCPUnavailable, match="timed out"):
        adapter.call_catalog(request("request-no-newline"))
    adapter.close()
    assert not adapter.server_running


def test_late_cancelled_response_is_ignored_before_next_correlation() -> None:
    with create("late-response") as adapter:
        adapter._timeout = 0.1
        with pytest.raises(mcp.Phase6LocalMCPUnavailable, match="timed out"):
            adapter.call_catalog(request("request-late-first"))
        time.sleep(0.4)
        result, _ = adapter.call_catalog(request("request-late-second"))
        assert result["items"][0]["mode"] == "read-only"


def test_duplicate_completed_response_poisoning_is_denied() -> None:
    with create("duplicate-response") as adapter:
        adapter.call_catalog(request("request-duplicate-first"))
        with pytest.raises(mcp.Phase6LocalMCPUnavailable, match="correlation diverged"):
            adapter.call_catalog(request("request-duplicate-second"))


def test_initialize_timeout_is_never_cancelled() -> None:
    with create() as adapter:
        notifications: list[tuple[str, object]] = []
        original = adapter._transport.notify
        adapter._transport.notify = (  # type: ignore[method-assign]
            lambda method, params=None: notifications.append((method, params))
        )
        try:
            adapter._transport._cancel_timeout("initialize", 99)
        finally:
            adapter._transport.notify = original  # type: ignore[method-assign]
        assert notifications == []


def test_argument_alias_is_never_sent() -> None:
    with create("arg-alias") as adapter:
        result, _ = adapter.call_catalog(request("request-arguments"))
        assert result["page_size"] == 17
    with pytest.raises(TypeError):
        mcp.LocalCatalogMCPRequestV1(  # type: ignore[call-arg]
            "request-alias",
            identity(),
            pageSize=17,
        )


def test_timeout_sends_cancellation_and_close_terminates_process() -> None:
    # Leave enough headroom for process startup on loaded Windows hosts while
    # keeping the hung call bounded.
    adapter = create("hang-call", timeout=0.5)
    assert adapter.server_running
    with pytest.raises(mcp.Phase6LocalMCPUnavailable, match="timed out"):
        adapter.call_catalog(request("request-timeout"))
    adapter.close()
    assert not adapter.server_running


def test_credentials_are_environment_only_and_never_receipted() -> None:
    adapter = create()
    try:
        result, receipt = adapter.call_catalog(request("request-secret"))
        material = repr((adapter, adapter.tool_declaration, result, receipt))
        assert "fixture-secret" not in material
        assert "ONYX_TEST_MCP_TOKEN" not in repr(receipt)
    finally:
        adapter.close()


def test_credential_reflection_and_parent_environment_leak_are_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with create("credential-leak") as adapter:
        with pytest.raises(
            mcp.Phase6LocalMCPUnavailable, match="credential reflection"
        ) as observed:
            adapter.call_catalog(request("request-credential-reflection"))
        assert "fixture-secret" not in str(observed.value)
    monkeypatch.setenv("ONYX_PARENT_SECRET", "must-not-cross")
    with create("parent-env-leak") as adapter:
        result, _ = adapter.call_catalog(request("request-parent-env"))
        assert result["items"][0]["provider"] == "local"


def test_executable_drift_is_denied_before_process_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / Path(sys.executable).name
    copied.write_bytes(Path(sys.executable).read_bytes())
    spec = replace(
        command(),
        executable=copied,
        executable_sha256=hashlib.sha256(copied.read_bytes()).hexdigest(),
    )
    copied.write_bytes(b"drift")
    monkeypatch.setattr(
        subprocess,
        "Popen",
        lambda *_args, **_kwargs: pytest.fail("drifted executable was launched"),
    )
    with pytest.raises(mcp.Phase6LocalMCPDenied, match="executable drifted"):
        mcp.create_local_read_only_mcp_v1(
            gate=mcp.LocalMCPFeatureGateV1(True),
            command=spec,
            identity=identity(),
            credential="fixture-secret",
        )


def test_failed_initialization_reaps_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[subprocess.Popen[bytes]] = []
    original = subprocess.Popen

    def capture(*args: object, **kwargs: object):
        process = original(*args, **kwargs)
        observed.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", capture)
    with pytest.raises(mcp.Phase6LocalMCPUnavailable, match="negotiation failed"):
        create("wrong-version")
    assert len(observed) == 1
    assert observed[0].poll() is not None


def test_no_network_or_live_wiring_and_factory_is_closed() -> None:
    source = inspect.getsource(mcp).lower()
    for forbidden in (
        "import socket",
        "import requests",
        "import httpx",
        "urllib.request",
        "main.py",
        "onyx_live_activation",
    ):
        assert forbidden not in source
    assert "shell=false" in source
    assert "notifications/initialized" in source
    assert "tools/list" in source
    assert "tools/call" in source
    with pytest.raises(mcp.Phase6LocalMCPDenied, match="requires the factory"):
        mcp.LocalReadOnlyMCPAdapterV1(
            _key=object(),
            command=command(),
            identity=identity(),
            transport=object(),  # type: ignore[arg-type]
            timeout_seconds=1.0,
        )
