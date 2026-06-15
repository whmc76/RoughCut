"""Prompt templates for LLM-assisted edit decisions."""
from __future__ import annotations


def build_edit_decision_prompt(transcript_summary: str, silence_info: str) -> list[dict]:
    """Build messages for LLM-based edit decision review."""
    system = (
        "你是一个专业的视频剪辑师，擅长口播和开箱视频的后期制作。"
        "你的任务是审查自动剪辑决策，判断哪些剪辑合理，哪些需要调整。"
    )

    user = f"""请审查以下自动剪辑分析结果：

转写摘要：
{transcript_summary}

静音段落信息：
{silence_info}

请以 JSON 格式给出建议：
{{
  "approved_cuts": ["silence at 5.2s-6.8s", ...],
  "rejected_cuts": [...],
  "additional_cuts": [
    {{"start": 10.0, "end": 11.5, "reason": "重复内容"}}
  ],
  "notes": "整体节奏较好，建议..."
}}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_high_risk_cut_review_prompt(
    *,
    source_meta: dict[str, object] | None,
    candidates: list[dict[str, object]],
) -> list[dict[str, str]]:
    system = (
        "你是短视频口播剪辑审校助手，重点判断哪些内容真实影响成片节奏。"
        "你的任务不是重剪全片，而是判断候选 cut 应该保留删除还是恢复为保留段。"
        "判断标准："
        "1. 必须基于候选片段、前后字幕、转写上下文和视频语义做整体判断，绝不能按固定词表或关键词直接匹配；"
        "2. 明确的口误重来、反复尝试失败且后面已有成功展示、被他人或噪音打断后继续、无意义长停顿，应继续 cut；"
        "3. 说话人如果表达了回删/前面不要/重说等剪辑意图，通常是在回指前一段废片；"
        "   你要结合前后字幕判断它是否指向前面十几秒的失败操作、卡壳、重复尝试，而不是只看当前这几个字；"
        "4. 连续重复同一展示或同一台词，前面失败/口误，后面已有更清楚或成功版本，应倾向 cut；"
        "5. 包含有效讲解、参数、对比、体验、展示进展的内容，不要误删；"
        "6. 没有台词的片段，如果明显是用于展示对比、细节、特写、上手动作，也应倾向 keep；"
        "7. 证据不足时输出 unsure，不要硬判。"
        "只输出 JSON。"
    )

    user = (
        "请逐条审查这些高风险删减候选，输出 JSON："
        '{"decisions":[{"candidate_id":"","verdict":"cut|keep|unsure","confidence":0.0,"reason":"","evidence":[] }],"summary":""}'
        "\n审查时特别注意：candidate.reason=rollback_instruction 表示候选来自口播中的剪辑指令，"
        "例如“把刚才这段剪掉”或 ASR 近似误写成“就是减6”。"
        "这类候选如果前段确实是操作失误、反复试错、被打断或重新组织语言，应 verdict=cut；"
        "如果前段其实是有效展示/讲解，则 verdict=keep 或 unsure。"
        f"\n视频上下文：{source_meta or {}}"
        f"\n候选 cut：{candidates}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_waste_segment_discovery_prompt(
    *,
    source_meta: dict[str, object] | None,
    subtitle_context: list[dict[str, object]],
) -> list[dict[str, str]]:
    system = (
        "你是短视频粗剪审片师，任务是主动发现废片候选。"
        "必须基于连续字幕、时间关系、上下文语义和视频主题做判断，绝不能按固定词表或关键词直接匹配。"
        "只输出确有上下文证据的候选；证据不足就不要输出。"
        "重点识别："
        "1. failed_attempt：重复展示失败、操作失败、尝试无效，后面已有成功或更完整展示，只保留最后成功段；"
        "2. restart_retake：多次口误、重说同一句或同一观点，后面已有更清楚版本；"
        "3. rollback_instruction：说话人表达前面不要、回删、重来等剪辑意图，且前面确实是废片；"
        "4. off_topic_interruption：他人、电话、噪音、离题对话等明显不属于视频主题的打断；"
        "5. long_non_dialogue：长时间无信息推进，既没有有效口播，也不是产品细节/操作展示。"
        "不要把正常停顿、产品特写、对比观察、上手操作、参数讲解判为废片。"
        "候选边界要覆盖应删除的完整废片段，不要只框住触发句。"
        "只输出 JSON。"
    )
    user = (
        "请从下面字幕时间线中发现废片候选，输出 JSON："
        '{"candidates":[{"start":0.0,"end":0.0,"reason":"failed_attempt|restart_retake|rollback_instruction|off_topic_interruption|long_non_dialogue","confidence":0.0,"summary":"","evidence":[]}],"summary":""}'
        f"\n视频上下文：{source_meta or {}}"
        f"\n字幕时间线：{subtitle_context}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

def build_multimodal_trim_review_batch_prompt(
    *,
    source_meta: dict[str, object] | None,
    candidates: list[dict[str, object]],
) -> str:
    return (
        "你是短视频口播剪辑的多模态复核助手。"
        "你会同时参考视频关键帧和候选删减文本，判断每个候选片段应该删除、保留还是保持不确定。"
        "判断标准："
        "1. 必须结合画面、候选文本和前后上下文判断，绝不能用固定关键词或词表直接判定；"
        "2. 明显没有信息推进、只是拖沓铺垫、失败尝试、空泛重复、转手等待、离题打断，倾向 cut；"
        "3. 含有真实参数、型号、功能结论、对比结论、关键展示动作，倾向 keep；"
        "4. 画面如果明显在演示细节、对比、上手动作，即使文本弱，也不要轻易 cut；"
        "5. 证据不足时输出 unsure，不要强判。"
        "只输出 JSON，不要解释。"
        "\n输出格式："
        '{"decisions":[{"candidate_id":"","verdict":"cut|keep|unsure","confidence":0.0,"reason":"","evidence":[],"summary":""}],"summary":""}'
        f"\n视频上下文：{source_meta or {}}"
        f"\n候选片段列表：{candidates}"
        "\n图片按照候选列表顺序分组排列；每个候选的 frame_indices 表示它对应的图片序号范围。"
        "\n请为每个 candidate_id 输出一条 decision。"
    )
