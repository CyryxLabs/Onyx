from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

import pytest

from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.phase8_microsoft_graph_tasks_v1 import (
    FEATURE_FLAG,
    WRITE_SCOPES,
    GraphTasksFeatureGateV1,
    GraphTasksV1ContractError,
    GraphTasksV1Denied,
    GraphTasksV1Error,
    GraphTasksV1Uncertain,
    InMemoryNonceLedgerV1,
    NotificationItemV1,
    QuietHoursPolicyV1,
    StdlibGraphTasksHttpV1,
    TaskCreateGrantV1,
    build_task_draft_v1,
    create_microsoft_graph_tasks_v1,
    issue_task_create_grant_v1,
    route_notifications,
)

ROOT = Path(__file__).resolve().parents[1]
NOW_MS = 1_785_000_000_000
NOW_S = 1_785_000_000
KEY = bytes(range(1, 33))
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
NONCE = "ab" * 16
LIST_ID = "AQMkAGtasklist01"


def _onboarding() -> MicrosoftGraphLiveOnboardingV1:
    return MicrosoftGraphLiveOnboardingV1(CLIENT_ID, TENANT_ID, ACCOUNT_ID)


# ── Notification router ─────────────────────────────────────────────────────


def _item(**changes: object) -> NotificationItemV1:
    values: dict[str, object] = {
        "notification_id": "n1",
        "source": "task",
        "urgency": "normal",
        "workspace_id": "cyryx-main",
        "device": "desktop",
        "created_epoch_s": NOW_S,
        "summary": "A task is due.",
    }
    values.update(changes)
    return NotificationItemV1(**values)  # type: ignore[arg-type]


def _policy(**changes: object) -> QuietHoursPolicyV1:
    values: dict[str, object] = {
        "start_hour_utc": 22,
        "end_hour_utc": 7,
        "min_urgency_in_quiet": "urgent",
        "allowed_workspaces": ("cyryx-main",),
        "allowed_devices": ("desktop", "phone"),
    }
    values.update(changes)
    return QuietHoursPolicyV1(**values)  # type: ignore[arg-type]


def test_quiet_hours_wraps_midnight() -> None:
    policy = _policy()
    assert policy.in_quiet_hours(23) is True
    assert policy.in_quiet_hours(3) is True
    assert policy.in_quiet_hours(7) is False
    assert policy.in_quiet_hours(12) is False
    day = _policy(start_hour_utc=9, end_hour_utc=17)
    assert day.in_quiet_hours(12) is True
    assert day.in_quiet_hours(8) is False


def test_route_outside_quiet_hours_delivers_all_allowed() -> None:
    items = (_item(urgency="low"), _item(notification_id="n2", urgency="urgent"))
    decisions = route_notifications(items, policy=_policy(), now_hour_utc=12)
    assert [d.decision for d in decisions] == ["deliver", "deliver"]


def test_route_inside_quiet_hours_defers_below_threshold() -> None:
    items = (
        _item(notification_id="low", urgency="low"),
        _item(notification_id="high", urgency="high"),
        _item(notification_id="urgent", urgency="urgent"),
    )
    decisions = route_notifications(items, policy=_policy(), now_hour_utc=2)
    by_id = {d.notification_id: d.decision for d in decisions}
    assert by_id == {"low": "defer", "high": "defer", "urgent": "deliver"}


def test_route_suppresses_unpermitted_workspace_and_device() -> None:
    items = (
        _item(notification_id="w", workspace_id="external"),
        _item(notification_id="d", device="watch"),
    )
    decisions = route_notifications(items, policy=_policy(), now_hour_utc=12)
    by_id = {d.notification_id: (d.decision, d.reason) for d in decisions}
    assert by_id["w"][0] == "suppress" and "workspace" in by_id["w"][1]
    assert by_id["d"][0] == "suppress" and "device" in by_id["d"][1]


def test_route_threshold_high_delivers_high_and_urgent() -> None:
    policy = _policy(min_urgency_in_quiet="high")
    items = (
        _item(notification_id="normal", urgency="normal"),
        _item(notification_id="high", urgency="high"),
    )
    decisions = route_notifications(items, policy=policy, now_hour_utc=2)
    by_id = {d.notification_id: d.decision for d in decisions}
    assert by_id == {"normal": "defer", "high": "deliver"}


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "sms"},
        {"urgency": "critical"},
        {"summary": ""},
        {"notification_id": ""},
        {"created_epoch_s": -1},
    ],
)
def test_notification_item_contract(changes: dict[str, object]) -> None:
    with pytest.raises(GraphTasksV1ContractError):
        _item(**changes)


# ── Task create ─────────────────────────────────────────────────────────────


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


def _draft(**changes: object):
    values: dict[str, object] = {
        "list_id": LIST_ID,
        "title": "Prepare Q3 review",
        "body_text": "Draft the deck.",
        "importance": "normal",
        "due_date": "2026-07-30",
    }
    values.update(changes)
    return build_task_draft_v1(**values)  # type: ignore[arg-type]


def _write_token(
    *, scopes: str = "Tasks.ReadWrite User.Read", refresh: str | None = None
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


def _created(task_id: str = "task-1") -> Queued:
    return Queued(
        "JSON",
        JsonHttpResponseV1(201, {"id": task_id}, (("request-id", "req-1"),)),
    )


def _echo(draft, *, title: str | None = None) -> Queued:
    return Queued(
        "GET",
        JsonHttpResponseV1(
            200,
            {
                "id": "task-1",
                "title": draft.title if title is None else title,
                "importance": draft.importance,
            },
        ),
    )


def _session(http: FakeHttp, vault: FakeVault | None = None, ledger=None):
    return create_microsoft_graph_tasks_v1(
        gate=GraphTasksFeatureGateV1(True),
        onboarding=_onboarding(),
        http=http,
        vault=FakeVault() if vault is None else vault,
        integrity_key=KEY,
        nonce_ledger=ledger,
        clock_ms=lambda: NOW_MS + 1,
        clock_epoch_s=lambda: NOW_S,
        project_root=ROOT,
    )


def _grant(draft, **changes: object) -> TaskCreateGrantV1:
    grant = issue_task_create_grant_v1(
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
    assert not GraphTasksFeatureGateV1.from_environ({}).enabled
    assert GraphTasksFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes"):
        assert not GraphTasksFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert (
        create_microsoft_graph_tasks_v1(
            gate=GraphTasksFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_and_bound_to_accepted_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphTasksV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_tasks_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphTasksV1ContractError, match="complete bindings"):
        create_microsoft_graph_tasks_v1(
            gate=GraphTasksFeatureGateV1(True),
            onboarding=_onboarding(),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_tasks_v1.ACCEPTED_MAIL_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphTasksV1Denied, match="evidence unavailable"):
        create_microsoft_graph_tasks_v1(
            gate=GraphTasksFeatureGateV1(True),
            project_root=ROOT,
        )


def test_create_task_happy_path_receipt_reconciled_and_one_shot() -> None:
    draft = _draft()
    http = FakeHttp(
        [_write_token(refresh="refresh-token-2"), _created(), _echo(draft)]
    )
    vault = FakeVault()
    session = _session(http, vault)
    assert session is not None
    grant = _grant(draft)
    receipt = session.create_task(draft=draft, grant=grant)
    assert receipt.task_id == "task-1"
    assert receipt.reconciled is True
    assert receipt.provider_request_id == "req-1"
    assert vault.value == "refresh-token-2"
    kind, url, payload = http.calls[1]
    assert kind == "JSON"
    assert url.endswith(f"/todo/lists/{LIST_ID}/tasks")
    assert payload["title"] == draft.title
    assert payload["dueDateTime"]["timeZone"] == "UTC"
    assert "write-access-1" not in repr(receipt)
    with pytest.raises(GraphTasksV1Denied, match="already used"):
        session.create_task(draft=draft, grant=grant)


def test_grant_denials_before_any_network() -> None:
    draft = _draft()
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    swapped = replace(draft, title="Buy 100 servers")
    other_list = _draft(list_id="AQMkAGotherlist")
    cases = [
        (_grant(draft, signature="0" * 64), "signature is invalid"),
        (_grant(draft, account_id="other@cyryxlabs.com"), "signature is invalid"),
        (_grant(_draft(title="Different")), "exact draft"),
        (swapped, "content does not match"),
        (_grant(other_list), "exact draft"),
    ]
    for grant_or_draft, message in cases:
        if isinstance(grant_or_draft, TaskCreateGrantV1):
            with pytest.raises(GraphTasksV1Denied, match=message):
                session.create_task(draft=draft, grant=grant_or_draft)
        else:
            with pytest.raises(GraphTasksV1Denied, match=message):
                session.create_task(draft=grant_or_draft, grant=_grant(draft))
    assert http.calls == []


def test_missing_write_scope_denies_before_mutation() -> None:
    draft = _draft()
    http = FakeHttp([_write_token(scopes="Tasks.Read User.Read")])
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphTasksV1Denied, match="write scope"):
        session.create_task(draft=draft, grant=_grant(draft))
    assert len(http.calls) == 1


def test_expired_grant_is_denied() -> None:
    draft = _draft()
    expired = issue_task_create_grant_v1(
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
    with pytest.raises(GraphTasksV1Denied, match="expired"):
        session.create_task(draft=draft, grant=expired)
    assert http.calls == []


def test_throttle_and_rejection_do_not_auto_retry() -> None:
    draft = _draft()
    throttled = FakeHttp([_write_token(), Queued("JSON", JsonHttpResponseV1(429, {}))])
    session = _session(throttled)
    assert session is not None
    with pytest.raises(GraphTasksV1Error, match="fresh grant"):
        session.create_task(draft=draft, grant=_grant(draft))
    assert len([c for c in throttled.calls if c[0] == "JSON"]) == 1


def test_uncertain_create_consumes_grant() -> None:
    draft = _draft()
    http = FakeHttp(
        [_write_token(), GraphTasksV1Uncertain("provider outcome unknown")]
    )
    session = _session(http)
    assert session is not None
    grant = _grant(draft)
    with pytest.raises(GraphTasksV1Uncertain):
        session.create_task(draft=draft, grant=grant)
    with pytest.raises(GraphTasksV1Denied, match="already used"):
        session.create_task(draft=draft, grant=grant)


def test_reconciliation_mismatch_yields_unreconciled_receipt() -> None:
    draft = _draft()
    http = FakeHttp(
        [_write_token(), _created(), _echo(draft, title="Something else")]
    )
    session = _session(http)
    assert session is not None
    receipt = session.create_task(draft=draft, grant=_grant(draft))
    assert receipt.reconciled is False


def test_cross_session_replay_denied_with_shared_durable_ledger() -> None:
    draft = _draft()
    grant = _grant(draft)
    shared = InMemoryNonceLedgerV1()
    first_http = FakeHttp([_write_token(), _created(), _echo(draft)])
    first = _session(first_http, ledger=shared)
    assert first is not None
    assert first.create_task(draft=draft, grant=grant).reconciled is True
    second_http = FakeHttp()
    second = _session(second_http, ledger=shared)
    assert second is not None
    with pytest.raises(GraphTasksV1Denied, match="already used"):
        second.create_task(draft=draft, grant=grant)
    assert second_http.calls == []


def test_stdlib_client_pins_routes_before_network() -> None:
    client = StdlibGraphTasksHttpV1()
    with pytest.raises(GraphTasksV1Denied, match="task create route"):
        client.post_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            payload={},
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphTasksV1Denied, match="task read route"):
        client.get_json(
            url="https://graph.microsoft.com/v1.0/me/todo/lists/x/tasks",
            query=(),
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphTasksV1Denied, match="identity POST"):
        client.post_form(
            url="https://evil.example/token",
            fields=(("a", "b"),),
            timeout_seconds=30,
        )


def test_module_has_no_broader_task_mutation_or_wiring() -> None:
    source = (ROOT / "core" / "phase8_microsoft_graph_tasks_v1.py").read_text(
        encoding="utf-8"
    )
    assert "client_secret" not in source
    assert "def delete" not in source
    assert "def complete" not in source
    assert "def update" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "subprocess" not in source
    assert "reconcile before retry" in source
    assert '"Tasks.ReadWrite"' in source
    assert set(WRITE_SCOPES) == {"Tasks.ReadWrite", "User.Read", "offline_access"}
