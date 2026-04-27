"""Activity log: in-memory ring buffer of recent jobs (HTTP requests
through the API), with an SSE broadcaster so the dashboard's Activity tab
gets live updates."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Job:
    id: str
    method: str
    path: str
    status: str = "running"  # running | retrying | success | failed
    status_code: int = 0
    attempts: int = 1
    started_at: float = 0.0  # unix seconds
    ended_at: float = 0.0
    duration_ms: int = 0
    request: str = ""
    response: str = ""
    error: str = ""
    retry_note: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


class JobStore:
    """Bounded ring buffer + fan-out subscription channel."""

    def __init__(self, max_jobs: int = 500) -> None:
        self._jobs: deque[Job] = deque(maxlen=max_jobs)
        self._lock = asyncio.Lock()
        self._subscribers: set[asyncio.Queue[Job]] = set()

    async def add(self, job: Job) -> None:
        async with self._lock:
            self._jobs.append(job)
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(job)
            except asyncio.QueueFull:
                pass  # drop on slow consumer

    async def update(self, job_id: str, mutate) -> None:
        snap: Job | None = None
        async with self._lock:
            for j in self._jobs:
                if j.id == job_id:
                    mutate(j)
                    snap = Job(**j.to_dict())
                    break
            subs = list(self._subscribers)
        if snap is None:
            return
        for q in subs:
            try:
                q.put_nowait(snap)
            except asyncio.QueueFull:
                pass

    async def snapshot(self, limit: int = 100) -> list[Job]:
        async with self._lock:
            jobs = list(self._jobs)
        # newest first
        jobs.reverse()
        if limit > 0:
            jobs = jobs[:limit]
        return jobs

    async def subscribe(self) -> tuple[asyncio.Queue[Job], Subscription]:
        q: asyncio.Queue[Job] = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.add(q)
        return q, Subscription(self, q)


class Subscription:
    """Async context manager for cleanup."""

    def __init__(self, store: JobStore, q: asyncio.Queue[Job]) -> None:
        self._store = store
        self._q = q

    async def __aenter__(self) -> Subscription:
        return self

    async def __aexit__(self, *_: object) -> None:
        async with self._store._lock:  # noqa: SLF001
            self._store._subscribers.discard(self._q)  # noqa: SLF001


def new_job_id() -> str:
    return secrets.token_hex(4)


def now_ts() -> float:
    return time.time()
