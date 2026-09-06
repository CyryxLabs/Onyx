from __future__ import annotations

from dataclasses import asdict, replace

from core.capability_ports.model_router_v1 import (
    ModelRouteRequestV1,
    ModelRouteV1,
    ModelRouterCapabilityPortV1,
    ModelRoutingPolicyV1,
)


LIVE = ("gemini", "gemini-live-original")
TEXT = ("ollama", "llama3.2")
REMOTE_TEXT = ("openai-compatible", "qwen-2.5")


def _router(**config: object) -> ModelRouterCapabilityPortV1:
    policy = ModelRoutingPolicyV1(
        principal_id="owner",
        workspace_id="workspace-a",
        generation=7,
        routes=(
            ModelRouteV1(*LIVE, ("live",), ("public", "internal"), 8_192, 50_000),
            ModelRouteV1(*TEXT, ("text",), ("public", "internal", "private"), 4_096, 5_000),
            ModelRouteV1(*REMOTE_TEXT, ("text",), ("public", "internal"), 4_096, 20_000),
        ),
        max_tokens=8_192,
        max_cost_micro_usd=50_000,
    )
    return ModelRouterCapabilityPortV1(policy, descriptive_config=config)


def _request(route: tuple[str, str] = TEXT, **changes: object) -> ModelRouteRequestV1:
    values: dict[str, object] = {
        "principal_id": "owner",
        "workspace_id": "workspace-a",
        "generation": 7,
        "privacy_class": "internal",
        "modality": "text",
        "provider_id": route[0],
        "model_id": route[1],
        "requested_tokens": 1_000,
        "estimated_cost_micro_usd": 1_000,
        "explicit_fallbacks": (),
    }
    values.update(changes)
    return ModelRouteRequestV1(**values)  # type: ignore[arg-type]


def test_private_prompt_is_denied_for_route_without_private_authority() -> None:
    decision = _router().evaluate(
        _request(REMOTE_TEXT, privacy_class="private"),
        available_routes=(REMOTE_TEXT,),
    )
    assert (decision.status, decision.reason_code) == ("denied", "privacy_not_allowed")


def test_provider_outage_is_explicit_and_never_silently_falls_back() -> None:
    decision = _router().evaluate(_request(), available_routes=(REMOTE_TEXT,))
    assert (decision.status, decision.reason_code) == ("outage", "provider_unavailable")
    assert decision.selected_provider_id is None


def test_cost_ceiling_is_fail_closed() -> None:
    decision = _router().evaluate(
        _request(estimated_cost_micro_usd=5_001), available_routes=(TEXT,)
    )
    assert (decision.status, decision.reason_code) == ("denied", "cost_ceiling_exceeded")


def test_token_ceiling_is_fail_closed() -> None:
    decision = _router().evaluate(
        _request(requested_tokens=4_097), available_routes=(TEXT,)
    )
    assert (decision.status, decision.reason_code) == ("denied", "token_ceiling_exceeded")


def test_unknown_model_is_denied_even_if_descriptive_config_lists_it() -> None:
    unknown = ("ollama", "unsealed-model")
    decision = _router(models=[unknown]).evaluate(
        _request(unknown), available_routes=(unknown,)
    )
    assert (decision.status, decision.reason_code) == ("denied", "route_not_allowed")


def test_explicit_fallback_cannot_widen_the_sealed_allowed_set() -> None:
    unknown = ("emergency-provider", "emergency-model")
    decision = _router(fallbacks=[unknown]).evaluate(
        _request(explicit_fallbacks=(unknown,)), available_routes=(unknown,)
    )
    assert (decision.status, decision.reason_code) == ("denied", "route_not_allowed")


def test_wrong_workspace_and_stale_generation_are_distinct_denials() -> None:
    router = _router()
    wrong_principal = router.evaluate(
        _request(principal_id="other-owner"), available_routes=(TEXT,)
    )
    wrong_workspace = router.evaluate(
        _request(workspace_id="workspace-b"), available_routes=(TEXT,)
    )
    stale = router.evaluate(_request(generation=6), available_routes=(TEXT,))
    assert wrong_principal.reason_code == "scope_binding_mismatch"
    assert wrong_workspace.reason_code == "scope_binding_mismatch"
    assert stale.reason_code == "stale_generation"


def test_live_and_text_use_the_same_redacted_parity_representation() -> None:
    router = _router()
    text = router.evaluate(_request(), available_routes=(TEXT,))
    live = router.evaluate(
        _request(LIVE, modality="live"), available_routes=(LIVE,)
    )
    assert type(text) is type(live)
    assert set(asdict(text)) == set(asdict(live))
    assert text.modality == "text" and live.modality == "live"
    assert text.redacted is live.redacted is True
    assert text.shadow_only is live.shadow_only is True


def test_decision_is_deterministic_rollback_compatible_and_provider_free() -> None:
    router = _router()
    request = _request(explicit_fallbacks=(REMOTE_TEXT,))
    first = router.evaluate(request, available_routes=(REMOTE_TEXT,))
    second = router.evaluate(replace(request), available_routes=(REMOTE_TEXT,))
    assert first == second
    assert first.used_explicit_fallback is True
    assert first.provider_called is False
    assert not hasattr(router, "dispatch")
    assert not hasattr(router, "call_provider")
    output = repr(first)
    assert len(output) < 1_024
    assert "prompt" not in output.casefold()
