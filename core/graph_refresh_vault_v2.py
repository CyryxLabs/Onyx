"""Single-record, native-vault Graph token rotation without changing V1 limits."""
from __future__ import annotations

import hmac

from core import native_vault
from core.phase8_microsoft_graph_oauth_v1 import (
    GraphOAuthV1Denied,
    GraphOAuthV1Error,
    NativeGraphRefreshTokenVaultV1,
)
from core.phase7_workspace_aliases_v1 import WorkspaceAliasRecordV1


# This is the existing cross-platform native primitive's bound, not the larger
# Windows API maximum. No chunking, file fallback, or global limit change.
MAX_REFRESH_TOKEN_BYTES_V2 = 2048
_DISCONNECTED = b"\x00"


def validate_refresh_token_v2(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > MAX_REFRESH_TOKEN_BYTES_V2
        or any(ord(character) < 32 for character in value)
    ):
        raise GraphOAuthV1Denied("Graph V2 refresh token contract invalid")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeError:
        raise GraphOAuthV1Denied("Graph V2 refresh token encoding invalid") from None
    if len(raw) > MAX_REFRESH_TOKEN_BYTES_V2:
        raise GraphOAuthV1Denied("Graph V2 refresh token exceeds native capacity")
    # Keep the successor subordinate to the actual native primitive as well.
    native_vault._bounded_secret(raw)
    return value


class NativeGraphRefreshTokenVaultV2:
    """Use a V2 slot; import V1 on read only until V2 has committed.

    A replacement is one protected native write followed by exact readback.
    Writers retain native last-writer-wins semantics; mismatched readback is an
    unknown outcome, never grounds to overwrite or delete a competing value.
    A tombstone prevents disconnect from falling back to a retained V1 token.
    """

    __slots__ = ("_legacy", "_vault")

    def __init__(self, credential: WorkspaceAliasRecordV1) -> None:
        self._legacy = NativeGraphRefreshTokenVaultV1(credential)
        reference = self._legacy._vault.reference
        self._vault = native_vault.NativeSecretVault(
            native_vault.SecretReference(
                "CyryxLabs.Onyx.GraphOAuth.v2",
                reference.account,
                "Cyryx Labs Onyx Microsoft Graph refresh token V2",
            )
        )

    def get_refresh_token(self) -> str | None:
        try:
            raw = self._vault.get_bytes()
            if raw is None:
                return self._legacy.get_refresh_token()
            if raw == _DISCONNECTED:
                return None
            value = raw.decode("utf-8", errors="strict")
        except (native_vault.NativeVaultError, UnicodeError):
            raise GraphOAuthV1Error("Graph V2 native vault read failed") from None
        return validate_refresh_token_v2(value)

    def _commit(self, raw: bytes) -> None:
        try:
            self._vault.set_bytes(raw)
            observed = self._vault.get_bytes()
        except native_vault.NativeVaultError:
            # Native APIs may fail before/after persistence. Never roll back by
            # overwriting an unobserved value or reveal backend exception data.
            raise GraphOAuthV1Error("Graph V2 native commit outcome unknown") from None
        if type(observed) is not bytes or not hmac.compare_digest(observed, raw):
            raise GraphOAuthV1Error("Graph V2 native commit verification failed")

    def set_refresh_token(self, value: str) -> None:
        self._commit(validate_refresh_token_v2(value).encode("utf-8"))

    def delete_refresh_token(self) -> bool:
        existed = self.get_refresh_token() is not None
        self._commit(_DISCONNECTED)
        return existed
