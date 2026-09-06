"""Verify the integrity-only anchor for current Live Activation V15 bytes."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
from typing import Final


ROOT: Final = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID: Final = "VE-ONYX-LIVE-ACTIVATION-V15-CURRENT-SOURCE-002"
MANIFEST_RELATIVE: Final = (
    f"docs/onyx/acceptance/{ACCEPTANCE_ID}.manifest.json"
)
MANIFEST_SHA256: Final = (
    "908eca8bc9b38318ec507ad90be5cb9cc5645caa80b98660301f53edf18ef030"
)
SOURCE_SHA256: Final = (
    "8b0fdf50dfd2884a7015a91120cd8b9097c6fd320d30ec811a2df0ec6e38e80b"
)
PREDECESSOR_MANIFEST: Final = (
    "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V15-CURRENT-SOURCE-001.manifest.json"
)
PREDECESSOR_SHA256: Final = (
    "b43d50754382b4e4465c190776ef4564666d9ac25efb35ccd23db7c419c877d6"
)


class LiveActivationV15SourceAnchorError(RuntimeError):
    """The current V15 source identity anchor is invalid."""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _regular(project: Path, relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise LiveActivationV15SourceAnchorError("anchor path is noncanonical")
    root = project.resolve(strict=True)
    current = root
    for part in parsed.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise LiveActivationV15SourceAnchorError(
                f"anchor path is unavailable: {relative}"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise LiveActivationV15SourceAnchorError(
                f"anchor path uses a symlink: {relative}"
            )
        try:
            current.resolve(strict=True).relative_to(root)
        except (OSError, ValueError) as exc:
            raise LiveActivationV15SourceAnchorError(
                f"anchor path leaves the project: {relative}"
            ) from exc
    if not stat.S_ISREG(current.lstat().st_mode):
        raise LiveActivationV15SourceAnchorError(
            f"anchor leaf is not a regular file: {relative}"
        )
    return current


def _load(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveActivationV15SourceAnchorError("anchor manifest is invalid") from exc
    if type(value) is not dict:
        raise LiveActivationV15SourceAnchorError("anchor manifest must be an object")
    return value


def verify(
    project: Path = ROOT,
    *,
    require_installed: bool = False,
) -> dict[str, object]:
    project = Path(project)
    manifest_path = _regular(project, MANIFEST_RELATIVE)
    if digest(manifest_path) != MANIFEST_SHA256:
        raise LiveActivationV15SourceAnchorError("anchor manifest digest drifted")
    manifest = _load(manifest_path)
    if (
        manifest.get("schema") != "onyx.source-identity-acceptance.v2"
        or manifest.get("acceptance_id") != ACCEPTANCE_ID
        or manifest.get("decision") != "authenticated_source_identity_only"
        or manifest.get("accepted_scope") != "current_source_byte_identity_only"
    ):
        raise LiveActivationV15SourceAnchorError("anchor manifest identity drifted")

    source = manifest.get("source")
    record = manifest.get("record")
    continuity = manifest.get("continuity")
    if type(source) is not dict or type(record) is not dict or type(continuity) is not dict:
        raise LiveActivationV15SourceAnchorError("anchor manifest records are malformed")
    predecessor_path = _regular(project, PREDECESSOR_MANIFEST)
    if (
        manifest.get("predecessor")
        != {"path": PREDECESSOR_MANIFEST, "sha256": PREDECESSOR_SHA256}
        or digest(predecessor_path) != PREDECESSOR_SHA256
    ):
        raise LiveActivationV15SourceAnchorError("anchor predecessor drifted")
    source_path = _regular(project, str(source.get("path", "")))
    record_path = _regular(project, str(record.get("path", "")))
    if (
        source != {
            "path": "core/onyx_live_activation_v15.py",
            "size": 52463,
            "sha256": SOURCE_SHA256,
        }
        or source_path.stat().st_size != source["size"]
        or digest(source_path) != source["sha256"]
        or record_path.stat().st_size != record.get("size")
        or digest(record_path) != record.get("sha256")
    ):
        raise LiveActivationV15SourceAnchorError("anchored source or record drifted")
    if continuity != {
        "canonical_installed_version": "1.1.9",
        "canonical_installed_source_match": True,
        "canonical_installed_source_sha256": SOURCE_SHA256,
        "prior_1_1_8_manifest_sha256": PREDECESSOR_SHA256,
        "historical_acceptance_reused": False,
    }:
        raise LiveActivationV15SourceAnchorError("anchor continuity record drifted")
    if manifest.get("unclaimed") != [
        "functional_acceptance",
        "security_acceptance",
        "cross_platform_parity",
        "release_readiness",
        "project_completion",
    ]:
        raise LiveActivationV15SourceAnchorError("anchor scope was widened")

    installed_verified = False
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        installed = (
            Path(local)
            / "Programs/Cyryx Labs/Onyx/_internal/core/onyx_live_activation_v15.py"
        )
        if installed.is_file() and not installed.is_symlink():
            if installed.stat().st_size != source["size"] or digest(installed) != SOURCE_SHA256:
                raise LiveActivationV15SourceAnchorError(
                    "canonical installed V15 source differs from the anchor"
                )
            installed_verified = True
    if require_installed and not installed_verified:
        raise LiveActivationV15SourceAnchorError(
            "canonical installed V15 source is unavailable"
        )
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "source_sha256": SOURCE_SHA256,
        "installed_payload_verified": installed_verified,
        "scope": "current_source_byte_identity_only",
        "functional_acceptance": False,
    }


if __name__ == "__main__":
    print(
        "ONYX_LIVE_ACTIVATION_V15_CURRENT_SOURCE_OK",
        json.dumps(verify(), sort_keys=True),
    )
