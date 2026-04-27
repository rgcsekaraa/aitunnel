"""Public Pydantic models for responses and streaming events."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WebImage(BaseModel):
    url: str
    alt: str = ""


class GeneratedImage(BaseModel):
    url: str
    alt: str = ""
    image_id: str = ""

    # Conversation IDs needed for the full-size image RPC. Populated at parse
    # time by stream.py; users normally don't read these directly.
    cid: str = ""
    rid: str = ""
    rcid: str = ""


class GeneratedVideo(BaseModel):
    url: str
    thumbnail: str = ""

    cid: str = ""
    rid: str = ""
    rcid: str = ""


class GeneratedMedia(BaseModel):
    """Music/audio media. `url` is the MP4 video; `mp3_url` is the audio-only
    track. Both may be empty if Gemini hadn't finished generating the media."""

    url: str = ""
    thumbnail: str = ""
    mp3_url: str = ""
    mp3_thumbnail: str = ""

    cid: str = ""
    rid: str = ""
    rcid: str = ""


class Candidate(BaseModel):
    """One reply candidate. A full ModelOutput typically has one Candidate
    today, but Gemini can return multiple alternative phrasings."""

    rcid: str
    text: str = ""
    thoughts: str = ""
    web_images: list[WebImage] = Field(default_factory=list)
    generated_images: list[GeneratedImage] = Field(default_factory=list)
    generated_videos: list[GeneratedVideo] = Field(default_factory=list)
    generated_media: list[GeneratedMedia] = Field(default_factory=list)


class ModelOutput(BaseModel):
    """Full response from Gemini for a single turn."""

    metadata: list[str] = Field(default_factory=list)  # [cid, rid, rcid]
    candidates: list[Candidate] = Field(default_factory=list)
    chosen: int = 0

    @property
    def text(self) -> str:
        if not self.candidates:
            return ""
        idx = self.chosen if 0 <= self.chosen < len(self.candidates) else 0
        return self.candidates[idx].text

    @property
    def thoughts(self) -> str:
        if not self.candidates:
            return ""
        idx = self.chosen if 0 <= self.chosen < len(self.candidates) else 0
        return self.candidates[idx].thoughts

    @property
    def cid(self) -> str:
        return self.metadata[0] if len(self.metadata) > 0 else ""

    @property
    def rid(self) -> str:
        return self.metadata[1] if len(self.metadata) > 1 else ""

    @property
    def rcid(self) -> str:
        return self.metadata[2] if len(self.metadata) > 2 else ""


class Delta(BaseModel):
    """One streamed chunk from `Client.query_stream`. The async generator
    closes after a Delta with `done=True` is yielded."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    text: str = ""              # cumulative text so far
    text_delta: str = ""        # just the new portion since the previous Delta
    thoughts: str = ""
    thoughts_delta: str = ""
    done: bool = False
    output: ModelOutput | None = None  # set on the terminal Delta


class FileAttachment(BaseModel):
    """An uploaded file reference. Returned from `Client.upload_file`,
    accepted by `Client.query` via the `files` parameter."""

    url: str
    filename: str


class ChatInfo(BaseModel):
    """One persisted conversation in the user's Gemini history."""

    cid: str
    title: str = ""
    is_pinned: bool = False
    timestamp: float = 0.0  # unix seconds


class ChatTurn(BaseModel):
    """One user or model turn in a persisted chat."""

    role: str           # "user" | "model"
    text: str = ""
    output: ModelOutput | None = None  # populated only for model turns


class ChatHistory(BaseModel):
    cid: str
    turns: list[ChatTurn] = Field(default_factory=list)


class Gem(BaseModel):
    """A saved system-prompt persona."""

    id: str
    name: str = ""
    description: str = ""
    prompt: str = ""
    predefined: bool = False  # True for Google's built-ins


class DeepResearchPlan(BaseModel):
    research_id: str = ""
    title: str = ""
    query: str = ""
    steps: list[str] = Field(default_factory=list)
    eta_text: str = ""
    confirm_prompt: str = ""
    confirmation_url: str = ""
    modify_prompt: str = ""
    response_text: str = ""
    cid: str = ""
    rid: str = ""
    rcid: str = ""
    metadata: list[str] = Field(default_factory=list)
    raw_state: int = 0


class DeepResearchStatus(BaseModel):
    research_id: str
    state: str = "running"  # "running" | "awaiting_confirmation" | "completed"
    done: bool = False
    title: str = ""
    query: str = ""
    cid: str = ""
    notes: list[str] = Field(default_factory=list)
    raw_state: int = 0
    timestamp: float = 0.0


class DeepResearchResult(BaseModel):
    plan: DeepResearchPlan
    start_output: ModelOutput | None = None
    final_output: ModelOutput | None = None
    statuses: list[DeepResearchStatus] = Field(default_factory=list)
    done: bool = False

    @property
    def text(self) -> str:
        return self.final_output.text if self.final_output else ""
