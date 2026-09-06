from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_lifecycle_uses_canonical_product_version() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    imports_canonical_version = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "core.version"
        and any(alias.name == "__version__" for alias in node.names)
        for node in tree.body
    )
    assert imports_canonical_version

    lifecycle_versions = [
        keyword.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "InstallerLifecycleServer"
        for keyword in node.keywords
        if keyword.arg == "version"
    ]
    assert len(lifecycle_versions) == 1
    assert isinstance(lifecycle_versions[0], ast.Name)
    assert lifecycle_versions[0].id == "__version__"
