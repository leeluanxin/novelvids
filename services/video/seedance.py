"""Seedance/即梦 视频生成器。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shlex
import tempfile
from asyncio.subprocess import PIPE
from typing import Any
from urllib.parse import urlparse

import anyio
import httpx

from config import settings
from services.video.base import BaseVideoGenerator
from utils.enums import TaskStatusEnum

logger = logging.getLogger(__name__)

_ENTITY_RE = re.compile(r"@\{([^}]+)\}|@([\w一-鿿·]+)")

MAX_REF_IMAGES = 4
INLINE_RESULT_PREFIX = "cli-result:"


def _normalize_seedance_duration(duration: float) -> int:
    return min(15, max(4, int(round(duration))))


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


def _parse_cli_json(stdout_text: str, stderr_text: str) -> dict[str, Any] | list[Any]:
    text = stdout_text.strip()
    if not text:
        raise Exception(f"CLI video command returned empty output: {stderr_text[:500]!r}")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue

    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue

    raise Exception(
        f"CLI video command returned invalid JSON. stdout={text[:500]!r}; stderr={stderr_text[:500]!r}"
    )


async def _run_cli_json(cli_command: str, args: list[str]) -> dict[str, Any] | list[Any]:
    command = [*shlex.split(cli_command), *args]
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

    stdout_text = stdout.decode("utf-8", errors="ignore").strip()
    stderr_text = stderr.decode("utf-8", errors="ignore").strip()

    if process.returncode != 0:
        raise Exception(
            stderr_text or stdout_text or f"CLI video command failed with exit code {process.returncode}"
        )

    return _parse_cli_json(stdout_text, stderr_text)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _clip_for_log(output: object, limit: int = 1000) -> str:
    try:
        text = json.dumps(output, ensure_ascii=False, default=str)
    except Exception:
        text = repr(output)
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _extract_video_urls(output: object) -> list[str]:
    if isinstance(output, str) and output.startswith(("http://", "https://")):
        return [output]

    if isinstance(output, list):
        urls: list[str] = []
        for item in output:
            urls.extend(_extract_video_urls(item))
        return _dedupe(urls)

    if isinstance(output, dict):
        urls: list[str] = []

        for key in ("video_url", "url"):
            value = output.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                urls.append(value)

        for key in ("videos", "video_urls", "result_urls", "assets", "items", "content"):
            value = output.get(key)
            if isinstance(value, list):
                urls.extend(_extract_video_urls(value))
            elif isinstance(value, dict):
                urls.extend(_extract_video_urls(value))

        for key in ("result", "result_json", "data", "output", "response"):
            value = output.get(key)
            if value is not None:
                urls.extend(_extract_video_urls(value))

        return _dedupe(urls)

    return []


def _extract_task_id(output: object) -> str | None:
    if isinstance(output, dict):
        for key in ("submit_id", "submitId", "task_id", "taskId", "job_id", "jobId", "id"):
            value = output.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value)

        for key in ("result", "result_json", "data", "output", "response"):
            task_id = _extract_task_id(output.get(key))
            if task_id:
                return task_id

    if isinstance(output, list):
        for item in output:
            task_id = _extract_task_id(item)
            if task_id:
                return task_id

    return None


def _extract_raw_status(output: object) -> str | None:
    if isinstance(output, dict):
        for key in ("status", "state", "task_status"):
            value = output.get(key)
            if isinstance(value, str) and value.strip():
                return value

        for key in ("result", "result_json", "data", "output", "response"):
            status = _extract_raw_status(output.get(key))
            if status:
                return status

    if isinstance(output, list):
        for item in output:
            status = _extract_raw_status(item)
            if status:
                return status

    return None


def _map_cli_status(raw_status: str | None) -> TaskStatusEnum:
    normalized = (raw_status or "").strip().lower()

    if normalized in {"succeeded", "completed", "success", "done", "finished"}:
        return TaskStatusEnum.completed
    if normalized in {"failed", "error", "cancelled", "canceled", "timeout"}:
        return TaskStatusEnum.failed
    if normalized in {"queued", "queueing", "waiting", "pending"}:
        return TaskStatusEnum.queued
    return TaskStatusEnum.running


def _encode_inline_result(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return INLINE_RESULT_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_inline_result(token: str) -> dict[str, Any] | None:
    if not token.startswith(INLINE_RESULT_PREFIX):
        return None

    try:
        raw = base64.urlsafe_b64decode(token[len(INLINE_RESULT_PREFIX):].encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise Exception("CLI inline video result is invalid") from exc

    if not isinstance(data, dict):
        raise Exception("CLI inline video result must be a JSON object")
    return data


def _guess_file_extension(media_url: str, content_type: str | None = None) -> str:
    path_ext = os.path.splitext(urlparse(media_url).path)[1].lower()
    if path_ext:
        return path_ext

    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        content_type_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
            "audio/mpeg": ".mp3",
            "audio/wav": ".wav",
            "audio/x-wav": ".wav",
            "audio/mp4": ".m4a",
            "audio/aac": ".aac",
            "audio/ogg": ".ogg",
        }
        if normalized in content_type_map:
            return content_type_map[normalized]

    return ".bin"


async def _materialize_cli_media(media_url: str, media_kind: str, index: int) -> str:
    prefix = f"dreamina-{media_kind}-ref-{index}-"

    if media_url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(media_url)
            response.raise_for_status()
            suffix = _guess_file_extension(media_url, response.headers.get("content-type"))
            with tempfile.NamedTemporaryFile(
                prefix=prefix,
                suffix=suffix,
                dir=settings.MEDIA_PATH,
                delete=False,
            ) as tmp:
                tmp.write(response.content)
                return tmp.name

    if media_url.startswith("data:"):
        header, _, data = media_url.partition(",")
        if not data:
            raise Exception(f"CLI reference {media_kind} data URL is invalid")

        mime_match = re.match(r"data:([^;]+)", header)
        suffix = _guess_file_extension("", mime_match.group(1) if mime_match else None)
        with tempfile.NamedTemporaryFile(
            prefix=prefix,
            suffix=suffix,
            dir=settings.MEDIA_PATH,
            delete=False,
        ) as tmp:
            tmp.write(base64.b64decode(data))
            return tmp.name

    if media_url.startswith("/media/"):
        return os.path.join(settings.MEDIA_PATH, media_url[len("/media/"):])

    if os.path.exists(media_url):
        return media_url

    raise Exception(
        f"CLI reference {media_kind} must be a remote URL, data URL, or local file path"
    )


class SeedanceGenerator(BaseVideoGenerator):
    """Seedance/即梦 平台视频生成。"""

    @staticmethod
    def _process_prompt(
        prompt: str,
        subjects: list[dict[str, Any]] | None,
    ) -> tuple[str, list[str], list[str], list[str]]:
        if not subjects:
            return _ENTITY_RE.sub(lambda m: m.group(1) or m.group(2), prompt), [], [], []

        subj_map: dict[str, dict[str, Any]] = {}
        name_to_ref_index: dict[str, int] = {}
        ref_images: list[str] = []
        ref_videos: list[str] = []
        ref_audios: list[str] = []
        audio_primary_by_name: dict[str, str] = {}
        primary_refs: list[tuple[str, str, int]] = []

        for subj in subjects:
            subj_map[subj["name"]] = subj

            images = _dedupe(list(subj.get("images") or []))
            videos = _dedupe(list(subj.get("videos") or []))
            audios = _dedupe(list(subj.get("audios") or []))

            if audios:
                ref_audios.extend(audios)

            if len(primary_refs) >= MAX_REF_IMAGES:
                continue

            if images:
                ref_images.append(images[0])
                primary_refs.append((subj["name"], "image", len(ref_images) - 1))
            elif videos:
                ref_videos.append(videos[0])
                primary_refs.append((subj["name"], "video", len(ref_videos) - 1))
            elif audios:
                audio_primary_by_name[subj["name"]] = audios[0]
                primary_refs.append((subj["name"], "audio", -1))

        ref_audios = _dedupe(ref_audios)
        audio_index_by_value: dict[str, int] = {}
        for idx, audio in enumerate(ref_audios):
            audio_index_by_value.setdefault(audio, idx)

        image_offset = 0
        video_offset = len(ref_images)
        audio_offset = len(ref_images) + len(ref_videos)
        for name, media_kind, local_index in primary_refs:
            if media_kind == "image":
                name_to_ref_index[name] = image_offset + local_index + 1
            elif media_kind == "video":
                name_to_ref_index[name] = video_offset + local_index + 1
            else:
                primary_audio = audio_primary_by_name.get(name)
                if primary_audio is not None and primary_audio in audio_index_by_value:
                    name_to_ref_index[name] = audio_offset + audio_index_by_value[primary_audio] + 1

        def _replace(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            subj = subj_map.get(name)
            if not subj:
                return name
            idx = name_to_ref_index.get(subj["name"])
            if idx is not None:
                return f"[参考{idx}]"
            return subj.get("description") or subj["name"]

        processed = _ENTITY_RE.sub(_replace, prompt)
        return processed, ref_images, ref_videos, ref_audios

    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> str:
        processed_prompt, ref_images, ref_videos, ref_audios = self._process_prompt(prompt, subjects)
        has_visual_refs = bool(ref_images or ref_videos)
        requested_model_version = kwargs.get("model_version")
        selected_model_version = requested_model_version or self.config.model

        if (self.config.invocation_type or "cli").lower() == "cli":
            if not self.config.cli_command:
                raise Exception("CLI video generation requires cli_command")
            if ref_audios and not has_visual_refs:
                raise Exception("即梦 CLI 的音频参考至少需要同时提供一张图片或一个视频参考")

            local_ref_media: list[str] = []
            try:
                cli_duration = _normalize_seedance_duration(duration)
                args = [
                    "multimodal2video" if (has_visual_refs or ref_audios) else "text2video",
                    f"--prompt={processed_prompt}",
                    f"--duration={cli_duration}",
                    "--poll=120",
                ]
                if aspect_ratio:
                    args.append(f"--ratio={aspect_ratio}")
                if selected_model_version and selected_model_version != "dreamina":
                    args.append(f"--model_version={selected_model_version}")

                for index, image_url in enumerate(ref_images, start=1):
                    local_path = await _materialize_cli_media(image_url, "image", index)
                    local_ref_media.append(local_path)
                    args.append(f"--image={local_path}")

                for index, video_url in enumerate(ref_videos, start=1):
                    local_path = await _materialize_cli_media(video_url, "video", index)
                    local_ref_media.append(local_path)
                    args.append(f"--video={local_path}")

                for index, audio_url in enumerate(ref_audios, start=1):
                    local_path = await _materialize_cli_media(audio_url, "audio", index)
                    local_ref_media.append(local_path)
                    args.append(f"--audio={local_path}")

                full_command = [*shlex.split(self.config.cli_command), *args]
                logger.info("Dreamina CLI submit command: %s", shlex.join(full_command))
                output = await _run_cli_json(self.config.cli_command, args)
                logger.info("Dreamina CLI submit output: %s", _clip_for_log(output))
            finally:
                for local_path in local_ref_media:
                    try:
                        if os.path.basename(local_path).startswith("dreamina-"):
                            os.remove(local_path)
                    except FileNotFoundError:
                        pass

            task_id = _extract_task_id(output)
            if task_id:
                logger.info("Dreamina CLI submit task id: %s", task_id)
                return task_id

            video_urls = _extract_video_urls(output)
            raw_status = _extract_raw_status(output)
            logger.warning(
                "Dreamina CLI submit missing task id. raw_status=%s, video_urls=%d, output=%s",
                raw_status,
                len(video_urls),
                _clip_for_log(output),
            )
            status = _map_cli_status(raw_status)
            if video_urls and status != TaskStatusEnum.failed:
                status = TaskStatusEnum.completed

            if status in (TaskStatusEnum.completed, TaskStatusEnum.failed):
                return _encode_inline_result(
                    {
                        "raw_status": raw_status,
                        "video_urls": video_urls,
                        "output": output,
                    }
                )

            raise Exception("CLI video generation did not return task id or terminal result")

        if not self.config.base_url or not self.config.api_key:
            raise Exception("Seedance API invocation requires base_url and api_key")

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Seedance _process_prompt: subjects=%d, ref_images=%d, ref_videos=%d, ref_audios=%d, prompt[:80]=%r",
            len(subjects or []), len(ref_images), len(ref_videos), len(ref_audios), processed_prompt[:80],
        )
        if ref_videos:
            logger.info("Seedance video refs: %s", ref_videos)

        model_name = selected_model_version
        supports_images = bool(model_name) and ("i2v" in model_name or "t2v" in model_name)
        if model_name and ref_images and "t2v" in model_name:
            model_name = model_name.replace("t2v", "i2v")
            logger.info("Seedance auto-switch: t2v -> i2v (has images)")
        elif model_name and not ref_images and "i2v" in model_name:
            model_name = model_name.replace("i2v", "t2v")
            logger.info("Seedance auto-switch: i2v -> t2v (no images)")
        elif model_name and ref_images and not supports_images:
            logger.warning(
                "Seedance model %s does not support reference images, skipping %d images",
                model_name, len(ref_images),
            )
            ref_images = []

        content: list[dict[str, Any]] = [
            {"type": "text", "text": processed_prompt}
        ]
        for img in ref_images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img},
                "role": "reference_image",
            })

        payload: dict[str, Any] = {
            "content": content,
            "duration": _normalize_seedance_duration(duration),
            "watermark": False,
        }
        if model_name:
            payload["model"] = model_name

        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{self.config.base_url}/contents/generations/tasks"
            logger.info("Seedance request: POST %s\npayload: %s", url, {
                **payload,
                "content": [
                    {**c, "image_url": {"url": c["image_url"]["url"][:80] + "..."}} if c.get("image_url") else c
                    for c in payload["content"]
                ],
            })
            resp = await client.post(url, headers=headers, json=payload)

            if resp.status_code != 200:
                logger.error("Seedance error %s: %s", resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()

        task_id = data.get("id")
        logger.info("Seedance submit: task_id=%s, images=%d", task_id, len(ref_images))
        return task_id

    async def query(self, external_task_id: str) -> dict[str, Any]:
        if (self.config.invocation_type or "cli").lower() == "cli":
            if not self.config.cli_command:
                raise Exception("CLI video generation requires cli_command")

            inline_result = _decode_inline_result(external_task_id)
            if inline_result is not None:
                output = inline_result.get("output")
                raw_status = inline_result.get("raw_status")
                video_urls = inline_result.get("video_urls") or []
                logger.info(
                    "Dreamina CLI query inline result: task_id=%s, raw_status=%s, video_urls=%d, output=%s",
                    external_task_id,
                    raw_status,
                    len(video_urls),
                    _clip_for_log(output),
                )
            else:
                try:
                    output = await _run_cli_json(
                        self.config.cli_command,
                        ["query_result", f"--submit_id={external_task_id}"],
                    )
                except Exception as exc:
                    raise Exception(
                        f"CLI video status query failed for task {external_task_id}: {exc}"
                    ) from exc

                raw_status = _extract_raw_status(output)
                video_urls = _extract_video_urls(output)
                logger.info(
                    "Dreamina CLI query output: task_id=%s, raw_status=%s, video_urls=%d, output=%s",
                    external_task_id,
                    raw_status,
                    len(video_urls),
                    _clip_for_log(output),
                )

            status = _map_cli_status(raw_status)
            if video_urls and status != TaskStatusEnum.failed:
                status = TaskStatusEnum.completed

            if status == TaskStatusEnum.completed and not video_urls:
                return self._build_result(
                    TaskStatusEnum.failed,
                    error="CLI video task completed but no video URL was returned",
                    raw_status=raw_status,
                    output=output,
                )

            return self._build_result(
                status,
                progress=100 if status == TaskStatusEnum.completed else None,
                url=video_urls[0] if video_urls else None,
                raw_status=raw_status,
                output=output,
            )

        if not self.config.base_url or not self.config.api_key:
            raise Exception("Seedance API invocation requires base_url and api_key")

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url}/contents/generations/tasks/{external_task_id}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        status = data.get("status", "")
        logger.info("Seedance query: task=%s, status=%s, keys=%s", external_task_id, status, list(data.keys()))

        if status in ("succeeded", "completed", "success"):
            logger.info("Seedance succeeded response: %s", {
                k: (str(v)[:200] + "..." if isinstance(v, (str, list)) and len(str(v)) > 200 else v)
                for k, v in data.items()
            })
            video_url = None
            resp_content = data.get("content")
            if isinstance(resp_content, dict):
                video_url = resp_content.get("video_url") or resp_content.get("url")
            elif isinstance(resp_content, list):
                for item in resp_content:
                    if isinstance(item, dict):
                        video_url = item.get("video_url") or item.get("url")
                        if video_url:
                            break
            if not video_url:
                video_url = data.get("video_url") or data.get("url")
            logger.info("Seedance video_url: %s", video_url)
            return self._build_result(
                TaskStatusEnum.completed, progress=100, url=video_url,
            )

        if status == "failed":
            error_msg = data.get("error", {})
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            if isinstance(error_msg, str) and "sensitive" in error_msg.lower():
                error_msg = "生成的视频可能包含敏感内容，请修改提示词后重试"
            return self._build_result(
                TaskStatusEnum.failed,
                error=error_msg,
            )

        return self._build_result(TaskStatusEnum.running)
