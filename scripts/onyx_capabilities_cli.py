"""Deterministic provider-free CLI for the production capability composition."""

from __future__ import annotations

import argparse
import gc
import json
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.capability_composition_v1 import (  # noqa: E402
    CAPABILITY_OPERATIONS,
    create_capability_composition_v1,
)
from core import permission_broker, tool_audit  # noqa: E402
from core.capability_expansion_service_v1 import (  # noqa: E402
    CapabilityExpansionServiceV1,
    with_installed_local_capabilities_v1,
)
from core.governance_nucleus_v1 import (  # noqa: E402
    GovernanceIdentityV1,
    GovernanceNucleusV1,
    GovernanceV1Denied,
)

CLI_SCHEMA = "OnyxCapabilitiesCLI.v1"


def _module_origins() -> dict[str, str]:
    """Return bounded origins after proving imports belong to the frozen root."""

    modules = {
        "composition": sys.modules[create_capability_composition_v1.__module__],
        "expansion": sys.modules[CapabilityExpansionServiceV1.__module__],
        "governance": sys.modules[GovernanceNucleusV1.__module__],
        "cli": sys.modules[__name__],
    }
    root = ROOT.resolve(strict=True)
    origins: dict[str, str] = {}
    for label, module in modules.items():
        origin = Path(module.__file__).resolve(strict=True)
        if not origin.is_relative_to(root):
            raise RuntimeError(f"capability module escaped runtime root: {label}")
        origins[label] = origin.relative_to(root).as_posix()
    if bool(getattr(sys, "frozen", False)) and root == Path.cwd().resolve():
        raise RuntimeError("frozen capability smoke cannot execute from its bundle root")
    return origins


class _MemoryVault:
    def __init__(self) -> None:
        self._value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self._value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self._value = bytes(value)

    def delete(self) -> bool:
        existed = self._value is not None
        self._value = None
        return existed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="onyx-capabilities")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("readiness")
    commands.add_parser("list")
    commands.add_parser("safe-test")
    return parser


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(
        path=path,
        identity=GovernanceIdentityV1(
            "provider-free-principal",
            "provider-free-workspace",
            "provider-free-account",
            "provider-free-profile",
        ),
        key_vault=_MemoryVault(),
        head_vault=_MemoryVault(),
        pending_vault=_MemoryVault(),
        require_windows_boundary=False,
    )


def _exercise_installed_local_capabilities(root: Path) -> dict[str, object]:
    """Execute positive, provider-free operations through the production broker."""

    previous_callback = permission_broker.get_permission_callback()
    previous_audit_path = tool_audit.AUDIT_PATH
    tool_audit.AUDIT_PATH = root / "audit" / "tool_audit.sqlite3"
    permission_broker.set_permission_callback(lambda request: request["digest"])
    settings = with_installed_local_capabilities_v1(
        {"ONYX_GOVERNED_PERSONALIZATION_V1": True}
    )
    service = CapabilityExpansionServiceV1(
        root / "local-capabilities",
        owner_profile_id="provider-free-principal",
        workspace_id="provider-free-workspace",
        config=settings,
        environ={},
        social_video_roots=(root,),
    )
    calls = (
        {"capability": "plugin", "operation": "list"},
        {"capability": "clipboard", "operation": "status"},
        {
            "capability": "wellness",
            "operation": "status",
            "day": "2026-01-01",
            "timezone": "UTC",
        },
        {"capability": "wellness", "operation": "repetition_start", "activity": "push-up"},
        {"capability": "wellness", "operation": "repetition_status"},
        {
            "capability": "wellness",
            "operation": "repetition_stop",
            "occurred_at": "2026-01-01T00:00:00+00:00",
            "timezone_name": "UTC",
            "idempotency_key": "provider-free-repetition-smoke-v1",
        },
        {"capability": "personalization", "operation": "onboarding_status"},
        {
            "capability": "social",
            "operation": "generate",
            "brief": "Explain one verified Cyryx Labs capability without unsupported claims.",
            "brand": "Cyryx Labs",
            "platform": "linkedin",
            "source_refs": ["provider-free-smoke-v1"],
        },
        {"capability": "social", "operation": "status"},
    )
    receipts: list[dict[str, object]] = []
    try:
        for index, call in enumerate(calls, start=1):
            response = service.dispatch_model(call, trace_id=f"capability-smoke-{index}")
            receipt = response.get("receipt")
            if (
                type(receipt) is not dict
                or receipt.get("decision") != "allow"
                or receipt.get("outcome") != "dispatched"
            ):
                raise RuntimeError("local capability did not produce a positive receipt")
            receipts.append(
                {
                    "capability": receipt["capability"],
                    "operation": receipt["operation"],
                    "decision": receipt["decision"],
                    "outcome": receipt["outcome"],
                }
            )
        states = service.redacted_status()
        expected = ("clipboard", "personalization", "plugin", "social", "wellness")
        verified = tuple(
            name
            for name in expected
            if states.get(name, {}).get("status") == "approved"
        )
        if verified != expected:
            raise RuntimeError("installed local capability activation is incomplete")
        return {
            "families": verified,
            "receipts": receipts,
            "publishing": "oauth-adapter-required",
            "provider_dispatch": False,
        }
    finally:
        service.kill()
        permission_broker.set_permission_callback(previous_callback)
        tool_audit.AUDIT_PATH = previous_audit_path
        del service
        gc.collect()


def _run(command: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="onyx-capabilities-") as temporary:
        nucleus = _nucleus(Path(temporary) / "governance.sqlite3")
        composition = create_capability_composition_v1(nucleus=nucleus)
        try:
            if command in {"status", "readiness"}:
                result: object = asdict(composition.status())
            elif command == "list":
                result = composition.list_capabilities()["capabilities"]
            else:
                session = nucleus.begin_session()
                denied: list[str] = []
                rows = composition.list_capabilities()["capabilities"]
                families = tuple(row["capability"] for row in rows)
                expected_families = tuple(sorted(CAPABILITY_OPERATIONS))
                if families != expected_families:
                    raise RuntimeError("required capability port membership drifted")
                for capability, row in ((item["capability"], item) for item in rows):
                    operation = row["operations"][0]
                    try:
                        receipt = composition.dispatch(session, capability, operation, {})
                        if receipt.outcome == "failed":
                            denied.append(capability)
                    except GovernanceV1Denied:
                        denied.append(capability)
                kill = composition.kill()
                local_operational = _exercise_installed_local_capabilities(
                    Path(temporary) / "operational"
                )
                result = {
                    "provider_dispatch": False,
                    "families": families,
                    "families_denied": tuple(sorted(denied)),
                    "policy_only_families": (
                        "budget",
                        "command_center",
                        "guild",
                        "intelligence",
                        "knowledge_refinery",
                        "model_router",
                        "project_execution",
                        "strategy",
                    ),
                    "kill_status": kill.status,
                    "local_operational": local_operational,
                    "redacted": True,
                    "module_origins": _module_origins(),
                    "runtime": "frozen" if getattr(sys, "frozen", False) else "source",
                }
            return {"schema": CLI_SCHEMA, "ok": True, "command": command, "result": result}
        finally:
            composition.kill()
            nucleus.close()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    print(json.dumps(_run(args.command), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
