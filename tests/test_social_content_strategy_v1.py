from __future__ import annotations

import pytest

from core.social_content_strategy_v1 import (
    GeminiCaptionProviderV1,
    SocialContentStrategyError,
    SocialStrategyRequestV1,
    generate_strategic_caption_v1,
)


class _FakeProvider:
    def generate(self, *, system: str, prompt: str) -> str:
        assert "Onyx" in system and "Cyryx Labs" in system
        assert "executives" in prompt
        return "A grounded strategic caption."


def _request(**overrides):
    values = {
        "brief": "AI governance turns evidence into operational confidence",
        "brand": "Cyryx Labs",
        "platform": "linkedin",
        "audience": "executives",
        "objective": "education",
        "source_refs": ("brief-001",),
    }
    values.update(overrides)
    return SocialStrategyRequestV1(**values)


def test_local_strategy_is_deterministic_and_never_publishes():
    first = generate_strategic_caption_v1(_request())
    second = generate_strategic_caption_v1(_request())
    assert first == second
    assert first.status == "draft"
    assert "No virality" in first.warnings[0]


def test_provider_requires_explicit_network_authorization():
    with pytest.raises(PermissionError):
        generate_strategic_caption_v1(_request(), provider=_FakeProvider())
    draft = generate_strategic_caption_v1(
        _request(), provider=_FakeProvider(), allow_provider=True
    )
    assert draft.caption == "A grounded strategic caption."


def test_secret_like_input_and_output_are_rejected():
    with pytest.raises(SocialContentStrategyError, match="secret-like"):
        _request(brief="api_key=very-secret-value")

    class _LeakingProvider:
        def generate(self, **_kwargs):
            return "Authorization: Bearer leaked"

    with pytest.raises(SocialContentStrategyError, match="secret-like"):
        generate_strategic_caption_v1(
            _request(), provider=_LeakingProvider(), allow_provider=True
        )


def test_gemini_adapter_keeps_key_out_of_prompt_and_returns_text():
    observed = {}

    class _Models:
        def generate_content(self, **kwargs):
            observed.update(kwargs)
            return type("Response", (), {"text": "Gemini draft"})()

    class _Client:
        models = _Models()

    def client_factory(key):
        observed["key"] = key
        return _Client()

    adapter = GeminiCaptionProviderV1(
        client_factory=client_factory,
        api_key_getter=lambda: "credential-value",
        model="configured-model",
    )
    assert adapter.generate(system="system", prompt="prompt") == "Gemini draft"
    assert observed["key"] == "credential-value"
    assert "credential-value" not in str(observed.get("contents", ""))
