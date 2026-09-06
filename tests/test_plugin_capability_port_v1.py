from pathlib import Path
from unittest.mock import patch

import pytest

from core.capability_ports.plugin_v1 import PluginCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceV1Denied
from core.plugin_runtime_v1 import PluginHostV1


def _port(tmp_path: Path) -> PluginCapabilityPortV1:
    return PluginCapabilityPortV1(PluginHostV1(tmp_path / "plugins.json", workspace_id="workspace-a"))


def test_plugin_lifecycle_is_separate_from_exact_echo_execution(tmp_path: Path) -> None:
    port = _port(tmp_path)
    assert port._dispatch_authorized("lifecycle.list", {}) == []
    with patch.object(PluginHostV1, "execute", return_value={"ok": True, "result": "echo"}) as execute:
        assert port._dispatch_authorized("execute.test.echo", {"plugin_id": "test.echo", "payload": "echo"})["result"] == "echo"
    execute.assert_called_once_with("test.echo", "test.echo", "echo")
    with pytest.raises(GovernanceV1Denied, match="unknown"):
        port._dispatch_authorized("execute.network", {})


def test_plugin_revoke_disconnect_close_and_kill_remain_distinct(tmp_path: Path) -> None:
    port = _port(tmp_path)
    assert port.revoke("binding-a")["status"] == "binding-revoked"
    assert port.disconnect() == {"status": "disconnected", "closed": False, "killed": False}
    assert port.close() == {"status": "closed", "killed": False}
    assert port.kill() == {"status": "kill-latched"}
