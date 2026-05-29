"""Per-thread FIFO run queue (port of bot/thread-queue.ts).

One active run per thread; further messages wait in FIFO order.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from ..mattermost.types import MattermostPost


@dataclass
class QueuedRun:
    id: str
    post: MattermostPost
    user_text: str
    history_run_id: str


def new_queue_id() -> str:
    return secrets.token_hex(4)


class ThreadRunQueue:
    def __init__(self) -> None:
        self.pending: list[QueuedRun] = []
        self.processing = False

    def enqueue(self, item: QueuedRun) -> int:
        self.pending.append(item)
        return len(self.pending)

    def cancel_all(self) -> int:
        n = len(self.pending)
        self.pending.clear()
        return n

    def cancel(self, item_id: str) -> bool:
        for i, q in enumerate(self.pending):
            if q.id == item_id:
                del self.pending[i]
                return True
        return False

    def list(self) -> list[tuple[str, str]]:
        return [(q.id, q.user_text) for q in self.pending]
