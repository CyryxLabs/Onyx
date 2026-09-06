import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_social_cli_works_through_stable_bootstrap_without_ui():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_onyx.pyw"), "--social",
         "generate", "--brief", "Test draft", "--brand", "Cyryx Labs",
         "--platform", "linkedin"],
        capture_output=True, text=True, timeout=15, cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "draft"
    assert "Traceback" not in result.stderr


def test_unconfigured_publication_is_structured_nonzero():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap_onyx.pyw"), "--social",
         "publish-status", "--request-digest", "unconfigured"],
        capture_output=True, text=True, timeout=15, cwd=ROOT,
    )
    assert result.returncode != 0
    assert json.loads(result.stderr)["status"] == "error"
    assert "Traceback" not in result.stderr
