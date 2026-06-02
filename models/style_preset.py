from tortoise import fields

from models._base import AbstractBaseModel


class StylePreset(AbstractBaseModel):
    """风格预设表"""

    name = fields.CharField(max_length=255, unique=True, description="风格名称")
    builtin_key = fields.CharField(
        max_length=100,
        unique=True,
        null=True,
        description="内置风格标识",
    )
    positive_prompt = fields.TextField(description="正向提示词")
    reference_image = fields.CharField(
        max_length=500,
        null=True,
        description="参考图URL",
    )

    class Meta:
        table = "style_presets"
        table_description = "风格预设表"

    def __str__(self):
        return self.name
