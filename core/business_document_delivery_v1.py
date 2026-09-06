"""Owner-terminal delivery of ledger-backed Onyx business PDFs.

Run ``python -m core.business_document_delivery_v1 --help``. Preview/send/reconcile select
an existing deals output directory and generation request ID, never arbitrary
PDF bytes or a model-supplied account object. All Telegram scope arguments are
mandatory. Send/reconcile additionally require --enable-telegram and a current
TTY confirmation of the displayed request. There is no --yes or token input.

The local deals ledger is provenance within the owner's filesystem trust
boundary, not a signed proof against an attacker who can rewrite that ledger.
Native vault access uses the snapshot's NativeSecretVault.get_bytes API (there
is no native_vault.read_secret function). This module never creates credentials.

Status is read-only and provider-free. Reconciliation is an explicit owner
attestation based on independently checked evidence, never an automatic resend.
The existing outbox may refuse reconciliation until an abandoned lease expires.
Exit codes: 0 preview/status/accepted/reconciled; 2 denied/invalid; 3 unresolved
or failed delivery; 130 cancelled (inspect status if dispatch had started).
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import re
import signal
import sqlite3
import stat
import sys
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from core import native_vault
from core.telegram_official_connector_v1 import (
    StdlibTelegramTransportV1,
    TelegramAccountV1,
    TelegramCancellationV1,
    TelegramDenied,
    TelegramDispatchV1,
    TelegramDocumentV1,
    TelegramFeatureGateV1,
    TelegramOfficialOutboxV1,
    TelegramReconciliationDecisionV1,
    TelegramReconciliationProofV1,
    prepare_telegram_document_v1,
    telegram_vault_reference_v1,
)


APPROVAL_SECONDS = 120.0
MAX_LEDGER_BYTES = 32 * 1024 * 1024
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{2,191}\Z")
_NUMBER = re.compile(r"(?:INV|QUO|PRO)-[0-9]{4}-[0-9]{5,10}\Z")
_STATES = {
    "reserved",
    "dispatching",
    "accepted",
    "rejected",
    "not_dispatched",
    "reconciliation",
}


class DeliveryDenied(ValueError):
    """Fixed, content-free CLI diagnostics."""


def _checked_path(
    path: Path, *, directory: bool = False, missing: bool = False
) -> Path:
    raw = str(path)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or "\x00" in raw
        or raw.startswith(("//", "\\\\"))
        or ":" in raw[len(path.drive) :]
        or path == Path(path.anchor)
    ):
        raise DeliveryDenied("local_absolute_scoped_path_required")
    for candidate in (*reversed(path.parents), path):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            if candidate == path and missing and not directory:
                continue
            raise DeliveryDenied("local_path_unavailable") from None
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DeliveryDenied("linked_or_reparse_path_denied")
        is_directory = candidate != path or directory
        if not (
            stat.S_ISDIR(info.st_mode) if is_directory else stat.S_ISREG(info.st_mode)
        ):
            raise DeliveryDenied("local_path_type_invalid")
        if not is_directory and info.st_nlink != 1:
            raise DeliveryDenied("hardlinked_storage_denied")
    return path


def _database_path(path: Path, *, missing: bool = False) -> Path:
    _checked_path(path, missing=missing)
    if path.exists() and path.stat().st_size > MAX_LEDGER_BYTES:
        raise DeliveryDenied("ledger_budget_exceeded")
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(path) + suffix)
        _checked_path(sidecar, missing=True)
        if sidecar.exists() and sidecar.stat().st_size > MAX_LEDGER_BYTES:
            raise DeliveryDenied("ledger_budget_exceeded")
    return path


@contextmanager
def _read_database(path: Path):
    _database_path(path)
    before = path.stat()
    with closing(
        sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2)
    ) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA trusted_schema=OFF")
        # Bound work even for a damaged/hostile owner-selected local database.
        remaining = [2000]

        def progress():
            remaining[0] -= 1
            return int(remaining[0] <= 0)

        db.set_progress_handler(progress, 1000)
        yield db
        _database_path(path)
        after = path.stat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise DeliveryDenied("ledger_replaced_during_read")


@dataclass(frozen=True, slots=True)
class GeneratedDeliveryV1:
    document: TelegramDocumentV1
    generation_digest: str
    number: str

    def preview(self) -> dict[str, object]:
        item = self.document
        return {
            "status": "preview",
            "provider_contacted": False,
            "number": self.number,
            "operation_id": item.operation_id,
            "owner": item.owner_profile_id,
            "workspace": item.workspace_id,
            "account": item.account_id,
            "chat": item.chat_id,
            "filename": item.filename,
            "size_bytes": len(item.content),
            "pdf_sha256": item.content_digest,
            "request_digest": item.request_digest,
        }


def prepare_generated_delivery_v1(
    *,
    output_dir: Path,
    request_id: str,
    operation_id: str,
    account: TelegramAccountV1,
) -> GeneratedDeliveryV1:
    """Authenticate number/path/bytes against deals_v1's existing generated row."""
    if (
        type(request_id) is not str
        or not request_id.strip()
        or len(request_id) > 120
        or any(ord(char) < 32 for char in request_id)
    ):
        raise DeliveryDenied("generation_request_id_invalid")
    if type(account) is not TelegramAccountV1 or len(account.allowed_chat_ids) != 1:
        raise DeliveryDenied("one_exact_owner_chat_required")
    root = _checked_path(output_dir, directory=True)
    with _read_database(root / "onyx-deals.sqlite3") as db:
        columns = db.execute("PRAGMA table_info(documents)").fetchall()
        if [row["name"] for row in columns] != [
            "request_id",
            "digest",
            "number",
            "status",
            "pdf_digest",
        ]:
            raise DeliveryDenied("generated_ledger_schema_invalid")
        kind = db.execute(
            "SELECT type FROM sqlite_master WHERE name='documents'"
        ).fetchone()
        if kind is None or kind[0] != "table":
            raise DeliveryDenied("generated_ledger_schema_invalid")
        row = db.execute(
            "SELECT digest,number,status,pdf_digest FROM documents WHERE request_id=?",
            (request_id,),
        ).fetchone()
        if row is None or row["status"] != "generated":
            raise DeliveryDenied("generated_document_unavailable")
        if (
            type(row["number"]) is not str
            or _NUMBER.fullmatch(row["number"]) is None
            or any(
                type(row[key]) is not str or _DIGEST.fullmatch(row[key]) is None
                for key in ("digest", "pdf_digest")
            )
        ):
            raise DeliveryDenied("generated_document_binding_invalid")
        document = prepare_telegram_document_v1(
            operation_id=operation_id,
            account=account,
            chat_id=account.allowed_chat_ids[0],
            pdf_path=root / (row["number"] + ".pdf"),
            allowed_root=root,
            expected_content_digest=row["pdf_digest"],
        )
    return GeneratedDeliveryV1(document, row["digest"], row["number"])


def read_delivery_status_v1(
    path: Path,
    *,
    operation_id: str,
    account: TelegramAccountV1,
) -> TelegramDispatchV1 | None:
    """Read exact scope without creating, migrating, or recovering an outbox."""
    if _ID.fullmatch(operation_id) is None:
        raise DeliveryDenied("operation_id_invalid")
    _database_path(path, missing=True)
    if not path.exists():
        return None
    with _read_database(path) as db:
        if (
            db.execute("PRAGMA user_version").fetchone()[0]
            != TelegramOfficialOutboxV1._SCHEMA_VERSION
        ):
            raise DeliveryDenied("outbox_schema_requires_separate_migration")
        TelegramOfficialOutboxV1._validate_schema_signature(
            db, TelegramOfficialOutboxV1._DDL
        )
        TelegramOfficialOutboxV1._validate_event_chain(db)
        row = db.execute(
            "SELECT * FROM messages WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if row is None:
            return None
        if (
            row["owner_profile_id"],
            row["workspace_id"],
            row["account_id"],
            row["chat_id"],
        ) != (
            account.owner_profile_id,
            account.workspace_id,
            account.account_id,
            account.allowed_chat_ids[0],
        ):
            raise DeliveryDenied("outbox_scope_mismatch")
        if (
            row["status"] not in _STATES
            or any(
                type(row[key]) is not str or _DIGEST.fullmatch(row[key]) is None
                for key in ("request_digest", "content_digest")
            )
            or (
                row["provider_message_id"] is not None
                and re.fullmatch(r"[1-9][0-9]{0,15}", str(row["provider_message_id"]))
                is None
            )
        ):
            raise DeliveryDenied("outbox_receipt_invalid")
        # Never echo arbitrary stored detail strings to the terminal.
        return TelegramDispatchV1(
            operation_id,
            row["status"],
            row["request_digest"],
            row["content_digest"],
            row["provider_message_id"],
            "local_outbox_status",
        )


class OwnerTerminalV1:
    """Inject streams for offline tests; the real CLI uses process stdin/stdout."""

    def __init__(self, stdin: TextIO | None = None, stdout: TextIO | None = None):
        self.stdin = sys.stdin if stdin is None else stdin
        self.stdout = sys.stdout if stdout is None else stdout

    def is_tty(self) -> bool:
        return self.stdin.isatty() is True and self.stdout.isatty() is True

    def emit(self, payload: dict[str, object]) -> None:
        print(
            json.dumps(payload, sort_keys=True, ensure_ascii=True),
            file=self.stdout,
            flush=True,
        )

    def confirm(self, phrase: str) -> bool:
        if not self.is_tty():
            raise DeliveryDenied("interactive_owner_tty_required")
        self.emit(
            {"confirmation_required": phrase, "expires_in_seconds": APPROVAL_SECONDS}
        )
        line = self.stdin.readline(1024)
        return line.rstrip("\r\n") == phrase


class _OwnerApproval:
    """Short-lived, one-request authority minted only inside the TTY CLI flow."""

    def __init__(
        self, account, digest, action, terminal, cancellation, clock, deadline, verify
    ):
        self.scope = (
            account.owner_profile_id,
            account.workspace_id,
            action,
            account.account_id,
            account.allowed_chat_ids[0],
        )
        self.digest = digest
        self.terminal = terminal
        self.cancellation = cancellation
        self.clock = clock
        self.deadline = deadline
        self.verify = verify
        self.revoked = False

    def active(self):
        now = self.clock()
        return (
            not self.revoked
            and not self.cancellation.cancelled
            and self.terminal.is_tty()
            and math.isfinite(now)
            and now < self.deadline
        )

    def authority(self, owner, workspace, action, account, chat):
        return self.active() and (owner, workspace, action, account, chat) == self.scope

    def owner_approval(self, digest):
        return (
            self.active()
            and digest == self.digest
            and self.verify() is True
            and self.active()
        )

    def revoke(self):
        self.revoked = True


@contextmanager
def _wire_cancellation(cancellation):
    # During a bounded HTTP call, SIGINT cancels the operation without escaping
    # the outbox's receipt handling. Post-dispatch cancellation stays uncertain.
    previous = None
    if threading.current_thread() is threading.main_thread():
        previous = signal.getsignal(signal.SIGINT)

        def cancel(_signal, _frame):
            cancellation.cancel()

        signal.signal(signal.SIGINT, cancel)
    try:
        yield
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)


def _receipt_payload(receipt, operation_id):
    if receipt is None:
        return {
            "operation_id": operation_id,
            "status": "unavailable",
            "provider_accepted": False,
        }
    return {
        "operation_id": receipt.operation_id,
        "status": receipt.status,
        "request_digest": receipt.request_digest,
        "pdf_sha256": receipt.content_digest,
        "provider_message_id": receipt.provider_message_id,
        "provider_accepted": receipt.status == "accepted",
        "automatic_retry": False,
    }


def _parser():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "send", "status", "reconcile"):
        command = commands.add_parser(name, allow_abbrev=False)
        for flag in ("owner", "workspace", "account", "chat", "operation-id"):
            command.add_argument("--" + flag, required=True)
        if name in {"preview", "send", "reconcile"}:
            command.add_argument("--output-dir", type=Path, required=True)
            command.add_argument(
                "--request-id",
                required=True,
                help="Existing deals generation request ID",
            )
        if name != "preview":
            command.add_argument("--outbox", type=Path, required=True)
        if name in {"send", "reconcile"}:
            command.add_argument(
                "--enable-telegram",
                action="store_true",
                help="Explicit connector opt-in for this invocation only",
            )
        if name == "reconcile":
            command.add_argument(
                "--decision",
                choices=[item.value for item in TelegramReconciliationDecisionV1],
                required=True,
            )
            command.add_argument("--provider-message-id")
    return parser


def cli(
    argv=None,
    *,
    terminal=None,
    connection_factory=None,
    cancellation=None,
    clock=time.monotonic,
):
    """Owner entrypoint. Test seams replace I/O, never the hardened transport."""
    args = _parser().parse_args(argv)
    terminal = OwnerTerminalV1() if terminal is None else terminal
    cancellation = TelegramCancellationV1() if cancellation is None else cancellation
    approval = None
    box = None
    try:
        if (
            type(terminal) is not OwnerTerminalV1
            or type(cancellation) is not TelegramCancellationV1
        ):
            raise DeliveryDenied("cli_dependencies_invalid")
        if _ID.fullmatch(args.operation_id) is None:
            raise DeliveryDenied("operation_id_invalid")
        account = TelegramAccountV1(
            args.account,
            args.owner,
            args.workspace,
            telegram_vault_reference_v1(args.owner, args.workspace, args.account),
            (args.chat,),
        )
        if args.command == "status":
            result = read_delivery_status_v1(
                args.outbox, operation_id=args.operation_id, account=account
            )
            terminal.emit(_receipt_payload(result, args.operation_id))
            return 0
        if args.command in {"send", "reconcile"}:
            if not args.enable_telegram:
                raise DeliveryDenied("explicit_telegram_opt_in_required")
            if not terminal.is_tty():
                raise DeliveryDenied("interactive_owner_tty_required")
            prior = read_delivery_status_v1(
                args.outbox, operation_id=args.operation_id, account=account
            )
        if args.command in {"preview", "send"}:
            prepared = prepare_generated_delivery_v1(
                output_dir=args.output_dir,
                request_id=args.request_id,
                operation_id=args.operation_id,
                account=account,
            )
            terminal.emit(prepared.preview())
            if args.command == "preview":
                return 0
            if (
                prior is not None
                and prior.request_digest != prepared.document.request_digest
            ):
                raise DeliveryDenied("outbox_request_mismatch")
            if args.outbox == args.output_dir / "onyx-deals.sqlite3":
                raise DeliveryDenied("separate_delivery_outbox_required")
            digest = prepared.document.request_digest
            phrase = f"SEND {digest} TO {args.chat}"
            action = "official_message.send"

            def verify():
                current = prepare_generated_delivery_v1(
                    output_dir=args.output_dir,
                    request_id=args.request_id,
                    operation_id=args.operation_id,
                    account=account,
                )
                _database_path(args.outbox, missing=True)
                return current == prepared
        else:
            if prior is None or prior.status != "reconciliation":
                raise DeliveryDenied("operation_not_ready_for_reconciliation")
            prepared = prepare_generated_delivery_v1(
                output_dir=args.output_dir,
                request_id=args.request_id,
                operation_id=args.operation_id,
                account=account,
            )
            if prior.request_digest != prepared.document.request_digest:
                raise DeliveryDenied("outbox_request_mismatch")
            proof = TelegramReconciliationProofV1(
                args.operation_id,
                TelegramReconciliationDecisionV1(args.decision),
                args.chat,
                prior.content_digest,
                args.provider_message_id,
            )
            attestation = {
                "request_digest": prior.request_digest,
                "decision": args.decision,
                "provider_message_id": proof.provider_message_id,
            }
            digest = hashlib.sha256(
                json.dumps(attestation, sort_keys=True).encode()
            ).hexdigest()
            terminal.emit(
                {
                    **_receipt_payload(prior, args.operation_id),
                    **attestation,
                    "owner": args.owner,
                    "workspace": args.workspace,
                    "account": args.account,
                    "chat": args.chat,
                    "number": prepared.number,
                    "reconciliation_digest": digest,
                    "evidence_required": "Independently verify this outcome; this command does not contact Telegram.",
                }
            )
            phrase = f"RECONCILE {digest} TO {args.chat}"
            action = "official_message.reconcile"

            def verify():
                current = prepare_generated_delivery_v1(
                    output_dir=args.output_dir,
                    request_id=args.request_id,
                    operation_id=args.operation_id,
                    account=account,
                )
                return (
                    current == prepared
                    and read_delivery_status_v1(
                        args.outbox, operation_id=args.operation_id, account=account
                    )
                    == prior
                )

        deadline = clock() + APPROVAL_SECONDS
        if not terminal.confirm(phrase):
            raise DeliveryDenied("exact_owner_consent_denied")
        approval = _OwnerApproval(
            account, digest, action, terminal, cancellation, clock, deadline, verify
        )
        if not approval.owner_approval(digest):
            raise DeliveryDenied("owner_approval_expired_cancelled_or_changed")
        box = TelegramOfficialOutboxV1(
            args.outbox, gate=TelegramFeatureGateV1(args.enable_telegram)
        )
        with _wire_cancellation(cancellation):
            if args.command == "send":
                reference = account.secret_reference

                def read_secret(requested_reference):
                    if requested_reference != reference or not approval.owner_approval(
                        digest
                    ):
                        raise TelegramDenied("exact_owner_vault_scope_denied")
                    return native_vault.NativeSecretVault(reference).get_bytes()

                transport = StdlibTelegramTransportV1(
                    vault_reader=read_secret,
                    connection_factory=http.client.HTTPSConnection
                    if connection_factory is None
                    else connection_factory,
                )
                result = box.send_document(
                    document=prepared.document,
                    account=account,
                    authority=approval.authority,
                    owner_approval=approval.owner_approval,
                    transport=transport,
                    cancellation=cancellation,
                )
            else:
                # Reconciliation's central-authority callback also binds the
                # exact still-current receipt and the approved decision digest.
                def reconciliation_authority(*scope):
                    return approval.authority(*scope) and approval.owner_approval(
                        digest
                    )

                result = box.reconcile(proof, authority=reconciliation_authority)
        terminal.emit(_receipt_payload(result, args.operation_id))
        return 0 if args.command == "reconcile" or result.status == "accepted" else 3
    except KeyboardInterrupt:
        cancellation.cancel()
        terminal.emit(
            {
                "status": "cancelled",
                "inspect_outbox_status": True,
                "automatic_retry": False,
            }
        )
        return 130
    except Exception as exc:
        # Provider/local exceptions may contain tokens, paths or business data.
        reason = (
            str(exc)
            if type(exc) is DeliveryDenied
            else "delivery_validation_or_storage_failed"
        )
        terminal.emit({"status": "denied", "reason": reason, "automatic_retry": False})
        return 2
    finally:
        if approval is not None:
            approval.revoke()
        if box is not None:
            box.close()


if __name__ == "__main__":
    raise SystemExit(cli())
