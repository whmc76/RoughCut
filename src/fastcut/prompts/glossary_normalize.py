"""Prompt templates for glossary-based text normalization."""
from __future__ import annotations


def build_glossary_prompt(text: str, glossary_terms: list[dict]) -> list[dict]:
    """
    Build messages for LLM-based glossary normalization.
    Returns [{"role": ..., "content": ...}] list.
    """
    term_list = "\n".join(
        f"- 错误形式: {', '.join(t['wrong_forms'])} → 正确: {t['correct_form']}"
        + (f" (类别: {t['category']})" if t.get("category") else "")
        for t in glossary_terms
    )

    system = (
        "你是一个专业的视频字幕校对助手。"
        "你的任务是根据词汇表，检查并纠正字幕中的错误术语。"
        "只修正词汇表中明确列出的错误，不要做其他修改。"
        "以 JSON 格式输出修正结果。"
    )

    user = f"""请检查以下字幕文本，根据词汇表进行纠错：

字幕文本：
{text}

词汇表：
{term_list}

请以 JSON 格式输出，格式如下：
{{
  "corrections": [
    {{
      "original": "错误词",
      "corrected": "正确词",
      "position": 0
    }}
  ],
  "corrected_text": "纠错后的完整文本"
}}

如果没有需要纠错的内容，corrections 为空数组。"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
