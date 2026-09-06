from __future__ import annotations

from pathlib import Path

import pytest

from core.phase9_intelligence_ingestion_v1 import (
    FEATURE_FLAG,
    MAX_CLAIMS_PER_ITEM,
    MAX_ITEMS,
    MAX_SOURCE_IDS,
    MAX_TEXT_BYTES,
    SOURCE_TIERS,
    IntelligenceIngestionFeatureGateV1,
    IntelligenceIngestionV1ContractError,
    IntelligenceIngestionV1Denied,
    create_intelligence_ingestion_v1,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = 1_785_000_000  # deterministic clock == 2026-07-25T17:20:00Z


def _session(now: int = NOW):
    return create_intelligence_ingestion_v1(
        gate=IntelligenceIngestionFeatureGateV1(True),
        now_epoch_s=lambda: now,
        project_root=ROOT,
    )


def _item(**overrides) -> dict:
    base = {
        "item_id": "a",
        "category": "ai_tech_cyber",
        "source_id": "reuters",
        "source_tier": "reputable",
        "url": "https://example.test/a",
        "title": "OpenAI ships a new model",
        "publication_datetime": "2026-07-24T10:00:00Z",
        "event_datetime": "2026-07-24T09:00:00Z",
        "claims": [],
    }
    base.update(overrides)
    return base


def test_feature_gate_is_exact_and_default_off() -> None:
    assert not IntelligenceIngestionFeatureGateV1.from_environ({}).enabled
    assert IntelligenceIngestionFeatureGateV1.from_environ({FEATURE_FLAG: "true"}).enabled
    for value in ("1", "TRUE", " true", "yes", "True"):
        assert not IntelligenceIngestionFeatureGateV1.from_environ(
            {FEATURE_FLAG: value}
        ).enabled
    assert (
        create_intelligence_ingestion_v1(
            gate=IntelligenceIngestionFeatureGateV1(False),
            project_root=ROOT / "missing",
        )
        is None
    )


def test_factory_is_sealed_and_entry_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(IntelligenceIngestionV1ContractError, match="sealed feature gate"):
        create_intelligence_ingestion_v1(gate=True)  # type: ignore[arg-type]
    with pytest.raises(IntelligenceIngestionV1ContractError, match="requires a clock"):
        create_intelligence_ingestion_v1(
            gate=IntelligenceIngestionFeatureGateV1(True), project_root=ROOT
        )
    monkeypatch.setattr(
        "core.phase9_intelligence_ingestion_v1.ACCEPTED_P8_EXIT_ROOTS",
        (("missing.json", "0" * 64),),
    )
    with pytest.raises(IntelligenceIngestionV1Denied, match="evidence unavailable"):
        create_intelligence_ingestion_v1(
            gate=IntelligenceIngestionFeatureGateV1(True),
            now_epoch_s=lambda: NOW,
            project_root=ROOT,
        )


def test_normalizes_temporal_and_claim_types() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(
                claims=[
                    {"text": "Model released", "claim_type": "fact"},
                    {"text": "May disrupt search", "claim_type": "scenario"},
                    {"text": "We should evaluate", "claim_type": "recommendation"},
                    {"text": "Likely rushed", "claim_type": "inference"},
                ]
            )
        ]
    )
    assert result.canonical_count == 1 and result.duplicate_count == 0
    item = result.items[0]
    # publication and event time are recorded separately, both normalized to UTC.
    assert item.publication_utc == "2026-07-24T10:00:00+00:00"
    assert item.event_utc == "2026-07-24T09:00:00+00:00"
    assert item.publication_utc != item.event_utc
    assert tuple(c.claim_type for c in item.claims) == (
        "fact",
        "scenario",
        "recommendation",
        "inference",
    )
    assert result.by_category == {"ai_tech_cyber": 1}
    assert result.generated_at_utc.endswith("+00:00")


def test_recycled_story_dedup_keeps_earliest_publication() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(
                item_id="late",
                title="OpenAI  SHIPS a New Model!!!",
                publication_datetime="2026-07-24T12:00:00Z",
            ),
            _item(
                item_id="early",
                title="OpenAI ships a new model",
                publication_datetime="2026-07-24T10:00:00Z",
            ),
        ]
    )
    by_id = {i.item_id: i for i in result.items}
    assert by_id["early"].duplicate_of is None
    assert by_id["late"].duplicate_of == "early"
    assert by_id["early"].content_signature == by_id["late"].content_signature
    assert result.canonical_count == 1 and result.duplicate_count == 1


def test_same_headline_different_category_is_not_a_duplicate() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(item_id="a", category="ai_tech_cyber", title="Rates move today"),
            _item(item_id="b", category="finance_macro", title="Rates move today"),
        ]
    )
    assert result.duplicate_count == 0 and result.canonical_count == 2
    assert result.items[0].content_signature != result.items[1].content_signature


def test_consequential_claim_requires_independent_corroboration() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(
                item_id="a",
                source_id="reuters",
                claims=[
                    {
                        "text": "Independently confirmed",
                        "claim_type": "fact",
                        "consequential": True,
                        "corroborating_source_ids": ["ap"],
                    },
                    {
                        "text": "Self cited only",
                        "claim_type": "fact",
                        "consequential": True,
                        "corroborating_source_ids": ["reuters"],
                    },
                    {
                        "text": "Not consequential",
                        "claim_type": "inference",
                        "consequential": False,
                        "corroborating_source_ids": [],
                    },
                ],
            )
        ]
    )
    item = result.items[0]
    assert item.claims[0].corroborated is True
    assert item.claims[1].corroborated is False
    assert item.claims[2].corroborated is False
    # only the consequential, self-cited claim is surfaced as uncorroborated.
    assert result.uncorroborated_consequential == (("a", 1),)


def test_source_health_tiers_and_unverified_count() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(item_id="a", source_tier="primary"),
            _item(item_id="b", source_tier="unverified", title="Second headline"),
        ]
    )
    assert result.unverified_source_count == 1
    with pytest.raises(IntelligenceIngestionV1ContractError, match="source_tier"):
        session.ingest([_item(source_tier="rumor")])
    assert "unverified" in SOURCE_TIERS and "primary" == SOURCE_TIERS[0]


def test_freshness_computed_and_future_publication_denied() -> None:
    session = _session(now=NOW)
    assert session is not None
    # publication 3600s before the clock (2026-07-25T17:20Z) -> 1 hour freshness.
    result = session.ingest(
        [_item(publication_datetime="2026-07-25T16:20:00Z")]
    )
    assert result.items[0].freshness_hours == 1
    with pytest.raises(IntelligenceIngestionV1Denied, match="future"):
        session.ingest([_item(publication_datetime="2027-01-01T00:00:00Z")])


def test_rejects_malformed_input() -> None:
    session = _session()
    assert session is not None
    with pytest.raises(IntelligenceIngestionV1ContractError, match="batch is invalid"):
        session.ingest("notalist")
    with pytest.raises(IntelligenceIngestionV1ContractError, match="batch is invalid"):
        session.ingest([_item() for _ in range(MAX_ITEMS + 1)])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="item must be an object"):
        session.ingest(["notdict"])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="category"):
        session.ingest([_item(category="sports")])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="claim_type"):
        session.ingest([_item(claims=[{"text": "x", "claim_type": "opinion"}])])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="consequential"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact", "consequential": 1}])]
        )
    with pytest.raises(IntelligenceIngestionV1ContractError, match="title"):
        session.ingest([_item(title="")])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="title"):
        session.ingest([_item(title="bad\x00title")])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="ISO-8601"):
        session.ingest([_item(publication_datetime="not-a-date")])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="duplicate item_id"):
        session.ingest([_item(item_id="a"), _item(item_id="a", title="Other")])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="claims block"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact"}] * (MAX_CLAIMS_PER_ITEM + 1))]
        )


def test_deterministic_and_side_effect_free() -> None:
    session = _session()
    assert session is not None
    batch = [
        _item(item_id="a", title="One"),
        _item(item_id="b", title="Two", category="geopolitics"),
    ]
    first = session.ingest(batch)
    second = session.ingest(batch)
    assert first == second


def test_nonlatin_titles_dedup_by_content_not_category() -> None:
    session = _session()
    assert session is not None
    # Two unrelated non-Latin headlines in one category must NOT be duplicates.
    result = session.ingest(
        [
            _item(item_id="ru", category="geopolitics", title="Россия и Украина"),
            _item(item_id="cn", category="geopolitics", title="中国宣布新政策"),
        ]
    )
    assert result.duplicate_count == 0 and result.canonical_count == 2
    assert result.items[0].content_signature != result.items[1].content_signature
    # Identical non-Latin headlines in the same category DO collapse.
    dup = session.ingest(
        [
            _item(
                item_id="a",
                category="geopolitics",
                title="中国宣布新政策",
                publication_datetime="2026-07-24T10:00:00Z",
            ),
            _item(
                item_id="b",
                category="geopolitics",
                title="中国宣布新政策",
                publication_datetime="2026-07-24T11:00:00Z",
            ),
        ]
    )
    assert dup.duplicate_count == 1
    assert {i.item_id: i.duplicate_of for i in dup.items} == {"a": None, "b": "a"}


def test_dedup_tie_break_uses_item_id_on_equal_publication() -> None:
    session = _session()
    assert session is not None
    pub = "2026-07-24T10:00:00Z"
    result = session.ingest(
        [
            {**_item(item_id="c", publication_datetime=pub)},
            {**_item(item_id="a", publication_datetime=pub)},
            {**_item(item_id="b", publication_datetime=pub)},
        ]
    )
    # Same signature, same publication -> lowest item_id is canonical.
    canonical = [i for i in result.items if i.duplicate_of is None]
    assert len(canonical) == 1 and canonical[0].item_id == "a"
    assert result.duplicate_count == 2
    assert all(i.duplicate_of == "a" for i in result.items if i.item_id != "a")


def test_entry_bind_detects_evidence_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    # An existing accepted-evidence file whose hash no longer matches -> drift.
    monkeypatch.setattr(
        "core.phase9_intelligence_ingestion_v1.ACCEPTED_P8_EXIT_ROOTS",
        (("docs/onyx/checkpoints/phase8-exit-candidate-v1/manifest.json", "0" * 64),),
    )
    with pytest.raises(IntelligenceIngestionV1Denied, match="evidence drift"):
        create_intelligence_ingestion_v1(
            gate=IntelligenceIngestionFeatureGateV1(True),
            now_epoch_s=lambda: NOW,
            project_root=ROOT,
        )


def test_future_event_time_is_allowed() -> None:
    session = _session()
    assert session is not None
    result = session.ingest(
        [
            _item(
                publication_datetime="2026-07-24T10:00:00Z",
                event_datetime="2030-01-01T00:00:00Z",
            )
        ]
    )
    assert result.items[0].event_utc == "2030-01-01T00:00:00+00:00"


def test_freshness_is_zero_when_publication_equals_now() -> None:
    session = _session(now=NOW)
    assert session is not None
    result = session.ingest([_item(publication_datetime="2026-07-25T17:20:00Z")])
    assert result.items[0].freshness_hours == 0


def test_corroborating_source_id_bounds_enforced() -> None:
    session = _session()
    assert session is not None
    over = [f"s{i}" for i in range(MAX_SOURCE_IDS + 1)]
    with pytest.raises(IntelligenceIngestionV1ContractError, match="corroborating_source_ids"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact", "corroborating_source_ids": over}])]
        )
    with pytest.raises(IntelligenceIngestionV1ContractError, match="corroborating_source_ids"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact", "corroborating_source_ids": "s1"}])]
        )
    with pytest.raises(IntelligenceIngestionV1ContractError, match="corroborating source id"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact", "corroborating_source_ids": [1]}])]
        )


def test_additional_malformed_inputs_rejected() -> None:
    session = _session()
    assert session is not None
    with pytest.raises(IntelligenceIngestionV1ContractError, match="claim must be an object"):
        session.ingest([_item(claims=["notdict"])])
    # oversize title measured in UTF-8 bytes, not code points.
    with pytest.raises(IntelligenceIngestionV1ContractError, match="title"):
        session.ingest([_item(title="a" * (MAX_TEXT_BYTES + 1))])
    with pytest.raises(IntelligenceIngestionV1ContractError, match="corroborating source id"):
        session.ingest(
            [_item(claims=[{"text": "x", "claim_type": "fact", "corroborating_source_ids": [""]}])]
        )
    bad_clock = create_intelligence_ingestion_v1(
        gate=IntelligenceIngestionFeatureGateV1(True),
        now_epoch_s=lambda: "not-an-int",
        project_root=ROOT,
    )
    assert bad_clock is not None
    with pytest.raises(IntelligenceIngestionV1ContractError, match="clock result is invalid"):
        bad_clock.ingest([_item()])


def test_source_has_no_network_model_or_action() -> None:
    source = (ROOT / "core" / "phase9_intelligence_ingestion_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "import requests",
        "urllib.request",
        "http",
        "socket",
        "subprocess",
        "llm",
        "openai",
        "dispatch(",
        "def buy",
        "def sell",
        "def trade",
    ):
        assert forbidden not in source, forbidden
