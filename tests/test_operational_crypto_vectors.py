from __future__ import annotations

import hashlib
import json

from core import control_plane_v3


def _encode(value: object) -> bytes:
    if value is None:
        return b"N"
    if type(value) is int:
        payload = str(value).encode("ascii")
        return b"I" + len(payload).to_bytes(8, "big") + payload
    if isinstance(value, bytes):
        return b"B" + len(value).to_bytes(8, "big") + value
    if isinstance(value, str):
        payload = value.encode("utf-8")
        return b"S" + len(payload).to_bytes(8, "big") + payload
    raise TypeError(type(value).__name__)


def _digest(domain: bytes, values: tuple[object, ...]) -> str:
    value = hashlib.sha256(domain)
    for item in values:
        value.update(_encode(item))
    return value.hexdigest()


def _entry_leaf(index: int, table: str, identity: str, row_hash: str) -> str:
    return _digest(
        b"ONYX-V3-ENTRY-MERKLE-LEAF-V1\0",
        (index, table, identity, row_hash),
    )


def _entry_parent(left: str, right: str) -> str:
    return hashlib.sha256(
        b"ONYX-V3-ENTRY-MERKLE-NODE-V1\0"
        + bytes.fromhex(left)
        + bytes.fromhex(right)
    ).hexdigest()


def _entry_tree(entries: tuple[tuple[str, str, str], ...]) -> tuple[str, tuple[str, ...]]:
    leaves = tuple(_entry_leaf(index, *entry) for index, entry in enumerate(entries))
    level = list(leaves)
    while len(level) > 1:
        level = [
            _entry_parent(level[index], level[index + 1] if index + 1 < len(level) else level[index])
            for index in range(0, len(level), 2)
        ]
    return level[0], leaves


def _json_hash(domain: bytes, values: list[object]) -> str:
    payload = json.dumps(values, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(domain + payload).hexdigest()


def _mmr_parent(height: int, left: str, right: str) -> str:
    return _digest(b"ONYX-V3-MMR-NODE-V1\0", (height, left, right))


def _mmr_bag(peaks: tuple[tuple[int, str], ...]) -> str:
    value = hashlib.sha256(b"ONYX-V3-MMR-PEAKS-V1\0")
    for height, peak in peaks:
        value.update(_encode(height))
        value.update(_encode(peak))
    value.update(_encode(len(peaks)))
    return value.hexdigest()


def _reference_vectors() -> dict[str, str]:
    entries = (
        ("artifact_index", '["artifact-vector"]', "11" * 32),
        ("evidence_records", '["evidence-vector"]', "22" * 32),
        ("event_envelopes", '["event-vector"]', "33" * 32),
    )
    merkle_root, leaves = _entry_tree(entries)
    delta = _digest(
        b"ONYX-V3-OPERATIONAL-DELTA-V1\0",
        tuple(item for entry in entries for item in entry) + (len(entries),),
    )
    values = [
        3, "44" * 32, "55" * 32, "db-vector", "66" * 32, delta,
        "77" * 32, merkle_root, len(entries), 42, 7,
        "2026-07-15T12:34:56+00:00",
    ]
    payload_root = _json_hash(b"ONYX-V3-OPERATIONAL-PAYLOAD-V2\0", values)
    commit_id = _json_hash(
        b"ONYX-V3-OPERATIONAL-COMMIT-V1\0",
        [payload_root, 3, "44" * 32, delta, "2026-07-15T12:34:56+00:00"],
    )
    mmr_leaf = _digest(b"ONYX-V3-MMR-LEAF-V1\0", (commit_id, 3, payload_root))
    parent = _mmr_parent(1, "88" * 32, mmr_leaf)
    mmr_root = _mmr_bag(((1, parent), (0, "99" * 32)))
    state_root = _json_hash(
        b"ONYX-V3-OPERATIONAL-ROOT-V2\0",
        values[:8] + [mmr_root, 3] + values[8:],
    )
    return {
        "entry_leaf_0": leaves[0],
        "entry_leaf_2": leaves[2],
        "entry_merkle_odd_root": merkle_root,
        "delta": delta,
        "payload_root": payload_root,
        "commit_id": commit_id,
        "mmr_leaf": mmr_leaf,
        "mmr_parent": parent,
        "mmr_peaks_root": mmr_root,
        "state_root": state_root,
    }


EXPECTED = {
    "commit_id": "5b2c5a5996732eacdd64fb3601f337d839f6c4a321d8b00d9874c8352235f5de",
    "delta": "b496c44fdde85bd2ada15a68b07e8c21cdffa646640ec83fecb78100cca23cbe",
    "entry_leaf_0": "12109e8913d192932dc5a3e3ab8f5741cf3089a90f455d0fcba85a4113155f6d",
    "entry_leaf_2": "a90070b57a4768c4047f339c78f8c3f9471af90e58e77b819507dfa1183cb577",
    "entry_merkle_odd_root": "2d58933996f9fadf23113e76b229c56f40f7bc72e1c5294dc0a727019dbfa9a9",
    "mmr_leaf": "eca0cd17e93307d150dcbb4bc34ee1e0ccaf7d01dd7359ad6dd1773a85ce65cd",
    "mmr_parent": "5b24ac2e1e89f9a79f18f2843b8e927134d93cacfd7085c124a5a0e49bebea47",
    "mmr_peaks_root": "5d9936c53a501fe4c46b29614aabd38396269d7f2d66268f8c56db2e98a944a4",
    "payload_root": "e6417e2d82495445132e4a64243afda7fac8f347105c74761504284e06b7dd0c",
    "state_root": "bbd39e139bd4e859b86c25da9269fc165b75422f554433ea8ef5992fc2d7d94b",
}
EXPECTED_SCHEMA_FINGERPRINT = "b914d4768809c5513199175c2ee40294b3198ea92bd33cd0637818cf6242affa"


def test_independent_operational_crypto_fixed_vectors():
    reference = _reference_vectors()
    assert reference == EXPECTED

    entries = (
        ("artifact_index", '["artifact-vector"]', "11" * 32),
        ("evidence_records", '["evidence-vector"]', "22" * 32),
        ("event_envelopes", '["event-vector"]', "33" * 32),
    )
    production_root, production_leaves, _nodes = control_plane_v3._entry_merkle_tree(entries)
    assert production_leaves[0] == reference["entry_leaf_0"]
    assert production_leaves[2] == reference["entry_leaf_2"]
    assert production_root == reference["entry_merkle_odd_root"]
    delta = control_plane_v3._operational_delta_digest(entries)
    assert delta == reference["delta"]
    payload = control_plane_v3._operational_payload_root(
        sequence=3,
        previous_commit_id="44" * 32,
        previous_state_root="55" * 32,
        database_id="db-vector",
        fingerprint="66" * 32,
        delta_sha256=delta,
        genesis_baseline_root="77" * 32,
        entry_merkle_root=production_root,
        entry_count=3,
        canonical_row_count=42,
        event_count=7,
        created_at="2026-07-15T12:34:56+00:00",
    )
    assert payload == reference["payload_root"]
    commit = control_plane_v3._operational_commit_id(
        state_root=payload,
        sequence=3,
        previous_commit_id="44" * 32,
        delta_sha256=delta,
        created_at="2026-07-15T12:34:56+00:00",
    )
    assert commit == reference["commit_id"]
    leaf = control_plane_v3._mmr_leaf(commit, 3, payload)
    assert leaf == reference["mmr_leaf"]
    parent = control_plane_v3._mmr_parent(1, "88" * 32, leaf)
    assert parent == reference["mmr_parent"]
    mmr_root = control_plane_v3._mmr_bag(((1, parent), (0, "99" * 32)))
    assert mmr_root == reference["mmr_peaks_root"]
    assert control_plane_v3._operational_state_root(
        sequence=3,
        previous_commit_id="44" * 32,
        previous_state_root="55" * 32,
        database_id="db-vector",
        fingerprint="66" * 32,
        delta_sha256=delta,
        genesis_baseline_root="77" * 32,
        entry_merkle_root=production_root,
        mmr_root=mmr_root,
        mmr_size=3,
        entry_count=3,
        canonical_row_count=42,
        event_count=7,
        created_at="2026-07-15T12:34:56+00:00",
    ) == reference["state_root"]


def test_schema_domain_version_vector():
    assert control_plane_v3.V3_SCHEMA_VERSION == 3
    assert control_plane_v3._v3_fingerprint() == EXPECTED_SCHEMA_FINGERPRINT
