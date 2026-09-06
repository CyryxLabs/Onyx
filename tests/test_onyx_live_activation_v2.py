from __future__ import annotations

import contextlib
import hashlib
import os
import runpy
import subprocess
import threading
from pathlib import Path

import pytest

from core import onyx_live_activation_v2 as live
from core import owner_profile_v8 as owner_v8
from memory.store import MemoryRecord


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v2.pyw"
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v2_host.py"


def launcher_api():
    return runpy.run_path(str(LAUNCHER), run_name="onyx_live_v2_launcher_test")


def clean_environment():
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    return result


def active_environment():
    result = clean_environment()
    result.update(live.exact_activation_environment())
    return result


def test_launcher_canonical_truth_table_is_preimport_and_exact():
    mode = launcher_api()["_launch_mode"]
    assert mode({}) == "legacy"
    assert mode(live.exact_activation_environment()) == "active"
    assert mode(live.exact_rollback_environment()) == "rollback"
    active_rollback = live.exact_activation_environment()
    active_rollback[live.LIVE_ROLLBACK_FLAG] = "1"
    assert mode(active_rollback) == "rollback"
    for name in (live.LIVE_MASTER_FLAG, *live.CHILD_FLAGS):
        partial = live.exact_activation_environment()
        partial.pop(name)
        assert mode(partial) == "refuse"
    for spelling in ("true", "True", " yes", "1 ", "01", "0"):
        for name in live.CONTROL_FLAGS:
            invalid = live.exact_activation_environment()
            invalid[name] = spelling
            assert mode(invalid) == "refuse"


def test_invalid_launcher_refuses_before_main_or_ui_import_in_fresh_process():
    env = clean_environment()
    env[live.LIVE_MASTER_FLAG] = "true"
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode != 0
    assert "ONYX_LIVE_V2_PREIMPORT_REFUSAL CLEAN" in result.stderr


def test_actual_main_preflight_in_fresh_subprocess_without_provisioning():
    result = subprocess.run(
        [str(PYTHON), "-B", str(LAUNCHER), "--preflight-only"],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "ONYX_LIVE_V2_HOST_PREFLIGHT_OK" in result.stdout


def test_real_onyxlive_transaction_reconnects_catalog_and_projection_e2e():
    result = subprocess.run(
        [str(PYTHON), "-B", str(HOST_GATE)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ONYX_LIVE_ACTIVATION_V2_REAL_HOST_OK" in result.stdout
    assert "reconnects=64 catalog_reads=64 session_trace_ids=128" in result.stdout


class Memory:
    def __init__(self):
        self.records = []

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
    def __init__(self):
        self.lock = threading.RLock()
        self.depth = 0

    @property
    def cross_session_guaranteed(self):
        return True

    @contextlib.contextmanager
    def hold(self, owner_profile_id, *, timeout_seconds):
        assert owner_profile_id == live.OWNER_PROFILE_ID
        with self.lock:
            self.depth += 1
            try:
                yield self
            finally:
                self.depth -= 1


class HeadStore:
    def __init__(self, lease):
        self.lease = lease
        self.value = None

    def load(self, owner_profile_id):
        return self.value

    def compare_and_set(self, owner_profile_id, expected, desired):
        assert self.lease.depth > 0
        if self.value != expected:
            return False
        self.value = desired
        return True


class Vault:
    def __init__(self, value=None):
        self.value = value
        self.writes = 0

    def get_bytes(self):
        return self.value

    def set_bytes(self, value):
        self.writes += 1
        self.value = bytes(value)


def test_owner_v8_real_provision_restart_correct_forget(tmp_path):
    memory = Memory()
    lease = Lease()
    heads = HeadStore(lease)
    vault = Vault()
    config = tmp_path / "config" / "api_keys.json"
    journal = tmp_path / "private" / "identity" / "owner.json"

    def authority():
        return live.provision_owner_authority(
            journal_path=journal,
            vault=vault,
            memory=memory,
            config_path=config,
            chain_head_store=heads,
            transaction_lease=lease,
        )

    first = authority()
    assert first.begin_contact() == owner_v8.FIRST_CONTACT_QUESTION
    assert first.set_name("José 李小龍").display_name == "José 李小龍"
    restarted = authority()
    assert restarted.reconcile().display_name == "José 李小龍"
    assert restarted.correct_name("Renée").display_name == "Renée"
    assert restarted.forget_name().display_name is None
    assert restarted.address() == "Sir"
    assert vault.writes == 1 and journal.is_file() and config.is_file()


def test_v1_is_frozen_rejected_and_v2_does_not_import_it():
    frozen = {
        "core/onyx_live_activation_v1.py": "141d363f2df1a8a17a3fa92dc1e5f9f17aed400cdb65fe53f35f3ada0e3f6c51",
        "scripts/launch_onyx_live_v1.pyw": "d920ba4fb222532e6a54ba6cc51bb52801ed5ce693e77c12282e4fa65bb09d9d",
        "scripts/verify_onyx_live_activation_v1.py": "d4259167ea354cfa25e541a5090c08e42b164742d7950185fbac8e18ed6d2daa",
        "tests/test_onyx_live_activation_v1.py": "66cc8a5ea33df0dd453b44a92c54dfc0146905f8bb00621d0ddb3ef342c316c8",
        "docs/onyx/checkpoints/onyx-live-activation-v1/manifest.json": "3e9021893d93a7c00749d2e5e2c19fd7b90fcf5286239aecbb19e5197487fbef",
        "docs/onyx/checkpoints/onyx-live-activation-v1/ONYX_LIVE_ACTIVATION_V1_CHECKPOINT.md": "d612962e7809653ca7f46e883c4dc7e4623a26ff30e1b4061b97a685e283dbcc",
    }
    for relative, expected in frozen.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    source = (ROOT / "core" / "onyx_live_activation_v2.py").read_text(
        encoding="utf-8"
    )
    assert "import core.onyx_live_activation_v1" not in source
    assert "from core.onyx_live_activation_v1" not in source
    assert (ROOT / "docs" / "onyx" / "rejections" / "ONYX_LIVE_ACTIVATION_V1_REJECTED.md").is_file()


def test_no_live_enablement_provider_calls_or_existing_host_drift():
    source = (ROOT / "core" / "onyx_live_activation_v2.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("requests.", "httpx.", "socket.", "google.genai"):
        assert forbidden not in source
    assert "os.environ.update" not in source and "os.environ[" not in source
    accepted = {
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "core/owner_profile_v8.py": "837295cfdf663dc97bf32592d186e0ba76ee74c83e1c757cfe420baea7dc0f3b",
        "core/phase5_integration_v3.py": "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d",
    }
    for relative, expected in accepted.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


@pytest.mark.parametrize("value", ["true", "True", "yes", "on", " 1", "1 "])
def test_activation_flags_reject_noncanonical_truth(value):
    environment = live.exact_activation_environment()
    environment[live.LIVE_MASTER_FLAG] = value
    with pytest.raises(live.ActivationV2Error, match="canonical"):
        live.ActivationFlagsV2.from_canonical_environ(environment)
