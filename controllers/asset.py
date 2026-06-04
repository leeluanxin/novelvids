from typing import Any, Optional, Type

from fastapi import HTTPException
from pydantic import BaseModel
from tortoise.queryset import QuerySet

from controllers.config import ai_model_config_controller
from models.ai_task import AiTask
from models.asset import Asset
from schemas.asset import AssetCreate, AssetPatch, AssetUpdate
from services.ai_task_executor import ai_task_executor
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, AssetTypeEnum, TaskStatusEnum
from utils.page import QueryParams

DEFAULT_GENERAL_ASSET_NAME = "旁白声音"


class AssetController(CRUDBase[Asset, AssetCreate, AssetUpdate]):
    def __init__(self):
        super().__init__(model=Asset)

    async def _ensure_general_asset(self, novel_id: int) -> Asset:
        asset, _ = await Asset.get_or_create(
            novel_id=novel_id,
            asset_type=AssetTypeEnum.general.value,
            canonical_name=DEFAULT_GENERAL_ASSET_NAME,
            defaults={
                "aliases": [],
                "description": "默认旁白声音资产",
                "base_traits": None,
                "is_global": True,
            },
        )
        return asset

    async def list(
        self,
        params: "QueryParams",
        response_model: Type[BaseModel],
        search_fields: Optional[list[str]] = None,
        base_query: Optional["QuerySet"] = None,
    ) -> dict[str, dict[str, int | Any] | Any]:
        if base_query is None:
            base_query = self.model.all()

        novel_id = None
        if params.filters and "novel_id" in params.filters:
            try:
                novel_id = int(params.filters["novel_id"])
            except (ValueError, TypeError):
                novel_id = None
        if novel_id is not None:
            await self._ensure_general_asset(novel_id)

        if params.filters and "chapter_id" in params.filters:
            try:
                chapter_id = int(params.filters.pop("chapter_id"))
                all_assets = await self.model.all().values("id", "source_chapters")
                matching_ids = [
                    a["id"] for a in all_assets
                    if chapter_id in (a["source_chapters"] or [])
                ]
                base_query = base_query.filter(id__in=matching_ids)
            except (ValueError, TypeError):
                pass

        return await super().list(params, response_model, search_fields, base_query)

    async def update(self, asset_id: int, obj_in: AssetUpdate) -> Asset:
        instance = await self.get(asset_id)
        return await super().update(instance, obj_in)

    async def patch(self, asset_id: int, obj_in: AssetPatch) -> Asset:
        instance = await self.get(asset_id)
        return await super().patch(instance, obj_in)

    async def remove(self, asset_id: int) -> None:
        instance = await self.get(asset_id)
        await super().remove(instance)

    async def reference(self, asset_id: int) -> AiTask:
        asset = await self.get(asset_id)
        await asset.fetch_related("novel")
        style = asset.novel.style if getattr(asset, "novel", None) else None

        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.reference_image.value
        )
        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.reference_image)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.reference_image.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for task in active_tasks:
            if task.request_params.get("asset_id") == asset_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"该资产已有进行中的生成任务（{task.id}）",
                )

        request_params = {
            "asset_id": asset.id,
            "novel_id": asset.novel_id,
            "style": style,
            "invocation_type": config.invocation_type,
            "cli_command": config.cli_command,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
        }
        return await ai_task_executor.submit(
            AiTaskTypeEnum.reference_image,
            request_params,
        )


asset_controller = AssetController()
