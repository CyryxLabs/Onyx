"""Immutable Onyx identity with an optional owner-selected call alias."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

PRODUCT_NAME: Final = "Onyx"
VENDOR_NAME: Final = "Cyryx Labs"
SCHEMA: Final = "onyx.assistant-identity-profile/v1"
MAX_ALIAS_CHARS: Final = 32
_ALIAS = re.compile(r"[^\W\d_][^\W_\-']*(?:[ '\-][^\W\d_][^\W_\-']*)?", re.UNICODE)
_SET_COMMAND = re.compile(
    r"^\s*(?:onyx[,;:!\-]?\s*)?(?:call yourself|use the call alias|"
    r"chame[- ]se|use o nome de chamada)\s+(?P<alias>.+?)\s*$",
    re.IGNORECASE,
)
_CLEAR_COMMAND = re.compile(
    r"^\s*(?:onyx[,;:!\-]?\s*)?(?:clear your call alias|use onyx again|"
    r"remova seu nome de chamada|volte a usar onyx)\s*$",
    re.IGNORECASE,
)


class AssistantIdentityProfileError(ValueError):
    """An identity profile or alias command was invalid."""


@dataclass(frozen=True, slots=True)
class AssistantIdentityStateV1:
    product_name: str = PRODUCT_NAME
    vendor_name: str = VENDOR_NAME
    call_alias: str | None = None
    updated_at_ns: int = 0


@dataclass(frozen=True, slots=True)
class AssistantAliasIntentV1:
    matched: bool
    alias: str | None = None
    clear: bool = False
    error: str = ""


def normalize_call_alias_v1(value: object) -> str:
    if type(value) is not str:
        raise AssistantIdentityProfileError("call alias must be text")
    alias = " ".join(unicodedata.normalize("NFC", value).split())
    if not alias or len(alias) > MAX_ALIAS_CHARS or not _ALIAS.fullmatch(alias):
        raise AssistantIdentityProfileError("call alias is invalid")
    if alias.casefold() in {PRODUCT_NAME.casefold(), VENDOR_NAME.casefold()}:
        raise AssistantIdentityProfileError("reserved identity cannot be used as an alias")
    return alias


def parse_assistant_alias_intent_v1(text: object) -> AssistantAliasIntentV1:
    if type(text) is not str:
        return AssistantAliasIntentV1(False)
    normalized = unicodedata.normalize("NFC", text)
    if _CLEAR_COMMAND.fullmatch(normalized):
        return AssistantAliasIntentV1(True, clear=True)
    match = _SET_COMMAND.fullmatch(normalized)
    if match is None:
        return AssistantAliasIntentV1(False)
    try:
        alias = normalize_call_alias_v1(match.group("alias"))
    except AssistantIdentityProfileError:
        return AssistantAliasIntentV1(True, error="invalid_alias")
    return AssistantAliasIntentV1(True, alias=alias)


class AssistantIdentityProfileV1:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def status(self) -> AssistantIdentityStateV1:
        if not self.path.exists():
            return AssistantIdentityStateV1()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if raw.pop("schema", None) != SCHEMA or set(raw) != {
                "product_name", "vendor_name", "call_alias", "updated_at_ns"
            }:
                raise ValueError
            state = AssistantIdentityStateV1(**raw)
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise AssistantIdentityProfileError("identity profile is malformed") from exc
        if state.product_name != PRODUCT_NAME or state.vendor_name != VENDOR_NAME:
            raise AssistantIdentityProfileError("immutable identity drifted")
        if state.call_alias is not None:
            normalize_call_alias_v1(state.call_alias)
        return state

    def _write(self, state: AssistantIdentityStateV1) -> AssistantIdentityStateV1:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(
                    {"schema": SCHEMA, **asdict(state)},
                    stream,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return state

    def set_alias(self, alias: object) -> AssistantIdentityStateV1:
        return self._write(AssistantIdentityStateV1(
            call_alias=normalize_call_alias_v1(alias), updated_at_ns=time.time_ns()
        ))

    def clear_alias(self) -> AssistantIdentityStateV1:
        self.path.unlink(missing_ok=True)
        return AssistantIdentityStateV1()

    def apply_command(self, text: object) -> AssistantAliasIntentV1:
        intent = parse_assistant_alias_intent_v1(text)
        if not intent.matched or intent.error:
            return intent
        if intent.clear:
            self.clear_alias()
        elif intent.alias is not None:
            self.set_alias(intent.alias)
        return intent

    def prompt_instruction(self) -> str:
        state = self.status()
        identity = (
            "[IMMUTABLE ASSISTANT IDENTITY — TRUSTED LOCAL CONTRACT]\n"
            "The product is Onyx by Cyryx Labs. Never claim that the product, vendor, legal identity, executable, or brand changed."
        )
        if state.call_alias is None:
            return identity + "\n"
        return (
            identity
            + f" The owner selected {state.call_alias} only as a conversational call alias; you may answer to it while continuing to identify the product as Onyx.\n"
        )


__all__ = [
    "AssistantAliasIntentV1",
    "AssistantIdentityProfileError",
    "AssistantIdentityProfileV1",
    "AssistantIdentityStateV1",
    "PRODUCT_NAME",
    "VENDOR_NAME",
    "normalize_call_alias_v1",
    "parse_assistant_alias_intent_v1",
]
