"""Multi-turn chat sessions. Persists cid/rid/rcid across `send` calls so the
model sees prior turns. Each ChatSession is single-threaded; spin up multiple
sessions if you want parallel conversations."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .models import Model
from .stream import StreamReader
from .types import FileAttachment, ModelOutput

if TYPE_CHECKING:
    from .client import Client


class ChatSession:
    """One persistent multi-turn conversation."""

    def __init__(self, client: "Client", *, model: Model, gem_id: str = "") -> None:
        self._client = client
        self._model = model
        self._gem_id = gem_id
        self._cid = ""
        self._rid = ""
        self._rcid = ""
        self._context = ""
        self._lock = asyncio.Lock()

    @property
    def cid(self) -> str:
        return self._cid

    @property
    def rid(self) -> str:
        return self._rid

    @property
    def rcid(self) -> str:
        return self._rcid

    @property
    def metadata(self) -> tuple[str, str, str]:
        return self._cid, self._rid, self._rcid

    def resume(self, cid: str, rid: str = "", rcid: str = "") -> "ChatSession":
        """Seed the session with previously-captured metadata. Pass empty
        strings to clear/restart. Returns self for chaining."""
        self._cid = cid
        self._rid = rid
        self._rcid = rcid
        return self

    async def send(
        self,
        prompt: str,
        *,
        files: list[FileAttachment] | None = None,
    ) -> ModelOutput:
        """Send a turn, await the full response."""
        stream = await self.send_stream(prompt, files=files)
        try:
            async for delta in stream:
                if delta.done:
                    return delta.output or ModelOutput()
            return ModelOutput()
        finally:
            await stream.aclose()

    async def send_stream(
        self,
        prompt: str,
        *,
        files: list[FileAttachment] | None = None,
    ) -> StreamReader:
        """Send a turn, return a streaming reader."""
        async with self._lock:
            chat_meta = self._metadata_payload()
            stream = await self._client._open_stream(  # noqa: SLF001
                prompt,
                model=self._model,
                files=files,
                gem_id=self._gem_id,
                temporary=False,
                chat_metadata=chat_meta,
            )

            async def _on_complete(out: ModelOutput) -> None:
                if len(out.metadata) > 0:
                    self._cid = out.metadata[0]
                if len(out.metadata) > 1:
                    self._rid = out.metadata[1]
                if len(out.metadata) > 2:
                    self._rcid = out.metadata[2]

            stream._on_complete_set(_on_complete)  # noqa: SLF001
            return stream

    def _metadata_payload(self) -> list | None:
        """Construct the inner[2] payload for follow-up turns. Returns None
        for a fresh chat (build_generate falls back to the default sentinel)."""
        if not self._cid:
            return None
        return [self._cid, self._rid, self._rcid, None, None, None, None, None, None, self._context]
