"""aitunnel - local Gemini proxy on localhost.

Public API. Internal modules are prefixed with `_`.
"""

from .chat import ChatSession
from .chats import ChatInfo
from .client import Client
from .errors import (
    AitunnelError,
    APIError,
    AuthError,
    ClosedError,
    EmptyResponseError,
    IPBlockedError,
    ModelError,
    ModelInvalidError,
    NotStartedError,
    TransientError,
    UsageLimitError,
)
from .models import (
    MODEL_FLASH,
    MODEL_FLASH_ADVANCED,
    MODEL_PRO,
    MODEL_PRO_ADVANCED,
    MODEL_THINKING,
    MODEL_UNSPECIFIED,
    Model,
)
from .retry import RetryPolicy
from .stream import StreamReader
from .types import (
    Candidate,
    ChatHistory,
    ChatTurn,
    DeepResearchPlan,
    DeepResearchResult,
    DeepResearchStatus,
    Delta,
    FileAttachment,
    Gem,
    GeneratedImage,
    GeneratedMedia,
    GeneratedVideo,
    ModelOutput,
    WebImage,
)

__version__ = "0.2.0"

__all__ = [
    "__version__",
    # client + chat
    "Client",
    "ChatSession",
    "StreamReader",
    # types
    "Candidate",
    "ChatHistory",
    "ChatInfo",
    "ChatTurn",
    "DeepResearchPlan",
    "DeepResearchResult",
    "DeepResearchStatus",
    "Delta",
    "FileAttachment",
    "Gem",
    "GeneratedImage",
    "GeneratedMedia",
    "GeneratedVideo",
    "ModelOutput",
    "WebImage",
    # models
    "Model",
    "MODEL_UNSPECIFIED",
    "MODEL_PRO",
    "MODEL_FLASH",
    "MODEL_THINKING",
    "MODEL_PRO_ADVANCED",
    "MODEL_FLASH_ADVANCED",
    # errors
    "AitunnelError",
    "APIError",
    "AuthError",
    "ClosedError",
    "EmptyResponseError",
    "IPBlockedError",
    "ModelError",
    "ModelInvalidError",
    "NotStartedError",
    "TransientError",
    "UsageLimitError",
    # retry
    "RetryPolicy",
]
