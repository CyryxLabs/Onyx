"""Enabled-only durable audit and idempotency authority for Google Workspace."""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final


_DIGEST: Final = frozenset("0123456789abcdef")
_ACTIONS: Final = frozenset(
    {
        "invalid",
        "status",
        "connect",
        "disconnect",
        "list_gmail_messages",
        "list_calendar_events",
    }
)
_STATES: Final = frozenset(
    {
        "not-opened",
        "unknown",
        "connected",
        "disconnected",
        "revoked",
        "attempted_unknown",
        "denied",
    }
)
_COMPLETIONS: Final = frozenset(
    {"succeeded", "denied", "attempted_unknown"}
)
_FINAL_STATES: Final = frozenset(
    {"completed", "denied", "unknown"}
)


class GoogleWorkspaceAuditV1Error(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceClaimV1:
    state: str
    result: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceAuditReferenceV1:
    trace_id: str
    event_hash: str


def _is_digest(value: object) -> bool:
    return bool(
        type(value) is str
        and len(value) == 64
        and set(value).issubset(_DIGEST)
    )


def _canonical(value: object) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError):
        raise GoogleWorkspaceAuditV1Error(
            "Google Workspace audit value is not canonical"
        ) from None


def _contract(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != {
        "contract",
        "trace_id",
        "identity",
        "operation",
        "decision",
        "outcome",
    }:
        raise GoogleWorkspaceAuditV1Error(
            "Google Workspace audit contract is invalid"
        )
    identity = value.get("identity")
    operation = value.get("operation")
    decision = value.get("decision")
    outcome = value.get("outcome")
    trace_id = value.get("trace_id")
    if (
        value.get("contract") != "OnyxGoogleWorkspaceAudit.v1"
        or type(trace_id) is not str
        or not trace_id
        or len(trace_id) > 64
        or not trace_id.isascii()
        or not isinstance(identity, dict)
        or set(identity)
        != {
            "owner_pseudonym",
            "workspace_pseudonym",
            "account_pseudonym",
            "binding_digest",
        }
        or any(not _is_digest(item) for item in identity.values())
        or not isinstance(operation, dict)
        or set(operation)
        != {"action", "argument_digest", "idempotency_digest"}
        or operation.get("action") not in _ACTIONS
        or not _is_digest(operation.get("argument_digest"))
        or not _is_digest(operation.get("idempotency_digest"))
        or not isinstance(decision, dict)
        or set(decision) != {"class", "proof_digest"}
        or decision.get("class") not in {"allow", "deny"}
        or not _is_digest(decision.get("proof_digest"))
        or not isinstance(outcome, dict)
        or set(outcome)
        != {
            "start_state",
            "end_state",
            "provider_boundary",
            "completion",
            "receipt_digest",
            "result_digest",
            "item_count",
            "page_count",
            "generation_before",
            "generation_after",
            "external_dispatch",
            "status_digest",
        }
        or outcome.get("start_state") not in _STATES
        or outcome.get("end_state") not in _STATES
        or outcome.get("provider_boundary") not in {"not_reached", "may_execute"}
        or outcome.get("completion") not in _COMPLETIONS
        or any(
            not _is_digest(outcome.get(field))
            for field in ("receipt_digest", "result_digest", "status_digest")
        )
        or any(
            type(outcome.get(field)) is not int or outcome[field] < 0
            for field in ("item_count", "page_count")
        )
        or any(
            item is not None and (type(item) is not int or item < 0)
            for item in (
                outcome.get("generation_before"),
                outcome.get("generation_after"),
            )
        )
        or type(outcome.get("external_dispatch")) is not bool
    ):
        raise GoogleWorkspaceAuditV1Error(
            "Google Workspace audit contract is invalid"
        )
    return {
        "contract": "OnyxGoogleWorkspaceAudit.v1",
        "trace_id": trace_id,
        "identity": dict(identity),
        "operation": dict(operation),
        "decision": dict(decision),
        "outcome": dict(outcome),
    }


class GoogleWorkspaceAuditStoreV1:
    """One authenticated durable row per exact logical action identity."""

    def __init__(self, *, path: Path, authentication_key: bytes) -> None:
        if (
            not isinstance(path, Path)
            or not path.is_absolute()
            or type(authentication_key) is not bytes
            or len(authentication_key) != 32
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace audit store configuration is invalid"
            )
        self._path = path
        self._key = authentication_key
        self._lock = threading.RLock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS logical_actions_v2(
                  binding_digest TEXT NOT NULL,
                  idempotency_digest TEXT NOT NULL,
                  action TEXT NOT NULL,
                  argument_digest TEXT NOT NULL,
                  trace_id TEXT NOT NULL,
                  state TEXT NOT NULL CHECK(state IN ('pending','completed','denied','unknown')),
                  contract_json TEXT,
                  result_json TEXT,
                  event_hash TEXT,
                  PRIMARY KEY(binding_digest,idempotency_digest)
                ) WITHOUT ROWID;
                CREATE TRIGGER IF NOT EXISTS logical_actions_v2_final_immutable
                BEFORE UPDATE ON logical_actions_v2 WHEN OLD.state!='pending'
                BEGIN SELECT RAISE(ABORT,'final Google action is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS logical_actions_v2_no_delete
                BEFORE DELETE ON logical_actions_v2
                BEGIN SELECT RAISE(ABORT,'Google action is immutable'); END;
                CREATE TABLE IF NOT EXISTS denied_attempts_v1(
                  event_digest TEXT NOT NULL PRIMARY KEY,
                  binding_digest TEXT NOT NULL,
                  action TEXT NOT NULL,
                  argument_digest TEXT NOT NULL,
                  idempotency_digest TEXT NOT NULL,
                  trace_id TEXT NOT NULL,
                  proof_digest TEXT NOT NULL,
                  event_hash TEXT NOT NULL
                ) WITHOUT ROWID;
                CREATE TRIGGER IF NOT EXISTS denied_attempts_v1_no_update
                BEFORE UPDATE ON denied_attempts_v1
                BEGIN SELECT RAISE(ABORT,'denied Google attempt is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS denied_attempts_v1_no_delete
                BEFORE DELETE ON denied_attempts_v1
                BEGIN SELECT RAISE(ABORT,'denied Google attempt is immutable'); END;
                CREATE TABLE IF NOT EXISTS approved_attempts_v1(
                  event_digest TEXT NOT NULL PRIMARY KEY,
                  binding_digest TEXT NOT NULL,
                  action TEXT NOT NULL,
                  argument_digest TEXT NOT NULL,
                  idempotency_digest TEXT NOT NULL,
                  trace_id TEXT NOT NULL,
                  classification TEXT NOT NULL CHECK(classification IN ('fresh','replay')),
                  logical_event_hash TEXT NOT NULL,
                  result_digest TEXT NOT NULL,
                  event_hash TEXT NOT NULL
                ) WITHOUT ROWID;
                CREATE TRIGGER IF NOT EXISTS approved_attempts_v1_no_update
                BEFORE UPDATE ON approved_attempts_v1
                BEGIN SELECT RAISE(ABORT,'approved Google attempt is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS approved_attempts_v1_no_delete
                BEFORE DELETE ON approved_attempts_v1
                BEGIN SELECT RAISE(ABORT,'approved Google attempt is immutable'); END;
                """
            )
            self._validate_schema(database)
            database.execute(
                "UPDATE logical_actions_v2 SET state='unknown',contract_json=NULL,"
                "result_json=NULL,event_hash=NULL WHERE state='pending'"
            )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=FULL")
        database.execute("PRAGMA foreign_keys=ON")
        return database

    @staticmethod
    def _validate_schema(database: sqlite3.Connection) -> None:
        action_columns = tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in database.execute("PRAGMA table_info(logical_actions_v2)")
        )
        denied_columns = tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in database.execute("PRAGMA table_info(denied_attempts_v1)")
        )
        approved_columns = tuple(
            (str(row[1]), str(row[2]), int(row[3]), int(row[5]))
            for row in database.execute("PRAGMA table_info(approved_attempts_v1)")
        )
        if action_columns != (
            ("binding_digest", "TEXT", 1, 1),
            ("idempotency_digest", "TEXT", 1, 2),
            ("action", "TEXT", 1, 0),
            ("argument_digest", "TEXT", 1, 0),
            ("trace_id", "TEXT", 1, 0),
            ("state", "TEXT", 1, 0),
            ("contract_json", "TEXT", 0, 0),
            ("result_json", "TEXT", 0, 0),
            ("event_hash", "TEXT", 0, 0),
        ) or denied_columns != (
            ("event_digest", "TEXT", 1, 1),
            ("binding_digest", "TEXT", 1, 0),
            ("action", "TEXT", 1, 0),
            ("argument_digest", "TEXT", 1, 0),
            ("idempotency_digest", "TEXT", 1, 0),
            ("trace_id", "TEXT", 1, 0),
            ("proof_digest", "TEXT", 1, 0),
            ("event_hash", "TEXT", 1, 0),
        ) or approved_columns != (
            ("event_digest", "TEXT", 1, 1),
            ("binding_digest", "TEXT", 1, 0),
            ("action", "TEXT", 1, 0),
            ("argument_digest", "TEXT", 1, 0),
            ("idempotency_digest", "TEXT", 1, 0),
            ("trace_id", "TEXT", 1, 0),
            ("classification", "TEXT", 1, 0),
            ("logical_event_hash", "TEXT", 1, 0),
            ("result_digest", "TEXT", 1, 0),
            ("event_hash", "TEXT", 1, 0),
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace audit schema is invalid"
            )
        triggers = {
            str(row[0]): " ".join(str(row[1]).split()).casefold()
            for row in database.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' "
                "AND tbl_name IN ('logical_actions_v2','denied_attempts_v1',"
                "'approved_attempts_v1')"
            )
        }
        expected = {
            "logical_actions_v2_final_immutable": " ".join(
                """CREATE TRIGGER logical_actions_v2_final_immutable
                BEFORE UPDATE ON logical_actions_v2 WHEN OLD.state!='pending'
                BEGIN SELECT RAISE(ABORT,'final Google action is immutable'); END""".split()
            ).casefold(),
            "logical_actions_v2_no_delete": " ".join(
                """CREATE TRIGGER logical_actions_v2_no_delete
                BEFORE DELETE ON logical_actions_v2
                BEGIN SELECT RAISE(ABORT,'Google action is immutable'); END""".split()
            ).casefold(),
            "denied_attempts_v1_no_update": " ".join(
                """CREATE TRIGGER denied_attempts_v1_no_update
                BEFORE UPDATE ON denied_attempts_v1
                BEGIN SELECT RAISE(ABORT,'denied Google attempt is immutable'); END""".split()
            ).casefold(),
            "denied_attempts_v1_no_delete": " ".join(
                """CREATE TRIGGER denied_attempts_v1_no_delete
                BEFORE DELETE ON denied_attempts_v1
                BEGIN SELECT RAISE(ABORT,'denied Google attempt is immutable'); END""".split()
            ).casefold(),
            "approved_attempts_v1_no_update": " ".join(
                """CREATE TRIGGER approved_attempts_v1_no_update
                BEFORE UPDATE ON approved_attempts_v1
                BEGIN SELECT RAISE(ABORT,'approved Google attempt is immutable'); END""".split()
            ).casefold(),
            "approved_attempts_v1_no_delete": " ".join(
                """CREATE TRIGGER approved_attempts_v1_no_delete
                BEFORE DELETE ON approved_attempts_v1
                BEGIN SELECT RAISE(ABORT,'approved Google attempt is immutable'); END""".split()
            ).casefold(),
        }
        if triggers != expected:
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace audit schema is invalid"
            )

    def record_denied(
        self,
        *,
        binding_digest: str,
        action: str,
        argument_digest: str,
        idempotency_digest: str,
        trace_id: str,
        proof_digest: str,
    ) -> GoogleWorkspaceAuditReferenceV1:
        """Append one authenticated denial without reserving provider idempotency."""

        if (
            not _is_digest(binding_digest)
            or type(action) is not str
            or action not in _ACTIONS - {"invalid"}
            or not _is_digest(argument_digest)
            or not _is_digest(idempotency_digest)
            or type(trace_id) is not str
            or not trace_id
            or len(trace_id) > 64
            or not trace_id.isascii()
            or not _is_digest(proof_digest)
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace denied attempt is invalid"
            )
        logical = {
            "action": action,
            "argument_digest": argument_digest,
            "binding_digest": binding_digest,
            "idempotency_digest": idempotency_digest,
        }
        event_identity = {**logical, "trace_id": trace_id}
        event_digest = hashlib.sha256(
            _canonical(event_identity).encode("ascii")
        ).hexdigest()
        event = {
            "contract": "OnyxGoogleWorkspaceDeniedAttempt.v1",
            **logical,
            "event_digest": event_digest,
            "proof_digest": proof_digest,
            "trace_id": trace_id,
        }
        event_hash = hmac.new(
            self._key, _canonical(event).encode("ascii"), hashlib.sha256
        ).hexdigest()
        with self._lock, closing(self._connect()) as database:
            self._validate_schema(database)
            database.execute("BEGIN IMMEDIATE")
            database.execute(
                "INSERT OR IGNORE INTO denied_attempts_v1("
                "event_digest,binding_digest,action,argument_digest,"
                "idempotency_digest,trace_id,proof_digest,event_hash) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    event_digest,
                    binding_digest,
                    action,
                    argument_digest,
                    idempotency_digest,
                    trace_id,
                    proof_digest,
                    event_hash,
                ),
            )
            row = database.execute(
                "SELECT binding_digest,action,argument_digest,idempotency_digest,"
                "trace_id,proof_digest,event_hash FROM denied_attempts_v1 "
                "WHERE event_digest=?",
                (event_digest,),
            ).fetchone()
            database.execute("COMMIT")
        if row is None or len(row) != 7:
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace denied attempt is unavailable"
            )
        (
            stored_binding,
            stored_action,
            stored_argument,
            stored_idempotency,
            stored_trace,
            stored_proof,
            stored_hash,
        ) = (str(item) for item in row)
        stored_logical = {
            "action": stored_action,
            "argument_digest": stored_argument,
            "binding_digest": stored_binding,
            "idempotency_digest": stored_idempotency,
        }
        stored_event = {
            "contract": "OnyxGoogleWorkspaceDeniedAttempt.v1",
            **stored_logical,
            "event_digest": event_digest,
            "proof_digest": stored_proof,
            "trace_id": stored_trace,
        }
        expected_hash = hmac.new(
            self._key, _canonical(stored_event).encode("ascii"), hashlib.sha256
        ).hexdigest()
        if (
            stored_logical != logical
            or stored_trace != trace_id
            or not _is_digest(stored_proof)
            or not _is_digest(stored_hash)
            or not hmac.compare_digest(expected_hash, stored_hash)
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace denied attempt drifted"
            )
        return GoogleWorkspaceAuditReferenceV1(trace_id, stored_hash)

    def _append_approved_attempt(
        self,
        database: sqlite3.Connection,
        *,
        binding_digest: str,
        action: str,
        argument_digest: str,
        idempotency_digest: str,
        trace_id: str,
        classification: str,
        logical_event_hash: str,
        encoded_result: str,
    ) -> GoogleWorkspaceAuditReferenceV1:
        if (
            not _is_digest(binding_digest)
            or type(action) is not str
            or action not in _ACTIONS - {"invalid"}
            or not _is_digest(argument_digest)
            or not _is_digest(idempotency_digest)
            or type(trace_id) is not str
            or not trace_id
            or len(trace_id) > 64
            or not trace_id.isascii()
            or type(classification) is not str
            or classification not in {"fresh", "replay"}
            or not _is_digest(logical_event_hash)
            or type(encoded_result) is not str
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace approved attempt is invalid"
            )
        result_digest = hashlib.sha256(encoded_result.encode("ascii")).hexdigest()
        identity = {
            "action": action,
            "argument_digest": argument_digest,
            "binding_digest": binding_digest,
            "idempotency_digest": idempotency_digest,
            "trace_id": trace_id,
        }
        event_digest = hashlib.sha256(
            _canonical(identity).encode("ascii")
        ).hexdigest()
        event = {
            "contract": "OnyxGoogleWorkspaceApprovedAttempt.v1",
            **identity,
            "classification": classification,
            "event_digest": event_digest,
            "logical_event_hash": logical_event_hash,
            "result_digest": result_digest,
        }
        event_hash = hmac.new(
            self._key, _canonical(event).encode("ascii"), hashlib.sha256
        ).hexdigest()
        database.execute(
            "INSERT OR IGNORE INTO approved_attempts_v1("
            "event_digest,binding_digest,action,argument_digest,"
            "idempotency_digest,trace_id,classification,logical_event_hash,"
            "result_digest,event_hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                event_digest,
                binding_digest,
                action,
                argument_digest,
                idempotency_digest,
                trace_id,
                classification,
                logical_event_hash,
                result_digest,
                event_hash,
            ),
        )
        row = database.execute(
            "SELECT binding_digest,action,argument_digest,idempotency_digest,"
            "trace_id,classification,logical_event_hash,result_digest,event_hash "
            "FROM approved_attempts_v1 WHERE event_digest=?",
            (event_digest,),
        ).fetchone()
        if row is None or len(row) != 9:
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace approved attempt is unavailable"
            )
        (
            stored_binding,
            stored_action,
            stored_argument,
            stored_idempotency,
            stored_trace,
            stored_classification,
            stored_logical_hash,
            stored_result_digest,
            stored_event_hash,
        ) = (str(item) for item in row)
        stored_identity = {
            "action": stored_action,
            "argument_digest": stored_argument,
            "binding_digest": stored_binding,
            "idempotency_digest": stored_idempotency,
            "trace_id": stored_trace,
        }
        stored_event = {
            "contract": "OnyxGoogleWorkspaceApprovedAttempt.v1",
            **stored_identity,
            "classification": stored_classification,
            "event_digest": event_digest,
            "logical_event_hash": stored_logical_hash,
            "result_digest": stored_result_digest,
        }
        expected_hash = hmac.new(
            self._key,
            _canonical(stored_event).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if (
            stored_identity != identity
            or stored_classification != classification
            or stored_logical_hash != logical_event_hash
            or stored_result_digest != result_digest
            or not _is_digest(stored_event_hash)
            or not hmac.compare_digest(expected_hash, stored_event_hash)
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace approved attempt drifted"
            )
        return GoogleWorkspaceAuditReferenceV1(trace_id, stored_event_hash)

    def reserve(
        self,
        *,
        binding_digest: str,
        action: str,
        argument_digest: str,
        idempotency_digest: str,
        trace_id: str,
    ) -> GoogleWorkspaceClaimV1:
        if (
            not _is_digest(binding_digest)
            or type(action) is not str
            or action not in _ACTIONS - {"invalid"}
            or not _is_digest(argument_digest)
            or not _is_digest(idempotency_digest)
            or type(trace_id) is not str
            or not trace_id
            or len(trace_id) > 64
            or not trace_id.isascii()
        ):
            raise GoogleWorkspaceAuditV1Error(
                "Google Workspace idempotency claim is invalid"
            )
        with self._lock, closing(self._connect()) as database:
            try:
                self._validate_schema(database)
            except BaseException:
                return GoogleWorkspaceClaimV1("unknown")
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT state,action,argument_digest,contract_json,result_json,"
                "event_hash FROM logical_actions_v2 "
                "WHERE binding_digest=? AND idempotency_digest=?",
                (binding_digest, idempotency_digest),
            ).fetchone()
            if row is None:
                database.execute(
                    "INSERT INTO logical_actions_v2(binding_digest,idempotency_digest,"
                    "action,argument_digest,trace_id,state) "
                    "VALUES(?,?,?,?,?,'pending')",
                    (
                        binding_digest,
                        idempotency_digest,
                        action,
                        argument_digest,
                        trace_id,
                    ),
                )
                database.execute("COMMIT")
                return GoogleWorkspaceClaimV1("claimed")
            database.execute("COMMIT")
            state, stored_action, stored_argument, encoded_contract, encoded_result, event_hash = (
                None if item is None else str(item) for item in row
            )
            if stored_action != action or stored_argument != argument_digest:
                return GoogleWorkspaceClaimV1("unknown")
            if state in {"pending", "unknown"}:
                return GoogleWorkspaceClaimV1("unknown")
            if (
                state not in {"completed", "denied"}
                or encoded_contract is None
                or encoded_result is None
                or event_hash is None
                or not _is_digest(event_hash)
            ):
                return GoogleWorkspaceClaimV1("unknown")
            try:
                raw_contract = json.loads(encoded_contract)
                result = json.loads(encoded_result)
                normalized = _contract(raw_contract)
                operation = normalized["operation"]
                identity = normalized["identity"]
                outcome = normalized["outcome"]
                assert isinstance(operation, dict)
                assert isinstance(identity, dict)
                assert isinstance(outcome, dict)
                canonical_contract = _canonical(normalized)
                canonical_result = _canonical(result)
                expected_hash = hmac.new(
                    self._key,
                    (canonical_contract + "\0" + canonical_result).encode("ascii"),
                    hashlib.sha256,
                ).hexdigest()
                payload = result.get("payload") if type(result) is dict else None
                expected_schemas = {
                    "status": {"OnyxGoogleWorkspaceStatus.v1"},
                    "connect": {"OnyxGoogleWorkspaceCommand.v1"},
                    "disconnect": {"OnyxGoogleWorkspaceCommand.v1"},
                    "list_gmail_messages": {"OnyxGoogleWorkspaceReadReplay.v1"},
                    "list_calendar_events": {"OnyxGoogleWorkspaceReadReplay.v1"},
                }
                replay_valid = (
                    type(result) is dict
                    and (
                        (
                            state == "completed"
                            and set(result) == {"kind", "payload"}
                            and result.get("kind") == "response"
                            and type(payload) is dict
                            and payload.get("schema") in expected_schemas[action]
                            and payload.get("action") == action
                            and outcome.get("completion") == "succeeded"
                        )
                        or (
                            state == "denied"
                            and result == {"kind": "denied"}
                            and outcome.get("completion") == "denied"
                        )
                    )
                )
                if (
                    encoded_contract != canonical_contract
                    or encoded_result != canonical_result
                    or identity.get("binding_digest") != binding_digest
                    or operation.get("action") != action
                    or operation.get("argument_digest") != argument_digest
                    or operation.get("idempotency_digest") != idempotency_digest
                    or not replay_valid
                    or not hmac.compare_digest(expected_hash, event_hash)
                ):
                    return GoogleWorkspaceClaimV1("unknown")
            except BaseException:
                return GoogleWorkspaceClaimV1("unknown")
            try:
                database.execute("BEGIN IMMEDIATE")
                self._append_approved_attempt(
                    database,
                    binding_digest=binding_digest,
                    action=action,
                    argument_digest=argument_digest,
                    idempotency_digest=idempotency_digest,
                    trace_id=trace_id,
                    classification="replay",
                    logical_event_hash=event_hash,
                    encoded_result=encoded_result,
                )
                database.execute("COMMIT")
            except BaseException:
                if database.in_transaction:
                    database.execute("ROLLBACK")
                return GoogleWorkspaceClaimV1("unknown")
            return GoogleWorkspaceClaimV1(state, result)

    def finalize(
        self, *, contract: object, result: dict[str, object]
    ) -> GoogleWorkspaceAuditReferenceV1:
        normalized = _contract(contract)
        operation = normalized["operation"]
        identity = normalized["identity"]
        outcome = normalized["outcome"]
        assert isinstance(operation, dict)
        assert isinstance(identity, dict)
        assert isinstance(outcome, dict)
        binding = str(identity["binding_digest"])
        idempotency = str(operation["idempotency_digest"])
        completion = str(outcome["completion"])
        state = {
            "succeeded": "completed",
            "denied": "denied",
            "attempted_unknown": "unknown",
        }[completion]
        encoded_contract = _canonical(normalized)
        encoded_result = _canonical(result)
        event_hash = hmac.new(
            self._key,
            (encoded_contract + "\0" + encoded_result).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        with self._lock, closing(self._connect()) as database:
            self._validate_schema(database)
            database.execute("BEGIN IMMEDIATE")
            row = database.execute(
                "SELECT state,contract_json,result_json,event_hash,trace_id "
                "FROM logical_actions_v2 WHERE binding_digest=? "
                "AND idempotency_digest=?",
                (binding, idempotency),
            ).fetchone()
            if row is None or str(row[0]) != "pending":
                database.execute("ROLLBACK")
                raise GoogleWorkspaceAuditV1Error(
                    "Google Workspace idempotency claim is not pending"
                )
            database.execute(
                "UPDATE logical_actions_v2 SET state=?,contract_json=?,result_json=?,"
                "event_hash=? WHERE binding_digest=? AND idempotency_digest=? "
                "AND action=? AND argument_digest=?",
                (
                    state,
                    encoded_contract,
                    encoded_result,
                    event_hash,
                    binding,
                    idempotency,
                    operation["action"],
                    operation["argument_digest"],
                ),
            )
            if database.execute("SELECT changes()").fetchone() != (1,):
                database.execute("ROLLBACK")
                raise GoogleWorkspaceAuditV1Error(
                    "Google Workspace idempotency binding drifted"
                )
            self._append_approved_attempt(
                database,
                binding_digest=binding,
                action=str(operation["action"]),
                argument_digest=str(operation["argument_digest"]),
                idempotency_digest=idempotency,
                trace_id=str(normalized["trace_id"]),
                classification="fresh",
                logical_event_hash=event_hash,
                encoded_result=encoded_result,
            )
            database.execute("COMMIT")
        return GoogleWorkspaceAuditReferenceV1(
            str(normalized["trace_id"]), event_hash
        )

    def verify(
        self, *, contract: object, result: dict[str, object], event_hash: str
    ) -> bool:
        normalized = _contract(contract)
        operation = normalized["operation"]
        identity = normalized["identity"]
        assert isinstance(operation, dict)
        assert isinstance(identity, dict)
        encoded_contract = _canonical(normalized)
        encoded_result = _canonical(result)
        expected = hmac.new(
            self._key,
            (encoded_contract + "\0" + encoded_result).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, event_hash):
            return False
        with self._lock, closing(self._connect()) as database:
            self._validate_schema(database)
            row = database.execute(
                "SELECT contract_json,result_json,event_hash FROM logical_actions_v2 "
                "WHERE binding_digest=? AND idempotency_digest=? "
                "AND action=? AND argument_digest=?",
                (
                    identity["binding_digest"],
                    operation["idempotency_digest"],
                    operation["action"],
                    operation["argument_digest"],
                ),
            ).fetchone()
            attempt = database.execute(
                "SELECT classification,logical_event_hash,result_digest,event_hash "
                "FROM approved_attempts_v1 WHERE binding_digest=? "
                "AND idempotency_digest=? AND action=? AND argument_digest=? "
                "AND trace_id=?",
                (
                    identity["binding_digest"],
                    operation["idempotency_digest"],
                    operation["action"],
                    operation["argument_digest"],
                    normalized["trace_id"],
                ),
            ).fetchone()
        result_digest = hashlib.sha256(encoded_result.encode("ascii")).hexdigest()
        if (
            row != (encoded_contract, encoded_result, event_hash)
            or attempt is None
            or tuple(str(item) for item in attempt[:3])
            != ("fresh", event_hash, result_digest)
            or not _is_digest(attempt[3])
        ):
            return False
        identity_event = {
            "action": operation["action"],
            "argument_digest": operation["argument_digest"],
            "binding_digest": identity["binding_digest"],
            "idempotency_digest": operation["idempotency_digest"],
            "trace_id": normalized["trace_id"],
        }
        event_digest = hashlib.sha256(
            _canonical(identity_event).encode("ascii")
        ).hexdigest()
        attempt_event = {
            "contract": "OnyxGoogleWorkspaceApprovedAttempt.v1",
            **identity_event,
            "classification": "fresh",
            "event_digest": event_digest,
            "logical_event_hash": event_hash,
            "result_digest": result_digest,
        }
        expected_attempt_hash = hmac.new(
            self._key,
            _canonical(attempt_event).encode("ascii"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected_attempt_hash, str(attempt[3]))

    def close(self) -> None:
        self._key = b"\0" * 32


__all__ = [
    "GoogleWorkspaceAuditReferenceV1",
    "GoogleWorkspaceAuditStoreV1",
    "GoogleWorkspaceAuditV1Error",
    "GoogleWorkspaceClaimV1",
]
