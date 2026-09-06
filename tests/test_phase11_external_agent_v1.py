from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.external_agent_adapter_v1 import (
    DeterministicExternalAgentProviderV1,
    ExternalCodingAgentAdapterV1,
)
from core.missions import MissionStore, worker_once
from core.permission_broker import set_permission_callback
from core.phase11_live_mission_v1 import (
    EXTERNAL_AGENT_MISSION_TYPE,
    Phase11LiveMissionError,
    Phase11LiveMissionV1,
)


KEY = b"phase11-external-agent-test-key"


class MemoryVault:
    def __init__(self) -> None:
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)


class AnchorVaults:
    def __init__(self) -> None:
        self.values: dict[str, MemoryVault] = {}

    def __call__(self, reference: object) -> MemoryVault:
        account = str(getattr(reference, "account"))
        return self.values.setdefault(account, MemoryVault())


def _git(root: Path, *argv: str) -> bytes:
    git = shutil.which("git")
    assert git
    result = subprocess.run(
        [git, "-C", str(root), *argv],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@cyryxlabs.invalid")
    _git(root, "config", "user.name", "Onyx Test")
    (root / "src").mkdir()
    (root / "src" / "base.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "baseline")
    return root


@pytest.fixture
def live(tmp_path: Path):
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    provider = DeterministicExternalAgentProviderV1(
        mutation=("src/generated.txt", "generated\n")
    )

    def factory(**binding: object) -> ExternalCodingAgentAdapterV1:
        return ExternalCodingAgentAdapterV1(
            provider=provider,
            git_cli=shutil.which("git") or "",
            model="sonnet",
            max_budget_usd=1.0,
            max_seconds=120,
            max_output_bytes=64 * 1024,
            enabled=True,
            **binding,
        )

    anchors = AnchorVaults()
    bridge = Phase11LiveMissionV1(
        store,
        binding_dir=tmp_path / "authority",
        allowed_roots=(root,),
        enabled=True,
        key=KEY,
        anchor_vault_factory=anchors,
        external_agent_enabled=True,
        external_agent_factory=factory,
    )
    set_permission_callback(lambda request: request["digest"])
    try:
        yield root, store, provider, bridge, factory, anchors
    finally:
        set_permission_callback(None)
        bridge.close()


def _create(bridge: Phase11LiveMissionV1, root: Path, **changes: object):
    values: dict[str, object] = {
        "title": "External patch",
        "workspace_root": str(root),
        "workspace_id": "cyryx",
        "objective": "Create src/generated.txt with a short marker.",
        "allowed_roots": ["src"],
    }
    values.update(changes)
    return bridge.create_external_agent(**values)


def test_external_agent_discovery_is_lazy_and_reused(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    store = MissionStore(tmp_path / "missions.sqlite3")
    provider = DeterministicExternalAgentProviderV1(
        mutation=("src/generated.txt", "generated\n")
    )
    calls: list[dict[str, object]] = []

    def factory(**binding: object) -> ExternalCodingAgentAdapterV1:
        calls.append(dict(binding))
        return ExternalCodingAgentAdapterV1(
            provider=provider,
            git_cli=shutil.which("git") or "",
            model="sonnet",
            max_budget_usd=1.0,
            max_seconds=120,
            max_output_bytes=64 * 1024,
            enabled=True,
            **binding,
        )

    bridge = Phase11LiveMissionV1(
        store,
        binding_dir=tmp_path / "authority",
        allowed_roots=(root,),
        enabled=True,
        key=KEY,
        anchor_vault_factory=AnchorVaults(),
        external_agent_enabled=True,
        external_agent_factory=factory,
    )
    try:
        assert calls == []
        assert bridge.external_agent is None
        _create(bridge, root)
        assert len(calls) == 1
        assert bridge.external_agent is not None
        bridge.cleanup_external_agent_quarantine(retain=0)
        assert len(calls) == 1
    finally:
        bridge.close()


def test_external_agent_mission_is_bound_approved_and_clone_only(live) -> None:
    root, store, provider, bridge, _factory, _anchors = live
    mission = _create(bridge, root)
    binding = json.loads(
        (bridge.binding_dir / f"{mission.id}.binding.json").read_text()
    )
    serialized = json.dumps(binding)
    assert binding["mission_type"] == EXTERNAL_AGENT_MISSION_TYPE
    assert "Create src/generated.txt" not in serialized
    assert binding["fixed_steps"][0]["args"]["external_pr_creation"] is False
    assert binding["fixed_steps"][0]["args"]["provider_budget_usd"] == 1.0
    bridge.approve(mission.id)
    completed = worker_once(store, "external-agent-test", bridge.runner)
    assert completed is not None and completed.state == "succeeded"
    assert not (root / "src" / "generated.txt").exists()
    assert len(provider.calls) == 1
    status = bridge.status(mission.id)
    assert status["external_agent"]["attempt_state"] == "succeeded"
    assert status["external_agent"]["draft_pr_creation_authorized"] is False


def test_external_agent_restart_authenticates_receipt_without_redispatch(
    live,
) -> None:
    root, store, provider, bridge, factory, anchors = live
    mission = _create(bridge, root)
    bridge.approve(mission.id)
    assert worker_once(store, "external-agent-test", bridge.runner).state == "succeeded"
    bridge.close()
    restarted = Phase11LiveMissionV1(
        MissionStore(store.path),
        binding_dir=bridge.binding_dir,
        allowed_roots=(root,),
        enabled=True,
        key=KEY,
        anchor_vault_factory=anchors,
        external_agent_enabled=True,
        external_agent_factory=factory,
    )
    try:
        assert restarted.status(mission.id)["state"] == "succeeded"
        assert (
            restarted.status(mission.id)["external_agent"]["dispatch_permitted"]
            is False
        )
        assert len(provider.calls) == 1
    finally:
        restarted.close()


def test_external_agent_follow_up_is_a_new_approved_mission(live) -> None:
    root, store, provider, bridge, _factory, _anchors = live
    first = _create(bridge, root)
    bridge.approve(first.id)
    assert worker_once(store, "external-agent-test", bridge.runner).state == "succeeded"
    second = _create(
        bridge,
        root,
        title="External follow-up",
        objective="Revise the same generated file.",
        prior_mission_id=first.id,
    )
    assert second.state == "awaiting_approval"
    binding = json.loads(
        (bridge.binding_dir / f"{second.id}.binding.json").read_text()
    )
    assert (
        binding["external_agent"]["prior_artifact_sha256"]
        == bridge.external_agent.artifact_sha256(first.id)
    )
    assert len(provider.calls) == 1


def test_external_agent_rejects_dirty_owner_and_host_budget_override(live) -> None:
    root, _store, _provider, bridge, _factory, _anchors = live
    with pytest.raises(ValueError, match="activation-owned"):
        _create(bridge, root, provider_cost_limit=2.0)
    (root / "src" / "base.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(Phase11LiveMissionError, match="clean immutable"):
        _create(bridge, root)
