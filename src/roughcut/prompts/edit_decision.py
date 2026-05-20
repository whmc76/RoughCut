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
        "1. 明确的口误重来、反复尝试失败、被人或宠物打断后继续、无意义长停顿，应继续 cut；"
        "2. 说话人如果说“把刚才这段剪掉/前面不算/刚才不要/这段删掉”等，通常是在回指前一段废片；"
        "   你要结合前后字幕判断它是否指向前面十几秒的失败操作、卡壳、重复尝试，而不是只看当前这几个字；"
        "3. 连续重复同一个词、口误多次最后才说顺、绕圈重复表达且后面已有更清楚版本，应倾向 cut；"
        "4. 包含有效讲解、参数、对比、体验、展示提示词的讲话内容，不要误删；"
        "5. 没有台词的片段，如果明显是用于展示对比、细节、特写、上手动作，也应倾向 keep；"
        "6. 证据不足时输出 unsure，不要硬判。"
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
