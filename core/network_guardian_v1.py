"""Bounded local connection/indicator matching; not an intrusion detection system."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import ipaddress
import json
import re
import socket
import sqlite3
import subprocess
import sys
import uuid
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterable

import psutil


MAX_RULES = 100
MAX_INDICATORS = 1000
MAX_CONNECTIONS = 100_000
COMMAND_TIMEOUT = 15
LIMITATION = (
    "Snapshot matching of user-provided IP indicators only; not a certified IDS, "
    "not proof of compromise, and cannot detect all hacking."
)


class GuardianError(RuntimeError):
    """A validation, collection, persistence, or firewall operation failed."""


def canonical_ip(value: str) -> str:
    """Accept one literal IP only, never DNS, CIDR, scopes, ranges or commands."""
    if not isinstance(value, str) or len(value) > 45 or "%" in value:
        raise GuardianError("Expected a single unscoped IPv4 or IPv6 literal")
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise GuardianError("Expected a single IPv4 or IPv6 literal") from exc
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def excluded(ip: str, local_ips: Iterable[str] = ()) -> bool:
    address = ipaddress.ip_address(canonical_ip(ip))
    return (
        address.is_loopback or address.is_unspecified or address.is_multicast
        or address.is_link_local or str(address) == "255.255.255.255"
        or str(address) in local_ips
    )


def budget(value: int, ceiling: int, label: str) -> int:
    if type(value) is not int or not 1 <= value <= ceiling:
        raise GuardianError(f"{label} must be between 1 and {ceiling}")
    return value


@dataclass(frozen=True)
class ConnectionV1:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    protocol: str
    status: str
    pid: int | None


@dataclass(frozen=True)
class SnapshotV1:
    connections: tuple[ConnectionV1, ...]
    local_ips: frozenset[str]
    enumerated: int


def collect_snapshot(*, source=psutil, max_connections: int = 10_000) -> SnapshotV1:
    """Read interfaces and inet sockets only; no packets, DNS, probes or processes."""
    budget(max_connections, MAX_CONNECTIONS, "max_connections")
    try:
        local_ips = {
            canonical_ip(item.address.split("%", 1)[0])
            for addresses in source.net_if_addrs().values()
            for item in addresses
            if item.family in (socket.AF_INET, socket.AF_INET6)
        }
        records = source.net_connections(kind="inet")
        if len(records) > max_connections:
            raise GuardianError("Connection budget exceeded; no truncated enforcement")
        result = []
        for item in records:
            if item.laddr:
                local_ips.add(canonical_ip(item.laddr[0].split("%", 1)[0]))
            if not item.raddr or not item.laddr:
                continue
            if item.type not in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
                continue
            result.append(ConnectionV1(
                canonical_ip(item.laddr[0].split("%", 1)[0]), item.laddr[1],
                canonical_ip(item.raddr[0].split("%", 1)[0]), item.raddr[1],
                "tcp" if item.type == socket.SOCK_STREAM else "udp",
                item.status, item.pid,
            ))
        return SnapshotV1(tuple(result), frozenset(local_ips), len(records))
    except (psutil.Error, OSError) as exc:
        raise GuardianError("Cannot enumerate local connections/interfaces; no enforcement") from exc


def indicator_set(values: Iterable[str]) -> frozenset[str]:
    result = set()
    for index, value in enumerate(values):
        if index >= MAX_INDICATORS:
            raise GuardianError("Indicator budget exceeded")
        result.add(canonical_ip(value))
    return frozenset(result)


def rule_prefix(owner: str, ip: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise GuardianError("Invalid guardian store owner")
    digest = hashlib.sha256(canonical_ip(ip).encode("ascii")).hexdigest()[:32]
    return f"Onyx-NG-v1-{owner}-{digest}-"


def validate_rule(owner: str, ip: str, name: str) -> None:
    prefix = rule_prefix(owner, ip)
    if excluded(ip) or not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", name):
        raise GuardianError("Refusing non-owned or invalid firewall rule")


def _system_netsh_path() -> str:
    """Use the native OS directory, never an inherited SystemRoot/PATH value."""
    from ctypes import wintypes

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_directory = kernel32.GetSystemDirectoryW
        get_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        get_directory.restype = wintypes.UINT
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_directory(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise GuardianError("Cannot resolve Windows system directory")
        directory = PureWindowsPath(buffer.value)
        if not directory.is_absolute() or directory.drive.startswith("\\\\") or ".." in directory.parts:
            raise GuardianError("Invalid Windows system directory")
        if ctypes.sizeof(ctypes.c_void_p) == 4:
            current_process = kernel32.GetCurrentProcess
            current_process.argtypes = []
            current_process.restype = wintypes.HANDLE
            is_wow64 = kernel32.IsWow64Process
            is_wow64.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
            is_wow64.restype = wintypes.BOOL
            wow64 = wintypes.BOOL()
            if not is_wow64(current_process(), ctypes.byref(wow64)):
                raise GuardianError("Cannot determine Windows process architecture")
            if wow64.value:
                directory = directory.parent / "Sysnative"
        return str(directory / "netsh.exe")
    except (AttributeError, OSError) as exc:
        raise GuardianError("Windows system directory API unavailable") from exc


class WindowsFirewallAdapterV1:
    """Exact generated names and single remote IPs; never uses shell=True."""

    def __init__(self, *, runner: Callable = subprocess.run, platform: str = sys.platform):
        self.runner = runner
        self.platform = platform

    def command(self, action: str, owner: str, ip: str, name: str) -> list[str]:
        validate_rule(owner, ip, name)
        if action not in ("add", "delete"):
            raise GuardianError("Unsupported firewall action")
        executable = _system_netsh_path()
        args = [executable, "advfirewall", "firewall", action, "rule",
                f"name={name}", "dir=out", f"remoteip={canonical_ip(ip)}", "protocol=any"]
        if action == "add":
            args.extend(["action=block", "enable=yes", "profile=any"])
        return args

    def execute(self, action: str, owner: str, ip: str, name: str) -> None:
        if self.platform != "win32":
            raise GuardianError("Firewall application requires Windows")
        args = self.command(action, owner, ip, name)
        try:
            completed = self.runner(
                args, shell=False, check=False, capture_output=True,
                timeout=COMMAND_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise GuardianError("Firewall outcome uncertain; retain journal and inspect rollback") from exc
        if completed.returncode != 0:
            raise GuardianError(
                f"Firewall returned {completed.returncode}; retain journal and inspect rollback"
            )


class NetworkGuardianV1:
    """Local durable alerts and owned-rule journal. Use one trusted DB per host."""

    def __init__(self, path: Path | str, *, collector: Callable = collect_snapshot,
                 firewall: WindowsFirewallAdapterV1 | None = None):
        self.path = Path(path)
        if str(path) == ":memory:" or self.path.is_symlink():
            raise GuardianError("Use a durable regular database in a trusted local directory")
        self.collector = collector
        self.firewall = firewall or WindowsFirewallAdapterV1()
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ng_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS ng_alerts (
                    remote_ip TEXT PRIMARY KEY, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL, observations INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS ng_rules (
                    name TEXT PRIMARY KEY, remote_ip TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending','active','removed')));
            """)
            db.execute("INSERT OR IGNORE INTO ng_meta VALUES ('owner', ?)", (uuid.uuid4().hex,))
            self.owner = db.execute("SELECT value FROM ng_meta WHERE key='owner'").fetchone()[0]
            rule_prefix(self.owner, "192.0.2.1")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        return db

    def _owned(self, db: sqlite3.Connection) -> list[dict]:
        rows = [dict(row) for row in db.execute(
            "SELECT name,remote_ip,state FROM ng_rules WHERE state != 'removed' ORDER BY name"
        )]
        for row in rows:
            validate_rule(self.owner, row["remote_ip"], row["name"])
        return rows

    def alerts(self, limit: int = 100) -> list[dict]:
        budget(limit, MAX_INDICATORS, "limit")
        with closing(self._connect()) as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM ng_alerts ORDER BY last_seen DESC,remote_ip LIMIT ?", (limit,)
            )]

    def scan(self, indicators: Iterable[str], *, enforce: bool = False,
             apply: bool = False, max_rules: int = 10,
             max_connections: int = 10_000) -> dict:
        if apply and not enforce:
            raise GuardianError("--apply requires --enforce")
        budget(max_rules, MAX_RULES, "max_rules")
        budget(max_connections, MAX_CONNECTIONS, "max_connections")
        targets = indicator_set(indicators)
        snapshot = self.collector(max_connections=max_connections)
        local = {canonical_ip(ip) for ip in snapshot.local_ips}
        local.update(canonical_ip(c.local_ip) for c in snapshot.connections)
        connections = [c for c in snapshot.connections if not excluded(c.remote_ip, local)]
        matches = sorted({canonical_ip(c.remote_ip) for c in connections} & targets)
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as db, db:
            for ip in matches:
                db.execute("""
                    INSERT INTO ng_alerts VALUES (?, ?, ?, 1)
                    ON CONFLICT(remote_ip) DO UPDATE SET last_seen=excluded.last_seen,
                        observations=ng_alerts.observations+1
                """, (ip, now, now))
        plan = []
        if enforce:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                owned = self._owned(db)
                if any(r["state"] == "pending" for r in owned):
                    raise GuardianError("Pending firewall outcome; inspect owned rollback before adding rules")
                new_ips = set(matches) - {r["remote_ip"] for r in owned}
                if len(owned) + len(new_ips) > max_rules:
                    raise GuardianError("Rule budget exceeded (includes existing owned rules)")
                for ip in sorted(new_ips):
                    name = rule_prefix(self.owner, ip) + uuid.uuid4().hex
                    plan.append({"name": name, "remote_ip": ip,
                                 "command": self.firewall.command("add", self.owner, ip, name)})
                    if apply:
                        db.execute("INSERT INTO ng_rules VALUES (?, ?, 'pending')", (name, ip))
            if apply:
                # Intent is durable BEFORE side effects. Lock excludes concurrent rollback.
                # Crash/failure rolls status back to pending, never silently retries adds.
                with closing(self._connect()) as db, db:
                    db.execute("BEGIN IMMEDIATE")
                    pending = {r["name"] for r in self._owned(db) if r["state"] == "pending"}
                    if any(rule["name"] not in pending for rule in plan):
                        raise GuardianError("Rule journal changed; rerun scan")
                    for rule in plan:
                        self.firewall.execute("add", self.owner, rule["remote_ip"], rule["name"])
                        db.execute("UPDATE ng_rules SET state='active' WHERE name=?", (rule["name"],))
        return {"mode": "applied" if apply else "dry-run" if enforce else "observe",
                "enumerated": snapshot.enumerated,
                "connections": [asdict(c) for c in connections], "matched_ips": matches,
                "excluded_indicators": sorted(ip for ip in targets if excluded(ip, local)),
                "plan": plan, "limitation": LIMITATION}

    def rollback(self, names: Iterable[str], *, apply: bool = False,
                 max_rules: int = 10) -> dict:
        budget(max_rules, MAX_RULES, "max_rules")
        requested = list(names)
        if not requested or len(requested) > max_rules or len(set(requested)) != len(requested):
            raise GuardianError("Supply distinct exact owned rule names within max_rules")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            owned = {row["name"]: row for row in self._owned(db)}
            if any(name not in owned for name in requested):
                raise GuardianError("Refusing rollback of unknown/non-owned rule")
            plan = [{**owned[name], "command": self.firewall.command(
                "delete", self.owner, owned[name]["remote_ip"], name
            )} for name in requested]
            if apply:
                for rule in plan:
                    self.firewall.execute("delete", self.owner, rule["remote_ip"], rule["name"])
                    db.execute("UPDATE ng_rules SET state='removed' WHERE name=?", (rule["name"],))
                    # Each successful removal persists; a later failure keeps remaining rows.
                    db.commit()
                    db.execute("BEGIN IMMEDIATE")
                    remaining = {r["name"] for r in self._owned(db)}
                    if any(r["name"] not in remaining for r in plan[plan.index(rule) + 1:]):
                        raise GuardianError("Rollback journal changed; inspect remaining rules")
        return {"mode": "applied" if apply else "dry-run", "plan": plan}

    def rules(self) -> list[dict]:
        with closing(self._connect()) as db:
            return self._owned(db)


def main(argv: list[str] | None = None, *, collector: Callable = collect_snapshot,
         firewall: WindowsFirewallAdapterV1 | None = None) -> int:
    parser = argparse.ArgumentParser(description=LIMITATION)
    parser.add_argument("--db", help="Trusted local SQLite file; required except for status/help")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="Read-only capability status; no collection or database access")
    scan = commands.add_parser("scan", help="One read-only local connection snapshot")
    scan.add_argument("--indicator", action="append", default=[], help="One literal IP; repeatable")
    scan.add_argument("--enforce", action="store_true", help="Enable a block plan (default: off)")
    scan.add_argument("--apply", action="store_true", help="Apply the block plan; requires --enforce")
    scan.add_argument("--max-rules", type=int, default=10)
    scan.add_argument("--max-connections", type=int, default=10_000)
    rollback = commands.add_parser("rollback", help="Remove exact journal-owned rules only")
    rollback.add_argument("--rule", action="append", required=True)
    rollback.add_argument("--apply", action="store_true")
    rollback.add_argument("--max-rules", type=int, default=10)
    alerts = commands.add_parser("alerts")
    alerts.add_argument("--limit", type=int, default=100)
    commands.add_parser("rules")
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            result = {"capability": "network_guardian_v1", "enforcement_default": False,
                      "firewall_platform_supported": sys.platform == "win32",
                      "max_rules_ceiling": MAX_RULES, "limitation": LIMITATION}
            if sys.stdout is not None:
                print(json.dumps(result, sort_keys=True))
            return 0
        if not args.db:
            raise GuardianError("--db is required for scan, alerts, rules and rollback")
        guardian = NetworkGuardianV1(args.db, collector=collector, firewall=firewall)
        if args.command == "scan":
            result = guardian.scan(args.indicator, enforce=args.enforce, apply=args.apply,
                                   max_rules=args.max_rules, max_connections=args.max_connections)
        elif args.command == "rollback":
            result = guardian.rollback(args.rule, apply=args.apply, max_rules=args.max_rules)
        elif args.command == "alerts":
            result = {"alerts": guardian.alerts(args.limit), "limitation": LIMITATION}
        else:
            result = {"rules": guardian.rules()}
        if sys.stdout is not None:
            print(json.dumps(result, sort_keys=True))
        return 0
    except (GuardianError, sqlite3.Error, OSError) as exc:
        if sys.stderr is not None:
            print(json.dumps({"error": str(exc), "limitation": LIMITATION}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
