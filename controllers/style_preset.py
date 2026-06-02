from fastapi import HTTPException

from models.style_preset import StylePreset
from schemas.style_preset import StylePresetCreate, StylePresetOut, StylePresetPatch, StylePresetUpdate
from utils.crud import CRUDBase
from utils.page import QueryParams


STORYBOARD_DEFAULT_BUILTIN_KEY = "storyboard-default"
STORYBOARD_DEFAULT_NAME = "分镜默认风格"
OLD_STORYBOARD_DEFAULT_PROMPT = (
    "动画摄影指导风格摘要：二维平涂卡通质感，简单镜头语言与扁平化构图，强调角色为中心、剧情信息清晰传递、"
    "明快柔和色调，黑体白色描边字幕、卡通化特效文字，沙雕搞笑荒诞氛围、短视频动画节奏"
)
STORYBOARD_DEFAULT_PROMPT = (
    "You are an elite Cinematographer (DP) and Sora 2 Prompt Engineering Expert.\n"
    "动画摄影指导风格摘要：二维平涂卡通质感，简单镜头语言与扁平化构图，强调角色为中心、剧情信息清晰传递、"
    "明快柔和色调，黑体白色描边字幕、卡通化特效文字，沙雕搞笑荒诞氛围、短视频动画节奏"
)


class StylePresetController(CRUDBase[StylePreset, StylePresetCreate, StylePresetUpdate]):
    def __init__(self):
        super().__init__(model=StylePreset)

    async def ensure_storyboard_default(self) -> StylePreset:
        instance = await StylePreset.get_or_none(builtin_key=STORYBOARD_DEFAULT_BUILTIN_KEY)
        if instance:
            if (instance.positive_prompt or "").strip() == OLD_STORYBOARD_DEFAULT_PROMPT:
                instance.positive_prompt = STORYBOARD_DEFAULT_PROMPT
                await instance.save()
            return instance
        return await StylePreset.create(
            name=STORYBOARD_DEFAULT_NAME,
            builtin_key=STORYBOARD_DEFAULT_BUILTIN_KEY,
            positive_prompt=STORYBOARD_DEFAULT_PROMPT,
            reference_image=None,
        )

    async def get_storyboard_default(self) -> StylePreset:
        return await self.ensure_storyboard_default()

    async def resolve_storyboard_prompt(self, novel_style: dict | None) -> dict:
        storyboard_default = await self.get_storyboard_default()
        resolved = {
            "storyboard_style_id": str(storyboard_default.id),
            "storyboard_style_name": storyboard_default.name,
            "storyboard_style_source": "builtin",
            "storyboard_style_builtin_key": STORYBOARD_DEFAULT_BUILTIN_KEY,
            "storyboard_style_prompt": storyboard_default.positive_prompt,
        }
        if not novel_style:
            return resolved

        style_source = novel_style.get("source")
        style_builtin_key = novel_style.get("builtin_key")
        style_prompt = (novel_style.get("positive_prompt") or "").strip()
        if not style_prompt:
            return resolved
        if style_source == "custom" or style_source == "local" or style_builtin_key == STORYBOARD_DEFAULT_BUILTIN_KEY:
            return {
                "storyboard_style_id": str(novel_style.get("id") or storyboard_default.id),
                "storyboard_style_name": novel_style.get("name") or storyboard_default.name,
                "storyboard_style_source": "builtin" if style_builtin_key == STORYBOARD_DEFAULT_BUILTIN_KEY else "custom",
                "storyboard_style_builtin_key": style_builtin_key,
                "storyboard_style_prompt": style_prompt,
            }
        return resolved

    async def list_with_storyboard_default(self, params: QueryParams) -> dict:
        storyboard_default = await self.ensure_storyboard_default()
        result = await super().list(
            params,
            StylePresetOut,
            search_fields=["name"],
            base_query=StylePreset.exclude(id=storyboard_default.id),
        )
        items = [StylePresetOut.model_validate(storyboard_default), *result["items"]]
        total = result["pagination"]["total"] + 1
        result["items"] = items
        result["pagination"]["total"] = total
        result["pagination"]["pages"] = (total + params.page_size - 1) // params.page_size if total > 0 else 0
        return result

    async def get_by_id_or_builtin(self, style_id: str | int) -> StylePreset:
        if str(style_id) == STORYBOARD_DEFAULT_BUILTIN_KEY:
            return await self.get_storyboard_default()
        return await self.get(int(style_id))

    async def update(self, style_id: str | int, obj_in: StylePresetUpdate) -> StylePreset:
        instance = await self.get_by_id_or_builtin(style_id)
        payload = obj_in.model_dump(exclude_unset=True, exclude={"id", "source", "builtin_key"})
        if instance.builtin_key == STORYBOARD_DEFAULT_BUILTIN_KEY:
            payload["builtin_key"] = STORYBOARD_DEFAULT_BUILTIN_KEY
        return await super().update(instance, payload)

    async def patch(self, style_id: str | int, obj_in: StylePresetPatch) -> StylePreset:
        instance = await self.get_by_id_or_builtin(style_id)
        payload = obj_in.model_dump(exclude_unset=True, exclude={"id", "source", "builtin_key"})
        if instance.builtin_key == STORYBOARD_DEFAULT_BUILTIN_KEY:
            payload["builtin_key"] = STORYBOARD_DEFAULT_BUILTIN_KEY
        return await super().patch(instance, payload)

    async def remove(self, style_id: str | int) -> None:
        instance = await self.get_by_id_or_builtin(style_id)
        if instance.builtin_key == STORYBOARD_DEFAULT_BUILTIN_KEY:
            raise HTTPException(status_code=400, detail="分镜默认风格不允许删除")
        await super().remove(instance)


style_preset_controller = StylePresetController()
