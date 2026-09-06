from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "onyx"


def _text(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_current_status_is_the_single_release_authority() -> None:
    status = _text("CURRENT_RELEASE_STATUS.md")
    index = _text("DOCUMENTATION_INDEX.md")

    assert (
        "Current installed product: **Onyx 1.1.9 Windows x64 V41, unsigned diagnostic**"
        in status
    )
    assert "Current frozen source: **V44, source-validated" in status
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in status
    assert "CURRENT_RELEASE_STATUS.md" in index
    assert "Current truth: V44 source frozen; V41 installed diagnostic" in index
    assert "Phase 5 V44 transition" in index
    assert "Release Workflow V44 transition" in index


def test_stale_top_level_documents_are_explicitly_classified() -> None:
    superseded = (
        "CURRENT_STATE_AUDIT.md",
        "GAP_ANALYSIS.md",
        "IMPLEMENTATION_ROADMAP.md",
        "OPERATIONAL_TODAY.md",
        "RELEASE_CUT_TODAY.md",
    )
    baselines = (
        "APPROVAL_POLICY.md",
        "CAPABILITY_MATRIX.md",
        "DATA_AND_MEMORY_BOUNDARIES.md",
        "TARGET_ARCHITECTURE.md",
        "THREAT_MODEL.md",
        "VERIFICATION_EVIDENCE.md",
    )

    for name in superseded:
        assert "superseded" in "\n".join(_text(name).splitlines()[:12]).casefold()
    for name in baselines:
        head = "\n".join(_text(name).splitlines()[:14]).casefold()
        assert "baseline" in head or "historical evidence" in head
        assert "current_release_status.md" in head


def test_current_status_preserves_external_and_human_gates() -> None:
    status = _text("CURRENT_RELEASE_STATUS.md")

    for gate in (
        "PARTIAL",
        "EXTERNAL_ENTRA_REQUIRED",
        "NATIVE_RUNNER_REQUIRED",
        "OWNER_OR_LEGAL_APPROVAL_REQUIRED",
        "REVIEWER_REQUIRED",
    ):
        assert gate in status
    assert "Formal/public status: **NOT RELEASE-ELIGIBLE**" in status
    assert "Onyx 1.1.9 is not complete" in status
    assert "every open gate has candidate-bound passing" in status


def test_current_status_binds_soak_to_the_exact_current_candidate() -> None:
    status = _text("CURRENT_RELEASE_STATUS.md")
    runtime_delta = (DOCS / "operations" / "ONYX_1_1_8_RUNTIME_EQUIVALENCE.md").read_text(
        encoding="utf-8"
    )

    assert (
        "| Windows long session | `IN_PROGRESS_MONITOR_FALSE_NEGATIVE_V41` |"
        in status
    )
    assert "rerun with the corrected V44 monitor" in status
    assert "interim data cannot pass the gate" in status
    assert "ONYX_1_1_9_V41_WINDOWS_LONG_SESSION_RECEIPT.json" in (
        DOCS / "operations" / "ONYX_1_1_9_V41_WINDOWS_ACCEPTANCE_2026-08-10.md"
    ).read_text(encoding="utf-8")
    assert "cannot be transferred to 1.1.8" in runtime_delta
    assert "byte-equivalent to\n1.1.7" in runtime_delta


def test_final_sbom_lifecycle_and_legal_approval_remain_open() -> None:
    status = _text("CURRENT_RELEASE_STATUS.md")
    legal = _text("LEGAL_RELEASE_APPROVAL_1.1.9.md")
    review = _text("FINAL_EVIDENCE_REVIEW_PROTOCOL.md")

    assert "| Final SBOM | `WINDOWS_TECHNICAL_ONLY` |" in status
    assert "V41 Windows reconciliation passed" in status
    assert "final signed all-platform shipped set absent" in status
    assert "| Windows signing/trust | `EXTERNAL_CREDENTIAL_REQUIRED` |" in status
    assert "| macOS | `NATIVE_RUNNER_REQUIRED` |" in status
    assert "| Linux packages | `FAILED_PRECHECK_V41` |" in status
    assert "packaged preflight exited 70" in status
    assert "Status: **approval required**" in legal
    assert "This engineering result is\nnot legal approval" in legal
    assert "state remains `REVIEW_REQUIRED`" in review


def test_key_v23_v24_predecessors_are_directly_marked_superseded() -> None:
    predecessors = (
        "ONYX_PROJECT_COMPLETION_ROADMAP_2026-08-04.md",
        "ONYX_PROJECT_COMPLETION_ROADMAP_V23_2026-08-04.md",
        "ONYX_PROJECT_COMPLETION_ROADMAP_V24_2026-08-04.md",
        "operations/ONYX_1_1_9_V24_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V24_COMPLIANCE_TECHNICAL_CHECKPOINT_2026-08-04.md",
        "operations/ONYX_1_1_9_V24_EXTERNAL_RELEASE_PREREQUISITES_2026-08-04.md",
    )
    for name in predecessors:
        head = "\n".join(_text(name).splitlines()[:8]).casefold()
        assert "superseded for current-state claims" in head


def test_versioned_operational_predecessors_cannot_look_current() -> None:
    superseded = (
        "operations/ONYX_1_1_8_MACOS_RELEASE_PIPELINE.md",
        "operations/ONYX_1_1_9_EXTERNAL_RELEASE_PREREQUISITES_2026-08-03.md",
        "operations/ONYX_1_1_9_V14_COMPLIANCE_TECHNICAL_CHECKPOINT_2026-08-03.md",
        "operations/ONYX_1_1_9_V14_WINDOWS_ACCEPTANCE_2026-08-03.md",
        "operations/ONYX_1_1_9_V17_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V18_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V19_COMPLIANCE_TECHNICAL_CHECKPOINT_2026-08-04.md",
        "operations/ONYX_1_1_9_V19_VOICE_ROTATION_SOURCE_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V19_WINDOWS_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V20_LINUX_DIAGNOSTIC_ACCEPTANCE_2026-08-04.md",
        "operations/ONYX_1_1_9_V21_ADVANCED_OPERATIONS_WINDOWS_ACCEPTANCE_2026-08-03.md",
        "operations/ONYX_1_1_9_V21_INSTALLED_MISSION_RECOVERY_ACCEPTANCE_2026-08-03.md",
        "operations/ONYX_V11_LIVE_PROMOTION_2026-07-23.md",
        "operations/ONYX_V13_LIVE_PROMOTION_2026-07-23.md",
        "operations/ONYX_V17_FOUNDER_SNAPSHOT_ACCEPTANCE_2026-07-31.md",
        "operations/ONYX_V18_DOCUMENT_INTAKE_ACCEPTANCE_2026-07-31.md",
        "operations/ONYX_V19_1_OPERATIONAL_CLOSURE_2026-08-01.md",
        "operations/ONYX_V19_DAYOPS_ACCEPTANCE_2026-07-31.md",
    )
    baselines = (
        "ONYX_DAYOPS_V14.md",
        "PHASE11_GOVERNED_AWAY_V1.md",
        "operations/ONYX_1_1_8_POSIX_OWNER_AUTHORITY.md",
        "operations/ONYX_WINDOWS_1_1_0_UPGRADE_ROLLBACK.md",
        "operations/PHASE11_EXECUTABLE_SANDBOX_V1.md",
        "operations/PHASE11_EXTERNAL_AGENT_ADAPTER_V1.md",
        "operations/PHASE11_PROJECT_AUTOPILOT_V1_RUNBOOK.md",
    )

    for name in superseded:
        head = "\n".join(_text(name).splitlines()[:10]).casefold()
        assert "superseded for current-state claims" in head
        assert "current_release_status.md" in head
    for name in baselines:
        head = "\n".join(_text(name).splitlines()[:12]).casefold()
        assert "version-bound" in head
        assert "current_release_status.md" in head


def test_dayops_onboarding_is_procedure_not_acceptance_evidence() -> None:
    head = "\n".join(
        _text("PHASE8_MICROSOFT_GRAPH_LIVE_ONBOARDING.md").splitlines()[:12]
    ).casefold()
    assert "current external procedure" in head
    assert "not pass evidence" in head
    assert "current_release_status.md" in head
