# Contributing

Bugs, breakage when Google rotates the wire format, FastAPI tweaks - all welcome.

## Reporting wire-format breakage

This is the most common cause of breakage. Open an issue with:

- Server output with `LOG_LEVEL=debug`
- The exact endpoint that broke
- A line or two from the error message

The protocol indices live in `src/aitunnel/_protocol/` with comments pointing
at the relevant Google wire-shape.

## Pull requests

- `pytest` should pass
- `ruff check .` should be clean
- New feature -> add a test in `tests/` if it touches the wire format

## Local dev

```sh
git clone https://github.com/rgcsekaraa/aitunnel
cd aitunnel
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
aitunnel-server
```

The first run pops a setup form for cookies; after that you're hitting your
own running instance at `http://localhost:8000`.

## Design notes

The four-layer split is load-bearing: keep imports flowing one direction.

```
server/         -> uses public package
public package  -> uses _transport, _protocol
_transport/     -> uses _protocol (only for shared URLs/types)
_protocol/      -> no internal deps
```

Errors at the public boundary should derive from the `AitunnelError` hierarchy
in `errors.py` so callers can pattern-match (`except AuthError:`). Don't
surface raw `curl_cffi` errors past `_transport/`.
