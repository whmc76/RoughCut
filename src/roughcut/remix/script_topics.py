from __future__ import annotations

import math
import re
from typing import Any


TOPIC_PLAN_SCHEMA = "roughcut.remix.topic_plan.v1"


def normalize_script_body(text: str) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        lines.append(line)
    return "\n".join(lines)


def split_script_sentences(text: str) -> list[str]:
    normalized = " ".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    parts = re.split(r"(?<=[。！？?])\s*", normalized)
    return [part.strip() for part in parts if part.strip()]


def strip_punctuation(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?：:“”\"'《》]+", "", str(value or ""))


def build_topic_chunks(script_text: str, *, target_count: int) -> list[str]:
    sentences = split_script_sentences(script_text)
    if not sentences:
        stripped = str(script_text or "").strip()
        return [stripped] if stripped else []
    target_count = max(1, min(int(target_count or 1), len(sentences)))
    total_weight = sum(max(1, len(strip_punctuation(sentence))) for sentence in sentences)
    target_weight = max(1, math.ceil(total_weight / target_count))
    chunks: list[str] = []
    current: list[str] = []
    current_weight = 0
    for sentence in sentences:
        weight = max(1, len(strip_punctuation(sentence)))
        if current and current_weight + weight > target_weight and len(chunks) < target_count - 1:
            chunks.append("".join(current).strip())
            current = []
            current_weight = 0
        current.append(sentence)
        current_weight += weight
    if current:
        chunks.append("".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def extract_story_keywords(title: str, text: str, *, limit: int = 48) -> list[str]:
    keywords: list[str] = []
    for item in [title, *re.findall(r"[\u4e00-\u9fff]{2,6}", str(text or ""))]:
        value = str(item or "").strip()
        if len(value) < 2:
            continue
        if value in keywords:
            continue
        if value in {"一个", "这个", "就是", "不是", "可以", "孩子", "我们", "他们", "自己", "今天", "因为", "所以"}:
            continue
        keywords.append(value)
        if len(keywords) >= limit:
            break
    for value in ("示例动画", "宾果", "爸爸", "妈妈", "孩子", "规则", "感受", "愿望", "边界"):
        if value not in keywords:
            keywords.append(value)
    return keywords


def infer_topic_title(text: str, *, fallback: str) -> str:
    compact = strip_punctuation(text)
    for keyword in ("不是", "可以", "不要", "真正", "规则", "感受", "愿望", "边界", "说出来"):
        index = compact.find(keyword)
        if index >= 0:
            return compact[index : index + 10]
    return compact[:10] or strip_punctuation(fallback)[:10] or "主题"


def infer_visual_intent(*, episode_title: str, text: str) -> str:
    keywords = extract_story_keywords(episode_title, text)[:8]
    return f"围绕《{episode_title}》中 {'、'.join(keywords[:4]) or '当前主题'} 的剧情重点，选择一段连续原片画面，不逐句跳切。"


def build_topic_plan_payload(
    *,
    episode: int,
    title: str,
    question: str,
    script_path: str,
    script_text: str,
    clip_starts: list[float],
    clip_durations: list[float],
    source_asr_index_path: str | None,
    min_topic_count: int = 5,
    max_topic_count: int = 8,
) -> dict[str, Any]:
    target_count = max(min_topic_count, min(max_topic_count, len(clip_starts) or min_topic_count))
    topic_chunks = build_topic_chunks(script_text, target_count=target_count)
    topics: list[dict[str, Any]] = []
    for index, chunk in enumerate(topic_chunks):
        clip_index = min(index, max(0, len(clip_starts) - 1))
        clip_start = clip_starts[clip_index] if clip_starts else None
        clip_duration = clip_durations[clip_index] if clip_durations else None
        topics.append(
            {
                "topic_id": f"s02e{int(episode):02d}_topic_{index + 1:02d}",
                "title": infer_topic_title(chunk, fallback=question or title),
                "script_text": chunk,
                "story_keywords": extract_story_keywords(title, chunk)[:12],
                "visual_intent": infer_visual_intent(episode_title=title, text=chunk),
                "selected_clip": {
                    "start_sec": round(float(clip_start), 3) if clip_start is not None else None,
                    "duration_sec": round(float(clip_duration), 3) if clip_duration is not None else None,
                },
            }
        )
    return {
        "schema": TOPIC_PLAN_SCHEMA,
        "episode": int(episode),
        "title": title,
        "question": question,
        "script_path": script_path,
        "script_chars": len(str(script_text or "")),
        "topic_count": len(topics),
        "source_asr_index_path": source_asr_index_path,
        "topics": topics,
    }
