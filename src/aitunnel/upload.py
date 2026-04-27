"""Public file-upload API. Clients call `client.upload_file(...)` to push a
file to Google's content store, then attach the returned `FileAttachment`
to a subsequent `client.query(...)` call."""

from __future__ import annotations

from pathlib import Path

from .client import Client
from .errors import NotStartedError
from .types import FileAttachment


async def _upload_bytes(
    client: Client,
    filename: str,
    content_type: str,
    data: bytes,
) -> FileAttachment:
    if not client.ready:
        raise NotStartedError("Client not started")
    if not data:
        raise ValueError("empty upload")
    push_id = client.push_id
    if not push_id:
        raise NotStartedError("push_id missing — re-start the client")
    # Retry the upload itself — the content-push endpoint occasionally returns
    # transient 5xx during heavy use, which fails the whole multi-file flow
    # without a retry. Addresses upstream gemini_webapi#284.
    import asyncio as _asyncio
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            url = await client.transport.upload_file(push_id, filename, content_type, data)
            return FileAttachment(url=url, filename=filename or "upload.bin")
        except Exception as e:
            last_err = e
            if attempt >= 3:
                break
            await _asyncio.sleep(0.5 * attempt)
    assert last_err is not None
    raise last_err


async def upload_file(
    client: Client,
    filename: str,
    data: bytes,
    *,
    content_type: str = "",
) -> FileAttachment:
    """Upload bytes. `filename` is what the model sees; if `content_type` is
    empty it's inferred from the filename's extension."""
    return await _upload_bytes(client, filename, content_type, data)


async def upload_path(client: Client, path: str | Path) -> FileAttachment:
    """Upload a file from disk. Filename + content-type both inferred from
    the path."""
    p = Path(path)
    return await _upload_bytes(client, p.name, "", p.read_bytes())


# Method-style API on Client. Keeping the free functions above for clarity;
# these mirror them so callers can write `client.upload_file(...)`.

async def _client_upload_file(self: Client, filename: str, data: bytes, *, content_type: str = "") -> FileAttachment:
    return await upload_file(self, filename, data, content_type=content_type)


async def _client_upload_path(self: Client, path: str | Path) -> FileAttachment:
    return await upload_path(self, path)


# Patch onto Client at import time.
Client.upload_file = _client_upload_file  # type: ignore[attr-defined]
Client.upload_path = _client_upload_path  # type: ignore[attr-defined]
