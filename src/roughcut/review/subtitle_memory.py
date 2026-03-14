from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
from typing import Any

from roughcut.review.domain_glossaries import detect_glossary_domains, merge_glossary_terms, resolve_builtin_glossary_terms


_DOMAIN_ANCHORS = (
    "EDC",
    "FAS",
    "NOC",
    "REATE",
    "LEATHERMAN",
    "OLIGHT",
    "ZIPPO",
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
    "贴片",
    "电镀",
    "渐变",
    "图纸",
    "顶配",
    "次顶配",
    "标配",
    "高配",
    "低配",
    "钢马",
    "锆马",
    "钛马",
    "铜马",
    "大马",
    "大马士革",
    "美中不足",
    "极致",
    "华丽",
    "彩雕",
    "深雕",
    "阳极",
    "镜面",
    "拉丝",
    "雾面",
    "开箱",
    "评测",
    "战术",
    "RunningHub",
    "ComfyUI",
    "OpenClaw",
    "无限画布",
    "工作流",
    "节点",
    "智能体",
    "MCP",
    "RAG",
    "LoRA",
    "潮玩",
    "手电",
    "打火机",
    "机能",
    "户外",
    "露营",
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
    "螺丝": ("螺四", "罗丝", "罗四", "螺司", "锣丝"),
    "螺丝刀": ("罗丝刀", "螺四刀"),
    "实用": ("执用",),
    "贴片": ("揭片", "接片"),
    "电镀": ("电路", "电渡", "店镀"),
    "渐变": ("键变", "间变", "见变"),
    "图纸": ("图指", "图址", "图子"),
    "FAS": ("法斯", "发斯", "F A S"),
    "NOC": ("N O C",),
    "REATE": ("锐特", "瑞特", "睿特"),
    "EDC": ("一滴西", "诶滴西", "E D C"),
    "OLIGHT": ("傲雷", "O LIGHT"),
    "ZIPPO": ("芝宝", "Z I P P O"),
    "RunningHub": ("running hub", "瑞宁哈布", "润宁哈布", "RH"),
    "ComfyUI": ("comfy ui", "康菲UI", "康飞UI", "咖啡外"),
    "OpenClaw": ("open claw", "欧喷扣", "欧喷爪"),
    "无限画布": ("无边画布", "无限画板"),
    "工作流": ("工作留", "工做流"),
    "节点编排": ("节点排布",),
    "智能体": ("智能提",),
    "LoRA": ("罗拉", "L O R A"),
    "MCP": ("M C P",),
    "美中不足": ("美中部组", "美中不组", "美中布足"),
    "极致华丽": ("经质的华历", "经质华历", "经致的华历", "精质的华历", "经质的华丽", "经致的华丽"),
    "镜面": ("静面", "净面"),
    "顶配": ("定配", "顶陪"),
    "次顶配": ("次定配", "次顶陪"),
    "标配": ("表配",),
    "高配": ("高陪",),
    "低配": ("低陪",),
    "钢马": ("刚马",),
    "锆马": ("告马", "造马"),
    "钛马": ("太马",),
    "铜马": ("同马",),
    "大马士革": ("大马是个", "大马事革"),
    "潮玩": ("朝玩",),
    "手电": ("手店",),
    "打火机": ("打火鸡",),
    "机能": ("肌能",),
}

_GENERIC_SAFE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"执用"), "实用"),
    (re.compile(r"(?:螺四|罗丝|罗四|螺司|锣丝)(?=(?:刀|批|口|位|孔|头|帽|钉|拧|拆|装|固定|调节|上|下|很|太|比较|特别|非常|也|都|就|了|的|$))"), "螺丝"),
    (re.compile(r"美中(?:部组|不组|布足)"), "美中不足"),
    (re.compile(r"(?:电路|电渡|店镀)(?=(?:层|工艺|处理|效果|件|色|色泽|面|一下|了|的|,|，|。|$))"), "电镀"),
    (re.compile(r"(?:键变|间变|见变)"), "渐变"),
    (re.compile(r"(?:揭片|接片)(?=(?:是|都|也|做|用|件|片|,|，|。|$))"), "贴片"),
    (re.compile(r"(?:图指|图址|图子)(?=(?:稿|方案|设计|修改|确认|看|,|，|。|$))"), "图纸"),
    (re.compile(r"(?:法斯|发斯)(?![A-Za-z])", re.IGNORECASE), "FAS"),
    (re.compile(r"N\s*O\s*C", re.IGNORECASE), "NOC"),
    (re.compile(r"(?:一滴西|诶滴西)(?![A-Za-z])", re.IGNORECASE), "EDC"),
    (re.compile(r"(?:锐特|瑞特|睿特)(?![A-Za-z])", re.IGNORECASE), "REATE"),
    (re.compile(r"(?:傲雷|O\s*LIGHT)(?![A-Za-z])", re.IGNORECASE), "OLIGHT"),
    (re.compile(r"(?:芝宝|Z\s*I\s*P\s*P\s*O)(?![A-Za-z])", re.IGNORECASE), "ZIPPO"),
    (re.compile(r"running\s*hub|(?<![A-Za-z0-9])RH(?![A-Za-z0-9])", re.IGNORECASE), "RunningHub"),
    (re.compile(r"comfy\s*ui|咖啡外", re.IGNORECASE), "ComfyUI"),
    (re.compile(r"open\s*claw", re.IGNORECASE), "OpenClaw"),
    (re.compile(r"无边画布|无限画板"), "无限画布"),
    (re.compile(r"工作留|工做流"), "工作流"),
    (re.compile(r"节点排布"), "节点编排"),
    (re.compile(r"智能提"), "智能体"),
    (re.compile(r"(?:罗拉|L\s*O\s*R\s*A)", re.IGNORECASE), "LoRA"),
    (re.compile(r"M\s*C\s*P", re.IGNORECASE), "MCP"),
    (re.compile(r"(?:经质的华历|经质华历|经致的华历|精质的华历|经质的华丽|经致的华丽)"), "极致华丽"),
    (re.compile(r"极致的华历"), "极致华丽"),
    (re.compile(r"极致华历"), "极致华丽"),
    (re.compile(r"(?:静面|净面)(?=(?:处理|效果|质感|工艺|版|板|层|一下|了|的|,|，|。|$))"), "镜面"),
    (re.compile(r"华丽历(?=(?:很|也|都|更|,|，|。|$))"), "华丽"),
    (re.compile(r"华历(?=(?:感|风格|路线|效果|,|，|。|$))"), "华丽"),
)

_PRESERVE_CASE_TERMS = {
    "RunningHub",
    "ComfyUI",
    "OpenClaw",
    "OpenAI",
    "Claude",
    "Gemini",
    "LoRA",
    "Checkpoint",
    "ControlNet",
    "Flux",
}


def build_subtitle_review_memory(
    *,
    channel_profile: str | None,
    glossary_terms: list[dict[str, Any]] | None,
    user_memory: dict[str, Any] | None,
    recent_subtitles: list[dict[str, Any]] | None,
    content_profile: dict[str, Any] | None = None,
    include_recent_terms: bool = True,
    include_recent_examples: bool = True,
    term_limit: int = 30,
    example_limit: int = 6,
) -> dict[str, Any]:
    term_scores: Counter[str] = Counter()
    examples: list[dict[str, str]] = []
    alias_pairs: list[dict[str, str]] = []
    seen_examples: set[str] = set()
    seen_aliases: set[tuple[str, str]] = set()
    builtin_glossary_terms = resolve_builtin_glossary_terms(
        channel_profile=channel_profile,
        content_profile=content_profile,
        subtitle_items=recent_subtitles,
    )
    direct_domains = set(
        detect_glossary_domains(
            channel_profile=channel_profile,
            content_profile=content_profile,
            subtitle_items=recent_subtitles,
        )
    )
    effective_glossary_terms = merge_glossary_terms(
        glossary_terms or [],
        builtin_glossary_terms,
    )
    context_text = " ".join(
        str(item or "")
        for item in [
            *((content_profile or {}).get(key) or "" for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary", "hook_line")),
            *(row.get("text_final") or row.get("text_norm") or row.get("text_raw") or "" for row in (recent_subtitles or [])),
        ]
    )

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
        for token in _extract_hotword_candidates(str(item.get("keyword") or "")):
            remember_term(token, 2)
        for token in _extract_compound_domain_terms(str(item.get("keyword") or "")):
            remember_term(token, 8)

    for item in (user_memory or {}).get("phrase_preferences") or []:
        remember_term(item.get("phrase"), 5)
        for token in _extract_compound_domain_terms(str(item.get("phrase") or "")):
            remember_term(token, 10)

    field_preferences = (user_memory or {}).get("field_preferences") or {}
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        for item in field_preferences.get(key) or []:
            remember_term(item.get("value"), 4)
            for token in _extract_compound_domain_terms(str(item.get("value") or "")):
                remember_term(token, 8)

    for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary", "hook_line"):
        value = (content_profile or {}).get(key)
        remember_term(value, 4 if key in {"subject_brand", "subject_model", "subject_type"} else 3)
        for token in _extract_compound_domain_terms(str(value or "")):
            remember_term(token, 10 if key in {"video_theme", "summary", "hook_line"} else 8)

    for item in (user_memory or {}).get("recent_corrections") or []:
        corrected_value = item.get("corrected_value")
        original_value = item.get("original_value")
        remember_term(corrected_value, 4)
        for token in _extract_hotword_candidates(str(corrected_value or "")):
            remember_term(token, 3)
        for token in _extract_compound_domain_terms(str(corrected_value or "")):
            remember_term(token, 10)
        if _should_promote_correction_alias(original_value, corrected_value):
            wrong = _normalize_alias_value(original_value)
            correct = _normalize_alias_value(corrected_value)
            if wrong and correct and wrong != correct and (wrong, correct) not in seen_aliases:
                seen_aliases.add((wrong, correct))
                alias_pairs.append({"wrong": wrong, "correct": correct})

    for term in effective_glossary_terms:
        correct_form = _normalize_term(term.get("correct_form"))
        if correct_form:
            term_domain = str(term.get("domain") or "").strip()
            context_bonus = 2 if _term_matches_context(term, context_text) else 0
            if not term_domain:
                remember_term(correct_form, 6 + context_bonus)
            elif term_domain in direct_domains:
                remember_term(correct_form, 6 + context_bonus)
            else:
                remember_term(correct_form, 3 + context_bonus)

    for row in recent_subtitles or []:
        text = _clean_example_text(
            row.get("text_final") or row.get("text_norm") or row.get("text_raw") or ""
        )
        if not text:
            continue
        if include_recent_terms:
            for token in _extract_domain_terms(text):
                remember_term(token, 2)
            for token in _extract_hotword_candidates(text):
                remember_term(token, 1)
            for token in _extract_compound_domain_terms(text):
                remember_term(token, 8)
        if include_recent_examples and _text_has_domain_signal(text) and text not in seen_examples:
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
    ranked_term_order = [str(item.get("term") or "").strip() for item in ranked_terms if item.get("term")]
    ranked_term_values = set(ranked_term_order)
    ranked_term_priority = {term: index for index, term in enumerate(ranked_term_order)}

    def append_aliases(
        term_collection: list[dict[str, Any]] | None,
        *,
        only_ranked_terms: bool,
    ) -> None:
        collected: list[tuple[int, str, str]] = []
        for term in term_collection or []:
            correct_form = _normalize_term(term.get("correct_form"))
            if not correct_form:
                continue
            if only_ranked_terms and correct_form not in ranked_term_values:
                continue
            priority = ranked_term_priority.get(correct_form, len(ranked_term_priority))
            for wrong_form in term.get("wrong_forms") or []:
                wrong = str(wrong_form or "").strip()
                if not wrong or wrong == correct_form:
                    continue
                collected.append((priority, wrong, correct_form))
        for _, wrong, correct_form in sorted(collected, key=lambda item: (item[0], len(item[1]), item[2], item[1])):
            pair = (wrong, correct_form)
            if pair not in seen_aliases:
                seen_aliases.add(pair)
                alias_pairs.append({"wrong": wrong, "correct": correct_form})

    append_aliases(glossary_terms or [], only_ranked_terms=True)

    for term in ranked_term_order:
        for wrong in _DEFAULT_TERM_ALIASES.get(term, ()):
            pair = (wrong, term)
            if pair not in seen_aliases:
                seen_aliases.add(pair)
                alias_pairs.append({"wrong": wrong, "correct": term})

    append_aliases(builtin_glossary_terms, only_ranked_terms=False)
    ranked_terms.sort(key=lambda item: (-_is_compound_domain_term(item["term"]), -int(item.get("count") or 0), item["term"]))

    return {
        "channel_profile": channel_profile or "",
        "terms": ranked_terms,
        "aliases": alias_pairs[:120],
        "style_examples": examples[:example_limit],
        "style_preferences": list((user_memory or {}).get("style_preferences") or [])[:8],
    }


def summarize_subtitle_review_memory(review_memory: dict[str, Any] | None) -> str:
    return _summarize_subtitle_review_memory(review_memory, include_examples=True)


def summarize_subtitle_review_memory_for_polish(review_memory: dict[str, Any] | None) -> str:
    return _summarize_subtitle_review_memory(review_memory, include_examples=False)


def _summarize_subtitle_review_memory(
    review_memory: dict[str, Any] | None,
    *,
    include_examples: bool,
) -> str:
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
    if include_examples and examples:
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
    terms = [item for item in terms if item][:12]
    if terms:
        snippets.append(f"热词：{', '.join(terms)}")
        snippets.append("请保持品牌、型号、圈内术语原词")

    alias_pairs = [
        f"{item['wrong']}={item['correct']}"
        for item in (review_memory or {}).get("aliases") or []
        if item.get("wrong") and item.get("correct")
    ][:8]
    if alias_pairs:
        snippets.append(f"错写归一：{'; '.join(alias_pairs)}")

    if _source_name_is_informative(source_name):
        snippets.append(f"源文件名参考：{source_name}")

    return "。".join(snippets)[:320]


def apply_domain_term_corrections(text: str, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result

    for pattern, replacement in _GENERIC_SAFE_REPLACEMENTS:
        result = pattern.sub(replacement, result)

    if not review_memory:
        return result

    for item in review_memory.get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct:
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)

    terms = [str(item.get("term") or "").strip() for item in review_memory.get("terms") or []]
    for term in terms:
        aliases = _DEFAULT_TERM_ALIASES.get(term, ())
        for wrong in aliases:
            result = re.sub(re.escape(wrong), term, result, flags=re.IGNORECASE)
        if not aliases:
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


def _extract_hotword_candidates(text: str) -> list[str]:
    compact = str(text or "").strip()
    if not compact:
        return []
    seen: set[str] = set()
    tokens: list[str] = []
    for token in re.findall(r"[A-Za-z0-9+-]{2,24}|[\u4e00-\u9fff]{2,10}", compact):
        normalized = _normalize_term(token)
        if not normalized:
            continue
        if len(normalized) < 2:
            continue
        if normalized in seen:
            continue
        if normalized.isdigit():
            continue
        if _text_has_domain_signal(normalized) or normalized in _DEFAULT_TERM_ALIASES:
            seen.add(normalized)
            tokens.append(normalized)
    return tokens


def _extract_compound_domain_terms(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return []
    seen: set[str] = set()
    phrases: list[str] = []
    for fragment in re.split(r"[，。,\.、；;：:\-—\(\)（）\[\]【】\s]+", compact):
        candidate = _trim_to_anchor_span(fragment)
        for part in _split_compound_candidate(candidate):
            normalized = _normalize_term(part)
            if not normalized:
                continue
            if len(normalized) < 4 or len(normalized) > 18:
                continue
            if normalized in seen:
                continue
            if _count_domain_anchor_hits(normalized) < 2:
                continue
            seen.add(normalized)
            phrases.append(normalized)
    return phrases


def _text_has_domain_signal(text: str) -> bool:
    upper = text.upper()
    if re.search(r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9-]{0,12}(?![A-Z0-9])", upper):
        return True
    return any(anchor in text for anchor in _DOMAIN_ANCHORS)


def _count_domain_anchor_hits(text: str) -> int:
    return sum(1 for anchor in _DOMAIN_ANCHORS if anchor in text)


def _trim_to_anchor_span(text: str) -> str:
    fragment = str(text or "").strip()
    if not fragment:
        return ""
    spans: list[tuple[int, int]] = []
    for anchor in _DOMAIN_ANCHORS:
        start = fragment.find(anchor)
        if start >= 0:
            spans.append((start, start + len(anchor)))
    if len(spans) < 2:
        return fragment
    left = min(start for start, _ in spans)
    right = max(end for _, end in spans)
    return fragment[left:right]


def _split_compound_candidate(text: str) -> list[str]:
    candidate = str(text or "").strip()
    if not candidate:
        return []
    parts = [part.strip() for part in re.split(r"[和与及]", candidate) if part.strip()]
    enriched = [part for part in parts if _count_domain_anchor_hits(part) >= 2]
    if enriched:
        return enriched
    return [candidate]


def _normalize_term(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if text in _PRESERVE_CASE_TERMS:
        return text
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", text):
        return text.upper()
    return text[:40]


def _is_compound_domain_term(value: str) -> int:
    text = str(value or "").strip()
    return 1 if len(text) >= 4 and _count_domain_anchor_hits(text) >= 2 else 0


def _normalize_alias_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:40]


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


def _should_promote_correction_alias(original_value: Any, corrected_value: Any) -> bool:
    original = _normalize_alias_value(original_value)
    corrected = _normalize_alias_value(corrected_value)
    if not original or not corrected or original == corrected:
        return False
    if len(original) < 2 or len(corrected) < 2:
        return False
    if len(original) > 20 or len(corrected) > 20:
        return False
    if _text_has_domain_signal(original) or _text_has_domain_signal(corrected):
        return True
    score = SequenceMatcher(None, original, corrected).ratio()
    return score >= 0.45


def _term_matches_context(term: dict[str, Any], context_text: str) -> bool:
    context = str(context_text or "").strip()
    if not context:
        return False
    correct_form = str(term.get("correct_form") or "").strip()
    if correct_form and re.search(re.escape(correct_form), context, re.IGNORECASE):
        return True
    for wrong_form in term.get("wrong_forms") or []:
        wrong = str(wrong_form or "").strip()
        if wrong and re.search(re.escape(wrong), context, re.IGNORECASE):
            return True
    return False


def _window_can_match(span: str, term: str) -> bool:
    if not span or span.isdigit():
        return False
    if re.search(r"[\u4e00-\u9fff]", term) and len(term) >= 4:
        if span[0] != term[0]:
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
