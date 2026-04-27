"""Exception hierarchy. Concrete errors derive from AitunnelError so callers
can `except AitunnelError` to catch any package-level failure, or pattern-
match on specific subclasses for retry/handling decisions."""

from __future__ import annotations


class AitunnelError(Exception):
    """Base for all package errors."""


class AuthError(AitunnelError):
    """Cookies missing, expired, or rejected by Google."""


class UsageLimitError(AitunnelError):
    """Per-account Gemini quota exhausted (code 1037)."""


class TransientError(AitunnelError):
    """Temporary upstream issue (code 1013, 5xx). Worth retrying."""


class IPBlockedError(AitunnelError):
    """Google flagged the IP (code 1060). Try a proxy."""


class ModelInvalidError(AitunnelError):
    """Model header invalid or inconsistent with chat history."""


class EmptyResponseError(AitunnelError):
    """Gemini returned a candidate with no usable text. Often safety-blocked."""


class NotStartedError(AitunnelError):
    """Client method called before .start() succeeded."""


class ClosedError(AitunnelError):
    """Client method called after .close()."""


class APIError(AitunnelError):
    """Non-200 response from a Gemini endpoint that we don't classify
    as one of the more specific errors above."""

    def __init__(self, status_code: int, body: str = "", *, cause: Exception | None = None) -> None:
        self.status_code = status_code
        self.body = body[:500]
        self.__cause__ = cause
        super().__init__(f"HTTP {status_code}: {self.body}")


class ModelError(AitunnelError):
    """Wrap a known Gemini error code surfaced inside a candidate envelope."""

    def __init__(self, code: int, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"model error {code}: {message}")


# Numeric error codes Gemini surfaces inside the candidate envelope at
# inner[5][2][0][1][0]. Worth keeping near the exception classes since they
# drive the classifier in stream.py.
CODE_TRANSIENT_1013 = 1013
CODE_USAGE_LIMIT = 1037
CODE_MODEL_INCONSISTENT = 1050
CODE_MODEL_HEADER_INVALID = 1052
CODE_IP_BLOCKED = 1060


def classify_model_error(code: int) -> ModelError:
    """Map a known error code to a typed `ModelError` subclass instance."""
    msg_map = {
        CODE_USAGE_LIMIT: "Gemini usage limit exceeded for this model",
        CODE_MODEL_INCONSISTENT: "model inconsistent with chat history",
        CODE_MODEL_HEADER_INVALID: "model header invalid (build IDs may be stale)",
        CODE_IP_BLOCKED: "IP temporarily blocked",
        CODE_TRANSIENT_1013: "transient model error 1013",
    }
    return ModelError(code, msg_map.get(code, f"unknown error code {code}"))
