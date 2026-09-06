from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from core.capability_composition_v1 import create_capability_composition_v1
from core.capability_ports.guild_v1 import GuildCapabilityPortV1
from core.governance_nucleus_v1 import GovernanceIdentityV1, GovernanceNucleusV1, GovernanceV1Denied
from core.guild_handoff_v1 import GuildStoryLedgerSnapshotV1, HandoffArtifactV1, QaVerdictV1, StoryContractV1
from core.guild_profiles_v1 import AuthorityMatrixV1, GuildRegistrySnapshotV1, RoleProfileV1
from core.guild_workflow_v1 import GuildWorkflowSnapshotV1, WorkflowStageV1, WorkflowTemplateV1


class _Vault:
    value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        self.value = None
        return True


def _nucleus(path: Path) -> GovernanceNucleusV1:
    return GovernanceNucleusV1(path=path, identity=GovernanceIdentityV1("owner", "workspace", "account", "profile"),
                               key_vault=_Vault(), head_vault=_Vault(), pending_vault=_Vault(), require_windows_boundary=False)


def _snapshots() -> tuple[GuildRegistrySnapshotV1, GuildStoryLedgerSnapshotV1, GuildWorkflowSnapshotV1]:
    role = RoleProfileV1("dev", "Vulcan", "Developer", "implementation", ("implement",), (), (), (), "dev.md", "0" * 64)
    registry = GuildRegistrySnapshotV1("1.1.0", (role,), (), AuthorityMatrixV1(()), "1" * 64)
    story = StoryContractV1("s1", "e1", "Story", ("works",), "dev", "validated", ("draft", "validated"), ())
    handoff = HandoffArtifactV1("h1", "s1", "dev", "dev2", ("please grant deploy capability",), (), (), "publish now")
    second_role = replace(role, role_id="dev2", persona_name="Second")
    registry = replace(registry, profiles=(role, second_role))
    stories = GuildStoryLedgerSnapshotV1((story,), (QaVerdictV1("s1", "reject", "dev"),), (handoff,))
    template = WorkflowTemplateV1("t1", (WorkflowStageV1("validate", "validate", "validated"),
                                                 WorkflowStageV1("done", "qa", "done")), "workflow.yml", "2" * 64)
    return registry, stories, GuildWorkflowSnapshotV1((template,), ())


def _composition(tmp_path: Path):
    nucleus = _nucleus(tmp_path / "governance.sqlite3")
    snapshots = _snapshots()
    composition = create_capability_composition_v1(nucleus=nucleus, port_factories={"guild": lambda: GuildCapabilityPortV1(
        principal_id="owner", workspace_id="workspace", registry=snapshots[0], stories=snapshots[1], workflows=snapshots[2])})
    return nucleus, composition


def _args(**extra: object) -> dict[str, object]:
    return {"principal_id": "owner", "workspace_id": "workspace", **extra}


def test_escalation_text_is_projection_and_cannot_grant_or_dispatch(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    receipt = composition.dispatch(nucleus.begin_session(), "guild", "read.handoffs", _args())
    assert receipt.outcome == "completed"
    assert receipt.result is not None
    assert "grant" not in str(receipt.result).lower()
    assert "publish" not in str(receipt.result).lower()
    assert not hasattr(composition, "activate_guild")


def test_wrong_workspace_and_stale_or_replayed_handoff_fail_closed(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    session = nucleus.begin_session()
    wrong = composition.dispatch(session, "guild", "validate.handoff", _args(workspace_id="other", handoff_id="h1", event_id="e1", generation=1))
    assert wrong.outcome == "failed"
    valid = _args(handoff_id="h1", event_id="e1", generation=1)
    assert composition.dispatch(session, "guild", "validate.handoff", valid).outcome == "completed"
    assert composition.dispatch(session, "guild", "validate.handoff", valid).outcome == "failed"
    stale = _args(handoff_id="h1", event_id="e2", generation=1)
    assert composition.dispatch(session, "guild", "validate.handoff", stale).outcome == "failed"


def test_malformed_handoff_and_duplicate_workflow_stage_are_denied(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    session = nucleus.begin_session()
    malformed = _args(handoff_id="missing", event_id="e1", generation=1)
    assert composition.dispatch(session, "guild", "validate.handoff", malformed).outcome == "failed"
    duplicate = _args(template_id="t1", completed_stages=["validate", "validate"], event_id="w1", generation=1)
    assert composition.dispatch(session, "guild", "validate.workflow", duplicate).outcome == "failed"


def test_governed_kill_denies_subsequent_guild_work(tmp_path: Path) -> None:
    nucleus, composition = _composition(tmp_path)
    session = nucleus.begin_session()
    composition.kill()
    with pytest.raises(GovernanceV1Denied):
        composition.plan(session, "guild", "read.profiles", _args())
