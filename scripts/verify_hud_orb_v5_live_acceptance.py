"""Verify the independent freeze of Onyx HUD / Orb V5 Live Candidate 003."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


PROJECT = Path(__file__).resolve().parents[1]
ACCEPTANCE_ID = "VE-HUD-ORB-V5-LIVE-E6-001"
ACCEPTANCE_RECORD = f"docs/onyx/acceptance/{ACCEPTANCE_ID}.md"
ACCEPTANCE_MANIFEST = "docs/onyx/VE-ACCEPTANCE-HUD-ORB-V5-LIVE-E6-001.sha256"
ACCEPTANCE_MARKER = "HUD_ORB_V5_LIVE_ACCEPTANCE_OK"

CANDIDATE_MANIFEST = "docs/onyx/checkpoints/hud-orb-v5-live/manifest.json"
CANDIDATE_CHECKPOINT = (
    "docs/onyx/checkpoints/hud-orb-v5-live/"
    "ONYX_HUD_ORB_V5_LIVE_CHECKPOINT.md"
)
CANDIDATE_MANIFEST_SHA256 = (
    "1b5415c70322cbdbb315046b7ef2a772c16d53a2db0ab326739265fd0d52152a"
)
CANDIDATE_CHECKPOINT_SHA256 = (
    "fd482f6cbc4d4dba849d980ccc3aa6d83f6a9e7b67b691e5df489fe28c729f9f"
)

CANDIDATE_FILES = {
    "ui.py": (164744, "e5768626b7eb9d162a54cd67b08b5cb7d9685fb5c0e1b8c951843a1146fc252b"),
    "dashboard/static/app.html": (34050, "c9c25ff774b81a3a32c9897c1307ebec74cd09e08cb92db834fbb02017669fd0"),
    "dashboard/static/login.html": (9197, "d05d3440bf9bee917dd794cbd4dfda3f19e44227fc86c59040f366a052184968"),
    "qml/OnyxLiveShellV5.qml": (13647, "9ff4d3d5d3771d1bbf2c2f8fe68793fd05e8cc80fd0c0644d700596d7cd39e47"),
    "qml/components/OnyxOrbCinematicV5.qml": (6357, "adff9ee062fff1c735bd28d4a77591581b6e4ce131067b1724699da5055e2622"),
    "qml/assets/onyx-orb-cinematic-v3.png": (1333775, "44668e57df10b4b47516cf7b35238ced7803523c76ea264a2045bdb35b174de1"),
    "tests/test_onyx_hud_v3_live_integration.py": (1584, "7d06410745d34561b6fc309c6ff6ebdc6056962e68240667f69f3eaba9592e00"),
    "tests/test_onyx_hud_v4_live_integration.py": (1615, "1270150def53c32661d8b9daa212a40cf8b8fe60221bf5b643fa8d7a734693ec"),
    "tests/test_onyx_hud_v5_live_integration.py": (14095, "93c3854d866d739adb261cfb241a40d20d34f25a22747f89b049a5c21caf5cfc"),
    "packaging/onyx.spec": (3034, "2ab5ade541b6cd8b9c6edcd52320535d7cad912d150169156810330c577506b3"),
    "scripts/build_release.py": (11733, "1d06830f743c818fb89fc6571efa971a35a9a46f005661b4d9cb6c6e6ab2c5e3"),
    "docs/onyx/checkpoints/hud-orb-v4-live/REJECTED.md": (526, "efff92bcecfc04770db135a19edc8c6846f5d8e0a3be34ac201e6e0d26e8fc92"),
    "docs/onyx/checkpoints/hud-orb-v4-live/candidate-002-snapshot/docs/onyx/checkpoints/hud-orb-v4-live/onyx-hud-v4-d3d11.png": (501346, "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1"),
}

ACCEPTED_V3_ANCHORS = {
    "core/render_governor_v3.py": (672, "ee1f2145eb90e930e1663287bc0e71ff6f0809b9b4bce18e445c2f47e80d1de8"),
    "core/ui_projection_v3.py": (3775, "cfbcc566dbcb5bd423b31571ef914bb24f389621c781d1edf05a02fd0792b7d2"),
    "qml/OnyxShellV3.qml": (4878, "4f450c9ff7b2a9926925273a29fb8cc77533576073f2015be3f87b450c180eac"),
    "tests/test_onyx_hud_v3.py": (8188, "928e92c25be8218ef83d2dbf035330c0017eef9bb03bfd2a737cbb82e39b5b9f"),
}

BOUNDARY_ANCHORS = {
    "main.py": "6b82fed0d7c932a08d2d1f8a31d7650a1b235d55085ee608fdbb7651e5f49712",
    "core/permission_broker.py": "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250",
    "dashboard/server.py": "4d3142dc9c6a78cfe76f804de2b154334da2d7790484783a993babc92300bae1",
}

SNAPSHOT_ROOT = "docs/onyx/checkpoints/hud-orb-v4-live/candidate-002-snapshot"
RETIREMENT_LEDGER = (
    "docs/onyx/checkpoints/HUD_REJECTED_CANDIDATES_RETIREMENT_V1.json"
)
REJECTED_SNAPSHOT_FILES = {
    "dashboard/static/app.html": (34050, "c9c25ff774b81a3a32c9897c1307ebec74cd09e08cb92db834fbb02017669fd0"),
    "dashboard/static/login.html": (9197, "d05d3440bf9bee917dd794cbd4dfda3f19e44227fc86c59040f366a052184968"),
    "docs/onyx/checkpoints/hud-orb-v4-live/manifest.json": (2920, "8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495"),
    "docs/onyx/checkpoints/hud-orb-v4-live/ONYX_HUD_ORB_V4_LIVE_CHECKPOINT.md": (3490, "42148552f863791979812F19B1019921CE9B785153F511F80803E40D127126D5".lower()),
    "docs/onyx/checkpoints/hud-orb-v4-live/onyx-hud-v4-d3d11.png": (501346, "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1"),
    "packaging/onyx.spec": (3034, "2ab5ade541b6cd8b9c6edcd52320535d7cad912d150169156810330c577506b3"),
    "qml/assets/onyx-orb-cinematic-v3.png": (1333775, "44668e57df10b4b47516cf7b35238ced7803523c76ea264a2045bdb35b174de1"),
    "qml/components/OnyxOrbCinematicV4.qml": (6357, "3ed374e0b85099fd3f8b57f0d4cfad690dcea70c473fbf10fdd254084219003e"),
    "qml/OnyxLiveShellV4.qml": (13647, "36ca53ebd5eb971be8322639a012c0aa91571612824287d619ac0f200a806b0c"),
    "scripts/build_release.py": (11733, "1d06830f743c818fb89fc6571efa971a35a9a46f005661b4d9cb6c6e6ab2c5e3"),
    "tests/test_onyx_hud_v3_live_integration.py": (1540, "b11593d2a9dff7af738e497dc6444e1412a7604cbb719c7764ebc24cf544f10e"),
    "tests/test_onyx_hud_v4_live_integration.py": (9990, "fa791f17f9d82a11d540226dc6d5abe93c81cb3e432a28fd7949fbaa13872dce"),
    "ui.py": (164691, "efefec138393803475b274e1d55711c5a2e3746ba924f5e049e7e9126129e189"),
}

FOCUSED_FILES = ["tests/test_onyx_hud_v5_live_integration.py"]
REPRESENTATIVE_FILES = [
    "tests/test_onyx_hud_v5_live_integration.py",
    "tests/test_onyx_hud_v4_live_integration.py",
    "tests/test_onyx_hud_v3_live_integration.py",
    "tests/test_onyx_hud_v3.py",
    "tests/test_orb_3d.py",
    "tests/test_ui_orb_performance.py",
    "tests/test_render_governor.py",
    "tests/test_render_governor_v3.py",
    "tests/test_packaging_paths.py",
    "browser_tests/test_dashboard_audio_worklet.py",
    "browser_tests/test_dashboard_device_token.py",
]
MATRIX_ANCHORS = {
    "tests/test_onyx_hud_v5_live_integration.py": (14095, "93c3854d866d739adb261cfb241a40d20d34f25a22747f89b049a5c21caf5cfc"),
    "tests/test_onyx_hud_v4_live_integration.py": (1615, "1270150def53c32661d8b9daa212a40cf8b8fe60221bf5b643fa8d7a734693ec"),
    "tests/test_onyx_hud_v3_live_integration.py": (1584, "7d06410745d34561b6fc309c6ff6ebdc6056962e68240667f69f3eaba9592e00"),
    "tests/test_onyx_hud_v3.py": (8188, "928e92c25be8218ef83d2dbf035330c0017eef9bb03bfd2a737cbb82e39b5b9f"),
    "tests/test_orb_3d.py": (5645, "01be59d1438621b6d16c1723feebe3b12cc0dcae006bffff076ba5bffc86411d"),
    "tests/test_ui_orb_performance.py": (1073, "6c9a06124c10e689791cedfeb0b815cce1968adeb287436232b2d5570453ceff"),
    "tests/test_render_governor.py": (3631, "6ffc50f38cd5b7be1fe38d927c3599828b6d2ca0190f048a635baada11a338db"),
    "tests/test_render_governor_v3.py": (1273, "15704af20c1859d1b61b3a30c645dcc26b625fce49b0fd581ff993830023a3e4"),
    "tests/test_packaging_paths.py": (2486, "9cf3add01964ccfba3eb6894349448349178f33777bdd2a5de8e23e5411358f8"),
    "browser_tests/test_dashboard_audio_worklet.py": (5875, "dc480226567e484f258e8f4e008c6184cce66ebb2d0555cde1256daaa156bf07"),
    "browser_tests/test_dashboard_device_token.py": (5217, "6a62665d317720673dda718a79e04b39421a60d44259ed7a81f21386ba923d76"),
}

_REPARSE_ATTRIBUTE = 0x400


class HudV5AcceptanceError(RuntimeError):
    """Candidate 003 or one of its frozen anchors is invalid."""


def _canonical_relative(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise HudV5AcceptanceError("acceptance path is not canonical")
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or str(parsed) != relative or any(
        part in {"", ".", ".."} for part in parsed.parts
    ):
        raise HudV5AcceptanceError("acceptance path is not canonical")
    return parsed.parts


def _regular_path(project: Path, relative: str) -> Path:
    parts = _canonical_relative(relative)
    root = project.absolute()
    try:
        root_info = root.lstat()
        root_resolved = root.resolve(strict=True)
    except OSError as exc:
        raise HudV5AcceptanceError("acceptance root is unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
        or root_resolved != root
    ):
        raise HudV5AcceptanceError("acceptance root is linked or aliased")
    current = root
    for index, part in enumerate(parts):
        try:
            entries = {entry.name: entry for entry in current.iterdir()}
        except OSError as exc:
            raise HudV5AcceptanceError(f"ancestor unavailable: {relative}") from exc
        if part not in entries:
            raise HudV5AcceptanceError(f"path missing or case-mismatched: {relative}")
        current = entries[part]
        try:
            metadata = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise HudV5AcceptanceError(f"path unavailable: {relative}") from exc
        if stat.S_ISLNK(metadata.st_mode) or getattr(
            metadata, "st_file_attributes", 0
        ) & _REPARSE_ATTRIBUTE:
            raise HudV5AcceptanceError(f"path uses a link/reparse point: {relative}")
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise HudV5AcceptanceError(f"path leaves project: {relative}") from exc
        if resolved.name != part:
            raise HudV5AcceptanceError(f"path uses a name alias: {relative}")
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise HudV5AcceptanceError(f"ancestor is not a directory: {relative}")
    if not stat.S_ISREG(current.lstat().st_mode):
        raise HudV5AcceptanceError(f"leaf is not a regular file: {relative}")
    return current


def _bytes(project: Path, relative: str) -> bytes:
    try:
        return _regular_path(project, relative).read_bytes()
    except OSError as exc:
        raise HudV5AcceptanceError(f"cannot read: {relative}") from exc


def _text(project: Path, relative: str) -> str:
    try:
        return _bytes(project, relative).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HudV5AcceptanceError(f"text is not UTF-8: {relative}") from exc


def _digest(project: Path, relative: str) -> str:
    return hashlib.sha256(_bytes(project, relative)).hexdigest()


def _require_file(project: Path, relative: str, size: int, digest: str) -> None:
    payload = _bytes(project, relative)
    if len(payload) != size or hashlib.sha256(payload).hexdigest() != digest:
        raise HudV5AcceptanceError(f"frozen anchor drifted: {relative}")


def _require_digest(project: Path, relative: str, expected: str) -> None:
    if _digest(project, relative) != expected:
        raise HudV5AcceptanceError(f"frozen anchor drifted: {relative}")


def _manifest_line(value: str) -> tuple[str, str]:
    lines = value.splitlines()
    if len(lines) != 1 or len(lines[0]) < 67 or lines[0][64:66] != "  ":
        raise HudV5AcceptanceError("acceptance manifest record is malformed")
    digest, relative = lines[0][:64], lines[0][66:]
    if any(character not in "0123456789abcdef" for character in digest):
        raise HudV5AcceptanceError("acceptance manifest digest is malformed")
    _canonical_relative(relative)
    return digest, relative


def _verify_record(project: Path) -> str:
    digest, relative = _manifest_line(_text(project, ACCEPTANCE_MANIFEST))
    if relative != ACCEPTANCE_RECORD or _digest(project, relative) != digest:
        raise HudV5AcceptanceError("external acceptance record is not bound")
    record = _text(project, ACCEPTANCE_RECORD)
    required = (
        ACCEPTANCE_ID,
        "ACCEPTED - HUD / Orb V5 Live Candidate 003 only, frozen default-off handoff",
        CANDIDATE_MANIFEST_SHA256,
        CANDIDATE_CHECKPOINT_SHA256,
        "P0=0, P1=0, P2=0",
        "15 passed, 0 failed",
        "66 passed, 0 failed",
        "01be59d1438621b6d16c1723feebe3b12cc0dcae006bffff076ba5bffc86411d",
        "GraphicsApi.Direct3D11Rhi",
        "2,095,770-byte snapshot",
        "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1",
        "No main, broker or server activation was added",
        "not an activation instruction",
        ACCEPTANCE_MARKER,
    )
    missing = [item for item in required if item not in record]
    if missing:
        raise HudV5AcceptanceError(f"acceptance record missing: {missing[0]}")
    return digest


def _verify_candidate(project: Path) -> dict[str, object]:
    _require_digest(project, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256)
    _require_digest(project, CANDIDATE_CHECKPOINT, CANDIDATE_CHECKPOINT_SHA256)
    try:
        manifest = json.loads(_text(project, CANDIDATE_MANIFEST))
    except (json.JSONDecodeError, TypeError) as exc:
        raise HudV5AcceptanceError("candidate manifest is invalid") from exc
    if (
        type(manifest) is not dict
        or manifest.get("candidate") != "ONYX-HUD-ORB-V5-LIVE-INTEGRATION-003"
        or manifest.get("status") != "candidate-default-off"
        or manifest.get("activation") != "ONYX_HUD_V5_LIVE=1"
    ):
        raise HudV5AcceptanceError("candidate identity/default-off contract drifted")
    actual_files = {
        entry.get("path"): (entry.get("size"), entry.get("sha256"))
        for entry in manifest.get("files", [])
        if type(entry) is dict
    }
    if actual_files != CANDIDATE_FILES or len(manifest.get("files", [])) != 13:
        raise HudV5AcceptanceError("candidate file closure is not exact")
    actual_v3 = {
        entry.get("path"): (entry.get("size"), entry.get("sha256"))
        for entry in manifest.get("accepted_v3_anchors", [])
        if type(entry) is dict
    }
    if actual_v3 != ACCEPTED_V3_ANCHORS or len(manifest.get("accepted_v3_anchors", [])) != 4:
        raise HudV5AcceptanceError("accepted V3 closure is not exact")
    for relative, (size, digest) in {**CANDIDATE_FILES, **ACCEPTED_V3_ANCHORS}.items():
        _require_file(project, relative, size, digest)
    rejected = manifest.get("rejected_candidate_snapshot")
    if rejected != {
        "path": SNAPSHOT_ROOT,
        "files": 13,
        "bytes": 2095770,
        "manifest_sha256": "8daf7a43fd08ee6d7548992f4a8ef2da48c4271142dabae4e8fb0ee76c50d495",
        "checkpoint_sha256": "42148552f863791979812f19b1019921ce9b785153f511f80803e40d127126d5",
    }:
        raise HudV5AcceptanceError("rejected Candidate 002 binding drifted")
    visual = manifest.get("visual_evidence")
    if (
        type(visual) is not dict
        or visual.get("visual_qml_changed_since_candidate_002") is not False
        or visual.get("screenshot_sha256")
        != "03b99d56a542d48680c5baa42ffd818e20c6e87043dc82333d098be662ee57a1"
    ):
        raise HudV5AcceptanceError("inherited visual evidence drifted")
    physical = manifest.get("physical_validation")
    if (
        type(physical) is not dict
        or physical.get("platform") != "Windows"
        or physical.get("graphics_api") != "Direct3D11Rhi"
        or physical.get("resolution") != [1440, 900]
        or physical.get("active_host_cpu_percent", 1) > 0.8
        or physical.get("idle_host_cpu_percent", 1) > 0.15
        or physical.get("hidden_host_cpu_percent", 1) > 0.15
        or physical.get("active_target_fps") != 16
        or physical.get("settled_measurement") is not True
    ):
        raise HudV5AcceptanceError("Windows/D3D11 physical evidence drifted")
    return {
        "candidate_files": len(CANDIDATE_FILES),
        "accepted_v3_anchors": len(ACCEPTED_V3_ANCHORS),
        "manifest_sha256": CANDIDATE_MANIFEST_SHA256,
        "checkpoint_sha256": CANDIDATE_CHECKPOINT_SHA256,
    }


def _verify_default_off_boundary(project: Path) -> dict[str, object]:
    ui_source = _text(project, "ui.py")
    exact_default = 'HUD_V5_LIVE = os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"'
    if ui_source.count(exact_default) != 1:
        raise HudV5AcceptanceError("V5 exact default-off comparison drifted")
    if "ONYX_HUD_V3_LIVE" in ui_source or "ONYX_HUD_V4_LIVE" in ui_source:
        raise HudV5AcceptanceError("a rejected HUD flag regained an activation path")
    forbidden = (
        "ONYX_HUD_V5_LIVE",
        "HUD_V5_LIVE",
        "OnyxLiveShellV5",
        "OnyxOrbCinematicV5",
    )
    for relative, digest in BOUNDARY_ANCHORS.items():
        _require_digest(project, relative, digest)
        source = _text(project, relative)
        if any(token in source for token in forbidden):
            raise HudV5AcceptanceError(f"host activation appeared in {relative}")
    return {
        "flag_default_false": True,
        "exact_opt_in": "ONYX_HUD_V5_LIVE=1",
        "host_boundaries": len(BOUNDARY_ANCHORS),
        "live_activated": False,
    }


def _verify_matrix_anchors(project: Path) -> int:
    if REPRESENTATIVE_FILES != list(MATRIX_ANCHORS):
        raise HudV5AcceptanceError("representative matrix order/membership drifted")
    for relative, (size, digest) in MATRIX_ANCHORS.items():
        _require_file(project, relative, size, digest)
    return len(MATRIX_ANCHORS)


def _verify_rejected_snapshot(project: Path) -> dict[str, object]:
    snapshot_path = project / SNAPSHOT_ROOT
    if snapshot_path.exists() or snapshot_path.is_symlink():
        raise HudV5AcceptanceError("retired Candidate 002 snapshot was restored")
    if sum(size for size, _digest_value in REJECTED_SNAPSHOT_FILES.values()) != 2095770:
        raise HudV5AcceptanceError("Candidate 002 snapshot byte count drifted")
    try:
        ledger = json.loads(_text(project, RETIREMENT_LEDGER))
    except (json.JSONDecodeError, TypeError) as exc:
        raise HudV5AcceptanceError("HUD retirement ledger is invalid") from exc
    if (
        type(ledger) is not dict
        or ledger.get("schema") != "OnyxHudRejectedCandidateRetirement.v1"
        or type(ledger.get("retired")) is not list
        or len(ledger["retired"]) != 2
    ):
        raise HudV5AcceptanceError("HUD retirement ledger contract drifted")
    retired = ledger["retired"][1]
    expected_retired = {
        "candidate": "ONYX-HUD-ORB-V4-LIVE-INTEGRATION-002",
        "snapshot_root": SNAPSHOT_ROOT,
        "state": "absent",
        "files": len(REJECTED_SNAPSHOT_FILES),
        "bytes": 2095770,
        "manifest_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/manifest.json"
        ][1],
        "checkpoint_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/ONYX_HUD_ORB_V4_LIVE_CHECKPOINT.md"
        ][1],
        "screenshot_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/onyx-hud-v4-d3d11.png"
        ][1],
    }
    if retired != expected_retired:
        raise HudV5AcceptanceError("Candidate 002 retirement record drifted")
    return {
        "candidate": "ONYX-HUD-ORB-V4-LIVE-INTEGRATION-002",
        "rejected": True,
        "storage": "retired-absent",
        "files": len(REJECTED_SNAPSHOT_FILES),
        "bytes": 2095770,
        "manifest_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/manifest.json"
        ][1],
        "checkpoint_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/ONYX_HUD_ORB_V4_LIVE_CHECKPOINT.md"
        ][1],
        "screenshot_sha256": REJECTED_SNAPSHOT_FILES[
            "docs/onyx/checkpoints/hud-orb-v4-live/onyx-hud-v4-d3d11.png"
        ][1],
    }


def verify(project: Path = PROJECT) -> dict[str, object]:
    project = Path(project)
    return {
        "acceptance_id": ACCEPTANCE_ID,
        "record_sha256": _verify_record(project),
        "candidate": _verify_candidate(project),
        "default_off_boundary": _verify_default_off_boundary(project),
        "matrix_anchors": _verify_matrix_anchors(project),
        "rejected_snapshot": _verify_rejected_snapshot(project),
        "focused_passed": 15,
        "representative_passed": 66,
        "severity": {"P0": 0, "P1": 0, "P2": 0},
        "p3": "physical validation is Windows/Direct3D11Rhi only",
        "scope": "hud-orb-v5-candidate003-frozen-default-off-no-activation",
    }


def main() -> int:
    print(
        ACCEPTANCE_MARKER
        + " "
        + json.dumps(verify(), sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
