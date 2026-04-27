"""Custom Gem CRUD (saved system-prompt personas)."""

from __future__ import annotations

import json

from . import _protocol as proto
from .client import Client
from .errors import APIError, AuthError, NotStartedError
from .types import Gem


async def list_gems(client: Client, *, include_hidden: bool = False) -> list[Gem]:
    """Fetch all gems available to this account: predefined system gems plus
    user-created custom gems."""
    if not client.ready:
        raise NotStartedError("Client not started")
    sess = client.session_info
    system_tier = 4 if include_hidden else 3
    lang = sess.language or "en"
    calls = [
        proto.BatchCall(
            rpc=proto.RPC_LIST_GEMS,
            payload=f'[{system_tier},["{_json_escape(lang)}"],0]',
            identifier="system",
        ),
        proto.BatchCall(
            rpc=proto.RPC_LIST_GEMS,
            payload=f'[2,["{_json_escape(lang)}"],0]',
            identifier="custom",
        ),
    ]
    parts, status = await client.transport.batch_execute(sess, calls)
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "list gems failed")

    gems: list[Gem] = []
    for part in parts:
        predefined = part.identifier == "system"
        try:
            body = json.loads(part.body)
        except json.JSONDecodeError:
            continue
        rows = body[2] if isinstance(body, list) and len(body) > 2 else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) < 2:
                continue
            gid = row[0] if isinstance(row[0], str) else ""
            if not gid:
                continue
            meta = row[1] if isinstance(row[1], list) else []
            name = meta[0] if len(meta) > 0 and isinstance(meta[0], str) else ""
            desc = meta[1] if len(meta) > 1 and isinstance(meta[1], str) else ""
            prompt = ""
            if len(row) > 2 and isinstance(row[2], list) and row[2] and isinstance(row[2][0], str):
                prompt = row[2][0]
            gems.append(Gem(id=gid, name=name, description=desc, prompt=prompt, predefined=predefined))
    return gems


async def create_gem(client: Client, name: str, prompt: str, description: str = "") -> Gem:
    if not client.ready:
        raise NotStartedError("Client not started")
    if not name or not prompt:
        raise ValueError("gem name and prompt are required")
    sess = client.session_info
    payload = json.dumps(
        [[name, description, prompt, None, None, None, None, None, 0, None, 1, None, None, None, []]],
        separators=(",", ":"),
    )
    parts, status = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_CREATE_GEM, payload=payload)]
    )
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "create gem failed")
    if not parts:
        raise APIError(200, "create gem: empty response")
    try:
        body = json.loads(parts[0].body)
    except json.JSONDecodeError:
        raise APIError(200, "create gem: parse failed") from None
    if not isinstance(body, list) or not body or not isinstance(body[0], str):
        raise APIError(200, "create gem: no ID in response")
    return Gem(id=body[0], name=name, description=description, prompt=prompt, predefined=False)


async def update_gem(client: Client, gem_id: str, name: str, prompt: str, description: str = "") -> Gem:
    if not client.ready:
        raise NotStartedError("Client not started")
    if not gem_id or not name or not prompt:
        raise ValueError("gem id, name, and prompt are all required")
    sess = client.session_info
    payload = json.dumps(
        [
            gem_id,
            [name, description, prompt, None, None, None, None, None, 0, None, 1, None, None, None, [], 0],
        ],
        separators=(",", ":"),
    )
    _, status = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_UPDATE_GEM, payload=payload)]
    )
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "update gem failed")
    return Gem(id=gem_id, name=name, description=description, prompt=prompt)


async def delete_gem(client: Client, gem_id: str) -> None:
    if not client.ready:
        raise NotStartedError("Client not started")
    if not gem_id:
        raise ValueError("gem id required")
    sess = client.session_info
    payload = json.dumps([gem_id], separators=(",", ":"))
    _, status = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_DELETE_GEM, payload=payload)]
    )
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "delete gem failed")


def _json_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# Patch.
Client.list_gems = lambda self, *, include_hidden=False: list_gems(self, include_hidden=include_hidden)  # type: ignore[attr-defined]
Client.create_gem = lambda self, name, prompt, description="": create_gem(self, name, prompt, description)  # type: ignore[attr-defined]
Client.update_gem = lambda self, gem_id, name, prompt, description="": update_gem(self, gem_id, name, prompt, description)  # type: ignore[attr-defined]
Client.delete_gem = lambda self, gem_id: delete_gem(self, gem_id)  # type: ignore[attr-defined]
