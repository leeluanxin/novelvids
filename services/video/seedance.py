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

# 匹配 @{Name} 和 @Name（兼容旧格式）
_ENTITY_RE = re.compile(r"@\{([^}]+)\}|@([\w一-鿿·]+)")

MAX_REF_IMAGES = 4
INLINE_RESULT_PREFIX = "cli-result:"


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


def _guess_file_extension(image_url: str, content_type: str | None = None) -> str:
    path_ext = os.path.splitext(urlparse(image_url).path)[1].lower()
    if path_ext in {".jpg", ".jpeg", ".png", ".webp"}:
        return path_ext

    if content_type:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized == "image/jpeg":
            return ".jpg"
        if normalized == "image/png":
            return ".png"
        if normalized == "image/webp":
            return ".webp"

    return ".png"


async def _materialize_cli_image(image_url: str, index: int) -> str:
    if image_url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            suffix = _guess_file_extension(image_url, response.headers.get("content-type"))
            with tempfile.NamedTemporaryFile(
                prefix=f"dreamina-video-ref-{index}-",
                suffix=suffix,
                dir=settings.MEDIA_PATH,
                delete=False,
            ) as tmp:
                tmp.write(response.content)
                return tmp.name

    if image_url.startswith("data:"):
        header, _, data = image_url.partition(",")
        if not data:
            raise Exception("CLI reference image data URL is invalid")

        mime_match = re.match(r"data:([^;]+)", header)
        suffix = _guess_file_extension("", mime_match.group(1) if mime_match else None)
        with tempfile.NamedTemporaryFile(
            prefix=f"dreamina-video-ref-{index}-",
            suffix=suffix,
            dir=settings.MEDIA_PATH,
            delete=False,
        ) as tmp:
            tmp.write(base64.b64decode(data))
            return tmp.name

    if image_url.startswith("/media/"):
        return os.path.join(settings.MEDIA_PATH, image_url[len("/media/"):])

    if os.path.exists(image_url):
        return image_url

    raise Exception("CLI reference image must be a remote URL, data URL, or local file path")


class SeedanceGenerator(BaseVideoGenerator):
    """Seedance/即梦 平台视频生成。

    Submit: POST {base_url}/contents/generations/tasks
    Query:  GET  {base_url}/contents/generations/tasks/{task_id}
    Auth:   Bearer {api_key}
    """

    @staticmethod
    def _process_prompt(
        prompt: str,
        subjects: list[dict[str, Any]] | None,
    ) -> tuple[str, list[str]]:
        """处理 prompt 中的 @资产引用，返回 (处理后的 prompt, 参考图列表)。

        规则:
        - 收集所有资产的参考图，上限 MAX_REF_IMAGES 张
        - 有参考图的资产: @{Name} -> [Name]
        - 无参考图 / 超出上限的资产: @{Name} -> 资产描述文本
        """
        if not subjects:
            return _ENTITY_RE.sub(lambda m: m.group(1) or m.group(2), prompt), []

        subj_map: dict[str, dict[str, Any]] = {s["name"]: s for s in subjects}
        ref_images: list[str] = []
        name_to_index: dict[str, int] = {}

        for subj in subjects:
            if len(ref_images) >= MAX_REF_IMAGES:
                break
            images = subj.get("images", [])
            if images:
                ref_images.append(images[0])
                name_to_index[subj["name"]] = len(ref_images)

        def _replace(m: re.Match) -> str:
            name = m.group(1) or m.group(2)
            subj = subj_map.get(name)
            if not subj:
                return name
            idx = name_to_index.get(subj["name"])
            if idx is not None:
                return f"[图{idx}]"
            return subj.get("description") or subj["name"]

        processed = _ENTITY_RE.sub(_replace, prompt)
        return processed, ref_images

    async def submit(
        self,
        prompt: str,
        negative_prompt: str = "",
        subjects: list[dict[str, Any]] | None = None,
        duration: float = 6.0,
        aspect_ratio: str = "16:9",
        **kwargs,
    ) -> str:
        processed_prompt, ref_images = self._process_prompt(prompt, subjects)

        if (self.config.invocation_type or "api").lower() == "cli":
            if not self.config.cli_command:
                raise Exception("CLI video generation requires cli_command")

            local_ref_images: list[str] = []
            try:
                cli_duration = min(15, max(4, int(round(duration))))
                args = [
                    "multimodal2video" if ref_images else "text2video",
                    f"--prompt={processed_prompt}",
                    f"--duration={cli_duration}",
                    "--poll=120",
                ]
                if ref_images:
                    args.append(f"--ratio={aspect_ratio}")
                elif aspect_ratio:
                    args.append(f"--ratio={aspect_ratio}")
                if self.config.model and self.config.model != "dreamina":
                    args.append(f"--model_version={self.config.model}")
                for index, image_url in enumerate(ref_images[:MAX_REF_IMAGES], start=1):
                    local_path = await _materialize_cli_image(image_url, index)
                    local_ref_images.append(local_path)
                    args.append(f"--image={local_path}")

                output = await _run_cli_json(self.config.cli_command, args)
                logger.info("Dreamina CLI submit output: %s", _clip_for_log(output))
            finally:
                for local_path in local_ref_images:
                    try:
                        if os.path.basename(local_path).startswith("dreamina-video-ref-"):
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

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Seedance _process_prompt: subjects=%d, ref_images=%d, prompt[:80]=%r",
            len(subjects or []), len(ref_images), processed_prompt[:80],
        )

        model_name = self.config.model
        supports_images = "i2v" in model_name or "t2v" in model_name
        if ref_images and "t2v" in model_name:
            model_name = model_name.replace("t2v", "i2v")
            logger.info("Seedance auto-switch: t2v -> i2v (has images)")
        elif not ref_images and "i2v" in model_name:
            model_name = model_name.replace("i2v", "t2v")
            logger.info("Seedance auto-switch: i2v -> t2v (no images)")
        elif ref_images and not supports_images:
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
            "model": model_name,
            "content": content,
            "duration": int(duration),
            "watermark": False,
        }

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
        if (self.config.invocation_type or "api").lower() == "cli":
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
