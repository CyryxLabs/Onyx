from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core import social_publish_v1 as mod
from scripts import onyx_social_cli


ROOT = Path(__file__).resolve().parents[1]


class FakeProvider:
    def __init__(self, *, dispatch_error=None, observation=None, observe_error=None):
        self.dispatch_error = dispatch_error
        self.observation = observation or mod.ProviderObservationV1(
            "verified", "post-1"
        )
        self.observe_error = observe_error
        self.dispatches = []
        self.observations = []

    def dispatch(self, request):
        self.dispatches.append(request)
        if self.dispatch_error:
            raise self.dispatch_error
        return mod.ProviderReceiptV1("provider-request-1", "post-1")

    def observe(self, receipt):
        self.observations.append(receipt)
        if self.observe_error:
            raise self.observe_error
        return self.observation


def test_social_cli_direct_entrypoint_loads_project_without_pythonpath() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/onyx_social_cli.py", "--help"],
        cwd=ROOT,
        env={"PATH": ""},
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "publish-preview" in completed.stdout


def request(**changes):
    values = {
        "workspace_id": "workspace-1",
        "principal_id": "owner-1",
        "account_id": "account-1",
        "target": "instagram-feed",
        "caption": "Evidence-bound caption.",
        "media_digests": ("a" * 64,),
        "provenance": ("draft:d1", "evidence:e1"),
        "warnings": ("Verify time-sensitive claims before publication.",),
    }
    values.update(changes)
    return mod.CaptionRequestV1(**values)


def service(tmp_path, fake=None, *, name="social.sqlite3"):
    fake = fake or FakeProvider()
    return mod.create_social_publication_v1(
        gate=mod.SocialPublishFeatureGateV1(True),
        adapter=fake,
        ledger_path=(tmp_path / name).resolve(),
    ), fake


def cli_request_args(command="publish-preview"):
    return [
        command,
        "--workspace-id",
        "workspace-1",
        "--principal-id",
        "owner-1",
        "--account-id",
        "account-1",
        "--target",
        "instagram-feed",
        "--caption",
        "Evidence-bound caption.",
        "--media-digest",
        "a" * 64,
        "--provenance",
        "draft:d1",
        "--provenance",
        "evidence:e1",
        "--warning",
        "Verify time-sensitive claims before publication.",
    ]


def test_local_caption_generation_is_stable_draft_only_with_provenance_warnings():
    item = mod.CaptionGenerationRequestV1(
        brief="Explain governed execution.",
        brand="Cyryx",
        platform="linkedin",
        source_refs=("brief:42",),
    )
    first = mod.generate_caption_draft(item)
    second = mod.generate_caption_draft(item)
    assert first == second
    assert first.status == "draft"
    assert first.caption == "Cyryx — Explain governed execution."
    assert f"request:{first.request_identity}" in first.provenance
    assert "source:brief:42" in first.provenance
    assert len(first.warnings) == 2


def test_local_generation_identity_changes_with_brief_brand_or_platform():
    base = mod.CaptionGenerationRequestV1("brief", "brand", "linkedin")
    identity = mod.generate_caption_draft(base).request_identity
    variants = (
        mod.CaptionGenerationRequestV1("changed", "brand", "linkedin"),
        mod.CaptionGenerationRequestV1("brief", "other", "linkedin"),
        mod.CaptionGenerationRequestV1("brief", "brand", "instagram"),
    )
    assert all(
        mod.generate_caption_draft(item).request_identity != identity
        for item in variants
    )


def test_local_generation_rejects_unknown_platform():
    with pytest.raises(mod.SocialPublishContractError):
        mod.CaptionGenerationRequestV1("brief", "brand", "unknown")


def test_preview_is_deterministic_provider_independent_and_carries_governance():
    first = mod.preview_caption(request())
    second = mod.preview_caption(request())
    assert first == second
    assert first.provenance == ("draft:d1", "evidence:e1")
    assert first.warnings
    assert first.consent_text == f"PUBLISH EXACT PREVIEW {first.request_digest}"


def test_preview_digest_changes_for_payload_account_media_and_target_drift():
    base = mod.preview_caption(request()).request_digest
    variants = (
        request(caption="changed"),
        request(account_id="account-2"),
        request(media_digests=("b" * 64,)),
        request(target="linkedin-company"),
    )
    assert all(mod.preview_caption(item).request_digest != base for item in variants)


def test_feature_gate_default_off_and_enabled_requires_injected_adapter():
    assert mod.SocialPublishFeatureGateV1.from_environ({}).enabled is False
    assert (
        mod.create_social_publication_v1(gate=mod.SocialPublishFeatureGateV1(False))
        is None
    )
    with pytest.raises(mod.SocialPublishDenied):
        mod.create_social_publication_v1(gate=mod.SocialPublishFeatureGateV1(True))


def test_exact_consent_one_dispatch_receipt_and_readback_verified(tmp_path):
    runtime, fake = service(tmp_path)
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    result = runtime.dispatch(item)
    assert result.status == "verified"
    assert result.receipt.content_id == "post-1"
    assert result.observation.outcome == "verified"
    assert len(fake.dispatches) == 1
    assert fake.dispatches[0].idempotency_key == preview.preview.request_digest


def test_wrong_consent_and_drift_have_no_provider_effect(tmp_path):
    runtime, fake = service(tmp_path)
    item = request()
    runtime.create_preview(item)
    with pytest.raises(mod.SocialPublishDenied):
        runtime.consent(item, exact_consent="yes")
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    with pytest.raises(mod.SocialPublishDenied):
        runtime.dispatch(request(caption="drifted"))
    assert runtime.status(preview.preview.request_digest).status == "invalidated"
    assert fake.dispatches == []


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "account-2"},
        {"target": "linkedin-company"},
        {"media_digests": ("b" * 64,)},
    ],
)
def test_new_preview_invalidates_prior_consent_on_bound_target_drift(tmp_path, changes):
    runtime, fake = service(tmp_path)
    item = request()
    first = runtime.create_preview(item)
    runtime.consent(item, exact_consent=first.preview.consent_text)
    runtime.create_preview(request(**changes))
    assert runtime.status(first.preview.request_digest).status == "invalidated"
    with pytest.raises(mod.SocialPublishDenied):
        runtime.dispatch(item)
    assert fake.dispatches == []


def test_duplicate_dispatch_is_denied_without_second_effect(tmp_path):
    runtime, fake = service(tmp_path)
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    runtime.dispatch(item)
    with pytest.raises(mod.SocialPublishDenied):
        runtime.dispatch(item)
    assert len(fake.dispatches) == 1


def test_restart_preserves_consent_and_prevents_duplicate_dispatch(tmp_path):
    path = (tmp_path / "restart.sqlite3").resolve()
    fake = FakeProvider()
    first = mod.create_social_publication_v1(
        gate=mod.SocialPublishFeatureGateV1(True), adapter=fake, ledger_path=path
    )
    item = request()
    preview = first.create_preview(item)
    first.consent(item, exact_consent=preview.preview.consent_text)

    restarted = mod.create_social_publication_v1(
        gate=mod.SocialPublishFeatureGateV1(True), adapter=fake, ledger_path=path
    )
    assert restarted.dispatch(item).status == "verified"
    again = mod.create_social_publication_v1(
        gate=mod.SocialPublishFeatureGateV1(True), adapter=fake, ledger_path=path
    )
    with pytest.raises(mod.SocialPublishDenied, match="blind retry"):
        again.dispatch(item)
    assert len(fake.dispatches) == 1


def test_atomic_claim_allows_one_dispatch_across_live_instances(tmp_path):
    path = (tmp_path / "race.sqlite3").resolve()
    fake = FakeProvider()
    first = mod.SocialPublicationV1(fake, path)
    second = mod.SocialPublicationV1(fake, path)
    item = request()
    preview = first.create_preview(item)
    first.consent(item, exact_consent=preview.preview.consent_text)

    def attempt(runtime):
        try:
            return runtime.dispatch(item).status
        except mod.SocialPublishDenied:
            return "denied"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))
    assert sorted(outcomes) == ["denied", "verified"]
    assert len(fake.dispatches) == 1


def test_interrupted_committed_claim_reopens_uncertain_without_retry(tmp_path):
    path = (tmp_path / "interrupted.sqlite3").resolve()
    fake = FakeProvider()
    runtime = mod.SocialPublicationV1(fake, path)
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE social_publications_v1 SET status='dispatching', dispatch_attempted=1 "
            "WHERE request_digest=?",
            (preview.preview.request_digest,),
        )

    restarted = mod.SocialPublicationV1(fake, path)
    assert restarted.status(preview.preview.request_digest).status == (
        "uncertain_needs_reconciliation"
    )
    with pytest.raises(mod.SocialPublishDenied, match="blind retry"):
        restarted.dispatch(item)
    assert fake.dispatches == []


def test_restart_payload_drift_invalidates_exact_consent(tmp_path):
    path = (tmp_path / "drift.sqlite3").resolve()
    fake = FakeProvider()
    first = mod.SocialPublicationV1(fake, path)
    item = request()
    preview = first.create_preview(item)
    first.consent(item, exact_consent=preview.preview.consent_text)

    restarted = mod.SocialPublicationV1(fake, path)
    restarted.create_preview(request(caption="changed after restart"))
    assert restarted.status(preview.preview.request_digest).status == "invalidated"
    with pytest.raises(mod.SocialPublishDenied):
        restarted.dispatch(item)
    assert fake.dispatches == []


def test_dispatch_exception_is_uncertain_and_never_blindly_retried(tmp_path):
    runtime, fake = service(
        tmp_path, FakeProvider(dispatch_error=TimeoutError("after send"))
    )
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    with pytest.raises(mod.SocialPublishUncertain):
        runtime.dispatch(item)
    assert (
        runtime.status(preview.preview.request_digest).status
        == "uncertain_needs_reconciliation"
    )
    with pytest.raises(mod.SocialPublishDenied):
        runtime.dispatch(item)
    assert len(fake.dispatches) == 1


def test_ambiguous_readback_reconciles_without_redispatch(tmp_path):
    fake = FakeProvider(observation=mod.ProviderObservationV1("unknown", None))
    runtime, _ = service(tmp_path, fake)
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    result = runtime.dispatch(item)
    assert result.status == "uncertain_needs_reconciliation"
    fake.observation = mod.ProviderObservationV1("verified", "post-1")
    reconciled = runtime.reconcile(preview.preview.request_digest)
    assert reconciled.status == "verified"
    assert len(fake.dispatches) == 1
    assert len(fake.observations) == 2


def test_receipt_content_mismatch_stays_uncertain(tmp_path):
    runtime, _ = service(
        tmp_path,
        FakeProvider(
            observation=mod.ProviderObservationV1("verified", "different-post")
        ),
    )
    item = request()
    preview = runtime.create_preview(item)
    runtime.consent(item, exact_consent=preview.preview.consent_text)
    assert runtime.dispatch(item).status == "uncertain_needs_reconciliation"


def test_cli_preview_has_no_provider_and_emits_json(capsys):
    assert (
        onyx_social_cli.main(
            [
                "preview",
                "--workspace-id",
                "w",
                "--principal-id",
                "p",
                "--account-id",
                "a",
                "--target",
                "feed",
                "--caption",
                "hello",
                "--provenance",
                "draft:d1",
                "--warning",
                "review claims",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["caption"] == "hello"
    assert output["provenance"] == ["draft:d1"]
    assert output["warnings"] == ["review claims"]


def test_cli_generate_is_local_and_draft_only(capsys):
    assert (
        onyx_social_cli.main(
            [
                "generate",
                "--brief",
                "Explain evidence.",
                "--brand",
                "Cyryx",
                "--platform",
                "linkedin",
                "--source-ref",
                "brief:7",
            ]
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "draft"
    assert output["caption"] == "Cyryx — Explain evidence."
    assert output["provenance"][2] == "source:brief:7"


def test_cli_publish_commands_require_explicitly_injected_runtime():
    with pytest.raises(RuntimeError, match="publication unavailable"):
        onyx_social_cli.main(cli_request_args())


def test_cli_explicit_fake_adapter_remains_default_off():
    with pytest.raises(RuntimeError, match="publication unavailable"):
        onyx_social_cli.main(
            cli_request_args("publish") + ["--exact-consent", "never-used"],
            provider_adapter=FakeProvider(),
            feature_gate=mod.SocialPublishFeatureGateV1(False),
        )


def test_cli_one_shot_publish_uses_explicit_fake_adapter(tmp_path, capsys):
    fake = FakeProvider()
    item = request()
    exact = mod.preview_caption(item).consent_text
    assert (
        onyx_social_cli.main(
            [
                "--ledger-path",
                str(tmp_path / "cli.sqlite3"),
                *cli_request_args("publish"),
                "--exact-consent",
                exact,
            ],
            provider_adapter=fake,
            feature_gate=mod.SocialPublishFeatureGateV1(True),
        )
        == 0
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "verified"
    assert len(fake.dispatches) == 1


def test_cli_fake_only_state_machine_dispatches_once_and_verifies(tmp_path, capsys):
    runtime, fake = service(tmp_path)
    assert onyx_social_cli.main(cli_request_args(), publication=runtime) == 0
    preview = json.loads(capsys.readouterr().out)
    consent_args = cli_request_args("publish-consent") + [
        "--exact-consent",
        preview["preview"]["consent_text"],
    ]
    assert onyx_social_cli.main(consent_args, publication=runtime) == 0
    capsys.readouterr()
    assert (
        onyx_social_cli.main(cli_request_args("publish-dispatch"), publication=runtime)
        == 0
    )
    dispatched = json.loads(capsys.readouterr().out)
    assert dispatched["status"] == "verified"
    digest = dispatched["preview"]["request_digest"]
    assert (
        onyx_social_cli.main(
            ["publish-status", "--request-digest", digest], publication=runtime
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert len(fake.dispatches) == 1


def test_cli_fake_reconciliation_reads_back_without_redispatch(tmp_path, capsys):
    fake = FakeProvider(observation=mod.ProviderObservationV1("unknown", None))
    runtime, _ = service(tmp_path, fake)
    onyx_social_cli.main(cli_request_args(), publication=runtime)
    preview = json.loads(capsys.readouterr().out)
    onyx_social_cli.main(
        cli_request_args("publish-consent")
        + ["--exact-consent", preview["preview"]["consent_text"]],
        publication=runtime,
    )
    capsys.readouterr()
    onyx_social_cli.main(cli_request_args("publish-dispatch"), publication=runtime)
    dispatched = json.loads(capsys.readouterr().out)
    fake.observation = mod.ProviderObservationV1("verified", "post-1")
    onyx_social_cli.main(
        [
            "publish-reconcile",
            "--request-digest",
            dispatched["preview"]["request_digest"],
        ],
        publication=runtime,
    )
    assert json.loads(capsys.readouterr().out)["status"] == "verified"
    assert len(fake.dispatches) == 1
