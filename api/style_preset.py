from fastapi import APIRouter, Depends

from controllers.style_preset import style_preset_controller
from schemas.style_preset import (
    StylePresetCreate,
    StylePresetOut,
    StylePresetPatch,
    StylePresetUpdate,
)
from utils.page import QueryParams, get_list_params
from utils.response_format import PaginationResponse, ResponseSchema

router = APIRouter()


@router.post("", summary="创建风格", response_model=ResponseSchema[StylePresetOut])
async def create_style_preset(style_preset: StylePresetCreate):
    instance = await style_preset_controller.create(style_preset)
    return ResponseSchema(data=StylePresetOut.model_validate(instance))


@router.get(
    "", summary="获取风格列表", response_model=ResponseSchema[PaginationResponse[StylePresetOut]]
)
async def get_style_preset_list(params: QueryParams = Depends(get_list_params)):
    result = await style_preset_controller.list_with_storyboard_default(params)
    return ResponseSchema(data=result)


@router.get("/{style_id}", summary="获取风格详情", response_model=ResponseSchema[StylePresetOut])
async def get_style_preset(style_id: str):
    instance = await style_preset_controller.get_by_id_or_builtin(style_id)
    return ResponseSchema(data=StylePresetOut.model_validate(instance))


@router.put("/{style_id}", summary="全量更新风格", response_model=ResponseSchema[StylePresetOut])
async def update_style_preset(style_id: str, style_preset: StylePresetUpdate):
    instance = await style_preset_controller.update(style_id, style_preset)
    return ResponseSchema(data=StylePresetOut.model_validate(instance))


@router.patch("/{style_id}", summary="局部更新风格", response_model=ResponseSchema[StylePresetOut])
async def patch_style_preset(style_id: str, style_preset: StylePresetPatch):
    instance = await style_preset_controller.patch(style_id, style_preset)
    return ResponseSchema(data=StylePresetOut.model_validate(instance))


@router.delete("/{style_id}", summary="删除风格", response_model=ResponseSchema)
async def delete_style_preset(style_id: str):
    await style_preset_controller.remove(style_id)
    return ResponseSchema()
