from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas._base import BaseResponse
from utils.enums import AiTaskTypeEnum


# --- 核心业务属性 ---

class AiModelConfigProperties(BaseModel):
    """AI 模型配置属性。"""

    task_type: Optional[int] = Field(None, description=AiTaskTypeEnum.__doc__)
    name: Optional[str] = Field(None, description="配置名称", max_length=100)
    invocation_type: Optional[Literal["api", "cli"]] = Field("api", description="调用方式")
    base_url: Optional[str] = Field(None, description="API 地址", max_length=500)
    api_key: Optional[str] = Field(None, description="API Key", max_length=500)
    model: Optional[str] = Field(None, description="模型名称", max_length=200)
    cli_command: Optional[str] = Field(None, description="CLI 命令", max_length=500)
    is_active: Optional[bool] = Field(None, description="是否启用")
    concurrency: Optional[int] = Field(None, description="并发数", ge=1)


class AiModelConfigInput(AiModelConfigProperties):
    @model_validator(mode="after")
    def validate_invocation_fields(self):
        if self.invocation_type == "cli":
            if not self.cli_command:
                raise ValueError("cli invocation requires cli_command")
        else:
            if not self.base_url:
                raise ValueError("api invocation requires base_url")
            if not self.api_key:
                raise ValueError("api invocation requires api_key")

        if not self.model:
            raise ValueError("model is required")
        return self


# --- 输入 Schema ---

class AiModelConfigCreate(AiModelConfigInput):
    """创建请求：必填字段。"""

    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    name: str = Field(..., description="配置名称", max_length=100)
    model: str = Field(..., description="模型名称", max_length=200)


class AiModelConfigUpdate(AiModelConfigCreate):
    """全量更新：同创建。"""
    pass


class AiModelConfigPatch(AiModelConfigProperties):
    """局部更新：全字段可选。"""

    pass


# --- 输出 Schema ---

class AiModelConfigOut(AiModelConfigProperties, BaseResponse):
    """配置输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="配置ID")
    task_type: int = Field(..., description=AiTaskTypeEnum.__doc__)
    name: str = Field(..., description="配置名称")
    invocation_type: Literal["api", "cli"] = Field(..., description="调用方式")
    model: str = Field(..., description="模型名称")
    is_active: bool = Field(..., description="是否启用")
    concurrency: int = Field(..., description="并发数")
