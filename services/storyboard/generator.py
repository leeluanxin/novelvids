import json
import logging
from typing import Any, List
from openai import AsyncOpenAI, BadRequestError

from schemas.scene import SceneEntity, Storyboard


logger = logging.getLogger(__name__)


def _coerce_storyboard_payload(payload: Any) -> Storyboard:
    if isinstance(payload, list):
        logger.warning("[storyboard] wrapping bare shots array into Storyboard payload")
        return Storyboard.model_validate({"shots": payload})
    return Storyboard.model_validate(payload)


def _parse_storyboard_content(content: str) -> Storyboard:
    try:
        return _coerce_storyboard_payload(json.loads(content))
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char not in "[{":
                continue
            try:
                payload, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            logger.warning("[storyboard] recovered JSON payload from mixed model output")
            return _coerce_storyboard_payload(payload)
        raise


def build_storyboard_system_prompt(
    entities: List[SceneEntity],
    style_prompt: str | None = None,
    system_prompt_override: str | None = None,
) -> str:
    if system_prompt_override and system_prompt_override.strip():
        return system_prompt_override.strip()

    entities_context = ""
    for e in entities:
        entities_context += f"- Entity Name: {e.name}\n  Aliases: {', '.join(e.aliases)}\n  Visual Description: {e.description} (RULE: DO NOT re-describe this look, simply use @{{{e.name}}})\n\n"

    style_directive = (style_prompt or "").strip()
    style_section = (
        f"\n### 3.5 APPLIED STYLE DIRECTIVE\n- Follow this style guidance across shot design, tone, pacing, composition, and text treatment: {style_directive}\n"
        if style_directive
        else ""
    )

    return f"""
You are an elite Cinematographer (DP) and Sora 2 Prompt Engineering Expert.
Your goal is to break down a narrative text into a "Sora 2 Ultra-Detailed Storyboard".

### 1. INPUT CONTEXT
- **Narrative**: A segment of a story.
- **Entities**: Pre-defined characters/places.

### 2. CRITICAL RULE: ENTITY BINDING
- When the narrative mentions a defined entity (or its alias), you MUST refer to it using the EXACT syntax `@{{EXACT Entity Name}}` with curly braces in `visual_prose` and `actions`.
- Entity names MUST be copied EXACTLY as listed below — do NOT abbreviate, truncate, or paraphrase them.
- Example: if entity is "Rabbit Cloth Doll", write `@{{Rabbit Cloth Doll}}`, NOT `@{{Rabbit Cloth}}` or `@{{Rabbit}}`.
- **NEVER** generate visual descriptions for `@{{Entity Name}}` (the rendering engine handles this).
- **ALWAYS** generate lavish, microscopic visual details for *anything else* (props, background textures, nameless extras).

### 3. SORA 2 "ULTRA-DETAILED" STYLE GUIDE
You must act like a film director using professional equipment. Fill the specific fields with technical jargon:
- **Format**: 180° shutter, Kodak Vision3, 65mm, coarse grain, halation, gate weave.
- **Lens**: 24mm/35mm/50mm/85mm primes, Anamorphic 2.0x, T1.5 aperture, Pro-Mist filters, Chromatic Aberration.
- **Lighting**: Chiaroscuro, Rembrandt, Sodium vapor practicals, Negative fill, Volumetric fog, God rays, 4x4 Bounce.
- **Grade**: Teal & Orange, Bleach bypass, Crushed blacks, Lifted shadows, Technicolor.
- **Sound**: Diegetic only. Mention LUFS levels, specific textures (leather creaking, snow crunching).

{style_section}
### 4. SHOT STRUCTURE
- Duration: Use a numeric duration in seconds. Any positive number is allowed (for example 3, 4, 4.5, 8).
- Pacing: Break long scenes into multiple cuts.
- Actions: precise timestamps (0.0s-2.0s).

### DEFINED ENTITIES LIST
{entities_context}
""".strip()


def build_storyboard_user_prompt(
    long_text: str,
    user_prompt_override: str | None = None,
    require_json: bool = False,
) -> str:
    if user_prompt_override and user_prompt_override.strip():
        base_prompt = user_prompt_override.strip()
    else:
        base_prompt = f'''### NARRATIVE TEXT TO PROCESS
"""
{long_text}
"""

Generate the storyboard now.'''.strip()

    if not require_json:
        return base_prompt

    return f'''{base_prompt}

Return JSON only. Do not wrap in markdown fences.
The JSON must match this schema exactly:
{{
  "shots": [
    {{
      "sequence": 1,
      "description": "...",
      "duration": 4,
      "visual_prose": "...",
      "actions": ["0.0s-2.0s: ..."],
      "format_and_look": "...",
      "lenses_and_filtration": "...",
      "lighting_and_atmosphere": "...",
      "grade_and_palette": "...",
      "camera_movement": "...",
      "sound_design": "..."
    }}
  ]
}}'''.strip()


def build_storyboard_messages(
    long_text: str,
    entities: List[SceneEntity],
    style_prompt: str | None = None,
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
    require_json: bool = False,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": build_storyboard_system_prompt(
                entities=entities,
                style_prompt=style_prompt,
                system_prompt_override=system_prompt_override,
            ),
        },
        {
            "role": "user",
            "content": build_storyboard_user_prompt(
                long_text=long_text,
                user_prompt_override=user_prompt_override,
                require_json=require_json,
            ),
        },
    ]


def _serialize_completion(completion) -> dict[str, Any]:
    raw_content = None
    choices_payload = []

    for choice in getattr(completion, "choices", []) or []:
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        parsed = getattr(message, "parsed", None)
        refusal = getattr(message, "refusal", None)
        if raw_content is None and content:
            raw_content = content

        choices_payload.append(
            {
                "index": getattr(choice, "index", None),
                "finish_reason": getattr(choice, "finish_reason", None),
                "message": {
                    "role": getattr(message, "role", None) if message else None,
                    "content": content,
                    "parsed": parsed.model_dump() if hasattr(parsed, "model_dump") else parsed,
                    "refusal": refusal,
                },
            }
        )

    usage = getattr(completion, "usage", None)
    usage_payload = None
    if usage:
        usage_payload = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
            usage_payload["prompt_tokens_details"] = usage.prompt_tokens_details.model_dump()
        if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
            usage_payload["completion_tokens_details"] = usage.completion_tokens_details.model_dump()

    return {
        "id": getattr(completion, "id", None),
        "model": getattr(completion, "model", None),
        "created": getattr(completion, "created", None),
        "service_tier": getattr(completion, "service_tier", None),
        "system_fingerprint": getattr(completion, "system_fingerprint", None),
        "choices": choices_payload,
        "usage": usage_payload,
        "raw_content": raw_content,
    }


async def generate_storyboard(
    client: AsyncOpenAI,
    long_text: str,
    entities: List[SceneEntity],
    model: str,
    style_prompt: str | None = None,
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
) -> tuple[Storyboard, dict]:
    """
    调用 OpenAI API 生成分镜板

    Returns:
        tuple[Storyboard, dict]: (生成的分镜板, 元数据字典)
    """
    messages = build_storyboard_messages(
        long_text=long_text,
        entities=entities,
        style_prompt=style_prompt,
        system_prompt_override=system_prompt_override,
        user_prompt_override=user_prompt_override,
    )
    request_log = {
        "model": model,
        "base_url": str(getattr(client, "base_url", "")),
        "messages": messages,
        "style_prompt": style_prompt,
        "system_prompt_override": system_prompt_override,
        "user_prompt_override": user_prompt_override,
        "max_completion_tokens": 10000,
        "timeout": 600,
        "structured_output": True,
    }
    logger.info("[storyboard] request=%s", json.dumps(request_log, ensure_ascii=False))

    def build_metadata(completion) -> dict:
        metadata = {
            "model": completion.model,
            "response_id": completion.id,
            "created": completion.created,
            "system_fingerprint": getattr(completion, "system_fingerprint", None),
        }

        if hasattr(completion, "usage") and completion.usage:
            usage = completion.usage
            metadata["usage"] = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }

            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                metadata["usage"]["prompt_tokens_details"] = usage.prompt_tokens_details.model_dump()
            if hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
                metadata["usage"]["completion_tokens_details"] = usage.completion_tokens_details.model_dump()

        if hasattr(completion.choices[0].message, "refusal") and completion.choices[0].message.refusal:
            metadata["refusal"] = completion.choices[0].message.refusal

        return metadata

    try:
        completion = await client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=Storyboard,
            timeout=600,
            max_completion_tokens=10000,
        )
        logger.info(
            "[storyboard] structured_response=%s",
            json.dumps(_serialize_completion(completion), ensure_ascii=False),
        )
        return completion.choices[0].message.parsed, build_metadata(completion)
    except BadRequestError as exc:
        error_message = str(exc)
        logger.warning("[storyboard] structured_request_failed error=%s", error_message)
        if "response_format" not in error_message and "response_format type is unavailable" not in error_message:
            raise

    fallback_messages = build_storyboard_messages(
        long_text=long_text,
        entities=entities,
        style_prompt=style_prompt,
        system_prompt_override=system_prompt_override,
        user_prompt_override=user_prompt_override,
        require_json=True,
    )
    fallback_request_log = {
        "model": model,
        "base_url": str(getattr(client, "base_url", "")),
        "messages": fallback_messages,
        "style_prompt": style_prompt,
        "system_prompt_override": system_prompt_override,
        "user_prompt_override": user_prompt_override,
        "max_completion_tokens": 10000,
        "timeout": 600,
        "structured_output": False,
        "fallback_json": True,
    }
    logger.info("[storyboard] fallback_request=%s", json.dumps(fallback_request_log, ensure_ascii=False))

    completion = await client.chat.completions.create(
        model=model,
        messages=fallback_messages,
        timeout=600,
        max_completion_tokens=10000,
    )
    logger.info(
        "[storyboard] fallback_response=%s",
        json.dumps(_serialize_completion(completion), ensure_ascii=False),
    )

    content = completion.choices[0].message.content or ""
    if not content:
        raise ValueError("Storyboard model returned empty content")

    storyboard = _parse_storyboard_content(content)

    return storyboard, build_metadata(completion)
