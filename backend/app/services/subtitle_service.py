from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from ..config import Settings
from ..schemas import (
    PromptPayload,
    SubtitleDownloadRequest,
    SubtitleDownloadResponse,
    SubtitleListRequest,
    SubtitleListResponse,
    SubtitleTrack,
)
from .prompt_service import PromptService


class SubtitleService:
    """Download and post-process YouTube subtitles using yt-dlp."""

    def __init__(self, settings: Settings, prompt_service: PromptService):
        self._settings = settings
        self._prompt_service = prompt_service

    def download(self, payload: SubtitleDownloadRequest) -> SubtitleDownloadResponse:
        job_id = uuid4()
        temp_dir = Path(tempfile.mkdtemp(prefix="yt_subs_"))

        try:
            subtitle_file = self._run_yt_dlp(temp_dir, payload)
            final_subtitle_path = self._persist_subtitle(job_id, subtitle_file, payload)

            prompt_text = None
            prompt_file = None
            if payload.prompt is not None:
                prompt_text = self._generate_prompt(final_subtitle_path, payload.prompt)
                prompt_file = self._prompt_service.save_prompt(job_id, prompt_text)

            return SubtitleDownloadResponse(
                job_id=job_id,
                subtitle_format=payload.subtitle_format,
                subtitle_languages=payload.subtitle_languages,
                subtitle_file=self._public_path(final_subtitle_path),
                prompt_file=self._public_path(prompt_file) if prompt_file else None,
                prompt_preview=prompt_text[:1000] if prompt_text else None,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def list_available_subtitles(
        self, payload: SubtitleListRequest
    ) -> SubtitleListResponse:
        command = [
            self._settings.yt_dlp_binary,
            "--list-subs",
            str(payload.video_url),
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="yt-dlp 可执行文件未找到，请确保已安装并配置到 PATH。",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"yt-dlp 执行失败：{exc.stderr or exc.stdout}",
            ) from exc

        automatic, manual = self._parse_list_subs_output(completed.stdout or "")
        if not automatic and not manual:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    "YouTube 未返回可列出的字幕轨道，可能仅支持实时自动字幕。"
                    "可直接尝试下载自动字幕（勾选“使用自动生成字幕”）。"
                ),
            )
        return SubtitleListResponse(automatic=automatic, manual=manual)

    def _run_yt_dlp(self, temp_dir: Path, payload: SubtitleDownloadRequest) -> Path:
        languages = ",".join(payload.subtitle_languages)
        command = [
            self._settings.yt_dlp_binary,
            "--skip-download",
            "--write-auto-subs" if payload.prefer_auto_subs else "--write-subs",
            "--sub-lang",
            languages,
            "--convert-subs",
            payload.subtitle_format,
            "-P",
            str(temp_dir),
            str(payload.video_url),
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="yt-dlp 可执行文件未找到，请确保已安装并配置到 PATH。",
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"yt-dlp 执行失败：{exc.stderr or exc.stdout}",
            ) from exc

        logs = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
        subtitle_file = self._locate_subtitle_file(temp_dir, payload.subtitle_format)
        if subtitle_file is None:
            message = self._missing_subtitle_message(payload, logs)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
        return subtitle_file

    def _locate_subtitle_file(self, directory: Path, extension: str) -> Path | None:
        for candidate in directory.rglob(f"*.{extension}"):
            return candidate
        return None

    def _persist_subtitle(
        self, job_id: UUID, subtitle_path: Path, payload: SubtitleDownloadRequest
    ) -> Path:
        output_name = payload.output_filename or f"{job_id}.{payload.subtitle_format}"
        final_path = self._settings.subtitle_dir() / output_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(subtitle_path), final_path)
        return final_path

    def _generate_prompt(
        self, subtitle_file: Path, prompt_payload: PromptPayload
    ) -> str:
        subtitle_text = subtitle_file.read_text(encoding="utf-8", errors="ignore")
        return self._prompt_service.build_prompt(subtitle_text, prompt_payload)

    def _public_path(self, actual_path: Path | None) -> str | None:
        if actual_path is None:
            return None
        rel_path = actual_path.relative_to(self._settings.storage_root)
        return f"/storage/{rel_path.as_posix()}"

    def _missing_subtitle_message(
        self, payload: SubtitleDownloadRequest, logs: str | None
    ) -> str:
        languages = "、".join(payload.subtitle_languages)
        hint = (
            "目标视频没有匹配的字幕语言，或 YouTube 暂时拒绝生成自动字幕。"
        )
        if logs and "There are no subtitles" in logs:
            hint = (
                f"未找到所请求语言（{languages}）的字幕。"
                "可尝试在 YouTube 中切换语言或使用 `yt-dlp --list-subs` 查看可用字幕。"
            )
        elif logs and "HTTP Error 429" in logs:
            hint = "YouTube 暂时返回 429（请求过多），稍后重试或配置 cookies。"
        return f"{hint}（请求语言：{languages}，格式：{payload.subtitle_format}）"

    def _parse_list_subs_output(
        self, output: str
    ) -> tuple[list[SubtitleTrack], list[SubtitleTrack]]:
        automatic: list[SubtitleTrack] = []
        manual: list[SubtitleTrack] = []
        section: str | None = None
        skip_header = False

        for raw in output.splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.startswith("["):
                continue
            if "Available automatic subtitles" in line:
                section = "automatic"
                skip_header = True
                continue
            if "Available subtitles" in line and "automatic" not in line:
                section = "manual"
                skip_header = True
                continue
            if skip_header and line.lower().startswith("language"):
                skip_header = False
                continue
            if skip_header:
                continue
            if section not in {"automatic", "manual"}:
                continue

            parts = line.split(None, 1)
            if not parts:
                continue
            language = parts[0]
            formats = []
            if len(parts) > 1:
                formats = [fmt.strip() for fmt in parts[1].split(",") if fmt.strip()]
            track = SubtitleTrack(
                language=language,
                formats=formats,
                is_automatic=(section == "automatic"),
            )
            if section == "automatic":
                automatic.append(track)
            else:
                manual.append(track)

        return automatic, manual

    def load_subtitle_text(
        self, job_id: UUID | None = None, subtitle_file: str | None = None
    ) -> str:
        target = self._resolve_subtitle_path(job_id, subtitle_file)
        try:
            return target.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"读取字幕文件失败：{exc}",
            ) from exc

    def _resolve_subtitle_path(
        self, job_id: UUID | None, subtitle_file: str | None
    ) -> Path:
        if subtitle_file:
            return self._from_public_path(subtitle_file)
        if job_id:
            matches = sorted(self._settings.subtitle_dir().glob(f"{job_id}.*"))
            if not matches:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="未找到对应 job_id 的字幕文件。",
                )
            return matches[0]
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少字幕文件引用。",
        )

    def _from_public_path(self, public_path: str) -> Path:
        prefix = "/storage/"
        if not public_path.startswith(prefix):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="字幕路径格式不正确，应以 /storage 开头。",
            )
        rel_posix = public_path[len(prefix) :]
        candidate = (self._settings.storage_root / Path(rel_posix)).resolve()
        storage_root = self._settings.storage_root.resolve()
        try:
            candidate.relative_to(storage_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="字幕路径超出允许的存储目录。",
            ) from exc
        if not candidate.exists():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="字幕文件不存在。"
            )
        return candidate

