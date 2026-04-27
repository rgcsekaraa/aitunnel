"""BatchExecute primitive. Used for non-streaming RPCs (chat list, gem CRUD,
deep-research status, full-size image, etc.). Same wire shape as the
StreamGenerate `f.req` but with a flat outer payload list and `rpcids` query
param."""

from __future__ import annotations

import asyncio
import io
import json
import secrets
from dataclasses import dataclass
from urllib.parse import quote_plus

from .auth import SessionInfo
from .frames import FrameReader

# Known RPC IDs.
RPC_LIST_CHATS = "MaZiqc"
RPC_READ_CHAT = "hNvQHb"
RPC_DELETE_CHAT_1 = "GzXR5e"
RPC_DELETE_CHAT_2 = "qWymEb"
RPC_LIST_GEMS = "CNgdBe"
RPC_CREATE_GEM = "oMH3Zd"
RPC_UPDATE_GEM = "kHv0Vd"
RPC_DELETE_GEM = "UXcSJb"
RPC_GET_FULL_SIZE_IMAGE = "c8o8Fe"

# Deep research RPCs.
RPC_DEEP_RESEARCH_STATUS = "kwDCne"
RPC_DEEP_RESEARCH_BOOTSTRAP = "ku4Jyf"
RPC_BARD_SETTINGS = "ESY5D"


@dataclass(frozen=True)
class BatchCall:
    """One RPC inside a BatchExecute call."""

    rpc: str
    payload: str       # JSON-encoded payload, already serialised
    identifier: str = "generic"

    def serialise(self) -> list:
        return [self.rpc, self.payload, None, self.identifier]


@dataclass(frozen=True)
class BatchPart:
    """One unwrapped envelope from a BatchExecute response."""

    rpc: str
    body: str          # inner JSON string; caller decodes it
    identifier: str


def build_batch_execute(
    calls: list[BatchCall],
    sess: SessionInfo,
    source_path: str = "/app",
) -> tuple[dict[str, str], dict[str, str], str]:
    """Construct the BatchExecute POST. Returns (params, headers, body)."""
    if not calls:
        raise ValueError("at least one BatchCall required")

    rpcids = ",".join(c.rpc for c in calls)
    outer = json.dumps([[c.serialise() for c in calls]], separators=(",", ":"), ensure_ascii=False)

    lang = sess.language or "en"
    params: dict[str, str] = {
        "rpcids": rpcids,
        "hl": lang,
        "_reqid": f"{secrets.randbelow(900000) + 100000}",
        "rt": "c",
        "source-path": source_path,
    }
    if sess.build_label:
        params["bl"] = sess.build_label
    if sess.session_id:
        params["f.sid"] = sess.session_id

    headers = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "X-Same-Domain": "1",
        "x-goog-ext-525001261-jspb": "[1,null,null,null,null,null,null,null,[4]]",
        "x-goog-ext-73010989-jspb": "[0]",
    }

    body = f"at={quote_plus(sess.access_token)}&f.req={quote_plus(outer)}"
    return params, headers, body


async def parse_batch_response(raw: bytes) -> list[BatchPart]:
    """Decode a complete BatchExecute response body into typed parts."""
    buf = io.BytesIO(raw)

    async def _read_chunk() -> bytes:
        return buf.read(8192)

    # FrameReader is async, but we have all bytes already - it'll just drain
    # the BytesIO synchronously through the coroutine.
    out: list[BatchPart] = []
    fr = FrameReader(_read_chunk)
    async for env in fr:
        if not isinstance(env, list) or len(env) < 3:
            continue
        rpc = env[1] if isinstance(env[1], str) else ""
        body = env[2] if isinstance(env[2], str) else ""
        if not rpc or not body:
            continue
        ident = "generic"
        if len(env) >= 6 and isinstance(env[5], str) and env[5]:
            ident = env[5]
        out.append(BatchPart(rpc=rpc, body=body, identifier=ident))
    return out


# Keep asyncio import alive (used elsewhere if we refactor). Suppress lint.
_ = asyncio
