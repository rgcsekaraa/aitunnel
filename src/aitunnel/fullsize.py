"""Full-size image RPC (c8o8Fe). Resolves a generated image's preview URL
to its original."""

from __future__ import annotations

import json

from . import _protocol as proto
from .client import Client
from .errors import APIError, AuthError, NotStartedError


async def get_full_size_url(
    client: Client, cid: str, rid: str, rcid: str, image_id: str
) -> str:
    """Returns the full-size image URL, or empty if Google's response shape
    didn't include one."""
    if not client.ready:
        raise NotStartedError("Client not started")
    if not all((cid, rid, rcid, image_id)):
        raise ValueError("cid/rid/rcid/image_id all required")
    sess = client.session_info
    payload = json.dumps(
        [
            [
                [None, None, None, [None, None, None, None, None, ""]],
                [image_id, 0],
                None,
                [19, ""],
                None,
                None,
                None,
                None,
                None,
                "",
            ],
            [rid, rcid, cid, None, ""],
            1,
            0,
            1,
        ],
        separators=(",", ":"),
    )
    parts, status = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_GET_FULL_SIZE_IMAGE, payload=payload)]
    )
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "get full-size image failed")
    if not parts:
        return ""
    try:
        inner = json.loads(parts[0].body)
    except json.JSONDecodeError:
        return ""
    if isinstance(inner, list) and inner and isinstance(inner[0], str):
        return inner[0]
    return ""


# Patch onto Client.
async def _client_get_full_size_image(self: Client, cid: str, rid: str, rcid: str, image_id: str) -> str:
    return await get_full_size_url(self, cid, rid, rcid, image_id)


Client.get_full_size_image = _client_get_full_size_image  # type: ignore[attr-defined]
