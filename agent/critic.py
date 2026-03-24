from __future__ import annotations


PROJECT_TERMS = (
    "donut",
    "token",
    "airdrop",
    "wallet",
    "testnet",
    "launch",
    "funding",
)


def normalize_reply_text(text: str) -> str:
    cleaned = text.strip()
    quote_pairs = (
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),
        ("‘", "’"),
    )
    edge_quotes = "\"'“”‘’`"

    while len(cleaned) >= 2:
        unwrapped = False
        for left, right in quote_pairs:
            if cleaned.startswith(left) and cleaned.endswith(right):
                cleaned = cleaned[1:-1].strip()
                unwrapped = True
                break
        if not unwrapped:
            break
    return cleaned.strip(edge_quotes + " ").strip()


def mentions_project_terms(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in PROJECT_TERMS)


def is_repetitive(candidate: str, recent_replies: list[str]) -> bool:
    normalized = candidate.lower().strip()
    for previous in recent_replies:
        if normalized == previous.lower().strip():
            return True
    return False


def word_count(text: str) -> int:
    return len([part for part in text.strip().split() if part])


def critique_reply(
    *,
    text: str | None,
    mode: str,
    is_crypto: bool,
    recent_replies: list[str],
    max_words_smalltalk: int = 12,
    max_words_crypto: int = 18,
) -> str | None:
    if not text:
        return None
    cleaned = normalize_reply_text(text)
    if not cleaned:
        return None

    if not is_crypto and mentions_project_terms(cleaned):
        return None

    if is_repetitive(cleaned, recent_replies):
        return None

    count = word_count(cleaned)
    if mode == "smalltalk" and count > max_words_smalltalk:
        return None
    if is_crypto and count > max_words_crypto:
        return None

    return cleaned
