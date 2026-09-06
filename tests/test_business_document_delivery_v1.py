"""Real owner CLI + deals ledger + hardened transport, with offline I/O only."""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import sqlite3
import subprocess
import sys
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import business_document_delivery_v1 as delivery
from core import deals_v1 as deals
from core import native_vault
from core import telegram_official_connector_v1 as tg


CHAT = "-1001234567890"
TOKEN = b"123456789:AAExample_secret_token_1234567890"


def synthetic_pdf():
    # Small valid PDF, replacing only the browser renderer in deals.generate.
    stream = b"BT /F1 12 Tf 10 50 Td (Synthetic invoice) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 100] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = []
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return (
        result
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )


@pytest.fixture
def generated(tmp_path, monkeypatch):
    root = tmp_path / "generated"
    root.mkdir()
    monkeypatch.setattr(deals, "_pdf_bytes", lambda _: synthetic_pdf())
    result = deals.generate(
        {
            "kind": "invoice",
            "currency": "CAD",
            "title": "Synthetic invoice",
            "client": "PRIVATE_CLIENT_SENTINEL",
            "terms": "PRIVATE_TERMS_SENTINEL",
            "items": [
                {"description": "Analysis", "quantity": "3", "unit_price": "0.10"}
            ],
        },
        output_dir=root,
        request_id="generation-001",
    )
    assert result["status"] == "generated" and result["delivered"] is False
    return SimpleNamespace(
        root=root,
        result=result,
        path=Path(result["path"]),
        outbox=tmp_path / "delivery.sqlite3",
    )


@pytest.fixture(autouse=True)
def forbid_external_access(monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("real network or native credentials are forbidden in tests")

    monkeypatch.setattr(tg.http.client.HTTPSConnection, "connect", forbidden)
    monkeypatch.setattr(native_vault.NativeSecretVault, "get_bytes", forbidden)
    monkeypatch.setattr(native_vault.NativeSecretVault, "set_bytes", forbidden)
    monkeypatch.setattr(native_vault.NativeSecretVault, "delete", forbidden)


class TerminalOutput(io.StringIO):
    def __init__(self, tty=True):
        super().__init__()
        self.tty = tty

    def isatty(self):
        return self.tty

    def records(self):
        return [json.loads(line) for line in self.getvalue().splitlines()]


def terminal(*, tty=True, output_tty=True, consent=True, on_prompt=None):
    output = TerminalOutput(output_tty)

    class Input(io.StringIO):
        def isatty(self):
            return tty

        def readline(self, limit=-1):
            if on_prompt:
                on_prompt()
            phrase = output.records()[-1]["confirmation_required"]
            return (phrase if consent is True else str(consent)) + "\n"

    return delivery.OwnerTerminalV1(Input(), output), output


def argv(generated, command="send", **overrides):
    config = {
        "owner": "owner.primary",
        "workspace": "workspace.main",
        "account": "telegram.synthetic",
        "chat": CHAT,
        "operation-id": "delivery.invoice.001",
    }
    if command in {"send", "preview", "reconcile"}:
        config.update(
            {"output-dir": str(generated.root), "request-id": "generation-001"}
        )
    if command != "preview":
        config["outbox"] = str(generated.outbox)
    config.update(overrides)
    args = [command] + [
        f"--{key}={value}" for key, value in config.items() if value is not None
    ]
    if command in {"send", "reconcile"}:
        args.append("--enable-telegram")
    return args


def install_wire(
    monkeypatch,
    generated,
    *,
    secret=TOKEN,
    failure=None,
    mismatch=False,
    before_connection=None,
    on_request=None,
):
    seen = {"vault": [], "connections": 0, "requests": 0}
    reference = tg.telegram_vault_reference_v1(
        "owner.primary", "workspace.main", "telegram.synthetic"
    )

    def read(vault):
        assert vault.reference == reference
        seen["vault"].append(vault.reference)
        return secret

    monkeypatch.setattr(native_vault.NativeSecretVault, "get_bytes", read)

    class Connection:
        def request(self, method, path, body, headers):
            seen.update(method=method, path=path, body=body, headers=headers)
            seen["requests"] += 1
            if on_request:
                on_request()
            if failure:
                raise failure

        def getresponse(self):
            payload = {
                "ok": True,
                "result": {
                    "message_id": 81,
                    "chat": {"id": int(CHAT)},
                    "document": {
                        "file_id": "synthetic-file",
                        "file_unique_id": "synthetic-unique",
                        "file_name": generated.path.name,
                        "file_size": generated.path.stat().st_size + int(mismatch),
                        "mime_type": "application/pdf",
                    },
                },
            }
            return SimpleNamespace(
                status=200, read=lambda limit: json.dumps(payload).encode()[:limit]
            )

        def close(self):
            seen["closed"] = True

    def factory(origin, port, **kwargs):
        assert origin == tg.TELEGRAM_ORIGIN and port == 443
        seen["connections"] += 1
        if before_connection:
            before_connection()
        return Connection()

    return factory, seen


def run(generated, command="send", *, tty=None, connection_factory=None, **kwargs):
    interaction, output = terminal() if tty is None else tty
    code = delivery.cli(
        argv(generated, command),
        terminal=interaction,
        connection_factory=connection_factory,
        **kwargs,
    )
    return code, output


def test_provider_free_preview_authenticates_real_generation_without_outbox(generated):
    ledger = generated.root / "onyx-deals.sqlite3"
    before = ledger.read_bytes()
    code, output = run(generated, "preview", tty=terminal(tty=False, output_tty=False))
    assert code == 0
    preview = output.records()[-1]
    assert preview["number"] == generated.result["number"]
    assert (
        preview["pdf_sha256"] == hashlib.sha256(generated.path.read_bytes()).hexdigest()
    )
    assert preview["provider_contacted"] is False
    assert preview["chat"] == CHAT
    assert not generated.outbox.exists() and ledger.read_bytes() == before
    assert "PRIVATE_" not in output.getvalue()


def test_real_module_cli_preview_is_provider_free(generated):
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "core.business_document_delivery_v1",
            *argv(generated, "preview"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["number"] == generated.result["number"]
    assert not generated.outbox.exists()


def test_tty_send_uses_native_alias_and_hardened_multipart(generated, monkeypatch):
    factory, seen = install_wire(monkeypatch, generated)
    code, output = run(generated, connection_factory=factory)
    assert code == 0 and output.records()[-1]["provider_accepted"] is True
    assert seen["requests"] == 1 and len(seen["vault"]) == 1
    assert seen["path"] == f"/bot{TOKEN.decode()}/sendDocument"
    mime = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + seen["headers"]["Content-Type"] + "\r\n\r\n").encode()
        + seen["body"]
    )
    parts = {
        part.get_param("name", header="content-disposition"): part
        for part in mime.iter_parts()
    }
    assert parts["document"].get_payload(decode=True) == generated.path.read_bytes()
    assert parts["chat_id"].get_payload(decode=True) == CHAT.encode()
    assert seen["closed"]
    preview, confirmation, receipt = output.records()
    assert (
        confirmation["confirmation_required"]
        == f"SEND {preview['request_digest']} TO {CHAT}"
    )
    assert receipt["status"] == "accepted"
    assert (
        TOKEN.decode() not in output.getvalue() and "PRIVATE_" not in output.getvalue()
    )
    assert TOKEN not in generated.outbox.read_bytes()


def test_duplicate_cli_send_reuses_durable_receipt_without_vault_or_upload(
    generated, monkeypatch
):
    factory, seen = install_wire(monkeypatch, generated)
    assert run(generated, connection_factory=factory)[0] == 0
    code, output = run(generated, connection_factory=factory)
    assert code == 0 and output.records()[-1]["status"] == "accepted"
    assert seen["requests"] == 1 and len(seen["vault"]) == 1


def test_missing_token_is_not_dispatched_and_never_automatically_retried(
    generated, monkeypatch
):
    factory, seen = install_wire(monkeypatch, generated, secret=None)
    code, output = run(generated, connection_factory=factory)
    assert code == 3 and output.records()[-1]["status"] == "not_dispatched"
    assert seen["requests"] == 0 and seen["connections"] == 0
    assert run(generated, connection_factory=factory)[0] == 3
    assert len(seen["vault"]) == 1


@pytest.mark.parametrize("consent", [False, "yes", "SEND", "", "SEND wrong TO " + CHAT])
def test_consent_denial_never_opens_vault_or_creates_outbox(generated, consent):
    code, output = run(generated, tty=terminal(consent=consent))
    assert code == 2 and output.records()[-1]["reason"] == "exact_owner_consent_denied"
    assert not generated.outbox.exists()


@pytest.mark.parametrize(
    "input_tty,output_tty", [(False, True), (True, False), (False, False)]
)
def test_piped_or_redirected_send_is_denied(generated, input_tty, output_tty):
    code, output = run(generated, tty=terminal(tty=input_tty, output_tty=output_tty))
    assert (
        code == 2 and output.records()[-1]["reason"] == "interactive_owner_tty_required"
    )
    assert not generated.outbox.exists()


def test_gate_is_explicit_not_inferred_from_environment(generated, monkeypatch):
    monkeypatch.setenv(tg.FEATURE_FLAG, "true")
    interaction, output = terminal()
    code = delivery.cli(
        [item for item in argv(generated) if item != "--enable-telegram"],
        terminal=interaction,
    )
    assert (
        code == 2
        and output.records()[-1]["reason"] == "explicit_telegram_opt_in_required"
    )
    assert not generated.outbox.exists()


@pytest.mark.parametrize(
    "field",
    [
        "owner",
        "workspace",
        "account",
        "chat",
        "operation-id",
        "output-dir",
        "request-id",
        "outbox",
    ],
)
def test_no_invented_configuration_defaults(generated, field):
    with pytest.raises(SystemExit) as error:
        delivery.cli(argv(generated, **{field: None}), terminal=terminal()[0])
    assert error.value.code == 2


def test_yes_switch_does_not_exist(generated):
    with pytest.raises(SystemExit) as error:
        delivery.cli(argv(generated) + ["--yes"], terminal=terminal()[0])
    assert error.value.code == 2


@pytest.mark.parametrize("tamper", ["pdf", "digest", "number", "status", "unknown"])
def test_only_generated_ledger_bound_documents_can_be_previewed(generated, tamper):
    if tamper == "pdf":
        generated.path.write_bytes(synthetic_pdf() + b"changed")
    else:
        with sqlite3.connect(generated.root / "onyx-deals.sqlite3") as db:
            if tamper == "unknown":
                db.execute("DELETE FROM documents")
            else:
                column, value = {
                    "digest": ("pdf_digest", "0" * 64),
                    "number": ("number", "../../arbitrary"),
                    "status": ("status", "reserved"),
                }[tamper]
                db.execute(f"UPDATE documents SET {column}=?", (value,))
    code, output = run(generated, "preview")
    assert code == 2 and output.records()[-1]["status"] == "denied"
    assert not generated.outbox.exists()


@pytest.mark.parametrize("target", ["pdf", "ledger"])
def test_generation_changed_during_consent_is_denied(generated, target):
    def change():
        if target == "pdf":
            generated.path.write_bytes(b"%PDF-1.4\nchanged\n%%EOF")
        else:
            with sqlite3.connect(generated.root / "onyx-deals.sqlite3") as db:
                db.execute("UPDATE documents SET status='failed'")

    assert run(generated, tty=terminal(on_prompt=change))[0] == 2
    assert not generated.outbox.exists()


def test_generation_revoked_at_wire_boundary_prevents_upload(generated, monkeypatch):
    def change():
        with sqlite3.connect(generated.root / "onyx-deals.sqlite3") as db:
            db.execute("UPDATE documents SET status='failed'")

    factory, seen = install_wire(monkeypatch, generated, before_connection=change)
    code, output = run(generated, connection_factory=factory)
    assert code == 3 and output.records()[-1]["status"] == "not_dispatched"
    assert seen["requests"] == 0


def test_expired_approval_does_not_create_outbox(generated):
    ticks = [100.0]
    code, output = run(
        generated,
        tty=terminal(on_prompt=lambda: ticks.__setitem__(0, 221.0)),
        clock=lambda: ticks[0],
    )
    assert code == 2 and "expired" in output.records()[-1]["reason"]
    assert not generated.outbox.exists()


def test_approval_expiring_during_final_file_verification_prevents_upload(
    generated, monkeypatch
):
    ticks = [100.0]
    at_wire = [False]
    original = delivery.prepare_generated_delivery_v1

    def delayed(**kwargs):
        result = original(**kwargs)
        if at_wire[0]:
            ticks[0] = 221.0
        return result

    monkeypatch.setattr(delivery, "prepare_generated_delivery_v1", delayed)
    factory, seen = install_wire(
        monkeypatch, generated, before_connection=lambda: at_wire.__setitem__(0, True)
    )
    code, output = run(generated, connection_factory=factory, clock=lambda: ticks[0])
    assert code == 3 and output.records()[-1]["status"] == "not_dispatched"
    assert seen["requests"] == 0


def test_cancel_during_consent_does_not_create_outbox(generated):
    cancel = tg.TelegramCancellationV1()
    assert (
        run(generated, tty=terminal(on_prompt=cancel.cancel), cancellation=cancel)[0]
        == 2
    )
    assert not generated.outbox.exists()


@pytest.mark.parametrize("when", ["before", "after"])
def test_wire_cancellation_has_honest_outcome(generated, monkeypatch, when):
    cancel = tg.TelegramCancellationV1()
    factory, seen = install_wire(
        monkeypatch,
        generated,
        before_connection=cancel.cancel if when == "before" else None,
        on_request=cancel.cancel if when == "after" else None,
    )
    code, output = run(generated, connection_factory=factory, cancellation=cancel)
    assert code == 3
    assert output.records()[-1]["status"] == (
        "not_dispatched" if when == "before" else "reconciliation"
    )
    assert seen["requests"] == (0 if when == "before" else 1)


def test_sigint_during_wire_is_reconciliation_and_handler_restored(
    generated, monkeypatch
):
    prior = signal.getsignal(signal.SIGINT)
    factory, seen = install_wire(
        monkeypatch,
        generated,
        on_request=lambda: signal.getsignal(signal.SIGINT)(signal.SIGINT, None),
    )
    code, output = run(generated, connection_factory=factory)
    assert code == 3 and output.records()[-1]["status"] == "reconciliation"
    assert seen["requests"] == 1 and signal.getsignal(signal.SIGINT) == prior


@pytest.mark.parametrize("unknown", ["timeout", "mismatch"])
def test_unknown_outcome_is_durable_and_not_retried(generated, monkeypatch, unknown):
    factory, seen = install_wire(
        monkeypatch,
        generated,
        mismatch=unknown == "mismatch",
        failure=TimeoutError("PRIVATE_TOKEN_SENTINEL")
        if unknown == "timeout"
        else None,
    )
    code, output = run(generated, connection_factory=factory)
    assert code == 3 and output.records()[-1]["status"] == "reconciliation"
    assert run(generated, connection_factory=factory)[0] == 3
    assert seen["requests"] == 1 and len(seen["vault"]) == 1
    assert "PRIVATE_TOKEN_SENTINEL" not in output.getvalue()


def test_status_has_no_provider_no_pdf_read_and_no_database_mutation(
    generated, monkeypatch
):
    factory, _ = install_wire(monkeypatch, generated)
    assert run(generated, connection_factory=factory)[0] == 0
    before = generated.outbox.read_bytes()
    generated.path.unlink()
    monkeypatch.setattr(
        native_vault.NativeSecretVault,
        "get_bytes",
        lambda _: pytest.fail("status read vault"),
    )
    code, output = run(generated, "status", tty=terminal(tty=False, output_tty=False))
    assert code == 0 and output.records()[-1]["status"] == "accepted"
    assert generated.outbox.read_bytes() == before
    assert (
        "PRIVATE_" not in output.getvalue()
        and str(generated.root) not in output.getvalue()
    )


def test_missing_status_never_creates_database(generated):
    code, output = run(generated, "status")
    assert code == 0 and output.records()[-1]["status"] == "unavailable"
    assert not generated.outbox.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner", "owner.other"),
        ("workspace", "workspace.other"),
        ("account", "telegram.other"),
        ("chat", "123456"),
    ],
)
def test_status_and_send_cannot_cross_existing_operation_scope(
    generated, monkeypatch, field, value
):
    factory, seen = install_wire(monkeypatch, generated)
    assert run(generated, connection_factory=factory)[0] == 0
    for command in ("status", "send"):
        interaction, output = terminal()
        assert (
            delivery.cli(
                argv(generated, command, **{field: value}),
                terminal=interaction,
                connection_factory=factory,
            )
            == 2
        )
        assert output.records()[-1]["reason"] == "outbox_scope_mismatch"
    assert seen["requests"] == 1


@pytest.mark.parametrize("target", ["pdf", "ledger", "outbox", "root", "sidecar"])
def test_links_and_reparse_storage_are_denied(generated, monkeypatch, target):
    original = Path.lstat
    selected = {
        "pdf": generated.path,
        "ledger": generated.root / "onyx-deals.sqlite3",
        "outbox": generated.outbox,
        "root": generated.root,
        "sidecar": Path(str(generated.outbox) + "-wal"),
    }[target]
    if target in {"outbox", "sidecar"}:
        selected.write_bytes(b"synthetic")

    def linked(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == selected:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
        return info

    monkeypatch.setattr(Path, "lstat", linked)
    assert run(generated)[0] == 2


def test_hardlinked_ledger_is_denied(generated):
    os.link(generated.root / "onyx-deals.sqlite3", generated.root / "linked.sqlite3")
    assert run(generated, "preview")[0] == 2


@pytest.mark.parametrize(
    "decision,message",
    [("confirmed_not_dispatched", None), ("confirmed_accepted", "81")],
)
def test_explicit_offline_reconciliation_preserves_no_retry(
    generated, monkeypatch, decision, message
):
    factory, seen = install_wire(monkeypatch, generated, failure=TimeoutError())
    assert run(generated, connection_factory=factory)[0] == 3
    # Synthetic abandoned lease; production must wait for the real lease.
    with sqlite3.connect(generated.outbox) as db:
        db.execute("UPDATE messages SET lease_expires_at=0")
    interaction, output = terminal()
    code = delivery.cli(
        argv(
            generated,
            "reconcile",
            decision=decision,
            **{"provider-message-id": message},
        ),
        terminal=interaction,
        connection_factory=factory,
    )
    assert code == 0
    assert output.records()[-1]["status"] == (
        "accepted" if message else "not_dispatched"
    )
    assert seen["requests"] == 1 and len(seen["vault"]) == 1
    assert run(generated, connection_factory=factory)[0] == (0 if message else 3)
    assert seen["requests"] == 1


def test_reconciliation_does_not_override_live_lease(generated, monkeypatch):
    factory, seen = install_wire(monkeypatch, generated, failure=TimeoutError())
    assert run(generated, connection_factory=factory)[0] == 3
    assert (
        delivery.cli(
            argv(generated, "reconcile", decision="confirmed_not_dispatched"),
            terminal=terminal()[0],
            connection_factory=factory,
        )
        == 2
    )
    assert run(generated, "status")[1].records()[-1]["status"] == "reconciliation"
    assert seen["requests"] == 1


def test_reconciliation_cannot_attest_to_a_different_generated_document(
    generated, monkeypatch
):
    factory, seen = install_wire(monkeypatch, generated, failure=TimeoutError())
    assert run(generated, connection_factory=factory)[0] == 3
    with sqlite3.connect(generated.outbox) as db:
        db.execute("UPDATE messages SET lease_expires_at=0")
    changed = synthetic_pdf().replace(b"Synthetic invoice", b"Different invoice")
    generated.path.write_bytes(changed)
    with sqlite3.connect(generated.root / "onyx-deals.sqlite3") as db:
        db.execute(
            "UPDATE documents SET pdf_digest=?", (hashlib.sha256(changed).hexdigest(),)
        )
    interaction, output = terminal()
    assert (
        delivery.cli(
            argv(generated, "reconcile", decision="confirmed_not_dispatched"),
            terminal=interaction,
        )
        == 2
    )
    assert output.records()[-1]["reason"] == "outbox_request_mismatch"
    assert seen["requests"] == 1


def test_authority_is_exact_and_revoked_after_cli_return(generated, monkeypatch):
    captured = {}
    original = tg.TelegramOfficialOutboxV1.send_document

    def capture(self, **kwargs):
        captured.update(kwargs)
        auth = kwargs["authority"]
        expected = (
            "owner.primary",
            "workspace.main",
            "official_message.send",
            "telegram.synthetic",
            CHAT,
        )
        assert auth(*expected) is True
        for index in range(5):
            wrong = list(expected)
            wrong[index] = "different"
            assert auth(*wrong) is False
        assert kwargs["owner_approval"]("0" * 64) is False
        return original(self, **kwargs)

    monkeypatch.setattr(tg.TelegramOfficialOutboxV1, "send_document", capture)
    factory, _ = install_wire(monkeypatch, generated)
    assert run(generated, connection_factory=factory)[0] == 0
    assert captured["owner_approval"](captured["document"].request_digest) is False
    assert (
        captured["authority"](
            "owner.primary",
            "workspace.main",
            "official_message.send",
            "telegram.synthetic",
            CHAT,
        )
        is False
    )
