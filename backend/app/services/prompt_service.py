from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ..config import Settings
from ..schemas import PromptPayload


class PromptService:
    """Compose and persist prompt files for downstream LLM usage."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def build_prompt(self, subtitle_text: str, payload: PromptPayload | None) -> str:
        template = (payload.template if payload and payload.template else None) or self._settings.default_prompt_template
        speaker = payload.speaker if payload else "未知主讲人"
        topic = payload.topic if payload else "未指定主题"
        prompt = template.format(
            speaker=speaker,
            topic=topic,
            subtitle_body=subtitle_text.strip(),
        )
        if payload and payload.extra_instructions:
            prompt += "\n\n额外提示：\n" + payload.extra_instructions.strip()
        return prompt

    def save_prompt(self, job_id: UUID, prompt_text: str) -> Path:
        prompt_path = self._settings.prompt_dir() / f"{job_id}.txt"
        prompt_path.write_text(prompt_text, encoding="utf-8")
        return prompt_path

