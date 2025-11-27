from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application configuration loaded from environment variables & YAML."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "YouTube Subtitle Hub"
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    storage_root: Path = BASE_DIR / "storage"
    subtitle_dir_name: str = "subtitles"
    prompt_dir_name: str = "prompts"
    video_dir_name: str = "videos"
    yt_dlp_binary: str = "yt-dlp"
    default_prompt_template: str = (
        "你是一个Notion软件使用专家，将下述我需要的内容以Notion笔记的格式输出，"
        "方便我拷贝到Notion里面作为笔记记录，要求美观简洁。\n"
        "标题和列表之类的前面使用这种类似的图标🎮、🏛、🛠️、🔗、⚡、📦、📚、📝、✅ 、⚙️、🏷、🏊、🪂、🤖、👤、❌、🎶、🎇、🎵、🔗。\n"
        "标题之间用---分隔。\n"
        "若存在数学公式，给出Notion支持的公式格式。\n"
        "要求：将视频内容整理成中文笔记，越详细越好，尽可能通俗易懂，必要情况下保留原文术语。\n"
        "视频主讲人是：{speaker}\n"
        "演讲主题是：{topic}\n"
        "演讲内容如下：\n"
        "{subtitle_body}"
    )
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_default_model: str = "gpt-4o-mini"
    openai_system_prompt: str = (
        "你是一名精通多语言的学习助手，擅长根据视频字幕梳理知识点、亮点与行动建议。"
        "回答时请尽量结构化，使用清晰的小节、序号或列表，语气亲切克制，强调可执行性。"
    )
    llm_config_path: Path = BASE_DIR / "providers.yaml"
    llm_providers: dict[str, dict[str, str | None]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _load_llm_providers(self) -> "Settings":
        providers = self.llm_providers or {}
        yaml_data = _load_yaml(self.llm_config_path)
        yaml_providers = yaml_data.get("providers", {})
        for provider_id, meta in yaml_providers.items():
            merged = providers.get(provider_id, {}).copy()
            for key, value in (meta or {}).items():
                if value is None or value == "":
                    continue
                if isinstance(value, str):
                    merged[key] = os.path.expandvars(value)
                else:
                    merged[key] = value
            providers[provider_id] = merged
        self.llm_providers = providers
        return self

    def subtitle_dir(self) -> Path:
        return self.storage_root / self.subtitle_dir_name

    def prompt_dir(self) -> Path:
        return self.storage_root / self.prompt_dir_name

    def video_dir(self) -> Path:
        return self.storage_root / self.video_dir_name


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.subtitle_dir().mkdir(parents=True, exist_ok=True)
    settings.prompt_dir().mkdir(parents=True, exist_ok=True)
    settings.video_dir().mkdir(parents=True, exist_ok=True)
    return settings


