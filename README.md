# aitunnel

[![tests](https://github.com/rgcsekaraa/aitunnel/actions/workflows/test.yml/badge.svg)](https://github.com/rgcsekaraa/aitunnel/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/aitunnel.svg)](https://pypi.org/project/aitunnel/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A small Python server that gives you Gemini on `localhost`, using the cookies
from your gemini.google.com session. Made for devs who don't have access to
the official Gemini API but still want to wire its quality into their tools.

You run `aitunnel-server`, paste two cookies once, and your scripts/agents/IDE
extensions can hit `http://localhost:8000/query` like any other LLM endpoint.

```sh
curl -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "explain monads in one paragraph"}'
```

## Why this exists

Google's official Gemini API is rate-limited (and not available everywhere).
The web app at gemini.google.com isn't. aitunnel reverse-engineers the same
protocol Gemini's web UI talks to internally - same models, same quality, no
API key needed.

It's not a SaaS, not a wrapper around the official API. It runs locally on
your machine, against your own Google account.

## What you get

- **HTTP API** at `localhost:8000` - JSON in, JSON out. Streaming via SSE.
- **A web dashboard** for sending queries by hand, browsing your saved chats,
  managing custom Gems, watching activity in real time.
- **File attachments** - drag-drop images or any file into the dashboard, or
  POST them to `/upload` and reference the URL in subsequent queries.
- **Multi-turn chats** via `cid` continuation in the API; deep research; gem CRUD.
- **Activity log** showing every request with status, attempt count, duration,
  and request/response previews.
- **Auto-rotating session** - the short-lived auth token is refreshed in the
  background so you set this up once and forget about it for months.

## Install

```sh
pip install aitunnel
aitunnel-server
```

Or from source:

```sh
git clone https://github.com/rgcsekaraa/aitunnel
cd aitunnel
python -m venv .venv && source .venv/bin/activate
pip install -e .
aitunnel-server
```

Python 3.11 or newer is required.

## First run

The first time you start it without cookies, it pops a setup form at
`http://localhost:8000`. Paste two values from Chrome's DevTools:

1. Open `https://gemini.google.com` in your browser, signed in.
2. F12 → Application → Cookies → `https://gemini.google.com`
3. Copy the values of `__Secure-1PSID` and `__Secure-1PSIDTS`.
4. Paste them into the form, click Save.

That's it. The server bootstraps the session, captures your account info,
starts a background coroutine to refresh the short-lived cookie every nine
minutes, and lands you on the dashboard.

After that, you only re-paste when `__Secure-1PSID` itself expires - that's
months, not hours. The server stores cookies in `.env` next to where you ran it.

## How it works

A short tour, in case you ever need to debug it:

- **Transport**: `curl_cffi` with Chrome uTLS impersonation. Without this,
  Google rejects requests based on TLS fingerprint, even with valid cookies.
- **Auth**: GETs `gemini.google.com/app` with your cookies, regexes the
  `SNlM0e` access token out of the bootstrap HTML. That token is needed in
  every subsequent generate request.
- **Generate**: POSTs to `BardFrontendService/StreamGenerate` with a
  form-encoded body containing the access token and a JSON-in-JSON payload
  that mimics what the web app sends. Response is a length-prefixed stream
  of JSON envelopes with the answer text inside.
- **Cookie rotation**: a background `asyncio.Task` POSTs to
  `accounts.google.com/RotateCookies` every nine minutes to keep
  `__Secure-1PSIDTS` fresh.
- **Dashboard**: a single embedded HTML file using vanilla JS + Tailwind CDN.
  Activity log uses Server-Sent Events for live updates.

The wire format is reverse-engineered, so it can break when Google changes
something. When that happens you'll see "SNlM0e token not found in bootstrap"
or similar - check `src/aitunnel/_protocol/` for the relevant offsets.

## Limits to know about

- Single Google account per process. If you want more, run a second instance
  on a different port with a different `.env`.
- Account-level rate limits still apply. "No API quota" doesn't mean "no
  quota at all" - if you hammer it Google will start throttling that account.
- It's a moving target. Pin a version that works for you; the wire format
  changes every few months.
- Stick to one model per chat session. Switching mid-conversation can return
  a `model_inconsistent` error.

## Configuration

`.env` (alongside the `aitunnel-server` invocation):

```sh
SECURE_1PSID=g.a000...        # your long-lived auth cookie
SECURE_1PSIDTS=sidts-...      # the short-lived one (auto-rotated)

HOST=127.0.0.1                # bind address
PORT=8000

LOG_LEVEL=info                # debug | info | warning | error
HTTPS_PROXY=                  # optional outbound proxy
```

## API

See [API.md](API.md) for the full endpoint reference. Quick highlights:

```sh
# basic query
curl -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "hello"}'

# streaming
curl -N -X POST localhost:8000/query/stream \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "tell me a story"}'

# upload a file, then ask about it
URL=$(curl -s -X POST localhost:8000/upload -F "file=@./photo.jpg" | jq -r .url)
curl -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d "{\"prompt\":\"describe this\",\"files\":[{\"url\":\"$URL\",\"filename\":\"photo.jpg\"}]}"
```

## Library use (Python)

aitunnel is also an importable Python package, so you can skip the HTTP layer
when calling from Python code:

```python
import asyncio
from aitunnel import Client

async def main():
    async with Client(psid, psidts) as c:
        # one-shot, never persisted to your history
        out = await c.query("hello")
        print(out.text)

        # streaming
        stream = await c.query_stream("write a poem")
        async for delta in stream:
            print(delta.text_delta, end="", flush=True)
            if delta.done:
                break
        await stream.aclose()

        # multi-turn
        chat = c.start_chat()
        await chat.send("my name is Sam")
        out = await chat.send("what's my name?")
        print(out.text)

asyncio.run(main())
```

Errors derive from `AitunnelError` - catch specific subclasses for retry/handling decisions:

```python
from aitunnel import AuthError, UsageLimitError, TransientError, IPBlockedError

try:
    out = await c.query(prompt)
except AuthError:        # cookies expired - re-auth
    ...
except UsageLimitError:  # back off or switch model
    ...
except TransientError:   # already retried by policy
    ...
except IPBlockedError:   # rotate IP / use proxy
    ...
```

## Layout

```
.
├── src/aitunnel/
│   ├── client.py, chat.py, stream.py     public surface
│   ├── types.py, models.py, errors.py    typed contracts
│   ├── retry.py                          retry policy
│   ├── chats.py, gems.py, ...            per-feature public APIs
│   ├── _protocol/                        wire format (auth, request, frames, response)
│   ├── _transport/                       curl_cffi async client + cookie rotation
│   └── server/                           FastAPI app + dashboard HTML
└── tests/                                pytest suite
```

Four layers, one job each. The `_`-prefixed packages are the internal API and
not exported from the top-level module.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bugs - especially when the wire format
breaks - are the main thing. Open an issue with `LOG_LEVEL=debug` server output.

## Acknowledgements

The Python project [HanaokaYuzu/Gemini-API](https://github.com/HanaokaYuzu/Gemini-API)
got there first and remains the canonical reference for the wire format.
aitunnel is a structural rework with a tighter architecture (separated
protocol/transport/client layers, single-responsibility files), built-in
FastAPI server and dashboard, activity log, multi-turn HTTP API, and a richer
typed-error hierarchy.

## License

MIT.
