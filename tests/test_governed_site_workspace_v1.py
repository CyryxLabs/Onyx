from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path

import pytest

from core.governed_site_workspace_v1 import (
    ABSENT_DIGEST,
    GitExecutionResultV1,
    GitHubOperationV1,
    GitOperationV1,
    GovernedSiteWorkspaceV1,
    SiteOwnerApprovalCapabilityV1,
    SiteWorkspaceContractError,
    SiteWorkspaceDenied,
    SiteWorkspaceError,
    SiteWorkspaceFeatureGateV1,
    SiteWorkspaceOutcomeUnknown,
    SiteWorkspaceScopeV1,
)


KEY = b"governed-site-test-key-is-at-least-thirty-two-bytes"
MAIN_OID = "1" * 40


def _git_state(root: Path) -> tuple[str, str]:
    oid = (
        (root / ".git" / "refs" / "heads" / "main").read_text(encoding="ascii").strip()
    )
    index = root / ".git" / "index"
    index_digest = (
        hashlib.sha256(index.read_bytes()).hexdigest()
        if index.exists()
        else ABSENT_DIGEST
    )
    return oid, index_digest


class FakeGit:
    def __init__(self, root: Path, *, fail: bool = False) -> None:
        self.root = root
        self.fail = fail
        self.calls: list[tuple[str, ...]] = []
        self.reconciled: GitExecutionResultV1 | None = None

    def execute(
        self, *, argv: tuple[str, ...], cwd: Path, timeout_seconds: float
    ) -> GitExecutionResultV1:
        assert cwd == self.root and timeout_seconds == 30.0
        self.calls.append(argv)
        if self.fail:
            raise TimeoutError("ambiguous transport boundary")
        before_oid, before_index = _git_state(self.root)
        if "commit" in argv:
            (self.root / ".git" / "refs" / "heads" / "main").write_text(
                "2" * 40 + "\n", encoding="ascii"
            )
        elif "revert" in argv:
            (self.root / ".git" / "refs" / "heads" / "main").write_text(
                "3" * 40 + "\n", encoding="ascii"
            )
        after_oid, after_index = _git_state(self.root)
        return GitExecutionResultV1(
            0,
            str(self.root),
            "main",
            "ok",
            "",
            "refs/heads/main",
            before_oid,
            before_index,
            after_oid,
            after_index,
            hashlib.sha256(repr(argv).encode()).hexdigest(),
        )

    def reconcile(
        self, *, intent_id: str, plan_digest: str
    ) -> GitExecutionResultV1 | None:
        assert intent_id.startswith("site_intent_") and len(plan_digest) == 64
        return self.reconciled


class DriftingReadGit(FakeGit):
    def execute(
        self, *, argv: tuple[str, ...], cwd: Path, timeout_seconds: float
    ) -> GitExecutionResultV1:
        result = super().execute(argv=argv, cwd=cwd, timeout_seconds=timeout_seconds)
        (self.root / ".git" / "refs" / "heads" / "main").write_text(
            "5" * 40 + "\n", encoding="ascii"
        )
        return result


def _git_root(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    (root / ".git" / "refs" / "heads").mkdir(parents=True)
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (root / ".git" / "refs" / "heads" / "main").write_text(
        MAIN_OID + "\n", encoding="ascii"
    )
    (root / "index.html").write_bytes(b"<h1>Onyx</h1>\n")
    return root


def _workspace(
    tmp_path: Path,
    *,
    root: Path | None = None,
    key: bytes = KEY,
    scope: SiteWorkspaceScopeV1 | None = None,
    git=None,
    approver=None,
):
    site = root or _git_root(tmp_path)
    hooks = tmp_path / "empty-hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    return GovernedSiteWorkspaceV1(
        root=site,
        state_path=tmp_path / "state" / "site.sqlite3",
        gate=SiteWorkspaceFeatureGateV1(True),
        scope=scope
        or SiteWorkspaceScopeV1(
            "owner.primary", "workspace.main", "site.cyryx", "cyryx-labs/onyx-site"
        ),
        integrity_key=key,
        owner_approver=approver or (lambda request: True),
        git_executor=git,
        git_hooks_directory=hooks,
    )


def test_default_off_and_execution_boundary_has_no_ambient_executor(
    tmp_path: Path,
) -> None:
    assert SiteWorkspaceFeatureGateV1.from_environ({}).enabled is False
    root = _git_root(tmp_path)
    with pytest.raises(SiteWorkspaceDenied, match="disabled"):
        GovernedSiteWorkspaceV1(
            root=root,
            state_path=tmp_path / "off.sqlite3",
            gate=SiteWorkspaceFeatureGateV1(False),
            scope=SiteWorkspaceScopeV1(
                "owner.primary", "workspace.main", "site.cyryx", "cyryx-labs/onyx-site"
            ),
            integrity_key=KEY,
            owner_approver=lambda _request: True,
        )
    assert GovernedSiteWorkspaceV1.execution_boundary() == {
        "shell_strings": False,
        "arbitrary_commands": False,
        "javascript_execution": False,
        "preview_listener": False,
        "browser_launch": False,
        "credential_urls": False,
        "background_workers": 0,
        "polling": False,
    }


def test_tree_is_bounded_paginated_utf8_and_cursor_authenticated(
    tmp_path: Path,
) -> None:
    root = _git_root(tmp_path)
    (root / "styles.css").write_text("body{}", encoding="utf-8")
    workspace = _workspace(tmp_path, root=root)
    page = workspace.list_files(limit=1)
    assert page.total == 2 and len(page.items) == 1 and page.next_cursor
    second = workspace.list_files(cursor=page.next_cursor, limit=1)
    assert len(second.items) == 1 and second.next_cursor is None
    with pytest.raises(SiteWorkspaceDenied, match="cursor authentication"):
        workspace.list_files(
            cursor=page.next_cursor[:-1] + ("0" if page.next_cursor[-1] != "0" else "1")
        )
    assert workspace.read_text("index.html") == "<h1>Onyx</h1>\n"


def test_traversal_extensions_binary_oversize_and_symlink_escape_are_denied(
    tmp_path: Path,
) -> None:
    root = _git_root(tmp_path)
    workspace = _workspace(tmp_path, root=root)
    for path in (
        "../outside.txt",
        "/absolute.txt",
        ".git/config",
        "payload.exe",
        "a\\b.txt",
    ):
        with pytest.raises((SiteWorkspaceDenied, SiteWorkspaceContractError)):
            workspace.read_text(path)
    (root / "binary.txt").write_bytes(b"\x00\xff")
    with pytest.raises(SiteWorkspaceDenied, match="binary"):
        workspace.read_text("binary.txt")
    (root / "huge.txt").write_bytes(b"a" * (512 * 1024 + 1))
    with pytest.raises(SiteWorkspaceDenied, match="byte budget"):
        workspace.read_text("huge.txt")
    outside = tmp_path / "outside"
    outside.mkdir()
    link = root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")
    with pytest.raises(SiteWorkspaceDenied, match="linked"):
        workspace.list_files()


def test_versioned_draft_apply_receipt_and_one_use_owner_capability(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    base = hashlib.sha256(b"<h1>Onyx</h1>\n").hexdigest()
    one = workspace.create_draft(
        relative_path="index.html",
        content="<h1>Cyryx</h1>\n",
        expected_base_digest=base,
    )
    two = workspace.create_draft(
        relative_path="index.html",
        content="<h1>Cyryx Labs</h1>\n",
        expected_base_digest=base,
    )
    assert (one.version, two.version) == (1, 2)
    plan = workspace.plan_apply_draft(two.draft_id, idempotency_key="apply:index:0001")
    assert (
        workspace.plan_apply_draft(two.draft_id, idempotency_key="apply:index:0001")
        == plan
    )
    capability = workspace.issue_owner_approval(plan)
    receipt = workspace.execute_apply_draft(plan, capability)
    assert receipt.outcome == "applied" and receipt.effect_digest == two.content_digest
    assert workspace.read_text("index.html") == "<h1>Cyryx Labs</h1>\n"
    with pytest.raises(SiteWorkspaceDenied):
        workspace.execute_apply_draft(plan, capability)


def test_new_file_draft_uses_absent_digest_and_rejects_toctou_drift(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    draft = workspace.create_draft(
        relative_path="about.md",
        content="# About\n",
        expected_base_digest=ABSENT_DIGEST,
    )
    plan = workspace.plan_apply_draft(
        draft.draft_id, idempotency_key="apply:about:0001"
    )
    capability = workspace.issue_owner_approval(plan)
    (workspace.root / "about.md").write_text("raced", encoding="utf-8")
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        workspace.execute_apply_draft(plan, capability)
    assert (workspace.root / "about.md").read_text(encoding="utf-8") == "raced"


def test_cross_scope_reopen_wrong_key_and_database_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    base = hashlib.sha256(b"<h1>Onyx</h1>\n").hexdigest()
    workspace.create_draft(
        relative_path="index.html", content="safe", expected_base_digest=base
    )
    with pytest.raises(SiteWorkspaceDenied, match="key or scope"):
        _workspace(
            tmp_path,
            root=workspace.root,
            key=b"another-key-that-is-clearly-long-enough-000",
        )
    other = SiteWorkspaceScopeV1(
        "owner.other", "workspace.main", "site.cyryx", "cyryx-labs/onyx-site"
    )
    with pytest.raises(SiteWorkspaceDenied, match="key or scope"):
        _workspace(tmp_path, root=workspace.root, scope=other)
    with sqlite3.connect(workspace.state_path) as connection:
        connection.execute("UPDATE drafts SET content_digest=?", ("0" * 64,))
    with pytest.raises(SiteWorkspaceError, match="drafts integrity"):
        _workspace(tmp_path, root=workspace.root)


def test_record_deletion_and_schema_tamper_are_detected_on_reopen(
    tmp_path: Path,
) -> None:
    deleted_root = _git_root(tmp_path / "deleted")
    deleted = _workspace(tmp_path / "deleted", root=deleted_root)
    base = hashlib.sha256(b"<h1>Onyx</h1>\n").hexdigest()
    deleted.create_draft(
        relative_path="index.html", content="safe", expected_base_digest=base
    )
    with sqlite3.connect(deleted.state_path) as connection:
        connection.execute("DELETE FROM drafts")
    with pytest.raises(SiteWorkspaceError, match="state root"):
        _workspace(tmp_path / "deleted", root=deleted_root)

    schema_root = _git_root(tmp_path / "schema")
    schema = _workspace(tmp_path / "schema", root=schema_root)
    with sqlite3.connect(schema.state_path) as connection:
        connection.execute("CREATE INDEX attacker_index ON drafts(relative_path)")
    with pytest.raises(SiteWorkspaceError, match="schema objects"):
        _workspace(tmp_path / "schema", root=schema_root)


def test_owner_approval_is_host_issued_exact_scope_and_not_publicly_forgeable(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, approver=lambda _request: False)
    base = hashlib.sha256(b"<h1>Onyx</h1>\n").hexdigest()
    draft = workspace.create_draft(
        relative_path="index.html", content="safe", expected_base_digest=base
    )
    plan = workspace.plan_apply_draft(
        draft.draft_id, idempotency_key="approval:test:0001"
    )
    with pytest.raises(SiteWorkspaceDenied, match="not granted"):
        workspace.issue_owner_approval(plan)
    with pytest.raises(SiteWorkspaceDenied, match="host-issued"):
        SiteOwnerApprovalCapabilityV1(
            object(), "fake", workspace.scope_digest, plan.plan_digest
        )


def test_preview_is_a_supervised_plan_and_starts_nothing(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    preview = workspace.plan_preview()
    assert preview.relative_path == "index.html"
    assert preview.listener_started is preview.browser_started is False
    assert preview.process_calls == 0


def test_git_plans_are_exact_argv_and_reject_destructive_or_malformed_inputs(
    tmp_path: Path,
) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root)
    workspace = _workspace(tmp_path, root=root, git=fake)
    status = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:status:0001",
    )
    status_argv = status.argv
    assert status_argv[0] == "git"
    assert status_argv[-4:] == ("status", "--porcelain=v2", "--branch", "--")
    assert "core.fsmonitor=false" in status_argv
    diff = workspace.plan_git(
        operation=GitOperationV1.STAGED_DIFF,
        expected_branch="main",
        idempotency_key="git:diff:00001",
    )
    assert diff.argv[-6:-3] == ("diff", "--cached", "--no-ext-diff")
    diff_receipt = workspace.execute_git(diff, workspace.issue_owner_approval(diff))
    commit = workspace.plan_git(
        operation=GitOperationV1.COMMIT,
        expected_branch="main",
        message="Update governed site",
        idempotency_key="git:commit:001",
        staged_diff_receipt_id=diff_receipt.receipt_id,
    )
    argv = commit.argv
    assert (
        argv[0] == "git"
        and any(item.startswith("core.hooksPath=") for item in argv)
        and "commit.gpgSign=false" in argv
    )
    assert not any(
        item in argv for item in ("reset", "clean", "push", "checkout", "-c rm -rf")
    )
    with pytest.raises(SiteWorkspaceContractError):
        workspace.plan_git(
            operation=GitOperationV1.ROLLBACK,
            expected_branch="main",
            rollback_commit="HEAD~1",
            idempotency_key="git:rollback:01",
        )
    with pytest.raises(SiteWorkspaceContractError):
        workspace.plan_git(
            operation=GitOperationV1.COMMIT,
            expected_branch="main",
            message="-c rm -rf /",
            idempotency_key="git:commit:002",
            staged_diff_receipt_id=diff_receipt.receipt_id,
        )
    with pytest.raises(SiteWorkspaceDenied, match="staged-diff"):
        workspace.plan_git(
            operation=GitOperationV1.COMMIT,
            expected_branch="main",
            message="Uninspected commit",
            idempotency_key="git:commit:003",
        )
    with pytest.raises(SiteWorkspaceContractError):
        workspace.plan_git(
            operation="reset", expected_branch="main", idempotency_key="git:reset:0001"
        )  # type: ignore[arg-type]


def test_git_branch_drift_is_denied_before_injected_executor(tmp_path: Path) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root)
    workspace = _workspace(tmp_path, root=root, git=fake)
    plan = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:drift:0001",
    )
    capability = workspace.issue_owner_approval(plan)
    (root / ".git" / "refs" / "heads" / "main").write_text(
        "4" * 40 + "\n", encoding="ascii"
    )
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        workspace.execute_git(plan, capability)
    assert fake.calls == []


def test_staged_index_drift_is_denied_before_diff_or_commit(tmp_path: Path) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root)
    workspace = _workspace(tmp_path, root=root, git=fake)
    diff = workspace.plan_git(
        operation=GitOperationV1.STAGED_DIFF,
        expected_branch="main",
        idempotency_key="git:index:00001",
    )
    (root / ".git" / "index").write_bytes(b"changed after planning")
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        workspace.execute_git(diff, workspace.issue_owner_approval(diff))
    assert fake.calls == []


def test_git_unknown_is_not_retried_and_requires_typed_reconciliation(
    tmp_path: Path,
) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root, fail=True)
    workspace = _workspace(tmp_path, root=root, git=fake)
    plan = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:unknown:001",
    )
    capability = workspace.issue_owner_approval(plan)
    with pytest.raises(SiteWorkspaceOutcomeUnknown, match="reconciliation"):
        workspace.execute_git(plan, capability)
    assert len(fake.calls) == 1
    with pytest.raises(SiteWorkspaceDenied, match="unknown"):
        workspace.issue_owner_approval(plan)
    with pytest.raises(SiteWorkspaceOutcomeUnknown, match="remains unknown"):
        workspace.reconcile_git(plan)
    fake.reconciled = GitExecutionResultV1(
        0,
        str(root),
        "main",
        "observed",
        "",
        "refs/heads/main",
        MAIN_OID,
        ABSENT_DIGEST,
        MAIN_OID,
        ABSENT_DIGEST,
        "a" * 64,
    )
    receipt = workspace.reconcile_git(plan)
    assert receipt.outcome == "git_reconciled" and len(receipt.effect_digest) == 64
    assert receipt.effect_digest != "a" * 64
    assert workspace.reconcile_git(plan) == receipt
    assert len(fake.calls) == 1


def test_rollback_is_only_exact_revert_and_has_rollback_receipt(tmp_path: Path) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root)
    workspace = _workspace(tmp_path, root=root, git=fake)
    commit = "a" * 40
    plan = workspace.plan_git(
        operation=GitOperationV1.ROLLBACK,
        expected_branch="main",
        rollback_commit=commit,
        idempotency_key="git:rollback:001",
    )
    argv = plan.argv
    assert "revert" in argv and commit in argv and "reset" not in argv
    receipt = workspace.execute_git(plan, workspace.issue_owner_approval(plan))
    assert receipt.outcome == "rollback_verified"


def test_idempotency_payload_conflict_and_plan_tamper_are_denied(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    one = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:same:000001",
    )
    assert (
        workspace.plan_git(
            operation=GitOperationV1.STATUS,
            expected_branch="main",
            idempotency_key="git:same:000001",
        )
        == one
    )
    with pytest.raises(SiteWorkspaceDenied, match="another operation"):
        workspace.plan_git(
            operation=GitOperationV1.STAGED_DIFF,
            expected_branch="main",
            idempotency_key="git:same:000001",
        )
    object.__setattr__(one, "operation", "git.reset")
    with pytest.raises(SiteWorkspaceDenied, match="authentication"):
        workspace.issue_owner_approval(one)


def test_github_is_plan_only_without_exact_official_adapter_and_never_accepts_url_repository(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan = workspace.plan_github(
        operation=GitHubOperationV1.CREATE_PULL_REQUEST,
        expected_branch="main",
        title="Review site",
        body="Bounded change",
        idempotency_key="github:pr:00001",
    )
    assert plan.payload["repository"] == "cyryx-labs/onyx-site"
    assert plan.payload["provider"] == "official_github_api"
    with pytest.raises(SiteWorkspaceDenied, match="adapter"):
        workspace.execute_github(plan, workspace.issue_owner_approval(plan))
    with pytest.raises(SiteWorkspaceContractError, match="owner/name"):
        SiteWorkspaceScopeV1(
            "owner.primary",
            "workspace.main",
            "site.cyryx",
            "https://token@github.com/cyryx/site.git",
        )


def test_clean_reopen_preserves_authenticated_receipt(tmp_path: Path) -> None:
    root = _git_root(tmp_path)
    fake = FakeGit(root)
    workspace = _workspace(tmp_path, root=root, git=fake)
    plan = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:reopen:0001",
    )
    receipt = workspace.execute_git(plan, workspace.issue_owner_approval(plan))
    reopened = _workspace(tmp_path, root=root, git=fake)
    reopened.verify_integrity()
    assert reopened.get_receipt(plan.intent_id) == receipt


def test_sqlite_connections_release_windows_rename_and_delete_handles(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.list_files()
    workspace.verify_integrity()
    moved = workspace.state_path.with_suffix(".moved")
    os.replace(workspace.state_path, moved)
    moved.unlink()
    assert not moved.exists()


def test_public_git_argv_is_exact_immutable_tuple_not_payload_list(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    plan = workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:immutable:01",
    )
    assert type(plan.argv) is tuple and "argv" not in plan.payload
    with pytest.raises(TypeError):
        plan.payload["branch"] = "other"  # type: ignore[index]


def test_packed_ref_and_linked_worktree_layout_resolve_exact_commit(
    tmp_path: Path,
) -> None:
    packed_root = _git_root(tmp_path / "packed")
    (packed_root / ".git" / "refs" / "heads" / "main").unlink()
    (packed_root / ".git" / "packed-refs").write_text(
        "# pack-refs with: peeled fully-peeled\n" + MAIN_OID + " refs/heads/main\n",
        encoding="ascii",
    )
    packed = _workspace(tmp_path / "packed", root=packed_root)
    packed_plan = packed.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:packed:0001",
    )
    assert packed_plan.payload["head_oid"] == MAIN_OID

    base = tmp_path / "linked"
    root = base / "site"
    root.mkdir(parents=True)
    (root / "index.html").write_bytes(b"linked worktree")
    common = base / "repository.git"
    git_dir = common / "worktrees" / "site"
    (common / "refs" / "heads").mkdir(parents=True)
    git_dir.mkdir(parents=True)
    (common / "refs" / "heads" / "main").write_text(MAIN_OID + "\n", encoding="ascii")
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
    (git_dir / "commondir").write_text("../..\n", encoding="ascii")
    (root / ".git").write_text(f"gitdir: {git_dir}\n", encoding="utf-8")
    linked = _workspace(base, root=root)
    linked_plan = linked.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:worktree:001",
    )
    assert linked_plan.payload["head_oid"] == MAIN_OID
    assert linked_plan.payload["head_ref"] == "refs/heads/main"


def test_every_git_operation_rejects_pre_or_post_snapshot_drift(
    tmp_path: Path,
) -> None:
    root = _git_root(tmp_path / "status")
    status_fake = FakeGit(root)
    status_workspace = _workspace(tmp_path / "status", root=root, git=status_fake)
    status = status_workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:status-drift:1",
    )
    (root / ".git" / "index").write_bytes(b"status index drift")
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        status_workspace.execute_git(
            status, status_workspace.issue_owner_approval(status)
        )
    assert status_fake.calls == []

    rollback_root = _git_root(tmp_path / "rollback")
    rollback_fake = FakeGit(rollback_root)
    rollback_workspace = _workspace(
        tmp_path / "rollback", root=rollback_root, git=rollback_fake
    )
    rollback = rollback_workspace.plan_git(
        operation=GitOperationV1.ROLLBACK,
        expected_branch="main",
        rollback_commit="a" * 40,
        idempotency_key="git:rollback-drift:1",
    )
    (rollback_root / ".git" / "index").write_bytes(b"rollback index drift")
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        rollback_workspace.execute_git(
            rollback, rollback_workspace.issue_owner_approval(rollback)
        )
    assert rollback_fake.calls == []

    post_root = _git_root(tmp_path / "post")
    post_fake = DriftingReadGit(post_root)
    post_workspace = _workspace(tmp_path / "post", root=post_root, git=post_fake)
    post = post_workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:post-drift:01",
    )
    with pytest.raises(SiteWorkspaceOutcomeUnknown, match="reconciliation"):
        post_workspace.execute_git(post, post_workspace.issue_owner_approval(post))


def test_commit_and_reconcile_reject_index_or_head_drift(
    tmp_path: Path,
) -> None:
    commit_root = _git_root(tmp_path / "commit")
    commit_fake = FakeGit(commit_root)
    commit_workspace = _workspace(
        tmp_path / "commit", root=commit_root, git=commit_fake
    )
    diff = commit_workspace.plan_git(
        operation=GitOperationV1.STAGED_DIFF,
        expected_branch="main",
        idempotency_key="git:commit-diff:1",
    )
    diff_receipt = commit_workspace.execute_git(
        diff, commit_workspace.issue_owner_approval(diff)
    )
    commit = commit_workspace.plan_git(
        operation=GitOperationV1.COMMIT,
        expected_branch="main",
        message="Inspected change",
        staged_diff_receipt_id=diff_receipt.receipt_id,
        idempotency_key="git:commit-drift:1",
    )
    (commit_root / ".git" / "index").write_bytes(b"post-plan commit drift")
    with pytest.raises(SiteWorkspaceDenied, match="changed after planning"):
        commit_workspace.execute_git(
            commit, commit_workspace.issue_owner_approval(commit)
        )
    assert len(commit_fake.calls) == 1

    reconcile_root = _git_root(tmp_path / "reconcile")
    reconcile_fake = FakeGit(reconcile_root, fail=True)
    reconcile_workspace = _workspace(
        tmp_path / "reconcile", root=reconcile_root, git=reconcile_fake
    )
    status = reconcile_workspace.plan_git(
        operation=GitOperationV1.STATUS,
        expected_branch="main",
        idempotency_key="git:reconcile-drift:1",
    )
    with pytest.raises(SiteWorkspaceOutcomeUnknown):
        reconcile_workspace.execute_git(
            status, reconcile_workspace.issue_owner_approval(status)
        )
    reconcile_fake.reconciled = GitExecutionResultV1(
        0,
        str(reconcile_root),
        "main",
        "stale result",
        "",
        "refs/heads/main",
        MAIN_OID,
        ABSENT_DIGEST,
        MAIN_OID,
        ABSENT_DIGEST,
        "b" * 64,
    )
    (reconcile_root / ".git" / "refs" / "heads" / "main").write_text(
        "6" * 40 + "\n", encoding="ascii"
    )
    with pytest.raises(SiteWorkspaceOutcomeUnknown, match="scope diverged"):
        reconcile_workspace.reconcile_git(status)


def test_apply_unknown_reconciles_from_observed_content_without_second_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _workspace(tmp_path)
    base = hashlib.sha256(b"<h1>Onyx</h1>\n").hexdigest()
    draft = workspace.create_draft(
        relative_path="index.html", content="reconciled", expected_base_digest=base
    )
    plan = workspace.plan_apply_draft(
        draft.draft_id, idempotency_key="apply:unknown:01"
    )
    original = os.replace

    def replace_then_raise(source, target):
        original(source, target)
        raise OSError("lost acknowledgement")

    monkeypatch.setattr(os, "replace", replace_then_raise)
    with pytest.raises(SiteWorkspaceOutcomeUnknown):
        workspace.execute_apply_draft(plan, workspace.issue_owner_approval(plan))
    monkeypatch.setattr(os, "replace", original)
    receipt = workspace.reconcile_apply_draft(plan)
    assert (
        receipt.outcome == "applied_reconciled"
        and workspace.read_text("index.html") == "reconciled"
    )
