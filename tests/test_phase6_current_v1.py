from pathlib import Path
import shutil

import pytest

from scripts import verify_phase6_current_v1 as current


ROOT = Path(__file__).resolve().parents[1]
CURRENT_SOURCES = (
    "scripts/bootstrap_onyx.pyw",
    current.CURRENT_BOOTSTRAP,
    current.CURRENT_LAUNCHER,
    current.V23_BOOTSTRAP,
    current.V23_LAUNCHER,
    "main.py",
    "core/onyx_live_activation_v18.py",
    "core/onyx_live_activation_v19.py",
    "core/onyx_live_activation_v20.py",
    "core/onyx_live_activation_v21.py",
    "core/onyx_live_activation_v22.py",
    "core/onyx_live_activation_v23.py",
    current.CURRENT_ACTIVATION,
    "packaging/onyx.spec",
)


def _projection(destination: Path) -> Path:
    for relative in CURRENT_SOURCES:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return destination


def test_current_phase6_successor_is_semantic_and_v24_additive() -> None:
    result = current.verify(ROOT)
    assert result["acceptance_id"] == current.ACCEPTANCE_ID
    assert result["current_bootstrap"] == current.CURRENT_BOOTSTRAP
    assert result["current_launcher"] == current.CURRENT_LAUNCHER
    assert result["current_activation"] == current.CURRENT_ACTIVATION
    assert result["v23_predecessor_sha256"] == current.V23_ACTIVATION_SHA256
    assert result["document_intake"] == "authorized-live-v18-via-v19-v20-v21-v22-v23-v24"
    assert result["advanced_operations"] == "lazy-live-v20-zero-polling"
    assert result["advanced_commands"] == "voice-tool-v21-local-metadata-only"
    assert result["owner_context"] == "voice-tool-v22-explicit-owner-local-context"
    assert result["operational_events"] == "host-callback-v23-metadata-only-zero-polling"
    assert result["historical_candidates"] == "default-off-unwired"
    assert len(result["historical_feature_flags"]) == 5
    assert result["runtime_effect"] == "additive-v24-shutdown-guard-over-exact-v23-events"


def test_current_gate_rejects_stable_bootstrap_regression(tmp_path: Path) -> None:
    project = _projection(tmp_path)
    stable = project / "scripts/bootstrap_onyx.pyw"
    stable.write_text(
        stable.read_text(encoding="utf-8").replace(
            '"bootstrap_onyx_live_v24.pyw"',
            '"bootstrap_onyx_live_v23.pyw"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(current.Phase6CurrentV1Error, match="current V24"):
        current.verify(project)


def test_current_gate_rejects_v24_launcher_regression(tmp_path: Path) -> None:
    project = _projection(tmp_path)
    bootstrap = project / current.CURRENT_BOOTSTRAP
    bootstrap.write_text(
        bootstrap.read_text(encoding="utf-8").replace(
            'LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v24.pyw"',
            'LAUNCHER = ROOT / "scripts" / "launch_onyx_live_v23.pyw"',
        ),
        encoding="utf-8",
    )
    with pytest.raises(current.Phase6CurrentV1Error, match="V24 bootstrap"):
        current.verify(project)


def test_current_gate_rejects_authenticated_v23_source_drift(tmp_path: Path) -> None:
    project = _projection(tmp_path)
    predecessor = project / current.V23_ACTIVATION
    predecessor.write_text(
        predecessor.read_text(encoding="utf-8") + "\n# drift\n",
        encoding="utf-8",
    )
    with pytest.raises(current.Phase6CurrentV1Error, match="V23 predecessor source"):
        current.verify(project)


def test_current_gate_rejects_retired_candidate_rewiring(tmp_path: Path) -> None:
    project = _projection(tmp_path)
    main = project / "main.py"
    main.write_text(
        "from core import phase6_live_wiring_v1\n"
        + main.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    with pytest.raises(current.Phase6CurrentV1Error, match="rewired into main.py"):
        current.verify(project)
