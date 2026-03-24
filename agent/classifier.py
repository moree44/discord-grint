from __future__ import annotations

from dataclasses import dataclass


GREETING_TERMS = ("gm", "good morning", "morning", "hello", "hi", "hey", "good night", "gn")


@dataclass(frozen=True)
class ModeResult:
    mode: str
    reason: str
    is_direct_reply: bool
    has_keyword: bool
    is_crypto: bool


def classify_message(
    *,
    content: str,
    has_reference_to_self: bool,
    is_mentioned: bool,
    keywords: list[str],
    crypto_terms: tuple[str, ...],
) -> ModeResult:
    lowered = content.lower()
    has_keyword = any(kw in lowered for kw in keywords)
    is_crypto = any(term in lowered for term in crypto_terms) or "crypto" in lowered

    if has_reference_to_self:
        return ModeResult(
            mode="direct_reply",
            reason="reply_to_our_message",
            is_direct_reply=True,
            has_keyword=has_keyword,
            is_crypto=is_crypto,
        )
    if is_mentioned:
        return ModeResult(
            mode="direct_reply",
            reason="mentioned",
            is_direct_reply=True,
            has_keyword=has_keyword,
            is_crypto=is_crypto,
        )
    if is_crypto or has_keyword:
        return ModeResult(
            mode="crypto",
            reason="keyword_or_crypto",
            is_direct_reply=False,
            has_keyword=has_keyword,
            is_crypto=True,
        )
    if any(term in lowered for term in GREETING_TERMS):
        return ModeResult(
            mode="smalltalk",
            reason="greeting",
            is_direct_reply=False,
            has_keyword=False,
            is_crypto=False,
        )
    return ModeResult(
        mode="smalltalk",
        reason="general_chat",
        is_direct_reply=False,
        has_keyword=False,
        is_crypto=False,
    )
