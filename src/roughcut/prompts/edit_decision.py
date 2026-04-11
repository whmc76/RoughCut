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
        "你是短视频口播剪辑审校助手，只审查高风险删减。"
        "你的任务不是重剪全片，而是判断候选 cut 应该保留删除还是恢复为保留段。"
        "判断标准："
        "1. 明确的口误重来、废话语气词、无意义长停顿，应继续 cut；"
        "2. 包含有效讲解、参数、对比、体验、展示提示词的讲话内容，不要误删；"
        "3. 没有台词的片段，如果明显是用于展示对比、细节、特写、上手动作，也应倾向 keep；"
        "4. 证据不足时输出 unsure，不要硬判。"
        "只输出 JSON。"
    )

    user = (
        "请逐条审查这些高风险删减候选，输出 JSON："
        '{"decisions":[{"candidate_id":"","verdict":"cut|keep|unsure","confidence":0.0,"reason":"","evidence":[] }],"summary":""}'
        f"\n视频上下文：{source_meta or {}}"
        f"\n候选 cut：{candidates}"
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
