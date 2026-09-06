# Network Guardian V1

Independent Python CLI for one local connection snapshot, explicit user-supplied
remote-IP indicator matching, durable deduplicated alerts, and optional bounded
Windows outbound blocking. This is not a certified IDS, proof of compromise, or
a system that can detect all hacking. No indicator feed, reputation lookup,
packet inspection, port scan, remote probe, telemetry upload, background service,
main application wiring, UI integration, installer change or release is included.

## Usage

Run from the Onyx source root with the existing Python environment (`psutil` is
already a dependency). Choose a trusted local directory whose parent exists.
Use the **same database per host** for every invocation. Do not move its rule
journal between hosts, delete it while rules exist, or use an untrusted/shared
directory. The SQLite file and its transaction journal are runtime data created
by invocation; no runtime database ships with the module.

```powershell
python -m core.network_guardian_v1 --help
python -m core.network_guardian_v1 status
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 scan
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 scan --indicator 192.0.2.10
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 alerts --limit 100
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 scan --indicator 192.0.2.10 --enforce --max-rules 5
```

The example IP is documentation-only, not a malicious-IP claim. Repeat
`--indicator` for multiple literal IPv4/IPv6 addresses. With no indicators the
CLI still enumerates eligible remote connections, but produces no alerts/rules.
JSON output includes enumeration count, eligible connection metadata, matched
IPs, excluded indicators and a limitation statement. A listening/unconnected
socket contributes to the enumeration count but has no remote IP to evaluate.

The stable bootstrap can forward `argv[2:]` directly to `main(argv=None)`.
`status` accesses neither connections nor the database and needs no `--db`.
`--help` follows argparse's normal `SystemExit(0)` convention. Missing stdout or
stderr in a frozen/windowless process is supported: the command still returns an
exit code and scan alerts remain in SQLite, but console JSON is omitted. V1 does
not provide `--output` or overwrite output files. `scan` is read-only with respect
to network/firewall state by default; it creates/updates the explicit local DB.

Enforcement is disabled by default. `--enforce` produces a dry-run plan only.
Adding **both `--enforce --apply`** explicitly requests live outbound block rules;
Windows and firewall administration privileges are required. No automatic UAC
elevation is attempted. Only matching IPs present in the current snapshot are
eligible; an unobserved indicator is never proactively blocked. Plans use fresh
generated rule names on each scan: `--apply` rescans, it does not replay saved JSON.

```powershell
# LIVE mutation, only when deliberately invoked by the operator:
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 scan --indicator 192.0.2.10 --enforce --apply --max-rules 5
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 rules
# Copy the EXACT name returned by rules; rollback defaults to a dry run:
python -m core.network_guardian_v1 --db C:\TrustedState\guardian.sqlite3 rollback --rule EXACT_NAME_FROM_RULES
# Add --apply to that rollback command to remove the named owned rule.
```

Rollback accepts repeated `--rule` flags, never wildcards, prefixes, `all`, or an
arbitrary firewall rule. Each selection must be an outstanding entry in this
database and match the generated identifier format bound to this store and IP.
Deletion also specifies the exact remote IP, outbound direction and protocol.
Rules block all outbound protocols/ports to that **single IP** on all profiles;
they are not restricted to the observed process and do not create inbound rules.
Other programs using that IP can therefore be affected. A successful command is
not packet-level verification that traffic stopped or that compromise was removed.

## Boundaries, persistence and failures

- Literal IP validation rejects hostnames, CIDRs, address lists/ranges, scope IDs,
  whitespace and command payloads. IPv4-mapped IPv6 canonicalizes to IPv4.
- Loopback, local interface/socket addresses, unspecified, multicast, link-local
  and limited IPv4 broadcast addresses are excluded. Private remote addresses
  remain eligible when explicitly indicated; local-self exclusion is not a ban
  on the entire LAN. Interface changes after a snapshot remain a timing limitation.
- `max-rules` defaults to 10 and allows 1–100 outstanding owned rules, including
  existing rules, per database. It is not a host-wide budget across arbitrary
  databases. Plans exceeding it fail before firewall calls. Rollback has the same
  1–100 per-invocation selection bound. Maximum indicators: 1,000 supplied entries.
- `max-connections` defaults to 10,000, accepts 1–100,000 and fails on overflow,
  never enforces from a truncated snapshot. psutil itself allocates its full OS
  result before this check. Each firewall call has a 15-second timeout; execution
  stops at the first error. There is no unbounded retry/watch loop.
- Alerts are SQLite rows keyed by canonical remote IP. Repeated sockets in one
  snapshot count once; subsequent matching scans increment `observations` and
  update `last_seen`, preserving `first_seen`. SQL constraints/transactions prevent
  duplicate rows across concurrent invocations. Alerts retain IPs and timestamps,
  not process names or packet contents; stdout includes endpoint/PID metadata.
- SQLite uses full synchronous commits. Enforcement intent is committed as
  `pending` before commands; exclusive writer transactions serialize rule changes.
  Only a successful batch marks entries `active`. Timeout, partial failure or
  crash leaves recoverable, possibly-applied `pending` entries. They consume budget
  and prevent further additions; inspect `rules` and use exact owned rollback.
- A failed delete retains its ownership entry. If a pending rule was never added,
  or a rule was removed externally, netsh may return a nonzero status for its
  absence. V1 conservatively leaves that entry unresolved for operator inspection;
  it does not parse localized error prose or treat every delete error as success.
  Keep the database for reconciliation; do not reset it to bypass pending state.
- Ownership is a local trusted-journal boundary, not protection against an
  administrator editing SQLite or cloning generated firewall names. Windows
  netsh deletes all exact matches; do not duplicate these generated names outside
  the subsystem. Existing owned active entries prevent duplicate adds, but V1
  does not continuously attest externally edited/deleted firewall rules.
- OS permissions can deny collection or limit visibility. Collection errors exit
  2 with JSON on stderr, never a fabricated clean scan. Successful enumeration
  also cannot prove OS-wide completeness. Short-lived connections can be missed.
  Other validation/database/firewall failures likewise exit 2; success exits 0.

## Implementation log and scoped review

[AUTO-DECISION] Delivery authority → use the explicit three-file user mission as
the acceptance contract, with review/decision notes here (reason: story, plan,
main, UI and release edits were explicitly excluded).

IDS search before creation covered core/tests/docs names for network/guardian,
and code for `net_connections`, `netsh`, `firewall`, `psutil`, and SQLite patterns.
No existing guardian or firewall adapter was found; squads/components do not
exist in this snapshot. Existing `core/installer.py` declares psutil, and the
versioned standalone modules/tests (including wellness tracking) establish the
module and pytest conventions.

| File | Decision | Reason |
| --- | --- | --- |
| `core/network_guardian_v1.py` | CREATE; REUSE psutil and stdlib SQLite/subprocess | Independent bounded subsystem; no new dependency or shared-file edit |
| `tests/test_network_guardian_v1.py` | CREATE; ADAPT existing pytest/temp-path conventions | Inject collection and command runner; no live firewall mutations |
| `docs/onyx/NETWORK_GUARDIAN_V1.md` | CREATE; ADAPT standalone capability documentation | CLI, limitations and required implementation log in the allowed file |

[AUTO-DECISION] Rule scope → one outbound all-protocol block per observed indicator
IP (reason: exact IP scope and a countable rule budget, without asserting inbound IDS).

Step 5.5 self-critique: addressed duplicate/concurrent application with durable
pending intent and SQLite writer serialization; constrained rollback to journal
ownership plus generated names/IPs; normalized mapped IPv4 before self/exclusion
checks. Edge cases: no indicators/listeners yield no alert, budget overflow denies
the whole block plan, and AccessDenied/timeout preserve truthful failure states.
All external command parameters are argument arrays with `shell=False`; SQL
values are parameterized. No new credentials or approval platform were added.

Step 6.5 / scoped DoD: the 46 isolated tests pass, covering collection, exclusions,
validation, persistence across restart, concurrent deduplication/application,
budgets, dry-run/apply, partial failure, owned rollback, CLI and windowless mode.
Ruff passes for both Python files. CLI `status` and `--help` were executed locally.
No real firewall modification was made; adapter tests inject a fake command runner.
The native netsh add/delete help was inspected read-only to check argument syntax.

The initial default pytest run was stopped during initialization. An isolated
run exposed `WinError 5` on the pre-existing global pytest temp root; using a
fresh unique `--basetemp` with plugin autoload disabled passed (46 tests, 2.09s).
An additional run retaining project conftest hooks also remained in initialization
without test output and was stopped; no project-hook or full-suite pass is claimed.
The exact isolated test invocation is:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$ngTemp = Join-Path $env:TEMP ('onyx-ng-' + [guid]::NewGuid().ToString('N'))
python -B -m pytest --noconftest -o addopts= -q --tb=short -p no:cacheprovider --basetemp $ngTemp tests/test_network_guardian_v1.py
python -B -m ruff check --no-cache core/network_guardian_v1.py tests/test_network_guardian_v1.py
```

Required npm lint/typecheck/test invocations were attempted with `--prefix .`;
all report ENOENT because this Python snapshot has no `package.json`. Git status
and log report that this root has no Git repository metadata. No commit or release
claim is made. Full application regression, live firewall behavior and packaged
bootstrap integration are not certified by this subsystem's isolated tests.
Story/checklist administration, framework report files and shared release files
were left unchanged under the explicit three-file scope; the skill's review and
IDS decision log are retained here instead. No new dependencies were added.
