from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import core.external_agent_adapter_v1 as module
from core.external_agent_adapter_v1 import (
    DeterministicExternalAgentProviderV1,
    ExternalAgentContractError,
    ExternalAgentEnvelopeV1,
    ExternalAgentUnavailable,
    ExternalAgentWaiting,
    ExternalCodingAgentAdapterV1,
    ProviderResultV1,
    _PinnedExecutableV1,
    _TrustedStateV1,
    _decode_git_quoted_path,
    resolve_trusted_git_v1,
)


KEY = b"external-agent-test-signing-key-v1"
MISSION_ID = "mis_" + "1" * 32


def _git() -> str:
    value = shutil.which("git")
    assert value
    return value


def _run(cwd: Path, *argv: str) -> bytes:
    result = subprocess.run(
        [_git(), *argv],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "owner"
    root.mkdir()
    _run(root, "init")
    _run(root, "config", "user.email", "test@cyryxlabs.invalid")
    _run(root, "config", "user.name", "Onyx Test")
    (root / "src").mkdir()
    (root / "src" / "base.txt").write_text("base\n", encoding="utf-8")
    _run(root, "add", ".")
    _run(root, "commit", "-m", "baseline")
    return root


def _adapter(
    tmp_path: Path,
    provider: DeterministicExternalAgentProviderV1,
) -> ExternalCodingAgentAdapterV1:
    return ExternalCodingAgentAdapterV1(
        state_root=tmp_path / "state",
        signing_key=KEY,
        provider=provider,
        git_cli=_git(),
        model="sonnet",
        max_budget_usd=1.0,
        max_seconds=120,
        max_output_bytes=64 * 1024,
        enabled=True,
    )


def _envelope(
    adapter: ExternalCodingAgentAdapterV1,
    root: Path,
    task: str = "Create src/new.txt.",
    mission_id: str = MISSION_ID,
) -> ExternalAgentEnvelopeV1:
    commit, owner_digest = adapter.capture_owner_state(root)
    rows, manifest_sha256 = adapter._blob_manifest(root, commit, ("src",))
    health = adapter.health()
    return ExternalAgentEnvelopeV1.build(
        signing_key=KEY,
        mission_id=mission_id,
        workspace_id="cyryx",
        workspace_root=str(root),
        repository_commit=commit,
        owner_git_sha256=owner_digest,
        repository_blob_manifest_sha256=manifest_sha256,
        repository_blob_count=len(rows),
        git_executable_path=str(health["git_executable_path"]),
        git_executable_sha256=str(health["git_executable_sha256"]),
        git_executable_identity_sha256=str(
            health["git_executable_identity_sha256"]
        ),
        git_executable_file_id=str(health["git_executable_file_id"]),
        allowed_roots=("src",),
        provider_version=adapter.provider.version,
        provider_executable_path=str(health["executable_path"]),
        provider_executable_sha256=adapter.provider.executable_sha256,
        provider_executable_identity_sha256=str(
            health["executable_identity_sha256"]
        ),
        provider_executable_file_id=str(health["executable_file_id"]),
        provider_account_sha256="0" * 64,
        model=adapter.model,
        max_budget_usd=adapter.max_budget_usd,
        max_seconds=adapter.max_seconds,
        max_output_bytes=adapter.max_output_bytes,
        task=task,
        approval_digest="2" * 64,
        nonce="3" * 32,
    )


def test_envelope_authenticates_and_rejects_tamper(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, DeterministicExternalAgentProviderV1())
    envelope = _envelope(adapter, _repo(tmp_path))
    envelope.authenticate(KEY)
    mutations = (
        replace(envelope, mission_id="mis_" + "4" * 32),
        replace(envelope, workspace_id="other"),
        replace(envelope, repository_commit="5" * 64),
        replace(envelope, repository_blob_manifest_sha256="5" * 64),
        replace(envelope, repository_blob_count=envelope.repository_blob_count + 1),
        replace(envelope, git_executable_sha256="5" * 64),
        replace(envelope, git_executable_identity_sha256="5" * 64),
        replace(envelope, git_executable_file_id="1:1"),
        replace(envelope, allowed_roots=("other",)),
        replace(envelope, model="opus"),
        replace(envelope, provider_account_sha256="8" * 64),
        replace(envelope, provider_executable_identity_sha256="8" * 64),
        replace(envelope, provider_executable_file_id="2:2"),
        replace(envelope, max_budget_usd=2.0),
        replace(envelope, task_sha256="6" * 64),
        replace(envelope, approval_digest="7" * 64),
    )
    for candidate in mutations:
        with pytest.raises(ExternalAgentContractError):
            candidate.authenticate(KEY)


def test_task_artifact_is_encrypted_and_authenticated(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, DeterministicExternalAgentProviderV1())
    envelope = _envelope(adapter, _repo(tmp_path))
    task = "Create src/new.txt."
    reference = adapter.protect_task(
        MISSION_ID, task, hashlib.sha256(task.encode()).hexdigest()
    )
    artifact = tmp_path / "state" / str(reference["name"])
    assert task.encode() not in artifact.read_bytes()
    assert adapter.read_task(envelope, reference) == task
    artifact.write_bytes(artifact.read_bytes()[:-1] + b"x")
    with pytest.raises(ExternalAgentContractError):
        adapter.read_task(envelope, reference)


def test_patch_is_applied_only_to_clone_and_receipt_is_durable(
    tmp_path: Path,
) -> None:
    provider = DeterministicExternalAgentProviderV1(
        mutation=("src/new.txt", "created by provider\n")
    )
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    before = _run(root, "status", "--porcelain=v1", "--untracked-files=all")
    envelope = _envelope(adapter, root)
    result = adapter.execute(
        envelope=envelope,
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    after = _run(root, "status", "--porcelain=v1", "--untracked-files=all")
    assert result["status"] == "succeeded"
    assert before == after == b""
    assert not (root / "src" / "new.txt").exists()
    assert result["data"]["external_pr_created"] is False
    status = adapter.status(MISSION_ID)
    assert status["attempt_state"] == "succeeded"
    assert status["dispatch_permitted"] is False
    artifact = next(
        (tmp_path / "state" / "artifacts").glob("*.aesgcm")
    )
    assert b"created by provider" not in artifact.read_bytes()
    checkpoint_path = next(
        (tmp_path / "state" / "checkpoints").glob(f"{MISSION_ID}.*.json")
    )
    checkpoint = json.loads(checkpoint_path.read_text())
    serialized = json.dumps(checkpoint)
    assert "created by provider" not in serialized
    assert "Create src/new.txt." not in serialized


def test_restart_refuses_duplicate_provider_dispatch(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1(
        mutation=("src/new.txt", "created\n")
    )
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    envelope = _envelope(adapter, root)
    adapter.execute(envelope=envelope, task="Create src/new.txt.", cancel=lambda: False)
    restarted = _adapter(tmp_path, provider)
    with pytest.raises(ExternalAgentWaiting, match="automatic retry"):
        restarted.execute(
            envelope=envelope,
            task="Create src/new.txt.",
            cancel=lambda: False,
        )
    assert len(provider.calls) == 1


def test_out_of_scope_patch_is_not_applied(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1(
        mutation=("outside.txt", "forbidden\n")
    )
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    result = adapter.execute(
        envelope=_envelope(adapter, root),
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert result["data"]["provider_status"] == "failed"
    clones = list((tmp_path / "state" / "clones").glob("*"))
    assert clones
    assert not (clones[0] / "outside.txt").exists()
    assert not (root / "outside.txt").exists()


def test_cancel_before_dispatch_has_no_provider_call(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    with pytest.raises(ExternalAgentWaiting, match="before provider"):
        adapter.execute(
            envelope=_envelope(adapter, root),
            task="Create src/new.txt.",
            cancel=lambda: True,
        )
    assert provider.calls == []
    assert adapter.status(MISSION_ID)["attempt_state"] == "not_started"


def test_child_environment_omits_provider_and_github_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    monkeypatch.setenv("GH_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    environment = module._provider_environment()
    assert not any(
        name in environment
        for name in (
            "ANTHROPIC_API_KEY",
            "ANTHROPIC_AUTH_TOKEN",
            "GH_TOKEN",
            "GITHUB_TOKEN",
        )
    )


def test_git_boundary_is_pinned_hermetic_and_trusted(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path, DeterministicExternalAgentProviderV1())
    environment = adapter._git._environment
    assert Path(adapter.health()["git_executable_path"]).is_absolute()
    assert len(str(adapter.health()["git_executable_sha256"])) == 64
    assert len(str(adapter.health()["git_executable_identity_sha256"])) == 64
    assert environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert environment["GIT_TERMINAL_PROMPT"] == "0"
    assert environment["GCM_INTERACTIVE"] == "never"
    assert environment["GIT_PROTOCOL_FROM_USER"] == "0"
    if os.name == "nt":
        assert isinstance(adapter._state.boundary, module.WindowsTrustedDirectoryV1)
    adapter.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse boundary")
def test_trusted_state_rejects_junction_ancestor(tmp_path: Path) -> None:
    target = tmp_path / "junction-target"
    junction = tmp_path / "junction"
    target.mkdir()
    shutil.copy2(_git(), target / "provider.exe")
    created = subprocess.run(
        [
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d",
            "/c",
            "mklink",
            "/J",
            str(junction),
            str(target),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if created.returncode != 0:
        pytest.skip("junction creation unavailable")
    with pytest.raises(ExternalAgentContractError, match="untrusted ancestor"):
        _TrustedStateV1(junction / "state")
    with pytest.raises(ExternalAgentUnavailable, match="reparse ancestor"):
        with _PinnedExecutableV1(junction / "provider.exe").open():
            pass


@pytest.mark.skipif(os.name != "nt", reason="Windows executable sharing")
def test_pinned_executable_rehashes_and_rejects_suspended_image_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "pinned.exe"
    shutil.copy2(_git(), executable)
    pinned = _PinnedExecutableV1(executable)
    with pinned.open() as first:
        assert first.file_id
        with pytest.raises(PermissionError):
            executable.open("wb")
    metadata = executable.stat()
    content = bytearray(executable.read_bytes())
    content[-1] ^= 0x01
    executable.write_bytes(content)
    os.utime(
        executable,
        ns=(metadata.st_atime_ns, metadata.st_mtime_ns),
    )
    with pinned.open() as second:
        assert second.file_id == first.file_id
        assert second.identity_sha256 == first.identity_sha256
        assert second.sha256 != first.sha256

    impostor = tmp_path / "impostor.exe"
    impostor.write_bytes(b"not the approved image")

    class SuspendedJob:
        resumed = False

        def __init__(self, process, *, before_resume=None):
            assert before_resume is not None
            before_resume()
            type(self).resumed = True

        def terminate(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        module,
        "_query_windows_process_image_path_v1",
        lambda _process: impostor,
    )
    monkeypatch.setattr(module, "_WindowsKillJob", SuspendedJob)
    with _PinnedExecutableV1(_git()).open() as approved:
        with pytest.raises(
            ExternalAgentUnavailable,
            match="suspended process image identity mismatched",
        ):
            module._bounded_process(
                [approved.path, "--version"],
                cwd=Path(approved.path).parent,
                env=module._provider_environment(),
                timeout=10,
                approved_executable=approved,
            )
    assert SuspendedJob.resumed is False


@pytest.mark.skipif(os.name != "nt", reason="V15 trusted Git is Windows-only")
def test_trusted_git_resolver_ignores_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", r"C:\untrusted")
    assert resolve_trusted_git_v1() == r"C:\Program Files\Git\cmd\git.exe"


def test_live_cli_contract_has_no_tools_and_no_task_in_argv() -> None:
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert '"--tools",\n            "",' in source
    assert '"--strict-mcp-config"' in source
    assert '"--no-session-persistence"' in source
    assert "argv.append(request.task)" not in source
    assert "process.stdin.write(request.task.encode" in source
    assert '"Bash,WebFetch' not in source
    assert "resume_session_id" not in source
    assert '"billable_dispatch_available": False' in source
    main_source = (Path(module.__file__).parents[1] / "main.py").read_text(
        encoding="utf-8"
    )
    matrix = (
        Path(module.__file__).parents[1]
        / "docs"
        / "onyx"
        / "CAPABILITY_MATRIX.md"
    ).read_text(encoding="utf-8")
    assert '"execution is available only when Phase 11 can authenticate the "' in main_source
    assert '"provider account receipt and still produces a detached encrypted "' in main_source
    assert '"patch handoff rather than a push or pull request."' in main_source
    assert (
        "| Claude Code external coding-agent V1 | "
        "`HEALTH_ONLY_FAIL_CLOSED` |"
    ) in matrix
    assert "low-cost test-repository mission" not in matrix


def test_git_quoted_path_decoder_handles_octal_space_and_utf8() -> None:
    assert (
        _decode_git_quoted_path('"src/caf\\303\\251\\040file.txt"')
        == "src/café file.txt"
    )


def test_owner_drift_blocks_before_clone(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    envelope = _envelope(adapter, root)
    (root / "src" / "base.txt").write_text("drift\n", encoding="utf-8")
    with pytest.raises(ExternalAgentWaiting, match="drifted"):
        adapter.execute(
            envelope=envelope,
            task="Create src/new.txt.",
            cancel=lambda: False,
        )
    assert provider.calls == []


def test_feature_is_not_environment_enabled_by_module_import() -> None:
    assert module.FEATURE_FLAG not in os.environ or isinstance(
        os.environ[module.FEATURE_FLAG], str
    )


def test_durable_rate_budget_blocks_next_dispatch(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = ExternalCodingAgentAdapterV1(
        state_root=tmp_path / "state",
        signing_key=KEY,
        provider=provider,
        git_cli=_git(),
        model="sonnet",
        max_budget_usd=1.0,
        max_seconds=120,
        max_output_bytes=64 * 1024,
        rate_limit_calls=1,
        rate_window_seconds=60,
        enabled=True,
    )
    root = _repo(tmp_path)
    first = _envelope(adapter, root)
    assert adapter.execute(
        envelope=first,
        task="Create src/new.txt.",
        cancel=lambda: False,
    )["status"] == "succeeded"
    second_id = "mis_" + "9" * 32
    second = _envelope(adapter, root, mission_id=second_id)
    with pytest.raises(ExternalAgentWaiting, match="rate budget"):
        adapter.execute(
            envelope=second,
            task="Create src/new.txt.",
            cancel=lambda: False,
        )
    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    ("provider_status", "expected"),
    (("timeout", "timeout"), ("cancelled", "cancelled")),
)
def test_terminal_provider_status_is_waiting_without_retry(
    tmp_path: Path, provider_status: str, expected: str
) -> None:
    class TerminalProvider(DeterministicExternalAgentProviderV1):
        def invoke(self, request, *, cancel):
            self.calls.append(request)
            return ProviderResultV1(
                provider_status,
                request.session_id,
                provider_status,
                0.0,
                10,
                account_receipt_sha256="0" * 64,
            )

    provider = TerminalProvider()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    result = adapter.execute(
        envelope=_envelope(adapter, root),
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert result["data"]["provider_status"] == expected
    assert adapter.status(MISSION_ID)["dispatch_permitted"] is False


def test_provider_patch_output_limit_is_terminal(tmp_path: Path) -> None:
    class OversizedProvider(DeterministicExternalAgentProviderV1):
        def invoke(self, request, *, cancel):
            self.calls.append(request)
            return ProviderResultV1(
                "succeeded",
                request.session_id,
                "oversized",
                0.0,
                request.max_output_bytes + 1,
                patch="x" * (request.max_output_bytes + 1),
                account_receipt_sha256="0" * 64,
            )

    provider = OversizedProvider()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    result = adapter.execute(
        envelope=_envelope(adapter, root),
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    assert result["status"] == "waiting"
    assert result["data"]["provider_status"] == "output_limit"
    assert adapter.status(MISSION_ID)["dispatch_permitted"] is False


def test_context_comes_only_from_exact_commit_blobs(tmp_path: Path) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    (root / ".gitignore").write_text("src/ignored.txt\n", encoding="utf-8")
    _run(root, "add", ".gitignore")
    _run(root, "commit", "-m", "ignore runtime file")
    commit, _owner = adapter.capture_owner_state(root)
    (root / "src" / "base.txt").write_text("LIVE DRIFT\n", encoding="utf-8")
    (root / "src" / "ignored.txt").write_text(
        "LIVE IGNORED\n", encoding="utf-8"
    )
    packet, roots, manifest_sha256, blob_count = adapter.build_commit_packet(
        workspace_root=root,
        repository_commit=commit,
        objective="Review src/base.txt.",
        allowed_roots=("src",),
    )
    assert roots == ("src",)
    assert len(manifest_sha256) == 64
    assert blob_count == 1
    assert "base" in packet
    assert "LIVE DRIFT" not in packet
    assert "LIVE IGNORED" not in packet


def test_canonical_git_parser_accepts_quoted_unicode_and_space_path(
    tmp_path: Path,
) -> None:
    relative = "src/café file.txt"
    provider = DeterministicExternalAgentProviderV1(
        mutation=(relative, "created\n")
    )
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    result = adapter.execute(
        envelope=_envelope(adapter, root, task="Create src/café file.txt."),
        task="Create src/café file.txt.",
        cancel=lambda: False,
    )
    assert result["status"] == "succeeded"
    assert result["data"]["changed_paths"] == [relative]
    assert result["data"]["draft_pr_handoff"] is True


def test_provider_without_execution_account_receipt_cannot_dispatch(
    tmp_path: Path,
) -> None:
    class NoReceiptProvider(DeterministicExternalAgentProviderV1):
        execution_account_receipt_supported = False

        def health(self, *, force: bool = False):
            result = super().health(force=force)
            result["execution_account_receipt_supported"] = False
            result["billable_dispatch_available"] = False
            result["billable_dispatch_unavailable_reason"] = "no_receipt"
            return result

    provider = NoReceiptProvider()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    with pytest.raises(
        ExternalAgentUnavailable, match="provider identity diverged"
    ):
        adapter.execute(
            envelope=_envelope(adapter, root),
            task="Create src/new.txt.",
            cancel=lambda: False,
        )
    assert provider.calls == []


def test_empty_patch_is_explicit_no_change_without_handoff(
    tmp_path: Path,
) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    result = adapter.execute(
        envelope=_envelope(adapter, root),
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    assert result["status"] == "succeeded"
    assert result["data"]["outcome"] == "no_change"
    assert result["data"]["draft_pr_handoff"] is False
    assert adapter.status(MISSION_ID)["attempt_state"] == "no_change"
    assert list((tmp_path / "state" / "artifacts").glob("*.aesgcm")) == []


def test_provider_identity_drift_after_intent_is_attempted_unknown(
    tmp_path: Path,
) -> None:
    class DriftingProvider(DeterministicExternalAgentProviderV1):
        def __init__(self) -> None:
            super().__init__(mutation=("src/new.txt", "created\n"))
            self.drifted = False

        def health(self, *, force: bool = False):
            result = super().health(force=force)
            if self.drifted:
                result["account_binding_sha256"] = "f" * 64
            return result

        def invoke(self, request, *, cancel):
            result = super().invoke(request, cancel=cancel)
            self.drifted = True
            return result

    provider = DriftingProvider()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    with pytest.raises(ExternalAgentWaiting, match="identity drifted"):
        adapter.execute(
            envelope=_envelope(adapter, root),
            task="Create src/new.txt.",
            cancel=lambda: False,
        )
    assert adapter.status(MISSION_ID)["attempt_state"] == "attempted_unknown"
    assert len(provider.calls) == 1


def test_atomic_reservation_allows_only_one_concurrent_dispatch(
    tmp_path: Path,
) -> None:
    provider = DeterministicExternalAgentProviderV1()
    common = {
        "state_root": tmp_path / "state",
        "signing_key": KEY,
        "provider": provider,
        "git_cli": _git(),
        "model": "sonnet",
        "max_budget_usd": 1.0,
        "max_seconds": 120,
        "max_output_bytes": 64 * 1024,
        "rate_limit_calls": 1,
        "rate_window_seconds": 60,
        "enabled": True,
    }
    first_adapter = ExternalCodingAgentAdapterV1(**common)
    second_adapter = ExternalCodingAgentAdapterV1(**common)
    root = _repo(tmp_path)
    first = _envelope(first_adapter, root, mission_id="mis_" + "a" * 32)
    second = _envelope(second_adapter, root, mission_id="mis_" + "b" * 32)
    barrier = threading.Barrier(2)

    def dispatch(adapter, envelope):
        barrier.wait()
        try:
            result = adapter.execute(
                envelope=envelope,
                task="Create src/new.txt.",
                cancel=lambda: False,
            )
            return str(result["data"]["outcome"])
        except ExternalAgentWaiting:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(dispatch, first_adapter, first),
            executor.submit(dispatch, second_adapter, second),
        )
        outcomes = sorted(future.result() for future in futures)
    assert outcomes == ["denied", "no_change"]
    assert len(list((tmp_path / "state" / "reservations").glob("*.json"))) == 1
    assert len(provider.calls) == 1
    first_adapter.close()
    second_adapter.close()


def test_orphan_building_clone_is_handle_quarantined_on_restart(
    tmp_path: Path,
) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    adapter.close()
    orphan = tmp_path / "state" / "clones" / "building-stale"
    orphan.mkdir()
    (orphan / "partial.txt").write_text("partial", encoding="utf-8")
    restarted = _adapter(tmp_path, provider)
    try:
        names = {path.name for path in (tmp_path / "state" / "clones").iterdir()}
        assert "building-stale" not in names
        assert any(name.startswith("orphan-") for name in names)
    finally:
        restarted.close()


def test_terminal_clone_is_quarantined_and_retention_is_bounded(
    tmp_path: Path,
) -> None:
    provider = DeterministicExternalAgentProviderV1()
    adapter = _adapter(tmp_path, provider)
    root = _repo(tmp_path)
    first = _envelope(adapter, root)
    result = adapter.execute(
        envelope=first,
        task="Create src/new.txt.",
        cancel=lambda: False,
    )
    assert result["data"]["outcome"] == "no_change"
    clone_names = {
        path.name for path in (tmp_path / "state" / "clones").iterdir()
    }
    assert any(name.startswith("terminal-") for name in clone_names)
    assert not any(name.startswith(MISSION_ID) for name in clone_names)
    for index in range(6):
        (tmp_path / "state" / "clones" / f"terminal-test-{index}").mkdir()
    (tmp_path / "state" / "clones" / "orphan-test").mkdir()
    second = _envelope(
        adapter,
        root,
        mission_id="mis_" + "c" * 32,
    )
    with pytest.raises(ExternalAgentWaiting, match="retention is full"):
        adapter._materialize_clone(second)
    with pytest.raises(
        ExternalAgentContractError, match="owner confirmation"
    ):
        adapter.cleanup_quarantine(owner_confirmed=False)
    cleanup = adapter.cleanup_quarantine(
        owner_confirmed=True,
        retain=1,
    )
    assert cleanup["removed"] == 7
    assert cleanup["retained"] == 1
    clone = adapter._materialize_clone(second)
    assert clone.is_dir()
