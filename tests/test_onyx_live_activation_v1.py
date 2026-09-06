from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import sys
import threading
import types
from pathlib import Path

import pytest

from core import onyx_live_activation_v1 as live
from core import owner_profile_v8 as owner_v8
from core.phase5_integration_v3 import (
    LOCAL_CATALOG_TOOL,
    CatalogSeedV3,
    create_phase5_integration_v3,
)
from memory.store import MemoryRecord


ROOT = Path(__file__).resolve().parents[1]


class Memory:
    def __init__(self) -> None:
        self.records: list[MemoryRecord] = []

    def list(self, *, kind=None, limit=100):
        values = [item for item in self.records if kind is None or item.kind == kind]
        return values if limit is None else values[:limit]

    def remember(
        self,
        content,
        *,
        kind="semantic",
        source="user",
        citation=None,
        salience=0.6,
        category=None,
        key=None,
        metadata=None,
        **_unused,
    ):
        self.forget_key(category, key)
        record = MemoryRecord(
            "owner-record",
            kind,
            content,
            source,
            citation or "user:owner",
            "2026-07-22T00:00:00+00:00",
            "2026-07-22T00:00:00+00:00",
            salience,
            category=category,
            key=key,
            metadata=metadata,
        )
        self.records.insert(0, record)
        return record

    def forget_key(self, category, key):
        before = len(self.records)
        self.records = [
            item
            for item in self.records
            if (item.category, item.key) != (category, key)
        ]
        return before - len(self.records)


class Lease:
    def __init__(self, *, fail=False) -> None:
        self.fail = fail
        self.lock = threading.RLock()
        self.depth = 0

    @property
    def cross_session_guaranteed(self):
        return True

    @contextlib.contextmanager
    def hold(self, owner_profile_id, *, timeout_seconds):
        assert owner_profile_id == live.OWNER_PROFILE_ID
        assert 0.05 <= timeout_seconds <= 30.0
        if self.fail:
            raise owner_v8.HostLeaseError("test lease unavailable")
        with self.lock:
            self.depth += 1
            try:
                yield self
            finally:
                self.depth -= 1


class HeadStore:
    def __init__(self, lease: Lease) -> None:
        self.lease = lease
        self.value = None

    def load(self, owner_profile_id):
        assert owner_profile_id == live.OWNER_PROFILE_ID
        return self.value

    def compare_and_set(self, owner_profile_id, expected, desired):
        assert owner_profile_id == live.OWNER_PROFILE_ID
        assert self.lease.depth > 0
        if self.value != expected:
            return False
        self.value = desired
        return True


class Vault:
    def __init__(self, value=None, *, fail_read=False) -> None:
        self.value = value
        self.fail_read = fail_read
        self.reads = 0
        self.writes = 0

    def get_bytes(self):
        self.reads += 1
        if self.fail_read:
            raise RuntimeError("vault unavailable")
        return self.value

    def set_bytes(self, value):
        self.writes += 1
        self.value = bytes(value)


def active_environment():
    return live.exact_activation_environment()


def authority_factory(tmp_path, memory, head, lease, vault):
    config = tmp_path / "config" / "api_keys.json"
    journal = tmp_path / "private-runtime" / "identity" / "owner.json"

    def factory():
        return live.provision_owner_authority(
            journal_path=journal,
            vault=vault,
            memory=memory,
            config_path=config,
            chain_head_store=head,
            transaction_lease=lease,
        )

    return factory, config, journal


def test_default_off_and_rollback_are_exact_legacy_delegation_boundaries():
    off = live.ActivationFlagsV1.from_environ({})
    rollback = live.ActivationFlagsV1.from_environ(
        {live.LIVE_MASTER_FLAG: "1", live.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert not off.active and not rollback.active and rollback.rollback
    for ambiguous in ("yes", "on", "enabled", "2"):
        assert not live.ActivationFlagsV1.from_environ(
            {live.LIVE_MASTER_FLAG: ambiguous}
        ).active
    source = (ROOT / "scripts" / "launch_onyx_live_v1.pyw").read_text(
        encoding="utf-8"
    )
    rollback_branch = source.index("if _true(ROLLBACK):")
    legacy_branch = source.index("if not _true(MASTER):")
    coordinator_import = source.index("from core.onyx_live_activation_v1 import")
    assert rollback_branch < legacy_branch < coordinator_import
    assert "os.environ.pop(name, None)" in source[rollback_branch:legacy_branch]
    assert "child flag set without master" in source[legacy_branch:coordinator_import]
    assert "legacy_run()" in source[legacy_branch:coordinator_import]


def test_partial_activation_is_refused_and_complete_map_is_explicit():
    environment = active_environment()
    flags = live.ActivationFlagsV1.from_environ(environment)
    assert flags.active and flags.all_children
    assert set(live.REQUIRED_CHILD_FLAGS) <= set(environment)
    for missing in live.REQUIRED_CHILD_FLAGS:
        partial = dict(environment)
        partial.pop(missing)
        with pytest.raises(live.ActivationError, match="every accepted child"):
            live.ActivationFlagsV1.from_environ(partial)
    assert live.exact_rollback_environment() == {live.LIVE_ROLLBACK_FLAG: "1"}


def test_owner_first_contact_persist_restart_correct_forget_and_literal_sir(tmp_path):
    memory = Memory()
    lease = Lease()
    head = HeadStore(lease)
    vault = Vault()
    factory, config, journal = authority_factory(tmp_path, memory, head, lease, vault)
    first = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=factory,
    )
    assert first.start() is live.ActivationState.READY
    directive = first.owner_prompt_directive()
    assert owner_v8.FIRST_CONTACT_QUESTION in directive
    assert "literal English" in directive and "never be translated" in directive
    assert first.owner_name() == "" and first.owner_address() == "Sir"
    assert first.handle_owner_tool("set_owner_name", {"name": "José 李小龍"})[
        "address"
    ] == "José 李小龍"
    assert config.exists() and journal.exists() and vault.writes == 1

    restarted = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=factory,
    )
    assert restarted.start() is live.ActivationState.READY
    assert restarted.owner_name() == "José 李小龍"
    assert owner_v8.FIRST_CONTACT_QUESTION not in restarted.owner_prompt_directive()
    assert restarted.handle_owner_tool("correct_owner_name", {"name": "Renée"})[
        "address"
    ] == "Renée"
    forgotten = restarted.handle_owner_tool("forget_owner_name", {})
    assert forgotten["state"] == "unknown" and forgotten["address"] == "Sir"
    assert owner_v8.FIRST_CONTACT_QUESTION in restarted.owner_prompt_directive()
    assert "Efendim" not in restarted.owner_prompt_directive()


def test_vault_failure_is_sticky_degraded_and_never_retried_or_rewritten(tmp_path):
    memory = Memory()
    lease = Lease()
    head = HeadStore(lease)
    vault = Vault(fail_read=True)
    factory, _config, journal = authority_factory(tmp_path, memory, head, lease, vault)
    controller = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=factory,
    )
    assert controller.start() is live.ActivationState.DEGRADED
    reads = vault.reads
    assert controller.start() is live.ActivationState.DEGRADED
    assert vault.reads == reads and vault.writes == 0 and not journal.exists()
    assert controller.owner_address() == "Sir"
    with pytest.raises(live.ActivationError, match="not writable"):
        controller.set_name("Alice")


def test_lease_failure_is_sticky_degraded_without_owner_store_rewrite(tmp_path):
    memory = Memory()
    good_lease = Lease()
    head = HeadStore(good_lease)
    vault = Vault(b"k" * 32)
    factory, config, journal = authority_factory(
        tmp_path, memory, head, good_lease, vault
    )
    seeded = factory()
    seeded.set_name("Alice")
    before = (config.read_bytes(), journal.read_bytes(), head.value, vault.value)

    bad_lease = Lease(fail=True)
    head.lease = bad_lease
    broken_factory, _, _ = authority_factory(
        tmp_path, memory, head, bad_lease, vault
    )
    controller = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=broken_factory,
    )
    assert controller.start() is live.ActivationState.DEGRADED
    assert (config.read_bytes(), journal.read_bytes(), head.value, vault.value) == before
    assert vault.writes == 0


def test_phase5_session_catalog_read_kill_revoke_and_reconnect():
    environment = active_environment()
    catalog = (CatalogSeedV3("system_status", "System Status"),)

    def bridge(suffix):
        return create_phase5_integration_v3(
            session_id=f"session-{suffix}",
            trace_id=f"trace-{suffix}",
            catalog=catalog,
            environ=environment,
        )

    first = bridge("read")
    assert first is not None
    allowed, reason = first.permission_hook(
        LOCAL_CATALOG_TOOL,
        {"page_size": 1, "_phase5_invocation_ref": "activation-read"},
    )
    assert allowed, reason
    result = first.catalog_read("activation-read", {"page_size": 1})
    assert result["state"] == "completed" and len(result["items"]) == 1
    assert first.kill()["data"]["state"] == "TERMINATED"

    second = bridge("revoke")
    assert second.revoke()["data"]["state"] == "TERMINATED"
    third = bridge("reconnect")
    assert third.reconnect()["data"]["state"] == "TERMINATED"
    replacement = bridge("replacement")
    assert replacement.status_payload()["data"]["state"] in {"READY", "DEGRADED"}


def test_coordinator_termination_forwards_exact_session_boundary():
    calls = []

    class Bridge:
        def kill(self):
            calls.append("kill")
            return {"state": "TERMINATED"}

    class Authority:
        class Snapshot:
            reconciled = True
            display_name = "Alice"

        snapshot = Snapshot()

        def reconcile(self):
            return self.snapshot

        def begin_contact(self):
            return None

        def prompt_directive(self):
            return "owner"

        def address(self):
            return "Alice"

    controller = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=Authority,
    )
    assert controller.start() is live.ActivationState.READY
    controller.bind_phase5_bridge(Bridge())
    assert controller.terminate("kill") == {"state": "TERMINATED"}
    assert calls == ["kill"] and controller.state is live.ActivationState.TERMINATED


def test_install_seams_owner_tools_prompt_phase5_binding_and_hud_flag(monkeypatch):
    calls = []

    class Authority:
        class Snapshot:
            reconciled = True
            display_name = None

        snapshot = Snapshot()

        def reconcile(self):
            return self.snapshot

        def begin_contact(self):
            return owner_v8.FIRST_CONTACT_QUESTION

        def prompt_directive(self):
            return "owner-directive"

        def address(self):
            return "Sir"

        def set_name(self, value):
            self.snapshot.display_name = value
            return types.SimpleNamespace(
                state=types.SimpleNamespace(value="known"),
                name_known=True,
                address=value,
            )

    class FunctionResponse:
        def __init__(self, **values):
            self.__dict__.update(values)

    class Assistant:
        async def _execute_tool(self, fc):
            calls.append(("legacy", fc.name))

        def _start_phase5_session(self):
            self._phase5 = "bridge"

        def _stop_phase5_session(self, reason):
            calls.append(("stop", reason))

    class UiMainWindow:
        def _configured_owner_name(self):
            return "legacy"

        def _on_setup_done(self, key, os_name, owner_name=""):
            calls.append(("setup", key, os_name, owner_name))

    monkeypatch.setitem(sys.modules, "ui", types.SimpleNamespace(MainWindow=UiMainWindow))

    module = types.SimpleNamespace(
        _load_system_prompt=lambda: "base-prompt",
        _load_owner_name=lambda: "legacy",
        TOOL_DECLARATIONS=[],
        Assistant=Assistant,
        types=types.SimpleNamespace(FunctionResponse=FunctionResponse),
    )
    controller = live.OnyxLiveActivationV1(
        live.ActivationFlagsV1.from_environ(active_environment()),
        authority_factory=Authority,
    )
    controller.install_into_main(module)
    assert module._load_owner_name() == ""
    prompt = module._load_system_prompt()
    assert "owner-directive" in prompt and "English token 'Sir'" in prompt
    assert {item["name"] for item in module.TOOL_DECLARATIONS} == {
        "set_owner_name",
        "correct_owner_name",
        "forget_owner_name",
    }
    instance = Assistant()
    instance._start_phase5_session()
    assert controller._phase5_bridge == "bridge"
    instance._stop_phase5_session("reconnect")
    assert controller._phase5_bridge is None and calls[-1] == ("stop", "reconnect")
    window = UiMainWindow()
    assert window._configured_owner_name() == "Sir"
    window._on_setup_done("key", "windows", "Alice")
    assert calls[-1] == ("setup", "key", "windows", "Alice")
    assert controller.owner_name() == "Alice"
    ui_source = (ROOT / "ui.py").read_text(encoding="utf-8")
    assert 'os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"' in ui_source
    assert "self._hud_v5_live = False" in ui_source
    assert "legacy central widget changed during activation" in ui_source


def test_accepted_candidate_bytes_and_e6_records_remain_exact():
    anchors = {
        "core/owner_profile_v8.py": "837295cfdf663dc97bf32592d186e0ba76ee74c83e1c757cfe420baea7dc0f3b",
        "core/phase5_integration_v3.py": "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    }
    for relative, expected in anchors.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    for record in (
        "VE-OWNER-PROFILE-V8-E6-001.md",
        "VE-P5-INTEGRATION-V3-E6-001.md",
        "VE-HUD-ORB-V5-LIVE-E6-001.md",
        "VE-P5-RUNTIME-V10-E6-001.md",
        "VE-P51-GRANTS-R11-E6-001.md",
        "VE-P52-APPROVAL-INBOX-V15-E6-001.md",
        "VE-P53-CAPABILITY-NEXUS-V32-E6-001.md",
    ):
        assert (ROOT / "docs" / "onyx" / "acceptance" / record).is_file()


def test_no_provider_network_or_live_activation_side_effects():
    source = (ROOT / "core" / "onyx_live_activation_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("requests.", "httpx.", "socket.", "google.genai", "subprocess"):
        assert forbidden not in source
    assert "os.environ[" not in source and "os.environ.update" not in source
    assert importlib.util.find_spec("core.onyx_live_activation_v1") is not None
