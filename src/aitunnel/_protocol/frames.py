"""Decoder for Google's length-prefixed framing protocol.

Body shape (after the `)]}'` anti-XSSI prefix):

    <utf16-units>\\n<json-payload>\\n<utf16-units>\\n<json-payload>\\n...

Each frame's length counts UTF-16 code units (matching JavaScript's
`String.length`), not bytes — so emoji and CJK count as 2. We track this
exactly because off-by-one errors here desync the whole stream.

The frame's JSON payload is a *list of envelopes*; we flatten it and yield
envelopes one at a time so callers don't worry about the framing.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

# Anti-XSSI prefix Google sticks at the start of every response.
_MAGIC_PREFIX = ")]}'"
_RE_LENGTH = re.compile(r"^(\d+)\n")


class FrameReader:
    """Async iterator over envelopes. `read_chunk` must be a coroutine that
    returns more bytes (or `b''` at EOF). Used by `transport` over a curl_cffi
    streaming response."""

    def __init__(self, read_chunk: Callable[[], Awaitable[bytes]]) -> None:
        self._read_chunk = read_chunk
        self._buf = ""           # decoded UTF-8 text waiting to be parsed
        self._raw_buf = b""      # raw bytes waiting for valid UTF-8 boundary
        self._primed = False     # have we consumed the )]}' prefix?
        self._eof = False
        self._pending: list[Any] = []  # envelopes already decoded but not yielded

    def __aiter__(self) -> AsyncIterator[Any]:
        return self

    async def __anext__(self) -> Any:
        env = await self._next()
        if env is None:
            raise StopAsyncIteration
        return env

    async def _next(self) -> Any | None:
        if self._pending:
            return self._pending.pop(0)
        if not self._primed:
            await self._consume_magic()
            self._primed = True
        while True:
            ok = await self._read_one_frame()
            if not ok:
                return None
            if self._pending:
                return self._pending.pop(0)
            # Empty frame, keep reading.

    async def _consume_magic(self) -> None:
        # Wait until we have at least 4 chars to peek.
        while len(self._buf) < 4 and not self._eof:
            await self._fill()
        if self._buf.startswith(_MAGIC_PREFIX):
            self._buf = self._buf[len(_MAGIC_PREFIX):]
        # Skip leading whitespace.
        self._buf = self._buf.lstrip()

    async def _read_one_frame(self) -> bool:
        # Skip inter-frame whitespace.
        while True:
            stripped = self._buf.lstrip()
            if stripped:
                self._buf = stripped
                break
            if self._eof and not self._buf:
                return False
            await self._fill()

        # Read the length line. Need at least one digit then a newline.
        while True:
            m = _RE_LENGTH.match(self._buf)
            if m:
                break
            if self._eof:
                return False
            await self._fill()

        length_str = m.group(1)
        utf16_len = int(length_str)
        digit_end = len(length_str)
        # Position cursor at the leading \n (which counts toward utf16_len
        # per Google's protocol). We DON'T strip it from the buffer.
        body_start = digit_end

        # Wait until we have enough chars to satisfy `utf16_len` UTF-16 units.
        while True:
            chars, units = _utf16_slice(self._buf, body_start, utf16_len)
            if units >= utf16_len or self._eof:
                break
            await self._fill()

        chunk = self._buf[body_start:body_start + chars].strip()
        self._buf = self._buf[body_start + chars:]

        if not chunk:
            return True

        try:
            decoded = json.loads(chunk)
        except json.JSONDecodeError:
            # Tolerate one bad frame; the next one might still parse.
            return True

        if isinstance(decoded, list):
            self._pending.extend(decoded)
        else:
            self._pending.append(decoded)
        return True

    async def _fill(self) -> None:
        """Pull more bytes from the source and append to `_buf` as UTF-8 text."""
        chunk = await self._read_chunk()
        if not chunk:
            self._eof = True
            # Flush any leftover raw bytes (best-effort).
            if self._raw_buf:
                self._buf += self._raw_buf.decode("utf-8", errors="replace")
                self._raw_buf = b""
            return
        # Combine with any leftover bytes from a partial UTF-8 sequence.
        data = self._raw_buf + chunk
        try:
            self._buf += data.decode("utf-8")
            self._raw_buf = b""
        except UnicodeDecodeError as e:
            # Cut at the last valid byte boundary; carry the trailing bytes
            # forward to combine with the next chunk.
            if e.start > 0:
                self._buf += data[: e.start].decode("utf-8")
            self._raw_buf = data[e.start:]


def _utf16_slice(s: str, start: int, units: int) -> tuple[int, int]:
    """Walk `s` from `start` consuming up to `units` UTF-16 code units.

    Returns (python_chars_consumed, utf16_units_consumed). BMP runes = 1
    unit; non-BMP (emoji etc.) = 2 (one surrogate pair).
    """
    chars = 0
    consumed = 0
    limit = len(s)
    while consumed < units and (start + chars) < limit:
        cp = ord(s[start + chars])
        u = 2 if cp > 0xFFFF else 1
        if consumed + u > units:
            break
        consumed += u
        chars += 1
    return chars, consumed
