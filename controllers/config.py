from fastapi import HTTPException

from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigPatch, AiModelConfigUpdate
from utils.crud import CRUDBase
from utils.enums import AiTaskTypeEnum


class AiModelConfigController(CRUDBase[AiModelConfig, AiModelConfigCreate, AiModelConfigUpdate]):
    def __init__(self):
        super().__init__(model=AiModelConfig)

    @staticmethod
    def _normalize_transport_fields(obj_dict: dict, invocation_type: str) -> dict:
        if invocation_type == "cli":
            obj_dict["base_url"] = None
            obj_dict["api_key"] = None
        else:
            obj_dict["cli_command"] = None
        return obj_dict

    async def _ensure_single_active(self, task_type: int, exclude_id: int | None = None):
        """确保同 task_type 下只有一个 is_active=True。"""
        query = AiModelConfig.filter(task_type=task_type, is_active=True)
        if exclude_id is not None:
            query = query.exclude(id=exclude_id)
        await query.update(is_active=False)

    async def create(self, obj_in: AiModelConfigCreate, **kwargs) -> AiModelConfig:
        obj_dict = self._normalize_transport_fields(
            obj_in.model_dump(exclude_unset=True),
            obj_in.invocation_type,
        )
        instance = await super().create(obj_dict, **kwargs)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def update(self, config_id: int, obj_in: AiModelConfigUpdate) -> AiModelConfig:
        instance = await self.get(config_id)
        obj_dict = self._normalize_transport_fields(
            obj_in.model_dump(exclude_unset=True, exclude={"id"}),
            obj_in.invocation_type,
        )
        instance = await super().update(instance, obj_dict)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def patch(self, config_id: int, obj_in: AiModelConfigPatch) -> AiModelConfig:
        instance = await self.get(config_id)
        obj_dict = obj_in.model_dump(exclude_unset=True, exclude={"id"})
        invocation_type = obj_dict.get("invocation_type", instance.invocation_type)
        obj_dict = self._normalize_transport_fields(obj_dict, invocation_type)

        merged_data = {
            "task_type": instance.task_type,
            "name": instance.name,
            "invocation_type": instance.invocation_type,
            "base_url": instance.base_url,
            "api_key": instance.api_key,
            "model": instance.model,
            "cli_command": instance.cli_command,
            "is_active": instance.is_active,
            "concurrency": instance.concurrency,
        }
        merged_data.update(obj_dict)
        AiModelConfigUpdate.model_validate(merged_data)

        instance = await super().patch(instance, obj_dict)
        if instance.is_active:
            await self._ensure_single_active(instance.task_type, exclude_id=instance.id)
        return instance

    async def remove(self, config_id: int) -> None:
        instance = await self.get(config_id)
        await super().remove(instance)

    async def activate(self, config_id: int) -> AiModelConfig:
        """启用指定配置，同类型下其他配置自动禁用。"""
        instance = await self.get(config_id)
        await self._ensure_single_active(instance.task_type, exclude_id=config_id)
        instance.is_active = True
        await instance.save(update_fields=["is_active", "updated_at"])
        return instance

    async def get_active(self, task_type: int) -> AiModelConfig:
        """获取某任务类型当前启用的配置。"""
        config = await AiModelConfig.get_or_none(task_type=task_type, is_active=True)
        if config is None:
            try:
                name = AiTaskTypeEnum(task_type).nickname
            except ValueError:
                name = str(task_type)
            raise HTTPException(
                status_code=404,
                detail=f"请先在「配置」中为「{name}」启用一个模型",
            )
        return config


ai_model_config_controller = AiModelConfigController()
