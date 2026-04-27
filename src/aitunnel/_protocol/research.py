"""Deep-research plan + status extractors. The plan lives at a particular
key inside the candidate envelope ("56" or "57" depending on Gemini build);
the status comes back from the polling RPC and is identified by string
markers rather than fixed indices."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_RE_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_RE_CHAT_ID = re.compile(r"\bc_[A-Za-z0-9_]+\b")
_RE_HTTP_URL = re.compile(r"^https?://")


@dataclass
class DeepResearchPlanData:
    research_id: str = ""
    title: str = ""
    query: str = ""
    steps: list[str] = field(default_factory=list)
    eta_text: str = ""
    confirm_prompt: str = ""
    confirmation_url: str = ""
    modify_prompt: str = ""
    raw_state: int = 0


@dataclass
class DeepResearchStatusData:
    research_id: str = ""
    state: str = "running"  # "running" | "awaiting_confirmation" | "completed"
    done: bool = False
    title: str = ""
    query: str = ""
    cid: str = ""
    notes: list[str] = field(default_factory=list)
    raw_state: int = 0


def extract_deep_research_plan(candidate: Any) -> DeepResearchPlanData | None:
    """Find the plan dict (key '56' or '57') inside the candidate, parse out
    title/steps/etc."""
    meta: dict[str, Any] | None = None
    payload: list | None = None
    for key in ("56", "57"):
        meta = _find_first_dict_with_key(candidate, key)
        if meta is None:
            continue
        v = meta.get(key)
        if isinstance(v, list):
            payload = v
            break
        meta = None
    if meta is None or payload is None:
        return None

    plan = DeepResearchPlanData()
    plan.research_id = _find_first_match(candidate, _RE_UUID)

    if len(payload) > 0 and isinstance(payload[0], str):
        plan.title = payload[0]

    if len(payload) > 1 and isinstance(payload[1], list):
        for step in payload[1]:
            if not isinstance(step, list):
                continue
            label = step[1] if len(step) > 1 and isinstance(step[1], str) else None
            body = step[2] if len(step) > 2 and isinstance(step[2], str) else None
            if label and body:
                plan.steps.append(f"{label}: {body}")
            elif body:
                plan.steps.append(body)
            elif label:
                plan.steps.append(label)

    q = _nested(payload, [1, 0, 2])
    if isinstance(q, str):
        plan.query = q

    if len(payload) > 2 and isinstance(payload[2], str):
        plan.eta_text = payload[2]

    cp = _nested(payload, [3, 0])
    if isinstance(cp, str):
        plan.confirm_prompt = cp

    cu = _nested(payload, [4, 0])
    if isinstance(cu, str):
        plan.confirmation_url = cu

    if len(payload) > 5:
        mp = _find_first_string(payload[5])
        if mp:
            plan.modify_prompt = mp

    rs = meta.get("70")
    if isinstance(rs, int):
        plan.raw_state = rs

    if not any(
        [
            plan.title,
            plan.query,
            plan.steps,
            plan.eta_text,
            plan.confirm_prompt,
            plan.confirmation_url,
            plan.modify_prompt,
        ]
    ):
        return None
    return plan


def extract_deep_research_status(payload: Any) -> DeepResearchStatusData | None:
    """Parse a status RPC body into the typed status snapshot."""
    data = payload
    if isinstance(payload, list) and payload and isinstance(payload[0], list):
        data = payload[0]

    rid = _find_first_match(data, _RE_UUID)
    if not rid:
        return None

    st = DeepResearchStatusData(research_id=rid)
    t = _nested(data, [1, 4, 0])
    if isinstance(t, str):
        st.title = t
    q = _nested(data, [1, 4, 1])
    if isinstance(q, str):
        st.query = q
    cid = _nested(data, [1, 3, 0])
    if isinstance(cid, str):
        st.cid = cid
    else:
        st.cid = _find_first_match(data, _RE_CHAT_ID)

    meta = _find_first_dict_with_key(data, "70")
    if meta is not None:
        rs = meta.get("70")
        if isinstance(rs, int):
            st.raw_state = rs

    awaiting = False
    for s in _walk_strings(data):
        if "immersive_entry_chip" in s:
            st.done = True
        if "deep_research_confirmation_content" in s:
            awaiting = True

    if st.done:
        st.state = "completed"
    elif awaiting:
        st.state = "awaiting_confirmation"
    else:
        st.state = "running"

    exclude = {x for x in (st.title, st.query, st.research_id, st.cid) if isinstance(x, str) and x}
    st.notes = _collect_notes(data, exclude=exclude)
    return st


def _find_first_dict_with_key(node: Any, key: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if key in node:
            return node
        for v in node.values():
            r = _find_first_dict_with_key(v, key)
            if r is not None:
                return r
    elif isinstance(node, list):
        for item in node:
            r = _find_first_dict_with_key(item, key)
            if r is not None:
                return r
    return None


def _find_first_match(node: Any, rx: re.Pattern[str]) -> str:
    for s in _walk_strings(node):
        m = rx.search(s)
        if m:
            return m.group(0)
    return ""


def _find_first_string(node: Any) -> str:
    for s in _walk_strings(node):
        if s:
            return s
    return ""


def _walk_strings(node: Any):
    if isinstance(node, str):
        yield node
        return
    if isinstance(node, list):
        for c in node:
            yield from _walk_strings(c)
    elif isinstance(node, dict):
        for c in node.values():
            yield from _walk_strings(c)


def _collect_notes(node: Any, *, exclude: set[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for s in _walk_strings(node):
        t = s.strip()
        if (
            not t
            or t in exclude
            or t in seen
            or _RE_HTTP_URL.match(t)
            or len(t) < 12
        ):
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= 12:
            break
    return out


def _nested(node: Any, path: list) -> Any:
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
