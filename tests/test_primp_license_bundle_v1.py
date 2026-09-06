from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from scripts import primp_license_bundle as bundle


def _tar_payload(entries: list[tuple[str, bytes, str]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, data, kind in entries:
            member = tarfile.TarInfo(name)
            if kind == "file":
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
            elif kind == "symlink":
                member.type = tarfile.SYMTYPE
                member.linkname = "target"
                archive.addfile(member)
            else:
                raise AssertionError(kind)
    return output.getvalue()


def test_target_triples_cover_all_release_architectures() -> None:
    assert bundle.target_triple("Windows", "x64") == "x86_64-pc-windows-msvc"
    assert bundle.target_triple("Linux", "arm64") == "aarch64-unknown-linux-gnu"
    assert bundle.target_triple("Darwin", "x86_64") == "x86_64-apple-darwin"
    with pytest.raises(bundle.PrimpLicenseBundleError, match="unsupported"):
        bundle.target_triple("Plan9", "x64")


def test_sdist_extraction_rejects_links(tmp_path: Path) -> None:
    payload = _tar_payload(
        [(f"primp-{bundle.PRIMP_VERSION}/unsafe", b"", "symlink")]
    )
    with pytest.raises(bundle.PrimpLicenseBundleError, match="links"):
        bundle._safe_extract_sdist(payload, tmp_path / "source")


def test_selected_graph_excludes_dev_only_edges() -> None:
    root = "path+file:///source/primp-python#1.3.1"
    normal = "registry+https://example.invalid#normal@1.0.0"
    build = "registry+https://example.invalid#build@1.0.0"
    dev = "registry+https://example.invalid#dev@1.0.0"
    metadata = {
        "packages": [
            {"id": root, "name": "primp-python", "version": "1.3.1", "source": None},
            {"id": normal, "name": "normal", "version": "1.0.0", "source": "registry+x"},
            {"id": build, "name": "build", "version": "1.0.0", "source": "registry+x"},
            {"id": dev, "name": "dev", "version": "1.0.0", "source": "registry+x"},
        ],
        "resolve": {
            "nodes": [
                {
                    "id": root,
                    "deps": [
                        {"pkg": normal, "dep_kinds": [{"kind": None}]},
                        {"pkg": build, "dep_kinds": [{"kind": "build"}]},
                        {"pkg": dev, "dep_kinds": [{"kind": "dev"}]},
                    ],
                },
                {"id": normal, "deps": []},
                {"id": build, "deps": []},
                {"id": dev, "deps": []},
            ]
        },
    }

    assert bundle._selected_package_ids(metadata) == {root, normal, build}


def test_cargo_metadata_decodes_the_utf8_json_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cargo = tmp_path / "cargo.exe"
    cargo.write_bytes(b"cargo")
    root = tmp_path / "source"
    (root / "crates" / "primp-python").mkdir(parents=True)
    (root / "crates" / "primp-python" / "Cargo.toml").write_text(
        "[package]\nname='primp-python'\nversion='1.3.1'\n",
        encoding="utf-8",
    )
    observed: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.update(kwargs)
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=json.dumps({"packages": [], "resolve": {}}),
            stderr="",
        )

    monkeypatch.setattr(bundle.shutil, "which", lambda _name: str(cargo))
    monkeypatch.setattr(bundle.subprocess, "run", fake_run)

    result = bundle._cargo_metadata(
        root,
        tmp_path / "cargo-home",
        "x86_64-pc-windows-msvc",
    )

    assert result == {"packages": [], "resolve": {}}
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "strict"


def test_release_build_wires_native_primp_license_evidence() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "build_release.py").read_text(
        encoding="utf-8"
    )
    assert "generate_primp_license_bundle" in source
    assert "NOTICE-ONYX-NATIVE-CRATES.txt" in source
    assert "packaged primp distribution metadata is not unique" in source
