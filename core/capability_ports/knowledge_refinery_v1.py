"""Provider-free, candidate-only local knowledge refinery capability port."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from threading import RLock
from typing import Protocol

from core.governance_nucleus_v1 import GovernanceV1ContractError, GovernanceV1Denied
from core.governed_capability_host_v1 import HostBoundCapabilityPortV1

OPERATIONS = frozenset({"ingest", "propose_promotion", "status"})
SUPPORTED_RIGHTS = frozenset({"owned", "licensed", "public-domain", "test-fixture"})
MAX_DIGEST_BYTES = 64


class KnowledgeRefineryStateStoreV1(Protocol):
    """Injected persistence boundary; saves replace the complete state atomically."""

    def load_bytes(self) -> bytes | None: ...

    def save_bytes(self, value: bytes) -> None: ...


def _exact_str(value: object, label: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or len(value.encode("utf-8")) > maximum:
        raise GovernanceV1ContractError(f"knowledge refinery {label} is malformed")
    return value


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    except (TypeError, ValueError) as exc:
        raise GovernanceV1ContractError("knowledge refinery value is not canonical JSON") from exc


class KnowledgeRefineryCapabilityPortV1(HostBoundCapabilityPortV1):
    """Classify injected local content and persist only inert candidate records."""

    def __init__(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        allowed_sources: Sequence[Mapping[str, object]],
        local_inputs: Mapping[str, bytes],
        max_items: int,
        max_bytes: int,
        owner_promotion_token_sha256: str,
        store: KnowledgeRefineryStateStoreV1 | None = None,
    ) -> None:
        super().__init__()
        self._principal_id = _exact_str(principal_id, "principal binding")
        self._workspace_id = _exact_str(workspace_id, "workspace binding")
        if type(max_items) is not int or isinstance(max_items, bool) or not 1 <= max_items <= 10_000:
            raise GovernanceV1ContractError("knowledge refinery item budget is out of bounds")
        if type(max_bytes) is not int or isinstance(max_bytes, bool) or not 1 <= max_bytes <= 1_000_000_000:
            raise GovernanceV1ContractError("knowledge refinery byte budget is out of bounds")
        if (type(owner_promotion_token_sha256) is not str or len(owner_promotion_token_sha256) != MAX_DIGEST_BYTES
                or any(char not in "0123456789abcdef" for char in owner_promotion_token_sha256)):
            raise GovernanceV1ContractError("owner promotion token digest is malformed")
        if type(local_inputs) is not dict or any(type(key) is not str or type(value) is not bytes
                                                 for key, value in local_inputs.items()):
            raise GovernanceV1ContractError("local inputs must be an injected exact bytes mapping")
        if store is not None and (not callable(getattr(store, "load_bytes", None)) or
                                  not callable(getattr(store, "save_bytes", None))):
            raise GovernanceV1ContractError("knowledge refinery store contract violation")
        self._sources = self._validate_sources(allowed_sources)
        self._inputs = dict(local_inputs)
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._owner_token_digest = owner_promotion_token_sha256
        self._store = store
        self._lock = RLock()
        self._killed = False
        self._candidates: dict[str, dict[str, object]] = {}
        self._idempotency: dict[str, dict[str, object]] = {}
        if store is not None:
            raw = store.load_bytes()  # Construction reads only the injected store boundary.
            if raw is not None:
                self._restore(raw)

    @staticmethod
    def _validate_sources(sources: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
        if type(sources) not in {list, tuple}:
            raise GovernanceV1ContractError("allowed local sources must be an exact sequence")
        result: dict[str, dict[str, object]] = {}
        required = {"source_id", "descriptor", "sha256", "provenance", "rights", "linked"}
        for source in sources:
            if type(source) is not dict or set(source) != required:
                raise GovernanceV1ContractError("local source descriptor contract violation")
            source_id = _exact_str(source["source_id"], "source id")
            descriptor = _exact_str(source["descriptor"], "source descriptor", maximum=1024)
            path = PurePosixPath(descriptor)
            if (source["linked"] is not False or path.is_absolute() or ".." in path.parts or "\\" in descriptor
                    or ":" in descriptor or descriptor.startswith(("~", "/"))):
                raise GovernanceV1Denied("linked or escaping local source descriptor denied")
            digest = _exact_str(source["sha256"], "source digest", maximum=MAX_DIGEST_BYTES)
            if len(digest) != MAX_DIGEST_BYTES or any(char not in "0123456789abcdef" for char in digest):
                raise GovernanceV1ContractError("source digest must be exact lowercase sha256")
            rights = _exact_str(source["rights"], "rights")
            if rights not in SUPPORTED_RIGHTS:
                raise GovernanceV1Denied("unsupported source rights")
            provenance = _exact_str(source["provenance"], "provenance", maximum=2048)
            if source_id in result or descriptor in {item["descriptor"] for item in result.values()}:
                raise GovernanceV1ContractError("duplicate source descriptor")
            result[source_id] = {"source_id": source_id, "descriptor": descriptor, "sha256": digest,
                                 "provenance": provenance, "rights": rights, "linked": False}
        return result

    def _restore(self, raw: bytes) -> None:
        try:
            state = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GovernanceV1ContractError("knowledge refinery store state is malformed") from exc
        keys = {"schema", "principal_id", "workspace_id", "limits", "source_policy_sha256", "candidates", "idempotency"}
        if type(state) is not dict or set(state) != keys:
            raise GovernanceV1ContractError("knowledge refinery store state contract violation")
        expected_policy = hashlib.sha256(_canonical(self._sources)).hexdigest()
        if (state["schema"] != "OnyxKnowledgeRefinery.v1" or state["principal_id"] != self._principal_id
                or state["workspace_id"] != self._workspace_id
                or state["limits"] != {"max_items": self._max_items, "max_bytes": self._max_bytes}
                or state["source_policy_sha256"] != expected_policy):
            raise GovernanceV1Denied("knowledge refinery persisted binding or policy mismatch")
        if type(state["candidates"]) is not dict or type(state["idempotency"]) is not dict:
            raise GovernanceV1ContractError("knowledge refinery persisted collections are malformed")
        self._candidates = state["candidates"]
        self._idempotency = state["idempotency"]
        self._validate_state()

    def _validate_state(self) -> None:
        if len(self._candidates) > self._max_items:
            raise GovernanceV1Denied("persisted knowledge refinery item budget exceeded")
        used = 0
        for candidate_id, item in self._candidates.items():
            required = {"candidate_id", "source_id", "descriptor", "sha256", "provenance", "rights",
                        "claim_key", "classification", "size_bytes", "state", "actionable"}
            if (type(candidate_id) is not str or type(item) is not dict or set(item) != required
                    or item["candidate_id"] != candidate_id or item["classification"] not in {"candidate", "contradiction", "poison", "quarantine"}
                    or item["state"] != "candidate" or item["actionable"] is not False
                    or type(item["size_bytes"]) is not int or item["size_bytes"] < 0):
                raise GovernanceV1ContractError("persisted candidate is malformed")
            source = self._sources.get(item["source_id"])
            content = self._inputs.get(str(item["descriptor"]))
            expected_id = "knowledge-candidate-" + hashlib.sha256(
                (self._workspace_id + "\0" + str(item["source_id"]) + "\0" + str(item["sha256"])).encode()
            ).hexdigest()[:32]
            if (source is None or content is None or item["descriptor"] != source["descriptor"]
                    or item["sha256"] != source["sha256"] or item["provenance"] != source["provenance"]
                    or item["rights"] != source["rights"] or hashlib.sha256(content).hexdigest() != item["sha256"]
                    or len(content) != item["size_bytes"] or candidate_id != expected_id):
                raise GovernanceV1Denied("persisted candidate provenance or digest mismatch")
            used += item["size_bytes"]
        for key, item in self._idempotency.items():
            if (type(key) is not str or not key or type(item) is not dict
                    or set(item) != {"fingerprint", "result"} or type(item["fingerprint"]) is not str
                    or len(item["fingerprint"]) != MAX_DIGEST_BYTES or type(item["result"]) is not dict):
                raise GovernanceV1ContractError("persisted idempotency record is malformed")
        if used > self._max_bytes:
            raise GovernanceV1Denied("persisted knowledge refinery byte budget exceeded")

    def _encoded(self) -> bytes:
        return _canonical({"schema": "OnyxKnowledgeRefinery.v1", "principal_id": self._principal_id,
                           "workspace_id": self._workspace_id,
                           "limits": {"max_items": self._max_items, "max_bytes": self._max_bytes},
                           "source_policy_sha256": hashlib.sha256(_canonical(self._sources)).hexdigest(),
                           "candidates": self._candidates, "idempotency": self._idempotency})

    def _scope(self, arguments: Mapping[str, object], extra: set[str]) -> str:
        required = {"principal_id", "workspace_id", "idempotency_key"} | extra
        if type(arguments) is not dict or set(arguments) != required:
            raise GovernanceV1ContractError("knowledge refinery operation arguments contract violation")
        if arguments["principal_id"] != self._principal_id or arguments["workspace_id"] != self._workspace_id:
            raise GovernanceV1Denied("knowledge refinery principal or workspace binding mismatch")
        return _exact_str(arguments["idempotency_key"], "idempotency key", maximum=256)

    def _prior(self, operation: str, arguments: Mapping[str, object], key: str) -> dict[str, object] | None:
        fingerprint = hashlib.sha256(_canonical({"operation": operation, "arguments": arguments})).hexdigest()
        prior = self._idempotency.get(key)
        if prior is None:
            return None
        if type(prior) is not dict or prior.get("fingerprint") != fingerprint or type(prior.get("result")) is not dict:
            raise GovernanceV1Denied("knowledge refinery idempotency key reuse mismatch")
        return dict(prior["result"])

    def _record(self, key: str, operation: str, arguments: Mapping[str, object], result: dict[str, object]) -> dict[str, object]:
        self._idempotency[key] = {"fingerprint": hashlib.sha256(
            _canonical({"operation": operation, "arguments": arguments})).hexdigest(), "result": result}
        if self._store is not None:
            self._store.save_bytes(self._encoded())
        return result

    def _dispatch_authorized(self, operation: str, arguments: Mapping[str, object]) -> object:
        extras = ({"source_id", "claim_key"} if operation == "ingest" else
                  ({"candidate_id", "owner_promotion_token"} if operation == "propose_promotion" else set()))
        key = self._scope(arguments, extras)
        with self._lock:
            if self._killed:
                raise GovernanceV1Denied("knowledge refinery kill is latched")
            prior = self._prior(operation, arguments, key)
            if prior is not None:
                return prior
            if operation == "status":
                result = {"schema": "onyx.knowledge-refinery-capability-port.v1", "candidate_count": len(self._candidates),
                          "used_bytes": sum(int(item["size_bytes"]) for item in self._candidates.values()),
                          "candidate_only": True, "actionable": False, "external_boundary_used": False}
                return self._record(key, operation, arguments, result)
            if operation == "ingest":
                return self._ingest(arguments, key)
            if operation == "propose_promotion":
                return self._propose_promotion(arguments, key)
            raise GovernanceV1Denied("knowledge refinery operation is not permitted")

    def _ingest(self, arguments: Mapping[str, object], key: str) -> dict[str, object]:
        source_id = _exact_str(arguments["source_id"], "source id")
        claim_key = _exact_str(arguments["claim_key"], "claim key")
        source = self._sources.get(source_id)
        if source is None:
            raise GovernanceV1Denied("source is not allowlisted")
        content = self._inputs.get(str(source["descriptor"]))
        if content is None:
            raise GovernanceV1Denied("allowlisted source content was not injected")
        digest = hashlib.sha256(content).hexdigest()
        if digest != source["sha256"]:
            raise GovernanceV1Denied("local source digest mismatch")
        duplicate = next((item for item in self._candidates.values() if item["sha256"] == digest), None)
        if duplicate is not None:
            result = {"status": "duplicate", "candidate_id": duplicate["candidate_id"], "candidate_only": True,
                      "actionable": False, "external_boundary_used": False}
            return self._record(key, "ingest", arguments, result)
        used = sum(int(item["size_bytes"]) for item in self._candidates.values())
        if len(self._candidates) >= self._max_items or used + len(content) > self._max_bytes:
            raise GovernanceV1Denied("knowledge refinery hard budget exhausted")
        lowered = content.lower()
        poison_markers = (b"ignore previous", b"system prompt", b"execute command", b"tool call", b"<script")
        classification = "poison" if any(marker in lowered for marker in poison_markers) else "candidate"
        if b"\x00" in content or not content.strip():
            classification = "quarantine"
        elif classification == "candidate" and any(item["claim_key"] == claim_key and item["sha256"] != digest
                                                     for item in self._candidates.values()):
            classification = "contradiction"
        candidate_id = "knowledge-candidate-" + hashlib.sha256(
            (self._workspace_id + "\0" + source_id + "\0" + digest).encode()).hexdigest()[:32]
        record = {"candidate_id": candidate_id, "source_id": source_id, "descriptor": source["descriptor"],
                  "sha256": digest, "provenance": source["provenance"], "rights": source["rights"],
                  "claim_key": claim_key, "classification": classification, "size_bytes": len(content),
                  "state": "candidate", "actionable": False}
        self._candidates[candidate_id] = record
        result = {"status": "stored-candidate", "record": dict(record), "candidate_only": True,
                  "actionable": False, "external_boundary_used": False}
        try:
            return self._record(key, "ingest", arguments, result)
        except Exception:
            self._candidates.pop(candidate_id, None)
            self._idempotency.pop(key, None)
            raise

    def _propose_promotion(self, arguments: Mapping[str, object], key: str) -> dict[str, object]:
        candidate_id = _exact_str(arguments["candidate_id"], "candidate id")
        token = _exact_str(arguments["owner_promotion_token"], "owner promotion token", maximum=1024)
        if not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), self._owner_token_digest):
            raise GovernanceV1Denied("owner promotion approval is missing or invalid")
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise GovernanceV1ContractError("unknown knowledge candidate")
        if candidate["classification"] != "candidate":
            raise GovernanceV1Denied("quarantined or disputed knowledge cannot be proposed")
        result = {"status": "promotion-proposal-only", "candidate_id": candidate_id, "candidate_state": "candidate",
                  "promoted": False, "actionable": False, "external_boundary_used": False}
        return self._record(key, "propose_promotion", arguments, result)

    def revoke(self, binding_id: str) -> None:
        del binding_id

    def kill(self) -> bool:
        with self._lock:
            self._killed = True
        return True


__all__ = ["KnowledgeRefineryCapabilityPortV1", "KnowledgeRefineryStateStoreV1", "OPERATIONS",
           "SUPPORTED_RIGHTS"]
