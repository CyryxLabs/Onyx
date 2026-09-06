"""Verify the current Phase 6 successor without rebinding frozen candidates."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
from typing import Final


PROJECT: Final = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID: Final = "VE-PHASE6-CURRENT-V1-001"
MARKER: Final = "PHASE6_CURRENT_V1_ACCEPTANCE_OK"
CURRENT_BOOTSTRAP: Final = "scripts/bootstrap_onyx_live_v24.pyw"
CURRENT_LAUNCHER: Final = "scripts/launch_onyx_live_v24.pyw"
CURRENT_ACTIVATION: Final = "core/onyx_live_activation_v24.py"
V23_BOOTSTRAP: Final = "scripts/bootstrap_onyx_live_v23.pyw"
V23_LAUNCHER: Final = "scripts/launch_onyx_live_v23.pyw"
V23_ACTIVATION: Final = "core/onyx_live_activation_v23.py"
V23_ACTIVATION_SHA256: Final = (
    "207aec29d0e87a874b3641162f53250382fe18f2dfc2998b68d3702b82d85607"
)
HISTORICAL_CANDIDATES: Final = (
    "phase6_live_integration_v2",
    "phase6_live_wiring_v1",
    "phase6_local_mcp_v1",
    "phase6_provider_registry_v1",
    "phase6_research_cells_v1",
)


class Phase6CurrentV1Error(RuntimeError):
    """The semantic current successor contract is invalid."""


def _text(project: Path, relative: str) -> str:
    path = (project.resolve() / relative).resolve(strict=True)
    try:
        path.relative_to(project.resolve(strict=True))
    except ValueError as exc:
        raise Phase6CurrentV1Error(f"current source escapes project: {relative}") from exc
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise Phase6CurrentV1Error(f"current source has an unexpected BOM: {relative}")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Phase6CurrentV1Error(f"current source is not UTF-8: {relative}") from exc


def _imports(source: str, relative: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=relative)
    except SyntaxError as exc:
        raise Phase6CurrentV1Error(f"current source cannot be parsed: {relative}") from exc
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported.add(module)
            imported.update(
                f"{module}.{alias.name}" if module else alias.name
                for alias in node.names
            )
    return imported


def _require_ordered(source: str, needles: tuple[str, ...], label: str) -> None:
    cursor = -1
    for needle in needles:
        position = source.find(needle, cursor + 1)
        if position < 0:
            raise Phase6CurrentV1Error(f"{label} omits ordered seam: {needle}")
        cursor = position


def _verify_default_off_candidates() -> tuple[str, ...]:
    if str(PROJECT) not in sys.path:
        sys.path.insert(0, str(PROJECT))
    from core import phase6_live_integration_v2 as integration
    from core import phase6_live_wiring_v1 as wiring
    from core import phase6_local_mcp_v1 as local_mcp
    from core import phase6_provider_registry_v1 as providers
    from core import phase6_research_cells_v1 as research

    checks = (
        (
            integration.FEATURE_FLAG,
            integration.LiveIntegrationFeatureGateV2.from_environ({}),
            lambda gate: integration.create_phase6_live_integration_v2(gate=gate),
        ),
        (
            wiring.FEATURE_FLAG,
            wiring.LiveWiringFeatureGateV1.from_environ({}),
            lambda gate: wiring.create_phase6_live_wiring_v1(gate=gate),
        ),
        (
            local_mcp.FEATURE_FLAG,
            local_mcp.LocalMCPFeatureGateV1.from_environ({}),
            lambda gate: local_mcp.create_local_read_only_mcp_v1(gate=gate),
        ),
        (
            providers.FEATURE_FLAG,
            providers.ProviderRegistryFeatureGateV1.from_environ({}),
            lambda gate: providers.create_provider_registry_v1(gate=gate),
        ),
        (
            research.FEATURE_FLAG,
            research.ResearchCellsFeatureGateV1.from_environ({}),
            lambda gate: research.create_research_verifier_pipeline_v1(gate=gate),
        ),
    )
    flags: list[str] = []
    for feature_flag, gate, factory in checks:
        if gate.enabled is not False or factory(gate) is not None:
            raise Phase6CurrentV1Error(
                f"historical candidate is no longer strict default-off: {feature_flag}"
            )
        flags.append(feature_flag)
    return tuple(flags)


def verify(project: Path = PROJECT) -> dict[str, object]:
    """Verify current composition and the retired candidates' safe boundary."""

    project = Path(project)
    stable = _text(project, "scripts/bootstrap_onyx.pyw")
    bootstrap = _text(project, CURRENT_BOOTSTRAP)
    launcher = _text(project, CURRENT_LAUNCHER)
    activation_v24 = _text(project, CURRENT_ACTIVATION)
    bootstrap_v23 = _text(project, V23_BOOTSTRAP)
    launcher_v23 = _text(project, V23_LAUNCHER)
    main = _text(project, "main.py")
    activation_v18 = _text(project, "core/onyx_live_activation_v18.py")
    activation_v19 = _text(project, "core/onyx_live_activation_v19.py")
    activation_v20 = _text(project, "core/onyx_live_activation_v20.py")
    activation_v21 = _text(project, "core/onyx_live_activation_v21.py")
    activation_v22 = _text(project, "core/onyx_live_activation_v22.py")
    activation_v23 = _text(project, "core/onyx_live_activation_v23.py")
    packaging = _text(project, "packaging/onyx.spec")

    if (
        'CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"'
        not in stable
    ):
        raise Phase6CurrentV1Error("stable bootstrap is not bound to current V24")
    if 'LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v24.pyw"' not in bootstrap:
        raise Phase6CurrentV1Error("V24 bootstrap is not bound to its launcher")
    if 'V23_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v23.pyw"' not in bootstrap:
        raise Phase6CurrentV1Error("V24 bootstrap lost its exact V23 predecessor")
    if 'ROOT / "scripts" / "launch_onyx_live_v23.pyw"' not in launcher:
        raise Phase6CurrentV1Error("V24 launcher lost its exact V23 predecessor")
    if (
        'from core.onyx_live_activation_v24 import activate_main' not in launcher
        or "controller = activate_main(onyx_main)" not in launcher
    ):
        raise Phase6CurrentV1Error("V24 launcher is not bound to activation V24")
    actual_v23_sha256 = hashlib.sha256(
        (project / V23_ACTIVATION).read_bytes()
    ).hexdigest()
    if actual_v23_sha256 != V23_ACTIVATION_SHA256:
        raise Phase6CurrentV1Error("authenticated V23 predecessor source drifted")
    if (
        'V23_RELATIVE_PATH: Final = Path("core") / "onyx_live_activation_v23.py"'
        not in activation_v24
        or f'V23_SHA256: Final = "{V23_ACTIVATION_SHA256}"' not in activation_v24
    ):
        raise Phase6CurrentV1Error("V24 activation lost its exact V23 source binding")
    _require_ordered(
        activation_v24,
        (
            "def _read_authenticated_v23(",
            "def _load_authenticated_v23(",
            "v23: Final = _load_authenticated_v23()",
            "class ActivationFlagsV24:",
            "class HostContractV24:",
            "def preflight_host(",
            "class OnyxLiveActivationV24:",
            "def activate_main(",
        ),
        "V24 authenticated activation",
    )
    if 'LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v23.pyw"' not in bootstrap_v23:
        raise Phase6CurrentV1Error("historical V23 bootstrap binding drifted")
    if 'launch_onyx_live_v22.pyw' not in launcher_v23:
        raise Phase6CurrentV1Error("historical V23 launcher predecessor drifted")
    if "from core import onyx_live_activation_v22 as v22" not in activation_v23:
        raise Phase6CurrentV1Error("V23 no longer composes exact V22")
    if "from core import onyx_live_activation_v21 as v21" not in activation_v22:
        raise Phase6CurrentV1Error("V22 no longer composes exact V21")
    if "from core import onyx_live_activation_v20 as v20" not in activation_v21:
        raise Phase6CurrentV1Error("V21 no longer composes exact V20")
    if "from core import onyx_live_activation_v19 as v19" not in activation_v20:
        raise Phase6CurrentV1Error("V20 no longer composes exact V19")
    if "from core import onyx_live_activation_v18 as v18" not in activation_v19:
        raise Phase6CurrentV1Error("V19 no longer composes exact V18")
    if "from core import onyx_live_activation_v17 as v17" not in activation_v18:
        raise Phase6CurrentV1Error("V18 no longer composes exact V17")

    imported = _imports(main, "main.py")
    for candidate in HISTORICAL_CANDIDATES:
        if any(name == candidate or name.endswith(f".{candidate}") for name in imported):
            raise Phase6CurrentV1Error(
                f"retired Phase 6 candidate was rewired into main.py: {candidate}"
            )
        if candidate in main:
            raise Phase6CurrentV1Error(
                f"retired Phase 6 candidate is referenced by main.py: {candidate}"
            )

    _require_ordered(
        main,
        (
            "authorize_model_tool, name, approval_args",
            "governance.assert_dispatch_allowed",
            "if name == _DOCUMENT_INTAKE_READ_TOOL",
            "controller.execute",
        ),
        "Document Intake dispatch",
    )
    _require_ordered(
        main,
        (
            '"_governance_activation_v16"',
            '"_founder_activation_v17"',
            '"_document_intake_activation_v18"',
            '"_dayops_activation_v19"',
        ),
        "live host initialization",
    )
    required_runtime = (
        "core.onyx_live_activation_v18",
        "core.onyx_live_activation_v19",
        "core.onyx_live_activation_v20",
        "core.onyx_live_activation_v21",
        "core.onyx_live_activation_v22",
        "core.onyx_live_activation_v23",
        "core.onyx_live_activation_v24",
        "core.owner_context_profile_v1",
        "core.owner_context_controller_v1",
        "core.operational_event_bridge_v1",
        "core.operational_event_controller_v1",
        "core.advanced_operations_live_v1",
        "core.document_intake_live_v1",
    )
    if any(f'"{name}"' not in packaging for name in required_runtime):
        raise Phase6CurrentV1Error("packaging omits a current live successor module")

    flags = _verify_default_off_candidates() if project.resolve() == PROJECT else ()
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "current_bootstrap": CURRENT_BOOTSTRAP,
        "current_launcher": CURRENT_LAUNCHER,
        "current_activation": CURRENT_ACTIVATION,
        "v23_predecessor_sha256": actual_v23_sha256,
        "document_intake": "authorized-live-v18-via-v19-v20-v21-v22-v23-v24",
        "advanced_operations": "lazy-live-v20-zero-polling",
        "advanced_commands": "voice-tool-v21-local-metadata-only",
        "owner_context": "voice-tool-v22-explicit-owner-local-context",
        "operational_events": "host-callback-v23-metadata-only-zero-polling",
        "historical_candidates": "default-off-unwired",
        "historical_feature_flags": flags,
        "runtime_effect": "additive-v24-shutdown-guard-over-exact-v23-events",
    }


def main() -> int:
    result = verify()
    print(MARKER + " " + json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
