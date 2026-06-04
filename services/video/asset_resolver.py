"""解析 prompt 中的 @资产昵称，查找匹配资产并收集参考媒体。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from config import settings
from models.asset import Asset
from services.video.base import image_to_base64

logger = logging.getLogger(__name__)

MENTION_PATTERN = re.compile(r"@\{([^}]+)\}|@([\w一-鿿·]+)")


async def resolve_assets(prompt: str, novel_id: int) -> list[dict[str, Any]]:
    """从 prompt 中解析 @mentions，返回 subjects 列表。"""
    mentions = [m1 or m2 for m1, m2 in MENTION_PATTERN.findall(prompt)]
    logger.info("resolve_assets: mentions=%s (prompt[:100]=%r)", mentions, prompt[:100])
    if not mentions:
        return []

    assets = await Asset.filter(novel_id=novel_id).all()
    logger.info(
        "resolve_assets: novel_id=%s, total_assets=%d, names=%s",
        novel_id, len(assets), [a.canonical_name for a in assets],
    )

    subjects: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for name in mentions:
        matched = _find_asset(name, assets)
        if matched and matched.id not in seen_ids:
            seen_ids.add(matched.id)
            images = _collect_images(matched)
            videos = _collect_media_paths(matched, ("video_url",))
            audios = _collect_media_paths(matched, ("audio_url",))
            logger.info(
                "resolve_assets: matched %r -> asset_id=%s, images=%d, videos=%d, audios=%d",
                name,
                matched.id,
                len(images),
                len(videos),
                len(audios),
            )
            subjects.append(
                {
                    "name": matched.canonical_name,
                    "images": images,
                    "videos": videos,
                    "audios": audios,
                    "description": matched.description or matched.base_traits or "",
                }
            )
        elif not matched:
            logger.warning("resolve_assets: mention %r not found in assets", name)

    return subjects


def _find_asset(name: str, assets: list[Asset]) -> Asset | None:
    """在资产列表中按 canonical_name 或 aliases 匹配。"""
    for asset in assets:
        if asset.canonical_name == name:
            return asset
        if name in (asset.aliases or []):
            return asset
    return None


def _collect_images(asset: Asset) -> list[str]:
    """收集资产的所有参考图（URL 直接返回，本地路径转 base64）。"""
    images: list[str] = []
    for field_name in ("main_image", "angle_image_1", "angle_image_2"):
        path = getattr(asset, field_name, None)
        if not path:
            continue
        if path.startswith(("http://", "https://")):
            images.append(path)
            continue
        local_path = _resolve_local_media_path(path)
        if not local_path:
            continue
        try:
            images.append(image_to_base64(local_path))
        except FileNotFoundError:
            logger.warning("resolve_assets: image not found: %s", local_path)
    return images


def _collect_media_paths(asset: Asset, field_names: tuple[str, ...]) -> list[str]:
    media_paths: list[str] = []
    for field_name in field_names:
        path = getattr(asset, field_name, None)
        if not path:
            continue
        if path.startswith(("http://", "https://")):
            media_paths.append(path)
            continue
        local_path = _resolve_local_media_path(path)
        if not local_path:
            continue
        media_paths.append(path)
    return media_paths


def _resolve_local_media_path(path: str) -> str | None:
    if path.startswith("/media/"):
        local_path = os.path.join(settings.MEDIA_PATH, path[len("/media/"):])
    else:
        local_path = path

    if not os.path.exists(local_path):
        logger.warning("resolve_assets: media not found: %s", local_path)
        return None
    return local_path
