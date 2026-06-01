import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from controllers.config import ai_model_config_controller
from models.config import AiModelConfig
from schemas.config import AiModelConfigCreate, AiModelConfigUpdate, AiModelConfigPatch
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_创建api配置_默认不启用():
    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="test-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="gpt-4o",
    )
    config = await ai_model_config_controller.create(obj_in)
    assert config.id is not None
    assert config.invocation_type == "api"
    assert config.is_active is False
    assert config.concurrency == 1


@pytest.mark.asyncio
async def test_创建cli配置_保存命令():
    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-pro",
    )
    config = await ai_model_config_controller.create(obj_in)
    assert config.invocation_type == "cli"
    assert config.cli_command == "dreamina"
    assert config.base_url is None
    assert config.api_key is None


def test_api配置缺少base_url时校验失败():
    with pytest.raises(ValidationError):
        AiModelConfigCreate(
            task_type=AiTaskTypeEnum.extraction.value,
            name="bad-api",
            invocation_type="api",
            api_key="sk-test",
            model="gpt-4o",
        )


def test_cli配置缺少cli_command时校验失败():
    with pytest.raises(ValidationError):
        AiModelConfigCreate(
            task_type=AiTaskTypeEnum.video.value,
            name="bad-cli",
            invocation_type="cli",
            model="seedance-pro",
        )


@pytest.mark.asyncio
async def test_patch切换为api缺少必填字段时校验失败():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="cli-only",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-pro",
    )

    with pytest.raises(ValidationError):
        await ai_model_config_controller.patch(config.id, AiModelConfigPatch(invocation_type="api"))


@pytest.mark.asyncio
async def test_创建配置_传入is_active为True():
    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-test",
        model="gpt-4o",
        is_active=True,
    )
    config = await ai_model_config_controller.create(obj_in)
    assert config.is_active is True


@pytest.mark.asyncio
async def test_创建配置_启用时同类型旧的自动禁用():
    old = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="old-active",
        invocation_type="api",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )

    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="new-active",
        invocation_type="api",
        base_url="https://new.com",
        api_key="key-new",
        model="model-new",
        is_active=True,
    )
    new = await ai_model_config_controller.create(obj_in)
    assert new.is_active is True

    await old.refresh_from_db()
    assert old.is_active is False


@pytest.mark.asyncio
async def test_创建配置_不启用不影响其他():
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="existing-active",
        invocation_type="api",
        base_url="https://a.com",
        api_key="key",
        model="model",
        is_active=True,
    )

    obj_in = AiModelConfigCreate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="new-inactive",
        invocation_type="api",
        base_url="https://b.com",
        api_key="key2",
        model="model2",
    )
    await ai_model_config_controller.create(obj_in)

    await active.refresh_from_db()
    assert active.is_active is True


@pytest.mark.asyncio
async def test_全量更新api配置():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="before-update",
        invocation_type="api",
        base_url="https://old.com",
        api_key="old-key",
        model="old-model",
    )

    obj_in = AiModelConfigUpdate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="after-update",
        invocation_type="api",
        base_url="https://new.com",
        api_key="new-key",
        model="new-model",
    )
    result = await ai_model_config_controller.update(config.id, obj_in)
    assert result.name == "after-update"
    assert result.base_url == "https://new.com"
    assert result.invocation_type == "api"


@pytest.mark.asyncio
async def test_全量更新切换为cli配置():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-config",
        invocation_type="api",
        base_url="https://old.com",
        api_key="old-key",
        model="seedance-old",
    )

    obj_in = AiModelConfigUpdate(
        task_type=AiTaskTypeEnum.video.value,
        name="video-config",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-cli",
    )
    result = await ai_model_config_controller.update(config.id, obj_in)
    assert result.invocation_type == "cli"
    assert result.cli_command == "dreamina"
    assert result.base_url is None
    assert result.api_key is None
    assert result.model == "seedance-cli"


@pytest.mark.asyncio
async def test_全量更新配置_传入is_active禁用同类型():
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="currently-active",
        invocation_type="api",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
        is_active=True,
    )
    target = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        invocation_type="api",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
    )

    obj_in = AiModelConfigUpdate(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        invocation_type="api",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
        is_active=True,
    )
    result = await ai_model_config_controller.update(target.id, obj_in)
    assert result.is_active is True

    await active.refresh_from_db()
    assert active.is_active is False


@pytest.mark.asyncio
async def test_局部更新配置_只改一个字段():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="patch-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="gpt-4o",
    )

    obj_in = AiModelConfigPatch(model="gpt-4o-mini")
    result = await ai_model_config_controller.patch(config.id, obj_in)
    assert result.model == "gpt-4o-mini"
    assert result.name == "patch-config"


@pytest.mark.asyncio
async def test_局部更新配置_补充cli字段():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="patch-cli-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="seedance-api",
    )

    obj_in = AiModelConfigPatch(invocation_type="cli", cli_command="dreamina")
    result = await ai_model_config_controller.patch(config.id, obj_in)
    assert result.invocation_type == "cli"
    assert result.cli_command == "dreamina"
    assert result.base_url is None
    assert result.api_key is None


@pytest.mark.asyncio
async def test_局部更新配置_传入is_active禁用同类型():
    active = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-patch",
        invocation_type="api",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
        is_active=True,
    )
    target = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="target-patch",
        invocation_type="api",
        base_url="https://b.com",
        api_key="key-b",
        model="model-b",
    )

    obj_in = AiModelConfigPatch(is_active=True)
    result = await ai_model_config_controller.patch(target.id, obj_in)
    assert result.is_active is True

    await active.refresh_from_db()
    assert active.is_active is False


@pytest.mark.asyncio
async def test_删除配置():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-delete",
        invocation_type="api",
        base_url="https://d.com",
        api_key="key",
        model="model",
    )

    await ai_model_config_controller.remove(config.id)
    exists = await AiModelConfig.filter(id=config.id).exists()
    assert not exists


@pytest.mark.asyncio
async def test_删除不存在的配置_抛出404():
    with pytest.raises(Exception):
        await ai_model_config_controller.remove(99999)


@pytest.mark.asyncio
async def test_启用配置():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-activate",
        invocation_type="api",
        base_url="https://act.com",
        api_key="key",
        model="model",
    )
    assert config.is_active is False

    result = await ai_model_config_controller.activate(config.id)
    assert result.is_active is True


@pytest.mark.asyncio
async def test_启用配置_同类型旧的自动禁用():
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="c1-active",
        invocation_type="api",
        base_url="https://1.com",
        api_key="key-1",
        model="model-1",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="c2-inactive",
        invocation_type="api",
        base_url="https://2.com",
        api_key="key-2",
        model="model-2",
    )

    await ai_model_config_controller.activate(c2.id)

    await c1.refresh_from_db()
    assert c1.is_active is False

    await c2.refresh_from_db()
    assert c2.is_active is True


@pytest.mark.asyncio
async def test_启用配置_不同类型互不影响():
    video = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-active",
        invocation_type="cli",
        cli_command="dreamina",
        model="model-v",
        is_active=True,
    )
    ext1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-1",
        invocation_type="api",
        base_url="https://e1.com",
        api_key="key-e1",
        model="model-e1",
        is_active=True,
    )
    ext2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-2",
        invocation_type="api",
        base_url="https://e2.com",
        api_key="key-e2",
        model="model-e2",
    )

    await ai_model_config_controller.activate(ext2.id)

    await video.refresh_from_db()
    assert video.is_active is True

    await ext1.refresh_from_db()
    assert ext1.is_active is False


@pytest.mark.asyncio
async def test_获取启用配置():
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="the-active-one",
        invocation_type="api",
        base_url="https://active.com",
        api_key="key",
        model="model",
        is_active=True,
    )

    result = await ai_model_config_controller.get_active(
        AiTaskTypeEnum.extraction.value
    )
    assert result.name == "the-active-one"
    assert result.is_active is True


@pytest.mark.asyncio
async def test_获取启用配置_无启用时抛出404():
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="inactive-only",
        invocation_type="api",
        base_url="https://i.com",
        api_key="key",
        model="model",
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc_info:
        await ai_model_config_controller.get_active(
            AiTaskTypeEnum.extraction.value
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_多个类型各有启用配置_互不干扰():
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="ext-active",
        invocation_type="api",
        base_url="https://e.com",
        api_key="key-e",
        model="model-e",
        is_active=True,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-active",
        invocation_type="cli",
        cli_command="dreamina",
        model="model-v",
        is_active=True,
    )

    ext = await ai_model_config_controller.get_active(AiTaskTypeEnum.extraction.value)
    assert ext.name == "ext-active"

    vid = await ai_model_config_controller.get_active(AiTaskTypeEnum.video.value)
    assert vid.name == "video-active"
    assert vid.invocation_type == "cli"
