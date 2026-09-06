"""Mechanical, read-only checks for the Phase 4 E1-E5 exit candidate.

This verifier deliberately does not activate a feature flag, import a startup
surface, open owner data, create a sidecar, or make a provider call.  It proves
only the default-off/source boundary and the immutable R10 input binding.  The
stateful failure/rollback cases are exercised separately in isolated pytest
fixtures and recorded in the checkpoint bundle.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core.control_plane import (  # noqa: E402
    CONTROL_PLANE_FLAG,
    ControlPlaneDisabled,
    ControlPlaneStore,
    control_plane_v1_enabled,
)
from core.control_plane_v3 import LEDGER_V3_FLAG, ledger_v3_enabled  # noqa: E402
from core.control_plane_v4 import CONTROL_PLANE_V4_FLAG, control_plane_v4_enabled  # noqa: E402
from core.control_plane_v5 import CONTROL_PLANE_V5_FLAG, control_plane_v5_enabled  # noqa: E402
from core.domain_ledger import M2A_DOMAIN_LEDGER_FLAG, m2a_domain_ledger_enabled  # noqa: E402
from core.ledger_anchor import LEDGER_ANCHOR_FLAG, ledger_anchor_enabled  # noqa: E402
from core.workspaces import (  # noqa: E402
    M1B_BACKFILL_FLAG,
    WORKSPACE_REGISTRY_FLAG,
    m1b_backfill_enabled,
    workspace_registry_enabled,
)
from scripts.verify_p44_scope import verify as verify_r10  # noqa: E402


R10_MANIFEST = PROJECT / "docs/onyx/VE-SCOPE-P44-R10-001.sha256"
STARTUP_SOURCES = (
    PROJECT / "main.py",
    PROJECT / "ui.py",
    PROJECT / "dashboard/server.py",
    PROJECT / "dashboard/security.py",
)
ENHANCED_MODULES = frozenset(
    {
        "core.control_plane",
        "core.control_plane_v3",
        "core.control_plane_v4",
        "core.control_plane_v5",
        "core.domain_ledger",
        "core.domain_ledger_v3",
        "core.ledger_anchor",
        "core.mission_context_v4",
        "core.mission_evidence_v5",
        "core.native_vault",
        "core.workspaces",
    }
)
FLAG_SPECS = (
    (CONTROL_PLANE_FLAG, control_plane_v1_enabled, frozenset({"1", "true"})),
    (WORKSPACE_REGISTRY_FLAG, workspace_registry_enabled, frozenset({"1", "true"})),
    (M1B_BACKFILL_FLAG, m1b_backfill_enabled, frozenset({"1", "true"})),
    (M2A_DOMAIN_LEDGER_FLAG, m2a_domain_ledger_enabled, frozenset({"1", "true"})),
    (LEDGER_ANCHOR_FLAG, ledger_anchor_enabled, frozenset({"1", "true"})),
    (LEDGER_V3_FLAG, ledger_v3_enabled, frozenset({"1", "true"})),
    (
        CONTROL_PLANE_V4_FLAG,
        control_plane_v4_enabled,
        frozenset({"1", "true", "yes", "on"}),
    ),
    (CONTROL_PLANE_V5_FLAG, control_plane_v5_enabled, frozenset({"1", "true"})),
)


def _imports(path: Path) -> set[str]:
    """Return static and literal dynamic imports without importing the source."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    importlib_names = {"importlib"}
    import_module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                if alias.name == "importlib":
                    importlib_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module)
            if node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_names.add(alias.asname or alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        dynamic = (
            isinstance(function, ast.Name)
            and function.id in ({"__import__"} | import_module_names)
        ) or (
            isinstance(function, ast.Attribute)
            and function.attr == "import_module"
            and isinstance(function.value, ast.Name)
            and function.value.id in importlib_names
        )
        literal = node.args[0]
        if (
            dynamic
            and isinstance(literal, ast.Constant)
            and isinstance(literal.value, str)
        ):
            found.add(literal.value)
    return found


def verify_startup_boundary() -> dict[str, list[str]]:
    """Reject any startup import that would wire the default-off sidecars."""
    observed: dict[str, list[str]] = {}
    for path in STARTUP_SOURCES:
        resolved = path.resolve(strict=False)
        try:
            label = resolved.relative_to(PROJECT.resolve()).as_posix()
        except ValueError:
            label = resolved.as_posix()
        if not path.is_file():
            raise RuntimeError(f"missing startup source: {label}")
        imports = _imports(path)
        forbidden = sorted(
            module
            for module in imports
            if module in ENHANCED_MODULES
            or any(module.startswith(prefix + ".") for prefix in ENHANCED_MODULES)
        )
        if forbidden:
            raise RuntimeError(f"enhanced startup import in {label}: {forbidden}")
        observed[label] = sorted(imports)
    return observed


def verify_default_off(*, require_process_flags_off: bool) -> list[str]:
    """Prove every Phase 4 implementation flag has strict false defaults."""
    checked: list[str] = []
    for name, reader, accepted in FLAG_SPECS:
        if reader({}):
            raise RuntimeError(f"feature flag does not default off: {name}")
        for value in ("0", "false", "disabled", "2", "true-ish"):
            if reader({name: value}):
                raise RuntimeError(f"feature flag accepts an unknown value: {name}")
        for value in accepted:
            if not reader({name: value}):
                raise RuntimeError(
                    f"feature flag lost explicit opt-in semantics: {name}"
                )
        if require_process_flags_off and reader(os.environ):
            raise RuntimeError(f"feature flag is enabled in verifier process: {name}")
        checked.append(name)
    return checked


def verify_disabled_owner_write_boundary() -> str:
    """Exercise V1 rollback against a nonexistent isolated owner-like root."""
    with tempfile.TemporaryDirectory(prefix="onyx-p4-exit-") as temporary:
        root = Path(temporary) / "owner-data-must-not-exist"
        with patch(
            "core.control_plane.private_control_plane_runtime_dir", return_value=root
        ):
            store = ControlPlaneStore(enabled=False)
            try:
                store.initialize()
            except ControlPlaneDisabled:
                pass
            else:  # pragma: no cover - defensive fail-closed branch
                raise RuntimeError("disabled control plane initialized")
            finally:
                store.close()
        if root.exists():
            raise RuntimeError("disabled control plane wrote an owner-data path")
    return "disabled-v1-zero-owner-writes"


def verify_all(*, require_process_flags_off: bool = True) -> dict[str, object]:
    count, manifest_sha256 = verify_r10(R10_MANIFEST)
    imports = verify_startup_boundary()
    flags = verify_default_off(require_process_flags_off=require_process_flags_off)
    owner_write = verify_disabled_owner_write_boundary()
    return {
        "status": "P4_EXIT_CANDIDATE_SOURCE_OK",
        "r10_files": count,
        "r10_manifest_sha256": manifest_sha256,
        "flags_default_off": flags,
        "startup_sources": sorted(imports),
        "owner_write_probe": owner_write,
        "activation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--allow-enabled-process-flag",
        action="store_true",
        help="test default semantics but do not require the verifier process flags off",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the canonical JSON result to this evidence path",
    )
    args = parser.parse_args()
    result = verify_all(require_process_flags_off=not args.allow_enabled_process_flag)
    payload = json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload.encode("utf-8"))
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
