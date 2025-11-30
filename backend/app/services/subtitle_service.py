from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Iterable
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from ..config import Settings
from ..schemas import (
    PromptPayload,
    SubtitleDownloadRequest,
    SubtitleDownloadResponse,
    SubtitleListRequest,
    SubtitleListResponse,
    SubtitlePlaylistDownloadResponse,
    SubtitleTrack,
)
from .prompt_service import PromptService


class SubtitleService:
    """Download and post-process YouTube subtitles using yt-dlp."""

    def __init__(self, settings: Settings, prompt_service: PromptService):
        self._settings = settings
        self._prompt_service = prompt_service
        # 播放列表下载进度跟踪：{job_id: progress_data}
        self._playlist_progress: dict[UUID, dict] = {}
        self._progress_lock = Lock()
        # 缓存文件路径
        self._cache_file = settings.storage_root / "subtitle_cache.json"
        self._cache_lock = Lock()
        # 加载缓存
        self._cache = self._load_cache()

    def download(self, payload: SubtitleDownloadRequest) -> SubtitleDownloadResponse | SubtitlePlaylistDownloadResponse:
        """下载字幕，如果是播放列表则下载所有视频的字幕。"""
        # 检测是否是播放列表
        if self._is_playlist_url(str(payload.video_url)):
            return self._download_playlist(payload)
        else:
            return self._download_single(payload)

    def _normalize_video_url(self, url: str) -> str:
        """规范化视频URL，提取核心视频ID，用于缓存键。"""
        try:
            parsed = urlparse(url)
            # 提取视频ID
            if "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc:
                if "youtu.be" in parsed.netloc:
                    # 短链接格式：https://youtu.be/VIDEO_ID
                    video_id = parsed.path.lstrip("/")
                else:
                    # 标准格式：https://www.youtube.com/watch?v=VIDEO_ID
                    query_params = parse_qs(parsed.query)
                    video_id = query_params.get("v", [None])[0]
                    if not video_id:
                        # 如果没有v参数，尝试从路径获取（如 /watch/VIDEO_ID）
                        path_parts = parsed.path.strip("/").split("/")
                        if len(path_parts) >= 2 and path_parts[0] == "watch":
                            video_id = path_parts[1]
                
                if video_id:
                    return f"https://www.youtube.com/watch?v={video_id}"
            # 如果不是YouTube URL，返回原始URL（去除查询参数中的list等）
            if parsed.query:
                # 移除list参数，只保留核心参数
                query_params = parse_qs(parsed.query)
                if "v" in query_params:
                    video_id = query_params["v"][0]
                    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?v={video_id}"
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        except Exception:
            # 如果解析失败，返回原始URL
            return url

    def _get_cache_key(self, payload: SubtitleDownloadRequest) -> str:
        """生成缓存键：规范化URL + 格式 + 语言。"""
        normalized_url = self._normalize_video_url(str(payload.video_url))
        languages = ",".join(sorted(payload.subtitle_languages))
        return f"{normalized_url}|{payload.subtitle_format}|{languages}|{payload.prefer_auto_subs}"

    def _load_cache(self) -> dict[str, dict]:
        """从文件加载缓存。"""
        if not self._cache_file.exists():
            return {}
        try:
            with self._cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        """保存缓存到文件。"""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_file.open("w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # 忽略保存错误

    def _get_cached_subtitle(self, payload: SubtitleDownloadRequest) -> SubtitleDownloadResponse | None:
        """检查缓存，如果存在且文件存在，返回缓存的结果。"""
        cache_key = self._get_cache_key(payload)
        
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if not cached:
                return None
            
            # 检查文件是否存在
            subtitle_path = self._settings.storage_root / cached["subtitle_file"].lstrip("/storage/")
            if not subtitle_path.exists():
                # 文件不存在，从缓存中移除
                del self._cache[cache_key]
                self._save_cache()
                return None
            
            # 返回缓存的结果
            return SubtitleDownloadResponse(
                job_id=UUID(cached["job_id"]),
                subtitle_format=payload.subtitle_format,
                subtitle_languages=payload.subtitle_languages,
                subtitle_file=cached["subtitle_file"],
                prompt_file=cached.get("prompt_file"),
                prompt_preview=cached.get("prompt_preview"),
                video_url=cached.get("video_url", str(payload.video_url)),
                video_title=cached.get("video_title"),
            )

    def _update_cache(self, payload: SubtitleDownloadRequest, response: SubtitleDownloadResponse) -> None:
        """更新缓存。"""
        cache_key = self._get_cache_key(payload)
        
        with self._cache_lock:
            self._cache[cache_key] = {
                "job_id": str(response.job_id),
                "subtitle_file": response.subtitle_file,
                "prompt_file": response.prompt_file,
                "prompt_preview": response.prompt_preview,
                "video_url": response.video_url,
                "video_title": response.video_title,
                "downloaded_at": datetime.utcnow().isoformat(),
            }
            self._save_cache()

    def _download_single(self, payload: SubtitleDownloadRequest) -> SubtitleDownloadResponse:
        """下载单个视频的字幕，先检查缓存。"""
        # 检查缓存
        cached = self._get_cached_subtitle(payload)
        if cached:
            return cached
        
        # 缓存未命中，执行下载
        job_id = uuid4()
        temp_dir = Path(tempfile.mkdtemp(prefix="yt_subs_"))

        try:
            video_title = self._get_video_title(str(payload.video_url))
            subtitle_file = self._run_yt_dlp(temp_dir, payload)
            final_subtitle_path = self._persist_subtitle(
                job_id, subtitle_file, payload, video_title
            )

            prompt_text = None
            prompt_file = None
            if payload.prompt is not None:
                prompt_text = self._generate_prompt(final_subtitle_path, payload.prompt)
                prompt_file = self._prompt_service.save_prompt(job_id, prompt_text)

            response = SubtitleDownloadResponse(
                job_id=job_id,
                subtitle_format=payload.subtitle_format,
                subtitle_languages=payload.subtitle_languages,
                subtitle_file=self._public_path(final_subtitle_path),
                prompt_file=self._public_path(prompt_file) if prompt_file else None,
                prompt_preview=prompt_text[:1000] if prompt_text else None,
                video_url=str(payload.video_url),
                video_title=video_title,
            )
            
            # 更新缓存
            self._update_cache(payload, response)
            
            return response
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _is_playlist_url(self, url: str) -> bool:
        """检测URL是否包含播放列表参数。"""
        return "list=" in url.lower() or "playlist" in url.lower()

    def _get_playlist_video_urls(self, playlist_url: str) -> list[str]:
        """获取播放列表中所有视频的URL。"""
        command = [
            self._settings.yt_dlp_binary,
            "--flat-playlist",
            "--print", "url",
            "--no-warnings",
            "--extractor-args", "youtube:player_client=default",
            "--sleep-interval", "1",
            "--max-sleep-interval", "3",
            playlist_url,
        ]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=120,  # 播放列表可能需要更长时间
            )
            urls = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
            # 过滤掉非URL的行
            urls = [url for url in urls if url.startswith("http")]
            return urls
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="yt-dlp 可执行文件未找到，请确保已安装并配置到 PATH。",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(
                status_code=status.HTTP_408_REQUEST_TIMEOUT,
                detail="获取播放列表超时，请稍后重试。",
            ) from exc
        except subprocess.CalledProcessError as exc:
            error_output = exc.stderr or exc.stdout or ""
            # 解析错误信息
            error_lower = error_output.lower()
            if "429" in error_output or "too many requests" in error_lower:
                http_status = status.HTTP_429_TOO_MANY_REQUESTS
                error_detail = (
                    "YouTube 返回 429 错误（请求过于频繁）。\n"
                    "建议等待几分钟后重试，或配置 yt-dlp cookies 文件。"
                )
            elif "403" in error_output or "forbidden" in error_lower:
                http_status = status.HTTP_403_FORBIDDEN
                error_detail = "YouTube 拒绝访问（403 Forbidden）。"
            else:
                http_status = status.HTTP_400_BAD_REQUEST
                error_detail = f"获取播放列表失败：{error_output[:500]}"
            
            raise HTTPException(
                status_code=http_status,
                detail=error_detail,
            ) from exc

    def _download_playlist(self, payload: SubtitleDownloadRequest) -> SubtitlePlaylistDownloadResponse:
        """下载播放列表中所有视频的字幕，使用线程池并发下载。"""
        playlist_url = str(payload.video_url)
        job_id = uuid4()
        
        # 获取播放列表中所有视频的URL
        video_urls = self._get_playlist_video_urls(playlist_url)
        
        if not video_urls:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="播放列表为空或无法获取视频列表。",
            )
        
        # 初始化进度跟踪
        with self._progress_lock:
            self._playlist_progress[job_id] = {
                "total_videos": len(video_urls),
                "completed": 0,
                "successful": 0,
                "failed": 0,
                "in_progress": 0,
                "status": "running",
                "current_videos": [],
                "results": [],
            }
        
        # 使用线程池并发下载，最多2个线程
        max_workers = 2
        results: list[SubtitleDownloadResponse] = []
        
        def download_video(video_url: str) -> SubtitleDownloadResponse | None:
            """下载单个视频的字幕（会检查缓存）。"""
            try:
                # 为每个视频创建新的请求payload
                video_payload = SubtitleDownloadRequest(
                    video_url=video_url,
                    subtitle_languages=payload.subtitle_languages,
                    subtitle_format=payload.subtitle_format,
                    prefer_auto_subs=payload.prefer_auto_subs,
                    output_filename=None,  # 播放列表中的视频不使用自定义文件名
                    prompt=payload.prompt,
                )
                
                # 先检查缓存
                cached = self._get_cached_subtitle(video_payload)
                is_cached = cached is not None
                
                if not is_cached:
                    # 更新进度：标记为进行中（仅当不是缓存时）
                    with self._progress_lock:
                        if job_id in self._playlist_progress:
                            self._playlist_progress[job_id]["in_progress"] += 1
                            self._playlist_progress[job_id]["current_videos"].append(video_url)
                
                # 下载或从缓存获取
                result = cached if is_cached else self._download_single(video_payload)
                
                # 更新进度：成功
                with self._progress_lock:
                    if job_id in self._playlist_progress:
                        progress = self._playlist_progress[job_id]
                        progress["completed"] += 1
                        progress["successful"] += 1
                        if not is_cached:
                            progress["in_progress"] -= 1
                            if video_url in progress["current_videos"]:
                                progress["current_videos"].remove(video_url)
                        progress["results"].append(result)
                
                return result
            except HTTPException as http_exc:
                # 如果是 429 错误，记录失败但继续
                if http_exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                    error_result = SubtitleDownloadResponse(
                        job_id=uuid4(),
                        subtitle_format=payload.subtitle_format,
                        subtitle_languages=payload.subtitle_languages,
                        subtitle_file="",
                        prompt_file=None,
                        prompt_preview=f"429 错误（请求过多），已跳过",
                        video_url=video_url,
                        video_title=None,
                    )
                else:
                    error_result = SubtitleDownloadResponse(
                        job_id=uuid4(),
                        subtitle_format=payload.subtitle_format,
                        subtitle_languages=payload.subtitle_languages,
                        subtitle_file="",
                        prompt_file=None,
                        prompt_preview=f"HTTP {http_exc.status_code}: {http_exc.detail[:200]}",
                        video_url=video_url,
                        video_title=None,
                    )
                
                # 更新进度：失败
                with self._progress_lock:
                    if job_id in self._playlist_progress:
                        progress = self._playlist_progress[job_id]
                        progress["completed"] += 1
                        progress["failed"] += 1
                        progress["in_progress"] -= 1
                        if video_url in progress["current_videos"]:
                            progress["current_videos"].remove(video_url)
                        progress["results"].append(error_result)
                
                return error_result
            except Exception as exc:
                # 记录失败但继续处理其他视频
                error_result = SubtitleDownloadResponse(
                    job_id=uuid4(),
                    subtitle_format=payload.subtitle_format,
                    subtitle_languages=payload.subtitle_languages,
                    subtitle_file="",
                    prompt_file=None,
                    prompt_preview=f"下载失败: {str(exc)[:200]}",
                    video_url=video_url,
                    video_title=None,
                )
                
                # 更新进度：失败
                with self._progress_lock:
                    if job_id in self._playlist_progress:
                        progress = self._playlist_progress[job_id]
                        progress["completed"] += 1
                        progress["failed"] += 1
                        progress["in_progress"] -= 1
                        if video_url in progress["current_videos"]:
                            progress["current_videos"].remove(video_url)
                        progress["results"].append(error_result)
                
                return error_result
        
        # 使用线程池并发下载
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_url = {
                executor.submit(download_video, video_url): video_url
                for video_url in video_urls
            }
            
            # 等待所有任务完成
            for future in as_completed(future_to_url):
                result = future.result()
                if result:
                    results.append(result)
        
        # 更新最终状态
        with self._progress_lock:
            if job_id in self._playlist_progress:
                progress = self._playlist_progress[job_id]
                progress["status"] = "completed"
                progress["in_progress"] = 0
                progress["current_videos"] = []
        
        return SubtitlePlaylistDownloadResponse(
            job_id=job_id,
            total_videos=len(video_urls),
            successful=sum(1 for r in results if r.subtitle_file),
            failed=sum(1 for r in results if not r.subtitle_file),
            completed=len(results),
            in_progress=0,
            results=results,
            status="completed",
        )
    
    def get_playlist_progress(self, job_id: UUID) -> dict | None:
        """获取播放列表下载进度。"""
        with self._progress_lock:
            return self._playlist_progress.get(job_id)

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
            # 解析错误信息，返回更合适的 HTTP 状态码
            error_output = exc.stderr or exc.stdout or ""
            http_status, error_detail = self._parse_yt_dlp_error(error_output, payload)
            raise HTTPException(
                status_code=http_status,
                detail=error_detail,
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
            # 添加参数以减少 429 错误
            "--extractor-args", "youtube:player_client=default",  # 避免需要 JS runtime
            "--sleep-interval", "1",  # 请求间隔 1 秒
            "--max-sleep-interval", "3",  # 最大间隔 3 秒
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
            # 解析错误信息，返回更合适的 HTTP 状态码
            error_output = exc.stderr or exc.stdout or ""
            http_status, error_detail = self._parse_yt_dlp_error(error_output, payload)
            raise HTTPException(
                status_code=http_status,
                detail=error_detail,
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

    def _parse_yt_dlp_error(
        self, error_output: str, payload: SubtitleDownloadRequest
    ) -> tuple[int, str]:
        """解析 yt-dlp 错误输出，返回合适的 HTTP 状态码和错误信息。"""
        languages = "、".join(payload.subtitle_languages)
        error_lower = error_output.lower()
        
        # HTTP 429: Too Many Requests
        if "429" in error_output or "too many requests" in error_lower:
            return (
                status.HTTP_429_TOO_MANY_REQUESTS,
                (
                    f"YouTube 返回 429 错误（请求过于频繁）。\n"
                    f"建议：\n"
                    f"1. 等待几分钟后重试\n"
                    f"2. 如果使用播放列表，请减少每次请求的视频数量\n"
                    f"3. 配置 yt-dlp cookies 文件（参考：https://github.com/yt-dlp/yt-dlp#cookies）\n"
                    f"4. 使用代理或 VPN\n"
                    f"（请求语言：{languages}，格式：{payload.subtitle_format}）"
                ),
            )
        
        # HTTP 403: Forbidden
        if "403" in error_output or "forbidden" in error_lower:
            return (
                status.HTTP_403_FORBIDDEN,
                (
                    f"YouTube 拒绝访问（403 Forbidden）。\n"
                    f"建议：\n"
                    f"1. 检查视频是否可公开访问\n"
                    f"2. 配置 yt-dlp cookies 文件\n"
                    f"3. 使用代理或 VPN\n"
                    f"（请求语言：{languages}，格式：{payload.subtitle_format}）"
                ),
            )
        
        # HTTP 404: Not Found
        if "404" in error_output or "not found" in error_lower or "no subtitles" in error_lower:
            return (
                status.HTTP_404_NOT_FOUND,
                (
                    f"未找到字幕。\n"
                    f"可能原因：\n"
                    f"1. 视频没有所请求语言（{languages}）的字幕\n"
                    f"2. 视频不存在或已被删除\n"
                    f"建议：尝试使用 `--list-subs` 查看可用字幕，或使用自动生成字幕\n"
                    f"（格式：{payload.subtitle_format}）"
                ),
            )
        
        # 其他错误，返回 400
        return (
            status.HTTP_400_BAD_REQUEST,
            f"yt-dlp 执行失败：{error_output[:500]}\n（请求语言：{languages}，格式：{payload.subtitle_format}）",
        )

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

