from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.generate_final_qualification_provenance_v1 import (
    QualificationProvenanceError,
    generate_provenance,
)
from scripts.prepare_qualification_artifacts_v1 import (
    QualificationArtifactError,
    resolve_inputs,
)


def _write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )


def _windows_release(root: Path, version: str, *, formal: bool = True) -> None:
    root.mkdir()
    setup = root / f"Onyx-{version}-Windows-x64-Setup.exe"
    portable = root / f"Onyx-{version}-Windows-x64-Portable.zip"
    setup.write_bytes(f"setup-{version}".encode())
    portable.write_bytes(f"portable-{version}".encode())
    records = [
        {
            "name": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for path in (portable, setup)
    ]
    _write(
        root / "release-manifest-Windows-x64.json",
        {
            "architecture": "x64",
            "artifacts": records,
            "build_input_seal": {"manifest_sha256": "a" * 64},
            "bundle_inventory": {"bundle_root_sha256": "b" * 64},
            "diagnostic_exceptions": [] if formal else ["unsigned"],
            "product": "Onyx",
            "release_class": "formal" if formal else "untrusted-candidate",
            "system": "Windows",
            "version": version,
        },
    )
    _write(
        root / "windows-release-evidence-x64.json",
        {
            "all_trusted": True,
            "contract": "onyx.windows-release-evidence.v1",
            "formal": True,
            "signer_thumbprint": "A" * 40,
        },
    )
    (root / "SBOM-Windows-x64.spdx.json").write_bytes(b"sbom")


def test_resolver_binds_current_prior_portable_signer_and_sbom(tmp_path: Path) -> None:
    current = tmp_path / "current"
    prior = tmp_path / "prior"
    _windows_release(current, "1.2.3")
    _windows_release(prior, "1.2.2")
    result = resolve_inputs(
        current_dir=current,
        prior_dir=prior,
        system="Windows",
        architecture="x64",
        current_version="1.2.3",
        prior_version="1.2.2",
    )
    assert result["current_artifact"].endswith("1.2.3-Windows-x64-Setup.exe")
    assert result["prior_artifact"].endswith("1.2.2-Windows-x64-Setup.exe")
    assert result["current_portable_sha256"] == hashlib.sha256(
        b"portable-1.2.3"
    ).hexdigest()
    assert result["current_signer_thumbprint"] == "A" * 40
    assert result["sbom_sha256"] == hashlib.sha256(b"sbom").hexdigest()


def test_resolver_rejects_downloaded_artifact_drift(tmp_path: Path) -> None:
    current = tmp_path / "current"
    prior = tmp_path / "prior"
    _windows_release(current, "1.2.3")
    _windows_release(prior, "1.2.2")
    (current / "Onyx-1.2.3-Windows-x64-Setup.exe").write_bytes(b"tampered")
    with pytest.raises(QualificationArtifactError, match="artifact bytes drifted"):
        resolve_inputs(
            current_dir=current,
            prior_dir=prior,
            system="Windows",
            architecture="x64",
            current_version="1.2.3",
            prior_version="1.2.2",
        )


def test_provenance_requires_formal_exact_artifact_bytes(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _windows_release(release, "1.2.3")
    sbom = release / "SBOM.spdx.json"
    sbom.write_bytes(b"aggregate-sbom")
    sbom_sha = hashlib.sha256(sbom.read_bytes()).hexdigest()
    (release / "SBOM.spdx.json.sha256").write_text(
        f"{sbom_sha}  SBOM.spdx.json\n", encoding="utf-8", newline="\n"
    )
    result = generate_provenance(
        release_dir=release,
        version="1.2.3",
        required_targets=("Windows-x64",),
        build_run_id="18",
        build_sha="b" * 40,
        qualification_run_id="19",
        qualification_sha="c" * 40,
    )
    assert result["build"] == {"run_id": "18", "workflow_sha": "b" * 40}
    assert result["targets"] == ["Windows-x64"]
    assert result["aggregate_sbom"]["sha256"] == sbom_sha
    (release / "Onyx-1.2.3-Windows-x64-Portable.zip").write_bytes(b"tampered")
    with pytest.raises(QualificationProvenanceError, match="artifact bytes drifted"):
        generate_provenance(
            release_dir=release,
            version="1.2.3",
            required_targets=("Windows-x64",),
            build_run_id="18",
            build_sha="b" * 40,
            qualification_run_id="19",
            qualification_sha="c" * 40,
        )


def test_provenance_rejects_aggregate_sbom_drift(tmp_path: Path) -> None:
    release = tmp_path / "release"
    _windows_release(release, "1.2.3")
    sbom = release / "SBOM.spdx.json"
    sbom.write_bytes(b"aggregate-sbom")
    sbom_sha = hashlib.sha256(sbom.read_bytes()).hexdigest()
    (release / "SBOM.spdx.json.sha256").write_text(
        f"{sbom_sha}  SBOM.spdx.json\n", encoding="utf-8", newline="\n"
    )
    generate_provenance(
        release_dir=release,
        version="1.2.3",
        required_targets=("Windows-x64",),
        build_run_id="18",
        build_sha="b" * 40,
        qualification_run_id="19",
        qualification_sha="c" * 40,
    )
    sbom.write_bytes(b"post-build-regeneration")
    with pytest.raises(QualificationProvenanceError, match="digest drifted"):
        generate_provenance(
            release_dir=release,
            version="1.2.3",
            required_targets=("Windows-x64",),
            build_run_id="18",
            build_sha="b" * 40,
            qualification_run_id="19",
            qualification_sha="c" * 40,
        )
