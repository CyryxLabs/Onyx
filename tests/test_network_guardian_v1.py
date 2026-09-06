from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace as NS

import psutil
import pytest

from core import network_guardian_v1 as ng


IP = "192.0.2.10"
LOCAL = "10.0.0.5"
REAL_WINDLL = getattr(ng.ctypes, "WinDLL", None)


def native_api(directory=r"C:\Windows\System32", *, length=None, wow64=False, wow_ok=True):
    def get_directory(buffer, size):
        buffer.value = directory
        return len(directory) if length is None else length

    def current_process():
        return -1

    def is_wow64(handle, output):
        output._obj.value = wow64
        return wow_ok

    return NS(GetSystemDirectoryW=get_directory, GetCurrentProcess=current_process,
              IsWow64Process=is_wow64)


@pytest.fixture(autouse=True)
def controlled_windows_api(monkeypatch):
    # Firewall tests never query or mutate the real firewall. This also keeps
    # command-generation tests portable when the test host is not Windows.
    monkeypatch.setattr(ng.ctypes, "WinDLL", lambda *a, **kw: native_api(), raising=False)


@pytest.mark.parametrize("ambient", [".", r"Z:\attacker", ""])
def test_netsh_uses_native_directory_not_environment(monkeypatch, ambient):
    monkeypatch.setenv("SystemRoot", ambient)
    monkeypatch.setenv("PATH", ambient)
    monkeypatch.setattr(ng.ctypes, "WinDLL", lambda *a, **kw: native_api(r"D:\OS\System32"))
    assert ng._system_netsh_path() == r"D:\OS\System32\netsh.exe"


@pytest.mark.parametrize("directory,length", [
    (r"System32", None), (r"C:relative", None), (r"\\server\share", None),
    (r"C:\Windows\..\evil", None), (r"C:\Windows\System32", 0),
    (r"C:\Windows\System32", 32768),
])
def test_native_directory_failures_never_dispatch(monkeypatch, directory, length):
    monkeypatch.setattr(ng.ctypes, "WinDLL", lambda *a, **kw: native_api(directory, length=length))
    runner = FakeRunner()
    adapter = ng.WindowsFirewallAdapterV1(runner=runner, platform="win32")
    owner = "a" * 32
    with pytest.raises(ng.GuardianError):
        adapter.execute("add", owner, IP, ng.rule_prefix(owner, IP) + "b" * 32)
    assert runner.calls == []


@pytest.mark.parametrize("bits,wow64,expected", [
    (8, False, "System32"), (4, True, "Sysnative"), (4, False, "System32"),
])
def test_native_directory_architecture(monkeypatch, bits, wow64, expected):
    monkeypatch.setattr(ng.ctypes, "sizeof", lambda _: bits)
    monkeypatch.setattr(ng.ctypes, "WinDLL", lambda *a, **kw: native_api(wow64=wow64))
    assert ng._system_netsh_path() == rf"C:\Windows\{expected}\netsh.exe"


def test_unknown_wow64_state_fails_closed(monkeypatch):
    monkeypatch.setattr(ng.ctypes, "sizeof", lambda _: 4)
    monkeypatch.setattr(ng.ctypes, "WinDLL", lambda *a, **kw: native_api(wow_ok=False))
    with pytest.raises(ng.GuardianError, match="architecture"):
        ng._system_netsh_path()


@pytest.mark.skipif(ng.sys.platform != "win32", reason="real Windows API required")
def test_real_system_directory_ignores_poisoned_environment(monkeypatch):
    monkeypatch.setattr(ng.ctypes, "WinDLL", REAL_WINDLL)
    monkeypatch.setenv("SystemRoot", ".")
    executable = Path(ng._system_netsh_path())
    assert executable.is_absolute() and executable.is_file()
    assert executable.name == "netsh.exe"


def test_unavailable_native_api_fails_closed(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("native API unavailable")

    monkeypatch.setattr(ng.ctypes, "WinDLL", unavailable)
    with pytest.raises(ng.GuardianError, match="API unavailable"):
        ng._system_netsh_path()


def connection(ip=IP):
    return ng.ConnectionV1(LOCAL, 50100, ip, 443, "tcp", "ESTABLISHED", 100)


def snapshot(*ips):
    rows = tuple(connection(ip) for ip in ips)
    return lambda **kwargs: ng.SnapshotV1(rows, frozenset({LOCAL}), len(rows))


class FakeRunner:
    def __init__(self):
        self.calls = []
        self.installed = set()
        self.failure = None

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == ng.COMMAND_TIMEOUT
        if self.failure:
            raise self.failure
        name = next(arg for arg in args if arg.startswith("name="))
        if args[3] == "add":
            assert name not in self.installed
            self.installed.add(name)
        else:
            self.installed.discard(name)
        return NS(returncode=0)


def subject(tmp_path, *ips):
    runner = FakeRunner()
    adapter = ng.WindowsFirewallAdapterV1(runner=runner, platform="win32")
    guardian = ng.NetworkGuardianV1(tmp_path / "guardian.sqlite3",
                                    collector=snapshot(*(ips or (IP,))), firewall=adapter)
    return guardian, runner


def test_observe_is_default_and_alerts_survive_restart_deduplicated(tmp_path):
    guardian, runner = subject(tmp_path, IP, IP)
    result = guardian.scan([IP])
    assert result["mode"] == "observe" and result["plan"] == []
    assert len(result["connections"]) == 2
    assert result["matched_ips"] == [IP]
    again = ng.NetworkGuardianV1(guardian.path, collector=snapshot(IP))
    again.scan([IP])
    assert again.alerts() == [{"remote_ip": IP, "observations": 2,
                              "first_seen": guardian.alerts()[0]["first_seen"],
                              "last_seen": guardian.alerts()[0]["last_seen"]}]
    assert runner.calls == [] and guardian.rules() == []


@pytest.mark.parametrize("value", ["127.0.0.1", "::1", "::", "0.0.0.0", "224.0.0.1",
                                  "ff02::1", LOCAL, "::ffff:127.0.0.1", "169.254.1.2",
                                  "fe80::1234", "255.255.255.255", "::ffff:10.0.0.5"])
def test_exclusions_never_alert_or_block(tmp_path, value):
    guardian, runner = subject(tmp_path, value)
    result = guardian.scan([value], enforce=True, apply=True)
    assert result["matched_ips"] == [] and result["connections"] == []
    assert guardian.alerts() == [] and guardian.rules() == [] and runner.calls == []


@pytest.mark.parametrize("value", ["example.com", "192.0.2.0/24", "any", "all", "1.2.3.4;whoami",
                                  "1.2.3.4&whoami", "1.2.3.4\n", "1.2.3.4,5.6.7.8",
                                  "$(whoami)", "fe80::1%3", " 1.2.3.4", ""])
def test_invalid_indicators_fail_before_collection(tmp_path, value):
    guardian, runner = subject(tmp_path)
    guardian.collector = lambda **kwargs: pytest.fail("must validate before collection")
    with pytest.raises(ng.GuardianError):
        guardian.scan([value], enforce=True, apply=True)
    assert runner.calls == []


def test_plan_only_then_apply_and_replay(tmp_path):
    guardian, runner = subject(tmp_path, IP, "198.51.100.3")
    plan = guardian.scan([IP, "203.0.113.4"], enforce=True)
    assert plan["mode"] == "dry-run" and len(plan["plan"]) == 1
    assert runner.calls == [] and guardian.rules() == []
    applied = guardian.scan([IP], enforce=True, apply=True)
    command = applied["plan"][0]["command"]
    assert "remoteip=" + IP in command and "action=block" in command
    assert "dir=out" in command and "profile=any" in command
    assert len(runner.calls) == 1 and guardian.rules()[0]["state"] == "active"
    assert guardian.scan([IP], enforce=True, apply=True)["plan"] == []
    assert len(runner.calls) == 1


def test_mapped_ipv4_matches_canonical_indicator(tmp_path):
    guardian, _ = subject(tmp_path, "::ffff:192.0.2.10")
    assert guardian.scan([IP])["matched_ips"] == [IP]


def test_empty_indicators_enumerates_but_never_alerts(tmp_path):
    guardian, runner = subject(tmp_path)
    assert len(guardian.scan([])["connections"]) == 1
    assert guardian.alerts() == [] and runner.calls == []


def test_budgets_validate_and_include_existing_rules(tmp_path):
    guardian, runner = subject(tmp_path, IP, "198.51.100.1")
    with pytest.raises(ng.GuardianError, match="requires --enforce"):
        guardian.scan([IP], apply=True)
    for value in (0, -1, 101, True):
        with pytest.raises(ng.GuardianError, match="max_rules"):
            guardian.scan([IP], enforce=True, apply=True, max_rules=value)
    with pytest.raises(ng.GuardianError, match="budget"):
        guardian.scan([IP, "198.51.100.1"], enforce=True, apply=True, max_rules=1)
    assert runner.calls == []
    guardian.scan([IP], enforce=True, apply=True, max_rules=1)
    with pytest.raises(ng.GuardianError, match="budget"):
        guardian.scan(["198.51.100.1"], enforce=True, apply=True, max_rules=1)
    assert len(runner.calls) == 1
    with pytest.raises(ng.GuardianError, match="Indicator budget"):
        guardian.scan([IP] * (ng.MAX_INDICATORS + 1))


def test_rollback_exact_owned_only_and_dry_run_default(tmp_path):
    guardian, runner = subject(tmp_path)
    guardian.scan([IP], enforce=True, apply=True)
    name = guardian.rules()[0]["name"]
    for names in (["all"], ["Onyx-NG-v1-*"], [name, "unrelated"], [name, name], []):
        with pytest.raises(ng.GuardianError):
            guardian.rollback(names, apply=True)
    plan = guardian.rollback([name])
    assert plan["mode"] == "dry-run" and len(runner.calls) == 1
    command = plan["plan"][0]["command"]
    assert command[3] == "delete" and "name=" + name in command
    assert "remoteip=" + IP in command and "dir=out" in command
    guardian.rollback([name], apply=True)
    assert guardian.rules() == [] and runner.installed == set()
    with pytest.raises(ng.GuardianError):
        guardian.rollback([name], apply=True)


def test_rollback_after_restart_uses_original_owner(tmp_path):
    guardian, runner = subject(tmp_path)
    guardian.scan([IP], enforce=True, apply=True)
    restarted = ng.NetworkGuardianV1(guardian.path, firewall=guardian.firewall)
    assert restarted.owner == guardian.owner
    restarted.rollback([guardian.rules()[0]["name"]], apply=True)
    assert not runner.installed


def test_intent_is_durable_on_timeout_and_add_cannot_retry(tmp_path):
    guardian, runner = subject(tmp_path)
    runner.failure = subprocess.TimeoutExpired("netsh", 15)
    with pytest.raises(ng.GuardianError, match="uncertain"):
        guardian.scan([IP], enforce=True, apply=True)
    assert guardian.rules()[0]["state"] == "pending"
    with pytest.raises(ng.GuardianError, match="Pending"):
        guardian.scan([IP], enforce=True, apply=True)
    assert len(runner.calls) == 1
    runner.failure = None
    guardian.rollback([guardian.rules()[0]["name"]], apply=True)
    assert guardian.rules() == []


def test_failed_rollback_preserves_ownership(tmp_path):
    guardian, runner = subject(tmp_path)
    guardian.scan([IP], enforce=True, apply=True)
    runner.failure = OSError("denied")
    name = guardian.rules()[0]["name"]
    with pytest.raises(ng.GuardianError):
        guardian.rollback([name], apply=True)
    assert guardian.rules()[0]["name"] == name


def test_partial_apply_keeps_entire_intent_for_rollback(tmp_path):
    guardian, runner = subject(tmp_path, IP, "198.51.100.1")
    count = 0

    def partial(args, **kwargs):
        nonlocal count
        count += 1
        return runner(args, **kwargs) if count == 1 else NS(returncode=5)

    guardian.firewall.runner = partial
    with pytest.raises(ng.GuardianError, match="returned 5"):
        guardian.scan([IP, "198.51.100.1"], enforce=True, apply=True)
    assert len(guardian.rules()) == 2
    assert {r["state"] for r in guardian.rules()} == {"pending"}
    assert len(runner.installed) == 1


def test_tampered_rule_is_not_executed(tmp_path):
    guardian, runner = subject(tmp_path)
    with sqlite3.connect(guardian.path) as db:
        db.execute("INSERT INTO ng_rules VALUES ('unrelated', ?, 'active')", (IP,))
    with pytest.raises(ng.GuardianError, match="non-owned"):
        guardian.rollback(["unrelated"], apply=True)
    assert runner.calls == []


def test_other_store_cannot_rollback_rule(tmp_path):
    guardian, runner = subject(tmp_path)
    guardian.scan([IP], enforce=True, apply=True)
    other = ng.NetworkGuardianV1(tmp_path / "other.sqlite3", firewall=guardian.firewall)
    with pytest.raises(ng.GuardianError, match="non-owned"):
        other.rollback([guardian.rules()[0]["name"]], apply=True)
    assert len(runner.calls) == 1


def test_non_windows_cannot_apply(tmp_path):
    guardian, runner = subject(tmp_path)
    guardian.firewall.platform = "linux"
    guardian.scan([IP], enforce=True)
    with pytest.raises(ng.GuardianError, match="requires Windows"):
        guardian.scan([IP], enforce=True, apply=True)
    assert runner.calls == []


def test_concurrent_alerts_are_one_durable_row(tmp_path):
    guardian, _ = subject(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: guardian.scan([IP]), range(12)))
    assert len(guardian.alerts()) == 1
    assert guardian.alerts()[0]["observations"] == 12


def test_collector_handles_listeners_udp_and_all_self_interfaces():
    records = [
        NS(laddr=(LOCAL, 80), raddr=(), type=socket.SOCK_STREAM, pid=None, status="LISTEN"),
        NS(laddr=(LOCAL, 42), raddr=(IP, 53), type=socket.SOCK_DGRAM, pid=None, status="NONE"),
    ]
    calls = []
    source = NS(net_if_addrs=lambda: {"eth0": [NS(family=socket.AF_INET, address=LOCAL),
                                              NS(family=socket.AF_INET6, address="fe80::1%3")]},
                net_connections=lambda **kw: calls.append(kw) or records)
    result = ng.collect_snapshot(source=source)
    assert result.enumerated == 2 and len(result.connections) == 1
    assert result.connections[0].protocol == "udp" and result.connections[0].pid is None
    assert result.local_ips == frozenset({LOCAL, "fe80::1"})
    assert calls == [{"kind": "inet"}]
    with pytest.raises(ng.GuardianError, match="budget"):
        ng.collect_snapshot(source=source, max_connections=1)


@pytest.mark.parametrize("error", [psutil.AccessDenied(), OSError("unavailable")])
def test_collection_failure_does_not_become_clean_scan(tmp_path, error):
    guardian, runner = subject(tmp_path)

    def denied():
        raise error

    guardian.collector = lambda **kw: ng.collect_snapshot(source=NS(net_if_addrs=denied))
    with pytest.raises(ng.GuardianError, match="Cannot enumerate"):
        guardian.scan([IP], enforce=True, apply=True)
    assert guardian.alerts() == [] and runner.calls == []


def test_cli_observe_plan_apply_rollback_and_errors(tmp_path, capsys):
    guardian, runner = subject(tmp_path)
    base = ["--db", str(guardian.path)]
    injected = {"collector": snapshot(IP), "firewall": guardian.firewall}
    assert ng.main(base + ["scan", "--indicator", IP], **injected) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "observe"
    assert ng.main(base + ["scan", "--indicator", IP, "--enforce"], **injected) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert runner.calls == []
    assert ng.main(base + ["scan", "--indicator", IP, "--enforce", "--apply"], **injected) == 0
    capsys.readouterr()
    assert ng.main(base + ["rules"], **injected) == 0
    name = json.loads(capsys.readouterr().out)["rules"][0]["name"]
    assert ng.main(base + ["rollback", "--rule", name], **injected) == 0
    capsys.readouterr()
    assert len(runner.calls) == 1
    assert ng.main(base + ["rollback", "--rule", name, "--apply"], **injected) == 0
    capsys.readouterr()
    assert ng.main(base + ["alerts"], **injected) == 0
    assert len(json.loads(capsys.readouterr().out)["alerts"]) == 1
    assert ng.main(base + ["scan", "--apply"], **injected) == 2
    assert "requires --enforce" in json.loads(capsys.readouterr().err)["error"]


def test_in_memory_database_rejected():
    with pytest.raises(ng.GuardianError, match="durable"):
        ng.NetworkGuardianV1(":memory:")


def test_status_does_not_collect_or_create_database(tmp_path, capsys):
    path = tmp_path / "absent.sqlite3"
    assert ng.main(["--db", str(path), "status"], collector=lambda **kw: pytest.fail()) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["enforcement_default"] is False
    assert not path.exists()


def test_windowless_status_help_scan_and_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ng.sys, "stdout", None)
    monkeypatch.setattr(ng.sys, "stderr", None)
    assert ng.main(["status"]) == 0
    with pytest.raises(SystemExit) as captured:
        ng.main(["--help"])
    assert captured.value.code == 0
    assert ng.main(["scan"]) == 2
    assert ng.main(["--db", str(tmp_path / "windowless.sqlite3"), "scan"],
                   collector=snapshot(IP)) == 0


def test_concurrent_enforcement_never_duplicates_rule(tmp_path):
    guardian, runner = subject(tmp_path)

    def apply_one(_):
        try:
            return guardian.scan([IP], enforce=True, apply=True)
        except ng.GuardianError as exc:
            assert "Pending" in str(exc)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(apply_one, range(8)))
    assert len(runner.installed) == 1 and len(runner.calls) == 1
