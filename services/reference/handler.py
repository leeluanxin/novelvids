
import asyncio
import json
import logging
import os
from asyncio.subprocess import PIPE
from urllib.parse import urlparse

import anyio
import httpx
from openai import AsyncOpenAI

from config import settings
from models.asset import Asset
from services.ai_task_executor import BaseTaskHandler
from services.reference.generator import (
    build_sora_compatible_prompt,
    generate_for_sora_consistency,
)
from utils.enums import AssetTypeEnum, ImageSourceEnum

logger = logging.getLogger(__name__)


async def _read_stream(stream) -> bytes:
    chunks: list[bytes] = []
    while True:
        try:
            chunk = await stream.receive()
        except anyio.EndOfStream:
            break
        if not chunk:
            break
        chunks.append(chunk)
    return b"".join(chunks)


def _extract_image_urls(output: object) -> list[str]:
    if isinstance(output, str) and output:
        return [output]

    if isinstance(output, list):
        urls: list[str] = []
        for item in output:
            urls.extend(_extract_image_urls(item))
        return urls

    if isinstance(output, dict):
        urls: list[str] = []

        for key in ("image_url", "url"):
            value = output.get(key)
            if isinstance(value, str) and value:
                urls.append(value)

        for key in ("images", "image_urls", "result_urls", "videos", "video_urls"):
            value = output.get(key)
            if isinstance(value, list):
                urls.extend(_extract_image_urls(value))

        for key in ("result", "result_json", "data"):
            value = output.get(key)
            if value is not None:
                urls.extend(_extract_image_urls(value))

        deduped_urls: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                deduped_urls.append(url)
        return deduped_urls

    return []


async def _run_cli_image_generation(
    cli_command: str,
    payload: dict,
) -> list[str]:
    prompt = payload["prompt"]
    model = str(payload.get("model") or "").strip()

    command = [
        cli_command,
        "text2image",
        f"--prompt={prompt}",
        "--ratio=1:1",
        "--resolution_type=2k",
        "--poll=120",
    ]
    if model and model != "dreamina":
        command.append(f"--model_version={model}")

    process = await anyio.open_process(
        command,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
    )

    await process.stdin.aclose()

    stdout, stderr = await asyncio.gather(
        _read_stream(process.stdout),
        _read_stream(process.stderr),
    )

    await process.wait()

    stderr_text = stderr.decode("utf-8", errors="ignore").strip()
    stdout_text = stdout.decode("utf-8", errors="ignore").strip()

    if process.returncode != 0:
        raise Exception(stderr_text or stdout_text or f"CLI image generation failed with exit code {process.returncode}")

    if not stdout_text:
        raise Exception("CLI image generation returned empty output")

    try:
        output = json.loads(stdout_text)
    except json.JSONDecodeError as exc:
        preview = stdout_text[:500]
        if stderr_text:
            raise Exception(
                f"CLI image generation returned invalid JSON. stdout={preview!r}; stderr={stderr_text[:500]!r}"
            ) from exc
        raise Exception(f"CLI image generation returned invalid JSON. stdout={preview!r}") from exc

    image_urls = _extract_image_urls(output)
    if not image_urls:
        raise Exception(f"CLI image generation did not return a valid images list: {stdout_text[:500]!r}")

    return image_urls


async def _download_image(remote_url: str, asset_id: int, suffix: str = "") -> str:
    """下载远程图片到本地 MEDIA_PATH/assets/ 目录，返回可访问的相对路径。

    Args:
        remote_url: 远程图片 URL
        asset_id: 资产 ID（用于文件名）
        suffix: 文件名后缀，如 "_angle1"

    Returns:
        可通过 /media/ 前缀访问的路径，如 /media/assets/42.png
    """
    asset_dir = os.path.join(settings.MEDIA_PATH, "assets")
    os.makedirs(asset_dir, exist_ok=True)

    # 从 URL 推断扩展名，默认 .png
    parsed = urlparse(remote_url)
    ext = os.path.splitext(parsed.path)[1] or ".png"
    if ext not in (".jpg", ".jpeg", ".png", ".webp"):
        ext = ".png"

    filename = f"{asset_id}{suffix}{ext}"
    local_path = os.path.join(asset_dir, filename)

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(remote_url)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(resp.content)

    media_url = f"/media/assets/{filename}"
    logger.info("Image downloaded: asset_id=%s -> %s", asset_id, media_url)
    return media_url


class AssetReferenceHandler(BaseTaskHandler):
    """资产参考图生成任务处理器。"""

    async def execute(self, request_params: dict) -> dict:
        """
        request_params:
            asset_id: int
            invocation_type: str
            cli_command: str | None
            base_url: str | None
            api_key: str | None
            model: str
        """
        asset_id = request_params["asset_id"]
        invocation_type = request_params.get("invocation_type", "api")
        cli_command = request_params.get("cli_command")
        base_url = request_params.get("base_url")
        api_key = request_params.get("api_key")
        model = request_params["model"]
        style = request_params.get("style")

        asset = await Asset.get(id=asset_id)

        try:
            asset_type_enum = AssetTypeEnum(asset.asset_type)
            asset_type_name = asset_type_enum.name
        except ValueError:
            if asset.asset_type == 1:
                asset_type_name = "person"
            elif asset.asset_type == 2:
                asset_type_name = "scene"
            elif asset.asset_type == 3:
                asset_type_name = "item"
            else:
                asset_type_name = "unknown"

        data = {
            "type": asset_type_name,
            "canonical_name": asset.canonical_name,
            "base_traits": asset.base_traits,
            "description": asset.description,
        }

        reference_images = [
            image
            for image in [
                style.get("reference_image") if isinstance(style, dict) else None,
                asset.main_image,
                asset.angle_image_1,
                asset.angle_image_2,
            ]
            if image
        ]

        try:
            if invocation_type == "cli":
                if not cli_command:
                    raise Exception("CLI image generation requires cli_command")

                image_urls = await _run_cli_image_generation(
                    cli_command,
                    {
                        "model": model,
                        "prompt": build_sora_compatible_prompt(data, style=style),
                        "asset_id": asset_id,
                    },
                )
            else:
                client = AsyncOpenAI(base_url=base_url, api_key=api_key)
                image_list = await generate_for_sora_consistency(
                    client,
                    data,
                    reference_images=reference_images,
                    model=model,
                    style=style,
                )
                image_urls = [image.url for image in image_list if getattr(image, "url", None)]

            result_urls = []
            if image_urls:
                local_url = await _download_image(image_urls[0], asset_id)
                asset.main_image = local_url
                asset.image_source = ImageSourceEnum.ai.value

                await asset.save(update_fields=["main_image", "image_source", "updated_at"])

                result_urls = [local_url]

                for i, image_url in enumerate(image_urls[1:3], start=1):
                    try:
                        angle_url = await _download_image(image_url, asset_id, f"_angle{i}")
                        field_name = f"angle_image_{i}"
                        setattr(asset, field_name, angle_url)
                        await asset.save(update_fields=[field_name, "updated_at"])
                        result_urls.append(angle_url)
                    except Exception:
                        logger.warning("Failed to download angle image %d for asset %s", i, asset_id)

            return {"images": result_urls}

        except Exception as e:
            error_str = str(e)
            if "OutputImageSensitiveContentDetected" in error_str:
                raise Exception("生成图像描述词过于血腥或者暴力，请修改提示词再次尝试") from e
            print(f"Asset reference generation failed for asset {asset_id}")
            raise e
