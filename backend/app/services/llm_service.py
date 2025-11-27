from __future__ import annotations

from typing import Iterator, Tuple

from fastapi import HTTPException, status
from openai import OpenAI, OpenAIError

from ..config import Settings


class LLMService:
    """Simple wrapper around OpenAI-compatible chat completions for subtitle analysis."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def analyze(
        self,
        subtitle_text: str,
        instructions: str,
        model: str | None,
        temperature: float,
        provider: str,
        api_key: str | None,
        base_url: str | None,
    ) -> tuple[str, str]:
        client, target_model = self._prepare_client(
            provider, api_key, base_url, model
        )
        try:
            response = client.chat.completions.create(
                model=target_model,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": self._settings.openai_system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"{instructions.strip()}\n\n"
                            "以下是完整字幕内容，请在回答中引用关键信息：\n"
                            f"{subtitle_text.strip()}"
                        ),
                    },
                ],
            )
        except OpenAIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"调用 LLM 失败：{exc}",
            ) from exc

        message = response.choices[0].message.content if response.choices else ""
        if not message:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail="LLM 未返回内容。"
            )
        return message, response.model or target_model

    def stream_analyze(
        self,
        subtitle_text: str,
        instructions: str,
        model: str | None,
        temperature: float,
        provider: str,
        api_key: str | None,
        base_url: str | None,
    ) -> tuple[Iterator[str], str]:
        client, target_model = self._prepare_client(
            provider, api_key, base_url, model
        )
        try:
            events = client.chat.completions.create(
                model=target_model,
                temperature=temperature,
                stream=True,
                messages=[
                    {"role": "system", "content": self._settings.openai_system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"{instructions.strip()}\n\n"
                            "以下是完整字幕内容，请在回答中引用关键信息：\n"
                            f"{subtitle_text.strip()}"
                        ),
                    },
                ],
            )
        except OpenAIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"调用 LLM 失败：{exc}",
            ) from exc

        def iterator() -> Iterator[str]:
            try:
                for event in events:
                    if not event.choices:
                        continue
                    delta = event.choices[0].delta
                    if not delta:
                        continue
                    chunk = delta.content
                    if chunk:
                        yield chunk
            except OpenAIError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"流式响应中断：{exc}",
                ) from exc

        return iterator(), target_model

    def _prepare_client(
        self,
        provider: str,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
    ) -> Tuple[OpenAI, str]:
        resolved = self._resolve_provider(provider)
        default_api_key = resolved.get("api_key") or (
            self._settings.openai_api_key if provider == "openai" else None
        )
        actual_api_key = api_key or default_api_key
        if not actual_api_key:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请提供所选模型的 API Key。",
            )
        endpoint = base_url or resolved.get("base_url") or self._settings.openai_base_url
        target_model = model or resolved.get("default_model") or self._settings.openai_default_model
        return self._build_client(actual_api_key, endpoint), target_model

    def _build_client(self, api_key: str, base_url: str | None) -> OpenAI:
        client_kwargs: dict[str, str] = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        return OpenAI(**client_kwargs)

    def _resolve_provider(self, provider_id: str) -> dict[str, str | None]:
        info = self._settings.llm_providers.get(provider_id)
        if info is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"未知的模型提供方：{provider_id}",
            )
        return info.copy()


