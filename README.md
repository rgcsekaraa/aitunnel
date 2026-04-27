# aitunnel

[![tests](https://github.com/rgcsekaraa/aitunnel/actions/workflows/test.yml/badge.svg)](https://github.com/rgcsekaraa/aitunnel/actions/workflows/test.yml)
[![PyPI](https://img.shields.io/pypi/v/aitunnel.svg)](https://pypi.org/project/aitunnel/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Local Gemini proxy on `localhost`. You paste two cookies once, your tools
hit `http://localhost:8000/query` like any other LLM endpoint, and you get
Gemini-quality answers without an API key or quota.

```sh
pip install aitunnel
aitunnel-server
# open http://localhost:8000, paste cookies, done

curl -X POST localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "explain monads in one paragraph"}'
```

## Why this exists

Google's official Gemini API is rate-limited and not available everywhere.
The web app at gemini.google.com isn't. aitunnel reverse-engineers the same
internal protocol the web UI uses - same models, same quality, no API key.

It runs locally against your own Google account. Not a SaaS, not a wrapper
around the official API.

## Compared to the upstream Python lib

aitunnel started as a Go rewrite of [HanaokaYuzu/Gemini-API][upstream] (the
canonical reverse-engineered Gemini lib), then got rewritten back to Python
with the architectural lessons. They're the canonical reference; we're the
opinionated alternative. Honest comparison:

|                          | aitunnel (this) | gemini_webapi |
|--------------------------|-----------------|---------------|
| Architecture             | Four-layer (server / public / `_protocol/` / `_transport/`), one job per file | Single 1.9k-line `client.py` with 9 mixins |
| HTTP server              | **FastAPI included**, run with `aitunnel-server` | Library only |
| Web dashboard            | **Built-in** (sidebar nav, markdown, drag-drop, activity log) | None |
| Multi-turn via HTTP      | **`cid` passthrough** - stateless server | Library-only (Python ChatSession) |
| Activity log             | **In-memory ring buffer + SSE feed** | None |
| Tests                    | 17 protocol-layer tests with synthetic fixtures | Sparse |
| Image generation         | Parse + download | Parse + download + edit (Nano Banana) |
| Video / audio generation | Parse + download | Parse + download |
| NotebookLM / Extensions  | ❌ | ✅ |
| CLI tool                 | ❌ (use the HTTP API) | ✅ |
| `browser-cookie3` import | ❌ (paste form) | ✅ |
| Stars / battle-testing   | New | 2.7k+ stars, hundreds of issues fixed |
| License                  | MIT | AGPL-3.0 |

If you need Nano Banana / extensions / CLI, use [gemini_webapi][upstream]. If
you need a local Gemini *server* with a dashboard and clean architecture,
use this.

For an issue-by-issue mapping of what aitunnel addresses from gemini_webapi's
tracker, see [UPSTREAM_ISSUES.md](UPSTREAM_ISSUES.md).

[upstream]: https://github.com/HanaokaYuzu/Gemini-API

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
pip install -e ".[dev]"
pytest
aitunnel-server
```

Python 3.11 or newer.

## First run

The first time you start it without cookies, the setup form appears at
`http://localhost:8000`:

1. Open `https://gemini.google.com` in your browser, signed in (you must
   land on the chat UI, not the marketing page).
2. F12 → Application → Cookies → `https://gemini.google.com`.
3. Copy the values of `__Secure-1PSID` and `__Secure-1PSIDTS`.
4. Paste them into the form, click Save.

After that, the background rotator keeps `__Secure-1PSIDTS` fresh
indefinitely. You only re-paste when `__Secure-1PSID` itself expires -
months, not hours.

## API in 30 seconds

```sh
# basic query
curl -X POST localhost:8000/query -d '{"prompt": "hello"}'

# streaming (SSE)
curl -N -X POST localhost:8000/query/stream -d '{"prompt": "tell a story"}'

# multi-turn - feed the cid back
RESP=$(curl -s -X POST localhost:8000/query \
  -d '{"prompt":"my favorite colour is teal"}')
CID=$(echo "$RESP" | jq -r .metadata.cid)
RID=$(echo "$RESP" | jq -r .metadata.rid)

curl -X POST localhost:8000/query \
  -d "{\"prompt\":\"what colour did I tell you?\",\"cid\":\"$CID\",\"rid\":\"$RID\"}"

# upload + use
URL=$(curl -s -X POST localhost:8000/upload -F "file=@./photo.jpg" | jq -r .url)
curl -X POST localhost:8000/query \
  -d "{\"prompt\":\"describe\",\"files\":[{\"url\":\"$URL\",\"filename\":\"photo.jpg\"}]}"
```

Full reference: [API.md](API.md).

## Library use

```python
import asyncio
from aitunnel import Client

async def main():
    async with Client(psid, psidts) as c:
        # one-shot
        out = await c.query("hello")
        print(out.text)

        # streaming
        stream = await c.query_stream("write a poem about the moon")
        async for delta in stream:
            print(delta.text_delta, end="", flush=True)
            if delta.done: break
        await stream.aclose()

        # multi-turn
        chat = c.start_chat()
        await chat.send("my name is Sam")
        out = await chat.send("what's my name?")
        print(out.text)  # → "You said your name is Sam."

        # file upload + image-aware question
        att = await c.upload_path("./diagram.png")
        out = await c.query("what does this diagram show?", files=[att])
        print(out.text)

        # save generated images
        out = await c.query("generate a picture of a teal owl")
        for img in out.candidates[0].generated_images:
            await img.save_file(c, "./owl.png")

        # cancel a long stream mid-way
        stream = await c.query_stream("write a long essay")
        async for delta in stream:
            print(delta.text_delta, end="")
            if len(delta.text) > 200:
                await stream.cancel()
                break

        # deep research (~5-15 min)
        result = await c.deep_research("what's new in solid-state batteries this year")
        print(result.text)

asyncio.run(main())
```

Errors derive from `AitunnelError` so you can pattern-match:

```python
from aitunnel import AuthError, UsageLimitError, TransientError, IPBlockedError, EmptyResponseError

try:
    out = await c.query(prompt)
except AuthError:           # cookies expired - re-auth
    ...
except UsageLimitError:     # back off or switch model
    ...
except TransientError:      # already retried by policy; retry yourself if you want more
    ...
except IPBlockedError:      # rotate IP / use proxy
    ...
except EmptyResponseError:  # safety block or silent abort - try rewording
    ...
```

## Configuration

`.env` next to where you launch `aitunnel-server`:

```sh
SECURE_1PSID=g.a000...        # long-lived auth cookie
SECURE_1PSIDTS=sidts-...      # short-lived; auto-rotated

HOST=127.0.0.1                # bind address
PORT=8000

LOG_LEVEL=info                # debug | info | warning | error
HTTPS_PROXY=                  # optional outbound proxy
```

## How it works

- **Transport**: `curl_cffi` with Chrome uTLS impersonation. Without this,
  Google rejects requests on TLS fingerprint even with valid cookies.
- **Auth**: GETs `gemini.google.com/app` with your cookies, regexes the
  `SNlM0e` access token from the bootstrap HTML.
- **Generate**: POSTs to `BardFrontendService/StreamGenerate` with a
  form-encoded body - access token plus Google's nested-JSON `f.req`
  payload (a 69-element inner array embedded inside a 2-element outer
  array). Response is a length-prefixed stream of envelopes.
- **Cookie rotation**: a background `asyncio.Task` POSTs to
  `accounts.google.com/RotateCookies` every nine minutes to keep
  `__Secure-1PSIDTS` fresh.
- **Dashboard**: single embedded HTML using vanilla JS + Tailwind CDN.
  Activity log uses Server-Sent Events for live updates.

The wire format is reverse-engineered, so it can break when Google changes
something. Four-layer architecture means breakage usually localises to
`src/aitunnel/_protocol/`.

## Troubleshooting

**"SNlM0e token not found in bootstrap"** - Cookies didn't authenticate.
Open https://gemini.google.com in a fresh tab - you should see the chat UI,
not a login page. If you do, re-copy `__Secure-1PSID` and `__Secure-1PSIDTS`
and paste again. If `__Secure-1PSIDTS` was copied a few hours ago, it's
expired (it rotates ~hourly). Note: Google occasionally changes the format
of how SNlM0e is embedded in the HTML; if multiple pastes still fail and
gemini.google.com shows the chat UI for you, the parser may need updating
in `src/aitunnel/_protocol/auth.py`.

**"Gemini closed the stream before sending any content"** - Most often a
safety/policy block on the prompt. Reword and retry. Less often: account
rate-limited or transient upstream failure.

**Multi-turn forgets the previous turn** - Make sure you're sending `cid`
(and ideally `rid`/`rcid`) from the previous response's `metadata` in the
next request. See the multi-turn example above.

**Cookies stop working after a few days** - `__Secure-1PSID` itself eventually
expires (months for daily users, faster if you sign out elsewhere). Re-paste
both cookies via the setup form.

**Image generation returns nothing** - Image generation is region-restricted
by Google. If your account doesn't have access, the response will be text
explaining that.

**Lots of `transient error 1013`** - Usually a temporary Gemini issue.
The retry policy (3 attempts with backoff) catches most of these silently.
If you see it bubble up, retry the full request a few minutes later.

## What this *doesn't* do

To set expectations honestly:

- No image editing (Nano Banana) - only generation. Use [gemini_webapi][upstream]
  for editing.
- No NotebookLM, no Google Workspace extensions (YouTube/Gmail/Maps) - text + media
  only.
- No CLI tool - the HTTP API is the only public surface besides the Python package.
- No stable wire format - Google changes things periodically. Pin a version that
  works for you.
- No multi-account on the same process - run multiple instances on different
  ports if you need this.

## Layout

```
.
├── src/aitunnel/
│   ├── client.py, chat.py, stream.py     public surface
│   ├── types.py, models.py, errors.py    typed contracts
│   ├── retry.py                          retry policy
│   ├── chats.py, gems.py, ...            per-feature public APIs
│   ├── _protocol/                        wire format only
│   ├── _transport/                       curl_cffi async + cookie rotation
│   └── server/                           FastAPI app + dashboard HTML
└── tests/                                pytest suite
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Wire-format breakage is the most
common bug - open an issue with `LOG_LEVEL=debug` server output and I'll
patch the protocol indices.

## Acknowledgements

[HanaokaYuzu/Gemini-API][upstream] is the canonical Python reference for
the wire format. aitunnel is a structural rework with a tighter architecture,
built-in FastAPI server and dashboard, multi-turn HTTP API, activity log,
and a more comprehensive typed-error hierarchy. It's a smaller surface
(no Nano Banana, no extensions, no CLI), aimed at devs who want a localhost
proxy more than a feature-complete library.

## License

MIT.
