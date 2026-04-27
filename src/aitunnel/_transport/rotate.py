"""Cookie rotation against accounts.google.com/RotateCookies. POST a
specific zero-padded payload and Google sends back a fresh
__Secure-1PSIDTS in the response Set-Cookie."""

from __future__ import annotations

from .._protocol import ROTATE_URL
from .client import Transport

_ROTATE_BODY = '[000,"-0000000000000000000"]'


async def rotate_cookies(t: Transport) -> tuple[str, int]:
    """Refresh __Secure-1PSIDTS in place. Returns (new_value, status_code).

    status 401 means the session is dead (PSID itself expired/revoked).
    """
    resp = await t.post(
        ROTATE_URL,
        headers={
            "Content-Type": "application/json",
            "Origin": "https://accounts.google.com",
        },
        data=_ROTATE_BODY,
    )
    if resp.status_code != 200:
        return "", resp.status_code
    # curl_cffi merges Set-Cookie into the session jar automatically.
    return t.get_cookie("__Secure-1PSIDTS"), resp.status_code
