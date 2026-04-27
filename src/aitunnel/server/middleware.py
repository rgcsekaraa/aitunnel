"""ASGI middleware: per-request job tracking + panic recovery."""

from __future__ import annotations

import json
import logging
import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from .jobs import Job, JobStore, new_job_id, now_ts

log = logging.getLogger("aitunnel.server")

# Paths we don't track (would be noise).
_SKIP_PREFIXES = ("/health", "/jobs", "/setup", "/favicon", "/dashboard")
_SKIP_EXACT = {"/"}


def _should_skip(path: str) -> bool:
    if path in _SKIP_EXACT:
        return True
    return any(path.startswith(p) for p in _SKIP_PREFIXES)


class JobTrackingMiddleware(BaseHTTPMiddleware):
    """Wraps each non-skipped request in a Job. Job is recorded with status
    'running' before the handler, then updated on completion."""

    def __init__(self, app: ASGIApp, store: JobStore) -> None:
        super().__init__(app)
        self._store = store

    async def dispatch(self, request: Request, call_next):
        if _should_skip(request.url.path):
            return await call_next(request)

        job = Job(
            id=new_job_id(),
            method=request.method,
            path=request.url.path,
            started_at=now_ts(),
        )

        # Capture body preview (only for JSON; multipart is too big).
        ct = request.headers.get("content-type", "")
        if request.method in ("POST", "PUT") and ct.startswith("application/json"):
            try:
                body = await request.body()
                # Re-inject the body so downstream handlers can read it.
                async def _receive() -> dict:
                    return {"type": "http.request", "body": body, "more_body": False}
                request._receive = _receive  # type: ignore[attr-defined]
                preview = body.decode("utf-8", errors="replace")[:512]
                job.request = preview
            except Exception:
                pass
        elif ct.startswith("multipart/"):
            job.request = "<multipart upload>"

        request.state.job_id = job.id
        request.state.job_store = self._store
        await self._store.add(job)

        t0 = time.monotonic()
        try:
            response: Response = await call_next(request)
        except Exception as e:
            duration_ms = int((time.monotonic() - t0) * 1000)
            log.error("handler crashed: %s %s -> %r", request.method, request.url.path, e)
            await self._store.update(
                job.id,
                lambda j: _finalize(j, status="failed", code=500, duration_ms=duration_ms, error=str(e)),
            )
            return Response("internal server error", status_code=500, media_type="text/plain")

        # Capture a small preview of response body for the activity log.
        # We do this by intercepting the streaming body: read all chunks, save,
        # then return a fresh response. SSE responses are skipped (too long).
        body_preview = ""
        if "text/event-stream" not in (response.media_type or ""):
            chunks: list[bytes] = []
            async for c in response.body_iterator:
                chunks.append(c)
                if sum(len(x) for x in chunks) > 8192:
                    break
            body = b"".join(chunks)
            body_preview = body.decode("utf-8", errors="replace")[:512]
            response = Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )
            # Drop the framework's auto Content-Length; it's set by Response.
            response.headers.__delitem__("content-length") if "content-length" in response.headers else None  # noqa: B015

        duration_ms = int((time.monotonic() - t0) * 1000)
        code = response.status_code
        ok = 200 <= code < 400
        err = ""
        if not ok:
            err = body_preview[:200]
        await self._store.update(
            job.id,
            lambda j: _finalize(
                j,
                status="success" if ok else "failed",
                code=code,
                duration_ms=duration_ms,
                response_preview=body_preview,
                error=err,
            ),
        )
        return response


def _finalize(
    j: Job,
    *,
    status: str,
    code: int,
    duration_ms: int,
    response_preview: str = "",
    error: str = "",
) -> None:
    j.status = status
    j.status_code = code
    j.duration_ms = duration_ms
    j.ended_at = now_ts()
    j.response = response_preview
    if error:
        j.error = error[:200]
