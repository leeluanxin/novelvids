from unittest.mock import AsyncMock, Mock, patch

import pytest

from models.asset import Asset
from models.novel import Novel
from services.reference.handler import AssetReferenceHandler
from utils.enums import AssetTypeEnum, ImageSourceEnum


@pytest.mark.asyncio
@patch("services.reference.handler._download_image", new_callable=AsyncMock)
@patch("services.reference.handler.generate_for_sora_consistency", new_callable=AsyncMock)
@patch("services.reference.handler.AsyncOpenAI")
async def test_reference_handler_api模式沿用现有生成链路(
    mock_async_openai,
    mock_generate,
    mock_download,
):
    novel = await Novel.create(name="Ref Handler API Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="API人物",
        base_traits="black hair",
        description="主角",
    )

    mock_client = object()
    mock_async_openai.return_value = mock_client
    mock_generate.return_value = [Mock(url="https://example.com/api.png")]
    mock_download.return_value = "/media/assets/api.png"

    handler = AssetReferenceHandler()
    result = await handler.execute(
        {
            "asset_id": asset.id,
            "invocation_type": "api",
            "base_url": "https://mock.api.com/v1",
            "api_key": "sk-test",
            "model": "mock-model",
        }
    )

    mock_async_openai.assert_called_once_with(
        base_url="https://mock.api.com/v1",
        api_key="sk-test",
    )
    mock_generate.assert_awaited_once()
    mock_download.assert_awaited_once_with("https://example.com/api.png", asset.id)
    assert result == {"images": ["/media/assets/api.png"]}

    await asset.refresh_from_db()
    assert asset.main_image == "/media/assets/api.png"
    assert asset.image_source == ImageSourceEnum.ai.value


@pytest.mark.asyncio
@patch("services.reference.handler._download_image", new_callable=AsyncMock)
@patch("services.reference.handler._run_cli_image_generation", new_callable=AsyncMock)
async def test_reference_handler_cli模式走json包装层(
    mock_run_cli,
    mock_download,
):
    novel = await Novel.create(name="Ref Handler CLI Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="CLI人物",
        base_traits="silver hair",
        description="配角",
    )

    mock_run_cli.return_value = ["https://example.com/cli.png"]
    mock_download.return_value = "/media/assets/cli.png"

    handler = AssetReferenceHandler()
    result = await handler.execute(
        {
            "asset_id": asset.id,
            "invocation_type": "cli",
            "cli_command": "dreamina",
            "model": "seedream-3.0",
        }
    )

    mock_run_cli.assert_awaited_once()
    cli_command, payload = mock_run_cli.await_args.args
    assert cli_command == "dreamina"
    assert payload["model"] == "seedream-3.0"
    assert payload["asset_id"] == asset.id
    assert "CLI人物" in payload["prompt"]
    mock_download.assert_awaited_once_with("https://example.com/cli.png", asset.id)
    assert result == {"images": ["/media/assets/cli.png"]}

    await asset.refresh_from_db()
    assert asset.main_image == "/media/assets/cli.png"
    assert asset.image_source == ImageSourceEnum.ai.value


@pytest.mark.asyncio
async def test_reference_handler_cli模式缺少命令时报错():
    novel = await Novel.create(name="Ref Handler CLI Error Novel", author="Author")
    asset = await Asset.create(
        novel_id=novel.id,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="CLI缺命令",
    )

    handler = AssetReferenceHandler()
    with pytest.raises(Exception, match="cli_command"):
        await handler.execute(
            {
                "asset_id": asset.id,
                "invocation_type": "cli",
                "model": "seedream-3.0",
            }
        )


@pytest.mark.asyncio
@patch("services.reference.handler.anyio.open_process")
async def test_run_cli_image_generation_无效json报错(mock_open_process):
    from services.reference.handler import _run_cli_image_generation

    process = AsyncMock()
    process.communicate.return_value = (b"not-json", b"")
    process.returncode = 0
    mock_open_process.return_value = process

    with pytest.raises(Exception, match="invalid JSON"):
        await _run_cli_image_generation(
            "dreamina",
            {"model": "seedream-3.0", "prompt": "hello", "asset_id": 1},
        )
