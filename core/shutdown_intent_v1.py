"""Deterministic owner-intent boundary for terminating the Onyx process."""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata


_NEGATED = re.compile(
    r"\b(?:nao|nunca)\s+(?:desligue|desliga|feche|fecha|encerre)|"
    r"\b(?:do\s+not|dont|never)\s+(?:shut\s*down|close|exit|quit|stop)\b"
)
_PORTUGUESE_COMMAND = re.compile(
    r"^(?:onyx[\s,]+)?(?:por\s+favor[\s,]+)?(?:pode\s+)?"
    r"(?:desligue|desliga|desligar|feche|fecha|fechar|encerre|encerra|encerrar)"
    r"(?:\s+(?:(?:o|a)\s+)?(?:onyx|assistente|programa|sistema|sessao|conversa))?"
    r"(?:[\s,]+por\s+favor)?$"
)
_ENGLISH_COMMAND = re.compile(
    r"^(?:onyx[\s,]+)?(?:please[\s,]+)?"
    r"(?:shut\s*down|shutdown|close|exit|quit|stop)"
    r"(?:\s+(?:onyx|the\s+assistant|assistant|the\s+program|program|"
    r"the\s+session|this\s+session|the\s+conversation))?"
    r"(?:[\s,]+please)?$"
)
_FAREWELL = re.compile(
    r"^(?:onyx[\s,]+)?(?:tchau|adeus|ate\s+logo|goodbye|bye)"
    r"(?:[\s,]+onyx)?$"
)


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", str(text)).encode(
        "ascii", "ignore"
    ).decode("ascii")
    folded = folded.casefold().replace("’", "'")
    folded = re.sub(r"[^a-z0-9'\s,]", " ", folded)
    folded = folded.replace("don't", "dont")
    return re.sub(r"\s+", " ", folded).strip(" ,")


def is_explicit_shutdown_intent_v1(text: str) -> bool:
    """Return true only for a direct process/session termination command."""

    normalised = _normalise(text)
    if not normalised or _NEGATED.search(normalised):
        return False
    return any(
        pattern.fullmatch(normalised) is not None
        for pattern in (_PORTUGUESE_COMMAND, _ENGLISH_COMMAND, _FAREWELL)
    )


class ShutdownIntentGateV1:
    """Issue and consume a short-lived, single-use local intent capability."""

    def __init__(self, *, ttl_seconds: float = 20.0) -> None:
        if ttl_seconds <= 0:
            raise ValueError("shutdown intent TTL must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._expires_at = 0.0
        self._utterance_sha256 = ""

    def observe(self, text: str, *, now: float | None = None) -> bool:
        if not is_explicit_shutdown_intent_v1(text):
            # Transcription is incremental. A later correction such as
            # "desligue... não, espere" must revoke an earlier partial match.
            with self._lock:
                self._expires_at = 0.0
                self._utterance_sha256 = ""
            return False
        observed_at = time.monotonic() if now is None else float(now)
        digest = hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()
        with self._lock:
            self._expires_at = observed_at + self._ttl_seconds
            self._utterance_sha256 = digest
        return True

    def consume(self, *, now: float | None = None) -> str | None:
        consumed_at = time.monotonic() if now is None else float(now)
        with self._lock:
            if not self._utterance_sha256 or consumed_at > self._expires_at:
                self._expires_at = 0.0
                self._utterance_sha256 = ""
                return None
            digest = self._utterance_sha256
            self._expires_at = 0.0
            self._utterance_sha256 = ""
            return digest
