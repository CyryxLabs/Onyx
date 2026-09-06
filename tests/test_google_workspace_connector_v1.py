from __future__ import annotations

import dataclasses
import hashlib
import json
import multiprocessing
import os
import sqlite3
import traceback
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

from core.google_workspace_connector_v1 import (
    AUTH_ORIGIN,
    AUTH_PATH,
    CALENDAR_EVENTS_PATH,
    CALENDAR_ORIGIN,
    GMAIL_MESSAGES_PATH,
    GMAIL_ORIGIN,
    GMAIL_PROFILE_PATH,
    OAUTH_ORIGIN,
    READ_SCOPES,
    REVOKE_PATH,
    TOKEN_PATH,
    GoogleHttpResponseV1,
    GoogleHttpRequestV1,
    GoogleGrantMetadataV1,
    GoogleOAuthSettingsV1,
    GooglePendingAuthorizationV1,
    GoogleWorkspaceBindingV1,
    GoogleWorkspaceBudgetV1,
    GoogleWorkspaceFeatureGateV1,
    GoogleWorkspaceV1ContractError,
    GoogleWorkspaceV1Denied,
    GoogleWorkspaceV1UnknownOutcome,
    HmacGoogleIdentityPseudonymizerV1,
    InMemoryGoogleGrantMetadataStoreV1,
    SqliteGoogleGrantMetadataStoreV1,
    _exclusive_file_lock,
    create_google_workspace_connector_v1,
)


NOW = 2_000_000_000
ACCESS = "access-token-secret"
REFRESH = "refresh-token-secret"
METADATA_KEY = b"m" * 32
IDENTITY_KEY = b"i" * 32
IDENTITY = HmacGoogleIdentityPseudonymizerV1(IDENTITY_KEY)


class GenerationAnchor:
    def __init__(self):
        self.values = {}

    def read(self, store_reference):
        return self.values.get(store_reference)

    def compare_and_swap(self, store_reference, expected, replacement):
        if self.values.get(store_reference) != expected:
            return False
        self.values[store_reference] = replacement
        return True


class FileGenerationAnchor:
    def __init__(self, path):
        self.path = str(path)

    def read(self, store_reference):
        del store_reference
        try:
            return int(open(self.path, encoding="ascii").read())
        except FileNotFoundError:
            return None

    def compare_and_swap(self, store_reference, expected, replacement):
        del store_reference
        current = self.read("")
        if current != expected:
            return False
        with open(self.path, "w", encoding="ascii") as stream:
            stream.write(str(replacement))
            stream.flush()
            os.fsync(stream.fileno())
        return True


def metadata_value(binding_digest_value, state="connected"):
    return GoogleGrantMetadataV1(
        binding_digest_value,
        "1" * 64,
        "2" * 64,
        "3" * 64,
        READ_SCOPES,
        NOW + 3600,
        "4" * 64,
        state,
        NOW,
    )


def process_put(database, anchor_path, digest, result_queue):
    try:
        store = SqliteGoogleGrantMetadataStoreV1(
            Path(database), METADATA_KEY, FileGenerationAnchor(anchor_path)
        )
        store.put(metadata_value(digest))
        result_queue.put("ok")
    except Exception as exc:
        result_queue.put(type(exc).__name__)


_ANCHORS = {}


def anchor_for(path):
    return _ANCHORS.setdefault(str(path), GenerationAnchor())


def durable_store(path, key=METADATA_KEY, *, anchor=None):
    return SqliteGoogleGrantMetadataStoreV1(
        path, key, anchor if anchor is not None else anchor_for(path)
    )


def binding_digest(binding):
    return IDENTITY.pseudonym(
        "binding",
        '["%s","%s","%s"]'
        % (binding.owner_id, binding.workspace_id, binding.account_id),
    )


class Vault:
    def __init__(self):
        self.tokens = {}

    def resolve(self, binding_digest):
        return self.tokens.get(binding_digest)

    def compare_and_set(self, binding_digest, expected_digest, value):
        current = self.tokens.get(binding_digest)
        actual = None if current is None else current.digest
        if actual != expected_digest:
            return False
        self.tokens[binding_digest] = value
        return True

    def delete(self, binding_digest, expected_digest):
        current = self.tokens.get(binding_digest)
        if current is None or current.digest != expected_digest:
            return False
        del self.tokens[binding_digest]
        return True


class Pending:
    def __init__(self):
        self.values = {}

    def store(self, state_digest, value):
        assert type(value) is GooglePendingAuthorizationV1
        self.values[state_digest] = value

    def consume(self, state_digest):
        return self.values.pop(state_digest, None)


class Http:
    def __init__(self, outcomes=()):
        self.outcomes = list(outcomes)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if callable(outcome):
            outcome = outcome(request)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def response(origin, path, payload, *, status=200, body_bytes=None, elapsed_ms=1):
    return GoogleHttpResponseV1(
        status,
        payload,
        len(str(payload).encode()) if body_bytes is None else body_bytes,
        elapsed_ms,
        origin,
        path,
    )


def token_response(*, scopes=READ_SCOPES, access=ACCESS, refresh=REFRESH):
    return response(
        OAUTH_ORIGIN,
        TOKEN_PATH,
        {
            "access_token": access,
            "refresh_token": refresh,
            "expires_in": 3600,
            "scope": " ".join(scopes),
            "token_type": "Bearer",
        },
    )


def profile_response(account="sir@example.com"):
    return response(GMAIL_ORIGIN, GMAIL_PROFILE_PATH, {"emailAddress": account})


def fixture(outcomes=(), *, monotonic_clock=None):
    binding = GoogleWorkspaceBindingV1("owner-1", "workspace-1", "sir@example.com")
    settings = GoogleOAuthSettingsV1(
        "onyx-desktop-client.apps.googleusercontent.com",
        "http://127.0.0.1:43871/oauth2/callback",
    )
    vault = Vault()
    pending = Pending()
    metadata = InMemoryGoogleGrantMetadataStoreV1()
    http = Http(outcomes)
    options = dict(
        gate=GoogleWorkspaceFeatureGateV1(True),
        settings=settings,
        binding=binding,
        token_resolver=vault,
        token_persister=vault,
        pending_vault=pending,
        metadata_store=metadata,
        transport=http,
        identity_pseudonymizer=IDENTITY,
    )
    if monotonic_clock is not None:
        options["monotonic_clock"] = monotonic_clock
    connector = create_google_workspace_connector_v1(**options)
    assert connector is not None
    return connector, binding, settings, vault, pending, metadata, http


def callback(start, settings, **replace):
    query = parse_qs(urlsplit(start.authorization_url).query)
    fields = {"code": "provider-code", "state": query["state"][0]}
    fields.update(replace)
    return f"{settings.redirect_uri}?{urlencode(fields)}"


def authorize(outcomes=()):
    connector, binding, settings, vault, pending, metadata, http = fixture(
        outcomes or (token_response(), profile_response())
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    receipt = connector.complete_authorization(
        callback(start, settings), now_epoch_s=NOW + 1
    )
    return connector, binding, settings, vault, pending, metadata, http, receipt


def test_default_off_factory_and_exact_read_only_scope_contract():
    _, binding, settings, vault, pending, metadata, http = fixture()
    assert create_google_workspace_connector_v1(
        gate=GoogleWorkspaceFeatureGateV1(False),
        settings=settings,
        binding=binding,
        token_resolver=vault,
        token_persister=vault,
        pending_vault=pending,
        metadata_store=metadata,
        transport=http,
    ) is None
    with pytest.raises(GoogleWorkspaceV1Denied):
        GoogleOAuthSettingsV1(
            settings.client_id,
            settings.redirect_uri,
            ("https://mail.google.com/", READ_SCOPES[1]),
        )


@pytest.mark.parametrize(
    "uri",
    (
        "http://example.com:43871/oauth2/callback",
        "http://127.0.0.1:43871/other",
        "http://127.0.0.1/oauth2/callback",
        "http://user@127.0.0.1:43871/oauth2/callback",
        "http://127.0.0.1:43871/oauth2/callback?x=1",
    ),
)
def test_settings_reject_redirect_drift(uri):
    with pytest.raises(GoogleWorkspaceV1ContractError):
        GoogleOAuthSettingsV1("onyx-client-123", uri)


def test_authorization_start_is_pkce_s256_one_shot_and_no_browser_automation():
    connector, _, settings, _, pending, _, _ = fixture()
    start = connector.begin_authorization(now_epoch_s=NOW)
    parsed = urlsplit(start.authorization_url)
    query = parse_qs(parsed.query)
    assert f"{parsed.scheme}://{parsed.netloc}" == AUTH_ORIGIN
    assert parsed.path == AUTH_PATH
    assert query["code_challenge_method"] == ["S256"]
    assert query["scope"] == [" ".join(READ_SCOPES)]
    assert query["include_granted_scopes"] == ["false"]
    assert query["redirect_uri"] == [settings.redirect_uri]
    assert start.browser_automation is False
    secret = pending.values[start.state_digest]
    assert query["state"] == [secret.state]
    assert secret.code_verifier not in start.authorization_url


def test_callback_exact_redirect_state_and_replay_are_enforced():
    connector, _, settings, _, _, _, _ = fixture((token_response(), profile_response()))
    start = connector.begin_authorization(now_epoch_s=NOW)
    with pytest.raises(GoogleWorkspaceV1Denied, match="redirect"):
        connector.complete_authorization(
            callback(start, settings).replace("127.0.0.1", "localhost"),
            now_epoch_s=NOW + 1,
        )
    start = connector.begin_authorization(now_epoch_s=NOW)
    good = callback(start, settings)
    connector.complete_authorization(good, now_epoch_s=NOW + 1)
    with pytest.raises(GoogleWorkspaceV1Denied, match="absent or replayed"):
        connector.complete_authorization(good, now_epoch_s=NOW + 2)


def test_pending_owner_workspace_binding_drift_fails_before_network():
    connector, _, settings, _, pending, _, http = fixture()
    start = connector.begin_authorization(now_epoch_s=NOW)
    secret = pending.values[start.state_digest]
    pending.values[start.state_digest] = dataclasses.replace(
        secret, binding_digest="0" * 64
    )
    with pytest.raises(GoogleWorkspaceV1Denied, match="binding"):
        connector.complete_authorization(
            callback(start, settings), now_epoch_s=NOW + 1
        )
    assert http.requests == []


def test_granted_scope_drift_fails_before_persistence():
    connector, _, settings, vault, _, _, _ = fixture(
        (token_response(scopes=(READ_SCOPES[0],)),)
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="schema"):
        connector.complete_authorization(callback(start, settings), now_epoch_s=NOW + 1)
    assert vault.tokens == {}


def test_account_drift_fails_and_attempts_provider_revocation_without_persisting():
    connector, _, settings, vault, _, _, http = fixture(
        (
            token_response(),
            profile_response("different@example.com"),
            response(OAUTH_ORIGIN, REVOKE_PATH, {}),
        )
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    with pytest.raises(GoogleWorkspaceV1Denied, match="account binding drift"):
        connector.complete_authorization(callback(start, settings), now_epoch_s=NOW + 1)
    assert vault.tokens == {}
    assert [(r.origin, r.path, r.method) for r in http.requests][-1] == (
        OAUTH_ORIGIN,
        REVOKE_PATH,
        "POST",
    )


def test_connected_status_and_durable_metadata_are_digest_only():
    connector, binding, _, vault, _, metadata, _, receipt = authorize()
    status = connector.status()
    assert status.connected is True
    assert status.binding_digest == binding_digest(binding)
    assert status.raw_tokens_included is False
    record = metadata.get(binding_digest(binding))
    assert record is not None
    serialized = repr(record) + repr(receipt) + repr(status)
    assert ACCESS not in serialized and REFRESH not in serialized
    assert vault.tokens[binding_digest(binding)].digest == record.grant_digest
    with pytest.raises(GoogleWorkspaceV1Denied, match="already connected"):
        connector.begin_authorization(now_epoch_s=NOW + 2)


def test_sqlite_metadata_store_persists_only_digests_expiry_scopes_and_state(tmp_path):
    connector, binding, settings, vault, pending, _, http = fixture(
        (token_response(), profile_response())
    )
    path = (tmp_path / "google.sqlite3").resolve()
    durable = durable_store(path)
    connector = create_google_workspace_connector_v1(
        gate=GoogleWorkspaceFeatureGateV1(True),
        settings=settings,
        binding=binding,
        token_resolver=vault,
        token_persister=vault,
        pending_vault=pending,
        metadata_store=durable,
        transport=http,
        identity_pseudonymizer=IDENTITY,
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    connector.complete_authorization(callback(start, settings), now_epoch_s=NOW + 1)
    reopened = durable_store(path)
    assert reopened.get(binding_digest(binding)).provider_state == "connected"
    raw = (tmp_path / "google.sqlite3").read_bytes()
    seal = (tmp_path / "google.sqlite3.seal").read_bytes()
    durable_bytes = raw + seal
    assert b"owner-1" not in durable_bytes
    assert b"workspace-1" not in durable_bytes
    assert b"sir@example.com" not in durable_bytes
    assert ACCESS.encode() not in durable_bytes
    assert REFRESH.encode() not in durable_bytes
    assert METADATA_KEY not in durable_bytes
    assert hashlib.sha256(b"owner-1").hexdigest().encode() not in durable_bytes
    assert hashlib.sha256(b"workspace-1").hexdigest().encode() not in durable_bytes
    assert hashlib.sha256(b"sir@example.com").hexdigest().encode() not in durable_bytes
    assert IDENTITY.pseudonym("owner", "same") != IDENTITY.pseudonym(
        "workspace", "same"
    )


def test_sqlite_metadata_wrong_key_row_and_head_tampering_fail_closed(tmp_path):
    def create(name):
        connector, binding, settings, vault, pending, _, http = fixture(
            (token_response(), profile_response())
        )
        path = (tmp_path / name).resolve()
        store = durable_store(path)
        connector = create_google_workspace_connector_v1(
            gate=GoogleWorkspaceFeatureGateV1(True),
            settings=settings,
            binding=binding,
            token_resolver=vault,
            token_persister=vault,
            pending_vault=pending,
            metadata_store=store,
            transport=http,
            identity_pseudonymizer=IDENTITY,
        )
        start = connector.begin_authorization(now_epoch_s=NOW)
        connector.complete_authorization(callback(start, settings), now_epoch_s=NOW + 1)
        return path, binding

    wrong_key_path, _ = create("wrong-key.sqlite3")
    with pytest.raises(GoogleWorkspaceV1Denied, match="authentication"):
        durable_store(wrong_key_path, b"x" * 32)

    row_path, _ = create("row.sqlite3")
    with closing(sqlite3.connect(row_path)) as connection:
        connection.execute(
            "UPDATE google_grants_v1 SET provider_state = 'revoked'"
        )
        connection.commit()
    with pytest.raises(GoogleWorkspaceV1Denied, match="row authentication"):
        durable_store(row_path)
    row_path.unlink()  # proves the failed read did not leak a Windows DB handle

    head_path, _ = create("head.sqlite3")
    with closing(sqlite3.connect(head_path)) as connection:
        connection.execute(
            "UPDATE google_grant_head_v1 SET head_digest = ?",
            ("0" * 64,),
        )
        connection.commit()
    with pytest.raises(GoogleWorkspaceV1Denied, match="head authentication"):
        durable_store(head_path)
    head_path.unlink()

    schema_path, _ = create("schema.sqlite3")
    with closing(sqlite3.connect(schema_path)) as connection:
        connection.execute(
            "ALTER TABLE google_grants_v1 RENAME COLUMN row_hmac TO row_mac"
        )
        connection.commit()
    with pytest.raises(GoogleWorkspaceV1Denied, match="schema drift"):
        durable_store(schema_path)
    schema_path.unlink()


@pytest.mark.parametrize(
    "statement",
    (
        "CREATE TABLE unexpected_table (value TEXT)",
        "CREATE INDEX unexpected_index ON google_grants_v1(provider_state)",
        "CREATE TRIGGER unexpected_trigger AFTER INSERT ON google_grants_v1 "
        "BEGIN SELECT 1; END",
        "CREATE VIEW unexpected_view AS SELECT binding_digest FROM google_grants_v1",
    ),
)
def test_sqlite_metadata_exact_application_object_set_rejects_extras(
    tmp_path, statement
):
    path = (tmp_path / "objects.sqlite3").resolve()
    durable_store(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(statement)
        connection.commit()

    with pytest.raises(GoogleWorkspaceV1Denied, match="object-set drift"):
        durable_store(path)

    path.unlink()
    path.with_name(f"{path.name}.seal").unlink()


def test_sqlite_metadata_external_seal_rejects_trailing_container_bytes(tmp_path):
    path = (tmp_path / "trailing.sqlite3").resolve()
    durable_store(path)
    with path.open("ab") as stream:
        stream.write(b"unexpected-trailing-container-data")

    with pytest.raises(GoogleWorkspaceV1Denied, match="container authentication"):
        durable_store(path)

    path.unlink()
    path.with_name(f"{path.name}.seal").unlink()


def test_sqlite_metadata_external_seal_rejects_unreadable_container(tmp_path):
    path = (tmp_path / "unreadable.sqlite3").resolve()
    durable_store(path)
    raw = bytearray(path.read_bytes())
    raw[:16] = b"not-a-sqlite-db!"
    path.write_bytes(raw)

    with pytest.raises(GoogleWorkspaceV1Denied, match="container authentication"):
        durable_store(path)

    path.unlink()
    path.with_name(f"{path.name}.seal").unlink()


def test_sqlite_metadata_missing_malformed_or_orphan_seal_fails_closed(tmp_path):
    missing_path = (tmp_path / "missing.sqlite3").resolve()
    durable_store(missing_path)
    missing_seal = missing_path.with_name(f"{missing_path.name}.seal")
    missing_seal.unlink()
    with pytest.raises(GoogleWorkspaceV1Denied, match="seal is unavailable"):
        durable_store(missing_path)
    missing_path.unlink()

    malformed_path = (tmp_path / "malformed.sqlite3").resolve()
    durable_store(malformed_path)
    malformed_seal = malformed_path.with_name(f"{malformed_path.name}.seal")
    malformed_seal.write_bytes(b"{}")
    with pytest.raises(GoogleWorkspaceV1Denied, match="seal schema drift"):
        durable_store(malformed_path)
    malformed_path.unlink()
    malformed_seal.unlink()

    orphan_path = (tmp_path / "orphan.sqlite3").resolve()
    orphan_path.with_name(f"{orphan_path.name}.seal").write_bytes(b"{}")
    with pytest.raises(GoogleWorkspaceV1Denied, match="orphan"):
        durable_store(orphan_path)
    orphan_path.with_name(f"{orphan_path.name}.seal").unlink()


def test_sqlite_metadata_unexpected_sidecar_fails_closed_and_releases_files(tmp_path):
    path = (tmp_path / "sidecar.sqlite3").resolve()
    durable_store(path)
    seal_path = path.with_name(f"{path.name}.seal")
    sidecar_path = path.with_name(f"{path.name}-wal")
    sidecar_path.write_bytes(b"unexpected")

    with pytest.raises(GoogleWorkspaceV1Denied, match="journal sidecar"):
        durable_store(path)

    sidecar_path.unlink()
    path.unlink()
    seal_path.unlink()


def test_existing_zero_byte_file_is_never_initialized_or_repaired(tmp_path):
    path = (tmp_path / "zero.sqlite3").resolve()
    path.write_bytes(b"")
    before = path.read_bytes()

    with pytest.raises(GoogleWorkspaceV1Denied, match="seal is unavailable"):
        durable_store(path)

    assert path.read_bytes() == before == b""
    path.unlink()


def test_existing_missing_required_object_is_rejected_without_byte_changes(tmp_path):
    path = (tmp_path / "missing-object.sqlite3").resolve()
    durable_store(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("DROP TABLE google_grants_v1")
        connection.commit()
    before = path.read_bytes()

    with pytest.raises(GoogleWorkspaceV1Denied, match="schema drift"):
        durable_store(path)

    assert path.read_bytes() == before


@pytest.mark.parametrize("suffix", ("-wal", "-shm", "-journal"))
def test_every_sqlite_sidecar_fails_closed(tmp_path, suffix):
    path = (tmp_path / f"sidecar-{suffix[1:]}.sqlite3").resolve()
    durable_store(path)
    sidecar = Path(f"{path}{suffix}")
    sidecar.write_bytes(b"unexpected")
    with pytest.raises(GoogleWorkspaceV1Denied, match="journal sidecar"):
        durable_store(path)
    sidecar.unlink()


def test_authenticated_pair_replay_fails_against_trusted_generation_anchor(tmp_path):
    path = (tmp_path / "replay.sqlite3").resolve()
    store = durable_store(path)
    old_database = path.read_bytes()
    seal_path = path.with_name(f"{path.name}.seal")
    old_seal = seal_path.read_bytes()
    store.put(metadata_value("a" * 64))
    path.write_bytes(old_database)
    seal_path.write_bytes(old_seal)

    with pytest.raises(GoogleWorkspaceV1Denied, match="generation anchor drift"):
        durable_store(path)


@pytest.mark.skipif(os.name == "nt", reason="Windows path binding is case-insensitive")
def test_path_binding_preserves_case_on_case_sensitive_platforms(tmp_path):
    upper = (tmp_path / "Case.sqlite3").resolve()
    lower = (tmp_path / "case.sqlite3").resolve()
    durable_store(upper)
    lower.write_bytes(upper.read_bytes())
    lower.with_name(f"{lower.name}.seal").write_bytes(
        upper.with_name(f"{upper.name}.seal").read_bytes()
    )
    with pytest.raises(GoogleWorkspaceV1Denied, match="authentication|drift"):
        durable_store(lower)


def test_post_prepared_seal_replace_failure_is_unknown_and_recoverable(
    tmp_path, monkeypatch
):
    path = (tmp_path / "replace-failure.sqlite3").resolve()
    store = durable_store(path)
    real_replace = store._atomic_replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if Path(destination) == path.with_name(f"{path.name}.seal") and not failed:
            failed = True
            raise OSError("injected secret seal failure")
        return real_replace(source, destination)

    monkeypatch.setattr(store, "_atomic_replace", fail_once)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="reconciliation"):
        store.put(metadata_value("b" * 64))
    monkeypatch.setattr(store, "_atomic_replace", real_replace)

    recovered = durable_store(path)
    assert recovered.get("b" * 64) is not None
    assert not path.with_name(f"{path.name}.journal.auth").exists()


def test_tamper_between_stage_verification_and_seal_publication_is_denied(
    tmp_path, monkeypatch
):
    path = (tmp_path / "interposition.sqlite3").resolve()
    store = durable_store(path)
    original_database = path.read_bytes()
    original = store._write_external_seal

    def tamper(container, *, generation):
        original(container, generation=generation)
        with store._path.open("ab") as stream:
            stream.write(b"tamper")

    monkeypatch.setattr(store, "_write_external_seal", tamper)
    with pytest.raises(GoogleWorkspaceV1Denied, match="container authentication"):
        store.put(metadata_value("c" * 64))
    assert path.read_bytes() == original_database
    assert not path.with_name(f"{path.name}.journal.auth").exists()


def test_two_store_instances_are_linearized(tmp_path):
    path = (tmp_path / "threads.sqlite3").resolve()
    first = durable_store(path)
    second = durable_store(path)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(first.put, metadata_value("d" * 64)),
            executor.submit(second.put, metadata_value("e" * 64)),
        )
        for future in futures:
            future.result()
    reopened = durable_store(path)
    assert reopened.get("d" * 64) is not None
    assert reopened.get("e" * 64) is not None


def test_two_processes_are_linearized(tmp_path):
    path = (tmp_path / "process.sqlite3").resolve()
    anchor_path = tmp_path / "generation.anchor"
    SqliteGoogleGrantMetadataStoreV1(
        path, METADATA_KEY, FileGenerationAnchor(anchor_path)
    )
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    processes = [
        context.Process(
            target=process_put,
            args=(str(path), str(anchor_path), digest, results),
        )
        for digest in ("f" * 64, "0" * 64)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in processes) == ["ok", "ok"]
    reopened = SqliteGoogleGrantMetadataStoreV1(
        path, METADATA_KEY, FileGenerationAnchor(anchor_path)
    )
    assert reopened.get("f" * 64) is not None
    assert reopened.get("0" * 64) is not None


def test_transport_exception_traceback_does_not_chain_secret():
    secret = "provider-secret-in-cause"
    connector, *_ = fixture()
    connector._transport.outcomes.append(RuntimeError(secret))
    request = GoogleHttpRequestV1(
        "GET",
        GMAIL_ORIGIN,
        GMAIL_PROFILE_PATH,
        headers=(("Authorization", "Bearer redacted"),),
    )
    budget = connector._operation_budget(None)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome) as captured:
        connector._send(request, budget)
    rendered = "".join(
        traceback.format_exception(
            type(captured.value), captured.value, captured.value.__traceback__
        )
    )
    assert secret not in rendered


def test_cow_rejects_source_tamper_before_stage_mutation(tmp_path, monkeypatch):
    path = (tmp_path / "source-tamper.sqlite3").resolve()
    store = durable_store(path)
    original = store._write_file_durable

    def interpose(destination, raw):
        if ".stage-" in destination.name:
            with path.open("ab") as stream:
                stream.write(b"tamper-before-copy")
        return original(destination, raw)

    monkeypatch.setattr(store, "_write_file_durable", interpose)
    with pytest.raises(GoogleWorkspaceV1Denied, match="source snapshot changed"):
        store.put(metadata_value("5" * 64))
    assert not path.with_name(f"{path.name}.journal.auth").exists()


def test_cow_rejects_replayed_stage_copy(tmp_path, monkeypatch):
    path = (tmp_path / "copy-replay.sqlite3").resolve()
    store = durable_store(path)
    old_raw = path.read_bytes()
    store.put(metadata_value("6" * 64))
    original = store._write_file_durable

    def replay(destination, raw):
        if ".stage-" in destination.name:
            return original(destination, old_raw)
        return original(destination, raw)

    monkeypatch.setattr(store, "_write_file_durable", replay)
    with pytest.raises(GoogleWorkspaceV1Denied, match="source snapshot changed"):
        store.put(metadata_value("7" * 64))


def test_get_rejects_generation_pair_swap_during_snapshot(tmp_path, monkeypatch):
    path = (tmp_path / "get-swap.sqlite3").resolve()
    store = durable_store(path)
    old_database = path.read_bytes()
    seal_path = path.with_name(f"{path.name}.seal")
    old_seal = seal_path.read_bytes()
    store.put(metadata_value("8" * 64))
    original = store._read_database_bytes
    calls = 0

    def swap_after_read():
        nonlocal calls
        calls += 1
        raw = original()
        if calls == 1:
            path.write_bytes(old_database)
            seal_path.write_bytes(old_seal)
        return raw

    monkeypatch.setattr(store, "_read_database_bytes", swap_after_read)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="snapshot read"):
        store.get("8" * 64)


def test_old_prepared_journal_never_reverts_newer_anchor(tmp_path, monkeypatch):
    path = (tmp_path / "old-journal.sqlite3").resolve()
    anchor = GenerationAnchor()
    store = durable_store(path, anchor=anchor)
    original = store._atomic_replace

    def stop_on_seal(source, destination):
        if Path(destination) == path.with_name(f"{path.name}.seal"):
            raise OSError("stop")
        return original(source, destination)

    monkeypatch.setattr(store, "_atomic_replace", stop_on_seal)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
        store.put(metadata_value("9" * 64))
    reference = next(iter(anchor.values))
    anchor.values[reference] = 9
    before = path.read_bytes()
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="older"):
        SqliteGoogleGrantMetadataStoreV1(path, METADATA_KEY, anchor)
    assert path.read_bytes() == before


@pytest.mark.parametrize("value", (True, False))
def test_anchor_bool_read_is_contract_drift(tmp_path, value):
    class BoolAnchor:
        def read(self, store_reference):
            del store_reference
            return value

        def compare_and_swap(self, store_reference, expected, replacement):
            del store_reference, expected, replacement
            return True

    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="contract drift"):
        SqliteGoogleGrantMetadataStoreV1(
            (tmp_path / f"bool-{value}.sqlite3").resolve(),
            METADATA_KEY,
            BoolAnchor(),
        )


def test_truthy_non_bool_anchor_cas_is_rejected(tmp_path):
    class TruthyAnchor:
        def read(self, store_reference):
            del store_reference
            return None

        def compare_and_swap(self, store_reference, expected, replacement):
            del store_reference, expected, replacement
            return 1

    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="contract drift"):
        SqliteGoogleGrantMetadataStoreV1(
            (tmp_path / "truthy.sqlite3").resolve(), METADATA_KEY, TruthyAnchor()
        )


def test_anchor_and_pseudonymizer_exceptions_do_not_leak_plaintext(tmp_path):
    secret = "secret-capability-payload"

    class RaisingAnchor:
        def read(self, store_reference):
            del store_reference
            raise RuntimeError(secret)

        def compare_and_swap(self, store_reference, expected, replacement):
            del store_reference, expected, replacement
            raise RuntimeError(secret)

    with pytest.raises(GoogleWorkspaceV1UnknownOutcome) as anchor_error:
        SqliteGoogleGrantMetadataStoreV1(
            (tmp_path / "anchor-error.sqlite3").resolve(),
            METADATA_KEY,
            RaisingAnchor(),
        )
    anchor_trace = "".join(
        traceback.format_exception(
            type(anchor_error.value), anchor_error.value, anchor_error.value.__traceback__
        )
    )
    assert anchor_error.value.__cause__ is None
    assert anchor_error.value.__context__ is None
    assert secret not in anchor_trace

    class RaisingIdentity:
        def pseudonym(self, domain, value):
            del domain, value
            raise RuntimeError(secret)

    options = dict(
        gate=GoogleWorkspaceFeatureGateV1(True),
        settings=GoogleOAuthSettingsV1(
            "onyx-desktop-client.apps.googleusercontent.com",
            "http://127.0.0.1:43871/oauth2/callback",
        ),
        binding=GoogleWorkspaceBindingV1(
            "owner-1", "workspace-1", "sir@example.com"
        ),
        token_resolver=Vault(), token_persister=Vault(), pending_vault=Pending(),
        metadata_store=InMemoryGoogleGrantMetadataStoreV1(), transport=Http(),
        identity_pseudonymizer=RaisingIdentity(),
    )
    with pytest.raises(GoogleWorkspaceV1Denied) as identity_error:
        create_google_workspace_connector_v1(**options)
    identity_trace = "".join(traceback.format_exception(
        type(identity_error.value), identity_error.value,
        identity_error.value.__traceback__,
    ))
    assert identity_error.value.__cause__ is None
    assert identity_error.value.__context__ is None
    assert secret not in identity_trace


def test_pseudonymizer_plaintext_and_non_lower_hex_outputs_are_rejected():
    class PlainIdentity:
        def __init__(self, value):
            self.value = value

        def pseudonym(self, domain, value):
            del domain, value
            return self.value

    for output in ("sir@example.com", "A" * 64, "a" * 63):
        connector, binding, settings, vault, pending, metadata, http = fixture()
        del connector
        with pytest.raises(GoogleWorkspaceV1ContractError, match="contract drift"):
            create_google_workspace_connector_v1(
                gate=GoogleWorkspaceFeatureGateV1(True), settings=settings,
                binding=binding, token_resolver=vault, token_persister=vault,
                pending_vault=pending, metadata_store=metadata, transport=http,
                identity_pseudonymizer=PlainIdentity(output),
            )


def test_oversized_recovery_stage_fails_closed_and_keeps_journal(
    tmp_path, monkeypatch
):
    path = (tmp_path / "oversized-recovery.sqlite3").resolve()
    anchor = GenerationAnchor()
    store = durable_store(path, anchor=anchor)
    original = store._atomic_replace

    def stop_on_database(source, destination):
        if Path(destination) == path:
            raise OSError("stop")
        return original(source, destination)

    monkeypatch.setattr(store, "_atomic_replace", stop_on_database)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
        store.put(metadata_value("a" * 64))
    journal_path = path.with_name(f"{path.name}.journal.auth")
    journal = json.loads(journal_path.read_text("ascii"))
    stage = path.parent / journal["staged_database"]
    with stage.open("ab") as stream:
        stream.truncate(16_777_217)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="recovery"):
        SqliteGoogleGrantMetadataStoreV1(path, METADATA_KEY, anchor)
    assert journal_path.exists()


def test_durable_write_flushes_before_atomic_replace(tmp_path, monkeypatch):
    path = (tmp_path / "durability-order.sqlite3").resolve()
    store = durable_store(path)
    events = []
    original_flush = store._flush_descriptor
    original_replace = store._atomic_replace

    def flush(descriptor):
        events.append("flush")
        return original_flush(descriptor)

    def replace(source, destination):
        events.append("replace")
        return original_replace(source, destination)

    monkeypatch.setattr(store, "_flush_descriptor", flush)
    monkeypatch.setattr(store, "_atomic_replace", replace)
    target = tmp_path / "durable-target"
    store._write_file_durable(target, b"durable")
    assert target.read_bytes() == b"durable"
    assert events[:2] == ["flush", "replace"]


@pytest.mark.skipif(os.name != "nt", reason="Windows durability primitive")
def test_windows_write_through_replace_primitive_overwrites_exact_bytes(tmp_path):
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"new")
    destination.write_bytes(b"old")
    SqliteGoogleGrantMetadataStoreV1._atomic_replace(source, destination)
    assert destination.read_bytes() == b"new"
    assert not source.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows API branch")
def test_windows_existing_destination_uses_movefileex_write_through(
    tmp_path, monkeypatch
):
    import ctypes

    calls = []

    class Move:
        argtypes = None
        restype = None

        def __call__(self, source, destination, flags):
            calls.append((source, destination, flags))
            return 1

    class Kernel:
        MoveFileExW = Move()

    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: Kernel())
    source = tmp_path / "mock-source"
    destination = tmp_path / "mock-destination"
    source.write_bytes(b"new")
    destination.write_bytes(b"old")
    SqliteGoogleGrantMetadataStoreV1._atomic_replace(source, destination)
    assert calls == [(str(source), str(destination), 0x1 | 0x8)]


def test_interprocess_lock_times_out_without_blocking_forever(tmp_path):
    lock_path = tmp_path / "busy.lock"
    with _exclusive_file_lock(lock_path):
        with pytest.raises(GoogleWorkspaceV1Denied, match="lock timeout"):
            with _exclusive_file_lock(lock_path, timeout_seconds=0.02):
                pytest.fail("contended lock must not be entered")


def test_head_sequence_must_equal_authenticated_seal_generation(tmp_path):
    path = (tmp_path / "generation-equality.sqlite3").resolve()
    store = durable_store(path)
    seal_path = path.with_name(f"{path.name}.seal")
    document = json.loads(seal_path.read_text("ascii"))
    document["generation"] = 1
    payload = dict(document)
    payload.pop("manifest_hmac")
    document["manifest_hmac"] = store._mac(payload)
    seal_path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("ascii")
    )
    with pytest.raises(GoogleWorkspaceV1Denied, match="head and seal generation"):
        durable_store(path)


@pytest.mark.parametrize("artifact", ("database", "seal", "lock"))
def test_hardlinked_canonical_artifacts_fail_closed_without_mutation(
    tmp_path, artifact
):
    path = (tmp_path / f"hardlink-{artifact}.sqlite3").resolve()
    durable_store(path)
    selected = {
        "database": path,
        "seal": path.with_name(f"{path.name}.seal"),
        "lock": path.with_name(f"{path.name}.lock"),
    }[artifact]
    alias = tmp_path / f"{artifact}.alias"
    os.link(selected, alias)
    database_before = path.read_bytes()
    seal_before = path.with_name(f"{path.name}.seal").read_bytes()
    with pytest.raises(GoogleWorkspaceV1Denied, match="link|identity"):
        durable_store(path)
    assert path.read_bytes() == database_before
    assert path.with_name(f"{path.name}.seal").read_bytes() == seal_before
    alias.unlink()


def test_hardlinked_prepared_stage_and_journal_fail_closed_and_keep_recovery(
    tmp_path, monkeypatch
):
    path = (tmp_path / "hardlink-recovery.sqlite3").resolve()
    anchor = GenerationAnchor()
    store = durable_store(path, anchor=anchor)
    original = store._atomic_replace

    def stop(source, destination):
        if Path(destination) == path:
            raise OSError("stop")
        return original(source, destination)

    monkeypatch.setattr(store, "_atomic_replace", stop)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
        store.put(metadata_value("b" * 64))
    journal_path = path.with_name(f"{path.name}.journal.auth")
    journal = json.loads(journal_path.read_text("ascii"))
    stage = path.parent / journal["staged_database"]
    stage_alias = tmp_path / "stage.alias"
    os.link(stage, stage_alias)
    before = path.read_bytes()
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="recovery"):
        SqliteGoogleGrantMetadataStoreV1(path, METADATA_KEY, anchor)
    assert path.read_bytes() == before
    assert journal_path.exists()
    stage_alias.unlink()
    journal_alias = tmp_path / "journal.alias"
    os.link(journal_path, journal_alias)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="journal"):
        SqliteGoogleGrantMetadataStoreV1(path, METADATA_KEY, anchor)
    assert journal_path.exists()
    journal_alias.unlink()


PORT_SECRET = "external-port-secret-payload"


def assert_clean_external_failure(operation, error_type, match):
    with pytest.raises(error_type, match=match) as captured:
        operation()
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    rendered = "".join(traceback.format_exception(
        type(captured.value), captured.value, captured.value.__traceback__
    ))
    assert PORT_SECRET not in rendered


class ExplodingPorts:
    def resolve(self, binding_digest):
        del binding_digest
        raise RuntimeError(PORT_SECRET)

    def compare_and_set(self, binding_digest, expected_digest, value):
        del binding_digest, expected_digest, value
        raise RuntimeError(PORT_SECRET)

    def delete(self, binding_digest, expected_digest):
        del binding_digest, expected_digest
        raise RuntimeError(PORT_SECRET)

    def get(self, binding_digest):
        del binding_digest
        raise RuntimeError(PORT_SECRET)

    def put(self, value):
        del value
        raise RuntimeError(PORT_SECRET)

    def store(self, state_digest, value):
        del state_digest, value
        raise RuntimeError(PORT_SECRET)

    def consume(self, state_digest):
        del state_digest
        raise RuntimeError(PORT_SECRET)

    def send(self, request):
        del request
        raise RuntimeError(PORT_SECRET)


def test_status_resolver_and_metadata_boundaries_are_fully_sanitized():
    connector, *_ = fixture()
    connector._resolver = ExplodingPorts()
    assert_clean_external_failure(
        connector.status, GoogleWorkspaceV1Denied, "token resolver capability"
    )
    connector, *_ = fixture()
    connector._metadata = ExplodingPorts()
    assert_clean_external_failure(
        connector.status, GoogleWorkspaceV1Denied, "metadata capability"
    )


def test_pending_store_and_consume_boundaries_are_fully_sanitized():
    connector, *_ = fixture()
    connector._pending = ExplodingPorts()
    assert_clean_external_failure(
        lambda: connector.begin_authorization(now_epoch_s=NOW),
        GoogleWorkspaceV1UnknownOutcome,
        "pending authorization persistence",
    )
    connector, _, settings, _, _, _, _ = fixture()
    start = connector.begin_authorization(now_epoch_s=NOW)
    connector._pending = ExplodingPorts()
    assert_clean_external_failure(
        lambda: connector.complete_authorization(
            callback(start, settings), now_epoch_s=NOW + 1
        ),
        GoogleWorkspaceV1UnknownOutcome,
        "pending authorization consume",
    )


def test_connect_transport_persister_and_metadata_boundaries_are_sanitized():
    connector, _, settings, _, _, _, _ = fixture()
    start = connector.begin_authorization(now_epoch_s=NOW)
    connector._transport = ExplodingPorts()
    assert_clean_external_failure(
        lambda: connector.complete_authorization(
            callback(start, settings), now_epoch_s=NOW + 1
        ),
        GoogleWorkspaceV1UnknownOutcome,
        "transport outcome",
    )

    connector, _, settings, _, _, _, _ = fixture(
        (token_response(), profile_response())
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    connector._persister = ExplodingPorts()
    assert_clean_external_failure(
        lambda: connector.complete_authorization(
            callback(start, settings), now_epoch_s=NOW + 1
        ),
        GoogleWorkspaceV1UnknownOutcome,
        "token persistence",
    )

    class PutExplodes:
        def get(self, binding_digest):
            del binding_digest
            return None

        def put(self, value):
            del value
            raise RuntimeError(PORT_SECRET)

    connector, _, settings, _, _, _, _ = fixture(
        (token_response(), profile_response())
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    connector._metadata = PutExplodes()
    assert_clean_external_failure(
        lambda: connector.complete_authorization(
            callback(start, settings), now_epoch_s=NOW + 1
        ),
        GoogleWorkspaceV1UnknownOutcome,
        "metadata persistence",
    )


def test_refresh_and_revoke_persister_boundaries_are_fully_sanitized():
    connector, _, _, _, _, _, http, _ = authorize()
    connector._persister = ExplodingPorts()
    http.outcomes.append(response(
        OAUTH_ORIGIN,
        TOKEN_PATH,
        {
            "access_token": "refreshed-access",
            "expires_in": 3600,
            "scope": " ".join(READ_SCOPES),
            "token_type": "Bearer",
        },
    ))
    assert_clean_external_failure(
        lambda: connector.list_gmail_messages(now_epoch_s=NOW + 4000),
        GoogleWorkspaceV1UnknownOutcome,
        "token persistence",
    )

    connector, _, _, _, _, _, http, _ = authorize()
    connector._persister = ExplodingPorts()
    http.outcomes.append(response(OAUTH_ORIGIN, REVOKE_PATH, {}))
    assert_clean_external_failure(
        lambda: connector.revoke(now_epoch_s=NOW + 2),
        GoogleWorkspaceV1UnknownOutcome,
        "token deletion",
    )


def test_gmail_pagination_is_bounded_and_receipt_has_no_query_or_tokens():
    connector, _, _, _, _, _, http, _ = authorize()
    http.outcomes.extend(
        (
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "m1", "threadId": "t1"}], "nextPageToken": "p2"},
            ),
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "m2", "threadId": "t2"}]},
            ),
        )
    )
    result = connector.list_gmail_messages(
        query="is:unread from:private@example.com", now_epoch_s=NOW + 2
    )
    assert result.items == (
        {"id": "m1", "thread_id": "t1"},
        {"id": "m2", "thread_id": "t2"},
    )
    assert result.has_more is False
    assert result.receipt.page_count == 2
    serialized = repr(result.receipt)
    assert "private@example.com" not in serialized
    assert ACCESS not in serialized and REFRESH not in serialized
    assert all(request.method == "GET" for request in http.requests[-2:])


def test_pagination_token_replay_fails_closed():
    connector, _, _, _, _, _, http, _ = authorize()
    repeated = {"messages": [], "nextPageToken": "same"}
    http.outcomes.extend(
        (
            response(GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, repeated),
            response(GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, repeated),
        )
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="pagination replay"):
        connector.list_gmail_messages(now_epoch_s=NOW + 2)


def test_duplicate_item_id_across_pages_is_reconciliation_required():
    connector, binding, _, _, _, metadata, http, _ = authorize()
    http.outcomes.extend(
        (
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "same", "threadId": "t1"}], "nextPageToken": "p2"},
            ),
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "same", "threadId": "t2"}]},
            ),
        )
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="duplicate item"):
        connector.list_gmail_messages(now_epoch_s=NOW + 2)
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"


def test_calendar_uses_only_fixed_primary_get_path_and_projects_bounded_fields():
    connector, _, _, _, _, _, http, _ = authorize()
    http.outcomes.append(
        response(
            CALENDAR_ORIGIN,
            CALENDAR_EVENTS_PATH,
            {
                "items": [
                    {
                        "id": "event-1",
                        "summary": "Standup",
                        "start": {"dateTime": "2033-05-18T14:00:00Z"},
                        "end": {"dateTime": "2033-05-18T14:30:00Z"},
                        "creator": {"email": "not-projected@example.com"},
                    }
                ]
            },
        )
    )
    result = connector.list_calendar_events(
        time_min="2033-05-18T00:00:00Z",
        time_max="2033-05-19T00:00:00Z",
        now_epoch_s=NOW + 2,
    )
    assert result.items[0]["id"] == "event-1"
    assert "creator" not in result.items[0]
    request = http.requests[-1]
    assert (request.origin, request.path, request.method) == (
        CALENDAR_ORIGIN,
        CALENDAR_EVENTS_PATH,
        "GET",
    )


@pytest.mark.parametrize(
    "time_min,time_max",
    (
        ("2033-05-18 00:00:00Z", "2033-05-19T00:00:00Z"),
        ("2033-05-18T00:00:00", "2033-05-19T00:00:00Z"),
        ("2033-05-18", "2033-05-19T00:00:00Z"),
        ("2033-05-19T00:00:00Z", "2033-05-18T00:00:00Z"),
    ),
)
def test_calendar_query_requires_strict_ordered_rfc3339_datetimes(
    time_min, time_max
):
    connector, *_ = authorize()
    with pytest.raises(GoogleWorkspaceV1ContractError):
        connector.list_calendar_events(
            time_min=time_min,
            time_max=time_max,
            now_epoch_s=NOW + 2,
        )


@pytest.mark.parametrize(
    "start,end",
    (
        ({"dateTime": "2033-05-18 14:00:00Z"}, {"dateTime": "2033-05-18T15:00:00Z"}),
        ({"dateTime": "2033-05-18T14:00:00"}, {"dateTime": "2033-05-18T15:00:00Z"}),
        ({"date": "2033-02-29"}, {"date": "2033-03-01"}),
        ({"date": "2033-05-20"}, {"date": "2033-05-19"}),
        ({"date": "2033-05-18"}, {"dateTime": "2033-05-19T00:00:00Z"}),
        ({"dateTime": "2033-05-18T15:00:00Z"}, {"dateTime": "2033-05-18T14:00:00Z"}),
    ),
)
def test_provider_event_time_schema_and_ordering_drift_require_reconciliation(
    start, end
):
    connector, binding, _, _, _, metadata, http, _ = authorize()
    http.outcomes.append(
        response(
            CALENDAR_ORIGIN,
            CALENDAR_EVENTS_PATH,
            {"items": [{"id": "event-invalid", "start": start, "end": end}]},
        )
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="item schema"):
        connector.list_calendar_events(
            time_min="2033-05-18T00:00:00Z",
            time_max="2033-05-21T00:00:00Z",
            now_epoch_s=NOW + 2,
        )
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"


@pytest.mark.parametrize(
    "outcome,match",
    (
        (
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": []},
                body_bytes=2049,
            ),
            "response budget",
        ),
        (
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": []},
                elapsed_ms=1001,
            ),
            "deadline",
        ),
    ),
)
def test_response_byte_and_time_budgets_fail_closed(outcome, match):
    connector, _, _, _, _, _, http, _ = authorize()
    http.outcomes.append(outcome)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match=match):
        connector.list_gmail_messages(
            now_epoch_s=NOW + 2,
            budget=GoogleWorkspaceBudgetV1(
                maximum_response_bytes=2048,
                timeout_seconds=1.0,
            ),
        )


def test_authorization_uses_one_request_budget_for_token_profile_and_cleanup():
    connector, binding, settings, vault, _, metadata, http = fixture(
        (token_response(),)
    )
    start = connector.begin_authorization(now_epoch_s=NOW)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="cleanup"):
        connector.complete_authorization(
            callback(start, settings),
            now_epoch_s=NOW + 1,
            budget=GoogleWorkspaceBudgetV1(maximum_requests=1),
        )
    assert len(http.requests) == 1
    assert vault.tokens == {}
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"


def test_aggregate_response_bytes_are_shared_across_pages():
    connector, binding, _, _, _, metadata, http, _ = authorize()
    http.outcomes.extend(
        (
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "m1", "threadId": "t1"}], "nextPageToken": "p2"},
                body_bytes=600,
            ),
            response(
                GMAIL_ORIGIN,
                GMAIL_MESSAGES_PATH,
                {"messages": [{"id": "m2", "threadId": "t2"}]},
                body_bytes=500,
            ),
        )
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="response budget"):
        connector.list_gmail_messages(
            now_epoch_s=NOW + 2,
            budget=GoogleWorkspaceBudgetV1(maximum_response_bytes=1000),
        )
    assert len(http.requests) == 4
    assert http.requests[-1].maximum_response_bytes == 400
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"


def test_operation_uses_one_monotonic_deadline_across_transport():
    connector, binding, _, _, _, metadata, http, _ = authorize()
    readings = iter((0.0, 0.0, 2.0))
    connector._clock = lambda: next(readings)
    http.outcomes.append(
        response(GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, {"messages": []}, elapsed_ms=0)
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="deadline"):
        connector.list_gmail_messages(
            now_epoch_s=NOW + 2,
            budget=GoogleWorkspaceBudgetV1(timeout_seconds=1.0),
        )
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"


def test_get_token_generation_drift_after_response_returns_no_stale_data():
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    expected = vault.tokens[binding_digest(binding)]

    def drift_after_dispatch(_request):
        vault.tokens[binding_digest(binding)] = dataclasses.replace(
            expected, access_token="rotated-concurrently", generation=2
        )
        return response(
            GMAIL_ORIGIN,
            GMAIL_MESSAGES_PATH,
            {"messages": [{"id": "must-not-return", "threadId": "t1"}]},
        )

    http.outcomes.append(drift_after_dispatch)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="generation"):
        connector.list_gmail_messages(now_epoch_s=NOW + 2)
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
    assert len(http.requests) == 3


def test_provider_status_and_schema_drift_after_get_require_reconciliation():
    for outcome in (
        response(GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, {}, status=503),
        response(GMAIL_ORIGIN, GMAIL_MESSAGES_PATH, {"messages": "not-a-list"}),
    ):
        connector, binding, _, _, _, metadata, http, _ = authorize()
        http.outcomes.append(outcome)
        with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
            connector.list_gmail_messages(now_epoch_s=NOW + 2)
        assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
        with pytest.raises(GoogleWorkspaceV1Denied, match="reconciliation"):
            connector.list_gmail_messages(now_epoch_s=NOW + 3)


def test_refresh_token_toctou_denies_api_dispatch_and_does_not_overwrite_new_generation():
    connector, binding, _, vault, _, _, http, _ = authorize()
    expiring = vault.tokens[binding_digest(binding)]

    def mutate_vault(_request):
        vault.tokens[binding_digest(binding)] = dataclasses.replace(
            expiring, access_token="parallel-access", generation=99
        )
        return response(
            OAUTH_ORIGIN,
            TOKEN_PATH,
            {
                "access_token": "refreshed-access",
                "expires_in": 3600,
                "scope": " ".join(READ_SCOPES),
                "token_type": "Bearer",
            },
        )

    http.outcomes.append(mutate_vault)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="generation"):
        connector.list_gmail_messages(now_epoch_s=NOW + 4000)
    assert vault.tokens[binding_digest(binding)].generation == 99
    assert len(http.requests) == 3  # authorize token + profile + refresh; no Gmail GET


def test_refresh_unknown_outcome_is_recorded_and_never_retried():
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    http.outcomes.append(TimeoutError("provider secret"))
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome) as captured:
        connector.list_gmail_messages(now_epoch_s=NOW + 4000)
    assert "provider secret" not in str(captured.value)
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
    assert len(http.requests) == 3


@pytest.mark.parametrize(
    "outcome",
    (
        response(OAUTH_ORIGIN, TOKEN_PATH, {"error": "invalid_grant"}, status=400),
        response(
            OAUTH_ORIGIN,
            TOKEN_PATH,
            {
                "access_token": "new",
                "expires_in": "not-an-int",
                "scope": " ".join(READ_SCOPES),
                "token_type": "Bearer",
            },
        ),
    ),
)
def test_refresh_status_and_schema_drift_are_attempted_unknown(outcome):
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    original = vault.tokens[binding_digest(binding)]
    http.outcomes.append(outcome)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
        connector.list_gmail_messages(now_epoch_s=NOW + 4000)
    assert vault.tokens[binding_digest(binding)].digest == original.digest
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
    assert len(http.requests) == 3


def test_revoke_requires_provider_success_then_exact_vault_delete():
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    http.outcomes.append(response(OAUTH_ORIGIN, REVOKE_PATH, {}))
    receipt = connector.revoke(now_epoch_s=NOW + 2)
    assert receipt.status == "revoked"
    assert binding_digest(binding) not in vault.tokens
    assert metadata.get(binding_digest(binding)).provider_state == "revoked"
    assert (http.requests[-1].origin, http.requests[-1].path) == (
        OAUTH_ORIGIN,
        REVOKE_PATH,
    )


def test_revoke_transport_unknown_is_not_retried_and_state_is_uncertain():
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    http.outcomes.append(TimeoutError("secret provider detail"))
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome) as captured:
        connector.revoke(now_epoch_s=NOW + 2)
    assert "secret provider detail" not in str(captured.value)
    assert binding_digest(binding) in vault.tokens
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
    assert len(http.requests) == 3


@pytest.mark.parametrize(
    "outcome",
    (
        response(OAUTH_ORIGIN, REVOKE_PATH, {"error": "invalid_token"}, status=400),
        response(OAUTH_ORIGIN, REVOKE_PATH, {"unexpected": True}, status=200),
    ),
)
def test_revoke_status_and_schema_drift_are_attempted_unknown(outcome):
    connector, binding, _, vault, _, metadata, http, _ = authorize()
    http.outcomes.append(outcome)
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome):
        connector.revoke(now_epoch_s=NOW + 2)
    assert binding_digest(binding) in vault.tokens
    assert metadata.get(binding_digest(binding)).provider_state == "attempted_unknown"
    assert len(http.requests) == 3


def test_redirect_response_origin_drift_and_provider_secrets_are_rejected_or_redacted():
    connector, _, _, _, _, _, http, _ = authorize()
    http.outcomes.append(
        response("https://evil.example", GMAIL_MESSAGES_PATH, {"messages": []})
    )
    with pytest.raises(GoogleWorkspaceV1UnknownOutcome, match="origin"):
        connector.list_gmail_messages(now_epoch_s=NOW + 2)
    start = repr(http.requests[-1])
    assert ACCESS not in start  # request repr is deliberately redacted


def test_http_contract_rejects_header_injection_and_redirect_enabling():
    with pytest.raises(GoogleWorkspaceV1ContractError, match="headers"):
        GoogleHttpRequestV1(
            "GET",
            GMAIL_ORIGIN,
            GMAIL_MESSAGES_PATH,
            headers=(("Authorization", "Bearer okay\r\nX-Evil: yes"),),
        )
    with pytest.raises(GoogleWorkspaceV1Denied, match="redirects"):
        GoogleHttpRequestV1(
            "GET",
            GMAIL_ORIGIN,
            GMAIL_MESSAGES_PATH,
            follow_redirects=True,
        )


def test_no_write_delete_send_or_worker_surface_exists():
    connector, *_ = fixture()
    forbidden = {
        "send_email",
        "create_event",
        "update_event",
        "delete_event",
        "start_worker",
        "poll",
        "watch",
    }
    assert forbidden.isdisjoint(dir(connector))
