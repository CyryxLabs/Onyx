"""Machine-readable CLI for Onyx agentic planning and opportunity controls."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.aexos_engine_adapter_v1 import (  # noqa: E402
    AexosBudgetEnvelopeV1,
    AexosEngineAdapterV1,
    AexosEngineAdapterV1ContractError,
    AexosEngineAdapterV1Denied,
    AexosEngineAdapterV1Error,
)
from core.aexos_department_router_v1 import (  # noqa: E402
    AexosDepartmentRouterV1,
    AexosDepartmentRouterV1ContractError,
    AexosDepartmentRouterV1Denied,
)
from core.opportunity_economics_v1 import (  # noqa: E402
    EconomicEvidenceV1,
    OpportunityEconomicsGuardV1,
    OpportunityEconomicsV1ContractError,
)
from core.opportunity_monitor_v1 import (  # noqa: E402
    OpportunityMonitorV1,
    OpportunityMonitorV1ContractError,
    OpportunityMonitorV1Denied,
    OpportunityMonitorV1Error,
)
from core.paths import memory_dir  # noqa: E402
from core.web_opportunity_research_v1 import (  # noqa: E402
    WebOpportunityResearchV1,
    WebOpportunityResearchV1ContractError,
    WebOpportunityResearchV1Denied,
    WebOpportunityResearchV1Error,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-agentic")
    commands = parser.add_subparsers(dest="command", required=True)

    status = commands.add_parser("aexos-status")
    status.add_argument("--root", type=Path)
    discover = commands.add_parser("aexos-discover")
    discover.add_argument("query")
    discover.add_argument("--root", type=Path)
    discover.add_argument("--story", required=True)
    discover.add_argument("--budget-micro-usd", type=int, required=True)
    discover.add_argument("--timeout", type=int, default=15)

    department = commands.add_parser("department-plan")
    department.add_argument("task")
    department.add_argument("--root", type=Path)
    department.add_argument("--story", required=True)
    department.add_argument("--budget-micro-usd", type=int, required=True)
    department.add_argument("--timeout", type=int, default=15)
    department.add_argument("--squad", action="append", default=[])

    research = commands.add_parser("research")
    research.add_argument("query")
    research.add_argument("--mode", choices=("search", "news"), default="search")
    research.add_argument("--limit", type=int, default=8)

    economics = commands.add_parser("economics")
    economics.add_argument("--revenue-micro", type=int, required=True)
    economics.add_argument("--cost-micro", type=int, required=True)
    economics.add_argument("--currency", default="USD")
    economics.add_argument("--revenue-source", required=True)
    economics.add_argument("--cost-source", required=True)
    economics.add_argument("--target-bp", type=int, default=8_000)
    economics.add_argument("--verified", action="store_true")

    monitor = commands.add_parser("monitor")
    monitor.add_argument(
        "action", choices=("configure", "status", "run", "digests", "kill", "resume")
    )
    monitor.add_argument("--db", type=Path, default=None)
    monitor.add_argument("--owner", default="owner")
    monitor.add_argument("--workspace", default="default")
    monitor.add_argument("--schedule-id")
    monitor.add_argument("--query")
    monitor.add_argument("--domain", action="append", default=[])
    monitor.add_argument("--interval-seconds", type=int, default=21_600)
    monitor.add_argument("--mode", choices=("search", "news"), default="news")
    monitor.add_argument("--limit", type=int, default=8)
    monitor.add_argument("--max-runs-per-day", type=int, default=4)
    monitor.add_argument("--max-age-hours", type=int, default=168)
    return parser


def _payload(value: object) -> object:
    if is_dataclass(value):
        return {key: _payload(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _payload(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_payload(item) for item in value]
    return value


def _aexos_adapter(root: Path | None) -> AexosEngineAdapterV1:
    return AexosEngineAdapterV1.bundled() if root is None else AexosEngineAdapterV1(root)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "aexos-status":
            result: object = _aexos_adapter(args.root).status()
        elif args.command == "aexos-discover":
            result = _aexos_adapter(args.root).discover_workers(
                args.query,
                envelope=AexosBudgetEnvelopeV1(
                    args.story, args.budget_micro_usd, args.timeout
                ),
            )
        elif args.command == "department-plan":
            result = AexosDepartmentRouterV1(
                _aexos_adapter(args.root)
            ).plan(
                args.task,
                envelope=AexosBudgetEnvelopeV1(
                    args.story, args.budget_micro_usd, args.timeout
                ),
                requested_squads=args.squad,
            )
        elif args.command == "research":
            result = WebOpportunityResearchV1().research(
                args.query, mode=args.mode, max_results=args.limit
            )
        elif args.command == "economics":
            result = OpportunityEconomicsGuardV1().evaluate(
                revenue=EconomicEvidenceV1(
                    args.revenue_micro,
                    args.currency,
                    args.revenue_source,
                    args.verified,
                ),
                direct_variable_cost=EconomicEvidenceV1(
                    args.cost_micro,
                    args.currency,
                    args.cost_source,
                    args.verified,
                ),
                target_margin_bp=args.target_bp,
            )
        else:
            monitor = OpportunityMonitorV1(
                args.db or (memory_dir() / "opportunity_monitor_v1.sqlite3"),
                owner_profile_id=args.owner,
                workspace_id=args.workspace,
            )
            if args.action == "configure":
                result = monitor.configure(
                    schedule_id=args.schedule_id,
                    query=args.query,
                    allowed_domains=args.domain,
                    interval_seconds=args.interval_seconds,
                    mode=args.mode,
                    max_results=args.limit,
                    max_runs_per_day=args.max_runs_per_day,
                    max_age_hours=args.max_age_hours,
                )
            elif args.action == "status":
                result = {"killed": monitor.killed(), "policies": monitor.policies()}
            elif args.action == "run":
                result = monitor.run_due(WebOpportunityResearchV1())
            elif args.action == "digests":
                result = monitor.digests(limit=args.limit)
            elif args.action == "kill":
                monitor.kill()
                result = {"killed": True}
            else:
                monitor.resume()
                result = {"killed": False}
        print(json.dumps({"ok": True, "result": _payload(result)}, ensure_ascii=False, sort_keys=True))
        return 0
    except (
        AexosEngineAdapterV1ContractError,
        AexosEngineAdapterV1Denied,
        AexosEngineAdapterV1Error,
        AexosDepartmentRouterV1ContractError,
        AexosDepartmentRouterV1Denied,
        OpportunityEconomicsV1ContractError,
        OpportunityMonitorV1ContractError,
        OpportunityMonitorV1Denied,
        OpportunityMonitorV1Error,
        WebOpportunityResearchV1ContractError,
        WebOpportunityResearchV1Denied,
        WebOpportunityResearchV1Error,
    ) as exc:
        print(
            json.dumps(
                {"ok": False, "error": {"code": type(exc).__name__, "message": str(exc)}},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
