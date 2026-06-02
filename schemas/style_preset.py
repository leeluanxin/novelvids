from typing import Literal, Optional

from pydantic import ConfigDict, Field, field_validator

from schemas._base import BaseResponse
from schemas.novel import StyleBinding


class StylePresetProperties(StyleBinding):
    source: Literal["builtin", "custom"] = Field("custom", description="风格来源")
    id: Optional[str] = Field(None, description="风格ID")
    name: Optional[str] = Field(None, description="风格名称", max_length=255)
    positive_prompt: Optional[str] = Field(None, description="正向提示词")
    reference_image: Optional[str] = Field(None, description="参考图URL", max_length=500)
    builtin_key: Optional[Literal["storyboard-default"]] = Field(None, description="内置风格标识")

    @field_validator("source", mode="before")
    @classmethod
    def normalize_source(cls, value):
        if value == "local" or value is None:
            return "custom"
        return value


class StylePresetCreate(StylePresetProperties):
    name: str = Field(..., description="风格名称", max_length=255)
    positive_prompt: str = Field(..., description="正向提示词")


class StylePresetUpdate(StylePresetCreate):
    pass


class StylePresetPatch(StylePresetProperties):
    pass


class StylePresetOut(StylePresetProperties, BaseResponse):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="风格ID")
    name: str = Field(..., description="风格名称")
    positive_prompt: str = Field(..., description="正向提示词")

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        if hasattr(obj, "id"):
            obj.id = str(obj.id)
        if hasattr(obj, "builtin_key") and obj.builtin_key == "storyboard-default":
            obj.source = "builtin"
        elif hasattr(obj, "source") and obj.source == "local":
            obj.source = "custom"
        elif hasattr(obj, "source") and obj.source is None:
            obj.source = "custom"
        return super().model_validate(obj, *args, **kwargs)
