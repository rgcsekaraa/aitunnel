"""Internal transport: curl_cffi-based async HTTP client with uTLS Chrome
fingerprint, plus thin wrappers for the specific Gemini call shapes
(generate, batch, upload, download, rotate)."""

from .client import Transport

__all__ = ["Transport"]
