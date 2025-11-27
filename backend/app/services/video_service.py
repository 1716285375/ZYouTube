from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Final
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from ..config import Settings
from ..schemas import (
    VideoDownloadRequest,
    VideoDownloadResponse,
    VideoJobResponse,
    VideoJobStatus,
    VideoQuality,
)

QUALITY_HEIGHT_MAP: Final[dict[VideoQuality, int]] = {
    "2160p": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
    "240p": 240,
    "144p": 144,
}


class VideoService:
    """Manage YouTube video downloads & async jobs via yt-dlp."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._jobs: dict[UUID, dict[str, object]] = {}
        self._job_files: dict[UUID, Path] = {}
        self._lock = threading.Lock()

    # ---------- Public API ----------

    def download(self, payload: VideoDownloadRequest, job_id: UUID | None = None) -> VideoDownloadResponse:
        """Synchronous download helper (used internally + tests)."""
        job_id = job_id or uuid4()
        temp_dir = Path(tempfile.mkdtemp(prefix="yt_video_"))
        try:
            video_path, format_note = self._run_yt_dlp(temp_dir, payload, job_id=job_id)
            final_path = self._persist_video(job_id, video_path, payload)
            stat = final_path.stat()
            return VideoDownloadResponse(
                job_id=job_id,
                quality=payload.quality,
                video_file=self._public_path(final_path),
                filename=final_path.name,
                file_size=stat.st_size,
                file_size_human=self._format_bytes(stat.st_size),
                format_note=format_note,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def enqueue(self, payload: VideoDownloadRequest) -> VideoJobResponse:
        job_id = uuid4()
        job = self._create_job(job_id, payload)
        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, payload),
            daemon=True,
        )
        thread.start()
        return self._serialize_job(job_id)

    def job_status(self, job_id: UUID) -> VideoJobResponse:
        self._ensure_job(job_id)
        return self._serialize_job(job_id)

    def fetch_file(self, job_id: UUID) -> Path:
        self._ensure_job(job_id)
        job = self._jobs[job_id]
        if job["status"] != VideoJobStatus.completed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="视频仍在处理中或已失败，暂无法下载。",
            )
        file_path = self._job_files.get(job_id)
        if not file_path or not file_path.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="视频文件不存在或已被清理。",
            )
        return file_path

    # ---------- Internal helpers ----------

    def _run_job(self, job_id: UUID, payload: VideoDownloadRequest) -> None:
        self._update_job(job_id, status=VideoJobStatus.running, progress_percent=5, message="正在初始化下载任务...")
        try:
            result = self.download(payload, job_id=job_id)
            file_path = self._settings.storage_root / Path(result.video_file.replace("/storage/", "", 1))
            self._job_files[job_id] = file_path
            self._update_job(
                job_id,
                status=VideoJobStatus.completed,
                progress_percent=100,
                message="下载完成，可点击获取视频。",
                video_file=result.video_file,
                filename=result.filename,
                file_size=result.file_size,
                file_size_human=result.file_size_human,
                format_note=result.format_note,
            )
        except Exception as exc:  # pylint: disable=broad-except
            self._update_job(
                job_id,
                status=VideoJobStatus.failed,
                progress_percent=100,
                message=str(exc),
            )

    def _create_job(self, job_id: UUID, payload: VideoDownloadRequest) -> dict[str, object]:
        job = {
            "job_id": job_id,
            "status": VideoJobStatus.pending,
            "progress_percent": 0,
            "message": "已加入队列",
            "quality": payload.quality,
            "video_file": None,
            "filename": None,
            "file_size": None,
            "file_size_human": None,
            "format_note": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        with self._lock:
            self._jobs[job_id] = job
        return job

    def _update_job(self, job_id: UUID, **updates: object) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.update(updates)
            job["updated_at"] = datetime.utcnow()

    def _ensure_job(self, job_id: UUID) -> None:
        if job_id not in self._jobs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到编号为 {job_id} 的视频任务。",
            )

    def _serialize_job(self, job_id: UUID) -> VideoJobResponse:
        job = self._jobs[job_id]
        fetch_url = f"/api/videos/fetch/{job_id}" if job["status"] == VideoJobStatus.completed else None
        return VideoJobResponse(
            job_id=job_id,
            status=job["status"],
            progress_percent=int(job["progress_percent"]),
            message=job.get("message"),
            quality=job["quality"],
            video_file=job.get("video_file"),
            filename=job.get("filename"),
            file_size=job.get("file_size"),
            file_size_human=job.get("file_size_human"),
            format_note=job.get("format_note"),
            fetch_url=fetch_url,
            created_at=job["created_at"],
            updated_at=job["updated_at"],
        )

    def _run_yt_dlp(
        self, temp_dir: Path, payload: VideoDownloadRequest, job_id: UUID | None = None
    ) -> tuple[Path, str]:
        format_selector = self._format_selector(payload.quality)
        output_template = temp_dir / "%(title)s.%(ext)s"
        command = [
            self._settings.yt_dlp_binary,
            "-f",
            format_selector,
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "--newline",
            "--progress",
            "-o",
            str(output_template),
            str(payload.video_url),
        ]
        
        stdout_lines = []
        stderr_lines = []
        
        try:
            # Use Popen to read output in real-time
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
            )
            
            # Progress regex: matches "[download] XX.X% of ..."
            progress_pattern = re.compile(r"\[download\]\s+(\d+\.?\d*)%")
            
            # Read stdout line by line
            if process.stdout:
                for line in iter(process.stdout.readline, ""):
                    if not line:
                        break
                    line = line.strip()
                    stdout_lines.append(line)
                    
                    # Parse progress percentage
                    if job_id:
                        match = progress_pattern.search(line)
                        if match:
                            try:
                                percent = float(match.group(1))
                                # Map 0-100% to 10-90% (reserve 10% for initialization, 10% for finalization)
                                mapped_percent = int(10 + (percent * 0.8))
                                self._update_job(
                                    job_id,
                                    progress_percent=mapped_percent,
                                    message=f"正在下载视频... {percent:.1f}%",
                                )
                            except (ValueError, IndexError):
                                pass
            
            # Read stderr
            if process.stderr:
                for line in iter(process.stderr.readline, ""):
                    if not line:
                        break
                    stderr_lines.append(line.strip())
            
            return_code = process.wait()
            
            if return_code != 0:
                error_output = "\n".join(stderr_lines + stdout_lines[-20:])
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"yt-dlp 执行失败：{error_output}",
                )
                
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="yt-dlp 可执行文件未找到，请确保已安装并配置到 PATH。",
            ) from exc

        downloaded_file = self._locate_downloaded_file(temp_dir)
        if downloaded_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="未能在下载目录中找到视频文件，可能是 YouTube 限制或链接无效。",
            )

        format_note = self._infer_format_note(payload.quality, "\n".join(stdout_lines))
        return downloaded_file, format_note

    def _locate_downloaded_file(self, directory: Path) -> Path | None:
        candidates = [
            candidate
            for candidate in directory.rglob("*")
            if candidate.is_file() and not candidate.name.endswith(".part")
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.stat().st_mtime)

    def _persist_video(
        self, job_id: UUID, temp_video: Path, payload: VideoDownloadRequest
    ) -> Path:
        suffix = temp_video.suffix or ".mp4"
        output_name = payload.output_filename.strip() if payload.output_filename else ""
        safe_name = Path(output_name).name if output_name else ""
        if safe_name:
            if not safe_name.lower().endswith(suffix.lower()):
                safe_name = f"{safe_name}{suffix}"
        else:
            safe_name = f"{job_id}{suffix}"

        target = self._settings.video_dir() / safe_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(temp_video), target)
        return target

    def _format_selector(self, quality: VideoQuality) -> str:
        if quality == "best":
            return "bv*+ba/b"
        height = QUALITY_HEIGHT_MAP.get(quality, 0)
        if not height:
            return "bv*+ba/b"
        return (
            f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
            f"bv*[height<={height}]+ba/b[height<={height}]"
        )

    def _infer_format_note(self, quality: VideoQuality, logs: str) -> str:
        if quality == "best":
            return "自动匹配最高可用画质"
        return f"目标画质：{quality}"

    def _public_path(self, actual_path: Path) -> str:
        rel_path = actual_path.relative_to(self._settings.storage_root)
        return f"/storage/{rel_path.as_posix()}"

    def _format_bytes(self, num: int) -> str:
        step = 1024.0
        units = ["B", "KB", "MB", "GB", "TB"]
        size = float(num)
        for unit in units:
            if size < step:
                return f"{size:.2f} {unit}"
            size /= step
        return f"{size * step:.2f} TB"

