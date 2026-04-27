"""Batch-execute encoding + parsing roundtrip."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

from aitunnel._protocol.auth import SessionInfo
from aitunnel._protocol.batch import (
    RPC_LIST_CHATS,
    RPC_LIST_GEMS,
    BatchCall,
    build_batch_execute,
    parse_batch_response,
)


def test_build_batch_shape() -> None:
    sess = SessionInfo(access_token="T", build_label="b", session_id="s", language="en")
    calls = [
        BatchCall(rpc=RPC_LIST_CHATS, payload="[13,null,[1,null,1]]", identifier="chats"),
        BatchCall(rpc=RPC_LIST_GEMS, payload='[3,["en"],0]', identifier="system"),
    ]
    params, headers, body = build_batch_execute(calls, sess, "/app")
    assert params["rpcids"] == f"{RPC_LIST_CHATS},{RPC_LIST_GEMS}"
    assert params["source-path"] == "/app"
    assert "bl" in params
    assert headers["X-Same-Domain"] == "1"
    qs = parse_qs(body)
    f_req = qs["f.req"][0]
    outer = json.loads(f_req)
    assert isinstance(outer, list) and len(outer) == 1
    inner_calls = outer[0]
    assert len(inner_calls) == 2
    assert inner_calls[0][0] == RPC_LIST_CHATS
    assert inner_calls[0][3] == "chats"


def _length_prefix(chunk: str) -> bytes:
    utf16_len = sum(2 if ord(ch) > 0xFFFF else 1 for ch in chunk) + 2
    return f"{utf16_len}\n{chunk}\n".encode("utf-8")


@pytest.mark.asyncio
async def test_parse_batch_response_roundtrip() -> None:
    env1 = ["wrb.fr", RPC_LIST_GEMS,
            '[[null,null,[["gem1",["Coder","helps with code"],["You are..."]]]]]',
            None, None, "system"]
    env2 = ["wrb.fr", RPC_LIST_GEMS,
            '[[null,null,[["gem2",["Editor","copy editor"],["edit it"]]]]]',
            None, None, "custom"]
    chunk = json.dumps([env1, env2])
    body = b")]}'\n" + _length_prefix(chunk)
    parts = await parse_batch_response(body)
    assert len(parts) == 2
    assert parts[0].identifier == "system"
    assert parts[1].identifier == "custom"
    assert "gem1" in parts[0].body
