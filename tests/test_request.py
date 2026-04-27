"""Verify the StreamGenerate request encoder lands the right values at the
right magic indices."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from aitunnel._protocol.auth import SessionInfo
from aitunnel._protocol.request import FileRef, GenerateOpts, build_generate


def _decode_inner(body: str) -> list:
    """Pull the inner array out of a built request body."""
    qs = parse_qs(body)
    f_req = qs["f.req"][0]
    outer = json.loads(f_req)
    return json.loads(outer[1])


def _sess() -> SessionInfo:
    return SessionInfo(access_token="TOKEN", build_label="b42", session_id="sess", language="en")


def test_temporary_flag() -> None:
    _, _, body = build_generate("hi", _sess(), GenerateOpts(temporary=True))
    inner = _decode_inner(body)
    assert inner[0][0] == "hi"
    assert inner[7] == 1   # streaming
    assert inner[45] == 1  # temporary


def test_files_populate_message() -> None:
    files = [FileRef(url="/u/abc", filename="a.png"), FileRef(url="/u/def", filename="b.jpg")]
    _, _, body = build_generate("describe", _sess(), GenerateOpts(files=files))
    inner = _decode_inner(body)
    file_data = inner[0][3]
    assert len(file_data) == 2
    assert file_data[0] == [["/u/abc"], "a.png"]


def test_gem_id_at_index_19() -> None:
    _, _, body = build_generate("hi", _sess(), GenerateOpts(gem_id="g_user_123"))
    inner = _decode_inner(body)
    assert inner[19] == "g_user_123"


def test_deep_research_flags() -> None:
    _, _, body = build_generate("research X", _sess(), GenerateOpts(deep_research=True))
    inner = _decode_inner(body)
    tok = inner[3]
    assert isinstance(tok, str) and tok.startswith("!") and len(tok) > 100
    uid = inner[4]
    assert isinstance(uid, str) and len(uid) == 32   # hex uuid (no dashes)
    assert inner[49] == 1
    assert inner[54] is not None
    assert inner[55] is not None


def test_default_metadata_for_fresh_chat() -> None:
    _, _, body = build_generate("hi", _sess(), GenerateOpts())
    inner = _decode_inner(body)
    md = inner[2]
    assert isinstance(md, list) and len(md) >= 1
    assert md[0] == ""  # default sentinel


def test_chat_metadata_passthrough() -> None:
    chat_md = ["c_abc", "r_def", "rc_ghi", None, None, None, None, None, None, ""]
    _, _, body = build_generate("hi", _sess(), GenerateOpts(chat_metadata=chat_md))
    inner = _decode_inner(body)
    assert inner[2][0] == "c_abc"
