"""Default-off corrective Microsoft device sign-in bootstrap (V2).

Defect record: the first live execution of the accepted Phase 8 stack on
2026-07-23 was structurally denied by the frozen OAuth V1 device-verification
host allowlist. The live Microsoft identity platform now returns
``verification_uri = https://login.microsoft.com/device`` while the accepted
allowlist predates that host. Frozen predecessors are never edited, so this
versioned successor performs only the initial device sign-in with the
corrected host allowlist and persists the refresh token into the exact
native-vault slot the accepted OAuth V1 session already reads through
``restore()``. Every other OAuth, transport and read behavior remains the
accepted frozen implementation.

The module reuses only public frozen contracts: the settings/scope validator,
the route-pinned stdlib HTTPS client, the refresh-token native-vault binding
and the secret-free onboarding identity. It stores no client secret, prints no
token and adds no provider mutation route.
"""

from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Callable, Final, Mapping

from core.phase7_workspace_aliases_v1 import (
    CAPABILITY_PREFIX,
    WorkspaceAliasRecordV1,
    credential_vault_locator_v1,
)
from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    DEVICE_GRANT,
    IDENTITY_ORIGIN,
    GraphOAuthHttpV1,
    JsonHttpResponseV1,
    MicrosoftGraphOAuthSettingsV1,
    NativeGraphRefreshTokenVaultV1,
    RefreshTokenVaultV1,
    StdlibGraphOAuthHttpV1,
)
from core.phase8_microsoft_graph_read_v1 import GRAPH_ORIGIN, GRAPH_PREFIX

FEATURE_FLAG: Final = "ONYX_PHASE8_MS_GRAPH_DEVICE_BOOTSTRAP_V2"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxMicrosoftGraphDeviceBootstrap.v2"
WORKSPACE_ID: Final = "cyryx-live-e2e"
PRINCIPAL_ID: Final = "owner:live-e2e"
ALIAS_NAME: Final = "microsoft-live-e2e"
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_POLL_SECONDS: Final = 1_800
# Corrected over frozen OAuth V1: live provider observation on 2026-07-23
# returned https://login.microsoft.com/device; the accepted allowlist lacked
# that legitimate Microsoft identity host and denied every live sign-in.
ALLOWED_VERIFICATION_HOSTS: Final = frozenset(
    {
        "microsoft.com",
        "www.microsoft.com",
        "login.microsoftonline.com",
        "login.microsoft.com",
    }
)
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}$")
_CONSTRUCTION_KEY = object()


class DeviceBootstrapV2Error(RuntimeError):
    pass


class DeviceBootstrapV2ContractError(ValueError):
    pass


class DeviceBootstrapV2Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceBootstrapFeatureGateV2:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise DeviceBootstrapV2ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "DeviceBootstrapFeatureGateV2":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class DeviceBootstrapResultV2:
    account_id: str
    tenant_id: str
    scopes: tuple[str, ...]
    refresh_token_stored: bool
    access_expires_in_s: int


def build_runner_credential_record(
    *,
    onboarding: MicrosoftGraphLiveOnboardingV1,
    now_ms: int,
) -> WorkspaceAliasRecordV1:
    """Build the exact in-memory credential identity the accepted runner uses.

    ``credential_vault_locator_v1`` is deterministic over workspace, provider,
    tenant and account, so the derived native-vault slot is identical to the
    one the accepted live-E2E runner resolves for its own alias catalog. No
    control-plane store is created and no secret is contained in this record.
    """

    if type(onboarding) is not MicrosoftGraphLiveOnboardingV1:
        raise DeviceBootstrapV2ContractError("exact onboarding identity required")
    if type(now_ms) is not int or now_ms < 0:
        raise DeviceBootstrapV2ContractError("current time is invalid")
    service, vault_account, locator = credential_vault_locator_v1(
        workspace_id=WORKSPACE_ID,
        provider="microsoft-graph",
        account_id=onboarding.account_id,
        tenant_id=onboarding.tenant_id,
    )
    alias_id = CAPABILITY_PREFIX + hashlib.sha256(locator.encode()).hexdigest()
    return WorkspaceAliasRecordV1(
        alias_id,
        WORKSPACE_ID,
        PRINCIPAL_ID,
        "credential",
        ALIAS_NAME,
        locator,
        "active",
        now_ms,
        now_ms,
        None,
        provider="microsoft-graph",
        account_id=onboarding.account_id,
        tenant_id=onboarding.tenant_id,
        scopes=("Calendars.Read", "Mail.Read"),
        vault_service=service,
        vault_account=vault_account,
    )


def _text(value: object, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise DeviceBootstrapV2Denied("provider text contract drift")
    return value


def _positive_int(value: object, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise DeviceBootstrapV2Denied("provider integer contract drift")
    return value


def _verification_uri(value: object) -> str:
    uri = _text(value, 2_048)
    parsed = urllib.parse.urlparse(uri)
    if (
        parsed.scheme != "https"
        or parsed.netloc.casefold() not in ALLOWED_VERIFICATION_HOSTS
        or parsed.fragment
    ):
        raise DeviceBootstrapV2Denied("device verification URI is invalid")
    return uri


class MicrosoftGraphDeviceBootstrapV2:
    """One-shot corrected device sign-in that primes the accepted vault slot."""

    __slots__ = (
        "_clock_epoch_s",
        "_http",
        "_onboarding",
        "_settings",
        "_sleeper",
        "_vault",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        onboarding: MicrosoftGraphLiveOnboardingV1,
        settings: MicrosoftGraphOAuthSettingsV1,
        http: GraphOAuthHttpV1,
        vault: RefreshTokenVaultV1,
        sleeper: Callable[[int], None],
        clock_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise DeviceBootstrapV2ContractError(
                "use create_microsoft_graph_device_bootstrap_v2"
            )
        self._onboarding = onboarding
        self._settings = settings
        self._http = http
        self._vault = vault
        self._sleeper = sleeper
        self._clock_epoch_s = clock_epoch_s

    def _token_url(self) -> str:
        tenant = urllib.parse.quote(self._settings.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/token"

    def _device_url(self) -> str:
        tenant = urllib.parse.quote(self._settings.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/devicecode"

    def _scope_text(self) -> str:
        return " ".join(sorted(self._settings.scopes, key=str.casefold))

    def _verify_account(self, access_token: str) -> None:
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}{GRAPH_PREFIX}me",
            query=(("$select", "id,mail,userPrincipalName"),),
            headers=(("Authorization", f"Bearer {access_token}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise DeviceBootstrapV2Denied("signed-in Microsoft account unavailable")
        candidates = {
            value.casefold()
            for value in (
                response.payload.get("mail"),
                response.payload.get("userPrincipalName"),
            )
            if type(value) is str and _EMAIL.fullmatch(value)
        }
        if self._onboarding.account_id.casefold() not in candidates:
            raise DeviceBootstrapV2Denied("signed-in Microsoft account mismatch")

    def sign_in(self, *, echo: Callable[[str], None]) -> DeviceBootstrapResultV2:
        if not callable(echo):
            raise DeviceBootstrapV2ContractError("exact echo callable required")
        response = self._http.post_form(
            url=self._device_url(),
            fields=(
                ("client_id", self._settings.client_id),
                ("scope", self._scope_text()),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise DeviceBootstrapV2Error("Microsoft device authorization failed")
        device_code = _text(response.payload.get("device_code"), 2_048)
        user_code = _text(response.payload.get("user_code"), 100)
        verification_uri = _verification_uri(
            response.payload.get("verification_uri")
        )
        expires_in = _positive_int(
            response.payload.get("expires_in"), minimum=60, maximum=MAX_POLL_SECONDS
        )
        interval = _positive_int(
            response.payload.get("interval", 5), minimum=1, maximum=60
        )
        echo(f"Verification URL : {verification_uri}")
        echo(f"User code        : {user_code}")
        started = self._clock_epoch_s()
        while True:
            now = self._clock_epoch_s()
            if type(now) is not int or now - started >= expires_in:
                raise DeviceBootstrapV2Error("device sign-in window expired")
            token = self._http.post_form(
                url=self._token_url(),
                fields=(
                    ("grant_type", DEVICE_GRANT),
                    ("client_id", self._settings.client_id),
                    ("device_code", device_code),
                ),
                timeout_seconds=HTTP_TIMEOUT_SECONDS,
            )
            if token.status_code == 200:
                break
            error = token.payload.get("error")
            if error == "authorization_pending":
                self._sleeper(interval)
                continue
            if error == "slow_down":
                interval = min(60, interval + 5)
                self._sleeper(interval)
                continue
            if error in {"authorization_declined", "expired_token"}:
                raise DeviceBootstrapV2Error(f"device sign-in ended: {error}")
            raise DeviceBootstrapV2Error("Microsoft device token exchange failed")
        token_type = _text(token.payload.get("token_type"), 30)
        access_token = _text(token.payload.get("access_token"), 16_384)
        refresh_token = _text(token.payload.get("refresh_token"), 1_800)
        expires_in_s = _positive_int(
            token.payload.get("expires_in"), minimum=60, maximum=86_400
        )
        scope_text = _text(token.payload.get("scope"), 2_000)
        granted = frozenset(scope_text.split())
        required = set(self._settings.scopes) - {"offline_access"}
        if token_type.casefold() != "bearer" or not required.issubset(granted):
            raise DeviceBootstrapV2Denied("Microsoft granted scope drift")
        self._verify_account(access_token)
        self._vault.set_refresh_token(refresh_token)
        return DeviceBootstrapResultV2(
            self._onboarding.account_id,
            self._onboarding.tenant_id,
            self._settings.scopes,
            True,
            expires_in_s,
        )


def create_microsoft_graph_device_bootstrap_v2(
    *,
    gate: DeviceBootstrapFeatureGateV2 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    http: GraphOAuthHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    sleeper: Callable[[int], None] | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    now_ms: int | None = None,
) -> MicrosoftGraphDeviceBootstrapV2 | None:
    selected = DeviceBootstrapFeatureGateV2.from_environ() if gate is None else gate
    if type(selected) is not DeviceBootstrapFeatureGateV2:
        raise DeviceBootstrapV2ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    chosen = (
        MicrosoftGraphLiveOnboardingV1.from_environ()
        if onboarding is None
        else onboarding
    )
    if type(chosen) is not MicrosoftGraphLiveOnboardingV1:
        raise DeviceBootstrapV2ContractError("exact onboarding identity required")
    if sleeper is None or clock_epoch_s is None or now_ms is None:
        raise DeviceBootstrapV2ContractError(
            "enabled bootstrap requires complete bindings"
        )
    if not callable(sleeper) or not callable(clock_epoch_s):
        raise DeviceBootstrapV2ContractError("exact sleeper and clock are required")
    settings = chosen.settings()
    selected_http = StdlibGraphOAuthHttpV1() if http is None else http
    selected_vault = (
        NativeGraphRefreshTokenVaultV1(
            build_runner_credential_record(onboarding=chosen, now_ms=now_ms)
        )
        if vault is None
        else vault
    )
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "get_json")
        or not hasattr(selected_vault, "set_refresh_token")
    ):
        raise DeviceBootstrapV2ContractError("bootstrap transport or vault invalid")
    return MicrosoftGraphDeviceBootstrapV2(
        construction_key=_CONSTRUCTION_KEY,
        onboarding=chosen,
        settings=settings,
        http=selected_http,
        vault=selected_vault,
        sleeper=sleeper,
        clock_epoch_s=clock_epoch_s,
    )


__all__ = [
    "ALLOWED_VERIFICATION_HOSTS",
    "DeviceBootstrapFeatureGateV2",
    "DeviceBootstrapResultV2",
    "DeviceBootstrapV2ContractError",
    "DeviceBootstrapV2Denied",
    "DeviceBootstrapV2Error",
    "FEATURE_FLAG",
    "MicrosoftGraphDeviceBootstrapV2",
    "build_runner_credential_record",
    "create_microsoft_graph_device_bootstrap_v2",
]
