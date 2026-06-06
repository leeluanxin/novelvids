from fastapi import HTTPException

from controllers.config import ai_model_config_controller
from controllers.style_preset import style_preset_controller
from models.ai_task import AiTask
from models.asset import Asset
from models.chapter import Chapter
from models.scene import Scene
from schemas.scene import SceneCreate, SceneEntity, SceneUpdate
from services.ai_task_executor import ai_task_executor
from services.storyboard.generator import build_storyboard_system_prompt
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum, TaskStatusEnum


class SceneController(CRUDBase[Scene, SceneCreate, SceneUpdate]):
    def __init__(self):
        super().__init__(model=Scene)

    async def _get_with_assets(self, instance_id: int) -> Scene:
        instance = await self.get(instance_id)
        await instance.fetch_related("assets")
        return instance

    async def create(self, obj_in: SceneCreate, **kwargs) -> Scene:
        instance = await super().create(obj_in, **kwargs)
        await instance.fetch_related("assets")
        return instance

    async def _perform_update(self, scene_id: int, obj_in: SceneUpdate, method: str) -> Scene:
        instance = await self.get(scene_id)

        if method == "patch":
            instance = await super().patch(instance, obj_in)
        else:
            instance = await super().update(instance, obj_in)

        await instance.fetch_related("assets")
        return instance

    async def update(self, scene_id: int, obj_in: SceneUpdate) -> Scene:
        return await self._perform_update(scene_id, obj_in, "update")

    async def patch(self, scene_id: int, obj_in: SceneUpdate) -> Scene:
        return await self._perform_update(scene_id, obj_in, "patch")

    async def remove(self, scene_id: int) -> None:
        instance = await self.get(scene_id)
        await super().remove(instance)

    async def _build_storyboard_prompt_context(self, chapter_id: int) -> tuple[Chapter, dict, list[SceneEntity]]:
        chapter = await Chapter.get(id=chapter_id).prefetch_related("novel")
        all_assets = await Asset.filter(novel_id=chapter.novel_id)
        assets = [a for a in all_assets if chapter.number in (a.source_chapters or [])]
        entities = [
            SceneEntity(
                name=asset.canonical_name,
                aliases=asset.aliases or [],
                description=asset.description or asset.base_traits or "",
            )
            for asset in assets
        ]
        storyboard_style = await style_preset_controller.resolve_storyboard_prompt(chapter.novel.style)
        return chapter, storyboard_style, entities

    async def build_prompt_preview(
        self,
        chapter_id: int,
        system_prompt_override: str | None = None,
        user_prompt_override: str | None = None,
    ) -> dict:
        chapter, storyboard_style, entities = await self._build_storyboard_prompt_context(chapter_id)
        system_prompt = build_storyboard_system_prompt(
            long_text=chapter.content,
            entities=entities,
            style_prompt=storyboard_style.get("storyboard_style_prompt"),
            system_prompt_override=system_prompt_override,
            user_prompt_override=user_prompt_override,
        )
        return {
            "system_prompt": system_prompt,
            "user_prompt": "",
            "storyboard_style": {
                "id": storyboard_style.get("storyboard_style_id"),
                "name": storyboard_style.get("storyboard_style_name"),
                "source": storyboard_style.get("storyboard_style_source"),
                "builtin_key": storyboard_style.get("storyboard_style_builtin_key"),
                "positive_prompt": storyboard_style.get("storyboard_style_prompt"),
            },
        }

    async def generate(
        self,
        chapter_id: int,
        system_prompt_override: str | None = None,
        user_prompt_override: str | None = None,
    ):
        chapter, storyboard_style, entities = await self._build_storyboard_prompt_context(chapter_id)

        config = await ai_model_config_controller.get_active(
            AiTaskTypeEnum.storyboard.value
        )

        await ai_task_executor.cleanup_stale_tasks(AiTaskTypeEnum.storyboard)

        active_tasks = await AiTask.filter(
            task_type=AiTaskTypeEnum.storyboard.value,
            status__in=[TaskStatusEnum.pending.value, TaskStatusEnum.running.value],
        )
        for task_item in active_tasks:
            if task_item.request_params.get("chapter_id") == chapter_id:
                raise HTTPException(
                    status_code=400,
                    detail=f"该章节已有进行中的分镜生成任务（{task_item.id}）",
                )

        actual_system_prompt = build_storyboard_system_prompt(
            long_text=chapter.content,
            entities=entities,
            style_prompt=storyboard_style.get("storyboard_style_prompt"),
            system_prompt_override=system_prompt_override,
            user_prompt_override=user_prompt_override,
        )
        actual_user_prompt = ""

        request_params = {
            "chapter_id": chapter.id,
            "base_url": config.base_url,
            "api_key": config.api_key,
            "model": config.model,
            "system_prompt_override": system_prompt_override,
            "user_prompt_override": user_prompt_override,
            "actual_system_prompt": actual_system_prompt,
            "actual_user_prompt": actual_user_prompt,
            **storyboard_style,
        }
        task = await ai_task_executor.submit(
            AiTaskTypeEnum.storyboard, request_params
        )
        return task


scene_controller = SceneController()
