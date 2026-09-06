"""Self-tests for the immutable P4.4 source-universe verifier."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import verify_p44_scope as verifier


def _records() -> dict[str, str]:
    return {
        relative: hashlib.sha256((verifier.PROJECT / relative).read_bytes()).hexdigest()
        for relative in verifier.expected_scope()
    }


def _write_manifest(path: Path, records: dict[str, str]) -> None:
    body = "".join(
        f"{digest} *{relative}\n"
        for relative, digest in sorted(records.items())
    )
    path.write_bytes(body.encode("utf-8"))


@pytest.fixture(scope="module")
def current_records() -> dict[str, str]:
    return _records()


@pytest.mark.parametrize("removed", ["main.py", "ui.py", "dashboard/server.py"])
def test_mandatory_product_source_removal_fails(
    tmp_path: Path, removed: str, current_records: dict[str, str]
) -> None:
    records = dict(current_records)
    assert records.pop(removed)
    manifest = tmp_path / "missing.sha256"
    _write_manifest(manifest, records)

    with pytest.raises(RuntimeError, match="manifest closure mismatch"):
        verifier.verify(manifest)


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ('__import__("dynamic_builtin_target")\n', "dynamic_builtin_target.py"),
        (
            'import importlib as loader\nloader.import_module("dynamic_importlib_target")\n',
            "dynamic_importlib_target.py",
        ),
    ],
)
def test_literal_dynamic_import_target_removal_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    target: str,
) -> None:
    for relative in verifier.PRODUCT_PYTHON_DIRS:
        package = tmp_path / relative
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "ui.py").write_text("", encoding="utf-8")
    entry = tmp_path / "tests" / "dynamic_entry.py"
    entry.write_text(source, encoding="utf-8")
    verifier_test = tmp_path / "tests" / "test_verify_p44_scope.py"
    verifier_test.write_text("", encoding="utf-8")
    dynamic_target = tmp_path / target
    dynamic_target.write_text("VALUE = True\n", encoding="utf-8")
    verifier_source = tmp_path / "scripts" / "verify_p44_scope.py"
    verifier_source.write_text("", encoding="utf-8")

    monkeypatch.setattr(verifier, "PROJECT", tmp_path)
    monkeypatch.setattr(verifier, "SELF", verifier_source)
    monkeypatch.setattr(
        verifier,
        "FOCUSED_TESTS",
        frozenset({"tests/dynamic_entry.py", "tests/test_verify_p44_scope.py"}),
    )
    monkeypatch.setattr(verifier, "RUNTIME_INPUTS", frozenset())

    records = _records()
    assert target in records
    records.pop(target)
    manifest = tmp_path / "missing-dynamic.sha256"
    _write_manifest(manifest, records)

    with pytest.raises(RuntimeError, match="manifest closure mismatch"):
        verifier.verify(manifest)


def test_unexpected_manifest_path_fails(
    tmp_path: Path, current_records: dict[str, str]
) -> None:
    records = dict(current_records)
    records["unexpected.py"] = "0" * 64
    manifest = tmp_path / "extra.sha256"
    _write_manifest(manifest, records)

    with pytest.raises(RuntimeError, match="manifest closure mismatch"):
        verifier.verify(manifest)


def test_digest_mismatch_fails(
    tmp_path: Path, current_records: dict[str, str]
) -> None:
    records = dict(current_records)
    records["main.py"] = "0" * 64
    manifest = tmp_path / "mismatch.sha256"
    _write_manifest(manifest, records)

    with pytest.raises(RuntimeError, match="manifest digest mismatch: main.py"):
        verifier.verify(manifest)
