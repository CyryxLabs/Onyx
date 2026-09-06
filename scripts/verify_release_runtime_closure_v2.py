"""Fail-closed Slice 5 source, staging and PyInstaller closure verifier."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Final

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from scripts.package_hygiene import (  # noqa: E402
    CAPABILITY_RUNTIME_FILES,
    PackageHygieneError,
    _assert_exact_capability_sources,
)

SPEC_RELATIVE: Final = "packaging/onyx.spec"
CAPABILITY_HIDDENIMPORTS: Final = (
    "core.capability_composition_v1",
    "core.capability_ports",
    "core.capability_ports.argos_v1",
    "core.capability_ports.budget_v1",
    "core.capability_ports.command_center_v1",
    "core.capability_ports.evidence_v1",
    "core.capability_ports.google_workspace_v1",
    "core.capability_ports.graph_v1",
    "core.capability_ports.guild_v1",
    "core.capability_ports.intelligence_v1",
    "core.capability_ports.knowledge_refinery_v1",
    "core.capability_ports.mission_context_v1",
    "core.capability_ports.model_router_v1",
    "core.capability_ports.nexus_v1",
    "core.capability_ports.plugin_v1",
    "core.capability_ports.project_execution_v1",
    "core.capability_ports.social_v1",
    "core.capability_ports.strategy_v1",
    "core.capability_ports.unified_router_v1",
    "core.capability_ports.workspace_v1",
    "core.governed_capability_host_v1",
    "scripts.onyx_capabilities_cli",
)


class ReleaseRuntimeClosureV2Error(RuntimeError):
    """The exact packaged capability closure drifted."""


def _spec_string_literals(path: Path) -> tuple[str, ...]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError) as exc:
        raise ReleaseRuntimeClosureV2Error("onyx.spec is unavailable or invalid") from exc
    return tuple(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def verify_release_runtime_closure_v2(project: Path = PROJECT) -> dict[str, object]:
    """Verify exact files/imports and the absence of test runtime data."""

    root = Path(project).resolve(strict=True)
    try:
        _assert_exact_capability_sources(root)
    except PackageHygieneError as exc:
        raise ReleaseRuntimeClosureV2Error(str(exc)) from exc
    spec = root / SPEC_RELATIVE
    literals = _spec_string_literals(spec)
    source = spec.read_text(encoding="utf-8")
    expected_hiddenimports = set(CAPABILITY_HIDDENIMPORTS)
    actual_hiddenimports = {
        literal
        for literal in literals
        if literal in {
            "core.capability_composition_v1",
            "core.governed_capability_host_v1",
            "scripts.onyx_capabilities_cli",
        }
        or literal == "core.capability_ports"
        or literal.startswith("core.capability_ports.")
    }
    missing_hiddenimports = sorted(expected_hiddenimports - actual_hiddenimports)
    additional_hiddenimports = sorted(actual_hiddenimports - expected_hiddenimports)
    broad_aggregation = sorted(
        token
        for token in (
            'collect_submodules("core")',
            "collect_submodules('core')",
            'collect_submodules("core.capability_ports")',
            "collect_submodules('core.capability_ports')",
        )
        if token in source
    )
    tests_in_runtime = any(
        marker in source
        for marker in (
            'RUNTIME_SOURCES / "tests"',
            "RUNTIME_SOURCES / 'tests'",
        )
    )
    diagnostics = {
        "missing_hiddenimports": missing_hiddenimports,
        "additional_hiddenimports": additional_hiddenimports,
        "broad_dynamic_aggregation": broad_aggregation,
        "tests_in_runtime": tests_in_runtime,
    }
    if (
        missing_hiddenimports
        or additional_hiddenimports
        or broad_aggregation
        or tests_in_runtime
    ):
        raise ReleaseRuntimeClosureV2Error(
            json.dumps(diagnostics, sort_keys=True, separators=(",", ":"))
        )
    return {
        "schema": "onyx.release-runtime-closure.v2",
        "capability_files": list(CAPABILITY_RUNTIME_FILES),
        "hiddenimports": list(CAPABILITY_HIDDENIMPORTS),
        "tests_in_runtime": False,
        "broad_dynamic_aggregation": False,
    }


if __name__ == "__main__":
    print(json.dumps(verify_release_runtime_closure_v2(), sort_keys=True))
