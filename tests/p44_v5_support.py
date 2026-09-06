"""Import-stable helpers for P4.4 tests and Windows spawn workers.

This deliberately lives as a uniquely named top-level test module. It avoids
the ambiguous ``tests.*`` package name, which may be owned by a dependency in
clean or user-site Python environments and is re-imported by multiprocessing.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from core.control_plane_v5 import MissionScope, V4AuthorityStatus


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def accept_test_audit(_contract: object, event_hash: str) -> bool:
    return event_hash == digest("audit")


class Vault:
    def __init__(self):
        self.value: bytes | None = None

    def get_bytes(self) -> bytes | None:
        return self.value

    def set_bytes(self, value: bytes | bytearray) -> None:
        self.value = bytes(value)

    def delete(self) -> bool:
        existed = self.value is not None
        self.value = None
        return existed


@dataclass
class Authority:
    root: str = digest("v4-root")

    def status(self) -> V4AuthorityStatus:
        return V4AuthorityStatus(
            "accepted-v4", 4, digest("v4-schema"), self.root, 12
        )

    def read_scope(self, workspace_id: str, mission_id: str) -> MissionScope:
        if workspace_id not in {"workspace-a", "workspace-b"}:
            raise RuntimeError("unknown")
        if mission_id != f"mission-{workspace_id[-1]}":
            raise RuntimeError("cross-scope")
        return MissionScope(
            workspace_id,
            mission_id,
            f"correlation-{workspace_id[-1]}",
            3,
            digest(f"context-{workspace_id}"),
            self.root,
        )
