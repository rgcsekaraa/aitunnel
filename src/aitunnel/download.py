"""Download methods for generated images/videos/media. Each typed object
gets `save_to(path)` and `open()` style helpers via free functions taking
the Client."""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

from .client import Client
from .types import GeneratedImage, GeneratedMedia, GeneratedVideo, WebImage


async def save_to(client: Client, url: str, fp: IO[bytes]) -> str:
    """Download `url`, write each chunk to `fp`. Returns Content-Type."""
    async def _write(b: bytes) -> None:
        fp.write(b)
    return await client.transport.download(url, _write)


async def save_file(client: Client, url: str, path: str | Path, *, default_ext: str = ".bin") -> Path:
    """Download `url` to `path`. If `path` is a directory, an auto filename
    is generated."""
    p = Path(path)
    if p.exists() and p.is_dir():
        name = "download" + _ext_from_url(url, default_ext)
        p = p / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        await save_to(client, url, fh)
    return p


def _ext_from_url(url: str, default: str) -> str:
    last = url.rsplit("/", 1)[-1]
    if "." in last and "?" not in last and len(last) - last.rindex(".") <= 6:
        return last[last.rindex("."):]
    return default


# Image / video / media helpers. We attach methods to the Pydantic models
# at import time. Pydantic v2 allows arbitrary attribute access via class
# methods (not instance fields) so this is safe.

async def _wi_save_to(self: WebImage, client: Client, fp: IO[bytes]) -> str:
    return await save_to(client, self.url, fp)


async def _wi_save_file(self: WebImage, client: Client, path: str | Path) -> Path:
    return await save_file(client, self.url, path, default_ext=".jpg")


WebImage.save_to = _wi_save_to  # type: ignore[attr-defined]
WebImage.save_file = _wi_save_file  # type: ignore[attr-defined]


async def _gi_save_to(self: GeneratedImage, client: Client, fp: IO[bytes]) -> str:
    url = await _resolve_full_size(client, self) or self.url
    return await save_to(client, url, fp)


async def _gi_save_file(self: GeneratedImage, client: Client, path: str | Path) -> Path:
    url = await _resolve_full_size(client, self) or self.url
    return await save_file(client, url, path, default_ext=".png")


GeneratedImage.save_to = _gi_save_to  # type: ignore[attr-defined]
GeneratedImage.save_file = _gi_save_file  # type: ignore[attr-defined]


async def _gv_save_to(self: GeneratedVideo, client: Client, fp: IO[bytes]) -> str:
    return await save_to(client, self.url, fp)


async def _gv_save_file(self: GeneratedVideo, client: Client, path: str | Path) -> Path:
    return await save_file(client, self.url, path, default_ext=".mp4")


GeneratedVideo.save_to = _gv_save_to  # type: ignore[attr-defined]
GeneratedVideo.save_file = _gv_save_file  # type: ignore[attr-defined]


async def _gm_save_to(self: GeneratedMedia, client: Client, fp: IO[bytes]) -> str:
    return await save_to(client, self.url or self.mp3_url, fp)


async def _gm_save_file(self: GeneratedMedia, client: Client, path: str | Path) -> Path:
    url = self.url or self.mp3_url
    ext = ".mp4" if self.url else ".mp3"
    return await save_file(client, url, path, default_ext=ext)


GeneratedMedia.save_to = _gm_save_to  # type: ignore[attr-defined]
GeneratedMedia.save_file = _gm_save_file  # type: ignore[attr-defined]


async def _resolve_full_size(client: Client, img: GeneratedImage) -> str:
    """Try the full-size image RPC; if it succeeds, return that URL with the
    `=d-I?alr=yes` suffix that asks for the original encoding. Falls back to
    empty string on any failure (caller uses `img.url`)."""
    if not (img.cid and img.rid and img.rcid and img.image_id):
        return ""
    try:
        from .fullsize import get_full_size_url
        url = await get_full_size_url(client, img.cid, img.rid, img.rcid, img.image_id)
        if url:
            return url + "=d-I?alr=yes"
    except Exception:
        pass
    return ""


# Suppress unused import.
_ = os
