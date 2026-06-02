"""视频控制器 - 生成、查询、CRUD。"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from controllers.config import ai_model_config_controller
from config import settings
from models.scene import Scene
from models.video import Video
from schemas.video import VideoGenerateRequest
from services.video import get_generator
from services.video.asset_resolver import resolve_assets
from services.video.merge import video_merger
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum
from utils.page import QueryBuilder, QueryParams

logger = logging.getLogger(__name__)


async def _download_video(remote_url: str, video_id: int) -> str:
    """将远程视频下载到本地 MEDIA_PATH/videos/ 目录，返回可访问的 /media/ 路径。"""
    video_dir = os.path.join(settings.MEDIA_PATH, "videos")
    os.makedirs(video_dir, exist_ok=True)

    filename = f"{video_id}.mp4"
    local_path = os.path.join(video_dir, filename)

    logger.info("Video download start: video_id=%s, url=%s", video_id, remote_url[:120])
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("GET", remote_url) as resp:
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=8192):
                    f.write(chunk)

    media_url = f"/media/videos/{filename}"
    logger.info("Video downloaded: video_id=%s -> %s", video_id, media_url)
    return media_url


class VideoController(CRUDBase[Video, dict, dict]):
    def __init__(self):
        super().__init__(model=Video)

    @staticmethod
    def _should_refresh_remote_status(video: Video | None) -> bool:
        return bool(
            video
            and video.external_task_id
            and video.status not in (
                TaskStatusEnum.completed.value,
                TaskStatusEnum.failed.value,
                TaskStatusEnum.cancelled.value,
            )
        )

    async def _refresh_video_status_on_read(self, video: Video | None) -> Video | None:
        if not self._should_refresh_remote_status(video):
            return video

        try:
            return await self.query_status(video.id)
        except Exception as exc:
            logger.warning(
                "Video read refresh failed: video_id=%s, task_id=%s, error=%s",
                video.id,
                video.external_task_id,
                exc,
            )
            return video

    async def generate(self, req: VideoGenerateRequest) -> Video:
        """提交视频生成请求。

        1. 获取 Scene (含关联 chapter -> novel)
        2. 根据 model_type 查找启用的 AiModelConfig
        3. 解析 prompt 中的 @资产昵称 -> subjects
        4. 调用生成器 submit()
        5. 创建 Video 记录 (status=pending)
        """
        scene = await Scene.get_or_none(id=req.scene_id)
        if not scene:
            raise HTTPException(404, detail=f"分镜 {req.scene_id} 不存在")

        # 获取 novel_id (通过 chapter)
        await scene.fetch_related("chapter")
        novel_id = scene.chapter.novel_id

        # 查找启用的视频配置
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)

        # 解析 @资产昵称
        prompt = scene.prompt or ""
        subjects = await resolve_assets(prompt, novel_id)
        logger.info(
            "Video resolve_assets: scene_id=%s, novel_id=%s, prompt_len=%d, subjects=%s",
            scene.id, novel_id, len(prompt),
            [(s["name"], len(s.get("images", []))) for s in subjects],
        )

        # 获取生成器并提交
        generator = get_generator(req.model_type, config)
        duration = scene.duration or 6.0
        external_task_id = await generator.submit(
            prompt=prompt,
            subjects=subjects if subjects else None,
            duration=duration,
        )

        # 创建 Video 记录
        video = await Video.create(
            scene_id=scene.id,
            model_type=req.model_type,
            external_task_id=external_task_id,
            status=TaskStatusEnum.pending.value,
        )
        logger.info(
            "Video generate: video_id=%s, scene_id=%s, task_id=%s",
            video.id, scene.id, external_task_id,
        )
        return video

    async def query_status(self, video_id: int) -> Video:
        """查询视频生成状态，如有变化则更新 Video 记录。"""
        video = await self.get(video_id)

        # 已完成或已失败的不再查询
        if video.status in (
            TaskStatusEnum.completed.value,
            TaskStatusEnum.failed.value,
        ):
            return video

        if not video.external_task_id:
            raise HTTPException(400, detail="该视频无外部任务ID，无法查询")

        # 查找启用的视频配置
        config = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)

        generator = get_generator(video.model_type, config)
        result = await generator.query(video.external_task_id)
        logger.info(
            "Video query result: video_id=%s, status=%s, url=%s, metadata=%s",
            video_id, result.get("status"), result.get("url"), result.get("metadata"),
        )

        # 更新 Video 记录
        new_status = result["status"].value
        update_fields = ["status"]

        video.status = new_status

        # 视频完成时，下载到本地替换临时 URL
        remote_url = result.get("url")
        if remote_url:
            try:
                media_url = await _download_video(remote_url, video.id)
                video.url = media_url
                update_fields.append("url")
            except Exception as e:
                logger.error("Video download failed: video_id=%s, error=%s", video_id, e)
                video.metadata = {**(video.metadata or {}), "error": f"视频下载失败: {e}"}
                update_fields.append("metadata")
        elif new_status == TaskStatusEnum.completed.value:
            logger.warning("Video completed but no URL: video_id=%s, result=%s", video_id, result)

        if result.get("metadata"):
            video.metadata = {**(video.metadata or {}), **result["metadata"]}
            if "metadata" not in update_fields:
                update_fields.append("metadata")

        await video.save(update_fields=update_fields)
        return video

    async def list(
        self,
        params: QueryParams,
        response_model: type[BaseModel],
        search_fields: list[str] | None = None,
        base_query=None,
    ) -> dict[str, dict[str, int | Any] | Any]:
        query = base_query if base_query is not None else self.model.all()
        query = await QueryBuilder.apply_filters(query, self.model, params.filters or {})
        query = await QueryBuilder.apply_search(query, params.search, search_fields or [])

        total = await query.count()
        query = await QueryBuilder.apply_sorting(query, params.sort)
        paginated_query = await QueryBuilder.apply_pagination(query, params.page, params.page_size)
        items = await paginated_query

        refreshed_items = []
        for item in items:
            refreshed_item = await self._refresh_video_status_on_read(item)
            if refreshed_item is not None:
                refreshed_items.append(refreshed_item)

        pages = (total + params.page_size - 1) // params.page_size if total > 0 else 0

        return {
            "items": [response_model.model_validate(item) for item in refreshed_items],
            "pagination": {
                "total": total,
                "page": params.page,
                "page_size": params.page_size,
                "pages": pages,
            },
        }

    async def remove(self, video_id: int) -> None:
        instance = await self.get(video_id)
        await super().remove(instance)

    async def _get_latest_completed_scene_video(self, scene_id: int) -> Video | None:
        latest_video = await Video.filter(scene_id=scene_id).order_by("-id").first()
        refreshed_video = await self._refresh_video_status_on_read(latest_video)
        if refreshed_video and refreshed_video.status == TaskStatusEnum.completed.value:
            return refreshed_video

        return await Video.filter(
            scene_id=scene_id,
            status=TaskStatusEnum.completed.value,
        ).order_by("-id").first()

    async def get_chapter_videos(self, chapter_id: int) -> list[dict]:
        """获取章节下所有分镜的视频，按 scene.sequence 排序。

        Returns:
            [
                {
                    "scene_id": 1,
                    "sequence": 1,
                    "description": "镜头描述",
                    "duration": 4.0,
                    "video": {
                        "id": 10,
                        "url": "/media/videos/10.mp4",
                        "status": 3,
                        "model_type": 4
                    } | None
                },
                ...
            ]
        """
        # 查询该章节的所有分镜，按 sequence 排序
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")

        result = []
        for scene in scenes:
            # 获取该分镜最新的已完成视频
            video = await self._get_latest_completed_scene_video(scene.id)

            item = {
                "scene_id": scene.id,
                "sequence": scene.sequence,
                "description": scene.description,
                "duration": scene.duration,
                "video": None
            }

            if video:
                item["video"] = {
                    "id": video.id,
                    "url": video.url,
                    "status": video.status,
                    "model_type": video.model_type
                }

            result.append(item)

        return result

    async def get_novel_videos(self, novel_id: int) -> list[dict]:
        """获取小说下所有视频。"""
        videos = await Video.filter(
            scene__chapter__novel_id=novel_id
        ).order_by("-created_at")

        refreshed_videos: list[Video] = []
        for video in videos:
            refreshed_video = await self._refresh_video_status_on_read(video)
            if refreshed_video is not None:
                refreshed_videos.append(refreshed_video)

        return [
            {
                "id": video.id,
                "url": video.url,
                "status": video.status,
                "model_type": video.model_type,
            }
            for video in refreshed_videos
        ]

    async def _collect_chapter_merge_videos(self, chapter_id: int) -> tuple[list[Video], float, list[int]]:
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")

        videos_to_merge: list[Video] = []
        total_duration = 0.0
        missing_scenes: list[int] = []

        for scene in scenes:
            video = await self._get_latest_completed_scene_video(scene.id)
            if video:
                videos_to_merge.append(video)
                total_duration += scene.duration or 0
            else:
                missing_scenes.append(scene.sequence)

        return videos_to_merge, total_duration, missing_scenes

    async def merge_chapter_videos(self, chapter_id: int) -> dict:
        """合并章节下所有已完成的视频。

        Args:
            chapter_id: 章节 ID

        Returns:
            {
                "chapter_id": 123,
                "merged_url": "/media/videos/merged/chapter_123_merged.mp4",
                "video_count": 5,
                "total_duration": 45.0
            }
        """
        videos_to_merge, total_duration, missing_scenes = await self._collect_chapter_merge_videos(chapter_id)

        if missing_scenes:
            raise HTTPException(
                400,
                detail=f"以下分镜尚未生成视频，无法合并：分镜 #{', '.join(map(str, missing_scenes))}"
            )

        try:
            merged_url = video_merger.merge_videos(videos_to_merge, chapter_id)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(500, detail=str(e))

        return {
            "chapter_id": chapter_id,
            "merged_url": merged_url,
            "video_count": len(videos_to_merge),
            "total_duration": round(total_duration, 1)
        }

    async def merge_available_chapter_videos(self, chapter_id: int) -> dict:
        videos_to_merge, total_duration, _ = await self._collect_chapter_merge_videos(chapter_id)

        if not videos_to_merge:
            raise HTTPException(400, detail="当前没有可用于测试合成的视频")

        try:
            merged_url = video_merger.merge_videos(videos_to_merge, chapter_id)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(500, detail=str(e))

        return {
            "chapter_id": chapter_id,
            "merged_url": merged_url,
            "video_count": len(videos_to_merge),
            "total_duration": round(total_duration, 1)
        }

    async def get_merged_video(self, chapter_id: int) -> dict | None:
        """查询章节是否已有合并好的视频。

        Args:
            chapter_id: 章节 ID

        Returns:
            如果存在返回合并信息，否则返回 None
        """
        merged_dir = os.path.join(settings.MEDIA_PATH, "videos", "merged")
        filename = f"chapter_{chapter_id}_merged.mp4"
        file_path = os.path.join(merged_dir, filename)

        if not os.path.exists(file_path):
            return None

        # 获取该章节的视频统计
        scenes = await Scene.filter(chapter_id=chapter_id).order_by("sequence")
        video_count = 0
        total_duration = 0.0

        for scene in scenes:
            video = await self._get_latest_completed_scene_video(scene.id)
            if video:
                video_count += 1
                total_duration += scene.duration or 0

        return {
            "chapter_id": chapter_id,
            "merged_url": f"/media/videos/merged/{filename}",
            "video_count": video_count,
            "total_duration": round(total_duration, 1)
        }


video_controller = VideoController()
