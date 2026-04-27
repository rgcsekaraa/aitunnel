"""Read chat history (turn-by-turn) for a persisted conversation."""

from __future__ import annotations

import json

from . import _protocol as proto
from .client import Client
from .errors import APIError, AuthError, NotStartedError
from .types import (
    Candidate,
    ChatHistory,
    ChatTurn,
    GeneratedImage,
    GeneratedMedia,
    GeneratedVideo,
    ModelOutput,
    WebImage,
)


async def read_chat(client: Client, cid: str, *, limit: int = 10) -> ChatHistory | None:
    """Fetch turns newest-first. Returns None if the model is still streaming
    a response in this chat (caller should retry)."""
    if not client.ready:
        raise NotStartedError("Client not started")
    if not cid:
        raise ValueError("cid required")
    if limit <= 0:
        limit = 10

    sess = client.session_info
    payload = json.dumps([cid, limit, None, 1, [1], [4], None, 1], separators=(",", ":"))
    parts, status = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_READ_CHAT, payload=payload)]
    )
    if status == 401:
        raise AuthError("session expired")
    if status != 200:
        raise APIError(status, "read chat failed")

    for part in parts:
        try:
            body = json.loads(part.body)
        except json.JSONDecodeError:
            continue
        # body[0] = list of turn dicts
        turns_data = body[0] if isinstance(body, list) and body and isinstance(body[0], list) else None
        if turns_data is None:
            continue
        turns: list[ChatTurn] = []
        for conv in turns_data:
            for t in _parse_conv_turn(conv, cid):
                turns.append(t)
        return ChatHistory(cid=cid, turns=turns)
    return None


async def latest_model_output(client: Client, cid: str) -> ModelOutput | None:
    """Return the most recent model-turn's output for a chat. Useful for
    deep-research recovery."""
    h = await read_chat(client, cid, limit=5)
    if h is None:
        return None
    for t in h.turns:
        if t.role == "model" and t.output is not None:
            return t.output
    return None


def _parse_conv_turn(node, cid: str) -> list[ChatTurn]:
    """One conv-turn → up to two ChatTurns (model + user)."""
    if not isinstance(node, list):
        return []
    out: list[ChatTurn] = []
    rid = ""
    if len(node) > 0 and isinstance(node[0], list) and len(node[0]) > 1:
        if isinstance(node[0][1], str):
            rid = node[0][1]

    # Model side at node[3][0]
    if len(node) > 3 and isinstance(node[3], list) and node[3] and isinstance(node[3][0], list):
        cands = node[3][0]
        cs: list[Candidate] = []
        for c in cands:
            cu = proto.parse_candidate(c)
            if cu is None:
                continue
            cs.append(_candidate_from_update(cu))
        if cs:
            mo = ModelOutput(metadata=[cid, rid], candidates=cs)
            out.append(ChatTurn(role="model", text=mo.text, output=mo))

    # User side at node[2][0][0]
    user_text = ""
    if (
        len(node) > 2
        and isinstance(node[2], list)
        and node[2]
        and isinstance(node[2][0], list)
        and node[2][0]
        and isinstance(node[2][0][0], str)
    ):
        user_text = node[2][0][0]
    if user_text:
        out.append(ChatTurn(role="user", text=user_text))
    return out


def _candidate_from_update(cu: proto.CandidateUpdate) -> Candidate:
    return Candidate(
        rcid=cu.rcid,
        text=cu.text,
        thoughts=cu.thoughts,
        web_images=[WebImage(url=w["url"], alt=w.get("alt", "")) for w in cu.web_images],
        generated_images=[
            GeneratedImage(url=g["url"], alt=g.get("alt", ""), image_id=g.get("image_id", ""))
            for g in cu.generated_images
        ],
        generated_videos=[
            GeneratedVideo(url=v["url"], thumbnail=v.get("thumbnail", "")) for v in cu.generated_videos
        ],
        generated_media=[
            GeneratedMedia(
                url=m.get("url", ""),
                thumbnail=m.get("thumbnail", ""),
                mp3_url=m.get("mp3_url", ""),
                mp3_thumbnail=m.get("mp3_thumbnail", ""),
            )
            for m in cu.generated_media
        ],
    )


async def _client_read_chat(self: Client, cid: str, *, limit: int = 10) -> ChatHistory | None:
    return await read_chat(self, cid, limit=limit)


async def _client_latest_model_output(self: Client, cid: str) -> ModelOutput | None:
    return await latest_model_output(self, cid)


Client.read_chat = _client_read_chat  # type: ignore[attr-defined]
Client.latest_model_output = _client_latest_model_output  # type: ignore[attr-defined]
