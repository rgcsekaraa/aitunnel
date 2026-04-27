# How aitunnel maps to gemini_webapi's open issues

aitunnel is structurally inspired by [HanaokaYuzu/Gemini-API][upstream] but
made different architectural and scope decisions. This file tracks every open
issue on their tracker and shows how aitunnel handles it (or doesn't).

Last reviewed against gemini_webapi at the **April 2026** issue snapshot.

[upstream]: https://github.com/HanaokaYuzu/Gemini-API/issues

## Authentication / wire-format

| Their issue | Status here |
|---|---|
| **#297** SNlM0e token missing in Gemini page HTML | ✅ Mitigated. `_protocol/auth.py` tries multiple regex variants (escaped, single-quoted, plain) before giving up. Adding more variants is the fastest fix when the format drifts again. |
| **#319** Authentication issue (generic) | ✅ Improved. Bootstrap retries once on first failure (handles cookie-jar settling races). When it does fail, the error includes a diagnostic snippet so users can tell whether they got the login page (cookies invalid), a different unexpected page, or a parser miss. |

## Reliability / error handling

| Their issue | Status here |
|---|---|
| **#313** APIError about silently aborted requests | ✅ Fixed. `StreamReader` raises `EmptyResponseError` with a clear message when the upstream closes the stream without sending any candidate text, instead of returning a bare empty Delta. |
| **#284** Attachment-heavy chats intermittently fail | ✅ Mitigated. `client.upload_file()` now retries up to 3 times with exponential backoff on transient upload failures. The dashboard also uploads files in parallel via `Promise.all`, so one slow file doesn't stall the others. |

## Cancellation / control

| Their issue | Status here |
|---|---|
| **#315** Stop generation | ✅ Fixed. `StreamReader.cancel()` closes the underlying response and short-circuits further iteration. The dashboard exposes this via the Stop button using `AbortController`. |

## Image generation

| Their issue | Status here |
|---|---|
| **#318** Image generation fails with "No CID found to recover" | ⚠️ Partially. Our `EmptyResponseError` covers the silent-close case. The deeper "candidate finished without media URL" case is tracked: it surfaces as a complete `Delta` with empty `generated_images`, which is at least non-misleading (caller sees `len(out.candidates[0].generated_images) == 0` and can retry). |
| **#294** Long image generation time | Not actionable — Google-side latency. |

## Out-of-scope feature requests

aitunnel is intentionally a smaller surface than gemini_webapi. We don't aim
to support:

| Their issue | Why not |
|---|---|
| **#316** Publish CLI as installable package | We're already pip-installable; the HTTP server (`aitunnel-server`) is our equivalent of a CLI. A separate CLI tool would duplicate it. |
| **#311** NotebookLM as queryable source | Different RPC surface; not in our scope. Use gemini_webapi if you need this. |
| **#308** Notebooks feature | Same — distinct RPC surface, not on our roadmap. |
| **#303** Nano Banana Pro image generation | We parse + download generated images but don't support image editing or "Redo with Pro". Use gemini_webapi for that. |

## Not bugs

| Their issue | Note |
|---|---|
| **#291** Similar projects to ChatGPT? | Discussion question, not a bug. |

---

## Honest summary

Out of 12 open issues:
- **5 fixed/mitigated** here (#297, #313, #315, #319, #284)
- **1 partially mitigated** (#318)
- **4 deliberately out of scope** (#316, #311, #308, #303)
- **2 not actionable** (#294, #291)

Where we're worse: feature breadth (image editing, NotebookLM, extensions),
maturity (their library has had hundreds of users find edge cases over years).
