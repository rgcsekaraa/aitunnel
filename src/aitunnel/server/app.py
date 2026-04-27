"""FastAPI app. All endpoints. Bootstrap loop drops back to setup mode if
cookies are invalid; the dashboard's setup form POSTs new cookies which
reload the .env file and retry the bootstrap."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from .. import chats as _chats_mod  # noqa: F401
from .. import download as _download_mod  # noqa: F401
from .. import fullsize as _fullsize_mod  # noqa: F401
from .. import gems as _gems_mod  # noqa: F401
from .. import history as _history_mod  # noqa: F401
from .. import research as _research_mod  # noqa: F401

# Bring side-effect patches onto Client.
from .. import upload as _upload_mod  # noqa: F401
from ..client import Client
from ..errors import (
    AitunnelError,
    APIError,
    AuthError,
    EmptyResponseError,
    IPBlockedError,
    ModelInvalidError,
    NotStartedError,
    TransientError,
    UsageLimitError,
)
from ..retry import RetryPolicy
from ..types import Delta, FileAttachment, ModelOutput
from .jobs import JobStore
from .middleware import JobTrackingMiddleware

log = logging.getLogger("aitunnel.server")

_HERE = Path(__file__).parent


def _read_asset(name: str) -> bytes:
    return (_HERE / name).read_bytes()


def _env_path() -> str:
    return os.getenv("AITUNNEL_ENV_PATH", ".env")


# ---- request/response models ----

class QueryIn(BaseModel):
    prompt: str
    files: list[FileAttachment] = Field(default_factory=list)
    gem_id: str = ""
    cid: str = ""   # optional - continue an existing chat
    rid: str = ""
    rcid: str = ""


class QueryOut(BaseModel):
    response: str
    metadata: dict[str, str] = Field(default_factory=dict)


class GemIn(BaseModel):
    name: str
    prompt: str
    description: str = ""


class SetupIn(BaseModel):
    psid: str
    psidts: str = ""


class DeepResearchIn(BaseModel):
    prompt: str
    poll_interval_sec: int = 10
    timeout_sec: int = 600


# ---- error mapping ----

_ERROR_MAP: dict[type, tuple[int, str]] = {
    AuthError: (401, "session expired - cookies invalid; reload to re-authenticate"),
    UsageLimitError: (429, "Gemini usage limit reached for this account"),
    IPBlockedError: (403, "IP temporarily flagged by Google"),
    ModelInvalidError: (400, "model selection invalid for this conversation"),
    TransientError: (502, "transient Gemini error - retry should succeed"),
    EmptyResponseError: (502, "Gemini returned an empty response (often a safety block)"),
    NotStartedError: (503, "client not ready"),
}


def _http_error(e: Exception) -> HTTPException:
    if isinstance(e, AitunnelError):
        for typ, (code, msg) in _ERROR_MAP.items():
            if isinstance(e, typ):
                return HTTPException(status_code=code, detail=msg)
        if isinstance(e, APIError):
            return HTTPException(status_code=e.status_code if 400 <= e.status_code < 600 else 502, detail=str(e))
    return HTTPException(status_code=502, detail=str(e))


# ---- bootstrap (run once at startup, falls back to setup mode on failure) ----

async def _bootstrap_with_retry(
    psid: str, psidts: str, retry: RetryPolicy
) -> Client:
    """Try to start a Client. Bubbles up the first error if it can't bootstrap."""
    c = Client(
        psid,
        psidts,
        proxy=os.getenv("HTTPS_PROXY") or None,
        retry=retry,
    )
    try:
        await c.start()
    except Exception:
        await c.close()
        raise
    return c


# ---- app builder ----

def build_app() -> FastAPI:
    state: dict[str, Any] = {
        "client": None,
        "ready": False,
        "setup_flash": "",
        "jobs": JobStore(),
    }
    jobs: JobStore = state["jobs"]

    # Retry policy that surfaces attempts to the activity log.
    def _on_attempt(attempt: int, err: Exception) -> None:
        # We don't have request-context here, so just log.
        log.info("retry attempt %d: %s", attempt, err)
    retry = RetryPolicy(on_attempt=_on_attempt)

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        load_dotenv(_env_path(), override=True)
        await _try_start(state, retry)
        try:
            yield
        finally:
            c: Client | None = state.get("client")
            if c is not None:
                await c.close()

    app = FastAPI(
        title="aitunnel",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        lifespan=_lifespan,
    )
    app.add_middleware(JobTrackingMiddleware, store=jobs)

    # ---- static + dashboard ----

    @app.get("/")
    async def root() -> HTMLResponse:
        if state["ready"]:
            return HTMLResponse(_read_asset("dashboard.html"))
        return HTMLResponse(_read_asset("setup.html"))

    @app.get("/dashboard")
    async def dashboard() -> HTMLResponse:
        if not state["ready"]:
            return HTMLResponse(_read_asset("setup.html"))
        return HTMLResponse(_read_asset("dashboard.html"))

    @app.get("/favicon.svg")
    async def favicon_svg() -> Response:
        return Response(_read_asset("favicon.svg"), media_type="image/svg+xml")

    @app.get("/favicon.ico")
    async def favicon_ico() -> Response:
        return Response(_read_asset("favicon.svg"), media_type="image/svg+xml")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        if state["ready"]:
            return {"ok": True}
        return {"ok": False, "setup": True}

    # ---- setup endpoints (used by setup.html) ----

    @app.get("/setup/flash")
    async def setup_flash() -> dict[str, str]:
        return {"flash": state["setup_flash"]}

    @app.post("/setup")
    async def do_setup(body: SetupIn) -> dict[str, str]:
        if not body.psid:
            raise HTTPException(400, "psid required")
        path = _env_path()
        # Touch the .env file if it doesn't exist.
        Path(path).touch(exist_ok=True)
        set_key(path, "SECURE_1PSID", body.psid)
        set_key(path, "SECURE_1PSIDTS", body.psidts or "")
        load_dotenv(path, override=True)
        state["setup_flash"] = ""
        # Try to start the client.
        old = state.get("client")
        if old is not None:
            await old.close()
            state["client"] = None
            state["ready"] = False
        try:
            client = await _bootstrap_with_retry(body.psid, body.psidts, retry)
            state["client"] = client
            state["ready"] = True
            return {"status": "saved"}
        except Exception as e:
            state["setup_flash"] = (
                "Google rejected the session. Your __Secure-1PSID is likely "
                "expired - log out of gemini.google.com, log back in, then "
                "copy fresh cookies."
            )
            log.warning("bootstrap after /setup failed: %s", e)
            raise HTTPException(401, str(e)) from e

    # ---- query ----

    def _client() -> Client:
        c = state.get("client")
        if c is None or not state["ready"]:
            raise HTTPException(503, "client not ready - finish setup at /")
        return c

    @app.post("/query")
    async def query(body: QueryIn) -> QueryOut:
        if not body.prompt or not body.prompt.strip():
            raise HTTPException(400, "prompt required")
        client = _client()
        try:
            if body.cid:
                chat = client.start_chat(gem_id=body.gem_id)
                chat.resume(body.cid, body.rid, body.rcid)
                out = await chat.send(body.prompt, files=body.files or None)
            else:
                out = await client.query(body.prompt, files=body.files or None, gem_id=body.gem_id)
        except Exception as e:
            raise _http_error(e) from e
        meta = {}
        if out.metadata:
            if len(out.metadata) > 0:
                meta["cid"] = out.metadata[0]
            if len(out.metadata) > 1:
                meta["rid"] = out.metadata[1]
            if len(out.metadata) > 2:
                meta["rcid"] = out.metadata[2]
        return QueryOut(response=out.text, metadata=meta)

    @app.post("/query/stream")
    async def query_stream(body: QueryIn) -> StreamingResponse:
        if not body.prompt or not body.prompt.strip():
            raise HTTPException(400, "prompt required")
        client = _client()
        try:
            if body.cid:
                chat = client.start_chat(gem_id=body.gem_id)
                chat.resume(body.cid, body.rid, body.rcid)
                stream = await chat.send_stream(body.prompt, files=body.files or None)
            else:
                stream = await client.query_stream(body.prompt, files=body.files or None, gem_id=body.gem_id)
        except Exception as e:
            raise _http_error(e) from e

        async def _emit():
            try:
                async for delta in stream:
                    if delta.text_delta:
                        yield _sse("delta", {"text": delta.text_delta})
                    if delta.done:
                        yield _sse("done", {"text": delta.text})
                        return
            except AitunnelError as e:
                yield _sse("error", {"error": str(e)})
            except Exception as e:
                yield _sse("error", {"error": f"stream error: {e}"})
            finally:
                await stream.aclose()

        return StreamingResponse(
            _emit(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ---- upload ----

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> FileAttachment:  # noqa: B008 — FastAPI idiom
        client = _client()
        data = await file.read()
        try:
            return await client.upload_file(  # type: ignore[attr-defined]
                file.filename or "upload.bin",
                data,
                content_type=file.content_type or "",
            )
        except Exception as e:
            raise _http_error(e) from e

    # ---- chats ----

    @app.get("/chats")
    async def list_chats(recent: int = Query(default=13, ge=1, le=100)):
        client = _client()
        try:
            chats = await client.list_chats(recent=recent)  # type: ignore[attr-defined]
            return [c.model_dump() for c in chats]
        except Exception as e:
            raise _http_error(e) from e

    @app.delete("/chats/{cid}")
    async def delete_chat(cid: str) -> Response:
        client = _client()
        try:
            await client.delete_chat(cid)  # type: ignore[attr-defined]
        except Exception as e:
            raise _http_error(e) from e
        return Response(status_code=204)

    @app.get("/chats/{cid}/history")
    async def chat_history(cid: str, limit: int = Query(default=10, ge=1, le=100)):
        client = _client()
        try:
            h = await client.read_chat(cid, limit=limit)  # type: ignore[attr-defined]
        except Exception as e:
            raise _http_error(e) from e
        if h is None:
            raise HTTPException(202, "still generating")
        return h.model_dump()

    # ---- gems ----

    @app.get("/gems")
    async def list_gems(hidden: bool = Query(default=False)):
        client = _client()
        try:
            gems = await client.list_gems(include_hidden=hidden)  # type: ignore[attr-defined]
            return [g.model_dump() for g in gems]
        except Exception as e:
            raise _http_error(e) from e

    @app.post("/gems")
    async def create_gem(body: GemIn):
        client = _client()
        try:
            gem = await client.create_gem(body.name, body.prompt, body.description)  # type: ignore[attr-defined]
            return gem.model_dump()
        except Exception as e:
            raise _http_error(e) from e

    @app.put("/gems/{gem_id}")
    async def update_gem(gem_id: str, body: GemIn):
        client = _client()
        try:
            gem = await client.update_gem(gem_id, body.name, body.prompt, body.description)  # type: ignore[attr-defined]
            return gem.model_dump()
        except Exception as e:
            raise _http_error(e) from e

    @app.delete("/gems/{gem_id}")
    async def delete_gem(gem_id: str) -> Response:
        client = _client()
        try:
            await client.delete_gem(gem_id)  # type: ignore[attr-defined]
        except Exception as e:
            raise _http_error(e) from e
        return Response(status_code=204)

    # ---- deep research ----

    @app.post("/deep-research")
    async def deep_research_endpoint(body: DeepResearchIn):
        if not body.prompt or not body.prompt.strip():
            raise HTTPException(400, "prompt required")
        client = _client()
        try:
            res = await client.deep_research(  # type: ignore[attr-defined]
                body.prompt,
                poll_interval=max(1, body.poll_interval_sec),
                timeout=max(10, body.timeout_sec),
            )
        except Exception as e:
            raise _http_error(e) from e
        return {
            "plan": res.plan.model_dump() if res.plan else None,
            "statuses": [s.model_dump() for s in res.statuses],
            "done": res.done,
            "final_text": res.final_output.text if res.final_output else "",
            "properties": {"had_final_output": res.final_output is not None},
        }

    # ---- jobs (activity log) ----

    @app.get("/jobs")
    async def jobs_list() -> list[dict[str, Any]]:
        snap = await jobs.snapshot(100)
        return [j.to_dict() for j in snap]

    @app.get("/jobs/stream")
    async def jobs_stream(request: Request) -> StreamingResponse:
        async def _emit():
            # Replay current snapshot first.
            for j in await jobs.snapshot(50):
                yield _sse("job", j.to_dict())
            q, sub = await jobs.subscribe()
            try:
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        j = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield _sse("job", j.to_dict())
                    except TimeoutError:
                        # heartbeat to keep the connection alive
                        yield ": ping\n\n"
            finally:
                await sub.__aexit__(None, None, None)

        return StreamingResponse(
            _emit(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    return app


# ---- helpers ----

async def _try_start(state: dict[str, Any], retry: RetryPolicy) -> None:
    psid = os.getenv("SECURE_1PSID", "")
    psidts = os.getenv("SECURE_1PSIDTS", "")
    if not psid:
        log.info("no SECURE_1PSID in env - serving setup form at /")
        state["setup_flash"] = ""
        return
    try:
        client = await _bootstrap_with_retry(psid, psidts, retry)
        state["client"] = client
        state["ready"] = True
        log.info("bootstrapped successfully")
    except Exception as e:
        log.warning("startup bootstrap failed: %s", e)
        state["setup_flash"] = (
            "Google rejected the session on startup. Re-paste fresh "
            "__Secure-1PSID and __Secure-1PSIDTS from gemini.google.com."
        )


def _sse(event: str, data: dict[str, Any] | Any) -> str:
    payload = json.dumps(data) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


# Suppress unused import warnings for FastAPI imports we keep for future use.
_ = (Form, ModelOutput, Delta)
