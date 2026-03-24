from __future__ import annotations

from dataclasses import dataclass
import re
import time

from storage.sqlite_store import SQLiteStore


ID_SIGNAL_WORDS = (
    "aku",
    "saya",
    "kamu",
    "bro",
    "bang",
    "gimana",
    "nggak",
    "ga",
    "udah",
    "iya",
)

TOPIC_TERMS = (
    "donut",
    "token",
    "airdrop",
    "wallet",
    "testnet",
    "launch",
    "funding",
    "gm",
    "morning",
)


@dataclass(frozen=True)
class UserProfile:
    user_id: int
    display_name: str | None
    preferred_language: str | None
    style_hint: str | None
    topics: list[str]


class UserProfileStore:
    def __init__(self, store: SQLiteStore):
        self.store = store

    def _detect_language(self, text: str) -> str:
        lowered = text.lower()
        if any(word in lowered for word in ID_SIGNAL_WORDS):
            return "id"
        return "en"

    def _detect_style(self, text: str) -> str:
        if len(text) <= 12:
            return "very_short"
        if re.search(r"[😂🤣🔥👀🍩👍]", text):
            return "emoji_casual"
        return "casual"

    def _extract_topics(self, text: str) -> list[str]:
        lowered = text.lower()
        return [term for term in TOPIC_TERMS if term in lowered]

    def update_from_message(self, *, user_id: int, display_name: str | None, content: str) -> None:
        lang = self._detect_language(content)
        style = self._detect_style(content)
        topics = self._extract_topics(content)

        existing = self.store.get_user_profile(user_id)
        existing_topics: list[str] = []
        if existing and existing["topics"]:
            existing_topics = [part for part in str(existing["topics"]).split(",") if part]
        merged_topics = list(dict.fromkeys((existing_topics + topics)[-10:]))

        self.store.upsert_user_profile(
            user_id=user_id,
            display_name=display_name,
            preferred_language=lang,
            style_hint=style,
            topics=",".join(merged_topics),
            updated_at=int(time.time()),
        )

    def get_profile(self, user_id: int) -> UserProfile | None:
        row = self.store.get_user_profile(user_id)
        if not row:
            return None
        topics = [part for part in str(row["topics"] or "").split(",") if part]
        return UserProfile(
            user_id=int(row["user_id"]),
            display_name=row["display_name"],
            preferred_language=row["preferred_language"],
            style_hint=row["style_hint"],
            topics=topics,
        )
