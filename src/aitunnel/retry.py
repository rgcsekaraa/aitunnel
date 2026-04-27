"""Retry policy with jittered exponential backoff. Used by `Client.query`
to retry transient errors (Gemini's 1013 sometimes fires randomly)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from .errors import TransientError

T = TypeVar("T")

OnAttempt = Callable[[int, Exception], None]


@dataclass
class RetryPolicy:
    """How many attempts, what to retry, how long to wait between."""

    max_attempts: int = 3
    initial_backoff: float = 0.5  # seconds
    max_backoff: float = 5.0
    jitter: float = 0.2  # +/- 20% noise on backoff
    # By default we only retry TransientError. Override `should_retry` to
    # broaden (e.g. include APIError with 5xx).
    should_retry: Callable[[Exception], bool] = lambda e: isinstance(e, TransientError)
    # Called once per retry, BEFORE the sleep. Used by the FastAPI server to
    # surface attempt counts to the activity log.
    on_attempt: OnAttempt | None = None


async def run_with_retry(policy: RetryPolicy, fn: Callable[[], Awaitable[T]]) -> T:
    """Run `fn`, retrying transient failures per `policy`."""
    backoff = policy.initial_backoff
    last_err: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await fn()
        except Exception as e:
            last_err = e
            if attempt >= policy.max_attempts or not policy.should_retry(e):
                raise
            if policy.on_attempt is not None:
                policy.on_attempt(attempt + 1, e)
            sleep = backoff
            if policy.jitter > 0:
                sleep += random.uniform(-policy.jitter, policy.jitter) * sleep
            sleep = min(max(sleep, 0), policy.max_backoff)
            await asyncio.sleep(sleep)
            backoff = min(backoff * 2, policy.max_backoff)
    # Unreachable, but keeps the type checker happy.
    assert last_err is not None
    raise last_err
