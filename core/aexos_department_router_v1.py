"""Governed task-first department routing over an attested AEXOS registry.

The router emits a bounded, non-executable plan.  It never dispatches a model,
worker or provider and therefore cannot turn discovery into ambient authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Final, Iterable

from core.aexos_engine_adapter_v1 import (
    AexosBudgetEnvelopeV1,
    AexosEngineAdapterV1,
    AexosEngineAdapterV1Denied,
)


SCHEMA: Final = "OnyxAexosDepartmentPlan.v1"
MAX_TASK_CHARS: Final = 4_000
MAX_DEPARTMENTS: Final = 4
_SQUAD_NAME = re.compile(r"^  - name: ([a-z0-9-]+)$", re.MULTILINE)
_UNTRUSTED_INSTRUCTION = (
    re.compile(r"\bignore (?:all |the )?(?:previous|prior) instructions?\b", re.I),
    re.compile(r"\b(?:system|developer) message\s*:", re.I),
)

# This is a routing vocabulary, not a source-of-truth registry. Every selected
# squad is checked against the byte-attested AEXOS registry before being emitted.
_ROUTES: Final = {
    "apex": ("frontend", "mobile", "ui", "ux", "design system", "3d", "performance"),
    "board": ("board", "governance", "audit", "risk", "oversight", "succession"),
    "brand": ("brand", "identity", "naming", "positioning", "logo"),
    "business-admin": ("finance", "people", "legal ops", "administration", "process"),
    "ceo": ("strategy", "capital", "organization", "stakeholder", "executive"),
    "claude-code-mastery": ("claude", "hooks", "skills", "mcp", "plugin"),
    "curator": ("curation", "knowledge", "taxonomy", "library", "content repository"),
    "customer-success": ("customer success", "retention", "onboarding", "advocacy", "support"),
    "deep-research": ("research", "market intelligence", "investigation", "evidence", "sources"),
    "dispatch": ("dispatch", "triage", "routing", "coordination"),
    "education": ("education", "learning", "curriculum", "teaching", "training"),
    "kaizen": ("continuous improvement", "kaizen", "efficiency", "optimization"),
    "kaizen-v2": ("operational excellence", "bottleneck", "waste", "throughput"),
    "legal-analyst": ("legal", "contract", "regulation", "compliance", "policy"),
    "marketing": ("marketing", "campaign", "content", "ads", "social media", "funnel"),
    "ops": ("operations", "incident", "reliability", "workflow", "delivery"),
    "products": ("product", "discovery", "pricing", "experiment", "jobs to be done"),
    "sales": ("sales", "pipeline", "qualification", "negotiation", "proposal"),
    "seo": ("seo", "search ranking", "keywords", "organic traffic"),
    "squad-creator": ("new squad", "create squad", "specialist team"),
}


class AexosDepartmentRouterV1ContractError(ValueError):
    pass


class AexosDepartmentRouterV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class AexosDepartmentRouteV1:
    squad_id: str
    score: int
    matched_terms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AexosDepartmentPlanV1:
    schema: str
    status: str
    story_id: str
    task_sha256: str
    budget_ceiling_micro_usd: int
    routes: tuple[AexosDepartmentRouteV1, ...]
    registry_sha256: str
    requires_owner_approval: bool
    dispatchable: bool
    provider_called: bool = False
    model_called: bool = False
    mutation_performed: bool = False


def _normalized_task(value: object) -> str:
    if type(value) is not str:
        raise AexosDepartmentRouterV1ContractError("task must be text")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > MAX_TASK_CHARS or "\x00" in normalized:
        raise AexosDepartmentRouterV1ContractError("task is outside its bound")
    if any(pattern.search(normalized) for pattern in _UNTRUSTED_INSTRUCTION):
        raise AexosDepartmentRouterV1Denied("task failed the intent security scan")
    return normalized


def _term_matches(task: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", task) is not None


class AexosDepartmentRouterV1:
    """Rank attested AEXOS squads for a task without executing them."""

    def __init__(self, adapter: AexosEngineAdapterV1) -> None:
        if type(adapter) is not AexosEngineAdapterV1:
            raise AexosDepartmentRouterV1ContractError("exact AEXOS adapter required")
        self._adapter = adapter

    def _attested_squads(self) -> tuple[set[str], str]:
        attestation = self._adapter.attest()
        if not attestation.available:
            raise AexosEngineAdapterV1Denied(
                f"AEXOS attestation failed: {attestation.reason_code}"
            )
        registry = self._adapter.registry_bytes()
        names = set(_SQUAD_NAME.findall(registry.decode("utf-8")))
        if not names:
            raise AexosDepartmentRouterV1Denied("AEXOS squad registry is empty")
        return names, hashlib.sha256(registry).hexdigest()

    def plan(
        self,
        task: object,
        *,
        envelope: AexosBudgetEnvelopeV1,
        requested_squads: Iterable[str] = (),
    ) -> AexosDepartmentPlanV1:
        if type(envelope) is not AexosBudgetEnvelopeV1:
            raise AexosDepartmentRouterV1ContractError("exact budget envelope required")
        normalized = _normalized_task(task)
        available, registry_sha256 = self._attested_squads()
        explicit = tuple(requested_squads)
        if len(explicit) > MAX_DEPARTMENTS or any(type(item) is not str for item in explicit):
            raise AexosDepartmentRouterV1ContractError("requested squads exceed their bound")
        unknown = sorted(set(explicit) - available)
        if unknown:
            raise AexosDepartmentRouterV1ContractError(
                f"unknown attested squad: {unknown[0]}"
            )
        lowered = normalized.casefold()
        scored: list[AexosDepartmentRouteV1] = []
        for squad_id, terms in _ROUTES.items():
            if squad_id not in available:
                continue
            matches = tuple(term for term in terms if _term_matches(lowered, term))
            score = len(matches) * 10 + (100 if squad_id in explicit else 0)
            if score:
                scored.append(AexosDepartmentRouteV1(squad_id, score, matches))
        if not scored:
            fallback = "dispatch" if "dispatch" in available else sorted(available)[0]
            scored.append(AexosDepartmentRouteV1(fallback, 1, ("task-first fallback",)))
        routes = tuple(sorted(scored, key=lambda item: (-item.score, item.squad_id))[:MAX_DEPARTMENTS])
        return AexosDepartmentPlanV1(
            schema=SCHEMA,
            status="planned_not_dispatched",
            story_id=envelope.story_id,
            task_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            budget_ceiling_micro_usd=envelope.budget_ceiling_micro_usd,
            routes=routes,
            registry_sha256=registry_sha256,
            requires_owner_approval=True,
            dispatchable=False,
        )


def bind_external_agent_objective_v1(
    task: object, plan: AexosDepartmentPlanV1
) -> str:
    """Seal an attested plan into the existing authenticated agent task.

    Phase 11 hashes and encrypts the returned task before provider dispatch,
    so a resulting ``onyx.external_agent.receipt.v1`` authenticates the exact
    story, registry, route and budget chosen here.
    """

    normalized = _normalized_task(task)
    if type(plan) is not AexosDepartmentPlanV1:
        raise AexosDepartmentRouterV1ContractError("exact AEXOS plan required")
    task_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    if (
        plan.schema != SCHEMA
        or plan.status != "planned_not_dispatched"
        or plan.task_sha256 != task_sha256
        or not plan.routes
        or plan.dispatchable is not False
        or plan.requires_owner_approval is not True
        or plan.provider_called is not False
        or plan.model_called is not False
        or plan.mutation_performed is not False
    ):
        raise AexosDepartmentRouterV1Denied("AEXOS plan binding failed")
    context = {
        "schema": "OnyxAexosExecutionContext.v1",
        "story_id": plan.story_id,
        "task_sha256": plan.task_sha256,
        "registry_sha256": plan.registry_sha256,
        "budget_ceiling_micro_usd": plan.budget_ceiling_micro_usd,
        "squads": [route.squad_id for route in plan.routes],
        "authority": (
            "detached_clone_patch_only; no publish, push, purchase, outreach, "
            "account mutation or deployment"
        ),
    }
    return normalized + "\n\n" + json.dumps(
        context, sort_keys=True, separators=(",", ":")
    )


__all__ = [
    "AexosDepartmentPlanV1",
    "AexosDepartmentRouteV1",
    "AexosDepartmentRouterV1",
    "AexosDepartmentRouterV1ContractError",
    "AexosDepartmentRouterV1Denied",
    "MAX_DEPARTMENTS",
    "SCHEMA",
    "bind_external_agent_objective_v1",
]
