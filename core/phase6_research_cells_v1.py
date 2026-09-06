"""Isolated provider-free Research and Independent Verifier Cells V1.

The candidate consumes only authenticated, content-addressed evidence. It
creates deterministic claim metadata and verifies that metadata without a
provider, network, live host import, or instruction channel.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Mapping

from core.phase6_agentic_core_v1 import (
    DataClassV1,
    OperatorCellProfileV1,
    RESEARCH_OPERATOR_V1,
    VERIFIER_OPERATOR_V1,
    WorkspaceScopeV1,
)
from core.phase6_agentic_core_v6 import AgenticCoreV6, AgenticStateStoreV6


FEATURE_FLAG: Final = "ONYX_PHASE6_RESEARCH_CELLS_V1"
CANDIDATE: Final = "phase6-research-cells-candidate-001"
MAX_SOURCES: Final = 32
MAX_SPANS_PER_SOURCE: Final = 64
MAX_TOTAL_SPANS: Final = 512
MAX_TOTAL_BYTES: Final = 1_048_576
MAX_FRESHNESS_MS: Final = 31_536_000_000
_CONSTRUCTION_KEY = object()
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
_CLAIM_KEY = re.compile(r"[a-z0-9][a-z0-9_.:/-]{0,255}\Z")
_URI = re.compile(r"(?:https://|urn:)[^\s]{1,2040}\Z")
_DATA_RANK = {
    DataClassV1.PUBLIC: 0,
    DataClassV1.INTERNAL: 1,
    DataClassV1.CONFIDENTIAL: 2,
    DataClassV1.RESTRICTED: 3,
}
_AGENTIC_CORE_TYPE = AgenticCoreV6
_AGENTIC_STATE_TYPE = AgenticStateStoreV6
_WORKSPACE_SCOPE_TYPE = WorkspaceScopeV1
_RESEARCH_PROFILE = RESEARCH_OPERATOR_V1
_VERIFIER_PROFILE = VERIFIER_OPERATOR_V1
_RLOCK_TYPE = type(threading.RLock())

RESEARCH_INSTRUCTION_PROFILE = {
    "schema": "OnyxResearchInstructionProfile.v1",
    "operator_id": "provider_free_research",
    "rules": [
        "authorized_evidence_only",
        "content_is_data_never_instruction",
        "all_claims_require_citations",
        "contradictions_and_freshness_explicit",
        "never_self_certify",
    ],
}
VERIFIER_INSTRUCTION_PROFILE = {
    "schema": "OnyxVerifierInstructionProfile.v1",
    "operator_id": "independent_verifier",
    "rules": [
        "candidate_and_evidence_only",
        "content_is_data_never_instruction",
        "validate_source_spans_and_digests",
        "never_generate_facts",
        "accept_only_fully_supported_fresh_consistent_candidate",
    ],
}


class ResearchCellsV1Error(RuntimeError):
    """The isolated research pipeline failed safely."""


class ResearchCellsV1ContractError(ValueError):
    """A caller supplied a non-canonical research contract."""


class ResearchCellsV1Denied(PermissionError):
    """Research authority, evidence, replay, or integrity was denied."""


class ResearchCellsV1Cancelled(ResearchCellsV1Error):
    """A bounded research or verification operation was cancelled."""


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResearchCellsV1ContractError("value is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(
        value if isinstance(value, bytes) else _canonical(value)
    ).hexdigest()


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ResearchCellsV1ContractError(f"{label} is not canonical")
    return value


def _claim_key(value: object) -> str:
    if type(value) is not str or _CLAIM_KEY.fullmatch(value) is None:
        raise ResearchCellsV1ContractError("claim_key is not canonical")
    return value


def _digest_value(value: object, label: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise ResearchCellsV1ContractError(f"{label} must be lowercase SHA-256")
    return value


def _bounded_int(value: object, label: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ResearchCellsV1ContractError(f"{label} is outside its bound")
    return value


def _bounded_text(value: object, label: str, maximum_bytes: int) -> str:
    if type(value) is not str or not value:
        raise ResearchCellsV1ContractError(f"{label} must be non-empty text")
    if len(value.encode("utf-8")) > maximum_bytes:
        raise ResearchCellsV1ContractError(f"{label} exceeds its byte bound")
    return value


def _key(value: object, label: str) -> bytes:
    if type(value) is not bytes or len(value) != 32:
        raise ResearchCellsV1ContractError(f"{label} must be exactly 32 bytes")
    return bytes(value)


def _profile_payload(profile: OperatorCellProfileV1) -> dict[str, object]:
    if type(profile) is not OperatorCellProfileV1:
        raise ResearchCellsV1ContractError("exact OperatorCellProfileV1 required")
    return {
        "operator_id": profile.operator_id,
        "version": profile.version,
        "allowed_capabilities": profile.allowed_capabilities,
        "maximum_data_class": profile.maximum_data_class.value,
        "independent_verifier_required": profile.independent_verifier_required,
    }


RESEARCH_OPERATOR_DIGEST: Final = _digest(_profile_payload(_RESEARCH_PROFILE))
VERIFIER_OPERATOR_DIGEST: Final = _digest(_profile_payload(_VERIFIER_PROFILE))
RESEARCH_INSTRUCTION_DIGEST: Final = _digest(RESEARCH_INSTRUCTION_PROFILE)
VERIFIER_INSTRUCTION_DIGEST: Final = _digest(VERIFIER_INSTRUCTION_PROFILE)


@dataclass(frozen=True, slots=True)
class ResearchCellsFeatureGateV1:
    enabled: bool

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ResearchCellsV1ContractError("feature gate must be exact bool")

    @classmethod
    def from_environ(
        cls, environ: Mapping[str, str] | None = None
    ) -> "ResearchCellsFeatureGateV1":
        source = os.environ if environ is None else environ
        return cls(source.get(FEATURE_FLAG, "") == "true")


@dataclass(frozen=True, slots=True)
class CellIdentityV1:
    operator_id: str
    operator_profile_digest: str
    instruction_profile_digest: str

    def __post_init__(self) -> None:
        _identifier(self.operator_id, "operator_id")
        _digest_value(self.operator_profile_digest, "operator_profile_digest")
        _digest_value(self.instruction_profile_digest, "instruction_profile_digest")

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxCellIdentity.v1",
                "operator_id": self.operator_id,
                "operator_profile_digest": self.operator_profile_digest,
                "instruction_profile_digest": self.instruction_profile_digest,
            }
        )


RESEARCH_IDENTITY: Final = CellIdentityV1(
    _RESEARCH_PROFILE.operator_id,
    RESEARCH_OPERATOR_DIGEST,
    RESEARCH_INSTRUCTION_DIGEST,
)
VERIFIER_IDENTITY: Final = CellIdentityV1(
    _VERIFIER_PROFILE.operator_id,
    VERIFIER_OPERATOR_DIGEST,
    VERIFIER_INSTRUCTION_DIGEST,
)
if RESEARCH_IDENTITY.digest == VERIFIER_IDENTITY.digest:
    raise RuntimeError("research and verifier identities must be distinct")
_RESEARCH_IDENTITY_DIGEST: Final = RESEARCH_IDENTITY.digest
_VERIFIER_IDENTITY_DIGEST: Final = VERIFIER_IDENTITY.digest


class ProviderFreeResearchCellV1:
    """Exact provider-free research identity; content is never instruction."""

    __slots__ = ()

    def __init__(self, *, _construction_key: object) -> None:
        if _construction_key is not _CONSTRUCTION_KEY:
            raise ResearchCellsV1Denied("research cell construction is factory-only")

    @property
    def identity(self) -> CellIdentityV1:
        return RESEARCH_IDENTITY

    def attest(self) -> None:
        if (
            RESEARCH_IDENTITY.digest != _RESEARCH_IDENTITY_DIGEST
            or _digest(RESEARCH_INSTRUCTION_PROFILE) != RESEARCH_INSTRUCTION_DIGEST
        ):
            raise ResearchCellsV1Denied("research cell identity drift denied")


class IndependentVerifierCellV1:
    """Independent verifier identity; it emits findings, never new facts."""

    __slots__ = ()

    def __init__(self, *, _construction_key: object) -> None:
        if _construction_key is not _CONSTRUCTION_KEY:
            raise ResearchCellsV1Denied("verifier cell construction is factory-only")

    @property
    def identity(self) -> CellIdentityV1:
        return VERIFIER_IDENTITY

    def attest(self) -> None:
        if (
            VERIFIER_IDENTITY.digest != _VERIFIER_IDENTITY_DIGEST
            or _digest(VERIFIER_INSTRUCTION_PROFILE) != VERIFIER_INSTRUCTION_DIGEST
        ):
            raise ResearchCellsV1Denied("verifier cell identity drift denied")


@dataclass(frozen=True, slots=True)
class ResearchBudgetV1:
    maximum_sources: int
    maximum_spans: int
    maximum_bytes: int
    maximum_age_ms: int
    deadline_at_ms: int

    def __post_init__(self) -> None:
        _bounded_int(self.maximum_sources, "maximum_sources", 1, MAX_SOURCES)
        _bounded_int(self.maximum_spans, "maximum_spans", 1, MAX_TOTAL_SPANS)
        _bounded_int(self.maximum_bytes, "maximum_bytes", 1, MAX_TOTAL_BYTES)
        _bounded_int(self.maximum_age_ms, "maximum_age_ms", 1, MAX_FRESHNESS_MS)
        _bounded_int(
            self.deadline_at_ms,
            "deadline_at_ms",
            0,
            9_223_372_036_854_775_807,
        )

    def payload(self) -> dict[str, int]:
        return {
            "maximum_sources": self.maximum_sources,
            "maximum_spans": self.maximum_spans,
            "maximum_bytes": self.maximum_bytes,
            "maximum_age_ms": self.maximum_age_ms,
            "deadline_at_ms": self.deadline_at_ms,
        }


@dataclass(frozen=True, slots=True)
class EvidenceSpanV1:
    span_id: str
    claim_key: str
    claim_value: str
    source_span_text: str

    def __post_init__(self) -> None:
        _identifier(self.span_id, "span_id")
        _claim_key(self.claim_key)
        _bounded_text(self.claim_value, "claim_value", 8_192)
        _bounded_text(self.source_span_text, "source_span_text", 16_384)

    def payload(self) -> dict[str, str]:
        return {
            "span_id": self.span_id,
            "claim_key": self.claim_key,
            "claim_value": self.claim_value,
            "source_span_text": self.source_span_text,
        }

    @property
    def digest(self) -> str:
        return _digest({"schema": "OnyxEvidenceSpan.v1", **self.payload()})


def _source_payload(
    *,
    source_id: str,
    source_uri: str,
    captured_at_ms: int,
    data_class: DataClassV1,
    workspace_id: str,
    spans: tuple[EvidenceSpanV1, ...],
) -> dict[str, object]:
    return {
        "schema": "OnyxAuthorizedEvidenceSource.v1",
        "source_id": source_id,
        "source_uri": source_uri,
        "captured_at_ms": captured_at_ms,
        "data_class": data_class.value,
        "workspace_id": workspace_id,
        "spans": [span.payload() | {"digest": span.digest} for span in spans],
    }


@dataclass(frozen=True, slots=True)
class AuthorizedEvidenceSourceV1:
    source_id: str
    source_uri: str
    captured_at_ms: int
    data_class: DataClassV1
    workspace_id: str
    spans: tuple[EvidenceSpanV1, ...]
    authorization_tag: str

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        if type(self.source_uri) is not str or _URI.fullmatch(self.source_uri) is None:
            raise ResearchCellsV1ContractError("source_uri is not canonical metadata")
        _bounded_int(
            self.captured_at_ms,
            "captured_at_ms",
            0,
            9_223_372_036_854_775_807,
        )
        if type(self.data_class) is not DataClassV1:
            raise ResearchCellsV1ContractError("exact DataClassV1 required")
        _identifier(self.workspace_id, "workspace_id")
        if (
            type(self.spans) is not tuple
            or not self.spans
            or len(self.spans) > MAX_SPANS_PER_SOURCE
            or any(type(span) is not EvidenceSpanV1 for span in self.spans)
        ):
            raise ResearchCellsV1ContractError("evidence spans are invalid")
        ids = tuple(span.span_id for span in self.spans)
        if ids != tuple(sorted(set(ids))):
            raise ResearchCellsV1ContractError(
                "evidence spans must be unique and sorted"
            )
        _digest_value(self.authorization_tag, "authorization_tag")

    @property
    def content_digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxEvidenceContent.v1",
                "spans": [
                    span.payload() | {"digest": span.digest} for span in self.spans
                ],
            }
        )

    @property
    def payload(self) -> dict[str, object]:
        return _source_payload(
            source_id=self.source_id,
            source_uri=self.source_uri,
            captured_at_ms=self.captured_at_ms,
            data_class=self.data_class,
            workspace_id=self.workspace_id,
            spans=self.spans,
        )

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedEvidenceSource.v1",
                "source_payload_digest": _digest(self.payload),
                "authorization_tag": self.authorization_tag,
            }
        )


def create_authorized_evidence_source_v1(
    *,
    source_id: str,
    source_uri: str,
    captured_at_ms: int,
    data_class: DataClassV1,
    workspace_id: str,
    spans: tuple[EvidenceSpanV1, ...],
    evidence_authority_key: bytes,
) -> AuthorizedEvidenceSourceV1:
    key = _key(evidence_authority_key, "evidence_authority_key")
    provisional = AuthorizedEvidenceSourceV1(
        source_id,
        source_uri,
        captured_at_ms,
        data_class,
        workspace_id,
        spans,
        "0" * 64,
    )
    tag = hmac.new(key, _canonical(provisional.payload), hashlib.sha256).hexdigest()
    return AuthorizedEvidenceSourceV1(
        source_id,
        source_uri,
        captured_at_ms,
        data_class,
        workspace_id,
        spans,
        tag,
    )


@dataclass(frozen=True, slots=True)
class EvidenceBundleV1:
    bundle_id: str
    workspace_id: str
    sources: tuple[AuthorizedEvidenceSourceV1, ...]
    authorization_tag: str

    def __post_init__(self) -> None:
        _identifier(self.bundle_id, "bundle_id")
        _identifier(self.workspace_id, "workspace_id")
        if (
            type(self.sources) is not tuple
            or not self.sources
            or len(self.sources) > MAX_SOURCES
            or any(
                type(source) is not AuthorizedEvidenceSourceV1
                for source in self.sources
            )
        ):
            raise ResearchCellsV1ContractError("evidence bundle is invalid")
        ids = tuple(source.source_id for source in self.sources)
        if ids != tuple(sorted(set(ids))):
            raise ResearchCellsV1ContractError(
                "evidence sources must be unique and sorted"
            )
        if any(source.workspace_id != self.workspace_id for source in self.sources):
            raise ResearchCellsV1Denied("cross-workspace evidence bundle denied")
        _digest_value(self.authorization_tag, "authorization_tag")

    @property
    def unsigned_payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxEvidenceBundle.v1",
            "bundle_id": self.bundle_id,
            "workspace_id": self.workspace_id,
            "sources": [
                {
                    "source_id": source.source_id,
                    "source_digest": source.digest,
                    "content_digest": source.content_digest,
                }
                for source in self.sources
            ],
        }

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedEvidenceBundle.v1",
                "unsigned_digest": _digest(self.unsigned_payload),
                "authorization_tag": self.authorization_tag,
            }
        )


def create_evidence_bundle_v1(
    *,
    bundle_id: str,
    workspace_id: str,
    sources: tuple[AuthorizedEvidenceSourceV1, ...],
    evidence_authority_key: bytes,
) -> EvidenceBundleV1:
    key = _key(evidence_authority_key, "evidence_authority_key")
    provisional = EvidenceBundleV1(
        bundle_id,
        workspace_id,
        sources,
        "0" * 64,
    )
    tag = hmac.new(
        key, _canonical(provisional.unsigned_payload), hashlib.sha256
    ).hexdigest()
    return EvidenceBundleV1(bundle_id, workspace_id, sources, tag)


@dataclass(frozen=True, slots=True)
class CitationV1:
    source_id: str
    source_uri: str
    source_digest: str
    span_id: str
    span_digest: str

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        if type(self.source_uri) is not str or _URI.fullmatch(self.source_uri) is None:
            raise ResearchCellsV1ContractError("citation URI is not canonical")
        _digest_value(self.source_digest, "source_digest")
        _identifier(self.span_id, "span_id")
        _digest_value(self.span_digest, "span_digest")

    def payload(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "source_uri": self.source_uri,
            "source_digest": self.source_digest,
            "span_id": self.span_id,
            "span_digest": self.span_digest,
        }


@dataclass(frozen=True, slots=True)
class ResearchClaimV1:
    claim_key: str
    claim_value: str
    citations: tuple[CitationV1, ...]

    def __post_init__(self) -> None:
        _claim_key(self.claim_key)
        _bounded_text(self.claim_value, "claim_value", 8_192)
        if (
            type(self.citations) is not tuple
            or not self.citations
            or len(self.citations) > MAX_TOTAL_SPANS
            or any(type(item) is not CitationV1 for item in self.citations)
        ):
            raise ResearchCellsV1ContractError("claim citations are invalid")
        keys = tuple((item.source_id, item.span_id) for item in self.citations)
        if keys != tuple(sorted(set(keys))):
            raise ResearchCellsV1ContractError(
                "claim citations must be unique and sorted"
            )

    def payload(self) -> dict[str, object]:
        return {
            "claim_key": self.claim_key,
            "claim_value": self.claim_value,
            "citations": [citation.payload() for citation in self.citations],
        }

    @property
    def digest(self) -> str:
        return _digest({"schema": "OnyxResearchClaim.v1", **self.payload()})


@dataclass(frozen=True, slots=True)
class ContradictionV1:
    claim_key: str
    claim_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        _claim_key(self.claim_key)
        if (
            type(self.claim_digests) is not tuple
            or len(self.claim_digests) < 2
            or self.claim_digests != tuple(sorted(set(self.claim_digests)))
        ):
            raise ResearchCellsV1ContractError("contradiction set is invalid")
        for digest in self.claim_digests:
            _digest_value(digest, "claim_digest")

    def payload(self) -> dict[str, object]:
        return {
            "claim_key": self.claim_key,
            "claim_digests": self.claim_digests,
        }


class FreshnessStatusV1(StrEnum):
    FRESH = "fresh"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class SourceFreshnessV1:
    source_id: str
    captured_at_ms: int
    age_ms: int
    status: FreshnessStatusV1

    def __post_init__(self) -> None:
        _identifier(self.source_id, "source_id")
        _bounded_int(
            self.captured_at_ms,
            "captured_at_ms",
            0,
            9_223_372_036_854_775_807,
        )
        _bounded_int(self.age_ms, "age_ms", 0, 9_223_372_036_854_775_807)
        if type(self.status) is not FreshnessStatusV1:
            raise ResearchCellsV1ContractError("exact freshness status required")

    def payload(self) -> dict[str, object]:
        return {
            "source_id": self.source_id,
            "captured_at_ms": self.captured_at_ms,
            "age_ms": self.age_ms,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ResearchCandidateV1:
    workspace_id: str
    evidence_bundle_digest: str
    research_identity_digest: str
    generated_at_ms: int
    claims: tuple[ResearchClaimV1, ...]
    contradictions: tuple[ContradictionV1, ...]
    freshness: tuple[SourceFreshnessV1, ...]
    status: str = "candidate_not_certified"
    certified: bool = False

    def __post_init__(self) -> None:
        _identifier(self.workspace_id, "workspace_id")
        _digest_value(self.evidence_bundle_digest, "evidence_bundle_digest")
        _digest_value(self.research_identity_digest, "research_identity_digest")
        _bounded_int(
            self.generated_at_ms,
            "generated_at_ms",
            0,
            9_223_372_036_854_775_807,
        )
        if (
            type(self.claims) is not tuple
            or not self.claims
            or len(self.claims) > MAX_TOTAL_SPANS
            or any(type(claim) is not ResearchClaimV1 for claim in self.claims)
        ):
            raise ResearchCellsV1ContractError("research claims are invalid")
        claim_keys = tuple(
            (claim.claim_key, claim.claim_value) for claim in self.claims
        )
        if claim_keys != tuple(sorted(set(claim_keys))):
            raise ResearchCellsV1ContractError(
                "research claims must be unique and sorted"
            )
        if (
            type(self.contradictions) is not tuple
            or any(type(item) is not ContradictionV1 for item in self.contradictions)
            or tuple(item.claim_key for item in self.contradictions)
            != tuple(sorted(set(item.claim_key for item in self.contradictions)))
        ):
            raise ResearchCellsV1ContractError("contradictions are not canonical")
        if (
            type(self.freshness) is not tuple
            or not self.freshness
            or any(type(item) is not SourceFreshnessV1 for item in self.freshness)
            or tuple(item.source_id for item in self.freshness)
            != tuple(sorted(set(item.source_id for item in self.freshness)))
        ):
            raise ResearchCellsV1ContractError("freshness is not canonical")
        if self.status != "candidate_not_certified" or self.certified is not False:
            raise ResearchCellsV1ContractError("research cannot self-certify")

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxResearchCandidate.v1",
            "workspace_id": self.workspace_id,
            "evidence_bundle_digest": self.evidence_bundle_digest,
            "research_identity_digest": self.research_identity_digest,
            "generated_at_ms": self.generated_at_ms,
            "claims": [
                claim.payload() | {"digest": claim.digest} for claim in self.claims
            ],
            "contradictions": [item.payload() for item in self.contradictions],
            "freshness": [item.payload() for item in self.freshness],
            "status": self.status,
            "certified": self.certified,
        }

    @property
    def digest(self) -> str:
        return _digest(self.payload())


class VerificationDecisionV1(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    REJECT = "reject"


@dataclass(frozen=True, slots=True)
class IndependentVerificationReportV1:
    decision: VerificationDecisionV1
    candidate_digest: str
    evidence_bundle_digest: str
    verifier_identity_digest: str
    supported_claim_digests: tuple[str, ...]
    unsupported_claim_digests: tuple[str, ...]
    contradiction_keys: tuple[str, ...]
    stale_source_ids: tuple[str, ...]
    findings: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.decision) is not VerificationDecisionV1:
            raise ResearchCellsV1ContractError("exact verification decision required")
        for value, label in (
            (self.candidate_digest, "candidate_digest"),
            (self.evidence_bundle_digest, "evidence_bundle_digest"),
            (self.verifier_identity_digest, "verifier_identity_digest"),
        ):
            _digest_value(value, label)
        for values, label, validator in (
            (self.supported_claim_digests, "supported claims", _digest_value),
            (self.unsupported_claim_digests, "unsupported claims", _digest_value),
            (
                self.contradiction_keys,
                "contradiction keys",
                lambda value, _: _claim_key(value),
            ),
            (self.stale_source_ids, "stale sources", _identifier),
            (self.findings, "findings", _identifier),
        ):
            if type(values) is not tuple or values != tuple(sorted(set(values))):
                raise ResearchCellsV1ContractError(f"{label} are not canonical")
            for value in values:
                validator(value, label)
        if self.decision is VerificationDecisionV1.ACCEPT and (
            self.unsupported_claim_digests
            or self.contradiction_keys
            or self.stale_source_ids
            or self.findings
        ):
            raise ResearchCellsV1ContractError(
                "accept decision cannot contain unresolved findings"
            )

    def payload(self) -> dict[str, object]:
        return {
            "schema": "OnyxIndependentVerificationReport.v1",
            "decision": self.decision.value,
            "candidate_digest": self.candidate_digest,
            "evidence_bundle_digest": self.evidence_bundle_digest,
            "verifier_identity_digest": self.verifier_identity_digest,
            "supported_claim_digests": self.supported_claim_digests,
            "unsupported_claim_digests": self.unsupported_claim_digests,
            "contradiction_keys": self.contradiction_keys,
            "stale_source_ids": self.stale_source_ids,
            "findings": self.findings,
        }

    @property
    def digest(self) -> str:
        return _digest(self.payload())


@dataclass(frozen=True, slots=True)
class CellReceiptV1:
    request_id: str
    operation: str
    workspace_id: str
    cell_identity_digest: str
    input_digest: str
    output_digest: str
    authentication_tag: str

    def __post_init__(self) -> None:
        _identifier(self.request_id, "request_id")
        if self.operation not in {"research", "verify"}:
            raise ResearchCellsV1ContractError("receipt operation is invalid")
        _identifier(self.workspace_id, "workspace_id")
        for value, label in (
            (self.cell_identity_digest, "cell_identity_digest"),
            (self.input_digest, "input_digest"),
            (self.output_digest, "output_digest"),
            (self.authentication_tag, "authentication_tag"),
        ):
            _digest_value(value, label)

    def unsigned_payload(self) -> dict[str, str]:
        return {
            "schema": "OnyxResearchCellReceipt.v1",
            "request_id": self.request_id,
            "operation": self.operation,
            "workspace_id": self.workspace_id,
            "cell_identity_digest": self.cell_identity_digest,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": "OnyxAuthenticatedResearchCellReceipt.v1",
                "unsigned_digest": _digest(self.unsigned_payload()),
                "authentication_tag": self.authentication_tag,
            }
        )


@dataclass(frozen=True, slots=True)
class FinalizedResearchV1:
    workspace_id: str
    candidate_digest: str
    verification_report_digest: str
    research_receipt_digest: str
    verification_receipt_digest: str
    status: str = "verified_complete"

    def __post_init__(self) -> None:
        _identifier(self.workspace_id, "workspace_id")
        for value in (
            self.candidate_digest,
            self.verification_report_digest,
            self.research_receipt_digest,
            self.verification_receipt_digest,
        ):
            _digest_value(value, "finalization digest")
        if self.status != "verified_complete":
            raise ResearchCellsV1ContractError("finalization status is invalid")


class ResearchVerifierPipelineV1:
    """Two-cell provider-free pipeline over exact Agentic Core V6 authority."""

    __slots__ = (
        "_core",
        "_state",
        "_workspace",
        "_evidence_key",
        "_evidence_key_digest",
        "_receipt_key",
        "_receipt_key_digest",
        "_research_cell",
        "_verifier_cell",
        "_receipts",
        "_outputs",
        "_lock",
    )

    def __init__(
        self,
        *,
        _construction_key: object,
        core: AgenticCoreV6,
        evidence_authority_key: bytes,
        receipt_authentication_key: bytes,
    ) -> None:
        if _construction_key is not _CONSTRUCTION_KEY:
            raise ResearchCellsV1Denied("pipeline construction is factory-only")
        if (
            type(core) is not _AGENTIC_CORE_TYPE
            or type(core._state) is not _AGENTIC_STATE_TYPE
            or type(core._workspace) is not _WORKSPACE_SCOPE_TYPE
            or core._closed
        ):
            raise ResearchCellsV1Denied("exact open Agentic Core V6 is required")
        evidence_key = _key(evidence_authority_key, "evidence_authority_key")
        receipt_key = _key(receipt_authentication_key, "receipt_authentication_key")
        if hmac.compare_digest(evidence_key, receipt_key):
            raise ResearchCellsV1ContractError(
                "evidence and receipt authorities must be distinct"
            )
        self._core = core
        self._state = core._state
        self._workspace = core._workspace
        self._evidence_key = evidence_key
        self._evidence_key_digest = _digest(evidence_key)
        self._receipt_key = receipt_key
        self._receipt_key_digest = _digest(receipt_key)
        self._research_cell = ProviderFreeResearchCellV1(
            _construction_key=_CONSTRUCTION_KEY
        )
        self._verifier_cell = IndependentVerifierCellV1(
            _construction_key=_CONSTRUCTION_KEY
        )
        self._receipts: dict[str, CellReceiptV1] = {}
        self._outputs: dict[
            str, ResearchCandidateV1 | IndependentVerificationReportV1
        ] = {}
        self._lock = threading.RLock()

    @property
    def research_identity(self) -> CellIdentityV1:
        self._research_cell.attest()
        return self._research_cell.identity

    @property
    def verifier_identity(self) -> CellIdentityV1:
        self._verifier_cell.attest()
        return self._verifier_cell.identity

    @property
    def state(self) -> AgenticStateStoreV6:
        self._attest()
        return self._state

    def _attest(self) -> None:
        if (
            AgenticCoreV6 is not _AGENTIC_CORE_TYPE
            or AgenticStateStoreV6 is not _AGENTIC_STATE_TYPE
            or WorkspaceScopeV1 is not _WORKSPACE_SCOPE_TYPE
            or RESEARCH_OPERATOR_V1 is not _RESEARCH_PROFILE
            or VERIFIER_OPERATOR_V1 is not _VERIFIER_PROFILE
            or _digest(_profile_payload(_RESEARCH_PROFILE)) != RESEARCH_OPERATOR_DIGEST
            or _digest(_profile_payload(_VERIFIER_PROFILE)) != VERIFIER_OPERATOR_DIGEST
            or _digest(RESEARCH_INSTRUCTION_PROFILE) != RESEARCH_INSTRUCTION_DIGEST
            or _digest(VERIFIER_INSTRUCTION_PROFILE) != VERIFIER_INSTRUCTION_DIGEST
            or RESEARCH_IDENTITY.operator_id != "provider_free_research"
            or RESEARCH_IDENTITY.operator_profile_digest != RESEARCH_OPERATOR_DIGEST
            or RESEARCH_IDENTITY.instruction_profile_digest
            != RESEARCH_INSTRUCTION_DIGEST
            or RESEARCH_IDENTITY.digest != _RESEARCH_IDENTITY_DIGEST
            or VERIFIER_IDENTITY.operator_id != "independent_verifier"
            or VERIFIER_IDENTITY.operator_profile_digest != VERIFIER_OPERATOR_DIGEST
            or VERIFIER_IDENTITY.instruction_profile_digest
            != VERIFIER_INSTRUCTION_DIGEST
            or VERIFIER_IDENTITY.digest != _VERIFIER_IDENTITY_DIGEST
            or type(self._research_cell) is not ProviderFreeResearchCellV1
            or type(self._verifier_cell) is not IndependentVerifierCellV1
            or type(self._core) is not _AGENTIC_CORE_TYPE
            or self._core._state is not self._state
            or self._core._workspace is not self._workspace
            or self._core._closed
            or type(self._evidence_key) is not bytes
            or len(self._evidence_key) != 32
            or not hmac.compare_digest(
                _digest(self._evidence_key), self._evidence_key_digest
            )
            or type(self._receipt_key) is not bytes
            or len(self._receipt_key) != 32
            or not hmac.compare_digest(
                _digest(self._receipt_key), self._receipt_key_digest
            )
            or type(self._receipts) is not dict
            or type(self._outputs) is not dict
            or set(self._receipts) != set(self._outputs)
            or type(self._lock) is not _RLOCK_TYPE
            or _RESEARCH_IDENTITY_DIGEST == _VERIFIER_IDENTITY_DIGEST
        ):
            raise ResearchCellsV1Denied("research pipeline authority drift denied")
        self._research_cell.attest()
        self._verifier_cell.attest()
        for request_id, receipt in self._receipts.items():
            output = self._outputs[request_id]
            if (
                type(request_id) is not str
                or receipt.request_id != request_id
                or (
                    receipt.operation == "research"
                    and (
                        type(output) is not ResearchCandidateV1
                        or receipt.cell_identity_digest != _RESEARCH_IDENTITY_DIGEST
                    )
                )
                or (
                    receipt.operation == "verify"
                    and (
                        type(output) is not IndependentVerificationReportV1
                        or receipt.cell_identity_digest != _VERIFIER_IDENTITY_DIGEST
                    )
                )
                or receipt.workspace_id != self._workspace.workspace_id
            ):
                raise ResearchCellsV1Denied("receipt replay map drift denied")
            self._attest_receipt(receipt, output.digest)

    def _attest_receipt(self, receipt: CellReceiptV1, output_digest: str) -> None:
        if type(receipt) is not CellReceiptV1 or receipt.output_digest != output_digest:
            raise ResearchCellsV1Denied("receipt output binding drift denied")
        expected = hmac.new(
            self._receipt_key,
            _canonical(receipt.unsigned_payload()),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(receipt.authentication_tag, expected):
            raise ResearchCellsV1Denied("forged cell receipt denied")

    def _validate_budget(
        self,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        *,
        now_ms: int,
        cancelled: bool,
    ) -> None:
        if type(bundle) is not EvidenceBundleV1:
            raise ResearchCellsV1ContractError("exact EvidenceBundleV1 required")
        if type(budget) is not ResearchBudgetV1:
            raise ResearchCellsV1ContractError("exact ResearchBudgetV1 required")
        _bounded_int(now_ms, "now_ms", 0, 9_223_372_036_854_775_807)
        if type(cancelled) is not bool:
            raise ResearchCellsV1ContractError("cancelled must be exact bool")
        if cancelled:
            raise ResearchCellsV1Cancelled("research operation cancelled")
        if now_ms > budget.deadline_at_ms:
            raise ResearchCellsV1Denied("research time budget exhausted")
        spans = sum(len(source.spans) for source in bundle.sources)
        size = sum(len(_canonical(source.payload)) for source in bundle.sources)
        if (
            len(bundle.sources) > budget.maximum_sources
            or spans > budget.maximum_spans
            or size > budget.maximum_bytes
        ):
            raise ResearchCellsV1Denied("research item or byte budget exhausted")

    def _validate_bundle(self, bundle: EvidenceBundleV1) -> None:
        if bundle.workspace_id != self._workspace.workspace_id:
            raise ResearchCellsV1Denied("cross-workspace evidence denied")
        expected_bundle_tag = hmac.new(
            self._evidence_key,
            _canonical(bundle.unsigned_payload),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(bundle.authorization_tag, expected_bundle_tag):
            raise ResearchCellsV1Denied("forged evidence bundle denied")
        maximum_rank = min(
            _DATA_RANK[self._workspace.maximum_data_class],
            _DATA_RANK[_RESEARCH_PROFILE.maximum_data_class],
        )
        for source in bundle.sources:
            if _DATA_RANK[source.data_class] > maximum_rank:
                raise ResearchCellsV1Denied("evidence classification denied")
            expected = hmac.new(
                self._evidence_key,
                _canonical(source.payload),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(source.authorization_tag, expected):
                raise ResearchCellsV1Denied("forged evidence source denied")

    def _validate_candidate_budget(
        self, candidate: ResearchCandidateV1, budget: ResearchBudgetV1
    ) -> None:
        if type(candidate) is not ResearchCandidateV1:
            raise ResearchCellsV1ContractError("exact ResearchCandidateV1 required")
        citations = sum(len(claim.citations) for claim in candidate.claims)
        size = len(_canonical(candidate.payload()))
        if (
            len(candidate.claims) > budget.maximum_spans
            or citations > budget.maximum_spans
            or len(candidate.freshness) > budget.maximum_sources
            or size > budget.maximum_bytes
        ):
            raise ResearchCellsV1Denied(
                "research candidate item or byte budget exhausted"
            )

    def _input_digest(
        self,
        operation: str,
        *,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        now_ms: int,
        candidate: ResearchCandidateV1 | None = None,
    ) -> str:
        return _digest(
            {
                "schema": "OnyxResearchCellInput.v1",
                "operation": operation,
                "workspace_id": self._workspace.workspace_id,
                "bundle_digest": bundle.digest,
                "budget": budget.payload(),
                "now_ms": now_ms,
                "candidate_digest": None if candidate is None else candidate.digest,
            }
        )

    def _replay(
        self,
        request_id: str,
        operation: str,
        input_digest: str,
    ) -> (
        tuple[ResearchCandidateV1, CellReceiptV1]
        | tuple[IndependentVerificationReportV1, CellReceiptV1]
        | None
    ):
        _identifier(request_id, "request_id")
        receipt = self._receipts.get(request_id)
        if receipt is None:
            return None
        output = self._outputs[request_id]
        self._attest_receipt(receipt, output.digest)
        if receipt.operation != operation or receipt.input_digest != input_digest:
            raise ResearchCellsV1Denied("request replay conflict denied")
        return output, receipt

    def _commit(
        self,
        *,
        request_id: str,
        operation: str,
        identity: CellIdentityV1,
        input_digest: str,
        output: ResearchCandidateV1 | IndependentVerificationReportV1,
    ) -> CellReceiptV1:
        unsigned = {
            "schema": "OnyxResearchCellReceipt.v1",
            "request_id": request_id,
            "operation": operation,
            "workspace_id": self._workspace.workspace_id,
            "cell_identity_digest": identity.digest,
            "input_digest": input_digest,
            "output_digest": output.digest,
        }
        tag = hmac.new(
            self._receipt_key, _canonical(unsigned), hashlib.sha256
        ).hexdigest()
        receipt = CellReceiptV1(
            request_id,
            operation,
            self._workspace.workspace_id,
            identity.digest,
            input_digest,
            output.digest,
            tag,
        )
        self._outputs[request_id] = output
        self._receipts[request_id] = receipt
        return receipt

    @staticmethod
    def _claims(bundle: EvidenceBundleV1) -> tuple[ResearchClaimV1, ...]:
        grouped: dict[tuple[str, str], list[CitationV1]] = {}
        for source in bundle.sources:
            for span in source.spans:
                grouped.setdefault((span.claim_key, span.claim_value), []).append(
                    CitationV1(
                        source.source_id,
                        source.source_uri,
                        source.digest,
                        span.span_id,
                        span.digest,
                    )
                )
        return tuple(
            ResearchClaimV1(
                key,
                value,
                tuple(
                    sorted(citations, key=lambda item: (item.source_id, item.span_id))
                ),
            )
            for (key, value), citations in sorted(grouped.items())
        )

    @staticmethod
    def _contradictions(
        claims: tuple[ResearchClaimV1, ...],
    ) -> tuple[ContradictionV1, ...]:
        grouped: dict[str, list[str]] = {}
        for claim in claims:
            grouped.setdefault(claim.claim_key, []).append(claim.digest)
        return tuple(
            ContradictionV1(key, tuple(sorted(digests)))
            for key, digests in sorted(grouped.items())
            if len(digests) > 1
        )

    @staticmethod
    def _freshness(
        bundle: EvidenceBundleV1,
        *,
        now_ms: int,
        maximum_age_ms: int,
    ) -> tuple[SourceFreshnessV1, ...]:
        values = []
        for source in bundle.sources:
            if source.captured_at_ms > now_ms:
                raise ResearchCellsV1Denied("future evidence timestamp denied")
            age = now_ms - source.captured_at_ms
            values.append(
                SourceFreshnessV1(
                    source.source_id,
                    source.captured_at_ms,
                    age,
                    (
                        FreshnessStatusV1.FRESH
                        if age <= maximum_age_ms
                        else FreshnessStatusV1.STALE
                    ),
                )
            )
        return tuple(values)

    def research(
        self,
        request_id: str,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        *,
        now_ms: int,
        cancelled: bool = False,
    ) -> tuple[ResearchCandidateV1, CellReceiptV1]:
        with self._lock:
            return self._research(
                request_id,
                bundle,
                budget,
                now_ms=now_ms,
                cancelled=cancelled,
            )

    def _research(
        self,
        request_id: str,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        *,
        now_ms: int,
        cancelled: bool = False,
    ) -> tuple[ResearchCandidateV1, CellReceiptV1]:
        self._attest()
        self._validate_budget(bundle, budget, now_ms=now_ms, cancelled=cancelled)
        self._validate_bundle(bundle)
        input_digest = self._input_digest(
            "research", bundle=bundle, budget=budget, now_ms=now_ms
        )
        replay = self._replay(request_id, "research", input_digest)
        if replay is not None:
            output, receipt = replay
            if type(output) is not ResearchCandidateV1:
                raise ResearchCellsV1Denied("research replay type drift denied")
            return output, receipt
        claims = self._claims(bundle)
        candidate = ResearchCandidateV1(
            self._workspace.workspace_id,
            bundle.digest,
            RESEARCH_IDENTITY.digest,
            now_ms,
            claims,
            self._contradictions(claims),
            self._freshness(
                bundle, now_ms=now_ms, maximum_age_ms=budget.maximum_age_ms
            ),
        )
        self._validate_candidate_budget(candidate, budget)
        receipt = self._commit(
            request_id=request_id,
            operation="research",
            identity=RESEARCH_IDENTITY,
            input_digest=input_digest,
            output=candidate,
        )
        return candidate, receipt

    @staticmethod
    def _evidence_index(
        bundle: EvidenceBundleV1,
    ) -> dict[tuple[str, str], tuple[AuthorizedEvidenceSourceV1, EvidenceSpanV1]]:
        return {
            (source.source_id, span.span_id): (source, span)
            for source in bundle.sources
            for span in source.spans
        }

    def verify(
        self,
        request_id: str,
        candidate: ResearchCandidateV1,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        *,
        now_ms: int,
        cancelled: bool = False,
    ) -> tuple[IndependentVerificationReportV1, CellReceiptV1]:
        with self._lock:
            return self._verify(
                request_id,
                candidate,
                bundle,
                budget,
                now_ms=now_ms,
                cancelled=cancelled,
            )

    def _verify(
        self,
        request_id: str,
        candidate: ResearchCandidateV1,
        bundle: EvidenceBundleV1,
        budget: ResearchBudgetV1,
        *,
        now_ms: int,
        cancelled: bool = False,
    ) -> tuple[IndependentVerificationReportV1, CellReceiptV1]:
        self._attest()
        if type(candidate) is not ResearchCandidateV1:
            raise ResearchCellsV1ContractError("exact ResearchCandidateV1 required")
        self._validate_budget(bundle, budget, now_ms=now_ms, cancelled=cancelled)
        self._validate_bundle(bundle)
        self._validate_candidate_budget(candidate, budget)
        if (
            candidate.workspace_id != self._workspace.workspace_id
            or candidate.evidence_bundle_digest != bundle.digest
            or candidate.research_identity_digest != RESEARCH_IDENTITY.digest
            or candidate.generated_at_ms > now_ms
        ):
            raise ResearchCellsV1Denied("candidate input binding drift denied")
        input_digest = self._input_digest(
            "verify",
            bundle=bundle,
            budget=budget,
            now_ms=now_ms,
            candidate=candidate,
        )
        replay = self._replay(request_id, "verify", input_digest)
        if replay is not None:
            output, receipt = replay
            if type(output) is not IndependentVerificationReportV1:
                raise ResearchCellsV1Denied("verification replay type drift denied")
            return output, receipt

        evidence = self._evidence_index(bundle)
        supported: list[str] = []
        unsupported: list[str] = []
        for claim in candidate.claims:
            citation_validity: list[bool] = []
            for citation in claim.citations:
                source_span = evidence.get((citation.source_id, citation.span_id))
                if source_span is None:
                    citation_validity.append(False)
                else:
                    source, span = source_span
                    citation_validity.append(
                        citation.source_uri == source.source_uri
                        and citation.source_digest == source.digest
                        and citation.span_digest == span.digest
                        and claim.claim_key == span.claim_key
                        and claim.claim_value == span.claim_value
                    )
            claim_supported = bool(citation_validity) and all(citation_validity)
            (supported if claim_supported else unsupported).append(claim.digest)

        expected_pairs = {
            (span.claim_key, span.claim_value)
            for source in bundle.sources
            for span in source.spans
        }
        candidate_pairs = {
            (claim.claim_key, claim.claim_value) for claim in candidate.claims
        }
        findings: set[str] = set()
        if unsupported:
            findings.add("unsupported_claim")
        if candidate_pairs != expected_pairs:
            findings.add("evidence_coverage_gap")
        expected_claims = self._claims(bundle)
        if candidate.claims != expected_claims:
            findings.add("claim_projection_drift")
        expected_contradictions = self._contradictions(expected_claims)
        if candidate.contradictions != expected_contradictions:
            findings.add("contradiction_projection_drift")
        contradiction_keys = tuple(
            sorted(item.claim_key for item in expected_contradictions)
        )
        if contradiction_keys:
            findings.add("contradiction")
        expected_freshness = self._freshness(
            bundle, now_ms=now_ms, maximum_age_ms=budget.maximum_age_ms
        )
        if candidate.freshness != self._freshness(
            bundle,
            now_ms=candidate.generated_at_ms,
            maximum_age_ms=budget.maximum_age_ms,
        ):
            findings.add("freshness_projection_drift")
        stale = tuple(
            sorted(
                item.source_id
                for item in expected_freshness
                if item.status is FreshnessStatusV1.STALE
            )
        )
        if stale:
            findings.add("stale_evidence")
        if {
            "unsupported_claim",
            "evidence_coverage_gap",
            "claim_projection_drift",
            "contradiction_projection_drift",
            "freshness_projection_drift",
        } & findings:
            decision = VerificationDecisionV1.REJECT
        elif findings:
            decision = VerificationDecisionV1.REVISE
        else:
            decision = VerificationDecisionV1.ACCEPT
        report = IndependentVerificationReportV1(
            decision,
            candidate.digest,
            bundle.digest,
            VERIFIER_IDENTITY.digest,
            tuple(sorted(supported)),
            tuple(sorted(unsupported)),
            contradiction_keys,
            stale,
            tuple(sorted(findings)),
        )
        receipt = self._commit(
            request_id=request_id,
            operation="verify",
            identity=VERIFIER_IDENTITY,
            input_digest=input_digest,
            output=report,
        )
        return report, receipt

    def finalize(
        self, research_request_id: str, verification_request_id: str
    ) -> FinalizedResearchV1:
        with self._lock:
            return self._finalize(research_request_id, verification_request_id)

    def _finalize(
        self, research_request_id: str, verification_request_id: str
    ) -> FinalizedResearchV1:
        self._attest()
        research_receipt = self._receipts.get(research_request_id)
        verification_receipt = self._receipts.get(verification_request_id)
        candidate = self._outputs.get(research_request_id)
        report = self._outputs.get(verification_request_id)
        if (
            type(research_receipt) is not CellReceiptV1
            or research_receipt.operation != "research"
            or type(verification_receipt) is not CellReceiptV1
            or verification_receipt.operation != "verify"
            or type(candidate) is not ResearchCandidateV1
            or type(report) is not IndependentVerificationReportV1
            or report.decision is not VerificationDecisionV1.ACCEPT
            or report.candidate_digest != candidate.digest
            or report.evidence_bundle_digest != candidate.evidence_bundle_digest
        ):
            raise ResearchCellsV1Denied(
                "pipeline finalization requires independent acceptance"
            )
        return FinalizedResearchV1(
            self._workspace.workspace_id,
            candidate.digest,
            report.digest,
            research_receipt.digest,
            verification_receipt.digest,
        )


def create_research_verifier_pipeline_v1(
    *,
    gate: ResearchCellsFeatureGateV1,
    core: AgenticCoreV6 | None = None,
    evidence_authority_key: bytes = b"",
    receipt_authentication_key: bytes = b"",
) -> ResearchVerifierPipelineV1 | None:
    if type(gate) is not ResearchCellsFeatureGateV1:
        raise ResearchCellsV1ContractError("exact ResearchCellsFeatureGateV1 required")
    if not gate.enabled:
        return None
    if type(core) is not _AGENTIC_CORE_TYPE:
        raise ResearchCellsV1ContractError("exact AgenticCoreV6 required")
    return ResearchVerifierPipelineV1(
        _construction_key=_CONSTRUCTION_KEY,
        core=core,
        evidence_authority_key=evidence_authority_key,
        receipt_authentication_key=receipt_authentication_key,
    )


__all__ = [
    "CANDIDATE",
    "FEATURE_FLAG",
    "AuthorizedEvidenceSourceV1",
    "CellIdentityV1",
    "CellReceiptV1",
    "CitationV1",
    "ContradictionV1",
    "EvidenceBundleV1",
    "EvidenceSpanV1",
    "FinalizedResearchV1",
    "FreshnessStatusV1",
    "IndependentVerificationReportV1",
    "IndependentVerifierCellV1",
    "ProviderFreeResearchCellV1",
    "RESEARCH_IDENTITY",
    "ResearchBudgetV1",
    "ResearchCandidateV1",
    "ResearchCellsFeatureGateV1",
    "ResearchCellsV1Cancelled",
    "ResearchCellsV1ContractError",
    "ResearchCellsV1Denied",
    "ResearchCellsV1Error",
    "ResearchClaimV1",
    "ResearchVerifierPipelineV1",
    "SourceFreshnessV1",
    "VERIFIER_IDENTITY",
    "VerificationDecisionV1",
    "create_authorized_evidence_source_v1",
    "create_evidence_bundle_v1",
    "create_research_verifier_pipeline_v1",
]
