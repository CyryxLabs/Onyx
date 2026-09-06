from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from scripts import verify_phase5_integration_v3_transition as transition


ROOT = Path(__file__).resolve().parents[1]


def test_v3_transition_verifies_three_separate_historical_closures() -> None:
    result = transition.verify()
    assert result["candidate"] == "phase5-integration-v3"
    assert result["boundary"] == {
        "main_imports": ["core.phase5_integration_v3"],
        "v1_reachable": False,
        "v2_reachable": False,
        "ui_dependency": False,
        "default_off": True,
    }
    historical = result["historical_execution_closures"]
    assert set(historical) == {
        "runtime-v10-e6",
        "approval-inbox-v15-e6",
        "capability-nexus-v32-e6",
    }
    assert historical["runtime-v10-e6"]["result"]["historical_state"] == (
        "isolated-default-off-unwired"
    )
    assert historical["approval-inbox-v15-e6"]["result"]["acceptance_id"] == (
        "VE-P52-APPROVAL-INBOX-V15-E6-001"
    )
    assert historical["capability-nexus-v32-e6"]["result"]["acceptance_id"] == (
        "VE-P53-CAPABILITY-NEXUS-V32-E6-001"
    )


@pytest.mark.parametrize(
    ("closure", "expected_count"),
    (
        ("runtime-v10-e6", 28),
        ("approval-inbox-v15-e6", 11),
        ("capability-nexus-v32-e6", 11),
    ),
)
def test_projection_manifest_binds_sorted_exact_source_bytes(
    closure: str, expected_count: int
) -> None:
    relative = transition.PROJECTION_MANIFESTS[closure]
    value = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    files = value["files"]
    assert len(files) == expected_count
    assert files == sorted(files, key=lambda entry: entry["path"])
    assert transition._closure_root(files) == value["closure_root_sha256"]
    for entry in files:
        transition._require_digest(ROOT, entry["path"], entry["sha256"])


def test_projection_copy_rehashes_and_rejects_extra_missing_or_changed_bytes() -> None:
    relative = transition.PROJECTION_MANIFESTS["approval-inbox-v15-e6"]
    projection = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="onyx-v3-projection-test-") as temporary:
        destination = Path(temporary).resolve(strict=True)
        with pytest.raises(
            transition.Phase5IntegrationV3TransitionError,
            match="historical projection retired and delegated",
        ):
            transition._copy_projection(ROOT, destination, projection)

        exact_entry = next(
            entry
            for entry in projection["files"]
            if hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
            == entry["sha256"]
        )
        exact_projection = {"files": [exact_entry]}
        transition._copy_projection(ROOT, destination, exact_projection)
        assert transition._verify_projection_tree(destination, exact_projection) == 1

        extra = destination / "extra.txt"
        extra.write_bytes(b"extra")
        with pytest.raises(
            transition.Phase5IntegrationV3TransitionError,
            match="extra or missing",
        ):
            transition._verify_projection_tree(destination, exact_projection)
        extra.unlink()

        first = exact_entry
        target = destination.joinpath(*Path(first["path"]).parts)
        original = target.read_bytes()
        target.write_bytes(original + b"tamper")
        with pytest.raises(
            transition.Phase5IntegrationV3TransitionError,
            match="byte drifted",
        ):
            transition._verify_projection_tree(destination, exact_projection)


def test_projection_implementation_has_no_precopy_then_copy_path() -> None:
    source = (ROOT / "scripts/verify_phase5_integration_v3_transition.py").read_text(
        encoding="utf-8"
    )
    assert "shutil.copy" not in source
    assert "path.open(\"rb\")" in source
    assert "os.fstat(handle.fileno())" in source
    assert "target.open(\"xb\")" in source
    assert "projection destination rehash failed" in source


def test_permission_broker_drift_is_explicitly_governed() -> None:
    result = transition._verify_permission_broker_transition(ROOT)
    assert result == {
        "historical_sha256": (
            "8358ba39d7ff2d965eae7af7c24007f64f4670bef349447737c72e88776cbffc"
        ),
        "current_generic_hook_sha256": (
            "e37fb092410ba0843036dbdc779342c4d24a811bbfcf0de8812f2f6144e7d250"
        ),
        "governed_as_post_acceptance_transition": True,
    }


def test_v1_v2_and_accepted_component_bytes_remain_exact() -> None:
    expected = {
        **transition.V1_FROZEN,
        **transition.V2_FROZEN,
        **transition.ACCEPTED_ANCHORS,
        **transition.UNCHANGED_HOOKS,
    }
    for relative, digest in expected.items():
        transition._require_digest(ROOT, relative, digest)


def test_cumulative_command_is_exact_and_has_no_deselection() -> None:
    command = transition.REPRODUCIBLE_CUMULATIVE_COMMAND
    assert command[:4] == ["python", "-m", "pytest", "-q"]
    assert "-k" not in command
    assert "--ignore" not in command
    assert not any("deselect" in item for item in command)
    assert command[-2:] == ["--basetemp", ".pytest-p5-v3-cumulative"]


@pytest.mark.parametrize(
    "relative",
    ("../main.py", "/main.py", "core\\phase5_integration_v3.py", "core/../main.py"),
)
def test_noncanonical_transition_paths_fail_closed(relative: str) -> None:
    with pytest.raises(transition.Phase5IntegrationV3TransitionError):
        transition._canonical_relative(relative)
