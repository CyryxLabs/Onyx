from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import pytest

from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_mail_v1 import (
    FEATURE_FLAG,
    WRITE_SCOPES,
    GraphMailFeatureGateV1,
    GraphMailV1ContractError,
    GraphMailV1Denied,
    GraphMailV1Error,
    GraphMailV1Uncertain,
    InMemoryNonceLedgerV1,
    MailSendGrantV1,
    StdlibGraphMailHttpV1,
    _expected_email_digest,
    create_microsoft_graph_mail_v1,
    issue_mail_send_grant_v1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.phase8_microsoft_graph_read_v1 import LocalEmailDraftV1

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
NONCE = "ab" * 16
INTERNET_ID = "<abc123@cyryxlabs.com>"


def _draft(**changes: object) -> LocalEmailDraftV1:
    values: dict[str, object] = {
        "recipients": ("dest@example.com",),
        "cc": (),
        "subject": "Onyx test",
        "body_text": "Hello from the mail test.",
        "reply_to_message_id": None,
    }
    values.update(changes)
    # Build with a content-consistent digest unless the caller pins one.
    if "draft_sha256" not in values:
        provisional = LocalEmailDraftV1(
            **values, draft_sha256="0" * 64  # type: ignore[arg-type]
        )
        values["draft_sha256"] = _expected_email_digest(provisional)
    return LocalEmailDraftV1(**values)  # type: ignore[arg-type]


def _onboarding() -> MicrosoftGraphLiveOnboardingV1:
    return MicrosoftGraphLiveOnboardingV1(CLIENT_ID, TENANT_ID, ACCOUNT_ID)


@dataclass(frozen=True)
class Queued:
    kind: str
    response: JsonHttpResponseV1


class FakeHttp:
    def __init__(self, responses: Iterable[object] = ()) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str, object]] = []

    def _next(self, kind: str) -> JsonHttpResponseV1:
        if not self.responses:
            raise AssertionError(f"unexpected {kind} request")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        assert item.kind == kind, f"expected {item.kind}, got {kind}"
        return item.response

    def post_form(self, *, url, fields, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("FORM", url, fields))
        return self._next("FORM")

    def post_json(self, *, url, payload, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("JSON", url, payload))
        return self._next("JSON")

    def post_empty(self, *, url, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("EMPTY", url, None))
        return self._next("EMPTY")

    def get_json(self, *, url, query, headers, timeout_seconds):
        assert timeout_seconds == 30
        self.calls.append(("GET", url, query))
        return self._next("GET")


class FakeVault:
    def __init__(self, value: str | None = "refresh-token-1") -> None:
        self.value = value
        self.writes: list[str] = []

    def get_refresh_token(self):
        return self.value

    def set_refresh_token(self, value: str) -> None:
        self.value = value
        self.writes.append(value)

    def delete_refresh_token(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


def _write_token(
    *, scopes: str = "Mail.ReadWrite Mail.Send User.Read", refresh: str | None = None
) -> Queued:
    payload: dict[str, object] = {
        "token_type": "Bearer",
        "access_token": "write-access-1",
        "expires_in": 3600,
        "scope": scopes,
    }
    if refresh is not None:
        payload["refresh_token"] = refresh
    return Queued("FORM", JsonHttpResponseV1(200, payload))


def _created(internet_id: str = INTERNET_ID) -> Queued:
    return Queued(
        "JSON",
        JsonHttpResponseV1(
            201, {"id": "draft-1", "internetMessageId": internet_id}
        ),
    )


def _sent() -> Queued:
    return Queued("EMPTY", JsonHttpResponseV1(202, {}, (("request-id", "req-1"),)))


def _found(internet_id: str = INTERNET_ID) -> Queued:
    return Queued(
        "GET",
        JsonHttpResponseV1(
            200,
            {"value": [{"id": "sent-1", "internetMessageId": internet_id}]},
        ),
    )


def _session(http: FakeHttp, vault: FakeVault | None = None, ledger=None):
    return create_microsoft_graph_mail_v1(
        gate=GraphMailFeatureGateV1(True),
        onboarding=_onboarding(),
        http=http,
        vault=FakeVault() if vault is None else vault,
        integrity_key=KEY,
        nonce_ledger=ledger,
        clock_ms=lambda: NOW_MS + 1,
        clock_epoch_s=lambda: NOW_S,
        project_root=ROOT,
    )


def _grant(draft: LocalEmailDraftV1, **changes: object) -> MailSendGrantV1:
    grant = issue_mail_send_grant_v1(
        integrity_key=KEY,
        workspace_id="cyryx-live-e2e",
        principal_id="owner:live-e2e",
        account_id=ACCOUNT_ID,
        draft=draft,
        nonce=NONCE,
        now_ms=NOW_MS,
    )
    return replace(grant, **changes) if changes else grant


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not GraphMailFeatureGateV1.from_environ({}).enabled
    assert GraphMailFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes"):
        assert not GraphMailFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert (
        create_microsoft_graph_mail_v1(
            gate=GraphMailFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_and_bound_to_accepted_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphMailV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_mail_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphMailV1ContractError, match="complete bindings"):
        create_microsoft_graph_mail_v1(
            gate=GraphMailFeatureGateV1(True),
            onboarding=_onboarding(),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_mail_v1.ACCEPTED_CALENDAR_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphMailV1Denied, match="evidence unavailable"):
        create_microsoft_graph_mail_v1(
            gate=GraphMailFeatureGateV1(True),
            project_root=ROOT,
        )


def test_grant_binds_exact_audience_order_independent() -> None:
    a = _draft(recipients=("x@a.com", "y@b.com"), cc=("z@c.com",))
    b = _draft(recipients=("Y@B.com", "x@a.com"), cc=("Z@c.com",))
    # Same audience, different order/case → same recipient_key → same signature
    # only if draft_sha256 also matches; here digests differ so compare keys.
    from core.phase8_microsoft_graph_mail_v1 import _recipient_key

    assert _recipient_key(a.recipients, a.cc) == _recipient_key(b.recipients, b.cc)
    c = _draft(recipients=("x@a.com",), cc=("y@b.com",))
    d = _draft(recipients=("x@a.com", "y@b.com"), cc=())
    assert _recipient_key(c.recipients, c.cc) != _recipient_key(d.recipients, d.cc)


def test_send_happy_path_receipt_reconciled_and_one_shot() -> None:
    draft = _draft(cc=("cc@example.com",))
    http = FakeHttp(
        [_write_token(refresh="refresh-token-2"), _created(), _sent(), _found()]
    )
    vault = FakeVault()
    session = _session(http, vault)
    assert session is not None
    grant = _grant(draft)
    receipt = session.send(draft=draft, grant=grant)
    assert receipt.message_id == "draft-1"
    assert receipt.internet_message_id == INTERNET_ID
    assert receipt.reconciled is True
    assert receipt.provider_request_id == "req-1"
    assert receipt.recipient_count == 1
    assert vault.value == "refresh-token-2"
    kind, url, payload = http.calls[1]
    assert (kind, url) == ("JSON", "https://graph.microsoft.com/v1.0/me/messages")
    assert payload["toRecipients"] == [{"emailAddress": {"address": "dest@example.com"}}]
    assert payload["ccRecipients"] == [{"emailAddress": {"address": "cc@example.com"}}]
    assert http.calls[2][0] == "EMPTY"
    assert http.calls[2][1].endswith("/messages/draft-1/send")
    assert "write-access-1" not in repr(receipt)
    assert "refresh-token" not in repr(receipt)
    with pytest.raises(GraphMailV1Denied, match="already used"):
        session.send(draft=draft, grant=grant)


def test_grant_denials_before_any_network() -> None:
    draft = _draft()
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    other = _draft(recipients=("attacker@evil.com",))
    cases = [
        (_grant(draft, signature="0" * 64), "signature is invalid"),
        (_grant(draft, account_id="other@cyryxlabs.com"), "signature is invalid"),
        (
            _grant(_draft(subject="X", draft_sha256=hashlib.sha256(b"z").hexdigest())),
            "exact draft",
        ),
        (
            replace(
                _grant(draft),
                recipient_key=hashlib.sha256(b"different").hexdigest(),
            ),
            "signature is invalid",
        ),
        # A grant for a different audience is a different draft digest → denied.
        (_grant(other), "exact draft"),
    ]
    for grant, message in cases:
        with pytest.raises(GraphMailV1Denied, match=message):
            session.send(draft=draft, grant=grant)
    assert http.calls == []


def test_content_swap_under_copied_digest_is_denied() -> None:
    approved = _draft(subject="Meeting at 3pm", body_text="See you at 3.")
    grant = _grant(approved)
    # Attacker keeps the approved digest and recipients but swaps subject/body.
    swapped = replace(
        approved, subject="I QUIT", body_text="Goodbye forever."
    )
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphMailV1Denied, match="content does not match its digest"):
        session.send(draft=swapped, grant=grant)
    assert http.calls == []


def test_expected_digest_matches_frozen_read_module() -> None:
    from core.phase8_microsoft_graph_read_v1 import _draft_sha256

    draft = _draft(recipients=("a@x.com", "b@y.com"), cc=("c@z.com",))
    frozen = _draft_sha256(
        "email",
        {
            "recipients": draft.recipients,
            "cc": draft.cc,
            "subject": draft.subject,
            "body_text": draft.body_text,
            "reply_to_message_id": draft.reply_to_message_id,
        },
    )
    assert _expected_email_digest(draft) == frozen == draft.draft_sha256


def test_reply_draft_and_invalid_recipient_are_denied() -> None:
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    reply = _draft(reply_to_message_id="AAMk-original")
    with pytest.raises(GraphMailV1Denied, match="reply drafts"):
        session.send(draft=reply, grant=_grant(reply))
    empty = _draft(recipients=("",))
    with pytest.raises(GraphMailV1Denied, match="recipient address is invalid"):
        session.send(draft=empty, grant=_grant(empty))
    assert http.calls == []


def test_cross_session_replay_denied_with_shared_durable_ledger() -> None:
    draft = _draft()
    grant = _grant(draft)
    shared = InMemoryNonceLedgerV1()
    first_http = FakeHttp([_write_token(), _created(), _sent(), _found()])
    first = _session(first_http, ledger=shared)
    assert first is not None
    receipt = first.send(draft=draft, grant=grant)
    assert receipt.reconciled is True
    # A brand-new session with the SAME durable ledger and the SAME grant must
    # be denied before any provider mutation — no duplicate mail.
    second_http = FakeHttp()
    second = _session(second_http, ledger=shared)
    assert second is not None
    with pytest.raises(GraphMailV1Denied, match="already used"):
        second.send(draft=draft, grant=grant)
    assert second_http.calls == []


def test_odata_injection_internetmessageid_is_rejected() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token(),
            _created(internet_id="x' or internetMessageId ne 'zzz"),
        ]
    )
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphMailV1Denied, match="internetMessageId is invalid"):
        session.send(draft=draft, grant=_grant(draft))


def test_missing_send_scope_denies_before_mutation() -> None:
    draft = _draft()
    http = FakeHttp([_write_token(scopes="Mail.ReadWrite User.Read")])
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphMailV1Denied, match="send scope"):
        session.send(draft=draft, grant=_grant(draft))
    assert len(http.calls) == 1


def test_expired_grant_is_denied() -> None:
    draft = _draft()
    expired = issue_mail_send_grant_v1(
        integrity_key=KEY,
        workspace_id="cyryx-live-e2e",
        principal_id="owner:live-e2e",
        account_id=ACCOUNT_ID,
        draft=draft,
        nonce=NONCE,
        now_ms=NOW_MS - 500_000,
        ttl_ms=1_000,
    )
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphMailV1Denied, match="expired"):
        session.send(draft=draft, grant=expired)
    assert http.calls == []


def test_throttle_and_rejection_do_not_auto_retry() -> None:
    draft = _draft()
    throttled = FakeHttp(
        [_write_token(), Queued("JSON", JsonHttpResponseV1(429, {}))]
    )
    session = _session(throttled)
    assert session is not None
    with pytest.raises(GraphMailV1Error, match="fresh grant"):
        session.send(draft=draft, grant=_grant(draft))
    assert len([c for c in throttled.calls if c[0] == "JSON"]) == 1
    assert not any(c[0] == "EMPTY" for c in throttled.calls)

    send_throttled = FakeHttp(
        [
            _write_token(),
            _created(),
            Queued("EMPTY", JsonHttpResponseV1(429, {})),
        ]
    )
    session2 = _session(send_throttled)
    assert session2 is not None
    with pytest.raises(GraphMailV1Error, match="reconcile Sent Items"):
        session2.send(draft=draft, grant=_grant(draft))


def test_uncertain_send_consumes_grant_and_reconciles() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token(),
            _created(),
            GraphMailV1Uncertain("provider outcome unknown"),
        ]
    )
    session = _session(http)
    assert session is not None
    grant = _grant(draft)
    with pytest.raises(GraphMailV1Uncertain):
        session.send(draft=draft, grant=grant)
    # Grant consumed even though send outcome unknown.
    with pytest.raises(GraphMailV1Denied, match="already used"):
        session.send(draft=draft, grant=grant)

    found = FakeHttp([_write_token(), _found()])
    session_found = _session(found)
    assert session_found is not None
    assert session_found.reconcile_uncertain(internet_message_id=INTERNET_ID) is True

    absent = FakeHttp([_write_token(), Queued("GET", JsonHttpResponseV1(200, {"value": []}))])
    session_absent = _session(absent)
    assert session_absent is not None
    assert session_absent.reconcile_uncertain(internet_message_id=INTERNET_ID) is False


def test_send_reconciliation_absent_yields_unreconciled_receipt() -> None:
    draft = _draft()
    http = FakeHttp(
        [
            _write_token(),
            _created(),
            _sent(),
            Queued("GET", JsonHttpResponseV1(200, {"value": []})),
        ]
    )
    session = _session(http)
    assert session is not None
    receipt = session.send(draft=draft, grant=_grant(draft))
    assert receipt.reconciled is False


def test_best_effort_rotation_does_not_abort_send() -> None:
    class RejectingVault(FakeVault):
        def set_refresh_token(self, value: str) -> None:
            raise PermissionError("refresh token exceeded vault limit")

    draft = _draft()
    http = FakeHttp(
        [_write_token(refresh="x" * 5000), _created(), _sent(), _found()]
    )
    session = _session(http, RejectingVault())
    assert session is not None
    receipt = session.send(draft=draft, grant=_grant(draft))
    assert receipt.reconciled is True


def test_stdlib_client_pins_routes_before_network() -> None:
    client = StdlibGraphMailHttpV1()
    with pytest.raises(GraphMailV1Denied, match="draft route"):
        client.post_json(
            url="https://graph.microsoft.com/v1.0/me/sendMail",
            payload={},
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphMailV1Denied, match="send route"):
        client.post_empty(
            url="https://graph.microsoft.com/v1.0/me/messages/x/forward",
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphMailV1Denied, match="sent-items route"):
        client.get_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            query=(),
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphMailV1Denied, match="identity POST"):
        client.post_form(
            url="https://evil.example/token",
            fields=(("a", "b"),),
            timeout_seconds=30,
        )


def test_module_has_no_broader_mail_mutation_or_wiring() -> None:
    source = (ROOT / "core" / "phase8_microsoft_graph_mail_v1.py").read_text(
        encoding="utf-8"
    )
    assert "client_secret" not in source
    assert "def delete" not in source
    assert "def forward" not in source
    assert "def reply" not in source
    assert "sendMail" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "subprocess" not in source
    assert "reconcile before resend" in source
    assert '"Mail.Send"' in source
    assert set(WRITE_SCOPES) == {
        "Mail.ReadWrite",
        "Mail.Send",
        "User.Read",
        "offline_access",
    }
