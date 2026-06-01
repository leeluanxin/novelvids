import pytest
from httpx import AsyncClient
from models.config import AiModelConfig
from utils.enums import AiTaskTypeEnum


@pytest.mark.asyncio
async def test_api_create_api_config(client: AsyncClient):
    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "deepseek-v3",
        "invocation_type": "api",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-test-key",
        "model": "deepseek-chat",
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "deepseek-v3"
    assert data["invocation_type"] == "api"
    assert data["is_active"] is False
    assert data["concurrency"] == 1


@pytest.mark.asyncio
async def test_api_create_cli_config(client: AsyncClient):
    payload = {
        "task_type": AiTaskTypeEnum.video.value,
        "name": "dreamina-cli",
        "invocation_type": "cli",
        "cli_command": "dreamina",
        "model": "seedance-pro",
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["invocation_type"] == "cli"
    assert data["cli_command"] == "dreamina"
    assert data["base_url"] is None
    assert data["api_key"] is None


@pytest.mark.asyncio
async def test_api_create_cli_config_missing_command_returns_422(client: AsyncClient):
    payload = {
        "task_type": AiTaskTypeEnum.video.value,
        "name": "bad-cli",
        "invocation_type": "cli",
        "model": "seedance-pro",
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 422
    assert "cli_command" in body["message"]


@pytest.mark.asyncio
async def test_api_patch_config_switch_to_api_missing_fields_returns_422(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="cli-only",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-pro",
    )

    response = await client.patch(
        f"/api/config/{config.id}",
        json={"invocation_type": "api"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["code"] == 422
    assert "base_url" in body["message"]


@pytest.mark.asyncio
async def test_api_get_config_list(client: AsyncClient):
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-a",
        invocation_type="api",
        base_url="https://a.com",
        api_key="key-a",
        model="model-a",
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="config-b",
        invocation_type="cli",
        cli_command="dreamina",
        model="model-b",
    )

    response = await client.get("/api/config")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pagination"]["total"] >= 2


@pytest.mark.asyncio
async def test_api_get_config_detail(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="detail-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-detail",
        model="gpt-4o",
    )

    response = await client.get(f"/api/config/{config.id}")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["id"] == config.id
    assert data["name"] == "detail-config"


@pytest.mark.asyncio
async def test_api_update_config_to_cli(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="old-name",
        invocation_type="api",
        base_url="https://old.com",
        api_key="old-key",
        model="old-model",
    )

    payload = {
        "task_type": AiTaskTypeEnum.video.value,
        "name": "new-name",
        "invocation_type": "cli",
        "cli_command": "dreamina",
        "model": "new-model",
    }
    response = await client.put(f"/api/config/{config.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "new-name"
    assert data["invocation_type"] == "cli"
    assert data["cli_command"] == "dreamina"
    assert data["base_url"] is None
    assert data["api_key"] is None


@pytest.mark.asyncio
async def test_api_patch_config(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="patch-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="gpt-4o",
    )

    response = await client.patch(
        f"/api/config/{config.id}",
        json={"model": "gpt-4o-mini"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["model"] == "gpt-4o-mini"
    assert data["name"] == "patch-config"


@pytest.mark.asyncio
async def test_api_patch_config_to_cli(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="patch-cli",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-patch",
        model="seedance-api",
    )

    response = await client.patch(
        f"/api/config/{config.id}",
        json={"invocation_type": "cli", "cli_command": "dreamina"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["invocation_type"] == "cli"
    assert data["cli_command"] == "dreamina"
    assert data["base_url"] is None
    assert data["api_key"] is None


@pytest.mark.asyncio
async def test_api_delete_config(client: AsyncClient):
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="delete-config",
        invocation_type="api",
        base_url="https://api.example.com",
        api_key="sk-del",
        model="gpt-4o",
    )

    response = await client.delete(f"/api/config/{config.id}")
    assert response.status_code == 200, response.text

    exists = await AiModelConfig.filter(id=config.id).exists()
    assert not exists


@pytest.mark.asyncio
async def test_api_activate_config(client: AsyncClient):
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-1",
        invocation_type="api",
        base_url="https://1.com",
        api_key="key-1",
        model="model-1",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="config-2",
        invocation_type="api",
        base_url="https://2.com",
        api_key="key-2",
        model="model-2",
    )

    response = await client.post(f"/api/config/{c2.id}/activate")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_create_config_with_active(client: AsyncClient):
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="existing-active",
        invocation_type="api",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )

    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "new-active",
        "invocation_type": "api",
        "base_url": "https://new.com",
        "api_key": "key-new",
        "model": "model-new",
        "is_active": True,
    }
    response = await client.post("/api/config", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_update_config_with_active(client: AsyncClient):
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-update",
        invocation_type="api",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-update",
        invocation_type="api",
        base_url="https://u.com",
        api_key="key-u",
        model="model-u",
    )

    payload = {
        "task_type": AiTaskTypeEnum.extraction.value,
        "name": "to-update",
        "invocation_type": "api",
        "base_url": "https://u.com",
        "api_key": "key-u",
        "model": "model-u",
        "is_active": True,
    }
    response = await client.put(f"/api/config/{c2.id}", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_patch_config_with_active(client: AsyncClient):
    c1 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="active-before-patch",
        invocation_type="api",
        base_url="https://old.com",
        api_key="key-old",
        model="model-old",
        is_active=True,
    )
    c2 = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="to-patch",
        invocation_type="api",
        base_url="https://p.com",
        api_key="key-p",
        model="model-p",
    )

    response = await client.patch(
        f"/api/config/{c2.id}",
        json={"is_active": True},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["is_active"] is True

    await c1.refresh_from_db()
    assert c1.is_active is False


@pytest.mark.asyncio
async def test_api_activate_does_not_affect_other_task_types(client: AsyncClient):
    extraction = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="extraction-active",
        invocation_type="api",
        base_url="https://e.com",
        api_key="key-e",
        model="model-e",
        is_active=True,
    )
    video = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="video-config",
        invocation_type="cli",
        cli_command="dreamina",
        model="model-v",
        is_active=True,
    )

    new_ext = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.extraction.value,
        name="extraction-new",
        invocation_type="api",
        base_url="https://e2.com",
        api_key="key-e2",
        model="model-e2",
    )
    await client.post(f"/api/config/{new_ext.id}/activate")

    await video.refresh_from_db()
    assert video.is_active is True

    await extraction.refresh_from_db()
    assert extraction.is_active is False


@pytest.mark.asyncio
async def test_api_获取所有枚举(client: AsyncClient):
    response = await client.get("/api/config/enums/all")
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    expected_keys = {
        "task_status", "asset_type", "image_source",
        "workflow_status", "ai_task_type", "video_model_type",
    }
    assert set(data.keys()) == expected_keys

    for key in expected_keys:
        items = data[key]
        assert len(items) > 0, f"{key} 不应为空"
        first = items[0]
        assert "value" in first
        assert "label" in first
        assert "name" in first

    video_types = {item["name"]: item for item in data["video_model_type"]}
    assert "viduq2" in video_types
    assert video_types["viduq2"]["value"] == 1
    assert video_types["viduq2"]["label"] == "Viduq2"
