from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator


SubtitleFormat = Literal["srt", "vtt", "ass", "json3", "ttml"]
VideoQuality = Literal[
    "best",
    "2160p",
    "1440p",
    "1080p",
    "720p",
    "480p",
    "360p",
    "240p",
    "144p",
]


class PromptPayload(BaseModel):
    template: str | None = None
    speaker: str = "未知主讲人"
    topic: str = "未指定主题"
    extra_instructions: str | None = Field(
        default=None,
        description="Additional hints appended after the template body.",
    )


class SubtitleDownloadRequest(BaseModel):
    video_url: HttpUrl
    subtitle_languages: list[str] = Field(default_factory=lambda: ["en"])
    subtitle_format: SubtitleFormat = "srt"
    prefer_auto_subs: bool = True
    output_filename: str | None = None
    prompt: PromptPayload | None = None

    @field_validator("subtitle_languages")
    @classmethod
    def validate_languages(cls, value: list[str]) -> list[str]:
        clean = [lang.strip() for lang in value if lang.strip()]
        if not clean:
            raise ValueError("At least one subtitle language must be provided.")
        return clean


class SubtitleDownloadResponse(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    subtitle_format: SubtitleFormat
    subtitle_languages: list[str]
    subtitle_file: str
    prompt_file: str | None = None
    prompt_preview: str | None = None


class SubtitleTrack(BaseModel):
    language: str
    formats: list[str] = Field(default_factory=list)
    is_automatic: bool = False


class SubtitleListRequest(BaseModel):
    video_url: HttpUrl


class SubtitleListResponse(BaseModel):
    automatic: list[SubtitleTrack] = Field(default_factory=list)
    manual: list[SubtitleTrack] = Field(default_factory=list)


class SubtitleAnalysisRequest(BaseModel):
    job_id: UUID | None = None
    subtitle_file: str | None = Field(
        default=None, description="Public path such as /storage/subtitles/xxx.srt"
    )
    subtitle_text: str | None = None
    instructions: str = Field(min_length=1)
    provider: str = Field(default="openai", description="LLM provider identifier.")
    api_key: str | None = Field(
        default=None, description="User-provided API key for the selected provider."
    )
    base_url: str | None = Field(
        default=None, description="Optional base URL override for OpenAI兼容 API。"
    )
    model: str | None = None
    temperature: float = Field(default=0.2, ge=0, le=1)
    stream: bool = False

    @model_validator(mode="after")
    def validate_sources(self) -> "SubtitleAnalysisRequest":
        if not any([self.job_id, self.subtitle_file, self.subtitle_text]):
            raise ValueError("job_id、subtitle_file 或 subtitle_text 至少提供一个。")
        return self


class SubtitleAnalysisResponse(BaseModel):
    assistant_message: str
    model_used: str
    provider: str


class VideoDownloadRequest(BaseModel):
    video_url: HttpUrl
    quality: VideoQuality = "best"
    output_filename: str | None = None


class VideoDownloadResponse(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    quality: VideoQuality
    video_file: str
    filename: str
    file_size: int = Field(description="File size in bytes")
    file_size_human: str
    format_note: str | None = Field(default=None, description="Human readable format info.")


class VideoJobStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class VideoJobResponse(BaseModel):
    job_id: UUID
    status: VideoJobStatus
    progress_percent: int = 0
    message: str | None = None
    quality: VideoQuality
    video_file: str | None = None
    filename: str | None = None
    file_size: int | None = None
    file_size_human: str | None = None
    format_note: str | None = None
    fetch_url: str | None = None
    created_at: datetime
    updated_at: datetime

