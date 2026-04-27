"""Endpoints + bootstrap-HTML parser. Pulls the SNlM0e token (and a few other
fields) out of `gemini.google.com/app`'s response, so we can use them in
subsequent requests."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Endpoints used by the Gemini web app.
GOOGLE_URL = "https://www.google.com"
INIT_URL = "https://gemini.google.com/app"
GENERATE_URL = (
    "https://gemini.google.com/_/BardChatUi/data/"
    "assistant.lamda.BardFrontendService/StreamGenerate"
)
ROTATE_URL = "https://accounts.google.com/RotateCookies"
UPLOAD_URL = "https://content-push.googleapis.com/upload"
BATCH_EXEC_URL = "https://gemini.google.com/_/BardChatUi/data/batchexecute"


@dataclass(frozen=True)
class SessionInfo:
    access_token: str          # SNlM0e
    build_label: str = ""      # cfb2h - sent as `bl` query param
    session_id: str = ""       # FdrFJe - sent as `f.sid` query param
    language: str = ""         # TuX5cc - sent as `hl` query param
    push_id: str = ""          # qKIAYe - used as Push-ID header for /upload


# Multiple patterns for SNlM0e because Google occasionally changes how the
# token is embedded in the bootstrap HTML — see HanaokaYuzu/Gemini-API#297.
# We try each in order; first hit wins. Adding more patterns here is the
# fastest fix when the wire format changes.
_RE_ACCESS_TOKENS: list[re.Pattern[str]] = [
    re.compile(r'"SNlM0e":\s*"(.*?)"'),
    re.compile(r'SNlM0e\\?":\\?"([^\\"]+)\\?"'),  # escaped variant some builds use
    re.compile(r"['\"]SNlM0e['\"]:\s*['\"]([^'\"]+)['\"]"),  # single-quoted variant
]
_RE_BUILD_LABEL = re.compile(r'"cfb2h":\s*"(.*?)"')
_RE_SESSION_ID = re.compile(r'"FdrFJe":\s*"(.*?)"')
_RE_LANGUAGE = re.compile(r'"TuX5cc":\s*"(.*?)"')
_RE_PUSH_ID = re.compile(r'"qKIAYe":\s*"(.*?)"')


def parse_session_info(html: str) -> SessionInfo | None:
    """Extract session-info fields from the bootstrap HTML.

    Returns None if SNlM0e is absent — that means cookies didn't authenticate
    and the page Google served was the marketing/login fallback.
    """
    token = ""
    for rx in _RE_ACCESS_TOKENS:
        m = rx.search(html)
        if m and m.group(1):
            token = m.group(1)
            break
    if not token:
        return None

    def _grab(rx: re.Pattern[str]) -> str:
        match = rx.search(html)
        return match.group(1) if match else ""

    push_id = _grab(_RE_PUSH_ID)
    if not push_id:
        # Fallback used by the upstream Python lib when qKIAYe is missing.
        push_id = "feeds/mcudyrk2a4khkz"

    return SessionInfo(
        access_token=token,
        build_label=_grab(_RE_BUILD_LABEL),
        session_id=_grab(_RE_SESSION_ID),
        language=_grab(_RE_LANGUAGE),
        push_id=push_id,
    )
