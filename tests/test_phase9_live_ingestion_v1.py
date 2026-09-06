from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core.phase9_intelligence_ingestion_v1 import (
    IntelligenceIngestionFeatureGateV1,
    create_intelligence_ingestion_v1,
)
from core.phase9_live_ingestion_v1 import (
    FEATURE_FLAG,
    MAX_HTTP_BYTES,
    MAX_ITEMS_PER_FETCH,
    ApprovedSourceV1,
    LiveIngestionFeatureGateV1,
    LiveIngestionV1ContractError,
    LiveIngestionV1Denied,
    LiveIngestionV1Error,
    LiveJsonResponseV1,
    StdlibLiveIngestionHttpV1,
    _strict_json,
    create_live_ingestion_v1,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_785_000_000
SOURCE = ApprovedSourceV1("reuters", "reputable", "geopolitics", "feeds.example.test", "/onyx/feed.json")


class FakeHttp:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str, int]] = []

    def get_json(self, *, url, origin, path, timeout_seconds):
        self.calls.append((url, origin, path, timeout_seconds))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _feed_item(**overrides) -> dict:
    base = {
        "id": "a",
        "title": "Something happened",
        "url": "https://feeds.example.test/onyx/a",
        "published": "2026-07-24T10:00:00Z",
        "event": "2026-07-24T09:00:00Z",
        "claims": [],
    }
    base.update(overrides)
    return base


def _ok(items) -> LiveJsonResponseV1:
    return LiveJsonResponseV1(200, {"items": list(items)})


def _session(http: FakeHttp, sources=(SOURCE,)):
    return create_live_ingestion_v1(
        gate=LiveIngestionFeatureGateV1(True),
        sources=sources,
        http=http,
        now_epoch_s=lambda: NOW,
        project_root=ROOT,
    )


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not LiveIngestionFeatureGateV1.from_environ({}).enabled
    assert LiveIngestionFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes", "True"):
        assert not LiveIngestionFeatureGateV1.from_environ({FEATURE_FLAG: value}).enabled
    assert (
        create_live_ingestion_v1(
            gate=LiveIngestionFeatureGateV1(False), project_root=ROOT / "missing"
        )
        is None
    )


def test_factory_is_sealed_and_entry_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LiveIngestionV1ContractError, match="sealed feature gate"):
        create_live_ingestion_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(LiveIngestionV1ContractError, match="requires sources and a clock"):
        create_live_ingestion_v1(
            gate=LiveIngestionFeatureGateV1(True), project_root=ROOT
        )
    monkeypatch.setattr(
        "core.phase9_live_ingestion_v1.ACCEPTED_SCORING_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(LiveIngestionV1Denied, match="evidence unavailable"):
        create_live_ingestion_v1(
            gate=LiveIngestionFeatureGateV1(True),
            sources=(SOURCE,),
            http=FakeHttp(_ok([])),
            now_epoch_s=lambda: NOW,
            project_root=ROOT,
        )


def test_entry_bind_detects_evidence_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "core.phase9_live_ingestion_v1.ACCEPTED_SCORING_ROOTS",
        (("docs/onyx/checkpoints/phase9-opportunity-scoring-v1/manifest.json", "0" * 64),),
    )
    with pytest.raises(LiveIngestionV1Denied, match="evidence drift"):
        create_live_ingestion_v1(
            gate=LiveIngestionFeatureGateV1(True),
            sources=(SOURCE,),
            http=FakeHttp(_ok([])),
            now_epoch_s=lambda: NOW,
            project_root=ROOT,
        )


def test_approved_source_validation() -> None:
    # a well-formed bare host with an absolute path is accepted.
    ApprovedSourceV1("s", "primary", "geopolitics", "feeds.example.test", "/onyx/feed.json")
    with pytest.raises(LiveIngestionV1ContractError, match="tier"):
        ApprovedSourceV1("s", "rumor", "geopolitics", "h.test", "/f")
    with pytest.raises(LiveIngestionV1ContractError, match="category"):
        ApprovedSourceV1("s", "primary", "sports", "h.test", "/f")
    for bad_origin in (
        "Host.Test",          # uppercase
        "host.test/x",        # path in origin
        "host.test:443",      # port
        "good.test@evil.test",  # userinfo -> would connect to evil.test
        "singlelabel",        # no dot
        "café.test",     # non-ASCII / unicode host
        "host..test",         # empty label
        "-host.test",         # leading hyphen
    ):
        with pytest.raises(LiveIngestionV1ContractError, match="host"):
            ApprovedSourceV1("s", "primary", "geopolitics", bad_origin, "/f")
    for bad_path in (
        "noslash",
        "/f?q=1",
        "/f#x",
        "/a/../b",            # dot-segment
        "//evil.test/x",      # protocol-relative-looking
        "/a b",               # space
        "/f\\x",              # backslash
    ):
        with pytest.raises(LiveIngestionV1ContractError, match="path"):
            ApprovedSourceV1("s", "primary", "geopolitics", "h.test", bad_path)


def test_registry_validation() -> None:
    http = FakeHttp(_ok([]))
    for bad in ([SOURCE], (), tuple(["notsource"])):
        with pytest.raises(LiveIngestionV1ContractError):
            create_live_ingestion_v1(
                gate=LiveIngestionFeatureGateV1(True),
                sources=bad,
                http=http,
                now_epoch_s=lambda: NOW,
                project_root=ROOT,
            )
    dup = (SOURCE, ApprovedSourceV1("reuters", "primary", "finance_macro", "other.test", "/g"))
    with pytest.raises(LiveIngestionV1ContractError, match="duplicate approved source_id"):
        create_live_ingestion_v1(
            gate=LiveIngestionFeatureGateV1(True),
            sources=dup,
            http=http,
            now_epoch_s=lambda: NOW,
            project_root=ROOT,
        )


def test_fetch_attributes_source_health_from_registry_not_feed() -> None:
    # feed tries to self-report a higher tier and a different source id.
    item = _feed_item(source_tier="primary", source_id="spoofed")
    http = FakeHttp(_ok([item]))
    session = _session(http)
    assert session is not None
    result = session.fetch(source_id="reuters")
    assert result.item_count == 1 and result.http_status == 200
    assert result.attribution == "reputable:reuters via feeds.example.test/onyx/feed.json"
    raw = result.raw_items[0]
    assert raw["source_id"] == "reuters" and raw["source_tier"] == "reputable"
    assert raw["category"] == "geopolitics"
    assert http.calls[0] == (
        "https://feeds.example.test/onyx/feed.json",
        "feeds.example.test",
        "/onyx/feed.json",
        30,
    )


def test_fetch_output_feeds_accepted_ingestion_contract() -> None:
    item = _feed_item(
        claims=[
            {"text": "It happened", "claim_type": "fact", "consequential": True, "corroborating_source_ids": ["ap"]}
        ]
    )
    session = _session(FakeHttp(_ok([item])))
    assert session is not None
    raw_items = list(session.fetch(source_id="reuters").raw_items)
    ingestion = create_intelligence_ingestion_v1(
        gate=IntelligenceIngestionFeatureGateV1(True), now_epoch_s=lambda: NOW, project_root=ROOT
    )
    assert ingestion is not None
    result = ingestion.ingest(raw_items)
    assert result.canonical_count == 1 and result.uncorroborated_consequential == ()


def test_fetch_rejects_unknown_source_and_bad_responses() -> None:
    session = _session(FakeHttp(_ok([])))
    assert session is not None
    with pytest.raises(LiveIngestionV1ContractError, match="approved registry"):
        session.fetch(source_id="unknown")
    with pytest.raises(LiveIngestionV1Error, match="fetch failed"):
        _session(FakeHttp(LiveJsonResponseV1(503, {"items": []}))).fetch(source_id="reuters")


def test_feed_shape_drift_is_denied() -> None:
    assert _session(FakeHttp(LiveJsonResponseV1(200, {"items": "no"}))) is not None
    with pytest.raises(LiveIngestionV1Denied, match="collection drift"):
        _session(FakeHttp(LiveJsonResponseV1(200, {"items": "no"}))).fetch(source_id="reuters")
    with pytest.raises(LiveIngestionV1Denied, match="item cap"):
        _session(FakeHttp(_ok([_feed_item(id=str(i)) for i in range(MAX_ITEMS_PER_FETCH + 1)]))).fetch(
            source_id="reuters"
        )
    with pytest.raises(LiveIngestionV1Denied, match="feed item drift"):
        _session(FakeHttp(_ok(["notdict"]))).fetch(source_id="reuters")
    with pytest.raises(LiveIngestionV1Denied, match="feed claims drift"):
        _session(FakeHttp(_ok([_feed_item(claims="no")]))).fetch(source_id="reuters")
    with pytest.raises(LiveIngestionV1ContractError, match="feed id"):
        _session(FakeHttp(_ok([_feed_item(id="")]))).fetch(source_id="reuters")
    with pytest.raises(LiveIngestionV1ContractError, match="feed title"):
        _session(FakeHttp(_ok([_feed_item(title="x\x00y")]))).fetch(source_id="reuters")


def test_stdlib_client_pins_route_before_network() -> None:
    client = StdlibLiveIngestionHttpV1()
    origin, path = "feeds.example.test", "/onyx/feed.json"
    good = f"https://{origin}{path}"
    for url, o, p in (
        ("https://evil.test/onyx/feed.json", origin, path),
        (f"https://{origin}/other", origin, path),
        (f"http://{origin}{path}", origin, path),
        (f"https://{origin}{path}?q=1", origin, path),
        (f"https://{origin}{path}#x", origin, path),
    ):
        with pytest.raises(LiveIngestionV1Denied, match="route is invalid"):
            client.get_json(url=url, origin=o, path=p, timeout_seconds=30)
    with pytest.raises(LiveIngestionV1Denied, match="route is invalid"):
        client.get_json(url=good, origin=origin, path=path, timeout_seconds=5)


def test_clock_must_be_int() -> None:
    session = create_live_ingestion_v1(
        gate=LiveIngestionFeatureGateV1(True),
        sources=(SOURCE,),
        http=FakeHttp(_ok([])),
        now_epoch_s=lambda: "no",
        project_root=ROOT,
    )
    assert session is not None
    assert session.approved_source_ids() == ("reuters",)
    with pytest.raises(LiveIngestionV1ContractError, match="clock result is invalid"):
        session.fetch(source_id="reuters")


def test_feed_category_is_ignored_source_is_authoritative() -> None:
    # the approved source is approved for geopolitics; a feed label is ignored.
    item = _feed_item(category="finance_macro")
    result = _session(FakeHttp(_ok([item]))).fetch(source_id="reuters")
    assert result.raw_items[0]["category"] == "geopolitics"


def test_item_cap_boundary_accepts_exactly_max() -> None:
    at_cap = [_feed_item(id=str(i)) for i in range(MAX_ITEMS_PER_FETCH)]
    result = _session(FakeHttp(_ok(at_cap))).fetch(source_id="reuters")
    assert result.item_count == MAX_ITEMS_PER_FETCH


def test_response_dataclass_validates_status_and_payload() -> None:
    LiveJsonResponseV1(200, {"items": []})
    with pytest.raises(LiveIngestionV1ContractError, match="payload"):
        LiveJsonResponseV1(200, ["not-a-dict"])  # type: ignore[arg-type]
    for bad_status in (99, 600, True):
        with pytest.raises(LiveIngestionV1ContractError, match="status"):
            LiveJsonResponseV1(bad_status, {})  # type: ignore[arg-type]


def test_strict_json_enforces_size_and_shape() -> None:
    assert _strict_json(b'{"items": []}') == {"items": []}
    with pytest.raises(LiveIngestionV1Denied, match="size"):
        _strict_json(b"x" * (MAX_HTTP_BYTES + 1))
    with pytest.raises(LiveIngestionV1Denied, match="duplicate JSON key"):
        _strict_json(b'{"a": 1, "a": 2}')
    with pytest.raises(LiveIngestionV1Denied, match="object required"):
        _strict_json(b"[1, 2]")
    with pytest.raises(LiveIngestionV1Denied, match="JSON is invalid"):
        _strict_json(b"{not json}")


class _FakeResponse:
    def __init__(self, status: int, data: bytes) -> None:
        self.status = status
        self._data = data

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self, amount: int) -> bytes:
        return self._data


class _FakeOpener:
    def __init__(self, *, response: object = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error

    def open(self, request: object, timeout: int) -> object:
        if self._error is not None:
            raise self._error
        return self._response


def test_stdlib_client_decodes_success_error_and_size_paths() -> None:
    origin, path = "feeds.example.test", "/onyx/feed.json"
    url = f"https://{origin}{path}"

    client = StdlibLiveIngestionHttpV1()
    client._opener = _FakeOpener(response=_FakeResponse(200, b'{"items": []}'))
    ok = client.get_json(url=url, origin=origin, path=path, timeout_seconds=30)
    assert ok.status_code == 200 and ok.payload == {"items": []}

    oversize = StdlibLiveIngestionHttpV1()
    oversize._opener = _FakeOpener(response=_FakeResponse(200, b"x" * (MAX_HTTP_BYTES + 1)))
    with pytest.raises(LiveIngestionV1Denied, match="exceeded size limit"):
        oversize.get_json(url=url, origin=origin, path=path, timeout_seconds=30)

    http_error = StdlibLiveIngestionHttpV1()
    http_error._opener = _FakeOpener(
        error=urllib.error.HTTPError(url, 503, "busy", {}, io.BytesIO(b'{"error": 1}'))  # type: ignore[arg-type]
    )
    decoded = http_error.get_json(url=url, origin=origin, path=path, timeout_seconds=30)
    assert decoded.status_code == 503 and decoded.payload == {"error": 1}

    url_error = StdlibLiveIngestionHttpV1()
    url_error._opener = _FakeOpener(error=urllib.error.URLError("no route"))
    with pytest.raises(LiveIngestionV1Error, match="request failed"):
        url_error.get_json(url=url, origin=origin, path=path, timeout_seconds=30)


def test_client_opener_suppresses_redirects() -> None:
    # a mutation that unwires the no-redirect handler leaves a default handler
    # whose redirect_request returns a Request (not None) -> this test fails.
    client = StdlibLiveIngestionHttpV1()
    request = urllib.request.Request("https://feeds.example.test/onyx/feed.json")
    redirect_handlers = [h for h in client._opener.handlers if hasattr(h, "redirect_request")]
    assert redirect_handlers
    for handler in redirect_handlers:
        assert (
            handler.redirect_request(request, None, 301, "Moved", {}, "https://evil.test/")
            is None
        )


def test_source_is_route_pinned_and_actionless() -> None:
    source = (ROOT / "core" / "phase9_live_ingestion_v1.py").read_text(encoding="utf-8")
    for required in ("_NoRedirect", "live ingestion route is invalid", "redirect_request"):
        assert required in source, required
    for forbidden in (
        "subprocess",
        "def buy",
        "def sell",
        "def trade",
        "dispatch(",
        "for attempt in range",
        "Mail.Send",
    ):
        assert forbidden not in source, forbidden
