"""List + delete persisted chats. Both endpoints use BatchExecute under
the hood; we run the two ListChats variants (pinned + unpinned) in
parallel via `asyncio.gather`."""

from __future__ import annotations

import asyncio
import json

from . import _protocol as proto
from .client import Client
from .errors import APIError, AuthError, NotStartedError
from .types import ChatInfo


async def list_chats(client: Client, *, recent: int = 13) -> list[ChatInfo]:
    """Fetch recent persisted chats. Combines pinned + unpinned, dedup by CID."""
    if not client.ready:
        raise NotStartedError("Client not started")
    if recent <= 0:
        recent = 13

    sess = client.session_info

    payloads = [
        json.dumps([recent, None, [1, None, 1]], separators=(",", ":")),
        json.dumps([recent, None, [0, None, 1]], separators=(",", ":")),
    ]

    async def _one(p: str) -> tuple[list[proto.BatchPart], int]:
        return await client.transport.batch_execute(
            sess, [proto.BatchCall(rpc=proto.RPC_LIST_CHATS, payload=p)]
        )

    results = await asyncio.gather(*[_one(p) for p in payloads])

    chats: list[ChatInfo] = []
    seen: set[str] = set()
    for parts, status in results:
        if status == 401:
            raise AuthError("session expired")
        if status != 200:
            raise APIError(status, "list chats failed")
        _append_chats(chats, parts, seen)
    return chats


async def delete_chat(client: Client, cid: str) -> None:
    """Remove a persisted chat. Idempotent; runs both required RPCs sequentially
    (the second depends on the first's effect)."""
    if not client.ready:
        raise NotStartedError("Client not started")
    if not cid:
        raise ValueError("cid required")
    sess = client.session_info

    for call in (
        proto.BatchCall(
            rpc=proto.RPC_DELETE_CHAT_1,
            payload=json.dumps([cid], separators=(",", ":")),
        ),
        proto.BatchCall(
            rpc=proto.RPC_DELETE_CHAT_2,
            payload=json.dumps([cid, [1, None, 0, 1]], separators=(",", ":")),
        ),
    ):
        _, status = await client.transport.batch_execute(sess, [call])
        if status == 401:
            raise AuthError("session expired")
        if status != 200:
            raise APIError(status, "delete chat failed")


def _append_chats(out: list[ChatInfo], parts: list[proto.BatchPart], seen: set[str]) -> None:
    for part in parts:
        try:
            body = json.loads(part.body)
        except json.JSONDecodeError:
            continue
        # body[2] = list of chat rows
        if not isinstance(body, list) or len(body) < 3:
            continue
        rows = body[2]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) < 2:
                continue
            cid = row[0] if isinstance(row[0], str) else ""
            if not cid or cid in seen:
                continue
            seen.add(cid)
            title = row[1] if len(row) > 1 and isinstance(row[1], str) else ""
            is_pinned = False
            if len(row) > 2:
                v = row[2]
                if isinstance(v, bool):
                    is_pinned = v
                elif isinstance(v, (int, float)):
                    is_pinned = bool(v)
            ts = 0.0
            if len(row) > 5 and isinstance(row[5], list) and len(row[5]) >= 2:
                sec = row[5][0]
                nanos = row[5][1]
                if isinstance(sec, (int, float)) and isinstance(nanos, (int, float)):
                    ts = float(sec) + float(nanos) / 1e9
            out.append(ChatInfo(cid=cid, title=title, is_pinned=is_pinned, timestamp=ts))


# Patch onto Client.
async def _client_list_chats(self: Client, *, recent: int = 13) -> list[ChatInfo]:
    return await list_chats(self, recent=recent)


async def _client_delete_chat(self: Client, cid: str) -> None:
    return await delete_chat(self, cid)


Client.list_chats = _client_list_chats  # type: ignore[attr-defined]
Client.delete_chat = _client_delete_chat  # type: ignore[attr-defined]


# Re-export for direct import via `from aitunnel import ChatInfo`.
__all__ = ["list_chats", "delete_chat", "ChatInfo"]
