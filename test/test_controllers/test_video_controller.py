import base64
import os

import pytest
from pydantic import BaseModel
from unittest.mock import AsyncMock, patch

from config import settings
from fastapi import HTTPException

from controllers.video import video_controller
from models.novel import Novel
from models.chapter import Chapter
from models.scene import Scene
from models.asset import Asset
from models.video import Video
from models.config import AiModelConfig
from schemas.video import VideoGenerateRequest
from services.video import get_generator
from utils.enums import (
    AiTaskTypeEnum,
    AssetTypeEnum,
    TaskStatusEnum,
    VideoModelTypeEnum,
)


class _VideoListItemOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    scene_id: int
    model_type: VideoModelTypeEnum | None = None
    url: str | None = None
    status: TaskStatusEnum | None = None
    metadata: object | None = None


# =====================================================================
# 辅助函数
# =====================================================================

async def _create_scene_with_config(
    prompt: str = "测试提示词",
    model_name: str = "viduq2",
) -> tuple[Scene, AiModelConfig]:
    """创建完整的 Scene + AiModelConfig 测试数据。"""
    novel = await Novel.create(name="Video Test Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt=prompt, duration=6.0)
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name=model_name,
        base_url="https://mock.api.com/v2",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )
    return scene, config


# =====================================================================
# generate 方法
# =====================================================================

@pytest.mark.asyncio
async def test_生成视频_提交成功():
    """正常提交视频生成，返回 Video 记录。"""
    scene, config = await _create_scene_with_config()
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "ext-task-001"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

    assert video.id is not None
    assert video.scene_id == scene.id
    assert video.model_type == VideoModelTypeEnum.viduq2.value
    assert video.external_task_id == "ext-task-001"
    assert video.status == TaskStatusEnum.pending.value
    print(f"    生成视频成功: video_id={video.id}, task_id={video.external_task_id}")


@pytest.mark.asyncio
async def test_生成视频_分镜不存在():
    """分镜ID不存在时报 404。"""
    req = VideoGenerateRequest(
        scene_id=99999,
        model_type=VideoModelTypeEnum.viduq2.value,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 404
    assert "分镜" in exc_info.value.detail
    print(f"    分镜不存在: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_无配置报404():
    """未配置视频模型时报 404。"""
    novel = await Novel.create(name="No Config Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)

    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )
    with pytest.raises(HTTPException) as exc_info:
        await video_controller.generate(req)
    assert exc_info.value.status_code == 404
    assert "未配置" in exc_info.value.detail
    print(f"    无配置: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_生成视频_解析资产引用():
    """prompt 含 @资产昵称 时解析并传递 subjects。"""
    novel = await Novel.create(name="Asset Resolve Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=["小张"],
    )
    scene = await Scene.create(
        chapter=chapter, sequence=1,
        prompt="@张三 在大殿中行走",
        duration=6.0,
    )
    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="viduq2",
        base_url="https://mock.api.com/v2",
        api_key="sk-test",
        model="mock-model",
        is_active=True,
    )
    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.viduq2.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "ext-task-002"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

        # 验证 submit 被调用时传递了 subjects
        call_kwargs = mock_gen.submit.call_args
        subjects = call_kwargs.kwargs.get("subjects") or call_kwargs[1].get("subjects")
        assert subjects is not None
        assert len(subjects) == 1
        assert subjects[0]["name"] == "张三"

    assert video.external_task_id == "ext-task-002"
    print(f"    解析资产引用: subjects={[s['name'] for s in subjects]}")


# =====================================================================
# query_status 方法
# =====================================================================

@pytest.mark.asyncio
async def test_查询视频状态_进行中():
    """查询进行中的任务，返回进度。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-001",
        status=TaskStatusEnum.pending.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.running,
            "progress": 50,
            "url": None,
            "metadata": {},
        }
        mock_factory.return_value = mock_gen

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.running.value
    print(f"    查询进行中: status={result.status}, video_id={result.id}")


@pytest.mark.asyncio
async def test_查询视频状态_已完成():
    """任务完成时更新 url 和 status。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-002",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/video.mp4",
            "metadata": {"duration": 6.0},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"./media/videos/{video.id}.mp4"

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.completed.value
    assert result.url == f"./media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/video.mp4", video.id)
    print(f"    查询已完成: url={result.url}")


@pytest.mark.asyncio
async def test_查询视频状态_已完成不再查询():
    """已完成的视频不再调用外部 API。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-003",
        status=TaskStatusEnum.completed.value,
        url="https://cdn.example.com/done.mp4",
    )

    # 不应调用 get_generator
    result = await video_controller.query_status(video.id)
    assert result.status == TaskStatusEnum.completed.value
    assert result.url == "https://cdn.example.com/done.mp4"
    print(f"    已完成不再查询: url={result.url}")


@pytest.mark.asyncio
async def test_查询视频状态_失败():
    """任务失败时更新 status。"""
    scene, config = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="ext-query-004",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.failed,
            "progress": None,
            "url": None,
            "metadata": {"err_code": "timeout"},
        }
        mock_factory.return_value = mock_gen

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.failed.value
    print(f"    查询失败: status={result.status}")


@pytest.mark.asyncio
async def test_小说视频列表_加载时主动补查远端状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="load-refresh-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/load-refresh.mp4",
            "metadata": {"source": "load-refresh"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"

        result = await video_controller.get_novel_videos(scene.chapter.novel_id)

    assert len(result) == 1
    assert result[0]["id"] == video.id
    assert result[0]["status"] == TaskStatusEnum.completed.value
    assert result[0]["url"] == f"/media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/load-refresh.mp4", video.id)


@pytest.mark.asyncio
async def test_小说视频列表_补查失败时返回本地状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="load-refresh-002",
        status=TaskStatusEnum.running.value,
    )

    with patch.object(video_controller, "query_status", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = RuntimeError("query boom")

        result = await video_controller.get_novel_videos(scene.chapter.novel_id)

    assert len(result) == 1
    assert result[0]["id"] == video.id
    assert result[0]["status"] == TaskStatusEnum.running.value
    assert result[0]["url"] is None
    mock_query.assert_awaited_once_with(video.id)


@pytest.mark.asyncio
async def test_分页视频列表_加载时主动补查远端状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="paged-refresh-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/paged-refresh.mp4",
            "metadata": {"source": "paged-refresh"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"

        result = await video_controller.list(
            params=type("P", (), {
                "page": 1,
                "page_size": 100,
                "sort": "-id",
                "search": None,
                "filters": {"scene_id": str(scene.id)},
            })(),
            response_model=_VideoListItemOut,
        )

    assert result["pagination"]["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0].id == video.id
    assert result["items"][0].status == TaskStatusEnum.completed
    assert result["items"][0].url == f"/media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/paged-refresh.mp4", video.id)


@pytest.mark.asyncio
async def test_分页视频列表_补查失败时返回本地状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="paged-refresh-002",
        status=TaskStatusEnum.running.value,
    )

    with patch.object(video_controller, "query_status", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = RuntimeError("query boom")

        result = await video_controller.list(
            params=type("P", (), {
                "page": 1,
                "page_size": 100,
                "sort": "-id",
                "search": None,
                "filters": {"scene_id": str(scene.id)},
            })(),
            response_model=_VideoListItemOut,
        )

    assert result["pagination"]["total"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0].id == video.id
    assert result["items"][0].status == TaskStatusEnum.running
    assert result["items"][0].url is None
    mock_query.assert_awaited_once_with(video.id)


@pytest.mark.asyncio
async def test_章节视频列表_加载时主动补查远端状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="chapter-refresh-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/chapter-refresh.mp4",
            "metadata": {"source": "chapter-refresh"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"

        result = await video_controller.get_chapter_videos(scene.chapter_id)

    assert len(result) == 1
    assert result[0]["scene_id"] == scene.id
    assert result[0]["video"] is not None
    assert result[0]["video"]["id"] == video.id
    assert result[0]["video"]["status"] == TaskStatusEnum.completed.value
    assert result[0]["video"]["url"] == f"/media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/chapter-refresh.mp4", video.id)


@pytest.mark.asyncio
async def test_章节视频列表_补查失败时返回空视频():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="chapter-refresh-002",
        status=TaskStatusEnum.running.value,
    )

    with patch.object(video_controller, "query_status", new_callable=AsyncMock) as mock_query:
        mock_query.side_effect = RuntimeError("query boom")

        result = await video_controller.get_chapter_videos(scene.chapter_id)

    assert len(result) == 1
    assert result[0]["scene_id"] == scene.id
    assert result[0]["video"] is None
    mock_query.assert_awaited_once_with(video.id)


@pytest.mark.asyncio
async def test_合并章节视频_加载时主动补查远端状态():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="chapter-merge-refresh-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl, \
         patch("controllers.video.video_merger.merge_videos") as mock_merge:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/chapter-merge-refresh.mp4",
            "metadata": {"source": "chapter-merge-refresh"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"
        mock_merge.return_value = "/media/videos/merged/chapter_1_merged.mp4"

        result = await video_controller.merge_chapter_videos(scene.chapter_id)

    assert result["chapter_id"] == scene.chapter_id
    assert result["video_count"] == 1
    assert result["merged_url"] == "/media/videos/merged/chapter_1_merged.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/chapter-merge-refresh.mp4", video.id)
    mock_merge.assert_called_once()


@pytest.mark.asyncio
async def test_测试合并章节视频_只合并已有视频():
    novel = await Novel.create(name="Merge Available Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene1 = await Scene.create(chapter=chapter, sequence=1, prompt="scene1", duration=3.5)
    await Scene.create(chapter=chapter, sequence=2, prompt="scene2", duration=5.0)
    video1 = await Video.create(
        scene=scene1,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.completed.value,
        url="/media/videos/available-1.mp4",
    )

    with patch("controllers.video.video_merger.merge_videos") as mock_merge:
        mock_merge.return_value = "/media/videos/merged/chapter_test_merged.mp4"

        result = await video_controller.merge_available_chapter_videos(chapter.id)

    assert result["chapter_id"] == chapter.id
    assert result["merged_url"] == "/media/videos/merged/chapter_test_merged.mp4"
    assert result["video_count"] == 1
    assert result["total_duration"] == 3.5
    mock_merge.assert_called_once()
    merge_args = mock_merge.call_args.args
    assert len(merge_args[0]) == 1
    assert merge_args[0][0].id == video1.id
    assert merge_args[1] == chapter.id


@pytest.mark.asyncio
async def test_测试合并章节视频_补查后纳入合并():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="chapter-test-merge-refresh-001",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl, \
         patch("controllers.video.video_merger.merge_videos") as mock_merge:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/chapter-test-merge-refresh.mp4",
            "metadata": {"source": "chapter-test-merge-refresh"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"
        mock_merge.return_value = "/media/videos/merged/chapter_test_refresh_merged.mp4"

        result = await video_controller.merge_available_chapter_videos(scene.chapter_id)

    assert result["chapter_id"] == scene.chapter_id
    assert result["video_count"] == 1
    assert result["merged_url"] == "/media/videos/merged/chapter_test_refresh_merged.mp4"
    assert result["total_duration"] == round(scene.duration or 0, 1)
    mock_dl.assert_called_once_with("https://cdn.example.com/chapter-test-merge-refresh.mp4", video.id)
    mock_merge.assert_called_once()
    merge_args = mock_merge.call_args.args
    assert len(merge_args[0]) == 1
    assert merge_args[0][0].id == video.id


@pytest.mark.asyncio
async def test_测试合并章节视频_没有可用视频时报错():
    novel = await Novel.create(name="No Merge Available Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    await Scene.create(chapter=chapter, sequence=1, prompt="scene1", duration=3.0)

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.merge_available_chapter_videos(chapter.id)

    assert exc_info.value.status_code == 400
    assert "当前没有可用于测试合成的视频" in exc_info.value.detail


@pytest.mark.asyncio
async def test_CLI配置_Seedance提交成功():
    novel = await Novel.create(name="CLI Seedance Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="测试提示词", duration=6.0)

    await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-t2v",
        is_active=True,
    )

    req = VideoGenerateRequest(
        scene_id=scene.id,
        model_type=VideoModelTypeEnum.seedance.value,
    )

    with patch("controllers.video.get_generator") as mock_factory:
        mock_gen = AsyncMock()
        mock_gen.submit.return_value = "cli-task-001"
        mock_factory.return_value = mock_gen

        video = await video_controller.generate(req)

    assert video.external_task_id == "cli-task-001"
    assert video.model_type == VideoModelTypeEnum.seedance.value
    assert video.status == TaskStatusEnum.pending.value


@pytest.mark.asyncio
async def test_CLI提交_返回submit_id也能成功识别():
    from services.video.seedance import SeedanceGenerator

    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance2.0",
        is_active=True,
    )
    generator = SeedanceGenerator(config)

    with patch("services.video.seedance._run_cli_json", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"submit_id": "submit-456"}

        task_id = await generator.submit(prompt="测试提示词", duration=6.0)

    assert task_id == "submit-456"


@pytest.mark.asyncio
async def test_CLI配置_非Seedance模型直接报错():
    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance-t2v",
        is_active=True,
    )

    with pytest.raises(ValueError) as exc_info:
        get_generator(VideoModelTypeEnum.sora2.value, config)

    assert "仅支持 Seedance" in str(exc_info.value)


@pytest.mark.asyncio
async def test_CLI查询状态_完成并返回URL():
    scene, _ = await _create_scene_with_config(model_name="seedance")
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.seedance.value,
        external_task_id="cli-task-002",
        status=TaskStatusEnum.running.value,
    )

    with patch("controllers.video.get_generator") as mock_factory, \
         patch("controllers.video._download_video", new_callable=AsyncMock) as mock_dl:
        mock_gen = AsyncMock()
        mock_gen.query.return_value = {
            "status": TaskStatusEnum.completed,
            "progress": 100,
            "url": "https://cdn.example.com/cli-video.mp4",
            "metadata": {"raw_status": "success"},
        }
        mock_factory.return_value = mock_gen
        mock_dl.return_value = f"/media/videos/{video.id}.mp4"

        result = await video_controller.query_status(video.id)

    assert result.status == TaskStatusEnum.completed.value
    assert result.url == f"/media/videos/{video.id}.mp4"
    mock_dl.assert_called_once_with("https://cdn.example.com/cli-video.mp4", video.id)


@pytest.mark.asyncio
async def test_CLI查询命令_使用query_result和submit_id():
    from services.video.seedance import SeedanceGenerator

    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance2.0",
        is_active=True,
    )
    generator = SeedanceGenerator(config)

    with patch("services.video.seedance._run_cli_json", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {
            "status": "success",
            "video_url": "https://cdn.example.com/query-result.mp4",
        }

        result = await generator.query("submit-123")

    mock_run.assert_awaited_once_with("dreamina", ["query_result", "--submit_id=submit-123"])
    assert result["status"] == TaskStatusEnum.completed.value
    assert result["url"] == "https://cdn.example.com/query-result.mp4"


@pytest.mark.asyncio
async def test_CLI提交_本地参考图改走临时文件避免参数过长(tmp_path):
    from services.video.seedance import SeedanceGenerator

    config = await AiModelConfig.create(
        task_type=AiTaskTypeEnum.video.value,
        name="dreamina-cli",
        invocation_type="cli",
        cli_command="dreamina",
        model="seedance2.0",
        is_active=True,
    )
    generator = SeedanceGenerator(config)

    image_bytes = b"fake-image-bytes"
    data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")

    with patch("services.video.seedance._run_cli_json", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = {"task_id": "cli-task-003"}

        task_id = await generator.submit(
            prompt="@张三 走向镜头",
            subjects=[{"name": "张三", "images": [data_url], "description": "角色描述"}],
            duration=6.0,
        )

    assert task_id == "cli-task-003"
    call_args = mock_run.await_args.args
    assert call_args[0] == "dreamina"
    args = call_args[1]
    assert args[0] == "multimodal2video"
    image_arg = next(arg for arg in args if arg.startswith("--image="))
    assert "data:image" not in image_arg
    local_image_path = image_arg.split("=", 1)[1]
    assert os.path.dirname(local_image_path) == os.path.abspath(settings.MEDIA_PATH)
    assert not os.path.exists(local_image_path)


# =====================================================================
# 边界情况
# =====================================================================

@pytest.mark.asyncio
async def test_查询视频_无外部任务ID():
    """无 external_task_id 时报 400。"""
    scene, _ = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.pending.value,
        external_task_id=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.query_status(video.id)
    assert exc_info.value.status_code == 400
    assert "外部任务ID" in exc_info.value.detail
    print(f"    无外部任务ID: {exc_info.value.detail}")


@pytest.mark.asyncio
async def test_查询视频_配置不存在():
    """查询时配置已被删除报 404。"""
    novel = await Novel.create(name="No Cfg Query Novel", author="Author")
    chapter = await Chapter.create(novel=novel, number=1, name="第1章", content="内容")
    scene = await Scene.create(chapter=chapter, sequence=1, prompt="test", duration=6.0)
    # 不创建 AiModelConfig
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        external_task_id="orphan-task",
        status=TaskStatusEnum.pending.value,
    )

    with pytest.raises(HTTPException) as exc_info:
        await video_controller.query_status(video.id)
    assert exc_info.value.status_code == 404
    assert "配置不存在" in exc_info.value.detail
    print(f"    配置不存在: {exc_info.value.detail}")


# =====================================================================
# CRUD
# =====================================================================

@pytest.mark.asyncio
async def test_删除视频():
    """删除视频后不再存在。"""
    scene, _ = await _create_scene_with_config()
    video = await Video.create(
        scene=scene,
        model_type=VideoModelTypeEnum.viduq2.value,
        status=TaskStatusEnum.pending.value,
    )

    await video_controller.remove(video.id)
    exists = await Video.filter(id=video.id).exists()
    assert not exists
    print(f"    删除视频: video_id={video.id}")
