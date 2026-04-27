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


_RE_ACCESS_TOKEN = re.compile(r'"SNlM0e":\s*"(.*?)"')
_RE_BUILD_LABEL = re.compile(r'"cfb2h":\s*"(.*?)"')
_RE_SESSION_ID = re.compile(r'"FdrFJe":\s*"(.*?)"')
_RE_LANGUAGE = re.compile(r'"TuX5cc":\s*"(.*?)"')
_RE_PUSH_ID = re.compile(r'"qKIAYe":\s*"(.*?)"')


def parse_session_info(html: str) -> SessionInfo | None:
    """Extract session-info fields from the bootstrap HTML.

    Returns None if SNlM0e is absent — that means cookies didn't authenticate
    and the page Google served was the marketing/login fallback.
    """
    m = _RE_ACCESS_TOKEN.search(html)
    if not m or not m.group(1):
        return None

    def _grab(rx: re.Pattern[str]) -> str:
        match = rx.search(html)
        return match.group(1) if match else ""

    push_id = _grab(_RE_PUSH_ID)
    if not push_id:
        # Fallback used by the upstream Python lib when qKIAYe is missing.
        push_id = "feeds/mcudyrk2a4khkz"

    return SessionInfo(
        access_token=m.group(1),
        build_label=_grab(_RE_BUILD_LABEL),
        session_id=_grab(_RE_SESSION_ID),
        language=_grab(_RE_LANGUAGE),
        push_id=push_id,
    )
