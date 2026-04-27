# aitunnel API reference

Everything is JSON, returned with `application/json` (except SSE streams,
which are `text/event-stream`). The base URL is `http://localhost:8000` by
default - override with `HOST` and `PORT` in `.env`.

When something goes wrong, the response body is JSON with a `detail` field
(FastAPI default) and the status code is meaningful:

| status | meaning |
|--------|---------|
| 400    | malformed input |
| 401    | session expired - re-auth via the setup page |
| 403    | your IP got flagged by Google - try a proxy or wait |
| 404    | unknown route |
| 413    | request body too large |
| 429    | usage limit reached on this Google account |
| 500    | server bug. these are caught and logged |
| 502    | Gemini upstream returned something we couldn't parse - usually transient |
| 503    | client not ready (still in setup) |

Frontends should retry 502/503 automatically.

---

## Generation

### POST `/query`

Returns the full answer in one JSON response. By default the chat is
*temporary* - it never appears in your Gemini history. If you pass a `cid`
from a previous response, the request continues that conversation instead
(and gets persisted in your Gemini history).

**Body:**

```json
{
  "prompt": "string (required)",
  "files":  [{"url": "...", "filename": "..."}],
  "gem_id": "optional gem ID",
  "cid":    "optional - continue an existing chat",
  "rid":    "optional - paired with cid for exact turn resolution",
  "rcid":   "optional - same"
}
```

**Response:**

```json
{
  "response": "the model's answer",
  "metadata": {
    "cid":  "c_a4b5...",
    "rid":  "r_a4b5...",
    "rcid": "rc_a4b5..."
  }
}
```

To continue a conversation, send `cid`/`rid`/`rcid` back in the next call:

```python
import requests

base = "http://localhost:8000"
session = {}

def chat(prompt: str) -> str:
    r = requests.post(f"{base}/query", json={"prompt": prompt, **session}).json()
    session.update(r["metadata"])
    return r["response"]

print(chat("my name is Pat"))
print(chat("what's my name?"))   # → "You said your name is Pat."
```

Continued chats appear in `/chats` and your Gemini history. Omit `cid` for
temporary one-shots.

---

### POST `/query/stream`

Same body as `/query` (including the optional `cid`/`rid`/`rcid` for
multi-turn), but returns a Server-Sent Events stream:

```
event: delta
data: {"text": "Hello"}

event: delta
data: {"text": "! How can I "}

event: done
data: {"text": "Hello! How can I help you?"}
```

The `done` event repeats the cumulative text so a slow consumer can recover
the full answer even if it dropped some deltas.

If the model errors mid-stream you get an `error` event and the connection
closes:

```
event: error
data: {"error": "usage limit exceeded"}
```

---

### POST `/upload`

Pushes a file to Google's content store and returns a reference you can
attach to subsequent queries.

**Request:** multipart form, single field `file`.

```sh
curl -X POST localhost:8000/upload -F "file=@./photo.jpg"
```

**Response:**

```json
{ "url": "/contrib_service/ttl_1d/abc...", "filename": "photo.jpg" }
```

The url is opaque - paste it as-is into `files[]` of your next query. Files
expire on Google's side after about a day.

Per-file size is limited by Gemini (around 20MB).

---

## Chats (persisted history)

### GET `/chats?recent=N`

```json
[
  {
    "cid":       "c_a4b5...",
    "title":     "Brainstorming a name",
    "is_pinned": false,
    "timestamp": 1712772720.0
  }
]
```

Default `recent=13`. The server runs the pinned and unpinned BatchExecute
calls in parallel under the hood.

### GET `/chats/{cid}/history?limit=N`

Returns turn-by-turn text for a chat, newest first.

```json
{
  "cid": "c_a4b5...",
  "turns": [
    {"role": "model", "text": "Sure, here are some ideas..."},
    {"role": "user",  "text": "Help me name a side project"}
  ]
}
```

If the model is mid-stream when you call this, you get `202 Accepted`.

### DELETE `/chats/{cid}`

Idempotent. Returns `204 No Content`.

---

## Gems (custom system prompts)

### GET `/gems?hidden=true`

```json
[
  {
    "id":          "g_user_xyz",
    "name":        "Pirate",
    "description": "Speaks like a pirate",
    "prompt":      "Reply only in pirate dialect.",
    "predefined":  false
  }
]
```

`hidden=true` includes Google's hidden/experimental gems too - they're often
broken; default is `false`.

### POST `/gems`

```json
{ "name": "Pirate", "prompt": "Reply only in pirate dialect.", "description": "" }
```

### PUT `/gems/{id}`

Same body as POST, replaces the gem.

### DELETE `/gems/{id}`

Returns `204 No Content`. Predefined gems can't be deleted.

### Using a gem in a query

Pass the gem's id in `gem_id`:

```json
{ "prompt": "hello", "gem_id": "g_user_xyz" }
```

---

## Deep research

### POST `/deep-research`

Synchronous. Runs the full plan → start → poll pipeline. Takes 5-15 minutes.

```json
{
  "prompt": "what's happened in solid-state batteries this year",
  "poll_interval_sec": 10,
  "timeout_sec": 600
}
```

Returns:

```json
{
  "plan": {
    "research_id":   "...",
    "title":         "Solid-state battery progress 2025-26",
    "query":         "...",
    "steps":         ["Phase 1: ...", "..."],
    "eta_text":      "About 7 minutes",
    "confirm_prompt":"Start research"
  },
  "statuses": [
    {"state": "running",   "done": false},
    {"state": "completed", "done": true}
  ],
  "done": true,
  "final_text": "Solid-state batteries advanced significantly in...",
  "properties": { "had_final_output": true }
}
```

---

## Activity log

In-memory ring buffer (last 500 jobs). The dashboard's Activity tab uses these.

### GET `/jobs`

```json
[
  {
    "id":          "8a3f2c91",
    "method":      "POST",
    "path":        "/query",
    "status":      "success",
    "status_code": 200,
    "attempts":    1,
    "started_at":  1712772720.0,
    "ended_at":    1712772722.5,
    "duration_ms": 2500,
    "request":     "{\"prompt\":\"hello\"}",
    "response":    "{\"response\":\"Hi! ..."
  }
]
```

`status` is one of `running`, `retrying`, `success`, `failed`.

### GET `/jobs/stream`

SSE stream of job events. Replays the last 50 jobs, then live updates as new
ones arrive. 15s heartbeat (`: ping`) keeps idle connections alive.

---

## Health

### GET `/health`

```json
{ "ok": true }
```

`ok: false` plus `setup: true` means the server is alive but the Gemini
session isn't bootstrapped (cookies missing or expired).

---

## Setup endpoints (internal)

Used by the setup form. Not normally called directly.

### POST `/setup`

```json
{ "psid": "g.a000...", "psidts": "sidts-..." }
```

Writes the cookies to `.env` and triggers a fresh bootstrap.

### GET `/setup/flash`

```json
{ "flash": "" }
```

Holds the error from a previous failed bootstrap (used by setup.html).

---

## Authentication and security notes

aitunnel runs on `127.0.0.1:8000` by default - no auth on the API, since
anyone with access to your loopback is presumed to be you. **Don't expose
this to a network you don't trust** without putting your own auth in front.

Your cookies live in `.env`. Treat that file like an SSH key. Don't commit
it; the project's `.gitignore` already excludes it.

The server's outbound traffic to Google goes through a uTLS-fingerprinted
client. If you want it to go through a proxy (e.g., for IP rotation), set
`HTTPS_PROXY=http://...` in `.env`.
