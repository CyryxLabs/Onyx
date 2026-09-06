from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from core import onyx_live_activation_v21 as v21
from core import onyx_live_activation_v22 as v22


ROOT = Path(__file__).resolve().parents[1]


def _namespace() -> dict[str, object]:
    return runpy.run_path(
        str(ROOT / "scripts" / "bootstrap_onyx_live_v22.pyw"),
        run_name="onyx_v22_bootstrap_test",
    )


def test_v22_bootstrap_migrates_exact_v21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    predecessor = v21.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )

    mode, environment = namespace["_bootstrap_environment"](predecessor)

    assert mode == "v22"
    assert environment[v22.LIVE_MASTER_FLAG] == "1"
    assert environment[v22.FEATURE_FLAG] == "true"
    flags = v22.ActivationFlagsV22.from_canonical_environ(environment)
    assert flags.base.base.base.base.base.base.base.workspace_roots == (
        str(tmp_path.resolve()),
    )


def test_v22_bootstrap_rollback_restores_exact_v21(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    predecessor = v21.exact_activation_environment(
        (tmp_path,), executable_sandbox=False
    )
    environment = {**predecessor, v22.LIVE_ROLLBACK_FLAG: "1"}

    mode, restored = namespace["_bootstrap_environment"](environment)

    assert mode == "v21"
    assert restored == predecessor


def test_v22_bootstrap_rejects_partial_current_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    monkeypatch.setattr(namespace["platform"], "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="V22_PARTIAL_CONFIGURATION_REFUSED"):
        namespace["_bootstrap_environment"]({v22.LIVE_MASTER_FLAG: "1"})


def test_v22_bootstrap_remains_historical_while_stable_selects_current_v24() -> None:
    historical = _namespace()
    source = (ROOT / "scripts" / "bootstrap_onyx.pyw").read_text(encoding="utf-8")
    assert historical["LAUNCHER"] == ROOT / "scripts" / "launch_onyx_live_v22.pyw"
    assert historical["V21_BOOTSTRAP"] == ROOT / "scripts" / "bootstrap_onyx_live_v21.pyw"
    assert 'CURRENT_BOOTSTRAP = ROOT / "scripts" / "bootstrap_onyx_live_v24.pyw"' in source
