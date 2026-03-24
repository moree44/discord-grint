from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextMessage:
    author_name: str
    content: str


class RecentContextCache:
    def __init__(self, max_items: int = 40):
        self.max_items = max_items
        self._channel_cache: dict[int, deque[ContextMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_items)
        )
        self._thread_cache: dict[int, deque[ContextMessage]] = defaultdict(
            lambda: deque(maxlen=self.max_items)
        )

    def remember(
        self,
        *,
        channel_id: int,
        thread_id: int | None,
        author_name: str,
        content: str,
    ) -> None:
        message = ContextMessage(author_name=author_name, content=content)
        if thread_id is not None:
            self._thread_cache[thread_id].append(message)
        else:
            self._channel_cache[channel_id].append(message)

    def get_context(self, *, channel_id: int, thread_id: int | None, limit: int) -> list[str]:
        if thread_id is not None:
            messages = list(self._thread_cache.get(thread_id, deque()))
        else:
            messages = list(self._channel_cache.get(channel_id, deque()))
        if limit > 0:
            messages = messages[-limit:]
        return [f"{msg.author_name}: {msg.content}" for msg in messages]
