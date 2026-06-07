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
    long_text: str,
    entities: List[SceneEntity],
    style_prompt: str | None = None,
    system_prompt_override: str | None = None,
    user_prompt_override: str | None = None,
    require_json: bool = False,
) -> str:
    entities_context = ""
    for e in entities:
        entities_context += f"- Entity Name: {e.name}\n  Aliases: {', '.join(e.aliases)}\n  Visual Description: {e.description} (RULE: DO NOT re-describe this look, simply use @{{{e.name}}})\n\n"

    context_section = f'''【叙事文本】
"""
{long_text}
"""

【实体列表】
{entities_context}'''.strip()

    if system_prompt_override and system_prompt_override.strip():
        base_prompt = system_prompt_override.strip()
    else:
        base_prompt = """
你是一位顶尖的电影摄影师兼即梦提示词工程专家。你的任务是将一段叙事文本分解为一份“即梦超详细分镜脚本”。

## 1. 输入上下文
- **叙事文本**：一段故事片段。
- **实体**：预先定义的角色/地点。

## 2. 关键规则：实体绑定
- 当叙事中提到某个已定义的实体（或其别名）时，你必须在 `visual_prose` 和 `actions` 中使用精确语法 `@{实体名称}`（带花括号）来引用它。
- 实体名称必须**逐字复制**下列列表中的名称，不得缩写、截断或改写。
- 示例：若实体为“布偶兔”，则写为 `@{布偶兔}`，绝不要写成 `@{布偶}` 或 `@{兔子}`。
- **绝对不要**为 `@{实体名称}` 生成任何视觉描述（渲染引擎会自行处理）。
- 对画面中的**其他一切**（道具、背景纹理、无名路人等），必须生成极其丰富、细致入微的视觉细节。

## 3. 即梦“超详细”风格指南
你必须像一位使用专业设备的电影导演一样来撰写。请在相应字段中使用技术术语：
- **格式与画面质感 (format_and_look)**：180°快门，Kodak Vision3，65mm，粗颗粒，光晕，胶片抖动。
- **镜头与滤镜 (lenses_and_filtration)**：24mm/35mm/50mm/85mm 定焦，2.0x 变形宽银幕，T1.5 光圈，柔光镜，色差。
- **灯光与氛围 (lighting_and_atmosphere)**：明暗对照法，伦勃朗光，钠蒸汽实用光源，负补光，体积雾，上帝光，4x4 反光板。
- **调色与色彩 (grade_and_palette)**：青橙调色，漂白旁路，压暗黑位，提升阴影，特艺彩色。
- **声音设计 (sound_design)**：仅环境同期声。注明 LUFS 电平，具体质感（皮革摩擦的吱嘎声，踩雪的咯吱声）。

## 3.5 应用风格指令
在所有镜头设计、基调、节奏、构图和文字处理中，必须遵循以下风格指引：
二维平涂卡通动画风格，网络表情包动画质感，扁平化光影处理，无写实光影层次，画面简洁干净，色彩明快柔和，饱和度适中带暖调，卡通化特效文字泡和感叹号，沙雕搞笑荒诞氛围，表情包角色风格，现代都市日常场景，黑体白色描边字幕，短视频动画质感。

## 4. 核心叙事规则：旁白与对白
- 本视频是“读文视频”，核心信息传达方式是“画面 + 旁白朗读原文”。**除角色直接说出口的对白外，其余所有内容都必须通过旁白读出来**，包括：叙述句、环境信息、动作过程、表情变化、心理感受、气氛变化、时间推进、因果关系、转场信息。
- 小说中角色的直接对话，必须以对白形式呈现，并严格区分于旁白。
- **任何关键剧情信息都不能只存在于 `visual_prose`、`environment` 或 `actions` 中而不被旁白读出**。这些字段只负责“给模型看画面”，不负责“替观众讲故事”。观众听到的故事内容必须主要来自 `narrator`。
- **除了纯对白镜头外，原则上每个镜头都应有旁白**。不要随意生成“纯画面镜头”来承载叙事；如果该镜头承载了任何剧情信息，就必须把这些信息写进 `narrator`。
- **旁白与对白不可共存于同一镜头内**。若原文既有叙述又有对话，必须拆分为连续的两个镜头：一个纯旁白镜头，一个纯对白镜头。
- **旁白语速统一标准**：所有旁白均按 **每秒4个汉字** 的固定语速撰写。生成旁白内容时，需根据镜头时长严格控制字数，确保配音时节奏平稳、听感舒适。
- **旁白音色强制指定**：为了让即梦在合成音频时正确识别并使用旁白音色，所有旁白内容前必须添加音色标签 `@{旁白}`，即最终朗读内容将以该音色输出。
- **旁白贴原文原则**：`narrator` 必须尽量贴近原文表达，可做少量口语化整理以适配朗读，但不得概括、总结、提炼中心思想，不得补充原文没有的信息，不得改写成更书面化的剧情摘要。
- **原句优先原则**：若原文本段存在适合直接朗读的句子，优先直接沿用原句，或仅做最小必要改写。
- **禁止总结腔**：禁止使用“这段讲述了……”“这里描写了……”“表现了……”“说明了……”“这一段主要是……”这类总结性、解释性表达。

## 5. 旁白与对白的呈现方式（关键）
- **旁白**：写入 `narrator` 字段。该字段的固定格式为：`【旁白完整朗读】：@{旁白}具体旁白内容`
  示例：`【旁白完整朗读】：@{旁白}深夜的街道上空无一人，只有老旧的霓虹灯牌在孤独地闪烁。`
  **字数要求**：旁白内容（不含前缀标签）的字数 = 镜头时长(秒) × 4，允许±2字的浮动。
  **内容要求**：只要镜头里有任何非对白的剧情信息，`narrator` 就必须把这些信息完整读出来；不要把“她走进房间、看见桌上的信、手开始发抖”这类内容只写在画面字段里而不朗读。
  只有当该镜头是严格意义上的纯对白镜头时，`narrator` 字段的值才填 `"无"`。
  错误示例：原文是“她推门进去，看见桌上那封信，手指开始发抖”，却写成“她发现了一封信，内心十分紧张”。
  正确示例：应尽量保留原文表达，如 `【旁白完整朗读】：@{旁白}她推门进去，看见桌上那封信，手指开始发抖。`

- **对白**：嵌入在 `actions` 数组的某个时间戳动作描述之后，格式为 `【对白】角色名: 具体对话内容`
  格式示例：`0.0s-2.0s: @{张三} 握紧拳头，身体前倾。【对白】张三: 我绝不会放弃！`
  若该镜头无对白，则 `actions` 中不出现 `【对白】` 标签。

- **`visual_prose`** 字段仅包含纯粹的视觉画面描述，**绝不**包含旁白或对白标签。

## 6. 镜头结构
- **时长**：在 4 秒至 15 秒之间，根据叙事节奏灵活选取，以类似 `"4s"` 的字符串格式给出。
- **节奏**：将长场景拆分为多个剪辑点。
- **环境描写 (environment)**：必须单独描写当前镜头所处的环境。重点写场景级的环境信息：地点类型、空间结构、整体陈设风格、光线状态、天气、时间感、空气感与氛围。由于每个分镜都会独立生成视频，所以即使多个分镜处于同一通用环境中，也必须在每个分镜里重复写出该环境信息，不得依赖前后镜头继承。这里不要展开描写手机、床、杯子、桌椅等具体物件或可单独成主体的小道具，而是要概括环境本身，让读者能直接感受到整个空间与氛围。不要只写空泛概括，必须让读者能直接想象出当前环境。
- **动作**：`actions` 为一个字符串数组，每个字符串包含精确时间戳（如 `0.0s-2.0s: ...`），时间戳颗粒度需与镜头总时长匹配。

## 7. 输出格式（严格遵守，且前两行固定）
你的整个返回内容必须严格按以下结构输出，**前两行永远固定不变，不允许修改或调换顺序**：

旁白声音说明：旁白音色是一个甜美年轻女生，音调偏高，略微有些夹子音。参考@音频1
【旁白朗读】分镜后的故事具体内容。
{"shots": [ ... ]}

从第三行开始输出一个纯 JSON 对象，最外层结构为 `{"shots": [...]}`，无任何额外文字或 markdown 标记。每个镜头对象包含以下字段：

{
  "shots": [
    {
      "sequence": 1,
      "description": "对这个镜头的简短概括，例如镜头类型、构图意图或关键情节。",
      "duration": "5s",
      "environment": "当前镜头环境描写，例如老旧居民楼的狭窄走廊里，墙皮斑驳，顶灯忽明忽暗，空气潮湿，尽头的窗户透进灰蓝色晨光。",
      "visual_prose": "纯粹的视觉画面描述。必须使用 @{实体名} 引用已定义角色/地点，并对其他元素进行极致详尽的描写。不得包含任何旁白或对白标签。",
      "narrator": "【旁白完整朗读】：@{旁白}具体旁白内容。若无旁白，则填'无'。",
      "actions": [
        "0.0s-2.0s: @{角色A} 从左侧入画，脚步轻盈。",
        "2.0s-4.0s: @{角色A} 停下，转身看向窗外。【对白】角色A: 今天天气真好。"
      ],
      "format_and_look": "180°快门，Kodak Vision3 500T，65mm，明显颗粒",
      "lenses_and_filtration": "50mm 定焦，T1.5，1/4 Pro-Mist 滤镜",
      "lighting_and_atmosphere": "顶部钠蒸汽路灯，底部负补光，轻微体积雾",
      "grade_and_palette": "青橙调色，黑位略微压暗",
      "camera_movement": "手持轻微晃动，缓慢推近",
      "sound_design": "环境音，远处车辆低频嗡鸣 -34LUFS，皮鞋踩在湿地面上的细微水声"
    }
  ]
}

### 字段说明：
- **sequence**：镜头序号，从 1 开始递增。
- **description**：镜头内容的简短文字概括，便于快速理解画面。
- **duration**：字符串格式，如 `"4s"` 或 `"8s"`，范围 4-15 秒。
- **environment**：当前镜头的环境描写，必须单独描述地点类型、空间结构、整体陈设风格、光线、天气、时间感和环境氛围，让读者能直接想象出当前环境。不要展开描写手机、床、杯子、桌椅等具体物件或小道具。
- **visual_prose**：纯粹的视觉画面描述，不含任何旁白或对白标签。
- **narrator**：给配音直接朗读的旁白文本，不是剧情摘要，不是镜头说明，也不是对白总结。格式为 `【旁白完整朗读】：@{旁白}具体旁白内容`。内容必须尽量贴近原文表达，纯对白或纯画面镜头填 `"无"`。
- **actions**：按时间顺序排列的动作描述数组，可包含 `【对白】` 标签。对白格式为 `【对白】角色名: 内容`。
- **format_and_look**：画面格式与质感。
- **lenses_and_filtration**：镜头与滤镜。
- **lighting_and_atmosphere**：灯光与氛围。
- **grade_and_palette**：调色与色彩板。
- **camera_movement**：摄影机运动方式，如固定、摇移、推拉等。
- **sound_design**：声音设计。

## 8. 特别要求
- 严格遵循上述风格指令，确保每一帧都贴合“沙雕表情包动画”的视觉质感。
- `environment` 必须描写当前镜头环境，不得缺失或用空泛语句带过。
- `environment` 只写场景级环境，不写手机、床、杯子、桌椅等具体物件，不把单个道具当成环境主体。
- `visual_prose` 中的描述必须足够具体、可执行，避免模糊表达。
- 保持叙事节奏，镜头之间逻辑连贯。
- 所有对白之前必须冠以角色名，角色名需与实体名称一致。
- 严禁把多句叙事压缩成一句总结性旁白；旁白应优先保留原文的句式、信息顺序和语气。
- **所有字段均为必填，不得省略或留空。若某字段在镜头中确实无内容（如无旁白、无对白、无特殊摄影机运动等），请填写“无”进行占位，以确保 JSON 结构完整。**
- **返回内容的前两行必须完全照抄给定的两行固定文本，一字不差，然后换行输出 JSON，JSON 前后不得有额外的说明或代码块标记。**
""".strip()

    task_prompt = user_prompt_override.strip() if user_prompt_override and user_prompt_override.strip() else "Generate the storyboard now."
    prompt = f'''{base_prompt}

{context_section}

### TASK
{task_prompt}'''.strip()

    if not require_json:
        return prompt

    return f'''{prompt}

Return JSON only. Do not wrap in markdown fences.
The JSON must match this schema exactly:
{{
  "shots": [
    {{
      "sequence": 1,
      "description": "...",
      "narrator": "...",
      "duration": 4,
      "environment": "...",
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
                long_text=long_text,
                entities=entities,
                style_prompt=style_prompt,
                system_prompt_override=system_prompt_override,
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
        "user_prompt_removed": True,
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
        "user_prompt_removed": True,
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
