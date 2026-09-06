"""Read-only, source-grounded Company Graph projection for Phase 7."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from core.domain_ledger import (
    ClaimRecord,
    DomainLedgerRepository,
    EvidenceRecord,
)
from core.phase7_approved_sources_v1 import (
    ApprovedSourceRecordV1,
    ApprovedSourceRegistryV1,
    SENSITIVITIES,
    domain_material_sha256_v1,
)
from memory.store import contains_secret


FEATURE_FLAG: Final = "ONYX_PHASE7_COMPANY_GRAPH_V1"
ENABLED_VALUE: Final = "true"
SCHEMA: Final = "OnyxCompanyGraph.v1"
ASSERTION_SCHEMA: Final = "OnyxCompanyGraphAssertion.v1"
MAX_ASSERTIONS: Final = 2_000
MAX_EVIDENCE_PER_ASSERTION: Final = 32
MAX_BLOCKERS: Final = 32
SEMANTICS: Final = frozenset(
    {
        "approved_fact",
        "current_status",
        "dependency",
        "evidence",
        "hypothesis",
        "metric",
        "proposed_decision",
        "rejected_decision",
        "risk",
        "superseded_decision",
    }
)
STATUSES: Final = frozenset(
    {
        "blocked",
        "implemented",
        "in_progress",
        "proposed",
        "rejected",
        "superseded",
        "unknown",
        "verified_complete",
    }
)
_ENTITY_ID = re.compile(
    r"^m2a-(?:evidence|claim)-[0-9a-f]{64}$"
)
_SLUG = re.compile(r"^[a-z][a-z0-9-]{2,79}$")
_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.@:-]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_CONSTRUCTION_KEY = object()


class CompanyGraphV1Error(RuntimeError):
    """Base graph projection error."""


class CompanyGraphV1ContractError(ValueError):
    """Input violates the graph assertion contract."""


class CompanyGraphV1Denied(PermissionError):
    """Source, evidence, lifecycle, or scope policy denied projection."""


@dataclass(frozen=True, slots=True)
class CompanyGraphFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise CompanyGraphV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls,
        environ: dict[str, str] | os._Environ[str] | None = None,
    ) -> "CompanyGraphFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG) == ENABLED_VALUE)


@dataclass(frozen=True, slots=True)
class GraphEvidenceBindingV1:
    evidence_id: str
    source_name: str
    excerpt: str

    def __post_init__(self) -> None:
        if (
            type(self.evidence_id) is not str
            or not self.evidence_id.startswith("m2a-evidence-")
            or not _ENTITY_ID.fullmatch(self.evidence_id)
        ):
            raise CompanyGraphV1ContractError("evidence_id is invalid")
        _slug("source_name", self.source_name)
        _text("evidence excerpt", self.excerpt, 4_096)

    def payload(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "source_name": self.source_name,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True, slots=True)
class CompanyGraphAssertionV1:
    claim_id: str
    semantic: str
    project_id: str
    project_name: str
    subject_id: str
    subject_name: str
    owner: str
    status: str
    blockers: tuple[str, ...]
    next_milestone: str
    definition_of_done: str
    last_verified_ms: int
    evidence: tuple[GraphEvidenceBindingV1, ...]

    def __post_init__(self) -> None:
        if (
            type(self.claim_id) is not str
            or not self.claim_id.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(self.claim_id)
        ):
            raise CompanyGraphV1ContractError("claim_id is invalid")
        if self.semantic not in SEMANTICS:
            raise CompanyGraphV1ContractError("semantic is invalid")
        _slug("project_id", self.project_id)
        _text("project_name", self.project_name, 160)
        _slug("subject_id", self.subject_id)
        _text("subject_name", self.subject_name, 200)
        if type(self.owner) is not str or not _OWNER.fullmatch(self.owner):
            raise CompanyGraphV1ContractError("owner is invalid")
        _text("owner", self.owner, 128)
        if self.status not in STATUSES:
            raise CompanyGraphV1ContractError("status is invalid")
        if (
            type(self.blockers) is not tuple
            or len(self.blockers) > MAX_BLOCKERS
            or len(set(self.blockers)) != len(self.blockers)
        ):
            raise CompanyGraphV1ContractError("blockers are invalid")
        for blocker in self.blockers:
            _text("blocker", blocker, 400)
        _text("next_milestone", self.next_milestone, 500)
        _text("definition_of_done", self.definition_of_done, 1_000)
        if type(self.last_verified_ms) is not int or self.last_verified_ms < 0:
            raise CompanyGraphV1ContractError("last_verified_ms is invalid")
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or len(self.evidence) > MAX_EVIDENCE_PER_ASSERTION
            or any(type(item) is not GraphEvidenceBindingV1 for item in self.evidence)
            or tuple(sorted(self.evidence, key=lambda item: item.evidence_id))
            != self.evidence
            or len({item.evidence_id for item in self.evidence})
            != len(self.evidence)
        ):
            raise CompanyGraphV1ContractError(
                "evidence bindings must be nonempty, unique, and sorted"
            )
        if self.status == "blocked" and not self.blockers:
            raise CompanyGraphV1ContractError(
                "blocked status requires at least one blocker"
            )
        if self.status == "verified_complete" and self.blockers:
            raise CompanyGraphV1ContractError(
                "verified complete status cannot carry blockers"
            )
        if len(self.canonical_statement().encode("utf-8")) > 8_192:
            raise CompanyGraphV1ContractError(
                "canonical graph assertion exceeds ledger bound"
            )

    def statement_payload(self) -> dict[str, object]:
        return {
            "schema": ASSERTION_SCHEMA,
            "semantic": self.semantic,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "owner": self.owner,
            "status": self.status,
            "blockers": list(self.blockers),
            "next_milestone": self.next_milestone,
            "definition_of_done": self.definition_of_done,
            "last_verified_ms": self.last_verified_ms,
            "evidence": [item.payload() for item in self.evidence],
        }

    def canonical_statement(self) -> str:
        return _canonical(self.statement_payload()).decode("utf-8")


@dataclass(frozen=True, slots=True)
class CompanyGraphItemV1:
    claim_id: str
    semantic: str
    project_id: str
    project_name: str
    subject_id: str
    subject_name: str
    owner: str
    status: str
    blockers: tuple[str, ...]
    next_milestone: str
    definition_of_done: str
    last_verified_ms: int
    confidence_bp: int
    verification_status: str
    source_names: tuple[str, ...]
    citations: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    evidence_sha256: tuple[str, ...]
    authority_summary: tuple[str, ...]
    knowledge_class: str
    freshness: str
    content_trust: str

    def __post_init__(self) -> None:
        if (
            not _ENTITY_ID.fullmatch(self.claim_id)
            or not self.claim_id.startswith("m2a-claim-")
            or self.semantic not in SEMANTICS
            or self.status not in STATUSES
            or type(self.blockers) is not tuple
            or len(self.blockers) > MAX_BLOCKERS
            or len(set(self.blockers)) != len(self.blockers)
            or type(self.confidence_bp) is not int
            or not 0 <= self.confidence_bp <= 10_000
            or self.verification_status
            not in {"supported", "unverified", "unknown", "contradicted"}
            or type(self.source_names) is not tuple
            or not self.source_names
            or len(set(self.source_names)) != len(self.source_names)
            or type(self.citations) is not tuple
            or len(self.citations) != len(self.source_names)
            or type(self.evidence_ids) is not tuple
            or not self.evidence_ids
            or len(set(self.evidence_ids)) != len(self.evidence_ids)
            or any(
                not item.startswith("m2a-evidence-")
                or not _ENTITY_ID.fullmatch(item)
                for item in self.evidence_ids
            )
            or type(self.evidence_sha256) is not tuple
            or len(self.evidence_sha256) != len(self.evidence_ids)
            or any(not _HEX64.fullmatch(item) for item in self.evidence_sha256)
            or type(self.authority_summary) is not tuple
            or len(self.authority_summary) != len(self.source_names)
            or self.knowledge_class not in {"known", "inferred", "unknown"}
            or self.freshness != "fresh"
            or self.content_trust != "untrusted_data"
        ):
            raise CompanyGraphV1ContractError("graph item contract drift")
        _slug("project_id", self.project_id)
        _text("project_name", self.project_name, 160)
        _slug("subject_id", self.subject_id)
        _text("subject_name", self.subject_name, 200)
        if type(self.owner) is not str or not _OWNER.fullmatch(self.owner):
            raise CompanyGraphV1ContractError("graph item owner is invalid")
        for value in self.blockers:
            _text("blocker", value, 400)
        _text("next_milestone", self.next_milestone, 500)
        _text("definition_of_done", self.definition_of_done, 1_000)
        if type(self.last_verified_ms) is not int or self.last_verified_ms < 0:
            raise CompanyGraphV1ContractError(
                "graph item verification time is invalid"
            )


@dataclass(frozen=True, slots=True)
class CompanyGraphRelationV1:
    source_id: str
    relation: str
    target_id: str
    evidence_claim_id: str

    def __post_init__(self) -> None:
        if (
            self.relation
            not in {
                "about",
                "belongs_to",
                "contradicts",
                "from_source",
                "supersedes",
            }
            or type(self.source_id) is not str
            or type(self.target_id) is not str
            or type(self.evidence_claim_id) is not str
            or not self.source_id
            or not self.target_id
            or not self.evidence_claim_id.startswith("m2a-claim-")
            or not _ENTITY_ID.fullmatch(self.evidence_claim_id)
        ):
            raise CompanyGraphV1ContractError("graph relation is invalid")


@dataclass(frozen=True, slots=True)
class CompanyGraphProjectionV1:
    workspace_id: str
    principal_id: str
    generated_at_ms: int
    items: tuple[CompanyGraphItemV1, ...]
    relations: tuple[CompanyGraphRelationV1, ...]
    contradictions: tuple[tuple[str, str], ...]
    supersessions: tuple[tuple[str, str], ...]
    graph_sha256: str
    read_only: bool
    content_trust: str

    def __post_init__(self) -> None:
        if (
            type(self.workspace_id) is not str
            or not self.workspace_id
            or type(self.principal_id) is not str
            or not self.principal_id
            or type(self.generated_at_ms) is not int
            or self.generated_at_ms < 0
            or type(self.items) is not tuple
            or type(self.relations) is not tuple
            or type(self.contradictions) is not tuple
            or type(self.supersessions) is not tuple
            or any(type(item) is not CompanyGraphItemV1 for item in self.items)
            or tuple(sorted(self.items, key=lambda item: item.claim_id))
            != self.items
            or len({item.claim_id for item in self.items}) != len(self.items)
            or any(
                type(item) is not CompanyGraphRelationV1
                for item in self.relations
            )
            or len(set(self.relations)) != len(self.relations)
            or any(
                type(item) is not tuple
                or len(item) != 2
                or tuple(sorted(item)) != item
                for item in self.contradictions
            )
            or any(
                type(item) is not tuple or len(item) != 2
                for item in self.supersessions
            )
            or not _HEX64.fullmatch(self.graph_sha256)
            or self.read_only is not True
            or self.content_trust != "untrusted_data"
        ):
            raise CompanyGraphV1ContractError("graph projection contract drift")


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompanyGraphV1ContractError(
            "value is not canonical JSON"
        ) from exc


def _text(label: str, value: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value.encode("utf-8")) > maximum
        or any(ord(character) < 32 for character in value)
        or contains_secret(value)
    ):
        raise CompanyGraphV1ContractError(
            f"{label} contains unsafe or secret-like material"
        )
    return value


def _slug(label: str, value: str) -> str:
    _text(label, value, 80)
    if not _SLUG.fullmatch(value):
        raise CompanyGraphV1ContractError(f"{label} is invalid")
    return value


def _utc_ms(value: str, label: str) -> int:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CompanyGraphV1Denied(f"{label} timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CompanyGraphV1Denied(f"{label} timestamp lacks timezone")
    return int(parsed.astimezone(timezone.utc).timestamp() * 1_000)


def _expected_claim_kind(semantic: str) -> frozenset[str]:
    if semantic in {
        "approved_fact",
        "current_status",
        "evidence",
        "metric",
        "rejected_decision",
        "superseded_decision",
    }:
        return frozenset({"fact"})
    if semantic == "proposed_decision":
        return frozenset({"inference", "recommendation"})
    return frozenset({"inference", "unknown"})


def _knowledge_class(semantic: str, verification_status: str) -> str:
    if semantic in {
        "hypothesis",
        "proposed_decision",
        "risk",
        "dependency",
    }:
        return "inferred"
    if verification_status == "supported":
        return "known"
    return "unknown"


def _projection_sha256(
    *,
    workspace_id: str,
    principal_id: str,
    generated_at_ms: int,
    items: tuple[CompanyGraphItemV1, ...],
    relations: tuple[CompanyGraphRelationV1, ...],
    contradictions: tuple[tuple[str, str], ...],
    supersessions: tuple[tuple[str, str], ...],
) -> str:
    payload = {
        "schema": SCHEMA,
        "workspace_id": workspace_id,
        "principal_id": principal_id,
        "generated_at_ms": generated_at_ms,
        "read_only": True,
        "content_trust": "untrusted_data",
        "items": [
            {
                "claim_id": item.claim_id,
                "semantic": item.semantic,
                "project_id": item.project_id,
                "project_name": item.project_name,
                "subject_id": item.subject_id,
                "subject_name": item.subject_name,
                "owner": item.owner,
                "status": item.status,
                "blockers": list(item.blockers),
                "next_milestone": item.next_milestone,
                "definition_of_done": item.definition_of_done,
                "last_verified_ms": item.last_verified_ms,
                "confidence_bp": item.confidence_bp,
                "verification_status": item.verification_status,
                "source_names": list(item.source_names),
                "citations": list(item.citations),
                "evidence_ids": list(item.evidence_ids),
                "evidence_sha256": list(item.evidence_sha256),
                "authority_summary": list(item.authority_summary),
                "knowledge_class": item.knowledge_class,
                "freshness": item.freshness,
                "content_trust": item.content_trust,
            }
            for item in items
        ],
        "relations": [
            {
                "source_id": item.source_id,
                "relation": item.relation,
                "target_id": item.target_id,
                "evidence_claim_id": item.evidence_claim_id,
            }
            for item in relations
        ],
        "contradictions": [list(item) for item in contradictions],
        "supersessions": [list(item) for item in supersessions],
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


class CompanyGraphProjectorV1:
    """Read-only graph projector over accepted source and domain ledgers."""

    __slots__ = (
        "_sources",
        "_ledger",
        "_workspace_id",
        "_principal_id",
        "_connection_id",
        "_control_path",
    )

    def __init__(
        self,
        *,
        construction_key: object,
        sources: ApprovedSourceRegistryV1,
        ledger: DomainLedgerRepository,
    ) -> None:
        if construction_key is not _CONSTRUCTION_KEY:
            raise CompanyGraphV1ContractError(
                "use create_company_graph_projector_v1"
            )
        if (
            type(sources) is not ApprovedSourceRegistryV1
            or type(ledger) is not DomainLedgerRepository
        ):
            raise CompanyGraphV1ContractError(
                "exact source registry and domain ledger required"
            )
        if (
            ledger.enabled is not True
            or ledger.workspace_id != sources.workspace_id
            or ledger.registry is not sources.registry
        ):
            raise CompanyGraphV1Denied("domain ledger binding denied")
        ledger.verify_integrity()
        connection = sources.registry.store._require_connection()
        self._sources = sources
        self._ledger = ledger
        self._workspace_id = sources.workspace_id
        self._principal_id = sources.principal_id
        self._connection_id = id(connection)
        self._control_path = sources.registry.store.path.absolute()

    def __init_subclass__(cls, **_kwargs: object) -> None:
        raise TypeError("CompanyGraphProjectorV1 cannot be subclassed")

    def __copy__(self) -> object:
        raise TypeError("CompanyGraphProjectorV1 cannot be copied")

    def __deepcopy__(self, _memo: object) -> object:
        raise TypeError("CompanyGraphProjectorV1 cannot be copied")

    def __reduce__(self) -> object:
        raise TypeError("CompanyGraphProjectorV1 cannot be serialized")

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    @property
    def principal_id(self) -> str:
        return self._principal_id

    def _attest(self) -> None:
        if (
            type(self._sources) is not ApprovedSourceRegistryV1
            or type(self._ledger) is not DomainLedgerRepository
            or self._sources.workspace_id != self.workspace_id
            or self._sources.principal_id != self.principal_id
            or self._ledger.workspace_id != self.workspace_id
            or self._ledger.registry is not self._sources.registry
            or self._sources.registry.store.path.absolute()
            != self._control_path
            or id(self._sources.registry.store._require_connection())
            != self._connection_id
        ):
            raise CompanyGraphV1Denied("graph projector binding drift denied")
        self._sources._attest()
        self._ledger.verify_integrity()

    def _source_and_evidence(
        self,
        binding: GraphEvidenceBindingV1,
        *,
        now_ms: int,
        allowed_sensitivities: tuple[str, ...],
    ) -> tuple[ApprovedSourceRecordV1, EvidenceRecord]:
        source = self._sources.get(
            binding.source_name,
            now_ms=now_ms,
            require_fresh=True,
        )
        if source.sensitivity not in allowed_sensitivities:
            raise CompanyGraphV1Denied(
                "source sensitivity is outside graph policy"
            )
        evidence = self._ledger.get_evidence(binding.evidence_id)
        if (
            type(evidence) is not EvidenceRecord
            or evidence.workspace_id != self.workspace_id
            or evidence.source_identity_sha256
            != source.source_identity_sha256
            or evidence.content_sha256
            != domain_material_sha256_v1(binding.excerpt)
            or evidence.credibility_bp != source.credibility_bp
            or evidence.access_license_sha256
            != domain_material_sha256_v1(source.access_license_note)
            or evidence.freshness != "current"
            or (
                evidence.valid_until is not None
                and now_ms >= _utc_ms(evidence.valid_until, "evidence validity")
            )
            or (
                source.locator_kind == "artifact_alias"
                and evidence.artifact_id != source.artifact_id
            )
            or (
                source.locator_kind == "https"
                and evidence.artifact_id is not None
            )
        ):
            raise CompanyGraphV1Denied(
                "evidence/source binding or freshness drift"
            )
        expected_source_kind = (
            "artifact"
            if source.locator_kind == "artifact_alias"
            else "public_url"
        )
        if evidence.source_kind != expected_source_kind:
            raise CompanyGraphV1Denied("evidence source kind drift")
        return source, evidence

    @staticmethod
    def _verify_completion(
        assertion: CompanyGraphAssertionV1,
        claim: ClaimRecord,
        sources: tuple[ApprovedSourceRecordV1, ...],
    ) -> None:
        if assertion.status != "verified_complete":
            return
        if (
            assertion.semantic != "current_status"
            or claim.verification_status != "supported"
            or not assertion.definition_of_done
            or assertion.blockers
            or not any(
                source.authority in {"authoritative_primary", "official"}
                and source.source_kind
                in {"decision_record", "release", "test_report"}
                for source in sources
            )
        ):
            raise CompanyGraphV1Denied(
                "completion lacks authoritative verification evidence and DoD"
            )

    def project(
        self,
        assertions: tuple[CompanyGraphAssertionV1, ...],
        *,
        now_ms: int,
        allowed_sensitivities: tuple[str, ...],
    ) -> CompanyGraphProjectionV1:
        if (
            type(assertions) is not tuple
            or not assertions
            or len(assertions) > MAX_ASSERTIONS
            or any(type(item) is not CompanyGraphAssertionV1 for item in assertions)
            or tuple(sorted(assertions, key=lambda item: item.claim_id))
            != assertions
            or len({item.claim_id for item in assertions}) != len(assertions)
        ):
            raise CompanyGraphV1ContractError(
                "assertions must be nonempty, unique, and sorted"
            )
        if type(now_ms) is not int or now_ms < 0:
            raise CompanyGraphV1ContractError("now_ms is invalid")
        if (
            type(allowed_sensitivities) is not tuple
            or not allowed_sensitivities
            or len(set(allowed_sensitivities))
            != len(allowed_sensitivities)
            or any(value not in SENSITIVITIES for value in allowed_sensitivities)
        ):
            raise CompanyGraphV1ContractError(
                "allowed sensitivities are invalid"
            )
        self._attest()
        claims: dict[str, ClaimRecord] = {}
        items: list[CompanyGraphItemV1] = []
        relations: set[CompanyGraphRelationV1] = set()
        assertion_ids = {assertion.claim_id for assertion in assertions}
        for assertion in assertions:
            claim = self._ledger.get_claim(assertion.claim_id)
            if (
                type(claim) is not ClaimRecord
                or claim.workspace_id != self.workspace_id
                or claim.statement_sha256
                != domain_material_sha256_v1(assertion.canonical_statement())
                or claim.claim_kind
                not in _expected_claim_kind(assertion.semantic)
                or claim.verification_status
                not in {"supported", "unverified", "unknown", "contradicted"}
                or tuple(item.evidence_id for item in assertion.evidence)
                != claim.evidence_ids
                or (
                    claim.valid_until is not None
                    and now_ms >= _utc_ms(claim.valid_until, "claim validity")
                )
                or assertion.last_verified_ms > now_ms
                or assertion.last_verified_ms < _utc_ms(
                    claim.created_at,
                    "claim creation",
                )
            ):
                raise CompanyGraphV1Denied(
                    "claim/assertion binding or validity drift"
                )
            if (
                assertion.semantic
                in {
                    "approved_fact",
                    "current_status",
                    "evidence",
                    "metric",
                    "rejected_decision",
                    "superseded_decision",
                }
                and claim.verification_status != "supported"
            ):
                raise CompanyGraphV1Denied(
                    "knowledge assertion is not supported"
                )
            if any(
                reference not in assertion_ids
                for reference in (
                    *claim.contradiction_claim_ids,
                    *(
                        ()
                        if claim.supersedes_claim_id is None
                        else (claim.supersedes_claim_id,)
                    ),
                )
            ):
                raise CompanyGraphV1Denied(
                    "graph would hide a contradiction or supersession"
                )
            bound_sources: list[ApprovedSourceRecordV1] = []
            bound_evidence: list[EvidenceRecord] = []
            for binding in assertion.evidence:
                source, evidence = self._source_and_evidence(
                    binding,
                    now_ms=now_ms,
                    allowed_sensitivities=allowed_sensitivities,
                )
                bound_sources.append(source)
                bound_evidence.append(evidence)
                relations.add(
                    CompanyGraphRelationV1(
                        source_id=claim.claim_id,
                        relation="from_source",
                        target_id=source.source_id,
                        evidence_claim_id=claim.claim_id,
                    )
                )
            unique_sources = tuple(
                sorted(
                    {source.source_id: source for source in bound_sources}.values(),
                    key=lambda source: source.source_name,
                )
            )
            self._verify_completion(assertion, claim, unique_sources)
            items.append(
                CompanyGraphItemV1(
                    claim_id=claim.claim_id,
                    semantic=assertion.semantic,
                    project_id=assertion.project_id,
                    project_name=assertion.project_name,
                    subject_id=assertion.subject_id,
                    subject_name=assertion.subject_name,
                    owner=assertion.owner,
                    status=assertion.status,
                    blockers=assertion.blockers,
                    next_milestone=assertion.next_milestone,
                    definition_of_done=assertion.definition_of_done,
                    last_verified_ms=assertion.last_verified_ms,
                    confidence_bp=claim.confidence_bp,
                    verification_status=claim.verification_status,
                    source_names=tuple(
                        source.source_name for source in unique_sources
                    ),
                    citations=tuple(
                        source.citation for source in unique_sources
                    ),
                    evidence_ids=tuple(
                        evidence.evidence_id for evidence in bound_evidence
                    ),
                    evidence_sha256=tuple(
                        evidence.content_sha256 for evidence in bound_evidence
                    ),
                    authority_summary=tuple(
                        source.authority for source in unique_sources
                    ),
                    knowledge_class=_knowledge_class(
                        assertion.semantic,
                        claim.verification_status,
                    ),
                    freshness="fresh",
                    content_trust="untrusted_data",
                )
            )
            relations.add(
                CompanyGraphRelationV1(
                    source_id=claim.claim_id,
                    relation="about",
                    target_id=assertion.subject_id,
                    evidence_claim_id=claim.claim_id,
                )
            )
            relations.add(
                CompanyGraphRelationV1(
                    source_id=assertion.subject_id,
                    relation="belongs_to",
                    target_id=assertion.project_id,
                    evidence_claim_id=claim.claim_id,
                )
            )
            claims[claim.claim_id] = claim
        contradictions: set[tuple[str, str]] = set()
        supersessions: set[tuple[str, str]] = set()
        for claim in claims.values():
            for target in claim.contradiction_claim_ids:
                pair = tuple(sorted((claim.claim_id, target)))
                contradictions.add(pair)
                relations.add(
                    CompanyGraphRelationV1(
                        source_id=pair[0],
                        relation="contradicts",
                        target_id=pair[1],
                        evidence_claim_id=claim.claim_id,
                    )
                )
            if claim.supersedes_claim_id is not None:
                supersessions.add(
                    (claim.claim_id, claim.supersedes_claim_id)
                )
                relations.add(
                    CompanyGraphRelationV1(
                        source_id=claim.claim_id,
                        relation="supersedes",
                        target_id=claim.supersedes_claim_id,
                        evidence_claim_id=claim.claim_id,
                    )
                )
        items_tuple = tuple(sorted(items, key=lambda item: item.claim_id))
        relations_tuple = tuple(
            sorted(
                relations,
                key=lambda item: (
                    item.source_id,
                    item.relation,
                    item.target_id,
                    item.evidence_claim_id,
                ),
            )
        )
        contradictions_tuple = tuple(sorted(contradictions))
        supersessions_tuple = tuple(sorted(supersessions))
        projection = CompanyGraphProjectionV1(
            workspace_id=self.workspace_id,
            principal_id=self.principal_id,
            generated_at_ms=now_ms,
            items=items_tuple,
            relations=relations_tuple,
            contradictions=contradictions_tuple,
            supersessions=supersessions_tuple,
            graph_sha256=_projection_sha256(
                workspace_id=self.workspace_id,
                principal_id=self.principal_id,
                generated_at_ms=now_ms,
                items=items_tuple,
                relations=relations_tuple,
                contradictions=contradictions_tuple,
                supersessions=supersessions_tuple,
            ),
            read_only=True,
            content_trust="untrusted_data",
        )
        self._attest()
        return projection


def create_company_graph_projector_v1(
    *,
    gate: CompanyGraphFeatureGateV1 | None = None,
    sources: ApprovedSourceRegistryV1 | None = None,
    ledger: DomainLedgerRepository | None = None,
) -> CompanyGraphProjectorV1 | None:
    selected = (
        CompanyGraphFeatureGateV1.from_environ() if gate is None else gate
    )
    if type(selected) is not CompanyGraphFeatureGateV1:
        raise CompanyGraphV1ContractError("sealed feature gate required")
    if not selected.enabled:
        return None
    if sources is None or ledger is None:
        raise CompanyGraphV1ContractError(
            "enabled projector requires complete host bindings"
        )
    return CompanyGraphProjectorV1(
        construction_key=_CONSTRUCTION_KEY,
        sources=sources,
        ledger=ledger,
    )


__all__ = [
    "ASSERTION_SCHEMA",
    "ENABLED_VALUE",
    "FEATURE_FLAG",
    "MAX_ASSERTIONS",
    "SEMANTICS",
    "STATUSES",
    "CompanyGraphAssertionV1",
    "CompanyGraphFeatureGateV1",
    "CompanyGraphItemV1",
    "CompanyGraphProjectionV1",
    "CompanyGraphProjectorV1",
    "CompanyGraphRelationV1",
    "CompanyGraphV1ContractError",
    "CompanyGraphV1Denied",
    "CompanyGraphV1Error",
    "GraphEvidenceBindingV1",
    "create_company_graph_projector_v1",
]
