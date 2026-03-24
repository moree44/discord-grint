from __future__ import annotations

import time
from dataclasses import dataclass

from storage.sqlite_store import SQLiteStore


@dataclass(frozen=True)
class EventScope:
    guild_id: int | None
    channel_id: int
    thread_id: int | None


class EventStore:
    def __init__(
        self,
        store: SQLiteStore,
        *,
        ttl_seconds: int,
        max_recent_context: int,
        max_events_per_user: int,
    ):
        self.store = store
        self.ttl_seconds = ttl_seconds
        self.max_recent_context = max_recent_context
        self.max_events_per_user = max_events_per_user

    def purge_expired(self) -> None:
        self.store.delete_expired_events(int(time.time()))

    def add_event(
        self,
        *,
        scope: EventScope,
        user_id: int | None,
        author_name: str | None,
        event_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        now_ts = int(time.time())
        expires_at = now_ts + self.ttl_seconds if self.ttl_seconds > 0 else None
        self.store.insert_event(
            guild_id=scope.guild_id,
            channel_id=scope.channel_id,
            thread_id=scope.thread_id,
            user_id=user_id,
            author_name=author_name,
            event_type=event_type,
            content=content,
            metadata=metadata,
            created_at=now_ts,
            expires_at=expires_at,
        )
        self.store.trim_events_for_channel(scope.channel_id, self.max_recent_context)
        if user_id is not None:
            self.store.trim_events_for_user(user_id, self.max_events_per_user)

    def get_recent_context(self, *, scope: EventScope, limit: int) -> list[str]:
        rows = self.store.recent_events_for_scope(
            channel_id=scope.channel_id,
            thread_id=scope.thread_id,
            limit=limit,
        )
        # oldest first for prompt readability
        rows.reverse()
        return [f"{row['author_name'] or 'user'}: {row['content']}" for row in rows]

    def get_recent_bot_replies(self, *, scope: EventScope, limit: int) -> list[str]:
        return self.store.recent_bot_replies(
            channel_id=scope.channel_id,
            thread_id=scope.thread_id,
            limit=limit,
        )

    def latest_bot_reply_ts(self, channel_id: int) -> int | None:
        return self.store.latest_event_ts(event_type="bot_reply", channel_id=channel_id)
