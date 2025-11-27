from uuid import UUID

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from ..config import get_settings
from ..schemas import VideoDownloadRequest, VideoJobResponse
from ..services.video_service import VideoService


router = APIRouter()
settings = get_settings()
video_service = VideoService(settings)


@router.post("/download", response_model=VideoJobResponse)
async def enqueue_video_download(payload: VideoDownloadRequest) -> VideoJobResponse:
    return await run_in_threadpool(video_service.enqueue, payload)


@router.get("/status/{job_id}", response_model=VideoJobResponse)
async def get_video_status(job_id: UUID) -> VideoJobResponse:
    return await run_in_threadpool(video_service.job_status, job_id)


@router.get("/fetch/{job_id}")
async def fetch_video(job_id: UUID) -> StreamingResponse:
    file_path = await run_in_threadpool(video_service.fetch_file, job_id)
    filename = file_path.name
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        file_path.open("rb"),
        media_type="video/mp4",
        headers=headers,
    )

