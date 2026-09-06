"""Default-off Microsoft Graph OneDrive/Office read-only vertical slice.

This successor adds read-only OneDrive access, strictly per the PRD order
(read metadata before any mutation). It acquires a delegated ``Files.Read``
token from the native-vault refresh token, exposes route-pinned GET listing of
the drive root, a folder's children and a single item's metadata, and returns
bounded normalized ``DriveItemV1`` records. It performs no content download, no
upload, no rename/move/delete and no share mutation, and adds no runtime
wiring.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Final, Mapping, Protocol
from urllib.parse import parse_qsl, urlparse

from core.phase8_microsoft_graph_live_read_e2e_v1 import (
    MicrosoftGraphLiveOnboardingV1,
)
from core.phase8_microsoft_graph_oauth_v1 import (
    IDENTITY_ORIGIN,
    JsonHttpResponseV1,
    RefreshTokenVaultV1,
)
from core.phase8_microsoft_graph_read_v1 import GRAPH_ORIGIN

FEATURE_FLAG: Final = "ONYX_PHASE8_MICROSOFT_GRAPH_DRIVE_V1"
ENABLED_VALUE: Final = "true"
READ_SCOPES: Final = ("Files.Read", "User.Read", "offline_access")
HTTP_TIMEOUT_SECONDS: Final = 30
MAX_HTTP_BYTES: Final = 1_048_576
ACCESS_EXPIRY_SKEW: Final = 90
MAX_PAGES: Final = 5
MAX_ITEMS: Final = 500
_SELECT: Final = "id,name,size,folder,file,lastModifiedDateTime,webUrl"
ACCEPTED_TASKS_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase8-microsoft-graph-tasks-v1/manifest.json",
        "44337ca6fdd348cd8ff7010d8ffeeb6fd6bc3167b4b80f0e3a08888b1bc859a8",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001.md",
        "8940ab667fd20ed168335d45a3a5c65df11c2644d39cf5832a9a0c686dc93ee7",
    ),
    (
        "docs/onyx/acceptance/VE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001.manifest.json",
        "51061cd36e1688c97d80c5cad9f3ec796bb7a623ca99f29e159b4648522af7a5",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P8-MICROSOFT-GRAPH-TASKS-V1-E6-001.sha256",
        "c0a9e00072300963e32103fe116f185256869db6069d3d2b7b910d0fb5892d9e",
    ),
)
_TOKEN_PATH = re.compile(
    r"^/(?:common|organizations|consumers|[0-9a-f-]{36})/oauth2/v2\.0/token$",
    re.IGNORECASE,
)
_DRIVE_PATH = re.compile(
    r"^/v1\.0/me/drive/(?:root/children|items/[^/]{1,513}(?:/children)?)$"
)
_ITEM_ID = re.compile(r"^[A-Za-z0-9!._=+\-]{1,512}$")
_CONSTRUCTION_KEY = object()


class GraphDriveV1Error(RuntimeError):
    pass


class GraphDriveV1ContractError(ValueError):
    pass


class GraphDriveV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class GraphDriveFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GraphDriveV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GraphDriveFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class DriveItemV1:
    item_id: str
    name: str
    size: int
    is_folder: bool
    child_count: int
    last_modified: str
    web_url: str


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_TASKS_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GraphDriveV1Denied("accepted Tasks V1 evidence unavailable") from exc
        if not hmac.compare_digest(actual, expected):
            raise GraphDriveV1Denied("accepted Tasks V1 evidence drift")


def _text(value: object, maximum: int) -> str:
    if value is None:
        return ""
    if type(value) is not str or len(value) > maximum or "\x00" in value:
        raise GraphDriveV1Denied("provider text contract drift")
    return value


def _required_text(value: object, maximum: int) -> str:
    text = _text(value, maximum)
    if not text:
        raise GraphDriveV1Denied("drive item identity drift")
    return text


def _utc(value: object) -> str:
    text = _text(value, 80)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GraphDriveV1Denied("provider timestamp drift") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _item(raw: dict[str, object]) -> DriveItemV1:
    if type(raw) is not dict:
        raise GraphDriveV1Denied("drive item drift")
    folder = raw.get("folder")
    file = raw.get("file")
    is_folder = folder is not None
    if is_folder and type(folder) is not dict:
        raise GraphDriveV1Denied("drive folder facet drift")
    if file is not None and type(file) is not dict:
        raise GraphDriveV1Denied("drive file facet drift")
    if is_folder and file is not None:
        raise GraphDriveV1Denied("drive facet conflict")
    child_count = 0
    if is_folder:
        raw_count = folder.get("childCount", 0)
        if type(raw_count) is not int or raw_count < 0 or raw_count > 1_000_000:
            raise GraphDriveV1Denied("drive childCount drift")
        child_count = raw_count
    size = raw.get("size", 0)
    if type(size) is not int or size < 0:
        raise GraphDriveV1Denied("drive size drift")
    return DriveItemV1(
        _required_text(raw.get("id"), 513),
        _required_text(raw.get("name"), 512),
        size,
        is_folder,
        child_count,
        _utc(raw.get("lastModifiedDateTime")),
        _text(raw.get("webUrl"), 2_048),
    )


class GraphDriveHttpV1(Protocol):
    def post_form(
        self, *, url: str, fields: tuple[tuple[str, str], ...], timeout_seconds: int
    ) -> JsonHttpResponseV1: ...

    def get_json(
        self,
        *,
        url: str,
        query: tuple[tuple[str, str], ...],
        headers: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> JsonHttpResponseV1: ...


def _strict_json(data: bytes) -> dict[str, object]:
    if type(data) is not bytes or len(data) > MAX_HTTP_BYTES:
        raise GraphDriveV1Denied("HTTP payload size is invalid")

    def pairs(values: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in values:
            if key in result:
                raise GraphDriveV1Denied("duplicate JSON key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GraphDriveV1Denied("HTTP JSON is invalid") from exc
    if type(value) is not dict:
        raise GraphDriveV1Denied("HTTP JSON object required")
    return value


def _headers(value: object) -> tuple[tuple[str, str], ...]:
    items = getattr(value, "items", None)
    if not callable(items):
        return ()
    return tuple(
        (name, item)
        for name, item in items()
        if type(name) is str and type(item) is str
    )


class StdlibGraphDriveHttpV1:
    """Route-pinned HTTPS client: identity POST, drive GET only."""

    __slots__ = ("_opener",)

    def __init__(self) -> None:
        context = ssl.create_default_context()

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        self._opener = urllib.request.build_opener(
            _NoRedirect(), urllib.request.HTTPSHandler(context=context)
        )

    def _open(self, request: urllib.request.Request) -> JsonHttpResponseV1:
        try:
            with self._opener.open(
                request, timeout=HTTP_TIMEOUT_SECONDS
            ) as response:
                data = response.read(MAX_HTTP_BYTES + 1)
                if len(data) > MAX_HTTP_BYTES:
                    raise GraphDriveV1Denied("HTTP response exceeded size limit")
                return JsonHttpResponseV1(
                    int(response.status), _strict_json(data), _headers(response.headers)
                )
        except urllib.error.HTTPError as exc:
            data = exc.read(MAX_HTTP_BYTES + 1)
            if len(data) > MAX_HTTP_BYTES:
                raise GraphDriveV1Denied("HTTP error exceeded size limit") from exc
            return JsonHttpResponseV1(int(exc.code), _strict_json(data), _headers(exc.headers))
        except GraphDriveV1Denied:
            raise
        except (OSError, urllib.error.URLError) as exc:
            raise GraphDriveV1Error("Microsoft HTTPS request failed") from exc

    def post_form(self, *, url, fields, timeout_seconds):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "login.microsoftonline.com"
            or not _TOKEN_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphDriveV1Denied("identity POST route is invalid")
        # URL is pinned above to HTTPS and the exact Microsoft identity route.
        request = urllib.request.Request(  # noqa: S310
            url,
            data=urllib.parse.urlencode(fields).encode("ascii"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "CyryxLabs-Onyx/1",
            },
            method="POST",
        )
        return self._open(request)

    def get_json(self, *, url, query, headers, timeout_seconds):
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or not _DRIVE_PATH.fullmatch(parsed.path)
            or parsed.query
            or parsed.fragment
            or timeout_seconds != HTTP_TIMEOUT_SECONDS
        ):
            raise GraphDriveV1Denied("Graph drive route is invalid")
        encoded = urllib.parse.urlencode(query)
        target = f"{url}?{encoded}" if encoded else url
        outbound = {"Accept": "application/json", "User-Agent": "CyryxLabs-Onyx/1"}
        for name, value in headers:
            outbound[name] = value
        # Base URL is pinned above; the query is encoded from structured pairs.
        request = urllib.request.Request(  # noqa: S310
            target, headers=outbound, method="GET"
        )
        return self._open(request)


class MicrosoftGraphDriveReadSessionV1:
    """Read-only OneDrive session: Files.Read token + route-pinned listing."""

    __slots__ = (
        "_access_expires_at",
        "_access_token",
        "_clock_epoch_s",
        "_http",
        "_onboarding",
        "_vault",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        onboarding: MicrosoftGraphLiveOnboardingV1,
        http: GraphDriveHttpV1,
        vault: RefreshTokenVaultV1,
        clock_epoch_s: Callable[[], int],
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GraphDriveV1ContractError("use create_microsoft_graph_drive_v1")
        self._onboarding = onboarding
        self._http = http
        self._vault = vault
        self._clock_epoch_s = clock_epoch_s
        self._access_token: str | None = None
        self._access_expires_at: int | None = None

    def _token_url(self) -> str:
        tenant = urllib.parse.quote(self._onboarding.tenant_id, safe="")
        return f"{IDENTITY_ORIGIN}/{tenant}/oauth2/v2.0/token"

    def _read_token(self) -> str:
        now = self._clock_epoch_s()
        if type(now) is not int:
            raise GraphDriveV1ContractError("clock result is invalid")
        if (
            self._access_token is not None
            and self._access_expires_at is not None
            and now + ACCESS_EXPIRY_SKEW < self._access_expires_at
        ):
            return self._access_token
        refresh = self._vault.get_refresh_token()
        if refresh is None:
            raise GraphDriveV1Denied("Microsoft sign-in is required")
        response = self._http.post_form(
            url=self._token_url(),
            fields=(
                ("client_id", self._onboarding.client_id),
                ("grant_type", "refresh_token"),
                ("refresh_token", refresh),
                ("scope", " ".join(sorted(READ_SCOPES, key=str.casefold))),
            ),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphDriveV1Error("Microsoft read-scope refresh failed")
        token_type = _text(response.payload.get("token_type"), 30)
        access = _text(response.payload.get("access_token"), 16_384)
        scope_text = _text(response.payload.get("scope"), 2_000)
        expires_in = response.payload.get("expires_in")
        if type(expires_in) is not int or not 60 <= expires_in <= 86_400:
            raise GraphDriveV1Denied("access expiry contract drift")
        granted = frozenset(scope_text.split())
        if token_type.casefold() != "bearer" or "Files.Read" not in granted:
            raise GraphDriveV1Denied("files read scope was not granted")
        rotated = response.payload.get("refresh_token")
        if type(rotated) is str and rotated:
            try:
                self._vault.set_refresh_token(rotated)
            except (PermissionError, ValueError):
                pass
        self._access_token = access
        self._access_expires_at = now + expires_in
        return access

    def _safe_next_link(
        self, value: object, expected_path: str
    ) -> tuple[str, tuple[tuple[str, str], ...]] | None:
        if value is None:
            return None
        if type(value) is not str:
            raise GraphDriveV1Denied("nextLink contract drift")
        parsed = urlparse(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "graph.microsoft.com"
            or parsed.path != expected_path
            or parsed.fragment
        ):
            raise GraphDriveV1Denied("cross-route nextLink denied")
        query = tuple(parse_qsl(parsed.query, keep_blank_values=True))
        if len(query) > 20 or any(
            len(key) > 100 or len(item) > 4_096 for key, item in query
        ):
            raise GraphDriveV1Denied("nextLink query contract drift")
        return f"{GRAPH_ORIGIN}{parsed.path}", query

    def _list(self, path: str) -> tuple[DriveItemV1, ...]:
        access = self._read_token()
        url = f"{GRAPH_ORIGIN}{path}"
        expected_path = urlparse(url).path
        query: tuple[tuple[str, str], ...] = (("$select", _SELECT), ("$top", "100"))
        headers = (("Authorization", f"Bearer {access}"),)
        items: list[DriveItemV1] = []
        for _page in range(MAX_PAGES):
            response = self._http.get_json(
                url=url, query=query, headers=headers, timeout_seconds=HTTP_TIMEOUT_SECONDS
            )
            if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
                raise GraphDriveV1Error("Microsoft drive read failed")
            value = response.payload.get("value")
            if type(value) is not list:
                raise GraphDriveV1Denied("drive collection drift")
            for raw in value:
                items.append(_item(raw))
                if len(items) >= MAX_ITEMS:
                    return tuple(items)
            next_page = self._safe_next_link(
                response.payload.get("@odata.nextLink"), expected_path
            )
            if next_page is None:
                break
            url, query = next_page
        return tuple(items)

    def list_root(self) -> tuple[DriveItemV1, ...]:
        return self._list("/v1.0/me/drive/root/children")

    def list_children(self, *, item_id: str) -> tuple[DriveItemV1, ...]:
        if type(item_id) is not str or not _ITEM_ID.fullmatch(item_id):
            raise GraphDriveV1ContractError("drive item id is invalid")
        return self._list(f"/v1.0/me/drive/items/{item_id}/children")

    def get_item(self, *, item_id: str) -> DriveItemV1:
        if type(item_id) is not str or not _ITEM_ID.fullmatch(item_id):
            raise GraphDriveV1ContractError("drive item id is invalid")
        access = self._read_token()
        response = self._http.get_json(
            url=f"{GRAPH_ORIGIN}/v1.0/me/drive/items/{item_id}",
            query=(("$select", _SELECT),),
            headers=(("Authorization", f"Bearer {access}"),),
            timeout_seconds=HTTP_TIMEOUT_SECONDS,
        )
        if type(response) is not JsonHttpResponseV1 or response.status_code != 200:
            raise GraphDriveV1Error("Microsoft drive read failed")
        if "value" in response.payload or "@odata.nextLink" in response.payload:
            raise GraphDriveV1Denied("drive item object drift")
        return _item(response.payload)


def create_microsoft_graph_drive_v1(
    *,
    gate: GraphDriveFeatureGateV1 | None = None,
    onboarding: MicrosoftGraphLiveOnboardingV1 | None = None,
    http: GraphDriveHttpV1 | None = None,
    vault: RefreshTokenVaultV1 | None = None,
    clock_epoch_s: Callable[[], int] | None = None,
    project_root: Path | str | None = None,
) -> MicrosoftGraphDriveReadSessionV1 | None:
    selected = GraphDriveFeatureGateV1.from_environ() if gate is None else gate
    if type(selected) is not GraphDriveFeatureGateV1:
        raise GraphDriveV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    _verify_entry(
        Path(__file__).resolve().parents[1] if project_root is None else project_root
    )
    chosen = (
        MicrosoftGraphLiveOnboardingV1.from_environ()
        if onboarding is None
        else onboarding
    )
    if type(chosen) is not MicrosoftGraphLiveOnboardingV1:
        raise GraphDriveV1ContractError("exact onboarding identity required")
    if vault is None or clock_epoch_s is None:
        raise GraphDriveV1ContractError("enabled session requires complete bindings")
    if not callable(clock_epoch_s):
        raise GraphDriveV1ContractError("exact clock is required")
    selected_http = StdlibGraphDriveHttpV1() if http is None else http
    if (
        not hasattr(selected_http, "post_form")
        or not hasattr(selected_http, "get_json")
        or not hasattr(vault, "get_refresh_token")
    ):
        raise GraphDriveV1ContractError("drive transport or vault is invalid")
    return MicrosoftGraphDriveReadSessionV1(
        construction_key=_CONSTRUCTION_KEY,
        onboarding=chosen,
        http=selected_http,
        vault=vault,
        clock_epoch_s=clock_epoch_s,
    )


__all__ = [
    "ACCEPTED_TASKS_ROOTS",
    "DriveItemV1",
    "FEATURE_FLAG",
    "GraphDriveFeatureGateV1",
    "GraphDriveV1ContractError",
    "GraphDriveV1Denied",
    "GraphDriveV1Error",
    "MicrosoftGraphDriveReadSessionV1",
    "READ_SCOPES",
    "StdlibGraphDriveHttpV1",
    "create_microsoft_graph_drive_v1",
]
