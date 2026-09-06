"""Governed model-tool adapter for the accepted Google Workspace host v1.

This module is imported only after the source provenance gate in
``onyx_live_activation_google_workspace_v1`` succeeds.  It never talks to a
Google transport or a native vault directly; the accepted host service remains
the sole provider boundary.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from core.google_workspace_connector_v1 import (
    READ_SCOPES,
    GoogleProviderReceiptV1,
    GoogleReadResultV1,
    GoogleWorkspaceV1ContractError,
    GoogleWorkspaceV1Denied,
    GoogleWorkspaceV1UnknownOutcome,
)
from core.google_workspace_host_v1 import (
    GoogleWorkspaceHostServiceV1,
    GoogleWorkspaceHostStatusV1,
    GoogleWorkspaceHostV1ContractError,
    GoogleWorkspaceHostV1Denied,
    GoogleWorkspaceHostV1UnknownOutcome,
)


TOOL_NAME: Final = "google_workspace"
ACTIONS: Final = (
    "status",
    "connect",
    "disconnect",
    "list_gmail_messages",
    "list_calendar_events",
)
READ_ACTIONS: Final = frozenset(
    {"status", "list_gmail_messages", "list_calendar_events"}
)
CONSEQUENTIAL_ACTIONS: Final = frozenset({"connect", "disconnect"})
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_MAX_TRACE: Final = 64
_ZERO_DIGEST: Final = "0" * 64
_RFC3339: Final = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?"
    r"(?:Z|[+-]\d{2}:\d{2})"
)
_GMAIL_FIELDS: Final = frozenset({"id", "thread_id"})
_CALENDAR_FIELDS: Final = frozenset(
    {"id", "status", "summary", "start", "end", "location", "htmlLink"}
)
_CALENDAR_DATE: Final = re.compile(r"\d{4}-\d{2}-\d{2}")


class GoogleWorkspaceLiveV1Error(RuntimeError):
    """Base class for the source-only live adapter."""


class GoogleWorkspaceLiveV1ContractError(ValueError):
    """The model or host supplied a value outside the fixed contract."""


class GoogleWorkspaceLiveV1Denied(PermissionError):
    """The request conclusively failed before a consequential attempt."""


class GoogleWorkspaceLiveV1UnknownOutcome(GoogleWorkspaceLiveV1Error):
    """An external or consequential outcome needs reconciliation."""


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceAuditIdentityV1:
    owner_pseudonym: str
    workspace_pseudonym: str
    account_pseudonym: str
    binding_digest: str

    def __post_init__(self) -> None:
        for value in (
            self.owner_pseudonym,
            self.workspace_pseudonym,
            self.account_pseudonym,
            self.binding_digest,
        ):
            if type(value) is not str or _DIGEST.fullmatch(value) is None:
                raise GoogleWorkspaceLiveV1ContractError(
                    "Google audit identity is invalid"
                )


def pseudonymize_live_identity_v1(
    *, owner_id: str, workspace_id: str, account_id: str, key: bytes
) -> GoogleWorkspaceAuditIdentityV1:
    if type(key) is not bytes or len(key) < 32:
        raise GoogleWorkspaceLiveV1ContractError(
            "Google audit pseudonym key is invalid"
        )

    def digest(domain: str, value: str) -> str:
        if type(value) is not str or not value:
            raise GoogleWorkspaceLiveV1ContractError(
                "Google audit identity source is invalid"
            )
        return hmac.new(
            key,
            b"OnyxGoogleWorkspaceLiveAudit.v1\0"
            + domain.encode("ascii")
            + b"\0"
            + value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    owner = digest("owner", owner_id)
    workspace = digest("workspace", workspace_id)
    account = digest("account", account_id)
    binding = digest("binding", f"{owner_id}\0{workspace_id}\0{account_id}")
    return GoogleWorkspaceAuditIdentityV1(owner, workspace, account, binding)


def tool_declaration_google_workspace_v1() -> dict[str, object]:
    """Return the single exact model-visible declaration."""

    return {
        "name": TOOL_NAME,
        "description": (
            "Read the owner's connected Google Workspace status, unread Gmail "
            "messages, or bounded Calendar window. Connecting and disconnecting "
            "always require a trusted host decision."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "enum": list(ACTIONS)},
                "query": {"type": "STRING", "enum": ["is:unread"]},
                "time_min": {"type": "STRING"},
                "time_max": {"type": "STRING"},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    }


def validate_google_workspace_arguments_v1(
    arguments: Mapping[str, object] | None,
) -> dict[str, object]:
    if type(arguments) is not dict:
        raise GoogleWorkspaceLiveV1ContractError(
            "Google Workspace arguments must be an exact object"
        )
    copied = dict(arguments)
    if any(type(key) is not str for key in copied):
        raise GoogleWorkspaceLiveV1ContractError(
            "Google Workspace argument names are invalid"
        )
    action = copied.get("action")
    if type(action) is not str or action not in ACTIONS:
        raise GoogleWorkspaceLiveV1ContractError(
            "Google Workspace action is invalid"
        )
    allowed = {
        "status": {"action"},
        "connect": {"action"},
        "disconnect": {"action"},
        "list_gmail_messages": {"action", "query"},
        "list_calendar_events": {"action", "time_min", "time_max"},
    }[action]
    if set(copied) - allowed:
        raise GoogleWorkspaceLiveV1ContractError(
            "Google Workspace arguments contain forbidden fields"
        )
    if action == "list_gmail_messages":
        query = copied.get("query", "is:unread")
        if type(query) is not str or query != "is:unread":
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace Gmail query is invalid"
            )
        copied["query"] = query
    if action == "list_calendar_events":
        parsed: list[datetime] = []
        for field in ("time_min", "time_max"):
            value = copied.get(field)
            if (
                type(value) is not str
                or _RFC3339.fullmatch(value) is None
                or len(value.encode("utf-8")) > 64
            ):
                raise GoogleWorkspaceLiveV1ContractError(
                    "Google Workspace calendar window is invalid"
                )
            try:
                instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                raise GoogleWorkspaceLiveV1ContractError(
                    "Google Workspace calendar window is invalid"
                ) from None
            if instant.tzinfo is None or instant.utcoffset() is None:
                raise GoogleWorkspaceLiveV1ContractError(
                    "Google Workspace calendar window is invalid"
                )
            parsed.append(instant)
        if parsed[0] >= parsed[1]:
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace calendar window is invalid"
            )
    return copied


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def idempotency_digest_v1(value: str) -> str:
    """Return the exact durable reservation digest for one caller identity."""

    if type(value) is not str or not value or not value.isascii() or len(value) > 256:
        raise GoogleWorkspaceLiveV1ContractError(
            "Google Workspace idempotency identity is invalid"
        )
    return _canonical_digest(value)


def _status_projection(value: GoogleWorkspaceHostStatusV1) -> dict[str, object]:
    return {
        "enabled": value.enabled,
        "configured": value.configured,
        "connected": value.connected,
        "backend": value.supported_backend,
        "binding_digest": value.binding_digest,
        "anchor_generation": value.anchor_generation,
        "anchor_health": value.anchor_health,
        "scopes": list(value.scopes),
        "pending_loopback": value.pending_loopback,
        "reconciliation": value.reconciliation,
        "trust_limit": value.trust_limit,
    }


def _status_digest(value: GoogleWorkspaceHostStatusV1) -> str:
    return _canonical_digest(_status_projection(value))


def _project_read_items(
    action: str, items: tuple[dict[str, object], ...]
) -> tuple[dict[str, object], ...]:
    projected: list[dict[str, object]] = []
    for raw in items:
        if type(raw) is not dict:
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google read projection contract drifted"
            )
        if action == "list_gmail_messages":
            if set(raw) != _GMAIL_FIELDS or any(
                type(raw[field]) is not str
                or not raw[field]
                or len(raw[field].encode("utf-8")) > 512
                for field in _GMAIL_FIELDS
            ):
                raise GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Gmail projection contract drifted"
                )
        else:
            if (
                not {"id", "start", "end"}.issubset(raw)
                or set(raw) - _CALENDAR_FIELDS
                or type(raw["id"]) is not str
                or not raw["id"]
            ):
                raise GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Calendar projection contract drifted"
                )
            for temporal_name in ("start", "end"):
                temporal = raw[temporal_name]
                if (
                    type(temporal) is not dict
                    or not set(temporal).issubset({"date", "dateTime", "timeZone"})
                    or len({"date", "dateTime"}.intersection(temporal)) != 1
                ):
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google Calendar projection contract drifted"
                    )
                value_name = next(iter({"date", "dateTime"}.intersection(temporal)))
                temporal_value = temporal[value_name]
                timezone_value = temporal.get("timeZone")
                if (
                    type(temporal_value) is not str
                    or not temporal_value
                    or len(temporal_value.encode("utf-8")) > 64
                    or (
                        value_name == "date"
                        and _CALENDAR_DATE.fullmatch(temporal_value) is None
                    )
                    or (
                        value_name == "dateTime"
                        and _RFC3339.fullmatch(temporal_value) is None
                    )
                    or (
                        timezone_value is not None
                        and (
                            type(timezone_value) is not str
                            or not timezone_value
                            or len(timezone_value.encode("utf-8")) > 64
                        )
                    )
                ):
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google Calendar projection contract drifted"
                    )
            for field in set(raw) - {"start", "end"}:
                if (
                    type(raw[field]) is not str
                    or not raw[field]
                    or len(raw[field].encode("utf-8")) > 2048
                ):
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google Calendar projection contract drifted"
                    )
        projected.append(dict(raw))
    return tuple(projected)


def _receipt_projection(value: GoogleProviderReceiptV1) -> dict[str, object]:
    return {
        "operation": value.operation,
        "status": value.status,
        "binding_digest": value.binding_digest,
        "request_digest": value.request_digest,
        "response_digest": value.response_digest,
        "grant_digest": value.grant_digest,
        "item_count": value.item_count,
        "page_count": value.page_count,
        "receipt_digest": _canonical_digest(
            {
                "operation": value.operation,
                "status": value.status,
                "binding_digest": value.binding_digest,
                "request_digest": value.request_digest,
                "response_digest": value.response_digest,
                "grant_digest": value.grant_digest,
                "item_count": value.item_count,
                "page_count": value.page_count,
            }
        ),
    }


_DENIED_EXCEPTIONS: Final = (
    GoogleWorkspaceV1ContractError,
    GoogleWorkspaceV1Denied,
    GoogleWorkspaceHostV1ContractError,
)
_HOST_DENIED_EXCEPTIONS: Final = (GoogleWorkspaceHostV1Denied,)
_UNKNOWN_EXCEPTIONS: Final = (
    GoogleWorkspaceV1UnknownOutcome,
    GoogleWorkspaceHostV1UnknownOutcome,
)


class GoogleWorkspaceLiveAdapterV1:
    """Strict host-only dispatcher with policy, receipts and post-verification."""

    def __init__(
        self,
        *,
        service: GoogleWorkspaceHostServiceV1,
        audit_identity: GoogleWorkspaceAuditIdentityV1,
        expected_binding_digest: str,
        central_authorizer: Callable[[str, Mapping[str, object]], tuple[bool, str]],
        reservation_port: Callable[..., object],
        denied_audit_port: Callable[..., object],
        audit_port: Callable[..., object],
        audit_verify_port: Callable[..., bool],
        epoch_clock: Callable[[], float] = time.time,
    ) -> None:
        if type(service) is not GoogleWorkspaceHostServiceV1:
            raise GoogleWorkspaceLiveV1ContractError(
                "exact Google Workspace host service is required"
            )
        if type(audit_identity) is not GoogleWorkspaceAuditIdentityV1:
            raise GoogleWorkspaceLiveV1ContractError(
                "exact Google Workspace audit identity is required"
            )
        if (
            type(expected_binding_digest) is not str
            or _DIGEST.fullmatch(expected_binding_digest) is None
        ):
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace binding digest is invalid"
            )
        if (
            not callable(central_authorizer)
            or not callable(reservation_port)
            or not callable(denied_audit_port)
            or not callable(audit_port)
            or not callable(audit_verify_port)
        ):
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace host policy ports are unavailable"
            )
        if not callable(epoch_clock):
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace clock is unavailable"
            )
        self._service = service
        self._identity = audit_identity
        self._binding_digest = expected_binding_digest
        self._authorizer = central_authorizer
        self._reserve = reservation_port
        self._audit_denied = denied_audit_port
        self._audit = audit_port
        self._audit_verify = audit_verify_port
        self._epoch = epoch_clock

    def _status(self) -> GoogleWorkspaceHostStatusV1:
        value = self._service.status()
        if type(value) is not GoogleWorkspaceHostStatusV1:
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace status contract drifted"
            )
        if (
            type(value.binding_digest) is not str
            or value.binding_digest != self._binding_digest
            or type(value.scopes) is not tuple
            or value.scopes != READ_SCOPES
            or any(type(scope) is not str for scope in value.scopes)
            or type(value.enabled) is not bool
            or value.enabled is not True
            or type(value.configured) is not bool
            or value.configured is not True
            or type(value.connected) is not bool
            or type(value.anchor_health) is not str
            or value.anchor_health not in {"available", "read-only"}
            or type(value.supported_backend) is not str
            or value.supported_backend
            not in {"Windows Credential Manager", "source-test"}
            or (
                value.anchor_generation is not None
                and (
                    type(value.anchor_generation) is not int
                    or value.anchor_generation < 0
                )
            )
            or type(value.pending_loopback) is not bool
            or type(value.reconciliation) is not str
            or value.reconciliation
            not in {"connected", "disconnected", "revoked", "attempted_unknown"}
            or type(value.trust_limit) is not str
            or value.trust_limit
            not in {"cooperating-process-cas-only", "source-test"}
        ):
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace status binding is unavailable"
            )
        return value

    def _authorize(
        self, action: str, arguments: Mapping[str, object], trace_id: str
    ) -> str:
        now = self._epoch()
        if type(now) not in {int, float} or isinstance(now, bool):
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace policy clock is unavailable"
            )
        nonce = secrets.token_hex(16)
        expiry = int(float(now) * 1000) + 30_000
        trusted = {
            "action": action,
            "argument_digest": _canonical_digest(arguments),
            "owner_pseudonym": self._identity.owner_pseudonym,
            "workspace_pseudonym": self._identity.workspace_pseudonym,
            "account_pseudonym": self._identity.account_pseudonym,
            "binding_digest": self._binding_digest,
            "trace_id": trace_id,
            "nonce": nonce,
            "expires_at_epoch_ms": expiry,
        }
        result = self._authorizer(TOOL_NAME, trusted)
        if (
            type(result) is not tuple
            or len(result) != 2
            or type(result[0]) is not bool
            or type(result[1]) is not str
        ):
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace policy result is invalid"
            )
        approved, proof = result
        current = self._epoch()
        if (
            not approved
            or not proof
            or type(current) not in {int, float}
            or isinstance(current, bool)
            or int(float(current) * 1000) > expiry
        ):
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace request was not approved"
            )
        if action in CONSEQUENTIAL_ACTIONS and _DIGEST.fullmatch(proof) is None:
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace consequential approval is invalid"
            )
        return proof

    def _validate_receipt(
        self,
        value: object,
        *,
        operations: frozenset[str],
        statuses: frozenset[str],
        expected_items: int | None = None,
    ) -> GoogleProviderReceiptV1:
        if type(value) is not GoogleProviderReceiptV1:
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace receipt contract drifted"
            )
        receipt = value
        if (
            type(receipt.operation) is not str
            or receipt.operation not in operations
            or type(receipt.status) is not str
            or receipt.status not in statuses
            or type(receipt.binding_digest) is not str
            or receipt.binding_digest != self._binding_digest
            or type(receipt.request_digest) is not str
            or type(receipt.response_digest) is not str
            or type(receipt.grant_digest) is not str
            or type(receipt.provider_content_included) is not bool
            or receipt.provider_content_included is not False
            or type(receipt.credentials_included) is not bool
            or receipt.credentials_included is not False
            or any(
                _DIGEST.fullmatch(field) is None
                for field in (
                    receipt.binding_digest,
                    receipt.request_digest,
                    receipt.response_digest,
                    receipt.grant_digest,
                )
            )
            or type(receipt.item_count) is not int
            or type(receipt.page_count) is not int
            or not 0 <= receipt.item_count <= 500
            or not 0 <= receipt.page_count <= 5
            or (expected_items is not None and receipt.item_count != expected_items)
        ):
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace receipt post-verification failed"
            )
        return receipt

    def _audit_once(
        self,
        *,
        action: str,
        arguments: Mapping[str, object],
        trace_id: str,
        started_state: str,
        ended_state: str,
        provider_attempted: bool,
        completion: str,
        receipt_digest: str,
        result_digest: str,
        status_digest: str,
        decision: str,
        proof: str,
        idempotency_key: str,
        item_count: int,
        page_count: int,
        generation_before: int | None,
        generation_after: int | None,
        result_record: dict[str, object],
    ) -> None:
        contract = {
            "contract": "OnyxGoogleWorkspaceAudit.v1",
            "trace_id": trace_id,
            "identity": {
                "owner_pseudonym": self._identity.owner_pseudonym,
                "workspace_pseudonym": self._identity.workspace_pseudonym,
                "account_pseudonym": self._identity.account_pseudonym,
                "binding_digest": self._binding_digest,
            },
            "operation": {
                "action": action,
                "argument_digest": _canonical_digest(arguments),
                "idempotency_digest": _canonical_digest(idempotency_key),
            },
            "decision": {
                "class": decision,
                "proof_digest": _canonical_digest(proof),
            },
            "outcome": {
                "start_state": started_state,
                "end_state": ended_state,
                "provider_boundary": (
                    "may_execute" if provider_attempted else "not_reached"
                ),
                "completion": completion,
                "receipt_digest": receipt_digest or _ZERO_DIGEST,
                "result_digest": result_digest or _ZERO_DIGEST,
                "item_count": item_count,
                "page_count": page_count,
                "generation_before": generation_before,
                "generation_after": generation_after,
                "external_dispatch": provider_attempted,
                "status_digest": status_digest or _ZERO_DIGEST,
            },
        }
        reference = self._audit(contract=contract, result=result_record)
        event_hash = getattr(reference, "event_hash", None)
        if (
            type(event_hash) is not str
            or _DIGEST.fullmatch(event_hash) is None
            or self._audit_verify(
                contract=contract, result=result_record, event_hash=event_hash
            )
            is not True
        ):
            raise GoogleWorkspaceLiveV1Error(
                "Google Workspace audit contract drifted"
            )

    def execute(
        self,
        arguments: Mapping[str, object] | None,
        *,
        trace_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        if (
            type(trace_id) is not str
            or not trace_id
            or len(trace_id) > _MAX_TRACE
            or not trace_id.isascii()
        ):
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace trace identity is invalid"
            )
        selected_idempotency = trace_id if idempotency_key is None else idempotency_key
        if (
            type(selected_idempotency) is not str
            or not selected_idempotency
            or len(selected_idempotency) > 256
            or not selected_idempotency.isascii()
        ):
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace idempotency identity is invalid"
            )
        idempotency_digest = idempotency_digest_v1(selected_idempotency)
        try:
            validated = validate_google_workspace_arguments_v1(arguments)
        except GoogleWorkspaceLiveV1ContractError:
            raise GoogleWorkspaceLiveV1ContractError(
                "Google Workspace arguments are invalid"
            ) from None
        action = validated["action"]
        assert isinstance(action, str)
        argument_digest = _canonical_digest(validated)
        authorization_error = False
        proof = ""
        try:
            proof = self._authorize(action, validated, trace_id)
        except BaseException:
            authorization_error = True
        if authorization_error:
            denial_error = False
            reference = None
            try:
                reference = self._audit_denied(
                    binding_digest=self._binding_digest,
                    action=action,
                    argument_digest=argument_digest,
                    idempotency_digest=idempotency_digest,
                    trace_id=trace_id,
                    proof_digest=_canonical_digest(proof),
                )
            except BaseException:
                denial_error = True
            if (
                denial_error
                or type(getattr(reference, "trace_id", None)) is not str
                or type(getattr(reference, "event_hash", None)) is not str
                or _DIGEST.fullmatch(reference.event_hash) is None
            ):
                raise GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace denial audit requires reconciliation"
                ) from None
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace request was not approved"
            ) from None
        reservation_error = False
        claim = None
        try:
            claim = self._reserve(
                binding_digest=self._binding_digest,
                action=action,
                argument_digest=argument_digest,
                idempotency_digest=idempotency_digest,
                trace_id=trace_id,
            )
        except BaseException:
            reservation_error = True
        if reservation_error:
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace idempotency authority requires reconciliation"
            ) from None
        claim_state = getattr(claim, "state", None)
        claim_result = getattr(claim, "result", None)
        if claim_state == "unknown":
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace prior outcome requires reconciliation"
            ) from None
        if claim_state == "completed" and type(claim_result) is dict:
            payload = claim_result.get("payload")
            if claim_result.get("kind") != "response" or type(payload) is not dict:
                raise GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace replay record drifted"
                ) from None
            return dict(payload)
        if claim_state == "denied" and type(claim_result) is dict:
            raise GoogleWorkspaceLiveV1Denied(
                "Google Workspace request was previously denied"
            ) from None
        if claim_state != "claimed":
            raise GoogleWorkspaceLiveV1UnknownOutcome(
                "Google Workspace idempotency authority failed closed"
            ) from None
        provider_attempted = False
        started_state = "unknown"
        ended_state = "denied"
        completion = "denied"
        receipt_digest = _ZERO_DIGEST
        result_digest = _ZERO_DIGEST
        status_digest = _ZERO_DIGEST
        decision = "allow"
        item_count = 0
        page_count = 0
        generation_before: int | None = None
        generation_after: int | None = None
        response: dict[str, object] | None = None
        pending_error: BaseException | None = None
        try:
            before = self._status()
            generation_before = before.anchor_generation
            status_digest = _status_digest(before)
            started_state = "connected" if before.connected else "disconnected"
            if action == "status":
                response = {
                    "schema": "OnyxGoogleWorkspaceStatus.v1",
                    "status": "succeeded",
                    "action": action,
                    "result": _status_projection(before),
                    "external_dispatch": False,
                }
                ended_state = started_state
                generation_after = generation_before
                result_digest = _canonical_digest(response)
            elif action == "connect":
                provider_attempted = True
                receipt = self._validate_receipt(
                    self._service.connect(),
                    operations=frozenset({"authorize"}),
                    statuses=frozenset({"connected"}),
                )
                after = self._status()
                if not after.connected or after.reconciliation != "connected":
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google connection post-verification failed"
                    )
                projected = _receipt_projection(receipt)
                receipt_digest = str(projected["receipt_digest"])
                generation_after = after.anchor_generation
                status_digest = _status_digest(after)
                item_count = receipt.item_count
                page_count = receipt.page_count
                response = {
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "succeeded",
                    "action": action,
                    "receipt": projected,
                    "external_dispatch": True,
                    "postverified": True,
                }
                ended_state = "connected"
                result_digest = _canonical_digest(response)
            elif action == "disconnect":
                provider_attempted = True
                receipt = self._validate_receipt(
                    self._service.disconnect(),
                    operations=frozenset({"revoke"}),
                    statuses=frozenset({"revoked"}),
                )
                after = self._status()
                if after.connected or after.reconciliation not in {
                    "revoked",
                    "disconnected",
                }:
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google disconnection post-verification failed"
                    )
                projected = _receipt_projection(receipt)
                receipt_digest = str(projected["receipt_digest"])
                generation_after = after.anchor_generation
                status_digest = _status_digest(after)
                item_count = receipt.item_count
                page_count = receipt.page_count
                response = {
                    "schema": "OnyxGoogleWorkspaceCommand.v1",
                    "status": "succeeded",
                    "action": action,
                    "receipt": projected,
                    "external_dispatch": True,
                    "postverified": True,
                }
                ended_state = "disconnected"
                result_digest = _canonical_digest(response)
            else:
                provider_attempted = True
                if action == "list_gmail_messages":
                    value = self._service.test_gmail()
                    expected_operation = frozenset({"gmail_list"})
                else:
                    value = self._service.test_calendar(
                        time_min=str(validated["time_min"]),
                        time_max=str(validated["time_max"]),
                    )
                    expected_operation = frozenset({"calendar_list"})
                if type(value) is not GoogleReadResultV1:
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google read result contract drifted"
                    )
                if (
                    type(value.provider_content_untrusted) is not bool
                    or value.provider_content_untrusted is not True
                    or type(value.items) is not tuple
                    or type(value.has_more) is not bool
                ):
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google read projection contract drifted"
                    )
                receipt = self._validate_receipt(
                    value.receipt,
                    operations=expected_operation,
                    statuses=frozenset({"complete"}),
                    expected_items=len(value.items),
                )
                after = self._status()
                if (
                    not after.connected
                    or after.scopes != READ_SCOPES
                    or before.anchor_generation != after.anchor_generation
                    or before.binding_digest != after.binding_digest
                    or before.reconciliation != after.reconciliation
                    or before.pending_loopback != after.pending_loopback
                ):
                    raise GoogleWorkspaceLiveV1UnknownOutcome(
                        "Google read post-verification failed"
                    )
                projected_items = _project_read_items(action, value.items)
                projected = _receipt_projection(receipt)
                receipt_digest = str(projected["receipt_digest"])
                generation_after = after.anchor_generation
                status_digest = _status_digest(after)
                item_count = len(projected_items)
                page_count = receipt.page_count
                response = {
                    "schema": "OnyxGoogleWorkspaceReadResult.v1",
                    "status": "succeeded",
                    "action": action,
                    "items": [dict(item) for item in projected_items],
                    "has_more": value.has_more,
                    "receipt": projected,
                    "external_dispatch": True,
                    "provider_read_only": True,
                    "postverified": True,
                }
                projection_digest = _canonical_digest(
                    {
                        "items": response["items"],
                        "has_more": response["has_more"],
                        "provider_response_digest": receipt.response_digest,
                    }
                )
                response["projection_digest"] = projection_digest
                ended_state = started_state
                result_digest = _canonical_digest(
                    {
                        "items": response["items"],
                        "has_more": response["has_more"],
                        "receipt_digest": receipt_digest,
                        "provider_response_digest": receipt.response_digest,
                        "projection_digest": projection_digest,
                    }
                )
            completion = "succeeded"
        except _UNKNOWN_EXCEPTIONS:
            completion = "attempted_unknown" if provider_attempted else "denied"
            pending_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace request failed closed"
                )
            )
        except _HOST_DENIED_EXCEPTIONS:
            completion = "denied"
            pending_error = GoogleWorkspaceLiveV1Denied(
                "Google Workspace request was denied"
            )
        except _DENIED_EXCEPTIONS:
            completion = "attempted_unknown" if provider_attempted else "denied"
            pending_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace request was denied"
                )
            )
        except GoogleWorkspaceLiveV1UnknownOutcome:
            completion = "attempted_unknown" if provider_attempted else "denied"
            pending_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace request failed closed"
                )
            )
        except (GoogleWorkspaceLiveV1ContractError, GoogleWorkspaceLiveV1Denied):
            completion = "attempted_unknown" if provider_attempted else "denied"
            pending_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace request was denied"
                )
            )
        except Exception:
            completion = "attempted_unknown" if provider_attempted else "denied"
            pending_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace request failed closed"
                )
            )
        audit_error: BaseException | None = None
        if response is not None and pending_error is None:
            replay_payload = response
            if action in {"list_gmail_messages", "list_calendar_events"}:
                # Durable idempotency must not turn the audit database into a
                # second mailbox/calendar store.  Persist only the bounded
                # projection proof; a replay remains deterministic and
                # explicitly redacted rather than re-dispatching the provider.
                replay_payload = {
                    "schema": "OnyxGoogleWorkspaceReadReplay.v1",
                    "status": "succeeded",
                    "action": action,
                    "replayed": True,
                    "item_count": item_count,
                    "page_count": page_count,
                    "has_more": response["has_more"],
                    "projection_digest": response["projection_digest"],
                    "receipt": response["receipt"],
                    "external_dispatch": False,
                    "provider_read_only": True,
                    "postverified": True,
                }
            result_record = {"kind": "response", "payload": replay_payload}
        else:
            result_record = {
                "kind": (
                    "unknown"
                    if completion == "attempted_unknown"
                    else "denied"
                )
            }
        try:
            self._audit_once(
                action=action,
                arguments=validated,
                trace_id=trace_id,
                started_state=started_state,
                ended_state=ended_state,
                provider_attempted=provider_attempted,
                completion=completion,
                receipt_digest=receipt_digest,
                result_digest=result_digest,
                status_digest=status_digest,
                decision=decision,
                proof=proof,
                idempotency_key=selected_idempotency,
                item_count=item_count,
                page_count=page_count,
                generation_before=generation_before,
                generation_after=generation_after,
                result_record=result_record,
            )
        except Exception:
            audit_error = (
                GoogleWorkspaceLiveV1UnknownOutcome(
                    "Google Workspace audit outcome requires reconciliation"
                )
                if provider_attempted
                else GoogleWorkspaceLiveV1Denied(
                    "Google Workspace audit failed closed"
                )
            )
        if audit_error is not None:
            raise audit_error from None
        if pending_error is not None:
            raise pending_error from None
        assert response is not None
        return response


__all__ = [
    "ACTIONS",
    "CONSEQUENTIAL_ACTIONS",
    "GoogleWorkspaceAuditIdentityV1",
    "GoogleWorkspaceLiveAdapterV1",
    "GoogleWorkspaceLiveV1ContractError",
    "GoogleWorkspaceLiveV1Denied",
    "GoogleWorkspaceLiveV1Error",
    "GoogleWorkspaceLiveV1UnknownOutcome",
    "READ_ACTIONS",
    "TOOL_NAME",
    "pseudonymize_live_identity_v1",
    "idempotency_digest_v1",
    "tool_declaration_google_workspace_v1",
    "validate_google_workspace_arguments_v1",
]
