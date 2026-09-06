from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts import linux_lifecycle_validation as lifecycle


ROOT = Path(__file__).resolve().parents[1]


def test_deb_requires_exact_name_version_and_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deb = tmp_path / "Onyx-1.1.9-Linux-x64.deb"
    deb.write_bytes(b"sealed-deb")
    digest = hashlib.sha256(b"sealed-deb").hexdigest()
    monkeypatch.setattr(lifecycle, "_tool", lambda name: name)

    class Result:
        stdout = "onyx-ai-assistant\n1.1.9\namd64\n"

    monkeypatch.setattr(lifecycle, "_run", lambda *_args, **_kwargs: Result())
    monkeypatch.setattr(lifecycle.platform, "machine", lambda: "x86_64")
    assert lifecycle.require_regular_deb(deb, digest, "1.1.9") == deb
    with pytest.raises(lifecycle.LinuxLifecycleError, match="filename/version"):
        lifecycle.require_regular_deb(deb, digest, "1.1.8")
    with pytest.raises(lifecycle.LinuxLifecycleError, match="SHA-256 mismatch"):
        lifecycle.require_regular_deb(deb, "0" * 64, "1.1.9")


def test_linux_lifecycle_contract_is_owner_scoped_and_complete() -> None:
    source = (ROOT / "scripts" / "linux_lifecycle_validation.py").read_text(
        encoding="utf-8"
    )
    for contract in (
        "ONYX_DISPOSABLE_LINUX_LIFECYCLE_V1",
        "unsigned-approved",
        "clean_install_current",
        "uninstall_app_only",
        "reinstall_current",
        "upgrade_prior_to_current",
        "rollback_current_to_prior",
        "final_uninstall_app_only",
        "/opt/cyryx-labs/onyx",
        "--native-startup-smoke-test",
        "onyx.linux-lifecycle-evidence.v1",
        "/usr/lib/systemd/user/onyx.service",
        '"--user", "enable", "--now", "onyx.service"',
        '"--user", "disable", "--now", "onyx.service"',
    ):
        assert contract in source
    assert 'os.geteuid() == 0' in source
    assert '_tool("sudo"), "-n"' in source
    assert "shutil.rmtree(APP)" not in source
    assert "shutil.rmtree(Path.home())" not in source
