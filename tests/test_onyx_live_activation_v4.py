from __future__ import annotations

import contextlib
import hashlib
import os
import runpy
import subprocess
import threading
from pathlib import Path

import pytest

from core import onyx_live_activation_v4 as live
from core import owner_profile_v8 as owner_v8
from memory.store import MemoryRecord


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v4.pyw"
HOST_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v4_host.py"
QT_GATE = ROOT / "scripts" / "verify_onyx_live_activation_v4_qt.py"


def launcher_api():
    return runpy.run_path(str(LAUNCHER), run_name="onyx_live_v4_launcher_test")


def clean_environment():
    result = dict(os.environ)
    for name in live.CONTROL_FLAGS:
        result.pop(name, None)
    result["PYTHONDONTWRITEBYTECODE"] = "1"
    result["QT_QPA_PLATFORM"] = "offscreen"
    result["QSG_RHI_BACKEND"] = "software"
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
    assert "ONYX_LIVE_V4_PREIMPORT_REFUSAL CLEAN" in result.stderr


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
    assert "ONYX_LIVE_V4_HOST_PREFLIGHT_OK" in result.stdout


def test_real_onyxlive_eleven_seams_reconnects_and_catalog_e2e():
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
    assert "ONYX_LIVE_ACTIVATION_V4_REAL_HOST_OK" in result.stdout
    assert "seam_failpoints=11 reconnects=64 catalog_reads=64" in result.stdout


def test_real_offscreen_qt_affinity_atomicity_timeout_and_teardown():
    result = subprocess.run(
        [str(PYTHON), "-B", str(QT_GATE)],
        cwd=ROOT,
        env=active_environment(),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ONYX_LIVE_ACTIVATION_V4_QT_OK" in result.stdout
    assert "no-op=refused wrong=refused getter=refused" in result.stdout


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


def test_v1_v2_v3_are_frozen_rejected_v4_is_independent_and_host_has_no_drift():
    frozen = {
        "core/onyx_live_activation_v1.py": "141d363f2df1a8a17a3fa92dc1e5f9f17aed400cdb65fe53f35f3ada0e3f6c51",
        "core/onyx_live_activation_v2.py": "a39c8a43b04b0147dd7efc44bbe355a6873417df8e2432a93c77ef042cd60659",
        "scripts/launch_onyx_live_v2.pyw": "b614616b3efc188b8179596e16d1a209c60d6cefefbb429146d6c9775d770e3b",
        "scripts/verify_onyx_live_activation_v2.py": "58f0328a93f72be2d0e806fd9f3b3656a20b92507e020bd2eaae7a91f7cbc5a7",
        "scripts/verify_onyx_live_activation_v2_host.py": "3bb6e35c84c4b07417ae0b306c1b5a28b5a6842ce2feff63d32e0a135fc8b12b",
        "tests/test_onyx_live_activation_v2.py": "8b84eccee4cb020e448119cec05f9e47fcf0f1af53d3245fc2df63442ba48e8c",
        "docs/onyx/checkpoints/onyx-live-activation-v2/ONYX_LIVE_ACTIVATION_V2_CHECKPOINT.md": "a0572baa31a68d81ce1aadb53780b65267331b4b4e96b97c89fe7a83a62c41f7",
        "docs/onyx/checkpoints/onyx-live-activation-v2/manifest.json": "f829cdc1c4ddb8b2612ab82b4c835d66d7440020f2e18a04ed8d1bcc881af76d",
        "core/onyx_live_activation_v3.py": "8860a140c053e07633209d482209635d67f8e1a4c1b5f70f7bd029ff8c0f0be7",
        "scripts/launch_onyx_live_v3.pyw": "86df14f853654053984623bef3557e205c28898b36b8c6ff02558f834877fc6a",
        "scripts/verify_onyx_live_activation_v3.py": "0dca532679626b3b4815caf668bf8cbbca2b1a48e76f551a6d2ed586e8e6a4c0",
        "scripts/verify_onyx_live_activation_v3_host.py": "2c51d4c61b79a009dbbf4d6ba3fccd38cb3299147cf28c70bc452c7938dbde10",
        "scripts/verify_onyx_live_activation_v3_qt.py": "c6f8f8000b6344f6fd8a469949ac15c06bdffc7e4f655b95dcb76f9b8dcf0ffb",
        "tests/test_onyx_live_activation_v3.py": "31c67de48a54c6145cda72ea25bf526dcd21b12ef8866c77b7bf149300bda6b8",
        "docs/onyx/checkpoints/onyx-live-activation-v3/ONYX_LIVE_ACTIVATION_V3_CHECKPOINT.md": "4419193517c172b9324a49233a0920c4c39b8456deb0a5c942294d4921a3f1d0",
        "docs/onyx/checkpoints/onyx-live-activation-v3/manifest.json": "e886340788a9c305b4cc2142da98e1964546382050880b7123b1203d0b8c9006",
        "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
        "ui.py": "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b",
        "core/owner_profile_v8.py": "837295cfdf663dc97bf32592d186e0ba76ee74c83e1c757cfe420baea7dc0f3b",
        "core/phase5_integration_v3.py": "52d48c121da485c024811e6cd3fafbabaed971175d7cb41ad23358c5c2879b0d",
    }
    for relative, expected in frozen.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    source = (ROOT / "core" / "onyx_live_activation_v4.py").read_text(
        encoding="utf-8"
    )
    assert "onyx_live_activation_v1" not in source
    assert "onyx_live_activation_v2" not in source
    assert "onyx_live_activation_v3" not in source
    assert "os.environ.update" not in source and "os.environ[" not in source
    for forbidden in ("requests.", "httpx.", "socket.", "google.genai"):
        assert forbidden not in source
    for version in ("V1", "V2", "V3"):
        assert (
            ROOT
            / "docs"
            / "onyx"
            / "rejections"
            / f"ONYX_LIVE_ACTIVATION_{version}_REJECTED.md"
        ).is_file()


@pytest.mark.parametrize("value", ["true", "True", "yes", "on", " 1", "1 "])
def test_activation_flags_reject_noncanonical_truth(value):
    environment = live.exact_activation_environment()
    environment[live.LIVE_MASTER_FLAG] = value
    with pytest.raises(live.ActivationV4Error, match="canonical"):
        live.ActivationFlagsV4.from_canonical_environ(environment)
