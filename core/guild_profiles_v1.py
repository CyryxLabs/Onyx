"""Default-off guild role-profile registry and authority matrix (Guild A9.1).

First Onyx Engineering Guild slice. It turns the first-party AEXOS agent
definitions (Cyryx Labs, `aexos-engine`) into a governed, versioned registry of
role profiles (architect, dev, qa, devops, sm, pm, po, ...) with an enforceable
authority matrix, so later guild slices can orchestrate autonomous development
under the same exclusive-authority discipline that governs AEXOS sessions. It
calls no model, opens no network, spawns no process, persists nothing and takes
no action.

Governance is structural, not advisory:

* **Constitutional floor.** The AEXOS Constitution v1.1.0 Article II
  exclusivities are a mandatory constant: `git_push`, `pr_creation` and
  `release_tag` belong to `devops`; `story_creation` to `po`/`sm`;
  `architecture_decisions` to `architect`; `quality_verdicts` to `qa`. A profile
  pack that omits, reassigns or dilutes any of them is rejected.
* **One-claim exclusivity.** An operation claimed exclusively is owned by
  exactly that claimant set; any other profile merely listing it among its
  allowed operations is rejected — authority cannot leak.
* **Closed delegation graph.** Every delegation names an existing role that
  itself holds the delegated operation; self-delegation is rejected.
* **Byte-pinned provenance.** Every profile and team pack carries the exact
  SHA-256 of its AEXOS source bytes; supplied bytes that do not match are
  rejected, and the registry seals a deterministic pack root over all sources.
* **No orchestration authority.** Profiles describe and the registry validates;
  there is no method that runs, schedules or hands work to anything. Sessions,
  grants, budgets and decommission are later guild slices, each separately
  gated.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

FEATURE_FLAG: Final = "ONYX_GUILD_PROFILES_V1"
ENABLED_VALUE: Final = "true"
MAX_ITEMS: Final = 2_000
MAX_ID_BYTES: Final = 256
MAX_TEXT_BYTES: Final = 20_000
MAX_SOURCE_BYTES: Final = 1_000_000
CONSTITUTION_VERSION: Final = "1.1.0"
_OPERATION_RE: Final = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_CONSTRUCTION_KEY = object()

# AEXOS Constitution v1.1.0, Article II ("Agent Authority", NON-NEGOTIABLE).
# Owner tuples are sorted; a pack must reproduce these claims exactly.
MANDATORY_CONSTITUTIONAL_EXCLUSIVES: Final = (
    ("git_push", ("devops",)),
    ("pr_creation", ("devops",)),
    ("release_tag", ("devops",)),
    ("story_creation", ("po", "sm")),
    ("architecture_decisions", ("architect",)),
    ("quality_verdicts", ("qa",)),
)

# The accepted Phase 10 content-draft four-file acceptance tuple. Building a
# guild registry is denied unless this frozen predecessor evidence is byte-exact.
ACCEPTED_CONTENT_DRAFT_ROOTS: Final = (
    (
        "docs/onyx/checkpoints/phase10-content-draft-v1/manifest.json",
        "f57046e1f65de10484b8ef31c706323683fd57952076d164dd0395150fdba8ff",
    ),
    (
        "docs/onyx/acceptance/VE-P10-CONTENT-DRAFT-V1-E6-001.md",
        "94f0964876f8c4a094ec8a3152501a87f20ddd8c1e08545eee591d92c822ad13",
    ),
    (
        "docs/onyx/acceptance/VE-P10-CONTENT-DRAFT-V1-E6-001.manifest.json",
        "8af9f47156ccd9ad8de232a105a40b6a32d9a42a85852d48de29c805fa5d850f",
    ),
    (
        "docs/onyx/VE-ACCEPTANCE-P10-CONTENT-DRAFT-V1-E6-001.sha256",
        "cee917429abc1c5463a839411973307b6cf381a6e2003256a309ae5360e8a221",
    ),
)


class GuildProfilesV1Error(RuntimeError):
    pass


class GuildProfilesV1ContractError(ValueError):
    pass


class GuildProfilesV1Denied(PermissionError):
    pass


def _text(value: object, maximum: int, *, field_name: str) -> str:
    if type(value) is not str or not value or "\x00" in value:
        raise GuildProfilesV1ContractError(f"{field_name} contract violation")
    if len(value.encode("utf-8")) > maximum:
        raise GuildProfilesV1ContractError(f"{field_name} contract violation")
    return value


def _operation(value: object, *, field_name: str) -> str:
    if type(value) is not str or _OPERATION_RE.fullmatch(value) is None:
        raise GuildProfilesV1ContractError(f"{field_name} operation grammar violation")
    return value


def _sha256_hex(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise GuildProfilesV1ContractError(f"{field_name} must be lowercase sha256 hex")
    return value


def _sequence(value: object, *, field_name: str) -> tuple[object, ...]:
    if type(value) not in (list, tuple):
        raise GuildProfilesV1ContractError(f"{field_name} must be a sequence")
    if len(value) > MAX_ITEMS:
        raise GuildProfilesV1ContractError(f"{field_name} exceeds item cap")
    return tuple(value)


def _pinned_source(raw_sha: object, raw_bytes: object, *, field_name: str) -> str:
    declared = _sha256_hex(raw_sha, field_name=f"{field_name} sha256")
    if type(raw_bytes) is not bytes or not raw_bytes:
        raise GuildProfilesV1ContractError(f"{field_name} bytes contract violation")
    if len(raw_bytes) > MAX_SOURCE_BYTES:
        raise GuildProfilesV1ContractError(f"{field_name} bytes contract violation")
    actual = hashlib.sha256(raw_bytes).hexdigest()
    if not hmac.compare_digest(actual, declared):
        raise GuildProfilesV1ContractError(f"{field_name} source bytes drift")
    return declared


@dataclass(frozen=True, slots=True)
class GuildProfilesFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise GuildProfilesV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "GuildProfilesFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class RoleProfileV1:
    role_id: str
    persona_name: str
    title: str
    scope: str
    allowed_operations: tuple[str, ...]
    exclusive_operations: tuple[str, ...]
    delegation_targets: tuple[tuple[str, str], ...]
    quality_gates: tuple[str, ...]
    source_ref: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class TeamPackV1:
    pack_id: str
    name: str
    member_role_ids: tuple[str, ...]
    workflow_refs: tuple[str, ...]
    source_ref: str
    source_sha256: str


@dataclass(frozen=True, slots=True)
class AuthorityMatrixV1:
    exclusive_owners: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True, slots=True)
class GuildRegistrySnapshotV1:
    constitution_version: str
    profiles: tuple[RoleProfileV1, ...]
    team_packs: tuple[TeamPackV1, ...]
    matrix: AuthorityMatrixV1
    pack_root_sha256: str


def _verify_entry(project_root: Path | str) -> None:
    root = Path(project_root).resolve()
    for relative, expected in ACCEPTED_CONTENT_DRAFT_ROOTS:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            raise GuildProfilesV1Denied(
                "accepted content-draft evidence unavailable"
            ) from exc
        if not hmac.compare_digest(actual, expected):
            raise GuildProfilesV1Denied("accepted content-draft evidence drift")


class GuildRegistryV1:
    """Deterministic, hermetic guild registry with an enforced authority matrix."""

    __slots__ = ("_profiles", "_packs", "_exclusive_owners")

    def __init__(self, *, construction_key: object) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise GuildProfilesV1ContractError("use create_guild_registry_v1")
        self._profiles: dict[str, RoleProfileV1] = {}
        self._packs: dict[str, TeamPackV1] = {}
        self._exclusive_owners: dict[str, tuple[str, ...]] = {}

    def _load_profile(self, raw: object) -> RoleProfileV1:
        if type(raw) is not dict or set(raw) != {
            "role_id",
            "persona_name",
            "title",
            "scope",
            "allowed_operations",
            "exclusive_operations",
            "delegation_targets",
            "quality_gates",
            "source_ref",
            "source_sha256",
            "source_bytes",
        }:
            raise GuildProfilesV1ContractError("profile keys contract violation")
        allowed: list[str] = []
        for item in _sequence(raw["allowed_operations"], field_name="allowed_operations"):
            operation = _operation(item, field_name="allowed_operations")
            if operation in allowed:
                raise GuildProfilesV1ContractError("duplicate allowed operation")
            allowed.append(operation)
        exclusive: list[str] = []
        for item in _sequence(
            raw["exclusive_operations"], field_name="exclusive_operations"
        ):
            operation = _operation(item, field_name="exclusive_operations")
            if operation in exclusive:
                raise GuildProfilesV1ContractError("duplicate exclusive operation")
            if operation not in allowed:
                raise GuildProfilesV1ContractError(
                    "exclusive operation missing from allowed operations"
                )
            exclusive.append(operation)
        delegations: list[tuple[str, str]] = []
        seen_delegated: set[str] = set()
        for item in _sequence(raw["delegation_targets"], field_name="delegation_targets"):
            if type(item) is not dict or set(item) != {"operation", "target_role_id"}:
                raise GuildProfilesV1ContractError("delegation keys contract violation")
            operation = _operation(item["operation"], field_name="delegation operation")
            if operation in seen_delegated:
                raise GuildProfilesV1ContractError("duplicate delegation operation")
            seen_delegated.add(operation)
            delegations.append(
                (
                    operation,
                    _text(
                        item["target_role_id"], MAX_ID_BYTES, field_name="target_role_id"
                    ),
                )
            )
        gates: list[str] = []
        for item in _sequence(raw["quality_gates"], field_name="quality_gates"):
            gate = _text(item, MAX_ID_BYTES, field_name="quality_gates")
            if gate in gates:
                raise GuildProfilesV1ContractError("duplicate quality gate")
            gates.append(gate)
        return RoleProfileV1(
            role_id=_text(raw["role_id"], MAX_ID_BYTES, field_name="role_id"),
            persona_name=_text(
                raw["persona_name"], MAX_ID_BYTES, field_name="persona_name"
            ),
            title=_text(raw["title"], MAX_ID_BYTES, field_name="title"),
            scope=_text(raw["scope"], MAX_TEXT_BYTES, field_name="scope"),
            allowed_operations=tuple(allowed),
            exclusive_operations=tuple(exclusive),
            delegation_targets=tuple(delegations),
            quality_gates=tuple(gates),
            source_ref=_text(raw["source_ref"], MAX_ID_BYTES, field_name="source_ref"),
            source_sha256=_pinned_source(
                raw["source_sha256"], raw["source_bytes"], field_name="profile"
            ),
        )

    def _load_pack(self, raw: object) -> TeamPackV1:
        if type(raw) is not dict or set(raw) != {
            "pack_id",
            "name",
            "member_role_ids",
            "workflow_refs",
            "source_ref",
            "source_sha256",
            "source_bytes",
        }:
            raise GuildProfilesV1ContractError("team pack keys contract violation")
        members: list[str] = []
        for item in _sequence(raw["member_role_ids"], field_name="member_role_ids"):
            member = _text(item, MAX_ID_BYTES, field_name="member_role_ids")
            if member in members:
                raise GuildProfilesV1ContractError("duplicate team pack member")
            members.append(member)
        if not members:
            raise GuildProfilesV1ContractError("team pack has no members")
        workflows: list[str] = []
        for item in _sequence(raw["workflow_refs"], field_name="workflow_refs"):
            workflow = _text(item, MAX_ID_BYTES, field_name="workflow_refs")
            if workflow in workflows:
                raise GuildProfilesV1ContractError("duplicate workflow ref")
            workflows.append(workflow)
        return TeamPackV1(
            pack_id=_text(raw["pack_id"], MAX_ID_BYTES, field_name="pack_id"),
            name=_text(raw["name"], MAX_ID_BYTES, field_name="name"),
            member_role_ids=tuple(members),
            workflow_refs=tuple(workflows),
            source_ref=_text(raw["source_ref"], MAX_ID_BYTES, field_name="source_ref"),
            source_sha256=_pinned_source(
                raw["source_sha256"], raw["source_bytes"], field_name="team pack"
            ),
        )

    def build(self, plan: object) -> GuildRegistrySnapshotV1:
        if type(plan) is not dict or set(plan) != {
            "constitution_version",
            "profiles",
            "team_packs",
        }:
            raise GuildProfilesV1ContractError("plan keys contract violation")
        version = _text(
            plan["constitution_version"], MAX_ID_BYTES, field_name="constitution_version"
        )
        if version != CONSTITUTION_VERSION:
            raise GuildProfilesV1ContractError("constitution version drift")

        seen_sources: set[str] = set()
        for raw in _sequence(plan["profiles"], field_name="profiles"):
            profile = self._load_profile(raw)
            if profile.role_id in self._profiles:
                raise GuildProfilesV1ContractError("duplicate role_id")
            if profile.source_ref in seen_sources:
                raise GuildProfilesV1ContractError("duplicate source_ref")
            seen_sources.add(profile.source_ref)
            self._profiles[profile.role_id] = profile

        for raw in _sequence(plan["team_packs"], field_name="team_packs"):
            pack = self._load_pack(raw)
            if pack.pack_id in self._packs:
                raise GuildProfilesV1ContractError("duplicate pack_id")
            if pack.source_ref in seen_sources:
                raise GuildProfilesV1ContractError("duplicate source_ref")
            seen_sources.add(pack.source_ref)
            for member in pack.member_role_ids:
                if member not in self._profiles:
                    raise GuildProfilesV1ContractError(
                        "team pack references unknown role"
                    )
            self._packs[pack.pack_id] = pack

        # Closed delegation graph: target exists, is not the delegator, and
        # itself holds the delegated operation.
        for profile in self._profiles.values():
            for operation, target in profile.delegation_targets:
                if target == profile.role_id:
                    raise GuildProfilesV1ContractError("self-delegation is rejected")
                owner = self._profiles.get(target)
                if owner is None:
                    raise GuildProfilesV1ContractError(
                        "delegation references unknown role"
                    )
                if operation not in owner.allowed_operations:
                    raise GuildProfilesV1ContractError(
                        "delegation target does not hold the operation"
                    )

        # One-claim exclusivity: claimants form the owner set; any non-owner
        # merely listing the operation as allowed is an authority leak.
        claims: dict[str, list[str]] = {}
        for profile in self._profiles.values():
            for operation in profile.exclusive_operations:
                claims.setdefault(operation, []).append(profile.role_id)
        for operation, claimants in claims.items():
            owners = tuple(sorted(claimants))
            for profile in self._profiles.values():
                if (
                    profile.role_id not in owners
                    and operation in profile.allowed_operations
                ):
                    raise GuildProfilesV1ContractError(
                        "exclusive operation leaked to non-owner"
                    )
            self._exclusive_owners[operation] = owners

        # Constitutional floor: Article II claims must be reproduced exactly.
        for operation, owners in MANDATORY_CONSTITUTIONAL_EXCLUSIVES:
            for owner in owners:
                if owner not in self._profiles:
                    raise GuildProfilesV1ContractError(
                        "constitutional owner role is missing"
                    )
            if self._exclusive_owners.get(operation) != owners:
                raise GuildProfilesV1ContractError(
                    "constitutional exclusivity violation"
                )

        pack_root = hashlib.sha256(
            "".join(
                sorted(
                    f"{item.source_ref}\0{item.source_sha256}\n"
                    for item in (*self._profiles.values(), *self._packs.values())
                )
            ).encode()
        ).hexdigest()

        return GuildRegistrySnapshotV1(
            constitution_version=version,
            profiles=tuple(self._profiles[key] for key in sorted(self._profiles)),
            team_packs=tuple(self._packs[key] for key in sorted(self._packs)),
            matrix=AuthorityMatrixV1(
                exclusive_owners=tuple(
                    (operation, self._exclusive_owners[operation])
                    for operation in sorted(self._exclusive_owners)
                )
            ),
            pack_root_sha256=pack_root,
        )

    def is_operation_permitted(self, role_id: str, operation: str) -> bool:
        # Pure projection: never grants anything. True only when the role exists,
        # lists the operation, and does not collide with an exclusive owner set.
        profile = self._profiles.get(role_id)
        if profile is None or operation not in profile.allowed_operations:
            return False
        owners = self._exclusive_owners.get(operation)
        return owners is None or role_id in owners

    def delegation_target(self, role_id: str, operation: str) -> str | None:
        profile = self._profiles.get(role_id)
        if profile is None:
            return None
        for delegated, target in profile.delegation_targets:
            if delegated == operation:
                return target
        return None


def create_guild_registry_v1(project_root: Path | str) -> GuildRegistryV1:
    _verify_entry(project_root)
    return GuildRegistryV1(construction_key=_CONSTRUCTION_KEY)


__all__ = [
    "FEATURE_FLAG",
    "ENABLED_VALUE",
    "CONSTITUTION_VERSION",
    "MANDATORY_CONSTITUTIONAL_EXCLUSIVES",
    "GuildProfilesFeatureGateV1",
    "RoleProfileV1",
    "TeamPackV1",
    "AuthorityMatrixV1",
    "GuildRegistrySnapshotV1",
    "GuildRegistryV1",
    "GuildProfilesV1Error",
    "GuildProfilesV1ContractError",
    "GuildProfilesV1Denied",
    "create_guild_registry_v1",
]
