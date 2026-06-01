import json
from typing import List
from openai import AsyncOpenAI, BadRequestError

from schemas.scene import SceneEntity, Storyboard


async def generate_storyboard(
    client: AsyncOpenAI,
    long_text: str,
    entities: List[SceneEntity],
    model: str
) -> tuple[Storyboard, dict]:
    """
    调用 OpenAI API 生成分镜板

    Returns:
        tuple[Storyboard, dict]: (生成的分镜板, 元数据字典)
    """
    # 构建实体上下文
    entities_context = ""
    for e in entities:
        entities_context += f"- Entity Name: {e.name}\n  Aliases: {', '.join(e.aliases)}\n  Visual Description: {e.description} (RULE: DO NOT re-describe this look, simply use @{{{e.name}}})\n\n"

    # 系统提示词 (System Prompt) - 融入了摄影指导思维
    system_prompt = f"""
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

### 4. SHOT STRUCTURE
- Duration: Strictly 4s or 8s.
- Pacing: Break long scenes into multiple cuts.
- Actions: precise timestamps (0.0s-2.0s).

### DEFINED ENTITIES LIST
{entities_context}
"""

    user_prompt = f"""
### NARRATIVE TEXT TO PROCESS
\"\"\"
{long_text}
\"\"\"

Generate the storyboard now.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

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
        return completion.choices[0].message.parsed, build_metadata(completion)
    except BadRequestError as exc:
        error_message = str(exc)
        if "response_format" not in error_message and "response_format type is unavailable" not in error_message:
            raise

    fallback_user_prompt = f"""
### NARRATIVE TEXT TO PROCESS
\"\"\"
{long_text}
\"\"\"

Generate the storyboard now.

Return JSON only. Do not wrap in markdown fences.
The JSON must match this schema exactly:
{{
  "shots": [
    {{
      "sequence": 1,
      "description": "...",
      "duration": "4s",
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
}}
"""

    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fallback_user_prompt},
        ],
        timeout=600,
        max_completion_tokens=10000,
    )

    content = completion.choices[0].message.content or ""
    if not content:
        raise ValueError("Storyboard model returned empty content")

    try:
        storyboard = Storyboard.model_validate_json(content)
    except Exception:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        storyboard = Storyboard.model_validate(json.loads(content[start:end + 1]))

    return storyboard, build_metadata(completion)
