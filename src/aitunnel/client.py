"""Public Client. Owns the transport, session info, and background cookie
rotator. Methods like `query`/`query_stream`/`start_chat` are thin wrappers
around the transport plus the right `GenerateOpts` config."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from . import _protocol as proto
from ._protocol.request import FileRef as ProtoFileRef
from ._protocol.request import GenerateOpts
from ._transport import Transport
from ._transport.rotate import rotate_cookies
from .errors import APIError, AuthError, ClosedError, NotStartedError
from .models import MODEL_UNSPECIFIED, Model
from .retry import RetryPolicy
from .stream import StreamReader
from .types import FileAttachment, ModelOutput

if TYPE_CHECKING:
    from .chat import ChatSession

log = logging.getLogger("aitunnel")


def _redact(s: str) -> str:
    if len(s) <= 6:
        return "****"
    return "****" + s[-4:]


class Client:
    """Single Gemini session. Construct -> `await start()` -> use; `await close()`
    when done. One Client wraps one Google account; concurrent calls to the
    same Client are safe."""

    def __init__(
        self,
        psid: str,
        psidts: str = "",
        *,
        proxy: str | None = None,
        request_timeout: float = 120.0,
        rotate_interval: float = 9 * 60.0,
        retry: RetryPolicy | None = None,
        default_model: Model = MODEL_UNSPECIFIED,
        logger: logging.Logger | None = None,
    ) -> None:
        if not psid:
            raise AuthError("__Secure-1PSID is required")
        self._psid = psid
        self._psidts = psidts
        self._proxy = proxy
        self._request_timeout = request_timeout
        self._rotate_interval = rotate_interval
        self._retry = retry or RetryPolicy()
        self._default_model = default_model
        self._log = logger or log

        self._tx = Transport(proxy=proxy, timeout=request_timeout)
        self._session: proto.SessionInfo | None = None
        self._started = False
        self._closed = False
        self._lock = asyncio.Lock()
        self._rotator: asyncio.Task[None] | None = None

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry

    @property
    def default_model(self) -> Model:
        return self._default_model

    @property
    def ready(self) -> bool:
        return self._started and not self._closed and self._session is not None

    @property
    def push_id(self) -> str:
        return self._session.push_id if self._session else ""

    @property
    def current_psidts(self) -> str:
        return self._tx.get_cookie("__Secure-1PSIDTS") or self._psidts

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Bootstrap: preflight google.com (for trust cookies), set auth
        cookies, optionally pre-rotate PSIDTS, GET /app and parse the SNlM0e
        access token, then launch the background rotator."""
        async with self._lock:
            if self._closed:
                raise ClosedError("Client closed")
            if self._started:
                return

            # Preflight - non-fatal.
            try:
                await self._tx.get(proto.GOOGLE_URL)
            except Exception as e:
                self._log.debug("preflight google.com failed (non-fatal): %s", e)

            self._tx.set_cookie("__Secure-1PSID", self._psid)
            if self._psidts:
                self._tx.set_cookie("__Secure-1PSIDTS", self._psidts)

            # Pre-rotate to recover from a stale PSIDTS while PSID is fine.
            try:
                new_val, status = await rotate_cookies(self._tx)
                if status == 200 and new_val:
                    self._psidts = new_val
                    self._log.debug("pre-bootstrap rotation refreshed PSIDTS: %s", _redact(new_val))
            except Exception as e:
                self._log.debug("pre-bootstrap rotation failed (will try bootstrap anyway): %s", e)

            await self._bootstrap()
            self._rotator = asyncio.create_task(self._rotate_loop(), name="aitunnel-rotator")
            self._started = True

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._rotator is not None:
                self._rotator.cancel()
                try:
                    await self._rotator
                except (asyncio.CancelledError, Exception):
                    pass
            await self._tx.close()

    async def __aenter__(self) -> Client:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ---- session info -------------------------------------------------------

    async def _bootstrap(self) -> None:
        # Try twice - Google occasionally serves a half-rendered page on the
        # first request after the cookie jar settles. Retrying once handles
        # the race and avoids a noisy AuthError on otherwise-good cookies.
        # Addresses upstream gemini_webapi#319.
        last_html = ""
        last_status = 0
        for attempt in (1, 2):
            resp = await self._tx.get(
                proto.INIT_URL,
                headers={
                    "Origin": "https://gemini.google.com",
                    "Referer": "https://gemini.google.com/",
                },
            )
            last_status = resp.status_code
            if resp.status_code != 200:
                if attempt == 1:
                    await asyncio.sleep(0.5)
                    continue
                raise APIError(resp.status_code, "bootstrap returned non-200", cause=AuthError())
            html = resp.text or ""
            last_html = html
            info = proto.parse_session_info(html)
            if info is not None:
                self._session = info
                self._log.info(
                    "aitunnel ready (build=%s session=%s lang=%s)",
                    info.build_label, _redact(info.session_id), info.language,
                )
                return
            if attempt == 1:
                await asyncio.sleep(0.5)
                continue

        # Both attempts failed. Build a diagnostic error so the user can tell
        # whether they got the login page (cookies bad), an unfamiliar shape
        # (parser drift), or something else.
        snippet = last_html[:240].replace("\n", " ").strip()
        if "accounts.google.com" in last_html and "ServiceLogin" in last_html:
            hint = "got the login page - cookies are invalid or expired"
        elif "<title>" in last_html.lower():
            t_start = last_html.lower().find("<title>") + 7
            t_end = last_html.lower().find("</title>", t_start)
            title = last_html[t_start:t_end][:80] if t_end > 0 else ""
            hint = f"page title: {title!r} - likely Google rejected the session"
        else:
            hint = f"first 240 chars: {snippet!r}"
        raise AuthError(
            f"SNlM0e token not found in bootstrap (HTTP {last_status}). {hint}"
        )

    async def _rotate_loop(self) -> None:
        try:
            while not self._closed:
                await asyncio.sleep(self._rotate_interval)
                try:
                    new_val, status = await rotate_cookies(self._tx)
                    if status == 401:
                        self._log.error("cookie rotation 401 - session dead, stopping rotator")
                        return
                    if new_val and new_val != self._psidts:
                        self._psidts = new_val
                        self._log.debug("rotated __Secure-1PSIDTS: %s", _redact(new_val))
                except Exception as e:
                    self._log.warning("cookie rotation failed (will retry): %s", e)
        except asyncio.CancelledError:
            return

    # ---- access for sibling modules -----------------------------------------

    @property
    def transport(self) -> Transport:
        if self._session is None:
            raise NotStartedError("Client not started - call start() first")
        return self._tx

    @property
    def session_info(self) -> proto.SessionInfo:
        if self._session is None:
            raise NotStartedError("Client not started - call start() first")
        return self._session

    # ---- generate -----------------------------------------------------------

    async def query(
        self,
        prompt: str,
        *,
        model: Model | None = None,
        files: list[FileAttachment] | None = None,
        gem_id: str = "",
    ) -> ModelOutput:
        """One-shot temporary chat. Returns the full ModelOutput once the
        stream completes."""
        async def _run() -> ModelOutput:
            stream = await self._open_stream(prompt, model=model, files=files, gem_id=gem_id, temporary=True)
            try:
                async for delta in stream:
                    if delta.done:
                        return delta.output or ModelOutput()
            finally:
                await stream.aclose()
            return ModelOutput()

        from .retry import run_with_retry
        return await run_with_retry(self._retry, _run)

    async def query_stream(
        self,
        prompt: str,
        *,
        model: Model | None = None,
        files: list[FileAttachment] | None = None,
        gem_id: str = "",
    ) -> StreamReader:
        """One-shot temporary chat as a streaming async iterator of Deltas."""
        return await self._open_stream(prompt, model=model, files=files, gem_id=gem_id, temporary=True)

    async def _open_stream(
        self,
        prompt: str,
        *,
        model: Model | None,
        files: list[FileAttachment] | None,
        gem_id: str,
        temporary: bool,
        chat_metadata: list | None = None,
        deep_research: bool = False,
    ) -> StreamReader:
        if not self.ready:
            raise NotStartedError("Client not started - call start() first")
        if not prompt or not prompt.strip():
            raise ValueError("prompt must be non-empty")
        m = model or self._default_model
        opts = GenerateOpts(
            model_headers=dict(m.headers),
            chat_metadata=chat_metadata,
            temporary=temporary,
            gem_id=gem_id,
            files=[ProtoFileRef(url=f.url, filename=f.filename) for f in (files or [])],
            deep_research=deep_research,
        )
        chunk_iter = self._tx.generate_stream(prompt, self.session_info, opts)
        return StreamReader(chunk_iter)

    # ---- chat session -------------------------------------------------------

    def start_chat(
        self,
        *,
        model: Model | None = None,
        gem_id: str = "",
    ) -> ChatSession:
        """Start a multi-turn ChatSession. Sends are persisted in your Gemini
        history."""
        from .chat import ChatSession  # local import: chat.py imports Client, so we'd loop
        return ChatSession(self, model=model or self._default_model, gem_id=gem_id)
