from uuid import UUID

from fastapi import APIRouter, HTTPException, status
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
    SubtitlePlaylistDownloadResponse,
    SubtitlePlaylistProgressResponse,
)
from ..services.llm_service import LLMService
from ..services.prompt_service import PromptService
from ..services.subtitle_service import SubtitleService


router = APIRouter()
settings = get_settings()
prompt_service = PromptService(settings)
subtitle_service = SubtitleService(settings, prompt_service)
llm_service = LLMService(settings)


@router.post("/download")
async def download_subtitles(
    payload: SubtitleDownloadRequest
) -> SubtitleDownloadResponse | SubtitlePlaylistDownloadResponse:
    """下载字幕，如果是播放列表则返回播放列表响应（包含job_id用于查询进度）。"""
    return await run_in_threadpool(subtitle_service.download, payload)


@router.get("/playlist-progress/{job_id}", response_model=SubtitlePlaylistProgressResponse)
async def get_playlist_progress(job_id: UUID) -> SubtitlePlaylistProgressResponse:
    """获取播放列表下载进度。"""
    progress = await run_in_threadpool(subtitle_service.get_playlist_progress, job_id)
    if progress is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到对应的下载任务，可能已完成或不存在。",
        )
    
    return SubtitlePlaylistProgressResponse(
        job_id=job_id,
        total_videos=progress["total_videos"],
        completed=progress["completed"],
        successful=progress["successful"],
        failed=progress["failed"],
        in_progress=progress["in_progress"],
        status=progress["status"],
        current_videos=progress["current_videos"],
        results=progress["results"],
    )


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
