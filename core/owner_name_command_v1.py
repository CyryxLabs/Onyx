"""Deterministic natural-language owner-name command routing.

The router recognizes only explicit first-person naming commands.  It does not
persist identity itself: the live owner-profile authority remains the sole
writer and is injected as ``correct_name`` by the host.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Final

from core.owner_profile_v8 import InvalidDisplayName, normalize_display_name


_COMMAND: Final = re.compile(
    r"^\s*(?:"
    r"meu\s+nome\s+[ée]|"
    r"pode\s+me\s+chamar\s+de|"
    r"chame[-\s]?me(?:\s+de)?|"
    r"atualize\s+meu\s+nome\s+para|"
    r"corrija\s+meu\s+nome\s+para|"
    r"call\s+me|"
    r"my\s+name\s+is|"
    r"update\s+my\s+name\s+to|"
    r"correct\s+my\s+name\s+to|"
    r"change\s+my\s+name\s+to"
    r")\s+(?P<name>.+?)\s*[.!?]?\s*$",
    re.IGNORECASE,
)
_PREFIX: Final = re.compile(
    r"^\s*(?:meu\s+nome|pode\s+me\s+chamar|chame[-\s]?me|"
    r"atualize\s+meu\s+nome|corrija\s+meu\s+nome|call\s+me|my\s+name|"
    r"update\s+my\s+name|correct\s+my\s+name|change\s+my\s+name)\b",
    re.IGNORECASE,
)
_PORTUGUESE_PREFIX: Final = re.compile(
    r"^\s*(?:meu\s+nome|pode\s+me\s+chamar|chame[-\s]?me|"
    r"atualize\s+meu\s+nome|corrija\s+meu\s+nome)\b",
    re.IGNORECASE,
)
_WAKE_PREFIX: Final = re.compile(
    r"^\s*(?:(?:hey|ol[áa])\s+)?onyx\b\s*[,;:!\-]?\s*",
    re.IGNORECASE,
)
_TRAILING_ADDRESS: Final = re.compile(r"\s*,?\s+(?:onyx)\s*$", re.IGNORECASE)


class OwnerNameLocaleV1(str, Enum):
    """Language explicitly selected by the matched command grammar."""

    PT = "pt"
    EN = "en"


@dataclass(frozen=True, slots=True)
class OwnerNameIntentV1:
    """One bounded parse result suitable for both text and voice transcripts."""

    matched: bool
    name: str | None = None
    needs_confirmation: bool = False
    error: str = ""
    locale: OwnerNameLocaleV1 | None = None


def parse_owner_name_intent_v1(text: object) -> OwnerNameIntentV1:
    """Parse explicit PT/EN owner-name commands without guessing.

    A phrase that clearly starts as a naming command is considered consumed
    even when invalid.  This prevents hostile or malformed values from falling
    through to a model/tool path with weaker interpretation.
    """

    if not isinstance(text, str):
        return OwnerNameIntentV1(False)
    normalized = unicodedata.normalize("NFC", text)
    normalized = _WAKE_PREFIX.sub("", normalized, count=1)
    locale = (
        OwnerNameLocaleV1.PT
        if _PORTUGUESE_PREFIX.match(normalized)
        else OwnerNameLocaleV1.EN
    )
    match = _COMMAND.fullmatch(normalized)
    if match is None:
        if _PREFIX.match(normalized):
            return OwnerNameIntentV1(
                True,
                needs_confirmation=True,
                error="missing_or_ambiguous_name",
                locale=locale,
            )
        return OwnerNameIntentV1(False)
    candidate = _TRAILING_ADDRESS.sub("", match.group("name")).strip()
    if candidate.casefold() == "sir":
        name = "Sir"
    else:
        try:
            name = normalize_display_name(candidate)
        except InvalidDisplayName:
            return OwnerNameIntentV1(True, error="invalid_name", locale=locale)
    if name is None:
        return OwnerNameIntentV1(True, error="invalid_name", locale=locale)
    return OwnerNameIntentV1(True, name=name, locale=locale)


def route_owner_name_command_v1(
    text: object,
    *,
    correct_name: Callable[[str], object],
) -> OwnerNameIntentV1:
    """Route a valid intent through the existing live identity authority."""

    result = parse_owner_name_intent_v1(text)
    if not result.matched or result.name is None:
        return result
    correct_name(result.name)
    return result


__all__ = [
    "OwnerNameIntentV1",
    "OwnerNameLocaleV1",
    "parse_owner_name_intent_v1",
    "route_owner_name_command_v1",
]
