"""Default-off brand passport and social account inventory for Phase 10.

This is the first Phase 10 (Social organic operating system) slice. It implements
the PRD inventory contract as a pure deterministic, hermetic registry over the
authorized brands (Cyryx Labs, MAAX Studio, Lyra and any other explicitly
authorized brand) and their declared social accounts. It calls no model, opens
no network, persists nothing and takes no action.

Governance is structural, not advisory:

* A brand passport carries always-on policy guards (no follower buying, no
  bots/automation-abuse, no fake personas, no competitor copying, no fabricated
  testimonials/stats/logos). A passport that omits any guard is rejected.
* Every social account belongs to exactly one brand; a ``(platform, handle)``
  pair can never be claimed by two brands, so the registry cannot be used to
  impersonate or leak one brand's identity into another.
* A passport/account NEVER grants publish authority. ``can_publish`` is
  structurally always ``False`` in V1 — the first real publish per account is a
  later owner-approved, access-gated slice (OAuth/app-review + test account),
  not something this inventory can unlock.

Live provider connectors, audience/trend research, content pipelines, publishing
and community replies are deliberately out of scope for later gated successors.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

FEATURE_FLAG: Final = "ONYX_PHASE10_BRAND_PASSPORT_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 1_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 4_000
_CONSTRUCTION_KEY = object()

# Recognised official platforms. Listing a platform here only means Onyx knows
# its name; a brand may still declare a narrower allow-list, and using an account
# additionally requires it to be authorised.
PLATFORMS: Final = frozenset(
    {"instagram", "youtube", "tiktok", "x", "linkedin", "facebook"}
)
ACCOUNT_TYPES: Final = frozenset({"brand", "test"})
# Always-on policy guards every brand passport must carry. These are invariants
# the registry asserts are present; they are never a runtime toggle.
REQUIRED_POLICY_GUARDS: Final = frozenset(
    {
        "no_follower_buying",
        "no_bots_or_automation_abuse",
        "no_fake_personas",
        "no_competitor_copying",
        "no_fabricated_testimonials_stats_logos",
    }
)

# The accepted Phase 9 exit four-file acceptance tuple. Constructing a registry
# is denied unless this frozen predecessor evidence is byte-exact on disk.
ACCEPTED_PHASE9_EXIT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase9-exit-candidate-v1/manifest.json",
        "c0e8105eceb011b5a0629df8d9ea5beb2588787833d6053cebee6f66bf66ee2d",
    ),
    (
        "docs/onyx/acceptance/VE-P9-EXIT-CANDIDATE-V1-E6-001.md",
        "d579582818877d2ba85824ae1b19b06b302ada9032e147e7de8f0efb5d304c31",
    ),
    (
        "docs/onyx/acceptance/VE-P9-EXIT-CANDIDATE-V1-E6-001.manifest.json",
        "7fe79fac2eec5f438e0d90d88e2a8a026aa715086e2fdbc75efda772d3bd174a",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P9-EXIT-CANDIDATE-V1-E6-001.sha256",
        "2024fc3768fa0e7b22e5ab78bdd05cf43822393513bde7d0998b164204fa88e2",
    ),
)


class BrandPassportV1Error(RuntimeError):
    pass


class BrandPassportV1ContractError(ValueError):
    pass


class BrandPassportV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class BrandPassportFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise BrandPassportV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "BrandPassportFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class BrandPassportV1:
    brand_id: str
    legal_name: str
    authorized: bool
    allowed_platforms: frozenset[str]
    disclosure_required: bool
    policy_guards: frozenset[str]


@dataclass(frozen=True, slots=True)
class SocialAccountV1:
    account_id: str
    brand_id: str
    platform: str
    handle: str
    account_type: str
    authorized: bool
    scopes: frozenset[str]

    @property
    def can_publish(self) -> bool:
        # Structural: inventory never grants publish authority in V1. A real
        # publish is a later owner-approved, access-gated slice.
        return False


@dataclass(frozen=True, slots=True)
class BrandInventoryV1:
    passports: tuple[BrandPassportV1, ...]
    accounts: tuple[SocialAccountV1, ...]


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_PHASE9_EXIT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise BrandPassportV1Denied(
                "accepted Phase 9 exit evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise BrandPassportV1Denied("accepted Phase 9 exit evidence drift")


def _text(value: object, maximum: int, *, field: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise BrandPassportV1ContractError(f"{field} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise BrandPassportV1ContractError(f"{field} contract violation")
    return value


def _bool(value: object, *, field: str) -> bool:
    if type(value) is not bool:
        raise BrandPassportV1ContractError(f"{field} must be exact bool")
    return value


def _str_set(value: object, allowed: frozenset[str] | None, *, field: str) -> frozenset[str]:
    if type(value) not in (list, tuple, set, frozenset):
        raise BrandPassportV1ContractError(f"{field} must be a collection")
    items: set[str] = set()
    for element in value:
        text = _text(element, MAX_ID_BYTES, field=field)
        if allowed is not None and text not in allowed:
            raise BrandPassportV1ContractError(f"{field} has an unknown value")
        items.add(text)
    return frozenset(items)


class BrandRegistryV1:
    """Deterministic, hermetic brand + social-account inventory."""

    __slots__ = ("_passports", "_accounts", "_by_handle")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise BrandPassportV1ContractError("use create_brand_registry_v1")
        self._passports: dict[str, BrandPassportV1] = {}
        self._accounts: dict[str, SocialAccountV1] = {}
        self._by_handle: dict[tuple[str, str], str] = {}

    def _load_passport(self, raw: object) -> BrandPassportV1:
        if type(raw) is not dict:
            raise BrandPassportV1ContractError("passport must be a mapping")
        allowed_keys = {
            "brand_id",
            "legal_name",
            "authorized",
            "allowed_platforms",
            "disclosure_required",
            "policy_guards",
        }
        if set(raw) != allowed_keys:
            raise BrandPassportV1ContractError("passport keys contract violation")
        brand_id = _text(raw["brand_id"], MAX_ID_BYTES, field="brand_id")
        guards = _str_set(
            raw["policy_guards"], REQUIRED_POLICY_GUARDS, field="policy_guards"
        )
        if guards != REQUIRED_POLICY_GUARDS:
            raise BrandPassportV1ContractError(
                "passport must carry every always-on policy guard"
            )
        return BrandPassportV1(
            brand_id=brand_id,
            legal_name=_text(raw["legal_name"], MAX_TEXT_BYTES, field="legal_name"),
            authorized=_bool(raw["authorized"], field="authorized"),
            allowed_platforms=_str_set(
                raw["allowed_platforms"], PLATFORMS, field="allowed_platforms"
            ),
            disclosure_required=_bool(
                raw["disclosure_required"], field="disclosure_required"
            ),
            policy_guards=guards,
        )

    def _load_account(self, raw: object) -> SocialAccountV1:
        if type(raw) is not dict:
            raise BrandPassportV1ContractError("account must be a mapping")
        allowed_keys = {
            "account_id",
            "brand_id",
            "platform",
            "handle",
            "account_type",
            "authorized",
            "scopes",
        }
        if set(raw) != allowed_keys:
            raise BrandPassportV1ContractError("account keys contract violation")
        platform = _text(raw["platform"], MAX_ID_BYTES, field="platform")
        if platform not in PLATFORMS:
            raise BrandPassportV1ContractError("account platform is unknown")
        account_type = _text(raw["account_type"], MAX_ID_BYTES, field="account_type")
        if account_type not in ACCOUNT_TYPES:
            raise BrandPassportV1ContractError("account_type is unknown")
        return SocialAccountV1(
            account_id=_text(raw["account_id"], MAX_ID_BYTES, field="account_id"),
            brand_id=_text(raw["brand_id"], MAX_ID_BYTES, field="brand_id"),
            platform=platform,
            handle=_text(raw["handle"], MAX_ID_BYTES, field="handle"),
            account_type=account_type,
            authorized=_bool(raw["authorized"], field="authorized"),
            scopes=_str_set(raw["scopes"], None, field="scopes"),
        )

    def build(self, inventory: object) -> BrandInventoryV1:
        if type(inventory) is not dict or set(inventory) != {"passports", "accounts"}:
            raise BrandPassportV1ContractError("inventory keys contract violation")
        passports_raw = inventory["passports"]
        accounts_raw = inventory["accounts"]
        if type(passports_raw) not in (list, tuple) or type(accounts_raw) not in (
            list,
            tuple,
        ):
            raise BrandPassportV1ContractError("inventory sections must be sequences")
        if len(passports_raw) > MAX_ITEMS or len(accounts_raw) > MAX_ITEMS:
            raise BrandPassportV1ContractError("inventory exceeds item cap")

        for raw in passports_raw:
            passport = self._load_passport(raw)
            if passport.brand_id in self._passports:
                raise BrandPassportV1ContractError("duplicate brand_id")
            self._passports[passport.brand_id] = passport

        for raw in accounts_raw:
            account = self._load_account(raw)
            if account.account_id in self._accounts:
                raise BrandPassportV1ContractError("duplicate account_id")
            passport = self._passports.get(account.brand_id)
            if passport is None:
                raise BrandPassportV1ContractError("account references unknown brand")
            if account.platform not in passport.allowed_platforms:
                raise BrandPassportV1ContractError(
                    "account platform outside the brand allow-list"
                )
            key = (account.platform, account.handle)
            if key in self._by_handle:
                # A (platform, handle) identifies exactly one real account, so it
                # can be claimed only once. This strictly enforces one-brand
                # separation (no impersonation/leakage across brands) and also
                # forbids a duplicate handle within a single brand.
                raise BrandPassportV1ContractError(
                    "platform handle already claimed"
                )
            self._by_handle[key] = account.brand_id
            self._accounts[account.account_id] = account

        return BrandInventoryV1(
            passports=tuple(
                self._passports[key] for key in sorted(self._passports)
            ),
            accounts=tuple(
                self._accounts[key] for key in sorted(self._accounts)
            ),
        )

    def passport(self, brand_id: str) -> BrandPassportV1 | None:
        return self._passports.get(brand_id)

    def accounts_for(self, brand_id: str) -> tuple[SocialAccountV1, ...]:
        return tuple(
            self._accounts[key]
            for key in sorted(self._accounts)
            if self._accounts[key].brand_id == brand_id
        )

    def resolve(self, platform: str, handle: str) -> str | None:
        return self._by_handle.get((platform, handle))

    def is_usable(self, account_id: str) -> bool:
        # An account is usable for future (gated) work only if it exists, its
        # brand exists and is authorised, and the account itself is authorised.
        # Usable never implies publish authority — see SocialAccountV1.can_publish.
        account = self._accounts.get(account_id)
        if account is None or not account.authorized:
            return False
        passport = self._passports.get(account.brand_id)
        return passport is not None and passport.authorized


def create_brand_registry_v1(project_root: Path | str) -> BrandRegistryV1:
    _verify_entry(project_root)
    return BrandRegistryV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "PLATFORMS",
    "ACCOUNT_TYPES",
    "REQUIRED_POLICY_GUARDS",
    "BrandPassportFeatureGateV1",
    "BrandPassportV1",
    "SocialAccountV1",
    "BrandInventoryV1",
    "BrandRegistryV1",
    "BrandPassportV1Error",
    "BrandPassportV1ContractError",
    "BrandPassportV1Denied",
    "create_brand_registry_v1",
]
