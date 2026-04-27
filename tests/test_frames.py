"""FrameReader tests. The framing protocol is the trickiest piece of wire
glue (UTF-16 unit counting, anti-XSSI prefix, multi-frame), so we exercise
it deliberately."""

from __future__ import annotations

import json

import pytest

from aitunnel._protocol.frames import FrameReader


def _length_prefix(chunk: str) -> bytes:
    """Encode a JSON list as one frame. Length counts both the leading and
    trailing newline (matching Google's framing)."""
    utf16_len = sum(2 if ord(ch) > 0xFFFF else 1 for ch in chunk) + 2
    return f"{utf16_len}\n{chunk}\n".encode()


def _bytes_iter(blob: bytes):
    """Build a chunk reader that returns the whole blob then EOF."""
    consumed = [False]

    async def _read() -> bytes:
        if consumed[0]:
            return b""
        consumed[0] = True
        return blob
    return _read


def _envelope(text: str, complete: bool) -> list:
    return [
        "wrb.fr",
        None,
        json.dumps([
            None,
            ["c", "r"],
            None,
            None,
            [["rcid", [text], None, None, None, None, None, None, [2 if complete else 1]]],
        ]),
    ]


@pytest.mark.asyncio
async def test_single_frame() -> None:
    chunk = json.dumps([_envelope("Hello world.", True)])
    body = b")]}'\n" + _length_prefix(chunk)
    fr = FrameReader(_bytes_iter(body))
    envs = [e async for e in fr]
    assert len(envs) == 1
    assert envs[0][0] == "wrb.fr"


@pytest.mark.asyncio
async def test_multi_frame_streaming() -> None:
    f1 = _length_prefix(json.dumps([_envelope("Hello", False)]))
    f2 = _length_prefix(json.dumps([_envelope("Hello world.", True)]))
    body = b")]}'\n" + f1 + f2
    fr = FrameReader(_bytes_iter(body))
    envs = [e async for e in fr]
    assert len(envs) == 2


@pytest.mark.asyncio
async def test_utf16_emoji_counting() -> None:
    text = "Hi 🌟"  # emoji = surrogate pair = 2 UTF-16 units
    chunk = json.dumps([_envelope(text, True)])
    body = b")]}'\n" + _length_prefix(chunk)
    fr = FrameReader(_bytes_iter(body))
    envs = [e async for e in fr]
    assert len(envs) == 1


@pytest.mark.asyncio
async def test_missing_magic_prefix() -> None:
    chunk = json.dumps([_envelope("ok", True)])
    body = _length_prefix(chunk)  # no )]}' prefix
    fr = FrameReader(_bytes_iter(body))
    envs = [e async for e in fr]
    assert len(envs) == 1
