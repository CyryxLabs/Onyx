from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.runtime_distribution_inventory import (
    BundleInventoryError,
    _distribution_record,
    build_bundle_inventory,
    expected_runtime_identities,
    runtime_distribution_closure,
    write_bundle_inventory,
)


ROOT = Path(__file__).resolve().parents[1]


def _metadata_only_bundle(root: Path) -> Path:
    bundle = root / "Onyx"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (bundle / "Onyx.exe").write_bytes(b"MZinventory-fixture")
    for distribution in runtime_distribution_closure(ROOT / "requirements.txt"):
        source = Path(distribution._path) / "METADATA"  # type: ignore[attr-defined]
        target = internal / f"{distribution.metadata['Name']}-{distribution.version}.dist-info"
        target.mkdir()
        (target / "METADATA").write_bytes(source.read_bytes())
    return bundle


def test_runtime_closure_keeps_automation_but_excludes_optional_gpl_utility() -> None:
    identities = dict(expected_runtime_identities(ROOT / "requirements.txt"))
    assert "pyautogui" in identities
    assert "pyside6" in identities
    assert "mouseinfo" not in identities
    assert "pypiwin32" not in identities


def test_bundle_inventory_binds_exact_runtime_metadata_and_bytes(tmp_path: Path) -> None:
    bundle = _metadata_only_bundle(tmp_path)
    output = tmp_path / "bundle-inventory-Windows-test64.json"

    inventory = write_bundle_inventory(
        bundle=bundle,
        output=output,
        version="1.2.3",
        system="Windows",
        architecture="test64",
        requirements_path=ROOT / "requirements.txt",
    )

    assert inventory["contract"] == "OnyxBundleInventory.v1"
    assert inventory["runtimeDistributionCount"] == len(
        expected_runtime_identities(ROOT / "requirements.txt")
    )
    assert inventory["fileCount"] > inventory["runtimeDistributionCount"]
    assert json.loads(output.read_text(encoding="utf-8")) == inventory


def test_bundle_inventory_fails_closed_when_expected_metadata_is_missing(
    tmp_path: Path,
) -> None:
    bundle = _metadata_only_bundle(tmp_path)
    first = next(bundle.rglob("*.dist-info/METADATA"))
    first.unlink()

    with pytest.raises(BundleInventoryError, match="lacks runtime distribution metadata"):
        build_bundle_inventory(
            bundle=bundle,
            version="1.2.3",
            system="Windows",
            architecture="test64",
            requirements_path=ROOT / "requirements.txt",
        )


@pytest.mark.parametrize("legal_name", ["LICENSE.txt", "LICENCE.rst"])
def test_distribution_inventory_recognizes_both_license_spellings(
    tmp_path: Path,
    legal_name: str,
) -> None:
    bundle = tmp_path / "Onyx"
    metadata_dir = bundle / "_internal" / "example-1.0.dist-info"
    metadata_dir.mkdir(parents=True)
    metadata_path = metadata_dir / "METADATA"
    metadata_path.write_text(
        "Metadata-Version: 2.4\nName: example\nVersion: 1.0\nLicense: MIT\n",
        encoding="utf-8",
    )
    legal = metadata_dir / legal_name
    legal.write_text("authoritative legal bytes\n", encoding="utf-8")

    record = _distribution_record(metadata_path, bundle)

    assert [item["path"] for item in record["legalFiles"]] == [
        f"_internal/example-1.0.dist-info/{legal_name}"
    ]
