from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pytest

from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import JsonHttpResponseV1
from core.phase8_microsoft_graph_drive_v1 import (
    FEATURE_FLAG,
    MAX_ITEMS,
    MAX_PAGES,
    READ_SCOPES,
    GraphDriveFeatureGateV1,
    GraphDriveV1ContractError,
    GraphDriveV1Denied,
    StdlibGraphDriveHttpV1,
    create_microsoft_graph_drive_v1,
)

ROOT = Path(__file__).resolve().parents[1]
NOW_S = 1_785_000_000
CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
ACCOUNT_ID = "owner@cyryxlabs.com"
ITEM_ID = "01ABCDEF1234567890"


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


def _token(*, scopes: str = "Files.Read User.Read", refresh: str | None = None) -> Queued:
    payload: dict[str, object] = {
        "token_type": "Bearer",
        "access_token": "read-access-1",
        "expires_in": 3600,
        "scope": scopes,
    }
    if refresh is not None:
        payload["refresh_token"] = refresh
    return Queued("FORM", JsonHttpResponseV1(200, payload))


def _file(name: str = "notes.txt", item_id: str = "file-1", size: int = 12) -> dict:
    return {
        "id": item_id,
        "name": name,
        "size": size,
        "file": {"mimeType": "text/plain"},
        "lastModifiedDateTime": "2026-07-20T10:00:00Z",
        "webUrl": "https://onedrive.live.com/x",
    }


def _folder(name: str = "Docs", item_id: str = "folder-1", count: int = 3) -> dict:
    return {
        "id": item_id,
        "name": name,
        "size": 0,
        "folder": {"childCount": count},
        "lastModifiedDateTime": "2026-07-19T09:00:00Z",
        "webUrl": "https://onedrive.live.com/y",
    }


def _collection(items, next_link=None) -> Queued:
    payload: dict[str, object] = {"value": list(items)}
    if next_link is not None:
        payload["@odata.nextLink"] = next_link
    return Queued("GET", JsonHttpResponseV1(200, payload))


def _session(http: FakeHttp, vault: FakeVault | None = None):
    return create_microsoft_graph_drive_v1(
        gate=GraphDriveFeatureGateV1(True),
        onboarding=_onboarding(),
        http=http,
        vault=FakeVault() if vault is None else vault,
        clock_epoch_s=lambda: NOW_S,
        project_root=ROOT,
    )


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not GraphDriveFeatureGateV1.from_environ({}).enabled
    assert GraphDriveFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes"):
        assert not GraphDriveFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert (
        create_microsoft_graph_drive_v1(
            gate=GraphDriveFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_and_bound_to_accepted_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GraphDriveV1ContractError, match="sealed feature gate"):
        create_microsoft_graph_drive_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(GraphDriveV1ContractError, match="complete bindings"):
        create_microsoft_graph_drive_v1(
            gate=GraphDriveFeatureGateV1(True),
            onboarding=_onboarding(),
            project_root=ROOT,
        )
    monkeypatch.setattr(
        "core.phase8_microsoft_graph_drive_v1.ACCEPTED_TASKS_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(GraphDriveV1Denied, match="evidence unavailable"):
        create_microsoft_graph_drive_v1(
            gate=GraphDriveFeatureGateV1(True),
            project_root=ROOT,
        )


def test_list_root_normalizes_files_and_folders() -> None:
    http = FakeHttp(
        [_token(refresh="refresh-token-2"), _collection([_folder(), _file()])]
    )
    vault = FakeVault()
    session = _session(http, vault)
    assert session is not None
    items = session.list_root()
    assert len(items) == 2
    folder, file = items
    assert folder.is_folder is True and folder.child_count == 3
    assert file.is_folder is False and file.size == 12
    assert file.last_modified.endswith("+00:00")
    assert vault.value == "refresh-token-2"
    kind, url, query = http.calls[1]
    assert (kind, url) == ("GET", "https://graph.microsoft.com/v1.0/me/drive/root/children")
    assert dict(query)["$select"].startswith("id,name,size")
    assert "read-access-1" not in repr(items)


def test_list_children_and_get_item() -> None:
    http = FakeHttp([_token(), _collection([_file()])])
    session = _session(http)
    assert session is not None
    children = session.list_children(item_id=ITEM_ID)
    assert len(children) == 1
    assert http.calls[1][1].endswith(f"/drive/items/{ITEM_ID}/children")

    http2 = FakeHttp([_token(), Queued("GET", JsonHttpResponseV1(200, _file()))])
    session2 = _session(http2)
    assert session2 is not None
    item = session2.get_item(item_id=ITEM_ID)
    assert item.name == "notes.txt"
    assert http2.calls[1][1].endswith(f"/drive/items/{ITEM_ID}")


def test_paging_follows_same_route_nextlink_and_bounds() -> None:
    page1 = _collection(
        [_file(item_id=f"f{i}") for i in range(3)],
        next_link="https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=abc",
    )
    page2 = _collection([_file(item_id="last")])
    http = FakeHttp([_token(), page1, page2])
    session = _session(http)
    assert session is not None
    items = session.list_root()
    assert len(items) == 4
    assert len([c for c in http.calls if c[0] == "GET"]) == 2


def test_cross_route_nextlink_is_denied() -> None:
    page = _collection(
        [_file()],
        next_link="https://graph.microsoft.com/v1.0/me/messages?$skiptoken=x",
    )
    http = FakeHttp([_token(), page])
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphDriveV1Denied, match="cross-route nextLink"):
        session.list_root()


def test_missing_read_scope_denies() -> None:
    http = FakeHttp([_token(scopes="User.Read offline_access")])
    session = _session(http)
    assert session is not None
    with pytest.raises(GraphDriveV1Denied, match="files read scope"):
        session.list_root()


def test_invalid_item_id_is_rejected_before_network() -> None:
    http = FakeHttp()
    session = _session(http)
    assert session is not None
    for bad in ("has/slash", "with space", "", "x" * 600):
        with pytest.raises(GraphDriveV1ContractError, match="item id"):
            session.get_item(item_id=bad)
        with pytest.raises(GraphDriveV1ContractError, match="item id"):
            session.list_children(item_id=bad)
    assert http.calls == []


def test_provider_shape_drift_is_denied() -> None:
    for raw, message in (
        ({"id": "x", "name": "n", "size": -1}, "size"),
        ({"id": "x", "name": "n", "size": 0, "folder": {"childCount": -1}}, "childCount"),
        ({"id": "x", "name": "n", "size": 0, "folder": "notdict"}, "folder facet"),
        ({"id": "x", "name": "n", "size": 0, "file": "notdict"}, "file facet"),
        (
            {"id": "x", "name": "n", "size": 0, "folder": {"childCount": 1}, "file": {}},
            "facet conflict",
        ),
        ({"name": "n", "size": 0, "file": {}}, "identity drift"),
        ({"id": "x", "size": 0, "file": {}}, "identity drift"),
        ({"id": "", "name": "n", "size": 0, "file": {}}, "identity drift"),
        ("notdict", "item drift"),
        (
            {"id": "x", "name": "n\x00", "size": 0, "file": {}},
            "text contract",
        ),
        (
            {"id": "x", "name": "n", "size": 0, "lastModifiedDateTime": "not-a-date"},
            "timestamp",
        ),
    ):
        http = FakeHttp([_token(), _collection([raw])])
        session = _session(http)
        assert session is not None
        with pytest.raises(GraphDriveV1Denied, match=message):
            session.list_root()


def test_bounded_paging_caps_page_count() -> None:
    same_route = (
        "https://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=p"
    )
    pages = [
        _collection([_file(item_id=f"f{i}")], next_link=same_route)
        for i in range(MAX_PAGES + 2)
    ]
    http = FakeHttp([_token(), *pages])
    session = _session(http)
    assert session is not None
    items = session.list_root()
    gets = [c for c in http.calls if c[0] == "GET"]
    assert len(gets) == MAX_PAGES
    assert len(items) == MAX_PAGES


def test_bounded_paging_caps_item_count() -> None:
    over = [_file(item_id=f"f{i}") for i in range(MAX_ITEMS + 100)]
    http = FakeHttp([_token(), _collection(over)])
    session = _session(http)
    assert session is not None
    items = session.list_root()
    assert len(items) == MAX_ITEMS
    assert len([c for c in http.calls if c[0] == "GET"]) == 1


def test_get_item_rejects_collection_shape() -> None:
    for payload in ({"value": []}, {"@odata.nextLink": "x", "id": "y", "name": "z"}):
        http = FakeHttp([_token(), Queued("GET", JsonHttpResponseV1(200, payload))])
        session = _session(http)
        assert session is not None
        with pytest.raises(GraphDriveV1Denied, match="item object drift"):
            session.get_item(item_id=ITEM_ID)


def test_access_token_refetched_after_expiry() -> None:
    times = iter([NOW_S, NOW_S + 4000])
    http = FakeHttp(
        [_token(), _collection([_file()]), _token(), _collection([_folder()])]
    )
    session = create_microsoft_graph_drive_v1(
        gate=GraphDriveFeatureGateV1(True),
        onboarding=_onboarding(),
        http=http,
        vault=FakeVault(),
        clock_epoch_s=lambda: next(times),
        project_root=ROOT,
    )
    assert session is not None
    session.list_root()
    session.list_root()
    assert len([c for c in http.calls if c[0] == "FORM"]) == 2


def test_best_effort_rotation_tolerates_vault_write_failure() -> None:
    class RaisingVault(FakeVault):
        def set_refresh_token(self, value: str) -> None:
            raise PermissionError("refresh token exceeds vault capacity")

    http = FakeHttp([_token(refresh="rotated"), _collection([_file()])])
    session = _session(http, RaisingVault())
    assert session is not None
    items = session.list_root()
    assert len(items) == 1


def test_cross_route_nextlink_host_scheme_fragment_denied() -> None:
    for link in (
        "https://evil.example/v1.0/me/drive/root/children?$skiptoken=x",
        "http://graph.microsoft.com/v1.0/me/drive/root/children?$skiptoken=x",
        "https://graph.microsoft.com/v1.0/me/drive/root/children#frag",
    ):
        http = FakeHttp([_token(), _collection([_file()], next_link=link)])
        session = _session(http)
        assert session is not None
        with pytest.raises(GraphDriveV1Denied, match="cross-route nextLink"):
            session.list_root()


def test_access_token_cached_across_reads() -> None:
    http = FakeHttp([_token(), _collection([_file()]), _collection([_folder()])])
    session = _session(http)
    assert session is not None
    session.list_root()
    session.list_children(item_id=ITEM_ID)
    assert len([c for c in http.calls if c[0] == "FORM"]) == 1


def test_stdlib_client_pins_routes_before_network() -> None:
    client = StdlibGraphDriveHttpV1()
    with pytest.raises(GraphDriveV1Denied, match="drive route"):
        client.get_json(
            url="https://graph.microsoft.com/v1.0/me/messages",
            query=(),
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphDriveV1Denied, match="drive route"):
        client.get_json(
            url="https://graph.microsoft.com/v1.0/me/drive/items/x/content",
            query=(),
            headers=(),
            timeout_seconds=30,
        )
    with pytest.raises(GraphDriveV1Denied, match="identity POST"):
        client.post_form(
            url="https://evil.example/token",
            fields=(("a", "b"),),
            timeout_seconds=30,
        )


def test_module_has_no_content_download_or_mutation_or_wiring() -> None:
    source = (ROOT / "core" / "phase8_microsoft_graph_drive_v1.py").read_text(
        encoding="utf-8"
    )
    assert "client_secret" not in source
    assert "Files.ReadWrite" not in source
    assert "/content" not in source
    assert "def upload" not in source
    assert "def delete" not in source
    assert "def create" not in source or "def create_microsoft_graph_drive_v1" in source
    assert "def post_json" not in source
    assert "main.py" not in source
    assert "dashboard" not in source
    assert "subprocess" not in source
    assert '"Files.Read"' in source
    assert set(READ_SCOPES) == {"Files.Read", "User.Read", "offline_access"}
