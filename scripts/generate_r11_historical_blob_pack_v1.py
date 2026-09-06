"""Generate the deterministic hermetic blob pack for retired R11 evidence."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RETIREMENT = ROOT / "tests/fixtures/r11_projection_retirement_v1.json"
RETIREMENT_SHA256 = (
    "4b87a75f4a4e882823b523d7a190d1eda91a034b295d48a6f0208dadc6f2bb07"
)
PHASE5_EXIT_RETIREMENT = ROOT / "tests/fixtures/phase5_exit_retirement_v1.json"
PHASE5_EXIT_RETIREMENT_SHA256 = (
    "23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997"
)
ARCHIVE = ROOT / "tests/fixtures/r11_historical_blobs_v1.zip"
MANIFEST = ROOT / "tests/fixtures/r11_historical_blob_pack_v1.json"
HEAD_FALLBACKS = {
    "actions/computer_control.py": (
        "79be91154318d954b32bb547370ad69fb1a25c513894feda5d492d4c85b135ac"
    ),
    "actions/computer_settings.py": (
        "a853aeafc96f516e2910484a0ce471de592d6bc7f9f0a08a88f47df7b655bc3a"
    ),
    "actions/screen_processor.py": (
        "b63cfd3ba8d6328f9271ae12c7f10464064f1adcce32289a4d3b00098c1bbef7"
    ),
    "actions/send_message.py": (
        "73cd12826016876a29bd226591974d1771b69d668d0309f07ed29a8bf7e735e7"
    ),
    "core/audio_contract.py": (
        "133d72bad448d99eabcd7d8909478a69b7e6580c81e814bca8f2b8e282c3f27a"
    ),
    "core/domain_ledger.py": (
        "2b0286405c85cde53a78ceb8ebe98c19c358b24641a5b526f8f419bb4c00db8d"
    ),
    "core/paths.py": (
        "8aa7600c18e2721594e04de54c27ddeed4c6344576468b25dc5e8a0afddb0b1b"
    ),
    "core/tool_audit.py": (
        "13fd34a5b07bfefb4dc8a973a237b784a1e751e48c3ae68f7ace3ad97ae5b447"
    ),
    "core/tts.py": (
        "e19bd304e3d673273b334c7465cf26bd5fb12a7d2fc734708819bb5d12aa5527"
    ),
    "core/version.py": (
        "5fa557e88e80da35c22ab75f01eb1d1ec356be53f05e5d646e391af7002d8d17"
    ),
    "docs/onyx/APPROVAL_POLICY.md": (
        "45f2b50a86911b599ac1e4536fa99af9ba1daec00f90a79c5fe2a16711974a32"
    ),
    "docs/onyx/DATA_AND_MEMORY_BOUNDARIES.md": (
        "94d5c468879ffed66fec08552514a97276604b07809a02fb0e823702ead86ed6"
    ),
    "packaging/macos/entitlements.plist": (
        "3c70bd8a436460de7e999674c5c924231cbfb4f7d142ff7b1a94f9ee772144b4"
    ),
    "scripts/check_release_eligibility.py": (
        "8a762c3e679f108f3c1a166f3820c4aafe0f774a8bd9d37e319ae47e576917a7"
    ),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_blob(oid: str) -> bytes:
    kind = subprocess.run(
        ["git", "cat-file", "-t", oid],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if kind != "blob":
        raise RuntimeError(f"R11 object is not a blob: {oid}")
    return subprocess.run(
        ["git", "cat-file", "blob", oid],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def generate() -> dict[str, object]:
    raw = RETIREMENT.read_bytes()
    if _sha(raw) != RETIREMENT_SHA256:
        raise RuntimeError("R11 retirement record drifted")
    record = json.loads(raw.decode("utf-8"))
    expected: dict[str, str] = {}
    for entry in (
        list(record["implementation_successors"])
        + [
            item
            for item in record["projections"]
            if item["state"] == "recoverable-exact"
        ]
    ):
        oid = entry["git_blob_oid"]
        digest = entry["historical_sha256"]
        prior = expected.setdefault(oid, digest)
        if prior != digest:
            raise RuntimeError(f"R11 blob digest conflict: {oid}")

    exit_raw = PHASE5_EXIT_RETIREMENT.read_bytes()
    if _sha(exit_raw) != PHASE5_EXIT_RETIREMENT_SHA256:
        raise RuntimeError("Phase 5 Exit retirement record drifted")
    exit_record = json.loads(exit_raw.decode("utf-8"))
    head_expectations = dict(HEAD_FALLBACKS)
    for entry in exit_record["bindings"]:
        if entry["state"] != "recoverable-exact":
            continue
        relative = entry["path"]
        digest = entry["historical_sha256"]
        prior = head_expectations.setdefault(relative, digest)
        if prior != digest:
            raise RuntimeError(f"historical HEAD digest conflict: {relative}")

    head_files: list[dict[str, object]] = []
    for relative, digest in sorted(head_expectations.items()):
        oid = subprocess.run(
            ["git", "rev-parse", f"HEAD:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        prior = expected.setdefault(oid, digest)
        if prior != digest:
            raise RuntimeError(f"R11 HEAD digest conflict: {relative}")
        head_files.append({"path": relative, "oid": oid, "sha256": digest})

    blobs: dict[str, bytes] = {}
    entries: list[dict[str, object]] = []
    for oid, digest in sorted(expected.items()):
        data = _git_blob(oid)
        computed_oid = hashlib.sha1(
            f"blob {len(data)}\0".encode("ascii") + data,
            usedforsecurity=False,
        ).hexdigest()
        if computed_oid != oid or _sha(data) != digest:
            raise RuntimeError(f"R11 historical blob drifted: {oid}")
        blobs[oid] = data
        entries.append({"oid": oid, "sha256": digest, "size": len(data)})

    temporary = ARCHIVE.with_suffix(".zip.tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
        for oid, data in sorted(blobs.items()):
            info = zipfile.ZipInfo(f"blobs/{oid}.blob", (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)
    temporary.replace(ARCHIVE)
    archive_sha = _sha(ARCHIVE.read_bytes())
    manifest = {
        "schema": "onyx.test.r11-historical-blob-pack.v1",
        "retirement_record_sha256": RETIREMENT_SHA256,
        "phase5_exit_retirement_record_sha256": PHASE5_EXIT_RETIREMENT_SHA256,
        "archive": {
            "path": ARCHIVE.relative_to(ROOT).as_posix(),
            "sha256": archive_sha,
            "size": ARCHIVE.stat().st_size,
        },
        "blobs": entries,
        "head_files": head_files,
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


if __name__ == "__main__":
    result = generate()
    print(
        json.dumps(
            {
                "archive_sha256": result["archive"]["sha256"],
                "blob_count": len(result["blobs"]),
                "manifest_sha256": _sha(MANIFEST.read_bytes()),
            },
            sort_keys=True,
        )
    )
