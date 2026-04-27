"""Walks the decoded frame envelopes from FrameReader and turns them into
typed Events. Each Event carries cid/rid updates and any candidate updates
(text, completion indicator, attached media)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .research import DeepResearchPlanData, extract_deep_research_plan

_ARTIFACT_RE = re.compile(r"http://googleusercontent\.com/\w+/\d+\n*")
_CARD_CONTENT_RE = re.compile(r"^http://googleusercontent\.com/card_content/\d+")


@dataclass
class CandidateUpdate:
    rcid: str
    text: str = ""
    thoughts: str = ""
    is_complete: bool = False
    web_images: list[dict[str, str]] = field(default_factory=list)
    generated_images: list[dict[str, str]] = field(default_factory=list)
    generated_videos: list[dict[str, str]] = field(default_factory=list)
    generated_media: list[dict[str, str]] = field(default_factory=list)
    deep_research_plan: DeepResearchPlanData | None = None


@dataclass
class Event:
    chat_id: str = ""
    reply_id: str = ""
    candidates: list[CandidateUpdate] = field(default_factory=list)
    fatal_code: int = 0  # non-zero = known Gemini error code


def parse_event(env: Any) -> Event | None:
    """Decode one envelope (a list like `["wrb.fr", null, "<inner-json>"]`)
    into a typed Event. Returns None if the envelope isn't a chat-data one
    we recognise."""

    if not isinstance(env, list) or len(env) < 3:
        return None

    inner_str = env[2]
    if not isinstance(inner_str, str) or not inner_str:
        # Non-data envelopes (di, af.httprm, ...) - still inspect for fatal codes.
        ev = Event()
        code = _extract_fatal(env)
        if code:
            ev.fatal_code = code
            return ev
        return None

    try:
        inner = json.loads(inner_str)
    except json.JSONDecodeError:
        return None

    ev = Event()

    md = _nested(inner, [1])
    if isinstance(md, list) and md:
        if len(md) > 0 and isinstance(md[0], str):
            ev.chat_id = md[0]
        if len(md) > 1 and isinstance(md[1], str):
            ev.reply_id = md[1]

    cands = _nested(inner, [4])
    if isinstance(cands, list):
        for c in cands:
            cu = parse_candidate(c)
            if cu is not None:
                ev.candidates.append(cu)

    code = _extract_fatal(env)
    if code:
        ev.fatal_code = code
    return ev


def parse_candidate(node: Any) -> CandidateUpdate | None:
    """Parse one element of inner[4] (one candidate)."""
    if not isinstance(node, list):
        return None
    rcid = _nested(node, [0])
    if not isinstance(rcid, str) or not rcid:
        return None

    cu = CandidateUpdate(rcid=rcid)

    text = _nested(node, [1, 0])
    if isinstance(text, str) and text:
        if _CARD_CONTENT_RE.match(text):
            alt = _nested(node, [22, 0])
            if isinstance(alt, str) and alt:
                text = alt
        cu.text = _ARTIFACT_RE.sub("", text)

    thoughts = _nested(node, [37, 0, 0])
    if isinstance(thoughts, str):
        cu.thoughts = thoughts

    indicator = _nested(node, [8, 0])
    if isinstance(indicator, (int, float)) and int(indicator) == 2:
        cu.is_complete = True

    web_list = _nested(node, [12, 1])
    if isinstance(web_list, list):
        for w in web_list:
            url = _nested(w, [0, 0, 0])
            if isinstance(url, str) and url:
                alt = _nested(w, [0, 4])
                cu.web_images.append({"url": url, "alt": alt if isinstance(alt, str) else ""})

    gen_list = _nested(node, [12, 7, 0])
    if isinstance(gen_list, list):
        for g in gen_list:
            url = _nested(g, [0, 3, 3])
            if isinstance(url, str) and url:
                alt = _nested(g, [0, 3, 2])
                img_id = _nested(g, [1, 0])
                cu.generated_images.append(
                    {
                        "url": url,
                        "alt": alt if isinstance(alt, str) else "",
                        "image_id": img_id if isinstance(img_id, str) else "",
                    }
                )

    vinfo = _nested(node, [12, 59, 0, 0, 0])
    if isinstance(vinfo, list) and vinfo:
        urls = _nested(vinfo[0], [7])
        if isinstance(urls, list) and len(urls) >= 2:
            thumb = urls[0] if isinstance(urls[0], str) else ""
            vurl = urls[1] if isinstance(urls[1], str) else ""
            cu.generated_videos.append({"url": vurl, "thumbnail": thumb})

    mdata = _nested(node, [12, 86])
    if isinstance(mdata, list) and mdata:
        gm: dict[str, str] = {}
        if len(mdata) > 0:
            mp3 = _nested(mdata[0], [1, 7])
            if isinstance(mp3, list) and len(mp3) >= 2:
                gm["mp3_thumbnail"] = mp3[0] if isinstance(mp3[0], str) else ""
                gm["mp3_url"] = mp3[1] if isinstance(mp3[1], str) else ""
        if len(mdata) > 1:
            mp4 = _nested(mdata[1], [1, 7])
            if isinstance(mp4, list) and len(mp4) >= 2:
                gm["thumbnail"] = mp4[0] if isinstance(mp4[0], str) else ""
                gm["url"] = mp4[1] if isinstance(mp4[1], str) else ""
        if gm.get("url") or gm.get("mp3_url"):
            cu.generated_media.append(gm)

    plan = extract_deep_research_plan(node)
    if plan is not None:
        cu.deep_research_plan = plan

    return cu


def _extract_fatal(env: list) -> int:
    v = _nested(env, [5, 2, 0, 1, 0])
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _nested(node: Any, path: list) -> Any:
    """Safely walk a nested list-or-dict tree by index/key. Returns None on
    any miss."""
    cur = node
    for key in path:
        if isinstance(key, int):
            if not isinstance(cur, list) or not (-len(cur) <= key < len(cur)):
                return None
            cur = cur[key]
        else:
            if not isinstance(cur, dict) or key not in cur:
                return None
            cur = cur[key]
    return cur
