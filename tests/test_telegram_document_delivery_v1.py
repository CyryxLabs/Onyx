"""Offline PDF delivery contract tests; all wire/vault dependencies are synthetic."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import threading
from dataclasses import replace
from email.parser import BytesParser
from email.policy import default
from pathlib import Path
from types import SimpleNamespace

import pytest

import core.telegram_official_connector_v1 as tg


CHAT = "-1001234567890"
PDF = b"%PDF-1.7\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"
TOKEN = b"123456789:AAExample_secret_token_1234567890"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("real network is forbidden")
    monkeypatch.setattr(tg.http.client.HTTPSConnection, "connect", forbidden)


def account(chat_ids=(CHAT,)):
    return tg.TelegramAccountV1(
        "telegram.synthetic", "owner.primary", "workspace.main",
        tg.telegram_vault_reference_v1("owner.primary", "workspace.main", "telegram.synthetic"),
        chat_ids,
    )


def outbox(tmp_path):
    return tg.TelegramOfficialOutboxV1(
        tmp_path / "outbox.sqlite3", gate=tg.TelegramFeatureGateV1(True),
    )


def prepare(tmp_path, **kwargs):
    path = tmp_path / "INV-2026-001.pdf"
    if not path.exists():
        path.write_bytes(PDF)
    args = dict(operation_id="pdf.invoice.001", account=account(), chat_id=CHAT,
                pdf_path=path, allowed_root=tmp_path,
                expected_content_digest=hashlib.sha256(PDF).hexdigest())
    args.update(kwargs)
    return tg.prepare_telegram_document_v1(**args)


def provider_payload(document):
    return {"ok": True, "result": {"message_id": 81, "chat": {"id": int(CHAT)},
            "document": {"file_id": "synthetic-file", "file_unique_id": "synthetic-unique",
                         "file_name": document.filename, "file_size": len(document.content),
                         "mime_type": "application/pdf"}}}


def wire(document, *, payload=None, status=200, failure=None, before_request=None,
         before_connection=None, after_response=None, secret=TOKEN):
    observed = {"requests": 0, "vault_reads": 0}
    raw = provider_payload(document) if payload is None else payload
    raw = raw if type(raw) is bytes else json.dumps(raw).encode()

    class Connection:
        def request(self, method, path, body, headers):
            observed.update(method=method, path=path, body=body, headers=headers)
            observed["requests"] += 1
            if before_request:
                before_request()
            if failure:
                raise failure

        def getresponse(self):
            def read(limit):
                if after_response:
                    after_response()
                return raw[:limit]
            return SimpleNamespace(status=status, read=read)

        def close(self):
            observed["closed"] = True

    def vault(reference):
        observed["vault_reads"] += 1
        assert reference == account().secret_reference
        return secret

    def factory(origin, port, **kwargs):
        observed.update(origin=origin, port=port, **kwargs)
        if before_connection:
            before_connection()
        return Connection()

    return tg.StdlibTelegramTransportV1(vault_reader=vault, connection_factory=factory), observed


def send(box, document, transport, **kwargs):
    args = dict(document=document, account=account(), transport=transport,
                authority=lambda *_: True,
                owner_approval=lambda digest: digest == document.request_digest)
    args.update(kwargs)
    return box.send_document(**args)


def test_pdf_uses_official_multipart_and_durable_shared_outbox(tmp_path):
    document = prepare(tmp_path)
    box = outbox(tmp_path)
    approvals = []
    scopes = []
    transport, observed = wire(document)
    result = send(box, document, transport,
                  owner_approval=lambda digest: approvals.append(digest) is None,
                  authority=lambda *scope: scopes.append(scope) is None)
    assert result.status == "accepted"
    assert result.provider_message_id == "81"
    assert result.content_digest == hashlib.sha256(PDF).hexdigest()
    assert result.request_digest == document.request_digest
    assert len(approvals) >= 2 and set(approvals) == {document.request_digest}
    assert all(scope == ("owner.primary", "workspace.main", "official_message.send",
                         "telegram.synthetic", CHAT) for scope in scopes)
    assert observed["origin"] == tg.TELEGRAM_ORIGIN
    assert observed["port"] == 443
    assert observed["method"] == "POST"
    assert observed["path"] == f"/bot{TOKEN.decode()}/sendDocument"
    assert observed["closed"]
    mime = BytesParser(policy=default).parsebytes(
        ("Content-Type: " + observed["headers"]["Content-Type"] + "\r\n\r\n").encode()
        + observed["body"])
    parts = {part.get_param("name", header="content-disposition"): part
             for part in mime.iter_parts()}
    assert set(parts) == {"chat_id", "document", "disable_content_type_detection"}
    assert parts["chat_id"].get_payload(decode=True) == CHAT.encode()
    assert parts["document"].get_payload(decode=True) == PDF
    assert parts["document"].get_filename() == document.filename
    assert parts["document"].get_content_type() == "application/pdf"
    assert send(box, document, transport) == result
    box.close()
    assert send(outbox(tmp_path), document, transport) == result
    assert observed["requests"] == 1
    with sqlite3.connect(tmp_path / "outbox.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        events = db.execute("SELECT event,detail_json FROM message_events").fetchall()
    assert [row[0] for row in events] == ["telegram.reserved", "telegram.dispatching", "telegram.accepted"]
    durable = (tmp_path / "outbox.sqlite3").read_bytes()
    assert PDF not in durable and TOKEN not in durable
    assert str(tmp_path).encode() not in durable
    assert PDF.decode() not in repr(document)


@pytest.mark.parametrize("change", ["content", "chat", "filename", "operation", "account"])
def test_approval_is_bound_to_exact_request(tmp_path, change):
    original = prepare(tmp_path)
    altered = {
        "content": replace(original, content=PDF.replace(b"Catalog", b"Changed")),
        "chat": replace(original, chat_id="902100100"),
        "filename": replace(original, filename="different.pdf"),
        "operation": replace(original, operation_id="pdf.different"),
        "account": replace(original, account_id="telegram.other"),
    }[change]
    transport, observed = wire(original)
    with pytest.raises(tg.TelegramDenied):
        send(outbox(tmp_path), altered, transport,
             account=account((CHAT, "902100100")),
             owner_approval=lambda digest: digest == original.request_digest)
    assert observed["requests"] == 0 and observed["vault_reads"] == 0


@pytest.mark.parametrize("denial", [False, 1, "true", None])
def test_owner_approval_requires_literal_true(tmp_path, denial):
    document = prepare(tmp_path)
    transport, observed = wire(document)
    with pytest.raises(tg.TelegramDenied):
        send(outbox(tmp_path), document, transport, owner_approval=lambda _: denial)
    assert observed["vault_reads"] == 0


def test_central_authority_and_default_gate_still_required(tmp_path):
    with pytest.raises(tg.TelegramDenied):
        tg.TelegramOfficialOutboxV1(tmp_path / "disabled.sqlite3")
    document = prepare(tmp_path)
    transport, observed = wire(document)
    with pytest.raises(tg.TelegramDenied):
        send(outbox(tmp_path), document, transport, authority=lambda *_: False)
    with pytest.raises(tg.TelegramNotDispatched, match="outbox_dispatch_required"):
        transport.send(account(), document, tg.TelegramBudgetV1(), tg.TelegramCancellationV1())
    assert observed["vault_reads"] == 0


@pytest.mark.parametrize("revoke", ["owner", "authority", "cancel"])
def test_revocation_at_last_wire_boundary_never_uploads(tmp_path, revoke):
    document = prepare(tmp_path)
    active = [True]
    cancel = tg.TelegramCancellationV1()

    def revoke_now():
        active[0] = False
        if revoke == "cancel":
            cancel.cancel()

    transport, observed = wire(document, before_connection=revoke_now)
    result = send(outbox(tmp_path), document, transport, cancellation=cancel,
                  owner_approval=lambda _: active[0] if revoke == "owner" else True,
                  authority=lambda *_: active[0] if revoke == "authority" else True)
    assert result.status == "not_dispatched"
    assert observed["requests"] == 0 and observed["closed"]


def test_path_changes_after_approval_upload_only_original_snapshot(tmp_path):
    document = prepare(tmp_path)
    transport, observed = wire(document)

    def approve(digest):
        (tmp_path / document.filename).write_bytes(b"changed after preview")
        return digest == document.request_digest

    assert send(outbox(tmp_path), document, transport, owner_approval=approve).status == "accepted"
    assert PDF in observed["body"] and b"changed after preview" not in observed["body"]


@pytest.mark.parametrize("case", ["timeout", "broken_json", "empty_ok", "server_error",
                                  "wrong_chat", "wrong_size", "wrong_name", "wrong_mime",
                                  "no_document", "no_file_id", "bool_size", "caption", "cancel"])
def test_uncertain_document_outcomes_persist_and_never_retry(tmp_path, case):
    document = prepare(tmp_path)
    payload = provider_payload(document)
    params = {}
    cancel = tg.TelegramCancellationV1()
    if case == "timeout":
        params["failure"] = TimeoutError("SENSITIVE")
    elif case == "broken_json":
        payload = b"SENSITIVE not json"
    elif case == "empty_ok":
        payload = {}
    elif case == "server_error":
        params["status"] = 503
    elif case == "wrong_chat":
        payload["result"]["chat"]["id"] = 123
    elif case == "no_document":
        del payload["result"]["document"]
    elif case == "caption":
        payload["result"]["caption"] = "unapproved"
    elif case == "cancel":
        params["after_response"] = cancel.cancel
    else:
        field, value = {"wrong_size": ("file_size", 999), "wrong_name": ("file_name", "other.pdf"),
                        "wrong_mime": ("mime_type", "text/plain"), "no_file_id": ("file_id", ""),
                        "bool_size": ("file_size", True)}[case]
        payload["result"]["document"][field] = value
    transport, observed = wire(document, payload=payload, **params)
    box = outbox(tmp_path)
    result = send(box, document, transport, cancellation=cancel)
    assert result.status == "reconciliation" and result.provider_message_id is None
    box.close()
    reopened = outbox(tmp_path)
    assert send(reopened, document, transport) == result
    assert observed["requests"] == 1
    assert "SENSITIVE" not in json.dumps(result.receipt_payload())
    assert b"SENSITIVE" not in (tmp_path / "outbox.sqlite3").read_bytes()


@pytest.mark.parametrize("status", [302, 400, 401, 403, 429])
def test_known_rejections_do_not_follow_redirects_or_retry(tmp_path, status):
    document = prepare(tmp_path)
    transport, observed = wire(document, status=status, payload=b"SENSITIVE")
    box = outbox(tmp_path)
    result = send(box, document, transport)
    assert result.status == "rejected"
    assert send(box, document, transport) == result
    assert observed["requests"] == 1


def test_missing_credentials_and_budget_failures_never_upload(tmp_path):
    document = prepare(tmp_path)
    for index, params in enumerate(({"secret": None}, {}, {})):
        candidate = replace(document, operation_id=f"pdf.budget.{index}")
        transport, observed = wire(candidate, **params)
        budget = tg.TelegramBudgetV1(maximum_request_bytes=1) if index == 1 else tg.TelegramBudgetV1()
        if index == 2:
            budget = tg.TelegramBudgetV1(maximum_response_bytes=1)
        result = send(outbox(tmp_path), candidate, transport, budget=budget)
        assert result.status == ("reconciliation" if index == 2 else "not_dispatched")
        assert observed["requests"] == (1 if index == 2 else 0)


def test_document_size_budget_and_signature_are_enforced(tmp_path):
    with pytest.raises(tg.TelegramContractError, match="size"):
        prepare(tmp_path, budget=tg.TelegramBudgetV1(maximum_document_bytes=len(PDF) - 1))
    document = prepare(tmp_path)
    transport, observed = wire(document)
    with pytest.raises(tg.TelegramContractError, match="size"):
        send(outbox(tmp_path), document, transport,
             budget=tg.TelegramBudgetV1(maximum_document_bytes=1))
    assert observed["vault_reads"] == 0
    for content in (b"", b"not PDF", b"%PDF-1.7 truncated", b"x" * (tg.MAX_DOCUMENT_BYTES + 1)):
        with pytest.raises(tg.TelegramContractError):
            replace(document, content=content)
    for value in (True, 0, tg.MAX_DOCUMENT_BYTES + 1):
        with pytest.raises(tg.TelegramContractError):
            tg.TelegramBudgetV1(maximum_document_bytes=value)


def test_pdf_larger_than_text_budget_uploads_with_exact_document_ceiling(tmp_path):
    content = b"%PDF-1.7\n" + b"% synthetic padding\n" * 4000 + b"%%EOF\n"
    assert len(content) > tg.MAX_REQUEST_BYTES
    path = tmp_path / "INV-2026-001.pdf"
    path.write_bytes(content)
    budget = tg.TelegramBudgetV1(maximum_document_bytes=len(content))
    document = prepare(tmp_path, expected_content_digest=hashlib.sha256(content).hexdigest(),
                       budget=budget)
    transport, observed = wire(document)
    assert send(outbox(tmp_path), document, transport, budget=budget).status == "accepted"
    assert content in observed["body"]
    assert len(observed["body"]) <= budget.maximum_document_bytes + budget.maximum_request_bytes


@pytest.mark.parametrize("name", ["../leak.pdf", 'bad".pdf', "bad\r\nheader.pdf", "file.txt", "file.pdf:stream", "file.PDF"])
def test_filename_cannot_inject_multipart_headers(tmp_path, name):
    with pytest.raises(tg.TelegramContractError):
        replace(prepare(tmp_path), filename=name)


@pytest.mark.parametrize("path", ["relative.pdf", "https://example.com/a.pdf", "file_id_123",
                                  "//server/share/a.pdf", "C:/tmp/a.pdf:stream"])
def test_nonlocal_and_ambiguous_paths_rejected(tmp_path, path):
    with pytest.raises(tg.TelegramDenied):
        prepare(tmp_path, pdf_path=path)


def test_root_traversal_and_digest_mismatch_rejected(tmp_path):
    with pytest.raises(tg.TelegramDenied):
        prepare(tmp_path, pdf_path=tmp_path / "sub" / ".." / "INV-2026-001.pdf")
    with pytest.raises(tg.TelegramDenied):
        prepare(tmp_path, allowed_root=tmp_path / "other")
    with pytest.raises(tg.TelegramDenied, match="digest"):
        prepare(tmp_path, expected_content_digest="0" * 64)


@pytest.mark.parametrize("linked", ["file", "root", "ancestor"])
def test_reparse_points_on_every_path_component_are_denied(tmp_path, monkeypatch, linked):
    prepare(tmp_path)
    target = {"file": tmp_path / "INV-2026-001.pdf", "root": tmp_path,
              "ancestor": tmp_path.parent}[linked]
    original = Path.lstat

    def lstat(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(tg.TelegramDenied, match="linked"):
        prepare(tmp_path)


def test_actual_hardlink_is_rejected(tmp_path):
    prepare(tmp_path)
    os.link(tmp_path / "INV-2026-001.pdf", tmp_path / "alias.pdf")
    with pytest.raises(tg.TelegramDenied, match="hard-linked"):
        prepare(tmp_path)


def test_file_swap_between_stat_and_open_rejected(tmp_path, monkeypatch):
    prepare(tmp_path)
    original = os.open

    def swapped(path, flags, *args, **kwargs):
        replacement = tmp_path / "replacement.pdf"
        replacement.write_bytes(PDF)
        os.replace(replacement, path)
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapped)
    with pytest.raises(tg.TelegramDenied, match="changed"):
        prepare(tmp_path)


def test_handle_and_path_ctime_need_not_share_windows_semantics(tmp_path, monkeypatch):
    original = os.fstat

    def fstat(fd):
        info = original(fd)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_mode", "st_nlink")
        return SimpleNamespace(**{key: getattr(info, key) for key in fields}, st_ctime_ns=123)

    monkeypatch.setattr(os, "fstat", fstat)
    assert prepare(tmp_path).content == PDF


def test_file_changed_during_bounded_read_is_rejected(tmp_path, monkeypatch):
    original = os.fstat
    calls = [0]

    def fstat(fd):
        info = original(fd)
        calls[0] += 1
        fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_nlink", "st_ctime_ns")
        return SimpleNamespace(**{key: getattr(info, key) for key in fields},
                               st_mtime_ns=info.st_mtime_ns + (1 if calls[0] > 1 else 0))

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(tg.TelegramDenied, match="during read"):
        prepare(tmp_path)


def test_cancellation_from_final_approval_callback_is_not_dispatched(tmp_path):
    document = prepare(tmp_path)
    cancel = tg.TelegramCancellationV1()
    approvals = [0]

    def approve(_):
        approvals[0] += 1
        if approvals[0] == 4:  # reservation, dispatch, transport, last wire check
            cancel.cancel()
        return True

    transport, observed = wire(document)
    result = send(outbox(tmp_path), document, transport, cancellation=cancel, owner_approval=approve)
    assert approvals[0] == 4
    assert result.status == "not_dispatched" and observed["requests"] == 0


def test_crash_after_durable_commit_leaves_no_retry(tmp_path):
    document = prepare(tmp_path)
    transport, observed = wire(document)
    box = outbox(tmp_path)

    def crash():
        raise SystemExit("synthetic crash")

    box._after_dispatching_commit = crash
    with pytest.raises(SystemExit):
        send(box, document, transport)
    assert box.status(document.operation_id).status == "dispatching"
    assert send(outbox(tmp_path), document, transport).status == "dispatching"
    assert observed["requests"] == 0


def test_same_operation_cannot_change_pdf_or_switch_to_text(tmp_path):
    document = prepare(tmp_path)
    transport, observed = wire(document)
    box = outbox(tmp_path)
    assert send(box, document, transport).status == "accepted"
    with pytest.raises(tg.TelegramDenied, match="idempotency"):
        send(box, replace(document, filename="changed.pdf"), transport)
    with pytest.raises(tg.TelegramDenied, match="idempotency"):
        box.send_message(operation_id=document.operation_id, account=account(), chat_id=CHAT,
                         text="hello", authority=lambda *_: True, transport=transport)
    assert observed["requests"] == 1


def test_document_uses_existing_reconciliation_proof(tmp_path):
    document = prepare(tmp_path)
    transport, observed = wire(document, failure=TimeoutError())
    box = outbox(tmp_path)
    assert send(box, document, transport).status == "reconciliation"
    proof = tg.TelegramReconciliationProofV1(
        document.operation_id, tg.TelegramReconciliationDecisionV1.CONFIRMED_NOT_DISPATCHED,
        CHAT, document.content_digest)
    assert box.reconcile(proof, authority=lambda *_: True).status == "not_dispatched"
    assert send(box, document, transport).status == "not_dispatched"
    assert observed["requests"] == 1


def test_concurrent_document_duplicate_has_one_wire_request(tmp_path):
    document = prepare(tmp_path)
    started, release = threading.Event(), threading.Event()

    def hold():
        started.set()
        assert release.wait(5)

    transport, observed = wire(document, before_request=hold)
    box = outbox(tmp_path)
    results = []
    worker = threading.Thread(target=lambda: results.append(send(box, document, transport)))
    worker.start()
    try:
        assert started.wait(5)
        assert send(outbox(tmp_path), document, transport).status == "dispatching"
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert results[0].status == "accepted" and observed["requests"] == 1
