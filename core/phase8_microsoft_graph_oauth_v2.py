"""Additive OAuth successor: native-capacity refresh tokens, unchanged guards.

V1 evidence and source remain immutable. Construction first runs the V1
factory's complete alias/settings/evidence validation. Only token acceptance
and the selected native refresh vault differ in this successor.
"""
from __future__ import annotations

import time
from pathlib import Path

from core import phase8_microsoft_graph_oauth_v1 as v1
from core import phase8_microsoft_graph_live_read_v1 as read_v1
from core.graph_refresh_vault_v2 import (
    NativeGraphRefreshTokenVaultV2,
    validate_refresh_token_v2,
)


_CONSTRUCTION_KEY_V2 = object()


class MicrosoftGraphOAuthSessionV2(v1.MicrosoftGraphOAuthSessionV1):
    __slots__ = ()

    def __init__(self, *, construction_key: object, validated: object, vault) -> None:
        if (
            construction_key is not _CONSTRUCTION_KEY_V2
            or type(validated) is not v1.MicrosoftGraphOAuthSessionV1
        ):
            raise v1.GraphOAuthV1ContractError("use Graph OAuth V2 factory")
        super().__init__(
            construction_key=v1._CONSTRUCTION_KEY,
            aliases=validated._aliases,
            credential=validated._credential,
            settings=validated._settings,
            http=validated._http,
            vault=vault,
        )

    def _accept_token_payload(
        self, payload: dict[str, object], *, now_ms: int, now_epoch_s: int,
        require_refresh: bool, previous_refresh: str | None = None,
    ) -> None:
        self._attest(now_ms)
        token_type = v1._text(payload.get("token_type"), 30)
        access_token = v1._text(payload.get("access_token"), 16_384)
        expires_in = v1._positive_int(
            payload.get("expires_in"), label="access expiry", minimum=60, maximum=86_400
        )
        granted = frozenset(v1._text(payload.get("scope"), 2_000).split())
        required = set(self._settings.scopes) - {"offline_access"}
        if token_type.casefold() != "bearer" or not required.issubset(granted):
            raise v1.GraphOAuthV1Denied("Microsoft granted scope drift")
        refresh_value = payload.get("refresh_token", previous_refresh)
        # Match V1's omitted/null replacement semantics without truncation.
        if refresh_value is None:
            refresh_value = previous_refresh
        refresh = (
            None if refresh_value is None else validate_refresh_token_v2(refresh_value)
        )
        if require_refresh and refresh is None:
            raise v1.GraphOAuthV1Denied("Microsoft refresh token unavailable")
        self._verify_account(access_token)
        # Re-attest after network I/O and before persisting/activating rotation.
        self._attest(now_ms)
        if refresh is not None:
            self._vault.set_refresh_token(refresh)
            self._refresh_present = True
        self._access_token = access_token
        self._access_expires_at = now_epoch_s + expires_in


def create_microsoft_graph_oauth_v2(**options) -> MicrosoftGraphOAuthSessionV2 | None:
    validated = v1.create_microsoft_graph_oauth_v1(**options)
    if validated is None:
        return None
    vault = options.get("vault")
    if vault is None:
        vault = NativeGraphRefreshTokenVaultV2(validated._credential)
    return MicrosoftGraphOAuthSessionV2(
        construction_key=_CONSTRUCTION_KEY_V2, validated=validated, vault=vault
    )


def create_microsoft_graph_live_read_transport_v2(
    *, gate=None, session=None, http=None, clock_epoch_s=None, clock_ms=None,
    sleeper=None, policy=None, project_root=None,
) -> read_v1.MicrosoftGraphLiveReadTransportV1 | None:
    """Admit only the exact V2 session to the unchanged bounded GET engine."""
    selected = read_v1.GraphLiveReadFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not read_v1.GraphLiveReadFeatureGateV1:
        raise read_v1.GraphLiveReadV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    read_v1._verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    if (
        type(session) is not MicrosoftGraphOAuthSessionV2
        or not callable(clock_epoch_s) or not callable(clock_ms)
    ):
        raise read_v1.GraphLiveReadV1ContractError("Graph V2 session and clocks required")
    selected_http = v1.StdlibGraphOAuthHttpV1() if http is None else http
    selected_sleeper = time.sleep if sleeper is None else sleeper
    selected_policy = read_v1.GraphLiveReadRetryPolicyV1() if policy is None else policy
    if (
        not hasattr(selected_http, "get_json") or not callable(selected_sleeper)
        or type(selected_policy) is not read_v1.GraphLiveReadRetryPolicyV1
    ):
        raise read_v1.GraphLiveReadV1ContractError("live-read dependency is invalid")
    return read_v1.MicrosoftGraphLiveReadTransportV1(
        construction_key=read_v1._CONSTRUCTION_KEY, session=session,
        http=selected_http, clock_epoch_s=clock_epoch_s, clock_ms=clock_ms,
        sleeper=selected_sleeper, policy=selected_policy,
    )
