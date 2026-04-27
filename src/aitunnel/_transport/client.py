"""curl_cffi-based async HTTP transport with Chrome uTLS fingerprint.

Without uTLS, Google rejects the request based on TLS fingerprint even with
valid cookies. curl_cffi's `impersonate="chrome"` matches what real Chrome
sends.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from curl_cffi import requests as curl_requests

from .._protocol import (
    BATCH_EXEC_URL,
    GENERATE_URL,
    UPLOAD_URL,
    UPLOAD_HEADERS_BASE,
    BatchCall,
    BatchPart,
    SessionInfo,
    build_batch_execute,
    build_generate,
    build_upload_body,
    parse_batch_response,
)
from .._protocol.request import GenerateOpts


class Transport:
    """Wraps curl_cffi.requests.AsyncSession with Gemini-specific helpers.

    One Transport per Client (single Google session). Safe for concurrent
    asyncio tasks because curl_cffi's async session is.
    """

    def __init__(self, *, proxy: str | None = None, timeout: float = 120.0) -> None:
        self._session = curl_requests.AsyncSession(
            impersonate="chrome",
            proxy=proxy,
            timeout=timeout,
            allow_redirects=True,
        )
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._session.close()
        except Exception:
            pass

    # ---- cookie management ---------------------------------------------------

    def set_cookie(self, name: str, value: str, *, domain: str = ".google.com") -> None:
        self._session.cookies.set(name, value, domain=domain, path="/")

    def get_cookie(self, name: str) -> str:
        # curl_cffi's cookie jar exposes a flat dict-like API.
        for c in self._session.cookies.jar:
            if c.name == name:
                return c.value or ""
        return ""

    # ---- raw HTTP ------------------------------------------------------------

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> curl_requests.Response:
        return await self._session.get(url, headers=headers or {})

    async def post(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        data: bytes | str | None = None,
    ) -> curl_requests.Response:
        return await self._session.post(url, params=params, headers=headers or {}, data=data)

    async def post_stream(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        data: bytes | str | None = None,
    ) -> AsyncIterator[bytes]:
        """Async-iterate the response body in chunks. Closes underlying
        connection when the iterator is exhausted or garbage-collected."""
        # curl_cffi's stream API: pass stream=True, then iter_content.
        resp = await self._session.post(
            url, params=params, headers=headers or {}, data=data, stream=True
        )
        try:
            if resp.status_code != 200:
                # Read body so the exception text is informative.
                body = await resp.atext()
                resp.close()
                raise _HTTPError(resp.status_code, body)
            async for chunk in resp.aiter_content(chunk_size=8192):
                yield chunk
        finally:
            resp.close()

    # ---- protocol-aware helpers ---------------------------------------------

    async def generate_stream(
        self,
        prompt: str,
        sess: SessionInfo,
        opts: GenerateOpts,
    ) -> AsyncIterator[bytes]:
        """POST /StreamGenerate, yield raw response chunks as they arrive."""
        params, headers, body = build_generate(prompt, sess, opts)
        async for chunk in self.post_stream(GENERATE_URL, params=params, headers=headers, data=body):
            yield chunk

    async def batch_execute(
        self,
        sess: SessionInfo,
        calls: list[BatchCall],
        *,
        source_path: str = "/app",
    ) -> tuple[list[BatchPart], int]:
        """One-shot BatchExecute. Returns (parts, status_code)."""
        params, headers, body = build_batch_execute(calls, sess, source_path=source_path)
        resp = await self.post(BATCH_EXEC_URL, params=params, headers=headers, data=body)
        if resp.status_code != 200:
            return [], resp.status_code
        parts = await parse_batch_response(resp.content)
        return parts, resp.status_code

    async def upload_file(
        self,
        push_id: str,
        filename: str,
        content_type: str,
        data: bytes,
    ) -> str:
        """POST a single file. Returns the opaque resource URL Google issues."""
        body, ct = build_upload_body(filename, content_type, data)
        headers = {**UPLOAD_HEADERS_BASE, "Push-ID": push_id, "Content-Type": ct}
        resp = await self.post(UPLOAD_URL, headers=headers, data=body)
        if resp.status_code != 200:
            raise _HTTPError(resp.status_code, resp.text)
        return (resp.text or "").strip()

    async def download(self, url: str, write: Callable[[bytes], Awaitable[None]]) -> str:
        """GET `url` and pipe each chunk through `write`. Returns content-type."""
        async for ct, chunk in self._download_iter(url):
            await write(chunk)
            content_type = ct
        return content_type  # type: ignore[possibly-undefined]

    async def _download_iter(self, url: str) -> AsyncIterator[tuple[str, bytes]]:
        resp = await self._session.get(
            url,
            headers={"Origin": "https://gemini.google.com", "Referer": "https://gemini.google.com/"},
            stream=True,
        )
        try:
            if resp.status_code != 200:
                body = await resp.atext()
                raise _HTTPError(resp.status_code, body)
            ct = resp.headers.get("Content-Type", "")
            async for chunk in resp.aiter_content(chunk_size=64 * 1024):
                yield ct, chunk
        finally:
            resp.close()

    async def open_stream(self, url: str) -> tuple[curl_requests.Response, str]:
        """GET `url`, return the raw streaming response + content-type. Caller
        must read `resp.content` (or stream via aiter_content) and call
        `resp.close()`."""
        resp = await self._session.get(
            url,
            headers={"Origin": "https://gemini.google.com", "Referer": "https://gemini.google.com/"},
            stream=True,
        )
        if resp.status_code != 200:
            body = await resp.atext()
            resp.close()
            raise _HTTPError(resp.status_code, body)
        return resp, resp.headers.get("Content-Type", "")


class _HTTPError(Exception):
    def __init__(self, status_code: int, body: str = "") -> None:
        self.status_code = status_code
        self.body = (body or "")[:500]
        super().__init__(f"HTTP {status_code}: {self.body}")


# Suppress unused import for type-checking purposes in isolated reads.
_ = json
_ = Any
