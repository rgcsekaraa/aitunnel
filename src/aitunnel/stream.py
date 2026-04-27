"""Async streaming reader. Wraps the raw response chunks from the transport
in a FrameReader, walks ParseEvent envelopes, and yields typed Deltas with
text-deltas already computed."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from . import _protocol as proto
from .errors import EmptyResponseError, classify_model_error
from .types import (
    Candidate,
    Delta,
    GeneratedImage,
    GeneratedMedia,
    GeneratedVideo,
    ModelOutput,
    WebImage,
)


class StreamReader:
    """Async iterator over Deltas. Each frame from the upstream becomes one
    Delta with `text_delta` (the new portion since the previous Delta)
    pre-computed.

    Use as an async iterator:

        async for delta in stream:
            print(delta.text_delta, end="")
            if delta.done:
                break
        await stream.aclose()
    """

    def __init__(self, chunk_iter: AsyncIterator[bytes]) -> None:
        self._chunks = chunk_iter
        self._iter_started = False
        self._fr: proto.FrameReader | None = None

        self._chat_id = ""
        self._reply_id = ""
        self._chosen_rcid = ""
        self._candidates: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._last_text: dict[str, str] = {}
        self._last_thoughts: dict[str, str] = {}

        self._done = False
        self._signaled_eof = False
        self._on_complete: Callable[[ModelOutput], Awaitable[None]] | None = None
        self._plan: proto.DeepResearchPlanData | None = None

    @property
    def research_plan(self) -> proto.DeepResearchPlanData | None:
        """Set during a deep-research stream when a candidate carries a plan."""
        return self._plan

    def _on_complete_set(self, fn: Callable[[ModelOutput], Awaitable[None]]) -> None:
        """Internal hook. ChatSession uses this to capture cid/rid/rcid for
        follow-up turns."""
        self._on_complete = fn

    async def cancel(self) -> None:
        """Cancel the in-flight generation. Marks the stream done so further
        iteration raises StopAsyncIteration immediately and releases the
        underlying response. Idempotent."""
        self._done = True
        self._signaled_eof = True
        await self.aclose()

    def __aiter__(self) -> StreamReader:
        return self

    async def __anext__(self) -> Delta:
        if self._done and self._signaled_eof:
            raise StopAsyncIteration
        if self._done and not self._signaled_eof:
            self._signaled_eof = True
            raise StopAsyncIteration

        if not self._iter_started:
            self._iter_started = True
            self._fr = proto.FrameReader(self._next_chunk)

        assert self._fr is not None
        while True:
            try:
                env = await self._fr.__anext__()
            except StopAsyncIteration:
                # Stream ended. If we never saw any candidate text, the upstream
                # closed silently - Google sometimes does this on safety blocks
                # or when the request gets rate-limited mid-stream. Surface a
                # clearer error than a bare empty Delta.
                if not self._candidates:
                    self._done = True
                    self._signaled_eof = True
                    raise EmptyResponseError(
                        "Gemini closed the stream before sending any content. "
                        "Common causes: safety/policy block, account rate-limited, "
                        "or transient upstream failure - try again or reword."
                    ) from None
                self._done = True
                out = self._build_output()
                if self._on_complete is not None:
                    try:
                        await self._on_complete(out)
                    except Exception:
                        pass
                self._signaled_eof = True
                return Delta(text=self._chosen_text(), thoughts=self._chosen_thoughts(), done=True, output=out)

            ev = proto.parse_event(env)
            if ev is None:
                continue

            if ev.fatal_code:
                self._done = True
                self._signaled_eof = True
                err = classify_model_error(ev.fatal_code)
                raise err

            if ev.chat_id:
                self._chat_id = ev.chat_id
            if ev.reply_id:
                self._reply_id = ev.reply_id

            if not ev.candidates:
                continue

            primary: proto.CandidateUpdate | None = None
            for cu in ev.candidates:
                self._upsert(cu)
                if cu.deep_research_plan is not None and self._plan is None:
                    self._plan = cu.deep_research_plan
                if primary is None or len(cu.text) > len(primary.text):
                    primary = cu

            if primary is None or not primary.rcid:
                continue
            if not self._chosen_rcid:
                self._chosen_rcid = primary.rcid

            prev_text = self._last_text.get(primary.rcid, "")
            prev_thoughts = self._last_thoughts.get(primary.rcid, "")
            text_delta = _compute_delta(prev_text, primary.text)
            thoughts_delta = _compute_delta(prev_thoughts, primary.thoughts)
            self._last_text[primary.rcid] = primary.text
            self._last_thoughts[primary.rcid] = primary.thoughts

            d = Delta(
                text=primary.text,
                text_delta=text_delta,
                thoughts=primary.thoughts,
                thoughts_delta=thoughts_delta,
            )
            if primary.is_complete:
                out = self._build_output()
                d.done = True
                d.output = out
                self._done = True
                if self._on_complete is not None:
                    try:
                        await self._on_complete(out)
                    except Exception:
                        pass
            return d

    async def aclose(self) -> None:
        # Drain so the underlying response gets cleanly closed.
        try:
            await self._chunks.aclose()  # type: ignore[attr-defined]
        except Exception:
            pass

    async def _next_chunk(self) -> bytes:
        try:
            return await self._chunks.__anext__()
        except StopAsyncIteration:
            return b""

    def _upsert(self, cu: proto.CandidateUpdate) -> None:
        c = self._candidates.get(cu.rcid)
        if c is None:
            c = {
                "rcid": cu.rcid,
                "text": "",
                "thoughts": "",
                "web_images": [],
                "generated_images": [],
                "generated_videos": [],
                "generated_media": [],
            }
            self._candidates[cu.rcid] = c
            self._order.append(cu.rcid)
        if cu.text:
            c["text"] = cu.text
        if cu.thoughts:
            c["thoughts"] = cu.thoughts
        for w in cu.web_images:
            c["web_images"].append(WebImage(url=w["url"], alt=w.get("alt", "")))
        for g in cu.generated_images:
            c["generated_images"].append(
                GeneratedImage(
                    url=g["url"],
                    alt=g.get("alt", ""),
                    image_id=g.get("image_id", ""),
                    cid=self._chat_id,
                    rid=self._reply_id,
                    rcid=cu.rcid,
                )
            )
        for v in cu.generated_videos:
            c["generated_videos"].append(
                GeneratedVideo(
                    url=v["url"],
                    thumbnail=v.get("thumbnail", ""),
                    cid=self._chat_id,
                    rid=self._reply_id,
                    rcid=cu.rcid,
                )
            )
        for m in cu.generated_media:
            c["generated_media"].append(
                GeneratedMedia(
                    url=m.get("url", ""),
                    thumbnail=m.get("thumbnail", ""),
                    mp3_url=m.get("mp3_url", ""),
                    mp3_thumbnail=m.get("mp3_thumbnail", ""),
                    cid=self._chat_id,
                    rid=self._reply_id,
                    rcid=cu.rcid,
                )
            )

    def _build_output(self) -> ModelOutput:
        cands: list[Candidate] = []
        chosen_idx = 0
        for i, rcid in enumerate(self._order):
            c = self._candidates.get(rcid)
            if c is None:
                continue
            cands.append(Candidate(**c))
            if rcid == self._chosen_rcid:
                chosen_idx = i
        return ModelOutput(
            metadata=[self._chat_id, self._reply_id, self._chosen_rcid],
            candidates=cands,
            chosen=chosen_idx,
        )

    def _chosen_text(self) -> str:
        if self._chosen_rcid and self._chosen_rcid in self._candidates:
            return self._candidates[self._chosen_rcid]["text"]
        return ""

    def _chosen_thoughts(self) -> str:
        if self._chosen_rcid and self._chosen_rcid in self._candidates:
            return self._candidates[self._chosen_rcid]["thoughts"]
        return ""


def _compute_delta(prev: str, cur: str) -> str:
    if not cur:
        return ""
    if not prev:
        return cur
    if cur.startswith(prev):
        return cur[len(prev):]
    return cur
