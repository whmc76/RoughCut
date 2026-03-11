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
