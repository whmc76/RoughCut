"""Prompt templates for filler word detection."""
from __future__ import annotations


def build_filler_prompt(subtitle_items: list[dict]) -> list[dict]:
    """Build messages for LLM-based filler word detection."""
    items_text = "\n".join(
        f"[{i['index']}] {i['start']:.2f}s-{i['end']:.2f}s: {i['text']}"
        for i in subtitle_items
    )

    system = (
        "你是一个专业的视频剪辑助手，擅长识别口播视频中的语气词、填充词和冗余内容。"
        "你的任务是标注哪些字幕条目主要是填充词，可以被剪掉。"
    )

    user = f"""请分析以下字幕条目，标注哪些是纯填充词/语气词（可以被剪掉）：

{items_text}

常见填充词：嗯、啊、呃、那个、这个、就是、然后、对吧、好吧等。

以 JSON 格式输出：
{{
  "filler_indices": [0, 3, 7],
  "reason": "这些条目主要由填充词组成，没有实质内容"
}}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
