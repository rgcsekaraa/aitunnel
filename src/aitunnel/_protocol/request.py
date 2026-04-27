"""Encoder for the StreamGenerate POST body. Google uses a very specific
"f.req" format: a 2-element JSON array whose second element is a string
containing another JSON-encoded array of 69 elements with magic indices."""

from __future__ import annotations

import base64
import json
import secrets
import uuid
from dataclasses import dataclass, field
from urllib.parse import quote_plus

from .auth import SessionInfo

# Magic indices into the 69-element inner array. Named to avoid magic-number
# noise in the encoder body.
_IDX_MESSAGE = 0
_IDX_LANGUAGE = 1
_IDX_METADATA = 2
_IDX_DEEP_TOKEN = 3
_IDX_DEEP_UUID = 4
_IDX_STREAMING = 7
_IDX_GEM = 19
_IDX_TEMPORARY = 45
_IDX_DEEP_FLAG = 49
_IDX_DEEP_NESTED_1 = 54
_IDX_DEEP_NESTED_2 = 55
_IDX_CONV_UUID = 59

# inner[2] for a brand-new chat. Multi-turn chats put [cid, rid, rcid, ...]
# here instead.
DEFAULT_METADATA: list = ["", "", "", None, None, None, None, None, None, ""]


@dataclass(frozen=True)
class FileRef:
    """One uploaded file: the URL Google returned, and the display name."""

    url: str
    filename: str


@dataclass
class GenerateOpts:
    """Per-call knobs. Empty fields use defaults."""

    model_headers: dict[str, str] = field(default_factory=dict)
    chat_metadata: list | None = None  # None -> DEFAULT_METADATA
    temporary: bool = False
    gem_id: str = ""
    files: list[FileRef] = field(default_factory=list)
    deep_research: bool = False


def build_generate(
    prompt: str,
    sess: SessionInfo,
    opts: GenerateOpts,
) -> tuple[dict[str, str], dict[str, str], str]:
    """Construct the StreamGenerate POST.

    Returns (params, headers, body) where body is already
    `application/x-www-form-urlencoded`.
    """
    if not prompt:
        raise ValueError("prompt must be non-empty")

    conv_uuid = str(uuid.uuid4()).upper()

    # message[3] carries file refs as [[[url], filename], ...].
    file_data = [[[f.url], f.filename] for f in opts.files]
    message = [prompt, 0, None, file_data, None, None, 0]

    inner: list = [None] * 69
    inner[_IDX_MESSAGE] = message
    lang = sess.language or "en"
    inner[_IDX_LANGUAGE] = [lang]
    inner[_IDX_METADATA] = opts.chat_metadata if opts.chat_metadata is not None else DEFAULT_METADATA

    if opts.deep_research:
        # The upstream web client sends a long random URL-safe-base64 token
        # plus a hex UUID when entering deep-research mode.
        inner[_IDX_DEEP_TOKEN] = "!" + base64.urlsafe_b64encode(secrets.token_bytes(2600)).decode().rstrip("=")
        inner[_IDX_DEEP_UUID] = uuid.uuid4().hex

    inner[6] = [1]
    inner[_IDX_STREAMING] = 1
    inner[10] = 1
    inner[11] = 0
    inner[17] = [[0]]
    inner[18] = 0
    if opts.gem_id:
        inner[_IDX_GEM] = opts.gem_id
    inner[27] = 1
    inner[30] = [4]
    inner[41] = [1]
    if opts.temporary:
        inner[_IDX_TEMPORARY] = 1
    if opts.deep_research:
        inner[_IDX_DEEP_FLAG] = 1
    inner[53] = 0
    if opts.deep_research:
        inner[_IDX_DEEP_NESTED_1] = [[[[[1]]]]]
        inner[_IDX_DEEP_NESTED_2] = [[1]]
    inner[_IDX_CONV_UUID] = conv_uuid
    inner[61] = []
    inner[68] = 2

    inner_json = json.dumps(inner, separators=(",", ":"), ensure_ascii=False)
    f_req = json.dumps([None, inner_json], separators=(",", ":"), ensure_ascii=False)

    params: dict[str, str] = {
        "_reqid": _rand_reqid(),
        "rt": "c",
    }
    if sess.build_label:
        params["bl"] = sess.build_label
    if sess.session_id:
        params["f.sid"] = sess.session_id
    if lang:
        params["hl"] = lang

    headers: dict[str, str] = {
        "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        "Origin": "https://gemini.google.com",
        "Referer": "https://gemini.google.com/",
        "X-Same-Domain": "1",
        "x-goog-ext-525005358-jspb": f'["{conv_uuid}",1]',
    }
    headers.update(opts.model_headers)

    body = f"at={quote_plus(sess.access_token)}&f.req={quote_plus(f_req)}"
    return params, headers, body


def _rand_reqid() -> str:
    return f"{secrets.randbelow(900000) + 100000}"
