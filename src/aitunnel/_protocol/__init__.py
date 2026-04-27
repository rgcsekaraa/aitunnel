"""Wire-format encoding and decoding for Gemini's web RPC.

This subpackage is internal. Public callers use `aitunnel.Client`.
"""

from .auth import (
    BATCH_EXEC_URL,
    GENERATE_URL,
    GOOGLE_URL,
    INIT_URL,
    ROTATE_URL,
    UPLOAD_URL,
    SessionInfo,
    parse_session_info,
)
from .batch import (
    RPC_BARD_SETTINGS,
    RPC_CREATE_GEM,
    RPC_DEEP_RESEARCH_BOOTSTRAP,
    RPC_DEEP_RESEARCH_STATUS,
    RPC_DELETE_CHAT_1,
    RPC_DELETE_CHAT_2,
    RPC_DELETE_GEM,
    RPC_GET_FULL_SIZE_IMAGE,
    RPC_LIST_CHATS,
    RPC_LIST_GEMS,
    RPC_READ_CHAT,
    RPC_UPDATE_GEM,
    BatchCall,
    BatchPart,
    build_batch_execute,
    parse_batch_response,
)
from .frames import FrameReader
from .request import (
    FileRef,
    GenerateOpts,
    build_generate,
)
from .research import (
    DeepResearchPlanData,
    DeepResearchStatusData,
    extract_deep_research_plan,
    extract_deep_research_status,
)
from .response import (
    CandidateUpdate,
    Event,
    parse_candidate,
    parse_event,
)
from .upload import UPLOAD_HEADERS_BASE, build_upload_body

__all__ = [
    "INIT_URL",
    "GOOGLE_URL",
    "GENERATE_URL",
    "BATCH_EXEC_URL",
    "UPLOAD_URL",
    "ROTATE_URL",
    "SessionInfo",
    "parse_session_info",
    "RPC_LIST_CHATS",
    "RPC_READ_CHAT",
    "RPC_DELETE_CHAT_1",
    "RPC_DELETE_CHAT_2",
    "RPC_LIST_GEMS",
    "RPC_CREATE_GEM",
    "RPC_UPDATE_GEM",
    "RPC_DELETE_GEM",
    "RPC_GET_FULL_SIZE_IMAGE",
    "RPC_DEEP_RESEARCH_STATUS",
    "RPC_DEEP_RESEARCH_BOOTSTRAP",
    "RPC_BARD_SETTINGS",
    "BatchCall",
    "BatchPart",
    "build_batch_execute",
    "parse_batch_response",
    "FrameReader",
    "GenerateOpts",
    "FileRef",
    "build_generate",
    "CandidateUpdate",
    "Event",
    "parse_candidate",
    "parse_event",
    "UPLOAD_HEADERS_BASE",
    "build_upload_body",
    "DeepResearchPlanData",
    "DeepResearchStatusData",
    "extract_deep_research_plan",
    "extract_deep_research_status",
]
