"""视频合并服务 - 使用 FFmpeg concat filter 合并多个视频。"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import TYPE_CHECKING

from config import settings

if TYPE_CHECKING:
    from models.video import Video

logger = logging.getLogger(__name__)


def _resolve_ffmpeg_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary:
        return binary

    candidates = [
        os.path.join("/opt/homebrew/bin", name),
        os.path.join("/usr/local/bin", name),
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    raise RuntimeError(f"未找到 {name}，请先安装 FFmpeg 并确保 {name} 可执行")


def _check_audio_stream(video_path: str) -> bool:
    """检查视频文件是否包含音频流。"""
    try:
        ffprobe_bin = _resolve_ffmpeg_binary("ffprobe")
    except RuntimeError:
        return False

    cmd = [ffprobe_bin, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_type', '-of', 'default=noprint_wrappers=1', video_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return bool(result.stdout.strip())
    except Exception:
        return False


class VideoMerger:
    """视频合并器 - 将多个视频按顺序合并为一个。"""

    def __init__(self):
        self.output_dir = os.path.join(settings.MEDIA_PATH, "videos", "merged")
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_video_path(self, video_id: int) -> str | None:
        """获取视频文件的本地路径。

        Args:
            video_id: 视频 ID

        Returns:
            本地文件路径，如果文件不存在返回 None
        """
        video_path = os.path.join(settings.MEDIA_PATH, "videos", f"{video_id}.mp4")
        if os.path.exists(video_path):
            return video_path
        return None

    def merge_videos(
        self,
        videos: list[Video],
        chapter_id: int,
        output_filename: str | None = None
    ) -> str:
        """合并多个视频为一个文件。

        Args:
            videos: 要合并的视频列表（按顺序）
            chapter_id: 章节 ID
            output_filename: 输出文件名，默认为 "chapter_{chapter_id}_merged.mp4"

        Returns:
            合并后的视频 URL (如 /media/videos/merged/xxx.mp4)

        Raises:
            ValueError: 视频数量不足或文件不存在
            RuntimeError: FFmpeg 执行失败
        """
        if len(videos) < 1:
            raise ValueError("至少需要1个视频才能合并")

        if len(videos) == 1:
            video = videos[0]
            path = self._get_video_path(video.id)
            if not path:
                raise ValueError(f"视频文件不存在: video_id={video.id}")

            if output_filename is None:
                output_filename = f"chapter_{chapter_id}_merged.mp4"

            output_path = os.path.abspath(os.path.join(self.output_dir, output_filename))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(path, "rb") as src, open(output_path, "wb") as dst:
                dst.write(src.read())
            return f"/media/videos/merged/{output_filename}"

        ffmpeg_bin = _resolve_ffmpeg_binary("ffmpeg")

        # 收集所有视频文件路径，并检测是否有音频
        video_paths = []
        has_audio_list = []
        for video in videos:
            path = self._get_video_path(video.id)
            if not path:
                raise ValueError(f"视频文件不存在: video_id={video.id}")
            # Windows 路径处理：转换为绝对路径并规范化
            abs_path = os.path.abspath(path)
            video_paths.append(abs_path)
            # 检测是否有音频流
            has_audio = _check_audio_stream(abs_path)
            has_audio_list.append(has_audio)

        # 生成输出文件名
        if output_filename is None:
            output_filename = f"chapter_{chapter_id}_merged.mp4"

        output_path = os.path.abspath(os.path.join(self.output_dir, output_filename))

        # 构建 FFmpeg 命令 - 根据是否有音频决定 filter
        input_args = []
        filter_parts = []

        if all(has_audio_list):
            # 所有视频都有音频 - 标准模式
            for i, path in enumerate(video_paths):
                input_args.extend(['-i', path])
                filter_parts.append(f'[{i}:v][{i}:a]')
            filter_complex = ''.join(filter_parts) + f'concat=n={len(video_paths)}:v=1:a=1[outv][outa]'
            cmd = [
                ffmpeg_bin, '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-map', '[outa]',
                output_path
            ]
        elif not any(has_audio_list):
            # 所有视频都没有音频 - 纯视频合并
            for i, path in enumerate(video_paths):
                input_args.extend(['-i', path])
                filter_parts.append(f'[{i}:v]')
            filter_complex = ''.join(filter_parts) + f'concat=n={len(video_paths)}:v=1:a=0[v]'
            cmd = [
                ffmpeg_bin, '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[v]',
                output_path
            ]
        else:
            # 混合情况 - 添加静音音频流
            for i, (path, has_audio) in enumerate(video_paths):
                input_args.extend(['-i', path])
                if has_audio:
                    filter_parts.append(f'[{i}:v][{i}:a]')
                else:
                    # 没有音频的视频，用 anullsrc 添加静音
                    filter_parts.append(f'[{i}:v]')
                    filter_parts.append(f'anullsrc=sample_rate=44100[aud{i}]')
                    filter_parts.append(f'[{i}:v][aud{i}]')

            filter_complex = ''.join(filter_parts) + f'concat=n={len(video_paths)}:v=1:a=1[outv][outa]'
            cmd = [
                ffmpeg_bin, '-y'
            ] + input_args + [
                '-filter_complex', filter_complex,
                '-map', '[outv]',
                '-map', '[outa]',
                output_path
            ]

        # Windows 命令行长度限制检查 (约 8000 字符安全边界)
        cmd_str = ' '.join(f'"{arg}"' if ' ' in arg else arg for arg in cmd)
        if len(cmd_str) > 8000:
            raise RuntimeError(f"视频数量过多（{len(video_paths)}个），命令行超过Windows限制，请分批合并")

        # 执行合并
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace'
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg returncode: {result.returncode}")
            logger.error(f"FFmpeg stderr: {result.stderr}")
            logger.error(f"FFmpeg stdout: {result.stdout}")
            raise RuntimeError(f"视频合并失败: {result.stderr}")

        # 验证输出文件是否真的创建成功
        if not os.path.exists(output_path):
            logger.error(f"Output file not created: {output_path}")
            logger.error(f"FFmpeg stdout: {result.stdout}")
            logger.error(f"FFmpeg stderr: {result.stderr}")
            raise RuntimeError(f"视频合并失败：输出文件未创建")

        return f"/media/videos/merged/{output_filename}"


video_merger = VideoMerger()
