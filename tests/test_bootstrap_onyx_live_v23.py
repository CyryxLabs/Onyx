from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from core import onyx_live_activation_v22 as v22
from core import onyx_live_activation_v23 as v23


ROOT = Path(__file__).resolve().parents[1]


def _namespace() -> dict[str, object]:
    return runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v23.pyw"),
        run_name="onyx_v23_bootstrap_test",
    )


def test_v23_bootstrap_migrates_exact_v22(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    predecessor = v22.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    mode, environment = namespace["_bootstrap_environment"](predecessor)
    assert mode == "v23"
    assert environment[v23.LIVE_MASTER_FLAG] == "1"
    assert environment[v23.FEATURE_FLAG] == "true"
    flags = v23.ActivationFlagsV23.from_canonical_environ(environment)
    assert flags.base.base.base.base.base.base.base.base.workspace_roots == (
        str(tmp_path.resolve()),
    )


def test_v23_bootstrap_rollback_restores_exact_v22(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    predecessor = v22.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    mode, restored = namespace["_bootstrap_environment"](
        {**predecessor, v23.LIVE_ROLLBACK_FLAG: "1"}
    )
    assert mode == "v22"
    assert restored == predecessor


def test_v23_bootstrap_rejects_partial_current_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="V23_PARTIAL_CONFIGURATION_REFUSED"):
        namespace["_bootstrap_environment"]({v23.LIVE_MASTER_FLAG: "1"})
