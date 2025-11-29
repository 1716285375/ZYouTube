from __future__ import annotations

import re
import secrets
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
            video_title = self._get_video_title(payload.video_url)
            subtitle_file = self._run_yt_dlp(temp_dir, payload)
            final_subtitle_path = self._persist_subtitle(
                job_id, subtitle_file, payload, video_title
            )

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

    def _get_video_title(self, video_url: str) -> str | None:
        """获取视频标题，用于生成文件名。"""
        command = [
            self._settings.yt_dlp_binary,
            "--print", "title",
            "--no-warnings",
            str(video_url),
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=30,
            )
            title = (completed.stdout or "").strip()
            return title if title else None
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            return None

    def _sanitize_filename(self, filename: str, max_length: int = 200) -> str:
        """清理文件名，移除非法字符并限制长度。"""
        # 移除或替换非法文件名字符
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # 移除控制字符
        filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
        # 移除首尾空格和点
        filename = filename.strip(' .')
        # 限制长度
        if len(filename) > max_length:
            filename = filename[:max_length]
        # 如果清理后为空，返回默认值
        if not filename:
            filename = "video"
        return filename

    def _generate_random_suffix(self, length: int = 8) -> str:
        """生成随机字符串后缀。"""
        return secrets.token_urlsafe(length)[:length]

    def _extract_text_from_subtitle(self, subtitle_path: Path) -> str:
        """从字幕文件中提取纯文本内容。"""
        content = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        format_ext = subtitle_path.suffix.lower()
        
        if format_ext == ".srt":
            # SRT格式：移除序号和时间戳，只保留文本
            lines = []
            for line in content.splitlines():
                line = line.strip()
                # 跳过空行、序号行和时间戳行
                if not line or line.isdigit() or "-->" in line:
                    continue
                # 跳过HTML标签
                line = re.sub(r'<[^>]+>', '', line)
                if line:
                    lines.append(line)
            return "\n".join(lines)
        elif format_ext == ".vtt":
            # VTT格式：移除WEBVTT头部、时间戳和样式
            lines = []
            skip_next = False
            for line in content.splitlines():
                line = line.strip()
                # 跳过WEBVTT头部
                if line.upper() == "WEBVTT" or line.startswith("WEBVTT"):
                    continue
                # 跳过时间戳行
                if "-->" in line:
                    skip_next = True
                    continue
                # 跳过样式块
                if line.startswith("STYLE") or line.startswith("NOTE"):
                    skip_next = True
                    continue
                if skip_next and not line:
                    skip_next = False
                    continue
                if skip_next:
                    continue
                # 移除HTML标签
                line = re.sub(r'<[^>]+>', '', line)
                if line:
                    lines.append(line)
            return "\n".join(lines)
        else:
            # 其他格式：尝试简单清理
            # 移除HTML标签
            content = re.sub(r'<[^>]+>', '', content)
            return content.strip()

    def _get_format_subdir(self, file_format: str) -> str:
        """根据文件格式返回对应的子目录名。"""
        format_lower = file_format.lower()
        # 常见字幕格式映射
        format_map = {
            "srt": "srt",
            "vtt": "vtt",
            "ass": "ass",
            "ssa": "ssa",
            "lrc": "lrc",
            "txt": "txt",
        }
        return format_map.get(format_lower, format_lower)

    def _persist_subtitle(
        self,
        job_id: UUID,
        subtitle_path: Path,
        payload: SubtitleDownloadRequest,
        video_title: str | None = None,
    ) -> Path:
        if payload.output_filename:
            # 如果用户提供了自定义文件名，优先使用
            output_name = payload.output_filename
            # 从自定义文件名中提取基础名称（不含扩展名）
            base_name = Path(output_name).stem
            random_suffix = self._generate_random_suffix()
        elif video_title:
            # 使用视频标题 + 随机字符
            sanitized_title = self._sanitize_filename(video_title)
            random_suffix = self._generate_random_suffix()
            base_name = f"{sanitized_title}_{random_suffix}"
            output_name = f"{base_name}.{payload.subtitle_format}"
        else:
            # 回退到使用 job_id
            base_name = str(job_id)
            random_suffix = self._generate_random_suffix()
            output_name = f"{base_name}.{payload.subtitle_format}"
        
        # 根据格式确定子目录
        format_subdir = self._get_format_subdir(payload.subtitle_format)
        format_dir = self._settings.subtitle_dir() / format_subdir
        final_path = format_dir / output_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(subtitle_path), final_path)
        
        # 自动生成txt文本副本，保存到txt子目录
        try:
            text_content = self._extract_text_from_subtitle(final_path)
            # 生成txt文件名：使用相同的基础名称和随机后缀
            if payload.output_filename:
                # 自定义文件名：使用基础名称 + 随机后缀
                txt_filename = f"{base_name}_{random_suffix}.txt"
            elif video_title:
                # 视频标题：base_name已经包含了随机后缀
                txt_filename = f"{base_name}.txt"
            else:
                # job_id：添加随机后缀
                txt_filename = f"{base_name}_{random_suffix}.txt"
            # txt文件保存到txt子目录
            txt_dir = self._settings.subtitle_dir() / "txt"
            txt_path = txt_dir / txt_filename
            txt_dir.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(text_content, encoding="utf-8")
        except Exception:
            # 如果转换失败，不影响主流程，静默忽略
            pass
        
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
            # 递归搜索所有子目录，因为文件现在按格式保存在不同子目录中
            matches = sorted(self._settings.subtitle_dir().rglob(f"{job_id}.*"))
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

