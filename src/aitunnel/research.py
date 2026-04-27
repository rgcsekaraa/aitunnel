"""Deep research: plan -> start -> poll -> wait. Long-running, runs the
whole pipeline as one async call."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass

from . import _protocol as proto
from .client import Client
from .errors import APIError, AuthError, NotStartedError
from .types import (
    DeepResearchPlan,
    DeepResearchResult,
    DeepResearchStatus,
    ModelOutput,
)


@dataclass
class DeepResearchOpts:
    poll_interval: float = 10.0
    timeout: float = 600.0
    on_status: Callable[[DeepResearchStatus], None] | None = None


async def create_plan(client: Client, prompt: str) -> DeepResearchPlan:
    """Submit a deep-research-mode generate request, extract the plan from
    the response."""
    if not client.ready:
        raise NotStartedError("Client not started")
    await _preflight(client)

    stream = await client._open_stream(  # noqa: SLF001
        prompt,
        model=client.default_model,
        files=None,
        gem_id="",
        temporary=False,
        deep_research=True,
    )

    response_text = ""
    plan_cid = ""
    plan_rid = ""
    plan_rcid = ""
    try:
        async for delta in stream:
            if delta.done:
                response_text = delta.text
                if delta.output is not None and delta.output.metadata:
                    md = delta.output.metadata
                    if len(md) > 0:
                        plan_cid = md[0]
                    if len(md) > 1:
                        plan_rid = md[1]
                    if len(md) > 2:
                        plan_rcid = md[2]
                break
        plan_data = stream.research_plan
    finally:
        await stream.aclose()

    if plan_data is None:
        raise APIError(200, f"Gemini did not return a deep research plan (got {response_text[:300]!r})")

    plan = DeepResearchPlan(
        research_id=plan_data.research_id,
        title=plan_data.title,
        query=plan_data.query,
        steps=list(plan_data.steps),
        eta_text=plan_data.eta_text,
        confirm_prompt=plan_data.confirm_prompt or "Start research",
        confirmation_url=plan_data.confirmation_url,
        modify_prompt=plan_data.modify_prompt,
        raw_state=plan_data.raw_state,
        response_text=response_text,
        cid=plan_cid,
        rid=plan_rid,
        rcid=plan_rcid,
        metadata=[plan_cid, plan_rid, plan_rcid],
    )
    return plan


async def start(
    client: Client,
    plan: DeepResearchPlan,
    *,
    confirm_prompt: str = "",
) -> ModelOutput:
    """Confirm the plan and kick off the research run."""
    if not client.ready:
        raise NotStartedError("Client not started")
    await _preflight(client)
    chat = client.start_chat()
    chat.resume(plan.cid, plan.rid, plan.rcid)
    prompt = confirm_prompt or plan.confirm_prompt or "Start research"
    return await chat.send(prompt)


async def status(client: Client, research_id: str) -> DeepResearchStatus | None:
    """Poll the research-status RPC for one snapshot."""
    if not client.ready:
        raise NotStartedError("Client not started")
    if not research_id:
        raise ValueError("research_id required")
    sess = client.session_info
    payload = json.dumps([research_id], separators=(",", ":"))
    parts, st = await client.transport.batch_execute(
        sess, [proto.BatchCall(rpc=proto.RPC_DEEP_RESEARCH_STATUS, payload=payload)]
    )
    if st == 401:
        raise AuthError("session expired")
    if st != 200:
        raise APIError(st, "deep research status failed")
    for part in parts:
        try:
            body = json.loads(part.body)
        except json.JSONDecodeError:
            continue
        ext = proto.extract_deep_research_status(body)
        if ext is None:
            continue
        return DeepResearchStatus(
            research_id=ext.research_id,
            state=ext.state,
            done=ext.done,
            title=ext.title,
            query=ext.query,
            cid=ext.cid,
            notes=list(ext.notes),
            raw_state=ext.raw_state,
            timestamp=time.time(),
        )
    return None


async def wait(
    client: Client,
    plan: DeepResearchPlan,
    opts: DeepResearchOpts | None = None,
) -> DeepResearchResult:
    """Poll until the run flags done, the timeout elapses, or the task is
    cancelled."""
    opts = opts or DeepResearchOpts()
    if not plan.research_id:
        raise APIError(400, "plan has no research_id (was the run started?)")
    deadline = time.monotonic() + opts.timeout
    result = DeepResearchResult(plan=plan)
    while time.monotonic() < deadline:  # noqa: ASYNC109 - explicit deadline is clearer than asyncio.timeout for this poll-loop
        st = await status(client, plan.research_id)
        if st is not None:
            result.statuses.append(st)
            if opts.on_status is not None:
                try:
                    opts.on_status(st)
                except Exception:
                    pass
            if st.done:
                result.done = True
                break
        await asyncio.sleep(opts.poll_interval)
    if plan.cid:
        from .history import latest_model_output
        try:
            final = await latest_model_output(client, plan.cid)
            if final is not None:
                result.final_output = final
        except Exception:
            pass
    return result


async def deep_research(
    client: Client,
    prompt: str,
    *,
    poll_interval: float = 10.0,
    timeout: float = 600.0,
    on_status: Callable[[DeepResearchStatus], None] | None = None,
) -> DeepResearchResult:
    """One-shot: plan -> start -> wait. Returns the aggregated result."""
    plan = await create_plan(client, prompt)
    start_out = await start(client, plan)
    res = await wait(
        client, plan, DeepResearchOpts(poll_interval=poll_interval, timeout=timeout, on_status=on_status)
    )
    res.start_output = start_out
    if res.plan is None:
        res.plan = plan
    return res


async def _preflight(client: Client) -> None:
    """Best-effort warmup RPCs the web client sends before deep research.
    Failures are logged, not raised - the actual generate often still works.
    Both calls run in parallel."""
    sess = client.session_info
    calls = [
        proto.BatchCall(rpc=proto.RPC_BARD_SETTINGS, payload='[[["bard_activity_enabled"]]]'),
        proto.BatchCall(
            rpc=proto.RPC_DEEP_RESEARCH_BOOTSTRAP,
            payload='["en",null,null,null,4,null,null,[2,4,7,15],null,[[5]]]',
        ),
    ]

    async def _one(c: proto.BatchCall) -> None:
        try:
            await client.transport.batch_execute(sess, [c])
        except Exception:
            pass

    await asyncio.gather(*[_one(c) for c in calls])


# Patch.
Client.create_research_plan = lambda self, prompt: create_plan(self, prompt)  # type: ignore[attr-defined]
Client.start_research = lambda self, plan, *, confirm_prompt="": start(self, plan, confirm_prompt=confirm_prompt)  # type: ignore[attr-defined]
Client.research_status = lambda self, research_id: status(self, research_id)  # type: ignore[attr-defined]
Client.wait_for_research = lambda self, plan, opts=None: wait(self, plan, opts)  # type: ignore[attr-defined]
Client.deep_research = lambda self, prompt, *, poll_interval=10.0, timeout=600.0, on_status=None: deep_research(  # type: ignore[attr-defined]
    self, prompt, poll_interval=poll_interval, timeout=timeout, on_status=on_status
)
