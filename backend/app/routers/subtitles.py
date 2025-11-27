from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from starlette.concurrency import iterate_in_threadpool
from starlette.responses import StreamingResponse

from ..config import get_settings
from ..schemas import (
    SubtitleAnalysisRequest,
    SubtitleAnalysisResponse,
    SubtitleDownloadRequest,
    SubtitleDownloadResponse,
    SubtitleListRequest,
    SubtitleListResponse,
)
from ..services.llm_service import LLMService
from ..services.prompt_service import PromptService
from ..services.subtitle_service import SubtitleService


router = APIRouter()
settings = get_settings()
prompt_service = PromptService(settings)
subtitle_service = SubtitleService(settings, prompt_service)
llm_service = LLMService(settings)


@router.post("/download", response_model=SubtitleDownloadResponse)
async def download_subtitles(payload: SubtitleDownloadRequest) -> SubtitleDownloadResponse:
    return await run_in_threadpool(subtitle_service.download, payload)


@router.post("/list", response_model=SubtitleListResponse)
async def list_subtitles(payload: SubtitleListRequest) -> SubtitleListResponse:
    return await run_in_threadpool(
        subtitle_service.list_available_subtitles, payload
    )


@router.post("/analyze", response_model=SubtitleAnalysisResponse)
async def analyze_subtitles(
    payload: SubtitleAnalysisRequest,
) -> SubtitleAnalysisResponse | StreamingResponse:
    subtitle_text = payload.subtitle_text
    if subtitle_text is None:
        subtitle_text = await run_in_threadpool(
            subtitle_service.load_subtitle_text, payload.job_id, payload.subtitle_file
        )
    if payload.stream:
        stream_iter, model_used = llm_service.stream_analyze(
            subtitle_text,
            payload.instructions,
            payload.model,
            payload.temperature,
            payload.provider,
            payload.api_key,
            payload.base_url,
        )
        headers = {
            "X-LLM-Provider": payload.provider,
            "X-LLM-Model": model_used,
        }
        return StreamingResponse(
            iterate_in_threadpool(stream_iter),
            media_type="text/plain; charset=utf-8",
            headers=headers,
        )

    assistant_message, model_used = await run_in_threadpool(
        llm_service.analyze,
        subtitle_text,
        payload.instructions,
        payload.model,
        payload.temperature,
        payload.provider,
        payload.api_key,
        payload.base_url,
    )
    return SubtitleAnalysisResponse(
        assistant_message=assistant_message,
        model_used=model_used,
        provider=payload.provider,
    )
