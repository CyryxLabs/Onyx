"""Authenticated, read-only AEXOS process boundary for Onyx.

This adapter exposes discovery and planning metadata only. It deliberately does
not invoke external executors, mutate projects, install packages or broaden an
Onyx mission. Executable work remains owned by the existing governed mission
and external-agent boundaries.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Final, Mapping, Sequence


SCHEMA: Final = "OnyxAexosEngineAdapter.v1"
EXPECTED_VERSION: Final = "5.3.0"
EXPECTED_COMMIT: Final = "5342f5a7c1ab6212087da2011265c11f1002503f"
EXPECTED_FILES: Final = {
    "bin/aexos.js": "33435b5e28e91f222819c49358eb87dbbee44d66a81f3023afbfaafbacf05190",
    "package.json": "9cd9c7dcecf86855cca7bbd42c393d8b29c8d67a16a29d55905b65da62469e55",
    ".aexos-core/data/squad-registry.yaml": "cd325a8a5e56d896e7121395f459cf6bab57109824c0860561e8bfbcbd8b2904",
}
BUNDLED_VENDOR_RELATIVE: Final = Path("vendor/aexos-engine-5.3.0")
BUNDLED_NODE_SHA256: Final = (
    "3331e1ffe19874215472217c5e94f5a0c6d8e18c4ac7111d3937aa0ad5e9b4a5"
)
MAX_QUERY_CHARS: Final = 500
MAX_OUTPUT_BYTES: Final = 2_000_000
_STORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_UNTRUSTED_INSTRUCTION = (
    re.compile(r"\bignore (?:all |the )?(?:previous|prior) instructions?\b", re.I),
    re.compile(r"\b(?:system|developer) message\s*:", re.I),
    re.compile(r"(?:^|\s)(?:cmd|powershell|bash|sh)\s+-", re.I),
)


class AexosEngineAdapterV1Error(RuntimeError):
    pass


class AexosEngineAdapterV1ContractError(ValueError):
    pass


class AexosEngineAdapterV1Denied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class AexosBudgetEnvelopeV1:
    story_id: str
    budget_ceiling_micro_usd: int
    timeout_seconds: int = 15

    def __post_init__(self) -> None:
        if type(self.story_id) is not str or _STORY.fullmatch(self.story_id) is None:
            raise AexosEngineAdapterV1ContractError("story_id is invalid")
        if (
            type(self.budget_ceiling_micro_usd) is not int
            or self.budget_ceiling_micro_usd < 0
        ):
            raise AexosEngineAdapterV1ContractError("budget ceiling is invalid")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise AexosEngineAdapterV1ContractError("timeout is outside its bound")


@dataclass(frozen=True, slots=True)
class AexosAttestationV1:
    schema: str
    available: bool
    reason_code: str
    version: str | None
    expected_commit: str
    artifact_digests: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class AexosDiscoveryReceiptV1:
    status: str
    story_id: str
    budget_ceiling_micro_usd: int
    query_sha256: str
    result: object
    provider_called: bool = False
    model_called: bool = False
    mutation_performed: bool = False


Runner = Callable[[Sequence[str], Path, int, Mapping[str, str]], tuple[int, bytes, bytes]]


def _default_runner(
    command: Sequence[str], cwd: Path, timeout: int, environment: Mapping[str, str]
) -> tuple[int, bytes, bytes]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=dict(environment),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AexosEngineAdapterV1:
    """Verify and query an exact Cyryx AEXOS installation."""

    def __init__(
        self,
        root: Path | str,
        *,
        node_executable: Path | str = "node",
        runner: Runner = _default_runner,
    ) -> None:
        lexical = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        if not lexical.is_absolute():
            raise AexosEngineAdapterV1ContractError("AEXOS root must be absolute")
        current = Path(lexical.anchor)
        for component in lexical.parts[1:]:
            current /= component
            if current.exists() and current.is_symlink():
                raise AexosEngineAdapterV1Denied("linked AEXOS path is denied")
        self._root = lexical
        self._node = os.fspath(node_executable)
        self._node_path: str | None = None
        if not callable(runner):
            raise AexosEngineAdapterV1ContractError("runner must be callable")
        self._runner = runner

    @classmethod
    def bundled(cls, *, runner: Runner = _default_runner) -> "AexosEngineAdapterV1":
        """Resolve the exact Cyryx-owned sidecar shipped with Onyx.

        PyInstaller exposes packaged data through ``sys._MEIPASS``. Source and
        test runs resolve from the repository root. The Node executable is
        hash-pinned before it is ever allowed to parse AEXOS content.
        """

        runtime_root = Path(
            getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])
        )
        vendor = runtime_root / BUNDLED_VENDOR_RELATIVE
        node = vendor / "node" / ("node.exe" if os.name == "nt" else "node")
        package = vendor / "engine"
        try:
            observed = _sha256(node)
        except OSError as exc:
            raise AexosEngineAdapterV1Denied(
                "bundled AEXOS runtime is unavailable"
            ) from exc
        if not hmac.compare_digest(observed, BUNDLED_NODE_SHA256):
            raise AexosEngineAdapterV1Denied(
                "bundled AEXOS runtime digest mismatch"
            )
        adapter = cls(package, node_executable=node, runner=runner)
        adapter._node_path = os.fspath(vendor / "runtime" / "node_modules")
        return adapter

    def attest(self) -> AexosAttestationV1:
        observed: list[tuple[str, str]] = []
        for relative, expected in EXPECTED_FILES.items():
            path = self._root / Path(relative)
            try:
                actual = _sha256(path)
            except OSError:
                return AexosAttestationV1(
                    SCHEMA, False, "artifact_unavailable", None, EXPECTED_COMMIT, tuple(observed)
                )
            observed.append((relative, actual))
            if actual != expected:
                return AexosAttestationV1(
                    SCHEMA, False, "artifact_digest_mismatch", None, EXPECTED_COMMIT, tuple(observed)
                )
        try:
            package = json.loads((self._root / "package.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return AexosAttestationV1(
                SCHEMA, False, "package_contract_invalid", None, EXPECTED_COMMIT, tuple(observed)
            )
        version = package.get("version") if isinstance(package, dict) else None
        name = package.get("name") if isinstance(package, dict) else None
        if name != "@aexos/core" or version != EXPECTED_VERSION:
            return AexosAttestationV1(
                SCHEMA, False, "package_identity_mismatch", None, EXPECTED_COMMIT, tuple(observed)
            )
        return AexosAttestationV1(
            SCHEMA, True, "attested", version, EXPECTED_COMMIT, tuple(observed)
        )

    def registry_bytes(self) -> bytes:
        """Return the exact registry bytes only after successful attestation."""
        attestation = self.attest()
        if not attestation.available:
            raise AexosEngineAdapterV1Denied(
                f"AEXOS attestation failed: {attestation.reason_code}"
            )
        try:
            return (self._root / ".aexos-core/data/squad-registry.yaml").read_bytes()
        except OSError as exc:
            raise AexosEngineAdapterV1Denied("AEXOS registry is unavailable") from exc

    def discover_workers(
        self, query: object, *, envelope: AexosBudgetEnvelopeV1
    ) -> AexosDiscoveryReceiptV1:
        if type(envelope) is not AexosBudgetEnvelopeV1:
            raise AexosEngineAdapterV1ContractError("exact budget envelope required")
        if type(query) is not str:
            raise AexosEngineAdapterV1ContractError("query must be text")
        normalized = " ".join(query.split())
        if not normalized or len(normalized) > MAX_QUERY_CHARS or "\x00" in normalized:
            raise AexosEngineAdapterV1ContractError("query is outside its bound")
        if any(pattern.search(normalized) for pattern in _UNTRUSTED_INSTRUCTION):
            raise AexosEngineAdapterV1Denied("query failed the intent security scan")
        attestation = self.attest()
        if not attestation.available:
            raise AexosEngineAdapterV1Denied(
                f"AEXOS attestation failed: {attestation.reason_code}"
            )
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": os.environ.get("TEMP", ""),
            "TMP": os.environ.get("TMP", ""),
            "AEXOS_MODEL_BUDGET_CEILING_USD": str(
                envelope.budget_ceiling_micro_usd / 1_000_000
            ),
            "AEXOS_STORY_ID": envelope.story_id,
        }
        if self._node_path is not None:
            environment["NODE_PATH"] = self._node_path
        command = (
            self._node,
            os.fspath(self._root / "bin" / "aexos.js"),
            "workers",
            "search",
            normalized,
            "--format=json",
        )
        try:
            code, stdout, stderr = self._runner(
                command, self._root, envelope.timeout_seconds, environment
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise AexosEngineAdapterV1Error("AEXOS discovery process failed") from exc
        if len(stdout) > MAX_OUTPUT_BYTES or len(stderr) > MAX_OUTPUT_BYTES:
            raise AexosEngineAdapterV1Denied("AEXOS output exceeded its bound")
        if code != 0:
            raise AexosEngineAdapterV1Error(
                "AEXOS discovery returned a non-zero result"
            )
        try:
            result = json.loads(stdout.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AexosEngineAdapterV1Denied("AEXOS discovery output is not JSON") from exc
        return AexosDiscoveryReceiptV1(
            status="completed",
            story_id=envelope.story_id,
            budget_ceiling_micro_usd=envelope.budget_ceiling_micro_usd,
            query_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            result=result,
        )

    def status(self) -> dict[str, object]:
        return asdict(self.attest())


__all__ = [
    "AexosAttestationV1",
    "AexosBudgetEnvelopeV1",
    "AexosDiscoveryReceiptV1",
    "AexosEngineAdapterV1",
    "AexosEngineAdapterV1ContractError",
    "AexosEngineAdapterV1Denied",
    "AexosEngineAdapterV1Error",
    "EXPECTED_COMMIT",
    "EXPECTED_FILES",
    "EXPECTED_VERSION",
    "SCHEMA",
]
