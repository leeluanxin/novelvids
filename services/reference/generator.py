from openai import AsyncOpenAI


def _normalize_sentence(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if normalized[-1] in "。！？!?.,;；:：":
        return normalized
    return f"{normalized}。"


def build_sora_compatible_prompt(data, style=None):
    asset_type = data.get("type")
    name = str(data.get("canonical_name") or "").strip()
    traits = str(data.get("base_traits") or "").strip()
    desc = str(data.get("description") or "").strip()
    style = style if isinstance(style, dict) else {}
    style_name = str(style.get("name") or "").strip()
    style_prompt = str(style.get("positive_prompt") or "").strip()

    subject_clause = {
        "person": f"角色设计稿：{name}的全身三视图（正面、侧面、背面）",
        "item": f"{name}的多角度产品展示",
        "scene": f"{name}的宏大全景图",
    }.get(asset_type, name)

    detail_parts = []
    if style_prompt:
        detail_parts.append(style_prompt)
    elif style_name:
        detail_parts.append(f"整体风格参考「{style_name}」")

    if asset_type == "person":
        detail_parts.extend([
            f"视觉特征锚点：{traits}" if traits else "",
            desc,
            "全身三视图一致",
            "白色背景",
            "平铺光",
            "人体比例严谨",
            "面部特征高度清晰且一致",
        ])
    elif asset_type == "item":
        detail_parts.extend([
            f"特征：{traits}" if traits else "",
            desc,
            "多角度展示",
            "摄影棚灯光",
            "微距镜头",
            "材质纹理锐利",
            "工作室渲染效果",
        ])
    elif asset_type == "scene":
        detail_parts.extend([
            f"空间架构：{traits}" if traits else "",
            desc,
            "广角视角",
            "丁达尔效应",
            "细腻的光影层次",
            "空间立体感强",
        ])
    else:
        detail_parts.extend([traits, desc])

    detail_clause = "，".join(part for part in detail_parts if part)
    prompt_parts = [subject_clause, _normalize_sentence(detail_clause)]
    return "".join(part for part in prompt_parts if part)


async def generate_for_sora_consistency(client: AsyncOpenAI, data, reference_images=None, model="doubao-seedream-4-5-251128", style=None):
    """
    执行生成任务，支持多图参考 (异步)
    """
    final_prompt = build_sora_compatible_prompt(data, style=style)

    extra_body = {
        "sequential_image_generation": "disabled",
        "watermark": False
    }

    # 兼容 OpenAI 格式，将 image 参数放入 extra_body
    if reference_images:
        extra_body["image"] = reference_images

    try:
        response = await client.images.generate(
            model=model,
            prompt=final_prompt,
            size="2K",  # 建议 2K，若需更高精度可在控制台设为 4K
            response_format="url",
            n=1, # 显式指定只生成一张
            extra_body=extra_body
        )
        return response.data
    except Exception as e:
        print(f"生成异常: {e}")
        raise e
