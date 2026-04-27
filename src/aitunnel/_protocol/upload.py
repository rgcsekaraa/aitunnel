"""Multipart body builder for the file-upload endpoint."""

from __future__ import annotations

import mimetypes
import secrets
import uuid

UPLOAD_HEADERS_BASE = {
    "Origin": "https://gemini.google.com",
    "Referer": "https://gemini.google.com/",
    "X-Tenant-Id": "bard-storage",
}


def build_upload_body(
    filename: str,
    content_type: str,
    data: bytes,
) -> tuple[bytes, str]:
    """Build a multipart/form-data body with a single 'file' part.

    Returns (body_bytes, content_type_header). The content-type header carries
    the boundary which the caller must set on the request.
    """
    if not filename:
        filename = f"input_{secrets.randbelow(9_000_000) + 1_000_000}.bin"
    if not content_type:
        content_type, _ = mimetypes.guess_type(filename)
        if not content_type:
            content_type = "application/octet-stream"

    boundary = f"aitunnel-{uuid.uuid4().hex}"
    safe_name = filename.replace('"', '\\"').replace("\\", "\\\\")

    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + data + tail

    return body, f"multipart/form-data; boundary={boundary}"
