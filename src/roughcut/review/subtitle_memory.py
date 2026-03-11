from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
from typing import Any


_DOMAIN_ANCHORS = (
    "EDC",
    "工具钳",
    "多功能工具钳",
    "工具",
    "钳",
    "主刀",
    "副刀",
    "刀",
    "钳头",
    "批头",
    "开合",
    "锁定",
    "锁",
    "钢材",
    "柄材",
    "背夹",
    "开箱",
    "评测",
    "战术",
)

_DEFAULT_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "LEATHERMAN": (
        "莱泽曼",
        "来泽曼",
        "来着曼",
        "来泽慢",
        "来自慢",
        "雷泽曼",
        "莱着曼",
    ),
    "工具钳": ("工具前", "工具钱", "工具签"),
    "多功能工具钳": ("多功能工具前", "多功能工具钱"),
    "主刀": ("主到", "主导"),
    "单手开合": ("单手开和", "单手开盒", "单手开核"),
    "钳头": ("前头",),
}


def build_subtitle_review_memory(
    *,
    channel_profile: str | None,
    glossary_terms: list[dict[str, Any]] | None,
    user_memory: dict[str, Any] | None,
    recent_subtitles: list[dict[str, Any]] | None,
    content_profile: dict[str, Any] | None = None,
    term_limit: int = 24,
    example_limit: int = 6,
) -> dict[str, Any]:
    term_scores: Counter[str] = Counter()
    examples: list[dict[str, str]] = []
    alias_pairs: list[dict[str, str]] = []
    seen_examples: set[str] = set()
    seen_aliases: set[tuple[str, str]] = set()

    def remember_term(term: Any, weight: int) -> None:
        value = _normalize_term(term)
        if not value:
            return
        term_scores[value] += max(1, weight)

    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        remember_term((content_profile or {}).get(key), 5)

    for item in (user_memory or {}).get("keyword_preferences") or []:
        remember_term(item.get("keyword"), 4)
        for token in _extract_domain_terms(str(item.get("keyword") or "")):
            remember_term(token, 3)

    field_preferences = (user_memory or {}).get("field_preferences") or {}
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        for item in field_preferences.get(key) or []:
            remember_term(item.get("value"), 4)

    for term in glossary_terms or []:
        correct_form = _normalize_term(term.get("correct_form"))
        if correct_form:
            remember_term(correct_form, 6)
            for wrong_form in term.get("wrong_forms") or []:
                wrong = str(wrong_form or "").strip()
                if not wrong or wrong == correct_form:
                    continue
                pair = (wrong, correct_form)
                if pair not in seen_aliases:
                    seen_aliases.add(pair)
                    alias_pairs.append({"wrong": wrong, "correct": correct_form})

    for row in recent_subtitles or []:
        text = _clean_example_text(
            row.get("text_final") or row.get("text_norm") or row.get("text_raw") or ""
        )
        if not text:
            continue
        for token in _extract_domain_terms(text):
            remember_term(token, 2)
        if _text_has_domain_signal(text) and text not in seen_examples:
            seen_examples.add(text)
            examples.append(
                {
                    "text": text,
                    "source_name": str(row.get("source_name") or ""),
                }
            )
        if len(examples) >= example_limit:
            break

    ranked_terms = [
        {"term": term, "count": count}
        for term, count in term_scores.most_common(term_limit)
    ]

    for item in ranked_terms:
        for wrong in _DEFAULT_TERM_ALIASES.get(item["term"], ()):
            pair = (wrong, item["term"])
            if pair not in seen_aliases:
                seen_aliases.add(pair)
                alias_pairs.append({"wrong": wrong, "correct": item["term"]})

    return {
        "channel_profile": channel_profile or "",
        "terms": ranked_terms,
        "aliases": alias_pairs[:24],
        "style_examples": examples[:example_limit],
    }


def summarize_subtitle_review_memory(review_memory: dict[str, Any] | None) -> str:
    if not review_memory:
        return ""

    lines: list[str] = []
    terms = review_memory.get("terms") or []
    if terms:
        values = " / ".join(str(item.get("term") or "") for item in terms[:16] if item.get("term"))
        if values:
            lines.append(f"- 高优先级术语: {values}")

    aliases = review_memory.get("aliases") or []
    if aliases:
        values = " / ".join(
            f"{item['wrong']}->{item['correct']}"
            for item in aliases[:12]
            if item.get("wrong") and item.get("correct")
        )
        if values:
            lines.append(f"- 常见错写归一: {values}")

    examples = review_memory.get("style_examples") or []
    if examples:
        values = " / ".join(str(item.get("text") or "") for item in examples[:4] if item.get("text"))
        if values:
            lines.append(f"- 同类视频常见表达: {values}")

    return "\n".join(lines)


def build_transcription_prompt(
    *,
    source_name: str,
    channel_profile: str | None,
    review_memory: dict[str, Any] | None,
) -> str:
    snippets: list[str] = []
    if channel_profile:
        snippets.append(f"频道类型：{channel_profile}")

    terms = [str(item.get("term") or "").strip() for item in (review_memory or {}).get("terms") or []]
    terms = [item for item in terms if item][:18]
    if terms:
        snippets.append(f"请优先识别这些术语并保持原词：{', '.join(terms)}")

    alias_pairs = [
        f"{item['wrong']}={item['correct']}"
        for item in (review_memory or {}).get("aliases") or []
        if item.get("wrong") and item.get("correct")
    ][:10]
    if alias_pairs:
        snippets.append(f"常见错写请归一：{'; '.join(alias_pairs)}")

    if _source_name_is_informative(source_name):
        snippets.append(f"源文件名参考：{source_name}")

    return "。".join(snippets)[:500]


def apply_domain_term_corrections(text: str, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result or not review_memory:
        return result

    for item in review_memory.get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct:
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)

    terms = [str(item.get("term") or "").strip() for item in review_memory.get("terms") or []]
    for term in terms:
        for wrong in _DEFAULT_TERM_ALIASES.get(term, ()):
            result = re.sub(re.escape(wrong), term, result, flags=re.IGNORECASE)
        result = _replace_near_match(result, term)
    return result


def _extract_domain_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    compact = str(text or "").strip()
    if not compact:
        return terms

    for match in re.finditer(r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9-]{0,12}(?![A-Z0-9])", compact.upper()):
        token = match.group(0).strip()
        if token and token not in seen:
            seen.add(token)
            terms.append(token)

    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,10}", compact)
    for token in chinese_tokens:
        if any(anchor in token for anchor in _DOMAIN_ANCHORS) and token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


def _text_has_domain_signal(text: str) -> bool:
    upper = text.upper()
    if re.search(r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9-]{0,12}(?![A-Z0-9])", upper):
        return True
    return any(anchor in text for anchor in _DOMAIN_ANCHORS)


def _normalize_term(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", text):
        return text.upper()
    return text[:40]


def _clean_example_text(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    return text[:80]


def _replace_near_match(text: str, term: str) -> str:
    if not text or not term:
        return text
    if re.search(re.escape(term), text, re.IGNORECASE):
        return re.sub(re.escape(term), term, text, flags=re.IGNORECASE)
    if not re.search(r"[\u4e00-\u9fff]", term):
        return text

    candidates: list[tuple[float, int, int]] = []
    term_len = len(term)
    min_len = max(2, term_len - 1)
    max_len = min(len(text), term_len + 1)
    for size in range(min_len, max_len + 1):
        for start in range(0, len(text) - size + 1):
            span = text[start:start + size]
            if span == term:
                return text
            if not _window_can_match(span, term):
                continue
            score = SequenceMatcher(None, span, term).ratio()
            threshold = 0.78 if term_len >= 5 else 0.7 if term_len >= 3 else 0.5
            if score >= threshold:
                candidates.append((score, start, start + size))
    if not candidates:
        return text

    score, start, end = max(candidates, key=lambda item: (item[0], -(item[2] - item[1])))
    if score < 0.6:
        return text
    return f"{text[:start]}{term}{text[end:]}"


def _window_can_match(span: str, term: str) -> bool:
    if not span or span.isdigit():
        return False
    shared = set(span) & set(term)
    if shared:
        return True
    return any(anchor in span and anchor in term for anchor in _DOMAIN_ANCHORS if len(anchor) >= 2)


def _source_name_is_informative(source_name: str) -> bool:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(source_name or "").strip())
    if not stem:
        return False
    if re.fullmatch(r"[\d_-]+", stem):
        return False
    if re.fullmatch(r"\d{8}[_-].+", stem):
        return False
    return True
