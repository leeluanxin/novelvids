import tempfile
from pathlib import Path

import pytest

from config import settings
from models.asset import Asset
from models.novel import Novel
from services.video.asset_resolver import MENTION_PATTERN, resolve_assets
from services.video.seedance import SeedanceGenerator
from utils.enums import AssetTypeEnum


@pytest.mark.asyncio
async def test_解析单个资产引用():
    """@张三 解析为一个 subject。"""
    novel = await Novel.create(name="Resolver Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )

    subjects = await resolve_assets("@张三 在大殿中行走", novel.id)
    assert len(subjects) == 1
    assert subjects[0]["name"] == "张三"
    assert subjects[0]["images"] == []
    assert subjects[0]["videos"] == []
    assert subjects[0]["audios"] == []


@pytest.mark.asyncio
async def test_解析多个资产引用():
    """@张三 和 @李四 解析为两个 subject。"""
    novel = await Novel.create(name="Multi Resolver Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="李四",
    )

    subjects = await resolve_assets("@张三 和 @李四 在大殿中行走", novel.id)
    assert len(subjects) == 2
    names = {s["name"] for s in subjects}
    assert names == {"张三", "李四"}


@pytest.mark.asyncio
async def test_通过别名解析资产():
    """@小张 通过 aliases 匹配到 张三。"""
    novel = await Novel.create(name="Alias Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
        aliases=["小张", "张大侠"],
    )

    subjects = await resolve_assets("@小张 在大殿中行走", novel.id)
    assert len(subjects) == 1
    assert subjects[0]["name"] == "张三"


@pytest.mark.asyncio
async def test_无引用返回空列表():
    """prompt 不含 @ 时返回空。"""
    novel = await Novel.create(name="Empty Novel", author="Author")
    subjects = await resolve_assets("在大殿中行走", novel.id)
    assert subjects == []


@pytest.mark.asyncio
async def test_未匹配资产被忽略():
    """@不存在 不在数据库中，被忽略。"""
    novel = await Novel.create(name="No Match Novel", author="Author")
    subjects = await resolve_assets("@不存在的角色 在大殿", novel.id)
    assert subjects == []


@pytest.mark.asyncio
async def test_重复引用不重复():
    """同一个 @张三 出现两次只产生一个 subject。"""
    novel = await Novel.create(name="Dedup Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.person.value,
        canonical_name="张三",
    )

    subjects = await resolve_assets("@张三 走到 @张三 面前", novel.id)
    assert len(subjects) == 1


@pytest.mark.asyncio
async def test_解析多模态资产引用(tmp_path: Path):
    image_path = tmp_path / "ref.png"
    image_path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    video_rel = "/media/test-video.mp4"
    audio_rel = "/media/test-audio.mp3"
    (Path(settings.MEDIA_PATH) / "test-video.mp4").write_bytes(b"video")
    (Path(settings.MEDIA_PATH) / "test-audio.mp3").write_bytes(b"audio")

    novel = await Novel.create(name="Multimodal Novel", author="Author")
    await Asset.create(
        novel=novel,
        asset_type=AssetTypeEnum.general.value,
        canonical_name="旁白声音",
        main_image=str(image_path),
        video_url=video_rel,
        audio_url=audio_rel,
        description="稳定的旁白声线",
    )

    subjects = await resolve_assets("请使用@{旁白声音}", novel.id)
    assert len(subjects) == 1
    subject = subjects[0]
    assert subject["name"] == "旁白声音"
    assert len(subject["images"]) == 1
    assert subject["images"][0].startswith("data:image/png;base64,")
    assert subject["videos"] == [video_rel]
    assert subject["audios"] == [audio_rel]
    assert subject["description"] == "稳定的旁白声线"


def test_mention正则匹配():
    """验证 MENTION_PATTERN 能匹配中英文。"""
    text = "@张三 和 @Alice 在 @大殿 里"
    matches = [m1 or m2 for m1, m2 in MENTION_PATTERN.findall(text)]
    assert "张三" in matches
    assert "Alice" in matches
    assert "大殿" in matches


class _DummyConfig:
    invocation_type = "cli"
    cli_command = "dreamina"
    model = "dreamina"
    api_key = ""
    base_url = ""


def _build_generator() -> SeedanceGenerator:
    return SeedanceGenerator(_DummyConfig())


def test_seedance_处理图片和音频引用():
    generator = _build_generator()
    prompt, images, videos, audios = generator._process_prompt(
        "给@{角色A}生成视频",
        [
            {
                "name": "角色A",
                "images": ["/media/ref-image.png"],
                "videos": [],
                "audios": ["/media/ref-audio.mp3"],
                "description": "角色A描述",
            }
        ],
    )

    assert prompt == "给[参考1]生成视频"
    assert images == ["/media/ref-image.png"]
    assert videos == []
    assert audios == ["/media/ref-audio.mp3"]


def test_seedance_处理视频和音频引用():
    generator = _build_generator()
    prompt, images, videos, audios = generator._process_prompt(
        "给@{角色B}生成视频",
        [
            {
                "name": "角色B",
                "images": [],
                "videos": ["/media/ref-video.mp4"],
                "audios": ["/media/ref-audio.mp3"],
                "description": "角色B描述",
            }
        ],
    )

    assert prompt == "给[参考1]生成视频"
    assert images == []
    assert videos == ["/media/ref-video.mp4"]
    assert audios == ["/media/ref-audio.mp3"]


def test_seedance_纯音频引用也生成参考占位():
    generator = _build_generator()
    prompt, images, videos, audios = generator._process_prompt(
        "给@{旁白声音}生成视频",
        [
            {
                "name": "旁白声音",
                "images": [],
                "videos": [],
                "audios": ["/media/ref-audio.mp3"],
                "description": "稳定的旁白声线",
            }
        ],
    )

    assert prompt == "给[参考1]生成视频"
    assert images == []
    assert videos == []
    assert audios == ["/media/ref-audio.mp3"]


def test_seedance_参考占位编号与_cli_参考顺序一致():
    generator = _build_generator()
    prompt, images, videos, audios = generator._process_prompt(
        "给@{角色A}、@{角色B}和@{旁白声音}生成视频",
        [
            {
                "name": "角色A",
                "images": ["/media/ref-image.png"],
                "videos": [],
                "audios": [],
                "description": "角色A描述",
            },
            {
                "name": "角色B",
                "images": [],
                "videos": ["/media/ref-video.mp4"],
                "audios": [],
                "description": "角色B描述",
            },
            {
                "name": "旁白声音",
                "images": [],
                "videos": [],
                "audios": ["/media/ref-audio.mp3"],
                "description": "稳定的旁白声线",
            },
        ],
    )

    assert prompt == "给[参考1]、[参考2]和[参考3]生成视频"
    assert images == ["/media/ref-image.png"]
    assert videos == ["/media/ref-video.mp4"]
    assert audios == ["/media/ref-audio.mp3"]


@pytest.mark.asyncio
async def test_seedance_纯音频引用在_cli_下报错():
    generator = _build_generator()

    with pytest.raises(Exception, match="音频参考至少需要同时提供一张图片或一个视频参考"):
        await generator.submit(
            prompt="给@{旁白声音}生成视频",
            subjects=[
                {
                    "name": "旁白声音",
                    "images": [],
                    "videos": [],
                    "audios": ["/media/ref-audio.mp3"],
                    "description": "稳定的旁白声线",
                }
            ],
        )
