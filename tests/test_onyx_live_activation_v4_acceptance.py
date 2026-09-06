from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from core import onyx_live_activation_v4 as live
from scripts import verify_onyx_live_activation_v4_acceptance as acceptance


def test_external_acceptance_validates_exact_frozen_candidate() -> None:
    result = acceptance.verify()
    assert result["acceptance_id"] == acceptance.ACCEPTANCE_ID
    assert result["candidate_manifest_sha256"] == acceptance.MANIFEST_SHA256
    assert result["candidate_files"] == 53
    assert result["rejected_history"] == {"v1": 7, "v2": 8, "v3": 9}
    assert result["accepted_e6_anchors"] == 7
    assert result["findings"] == {"P0": 0, "P1": 0, "P2": 0, "P3": 1}
    assert result["scope"] == "activation-v4-default-off-not-activated-handoff"


@pytest.mark.parametrize(
    ("relative", "expected"),
    (
        (acceptance.CANDIDATE_MANIFEST, acceptance.MANIFEST_SHA256),
        (acceptance.CHECKPOINT, acceptance.CHECKPOINT_SHA256),
        (acceptance.ACCEPTANCE_TEST, acceptance.ACCEPTANCE_TEST_SHA256),
    ),
)
def test_acceptance_anchors_are_exact(relative: str, expected: str) -> None:
    assert acceptance._digest(acceptance.PROJECT, relative) == expected


def test_acceptance_manifest_binds_only_the_external_record() -> None:
    digest, relative = acceptance._manifest_line(
        acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_MANIFEST)
    )
    assert relative == acceptance.ACCEPTANCE_RECORD
    assert digest == hashlib.sha256(
        (acceptance.PROJECT / relative).read_bytes()
    ).hexdigest()


def test_candidate_root_excludes_external_acceptance_paths() -> None:
    value = acceptance._text(acceptance.PROJECT, acceptance.CANDIDATE_MANIFEST)
    for forbidden in (
        acceptance.ACCEPTANCE_ID,
        acceptance.ACCEPTANCE_RECORD,
        acceptance.ACCEPTANCE_MANIFEST,
        acceptance.ACCEPTANCE_TEST,
        acceptance.VERIFIER,
    ):
        assert forbidden not in value


def test_activation_and_rollback_recipes_are_exact_but_not_executed() -> None:
    result = acceptance.verify()
    assert result["activation_master"] == "ONYX_LIVE_ACTIVATION_V4=1"
    assert result["rollback_switch"] == "ONYX_LIVE_ROLLBACK_V4=1"
    assert result["launcher"] == "scripts/launch_onyx_live_v4.pyw"
    assert result["legacy_rollback"] == "scripts/launch_onyx.pyw"


def test_forced_real_qt_timeout_cannot_mutate_after_late_delivery() -> None:
    """Prove the candidate cancellation seam without editing candidate bytes."""

    app = QApplication.instance() or QApplication([])
    window = QObject()
    mutations: list[str] = []

    class ProbeController:
        def _gui_apply_request(
            self, request: live.OwnerUiRequestV4, endpoint: live.OwnerUiEndpointV4
        ) -> live.OwnerUiAckV4:
            mutations.append(request.address)
            return live.OwnerUiAckV4(request.request_id, True, 1)

        def _gui_unregister(self, dispatcher: live.OwnerUiDispatcherV4) -> None:
            del dispatcher

    endpoint = live.OwnerUiEndpointV4(timeout_seconds=0.01)
    dispatcher = live.OwnerUiDispatcherV4(ProbeController(), window, endpoint)  # type: ignore[arg-type]
    result: list[live.OwnerUiAckV4] = []
    worker = threading.Thread(
        target=lambda: result.append(endpoint.submit("Late Mutation")), daemon=True
    )
    worker.start()
    # Intentionally do not service the GUI event queue until the endpoint has
    # timed out and atomically removed the request from its pending map.
    worker.join(1.0)
    assert not worker.is_alive()
    assert len(result) == 1
    assert result[0].applied is False
    assert result[0].failure_type == "TimeoutError"
    assert not endpoint.is_pending(result[0].request_id)
    assert mutations == []

    # Deliver every queued signal after cancellation, then continue observing.
    # The dispatcher's first action is the pending-membership gate, so the
    # controller mutation callback must remain unreachable indefinitely.
    for _ in range(12):
        app.processEvents()
        time.sleep(0.002)
    assert mutations == []
    assert not endpoint.is_pending(result[0].request_id)
    endpoint.close()
    dispatcher.deleteLater()
    window.deleteLater()
    app.processEvents()


def test_noncanonical_and_linked_paths_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(acceptance.ActivationV4AcceptanceError):
        acceptance._canonical_relative("../core/onyx_live_activation_v4.py")
    target = tmp_path / "target.txt"
    target.write_text("target\n", encoding="utf-8", newline="\n")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this host")
    with pytest.raises(acceptance.ActivationV4AcceptanceError):
        acceptance._regular_path(tmp_path, "link.txt")


def test_record_retains_only_the_bounded_p3_advisory() -> None:
    record = acceptance._text(acceptance.PROJECT, acceptance.ACCEPTANCE_RECORD)
    assert "P0=0, P1=0, P2=0" in record
    assert "P3=1" in record
    assert "bundled timeout label gap" in record
    assert "No activation, restart, credential provisioning, provider call" in record
