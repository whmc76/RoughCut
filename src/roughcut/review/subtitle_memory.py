from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re
from typing import Any

from roughcut.review.domain_glossaries import detect_glossary_domains, merge_glossary_terms, resolve_builtin_glossary_terms
from roughcut.speech.dialects import resolve_transcription_dialect


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

_PROTECTED_BRAND_TERMS = {
    "FAS",
    "NOC",
    "REATE",
    "LEATHERMAN",
    "OLIGHT",
    "ZIPPO",
    "RunningHub",
    "ComfyUI",
    "OpenClaw",
}

_GENERIC_SUBJECT_PREFIXES = {
    "这",
    "那",
    "这个",
    "那个",
    "这把",
    "那把",
    "这个是",
    "那个是",
    "现在",
    "之前",
    "新版",
    "老款",
    "全新",
}

_ARABIC_TO_CHINESE_DIGITS = str.maketrans("0123456789", "零一二三四五六七八九")
_CHINESE_TO_ARABIC_DIGITS = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
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
    confirmed_entities = _build_confirmed_feedback_entities(content_profile)
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

    for entity in confirmed_entities:
        remember_term(entity.get("brand"), 8)
        remember_term(entity.get("model"), 8)
        for phrase in entity.get("phrases") or []:
            remember_term(phrase, 8)
        for item in entity.get("model_aliases") or []:
            remember_term(item.get("correct"), 7)

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
            base_weight = 6
            fallback_weight = 3
            if not term_domain and _is_brand_like_category(term.get("category")):
                base_weight = 8
                fallback_weight = 4
            if _is_brand_like_category(term.get("category")) and term_domain in {
                "gear",
                "edc",
                "knife",
                "flashlight",
                "bag",
                "lighter",
                "tactical",
                "outdoor",
                "functional_wear",
                "toy",
            }:
                # Keep brand anchors available for correction, but do not let
                # a large brand pool crowd out core EDC/flashlight process terms.
                if context_bonus > 0:
                    base_weight = 4
                    fallback_weight = 2
                else:
                    base_weight = 1
                    fallback_weight = 1
            if not term_domain:
                remember_term(correct_form, base_weight + context_bonus)
            elif term_domain in direct_domains:
                remember_term(correct_form, base_weight + context_bonus)
            else:
                remember_term(correct_form, fallback_weight + context_bonus)

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
    ranked_term_values = {
        str(item.get("term") or "").strip()
        for item in ranked_terms
        if item.get("term")
    }
    for term in glossary_terms or []:
        correct_form = _normalize_term(term.get("correct_form"))
        if not correct_form or correct_form in ranked_term_values:
            continue
        ranked_terms.append({"term": correct_form, "count": int(term_scores.get(correct_form) or 1)})
        ranked_term_values.add(correct_form)
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
                alias_pairs.append(
                    {
                        "wrong": wrong,
                        "correct": correct_form,
                        "category": str(term.get("category") or ""),
                    }
                )

    append_aliases(glossary_terms or [], only_ranked_terms=True)

    for term in ranked_term_order:
        for wrong in _DEFAULT_TERM_ALIASES.get(term, ()):
            pair = (wrong, term)
            if pair not in seen_aliases:
                seen_aliases.add(pair)
                alias_pairs.append({"wrong": wrong, "correct": term, "category": "brand" if _is_protected_brand_term(term) else ""})

    for entity in confirmed_entities:
        for item in entity.get("model_aliases") or []:
            wrong = str(item.get("wrong") or "").strip()
            correct = str(item.get("correct") or "").strip()
            if not wrong or not correct or wrong == correct:
                continue
            pair = (wrong, correct)
            if pair in seen_aliases:
                continue
            seen_aliases.add(pair)
            alias_pairs.append({"wrong": wrong, "correct": correct, "category": "confirmed_subject"})

    append_aliases(builtin_glossary_terms, only_ranked_terms=False)
    ranked_terms.sort(key=lambda item: (-_is_compound_domain_term(item["term"]), -int(item.get("count") or 0), item["term"]))

    return {
        "channel_profile": channel_profile or "",
        "terms": ranked_terms,
        "aliases": alias_pairs[:120],
        "confirmed_entities": confirmed_entities[:6],
        "style_examples": examples[:example_limit],
        "phrase_preferences": list((user_memory or {}).get("phrase_preferences") or [])[:12],
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

    phrases = review_memory.get("phrase_preferences") or []
    if phrases:
        values = " / ".join(
            str(item.get("phrase") or "")
            for item in phrases[:8]
            if item.get("phrase")
        )
        if values:
            lines.append(f"- 已学习短语: {values}")

    styles = review_memory.get("style_preferences") or []
    if styles:
        values = " / ".join(
            str(item.get("tag") or "")
            for item in styles[:6]
            if item.get("tag")
        )
        if values:
            lines.append(f"- 表达风格偏好: {values}")

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
    dialect_profile: str | None = None,
) -> str:
    snippets: list[str] = []
    if channel_profile:
        snippets.append(f"频道类型：{channel_profile}")

    dialect_spec = resolve_transcription_dialect(dialect_profile)
    if dialect_spec["value"] != "mandarin":
        snippets.append(f"识别口音：{dialect_spec['asr_label']}")
        if dialect_spec["prompt_hint"]:
            snippets.append(str(dialect_spec["prompt_hint"]).rstrip("。.!！？；;"))

    base_terms = [str(item.get("term") or "").strip() for item in (review_memory or {}).get("terms") or []]
    base_terms = [item for item in base_terms if item]
    dialect_hotwords = [str(item).strip() for item in dialect_spec.get("hotwords") or [] if str(item).strip()]
    reserved_dialect_slots = min(4, len(dialect_hotwords))
    terms = base_terms[: max(0, 12 - reserved_dialect_slots)]
    for hotword in dialect_hotwords:
        if hotword and hotword not in terms:
            terms.append(hotword)
        if len(terms) >= 12:
            break
    if terms:
        snippets.append(f"热词：{', '.join(terms)}")
        snippets.append("请保持品牌、型号、圈内术语和方言原词")

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


def apply_domain_term_corrections(
    text: str,
    review_memory: dict[str, Any] | None,
    *,
    prev_text: str = "",
    next_text: str = "",
) -> str:
    result = str(text or "").strip()
    if not result:
        return result

    for pattern, replacement in _GENERIC_SAFE_REPLACEMENTS:
        if _is_protected_brand_term(replacement):
            continue
        result = pattern.sub(replacement, result)

    if not review_memory:
        return result

    result = _apply_confirmed_entity_corrections(
        result,
        review_memory,
        prev_text=prev_text,
        next_text=next_text,
    )

    compound_terms = [
        str(item.get("term") or "").strip()
        for item in review_memory.get("terms") or []
        if _is_compound_domain_term(str(item.get("term") or "").strip())
    ]
    for term in compound_terms:
        result = _replace_compound_phrase_match(result, term)

    for item in review_memory.get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        if not wrong or not correct:
            continue
        category = str(item.get("category") or "").strip()
        if (
            _is_brand_like_category(category)
            or _is_protected_brand_term(correct)
        ) and category != "confirmed_subject":
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)

    terms = [str(item.get("term") or "").strip() for item in review_memory.get("terms") or []]
    for term in terms:
        if _is_protected_brand_term(term):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", term):
                result = re.sub(re.escape(term), term, result, flags=re.IGNORECASE)
            continue
        aliases = _DEFAULT_TERM_ALIASES.get(term, ())
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", term):
            result = re.sub(re.escape(term), term, result, flags=re.IGNORECASE)
        for wrong in aliases:
            result = re.sub(re.escape(wrong), term, result, flags=re.IGNORECASE)
        if not aliases or re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", term):
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


def _extract_compound_components(text: str) -> list[str]:
    candidate = str(text or "").strip()
    components: list[str] = []
    for anchor in sorted(_DOMAIN_ANCHORS, key=len, reverse=True):
        if len(anchor) < 2:
            continue
        if anchor in candidate and anchor not in components:
            components.append(anchor)
    return components


def _normalize_term(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    if text in _PRESERVE_CASE_TERMS:
        return text
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,24}", text):
        return text.upper()
    return text[:40]


def _is_brand_like_category(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized and "brand" in normalized)


def _is_protected_brand_term(value: Any) -> bool:
    normalized = _normalize_term(value)
    return normalized in _PROTECTED_BRAND_TERMS


def _is_compound_domain_term(value: str) -> int:
    text = str(value or "").strip()
    return 1 if len(text) >= 4 and _count_domain_anchor_hits(text) >= 2 else 0


def _normalize_alias_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())[:40]


def _clean_example_text(value: Any) -> str:
    text = re.sub(r"\s+", "", str(value or "").strip())
    return text[:80]


def _extract_confirmed_profile_fields(content_profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = content_profile or {}
    feedback = profile.get("user_feedback")
    sources: list[dict[str, Any]] = []
    if isinstance(feedback, dict):
        sources.append(feedback)
    if _content_profile_is_confirmed(profile):
        sources.append(profile)
    if not sources:
        return {}

    confirmed: dict[str, Any] = {}
    for source in sources:
        for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
            value = str(source.get(key) or "").strip()
            if value and key not in confirmed:
                confirmed[key] = value

    keywords: list[str] = []
    for source in sources:
        for field_name in ("keywords", "search_queries"):
            for item in source.get(field_name) or []:
                value = str(item).strip()
                if value and value not in keywords:
                    keywords.append(value)

    if keywords:
        confirmed["keywords"] = keywords
    return confirmed


def _content_profile_is_confirmed(profile: dict[str, Any] | None) -> bool:
    review_mode = str((profile or {}).get("review_mode") or "").strip().lower()
    if review_mode in {"manual_confirmed", "auto_confirmed"}:
        return True
    automation = (profile or {}).get("automation_review")
    if isinstance(automation, dict) and bool(automation.get("auto_confirm")):
        return True
    return False


def _build_confirmed_feedback_entities(content_profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    confirmed = _extract_confirmed_profile_fields(content_profile)
    brand = _compact_subject_text(confirmed.get("subject_brand"))
    model = _compact_subject_text(confirmed.get("subject_model"))
    phrases: list[str] = []
    for item in confirmed.get("keywords") or []:
        value = _compact_subject_text(item)
        if value and value not in phrases:
            phrases.append(value)
    if brand and model:
        combined = f"{brand}{model}"
        if combined not in phrases:
            phrases.insert(0, combined)
    if not brand and not model and not phrases:
        return []
    return [
        {
            "brand": brand,
            "model": model,
            "phrases": phrases[:8],
            "model_aliases": _build_confirmed_model_aliases(model),
        }
    ]


def _compact_subject_text(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return ""
    return re.sub(r"\s+", "", text)


def _build_confirmed_model_aliases(model: str) -> list[dict[str, str]]:
    compact = _compact_subject_text(model)
    if not compact:
        return []
    canonical_forms: list[str] = []
    for candidate in (
        compact,
        _extract_model_core(compact),
        _extract_model_generation_anchor(compact),
        _extract_model_suffix(compact),
        _extract_model_variant_suffix(compact),
    ):
        value = _compact_subject_text(candidate)
        if value and value not in canonical_forms:
            canonical_forms.append(value)

    pairs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for canonical in canonical_forms:
        for wrong in _generate_confirmed_model_wrong_forms(canonical):
            pair = (wrong, canonical)
            if wrong and wrong != canonical and pair not in seen:
                seen.add(pair)
                pairs.append({"wrong": wrong, "correct": canonical})
    return pairs[:40]


def _extract_model_core(model: str) -> str:
    match = re.search(r"[A-Za-z]{1,6}\d{1,4}(?:[A-Za-z0-9]+)?(?:[零〇一二三四五六七八九十\d]+代)?(?:Pro|MAX|Mini|Ultra|Plus|SE)?", model, re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_model_generation_anchor(model: str) -> str:
    match = re.search(r"[A-Za-z]{1,6}\d{1,4}(?:[零〇一二三四五六七八九十\d]+代)", model, re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_model_suffix(model: str) -> str:
    match = re.search(r"(?:UV|Pro|MAX|Mini|Ultra|Plus|SE)[A-Za-z0-9\u4e00-\u9fff]*版?$", model, re.IGNORECASE)
    return match.group(0) if match else ""


def _extract_model_variant_suffix(model: str) -> str:
    if re.search(r"UV版", model, re.IGNORECASE):
        return "UV版"
    return ""


def _generate_confirmed_model_wrong_forms(canonical: str) -> list[str]:
    forms = {canonical}
    digit_to_chinese = canonical.translate(_ARABIC_TO_CHINESE_DIGITS)
    if digit_to_chinese:
        forms.add(digit_to_chinese)
    chinese_to_digit = "".join(_CHINESE_TO_ARABIC_DIGITS.get(char, char) for char in canonical)
    if chinese_to_digit:
        forms.add(chinese_to_digit)
    if canonical.upper() == "UV版":
        forms.add("五眼版")
    elif "UV" in canonical.upper():
        forms.add(re.sub("UV", "五眼", canonical, flags=re.IGNORECASE))
        forms.add(re.sub("UV版", "五眼版", canonical, flags=re.IGNORECASE))
    if "五眼" in canonical:
        forms.add(canonical.replace("五眼", "UV"))
    return sorted(forms, key=lambda item: (-len(item), item))


def _apply_confirmed_entity_corrections(
    text: str,
    review_memory: dict[str, Any] | None,
    *,
    prev_text: str = "",
    next_text: str = "",
) -> str:
    result = str(text or "")
    for entity in (review_memory or {}).get("confirmed_entities") or []:
        brand = str(entity.get("brand") or "").strip()
        model = str(entity.get("model") or "").strip()
        model_aliases = [
            (str(item.get("wrong") or "").strip(), str(item.get("correct") or "").strip())
            for item in entity.get("model_aliases") or []
            if item.get("wrong") and item.get("correct")
        ]
        for wrong, correct in sorted(model_aliases, key=lambda item: (-len(item[0]), item[0])):
            if not _confirmed_alias_has_context_support(
                wrong=wrong,
                correct=correct,
                current_text=result,
                prev_text=prev_text,
                next_text=next_text,
                entity=entity,
            ):
                continue
            result = _replace_confirmed_subject_anchor(result, wrong=wrong, correct=correct, brand=brand)
        for anchor in _build_confirmed_model_anchor_forms(model):
            result = _replace_confirmed_subject_anchor(result, wrong=anchor, correct=anchor, brand=brand)
    return result


def _replace_confirmed_subject_anchor(text: str, *, wrong: str, correct: str, brand: str) -> str:
    if not text or not wrong or not correct:
        return text
    match = re.search(re.escape(wrong), text, re.IGNORECASE)
    if not match:
        return text
    start, end = match.span()
    prefix_match = re.search(r"([A-Za-z\u4e00-\u9fff]{1,4})$", text[:start])
    raw_prefix = prefix_match.group(1) if prefix_match else ""
    prefix = _trim_brand_candidate_prefix(raw_prefix)
    if prefix and _alias_supports_brand_prefix(wrong, correct) and not _is_generic_subject_prefix(prefix):
        if brand and text[:start].endswith(brand):
            return text
        replace_start = start - len(prefix)
        replacement = f"{brand}{correct}" if brand else correct
        return f"{text[:replace_start]}{replacement}{text[end:]}"
    return f"{text[:start]}{correct}{text[end:]}"


def _build_confirmed_model_anchor_forms(model: str) -> list[str]:
    compact = _compact_subject_text(model)
    if not compact:
        return []
    anchors: list[str] = []
    for candidate in (
        compact,
        _extract_model_core(compact),
        _extract_model_generation_anchor(compact),
    ):
        value = _compact_subject_text(candidate)
        if value and value not in anchors:
            anchors.append(value)
    return anchors[:8]


def _is_generic_subject_prefix(value: str) -> bool:
    token = str(value or "").strip()
    return token in _GENERIC_SUBJECT_PREFIXES


def _trim_brand_candidate_prefix(value: str) -> str:
    token = str(value or "").strip()
    token = re.sub(r"^[呃啊嗯哦]+", "", token)
    if "是" in token:
        token = token.rsplit("是", 1)[-1].strip() or token
    return token


def _alias_supports_brand_prefix(wrong: str, correct: str) -> bool:
    candidate = f"{wrong}{correct}"
    return bool(re.search(r"[A-Za-z]{1,6}\d{1,4}", candidate, re.IGNORECASE))


def _confirmed_alias_has_context_support(
    *,
    wrong: str,
    correct: str,
    current_text: str,
    prev_text: str,
    next_text: str,
    entity: dict[str, Any],
) -> bool:
    normalized_wrong = str(wrong or "").strip()
    normalized_correct = str(correct or "").strip()
    if not normalized_wrong or not normalized_correct:
        return False
    if normalized_wrong != "五眼版" or normalized_correct != "UV版":
        return True

    context = " ".join(
        item for item in [str(current_text or ""), str(prev_text or ""), str(next_text or "")]
        if item
    )
    explicit_feature_tokens = {
        "UV",
        "灯",
        "灯珠",
        "跑马灯",
        "发光",
        "光杯",
    }
    if any(token and token in context for token in explicit_feature_tokens):
        return True

    neighbor_context = " ".join(item for item in [str(prev_text or ""), str(next_text or "")] if item)
    entity_tokens = _extract_context_support_tokens(entity)
    return any(token and token in neighbor_context for token in entity_tokens)


def _extract_context_support_tokens(entity: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    for source in (
        str(entity.get("brand") or "").strip(),
        str(entity.get("model") or "").strip(),
    ):
        compact = _compact_subject_text(source)
        if not compact:
            continue
        for match in re.findall(r"[A-Za-z]{1,8}\d{1,4}|[\u4e00-\u9fff]{2,4}", compact, flags=re.IGNORECASE):
            if match in {"二代", "版本", "Pro", "UV版", "UV"}:
                continue
            if match not in tokens:
                tokens.append(match)
    return tokens[:12]


def _replace_near_match(text: str, term: str) -> str:
    if not text or not term:
        return text
    if re.search(re.escape(term), text, re.IGNORECASE):
        return re.sub(re.escape(term), term, text, flags=re.IGNORECASE)
    if not re.search(r"[\u4e00-\u9fff]", term):
        return _replace_near_latin_token(text, term)

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


def _replace_near_latin_token(text: str, term: str) -> str:
    best: tuple[float, str] | None = None
    for token in re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+-]{2,23})(?![A-Za-z0-9])", text):
        score = SequenceMatcher(None, token.upper(), term.upper()).ratio()
        if best is None or score > best[0]:
            best = (score, token)
    if not best or best[0] < 0.72:
        return text
    return re.sub(re.escape(best[1]), term, text, count=1, flags=re.IGNORECASE)


def _replace_compound_phrase_match(text: str, term: str) -> str:
    if not text or not term or term in text:
        return text
    components = [part for part in _extract_compound_components(term) if len(part) >= 2]
    if len(components) < 2:
        return text

    best: tuple[float, int, int] | None = None
    term_len = len(term)
    min_len = max(3, term_len - 2)
    max_len = min(len(text), term_len + 2)
    for size in range(min_len, max_len + 1):
        for start in range(0, len(text) - size + 1):
            span = text[start:start + size]
            if not _compound_window_can_match(span, components):
                continue
            score = SequenceMatcher(None, span, term).ratio()
            if best is None or score > best[0]:
                best = (score, start, start + size)
    if not best or best[0] < 0.58:
        return text
    _, start, end = best
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


def _compound_window_can_match(span: str, components: list[str]) -> bool:
    hits = 0
    for component in components:
        if component in span:
            hits += 1
            continue
        if _span_has_component_like(span, component):
            hits += 1
    return hits >= 2


def _span_has_component_like(span: str, component: str) -> bool:
    if not span or not component:
        return False
    if component in span:
        return True
    comp_len = len(component)
    min_len = max(2, comp_len - 1)
    max_len = min(len(span), comp_len + 1)
    for size in range(min_len, max_len + 1):
        for start in range(0, len(span) - size + 1):
            candidate = span[start:start + size]
            if not _window_can_match(candidate, component):
                continue
            score = SequenceMatcher(None, candidate, component).ratio()
            threshold = 0.72 if comp_len >= 4 else 0.64
            if score >= threshold:
                return True
    return False


def _source_name_is_informative(source_name: str) -> bool:
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(source_name or "").strip())
    if not stem:
        return False
    if re.fullmatch(r"[\d_-]+", stem):
        return False
    if re.fullmatch(r"\d{8}[_-].+", stem):
        return False
    return True
