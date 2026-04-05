from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class SQLiteStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_parent_dir()
        self._init_db()

    def _ensure_parent_dir(self) -> None:
        parent = Path(self.db_path).parent
        parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER NOT NULL,
                    thread_id INTEGER,
                    user_id INTEGER,
                    author_name TEXT,
                    event_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_events_channel_created
                    ON events(channel_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_thread_created
                    ON events(thread_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_user_created
                    ON events(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_events_expire
                    ON events(expires_at);

                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id INTEGER PRIMARY KEY,
                    display_name TEXT,
                    preferred_language TEXT,
                    style_hint TEXT,
                    topics TEXT,
                    updated_at INTEGER NOT NULL
                );
                """
            )

    def insert_event(
        self,
        *,
        guild_id: int | None,
        channel_id: int,
        thread_id: int | None,
        user_id: int | None,
        author_name: str | None,
        event_type: str,
        content: str,
        metadata: dict[str, Any] | None,
        created_at: int,
        expires_at: int | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    guild_id, channel_id, thread_id, user_id, author_name,
                    event_type, content, metadata, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    channel_id,
                    thread_id,
                    user_id,
                    author_name,
                    event_type,
                    content,
                    json.dumps(metadata or {}),
                    created_at,
                    expires_at,
                ),
            )

    def delete_expired_events(self, now_ts: int) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM events WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (now_ts,),
            )
            return cur.rowcount

    def trim_events_for_scope(
        self,
        *,
        channel_id: int,
        thread_id: int | None,
        keep_last: int,
    ) -> None:
        keep_last = max(1, int(keep_last))
        with self._connect() as conn:
            if thread_id is not None:
                conn.execute(
                    """
                    DELETE FROM events
                    WHERE thread_id = ?
                      AND id NOT IN (
                        SELECT id FROM events
                        WHERE thread_id = ?
                        ORDER BY created_at DESC
                        LIMIT ?
                      )
                    """,
                    (thread_id, thread_id, keep_last),
                )
            else:
                conn.execute(
                    """
                    DELETE FROM events
                    WHERE channel_id = ? AND thread_id IS NULL
                      AND id NOT IN (
                        SELECT id FROM events
                        WHERE channel_id = ? AND thread_id IS NULL
                        ORDER BY created_at DESC
                        LIMIT ?
                      )
                    """,
                    (channel_id, channel_id, keep_last),
                )

    def trim_events_for_user(self, user_id: int, keep_last: int) -> None:
        keep_last = max(1, int(keep_last))
        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM events
                WHERE user_id = ?
                  AND id NOT IN (
                    SELECT id FROM events
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                  )
                """,
                (user_id, user_id, keep_last),
            )

    def recent_events_for_scope(
        self,
        *,
        channel_id: int,
        thread_id: int | None,
        limit: int,
    ) -> list[sqlite3.Row]:
        with self._connect() as conn:
            if thread_id is not None:
                rows = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE thread_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (thread_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM events
                    WHERE channel_id = ? AND thread_id IS NULL
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (channel_id, limit),
                ).fetchall()
            return rows

    def recent_events_for_user(self, user_id: int, limit: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT * FROM events
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()

    def recent_bot_replies(
        self,
        *,
        channel_id: int,
        thread_id: int | None,
        limit: int,
    ) -> list[str]:
        with self._connect() as conn:
            if thread_id is not None:
                rows = conn.execute(
                    """
                    SELECT content FROM events
                    WHERE thread_id = ? AND event_type = 'bot_reply'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (thread_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT content FROM events
                    WHERE channel_id = ? AND thread_id IS NULL AND event_type = 'bot_reply'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (channel_id, limit),
                ).fetchall()
            return [row["content"] for row in rows]

    def latest_event_ts_for_scope(
        self,
        *,
        event_type: str,
        channel_id: int,
        thread_id: int | None,
    ) -> int | None:
        with self._connect() as conn:
            if thread_id is not None:
                row = conn.execute(
                    """
                    SELECT created_at FROM events
                    WHERE event_type = ? AND thread_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (event_type, thread_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT created_at FROM events
                    WHERE event_type = ? AND channel_id = ? AND thread_id IS NULL
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (event_type, channel_id),
                ).fetchone()
            if not row:
                return None
            return int(row["created_at"])

    def get_user_profile(self, user_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()

    def upsert_user_profile(
        self,
        *,
        user_id: int,
        display_name: str | None,
        preferred_language: str | None,
        style_hint: str | None,
        topics: str,
        updated_at: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles (
                    user_id, display_name, preferred_language, style_hint, topics, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    display_name = excluded.display_name,
                    preferred_language = excluded.preferred_language,
                    style_hint = excluded.style_hint,
                    topics = excluded.topics,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    display_name,
                    preferred_language,
                    style_hint,
                    topics,
                    updated_at,
                ),
            )
