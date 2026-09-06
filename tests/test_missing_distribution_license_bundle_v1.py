from __future__ import annotations

import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import missing_distribution_license_bundle as bundle
from scripts import build_release


def _tar(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return output.getvalue()


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_specs_pin_exact_artifacts_and_preserve_every_ambiguity() -> None:
    assert {item.name for item in bundle.SPECS} == {
        "odfpy",
        "WMI",
        "PyGetWindow",
        "win10toast",
    }
    assert all(len(item.artifact_sha256) == 64 for item in bundle.SPECS)
    decisions = " ".join(item.decision for item in bundle.SPECS)
    assert "DUAL_LICENSE" in decisions
    assert "FULL_PERMISSION_TEXT_ABSENT" in decisions
    assert "UNTAGGED_REPOSITORY" in decisions
    assert "BSD_MIT_CONFLICT" in decisions
    odfpy = next(item for item in bundle.SPECS if item.name == "odfpy")
    assert odfpy.include_artifact is True
    assert odfpy.supplemental_filename == "LGPL-2.1.txt"
    assert odfpy.supplemental_sha256 == (
        "20e50fe7aae3e56378ebf0417d9de904f55a0e61e4df315333e632a4d3555d95"
    )
    assert odfpy.local_supplemental_path == (
        "packaging/legal-supplements/LGPL-2.1.txt"
    )
    assert "odfpy-1.4.1/odf/element.py" in odfpy.members
    assert "odfpy-1.4.1/odf/grammar.py" in odfpy.members


def test_formal_build_wires_inventory_and_per_distribution_notice() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts/build_release.py").read_text(encoding="utf-8")
    assert "generate_missing_distribution_license_bundle" in source
    assert "missing-distribution-evidence-v1" in source
    assert "NOTICE-ONYX-SUPPLEMENTAL-LEGAL-EVIDENCE.txt" in source
    assert "This technical evidence is not a legal approval." in source


def test_packaged_notice_resolution_allows_platform_absence_but_not_drift() -> None:
    assert (
        build_release._resolve_packaged_supplemental_metadata(
            {},
            name="WMI",
            version="1.5.1",
        )
        is None
    )
    expected = Path("_internal/WMI-1.5.1.dist-info")
    metadata = {"wmi": [expected]}
    assert build_release._resolve_packaged_supplemental_metadata(
        metadata,
        name="WMI",
        version="1.5.1",
    ) == expected

    with pytest.raises(RuntimeError, match="metadata is not unique"):
        build_release._resolve_packaged_supplemental_metadata(
            {"wmi": [Path("_internal/WMI-2.0.dist-info")]},
            name="WMI",
            version="1.5.1",
        )
    with pytest.raises(RuntimeError, match="metadata is not unique"):
        build_release._resolve_packaged_supplemental_metadata(
            {"wmi": [expected, Path("other/WMI-1.5.1.dist-info")]},
            name="WMI",
            version="1.5.1",
        )


def test_generator_emits_exact_members_and_unapproved_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specifications = (
        bundle.LicenseEvidenceSpecV1(
            "Example",
            "1.0",
            "Example-1.0.tar.gz",
            "0" * 64,
            ("Example-1.0/LICENSE",),
            "REVIEW_CONFLICT",
            "https://raw.githubusercontent.com/example/repo/commit/LICENSE",
            hashlib.sha256(b"supplement").hexdigest(),
            "EXACT-LICENSE-SUPPLEMENT.txt",
            True,
            True,
        ),
    )
    artifact = _tar({"Example-1.0/LICENSE": b"exact-license"})
    specifications = (
        bundle.LicenseEvidenceSpecV1(
            **{**specifications[0].__dict__, "artifact_sha256": hashlib.sha256(artifact).hexdigest()}
        ),
    )
    monkeypatch.setattr(bundle, "SPECS", specifications)

    def fetch(url: str, _maximum: int) -> bytes:
        if url.endswith("/json"):
            return json.dumps(
                {
                    "urls": [
                        {
                            "filename": "Example-1.0.tar.gz",
                            "digests": {"sha256": hashlib.sha256(artifact).hexdigest()},
                            "url": "https://files.pythonhosted.org/example.tar.gz",
                        }
                    ]
                }
            ).encode()
        if url.startswith("https://files.pythonhosted.org/"):
            return artifact
        return b"supplement"

    report = bundle.generate_missing_distribution_license_bundle(
        tmp_path / "licenses", fetch=fetch
    )
    assert report["legalDecision"] == "REQUIRED"
    assert report["packages"][0]["decision"] == "REVIEW_CONFLICT"
    assert (tmp_path / "licenses/Example-1.0/LICENSE").read_bytes() == b"exact-license"
    assert (tmp_path / "licenses/Example-1.0/Example-1.0.tar.gz").read_bytes() == artifact
    assert (
        tmp_path
        / "licenses/Example-1.0/EXACT-LICENSE-SUPPLEMENT.txt"
    ).read_bytes() == b"supplement"
    files = report["packages"][0]["files"]
    assert next(item for item in files if item["name"] == "Example-1.0.tar.gz")[
        "correspondingSource"
    ] is True
    assert next(item for item in files if item["name"] == "EXACT-LICENSE-SUPPLEMENT.txt")[
        "exactVersionBinding"
    ] is True


def test_generator_rejects_archive_traversal_before_output_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact = _tar({"../LICENSE": b"unsafe"})
    spec = bundle.LicenseEvidenceSpecV1(
        "Unsafe",
        "1.0",
        "Unsafe-1.0.tar.gz",
        hashlib.sha256(artifact).hexdigest(),
        ("Unsafe-1.0/LICENSE",),
        "REQUIRED",
    )
    monkeypatch.setattr(bundle, "SPECS", (spec,))

    def fetch(url: str, _maximum: int) -> bytes:
        if url.endswith("/json"):
            return json.dumps(
                {
                    "urls": [
                        {
                            "filename": spec.filename,
                            "digests": {"sha256": spec.artifact_sha256},
                            "url": "https://files.pythonhosted.org/unsafe.tar.gz",
                        }
                    ]
                }
            ).encode()
        return artifact

    with pytest.raises(bundle.MissingDistributionLicenseError, match="unsafe path"):
        bundle.generate_missing_distribution_license_bundle(
            tmp_path / "licenses", fetch=fetch
        )


def test_generator_uses_hash_pinned_local_supplement_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "LOCAL-LICENSE.txt"
    local.write_bytes(b"local supplement")
    artifact = _tar({"Example-1.0/LICENSE": b"exact-license"})
    spec = bundle.LicenseEvidenceSpecV1(
        "Example",
        "1.0",
        "Example-1.0.tar.gz",
        hashlib.sha256(artifact).hexdigest(),
        ("Example-1.0/LICENSE",),
        "REVIEW_CONFLICT",
        "https://www.gnu.org/licenses/example.txt",
        hashlib.sha256(b"local supplement").hexdigest(),
        local_supplemental_path=str(local),
    )
    monkeypatch.setattr(bundle, "SPECS", (spec,))

    def fetch(url: str, _maximum: int) -> bytes:
        if url.endswith("/json"):
            return json.dumps(
                {
                    "urls": [
                        {
                            "filename": spec.filename,
                            "digests": {"sha256": spec.artifact_sha256},
                            "url": "https://files.pythonhosted.org/example.tar.gz",
                        }
                    ]
                }
            ).encode()
        if url.startswith("https://files.pythonhosted.org/"):
            return artifact
        raise AssertionError("local supplement unexpectedly used the network")

    report = bundle.generate_missing_distribution_license_bundle(
        tmp_path / "licenses", fetch=fetch
    )
    assert (tmp_path / "licenses/Example-1.0/UNTAGGED-REPOSITORY-LICENSE-SUPPLEMENT.txt").read_bytes() == b"local supplement"
    assert "hash-pinned local release input" in report["packages"][0]["files"][-1]["source"]


def test_zip_reader_rejects_duplicate_paths() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w") as archive:
        archive.writestr("dist/METADATA", b"one")
        archive.writestr("DIST/metadata", b"two")
    with pytest.raises(bundle.MissingDistributionLicenseError, match="duplicate"):
        bundle._zip_members(output.getvalue())
