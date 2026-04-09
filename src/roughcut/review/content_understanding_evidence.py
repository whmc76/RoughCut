from __future__ import annotations

import re
from typing import Any

from roughcut.review.content_understanding_schema import parse_primary_evidence_graph_payload

_RELATION_CUE_TERMS = (
    "叫",
    "是",
    "来自",
    "联名",
    "合作",
    "型号",
    "系列",
    "版本",
    "品牌",
    "出品",
)
_PRODUCT_FOCUS_TERMS = (
    "包",
    "背包",
    "双肩包",
    "手电",
    "手电筒",
    "刀",
    "刀具",
    "折刀",
    "美工刀",
    "刀刃",
    "刀身",
    "工具",
    "桌布",
    "收纳",
    "盒",
    "改造",
    "雕刻",
    "深雕",
    "电镀",
    "背负",
    "开箱",
    "对比",
    "版本",
    "系列",
)
_ANNOUNCEMENT_CUE_TERMS = (
    "宣布",
    "消息",
    "推出",
    "发布",
    "命名",
    "叫",
    "系列",
    "开发",
    "开创",
    "基于",
    "新",
)
_GENERIC_TOKEN_STOPWORDS = {
    "今天",
    "主要",
    "这个",
    "这款",
    "一下",
    "系列",
    "型号",
    "品牌",
    "联名",
    "合作",
    "review",
    "video",
    "mp4",
    "mov",
    "mkv",
    "avi",
    "webm",
    "demo",
}
_ENTITY_TOKEN_PATTERN = r"[A-Za-z][A-Za-z0-9_-]{1,}|[\u4e00-\u9fff]{2,8}"
_VISUAL_CATEGORY_ALIAS_MAP: dict[str, tuple[str, ...]] = {
    "backpack": ("背包", "双肩包"),
    "bag": ("包",),
    "sling_bag": ("斜挎包", "机能包"),
    "flashlight": ("手电", "手电筒"),
    "torch": ("手电", "手电筒"),
    "knife": ("刀", "折刀"),
    "folding_knife": ("折刀", "刀"),
    "utility_knife": ("美工刀", "折刀"),
    "box_cutter": ("美工刀", "刀"),
    "multitool": ("多功能工具", "工具"),
    "tool": ("工具",),
    "hard_case": ("收纳盒", "防水盒"),
    "case": ("收纳盒", "盒"),
    "storage_box": ("收纳盒", "盒"),
}
_COLLABORATION_PATTERNS = (
    re.compile(
        rf"(?P<left>{_ENTITY_TOKEN_PATTERN})\s*(?:和|与|跟|同|及|、|&|＆|x|X|×)\s*(?P<right>{_ENTITY_TOKEN_PATTERN})\s*(?:联名|合作)"
    ),
    re.compile(
        rf"(?P<left>{_ENTITY_TOKEN_PATTERN})\s*(?:x|X|×|&|＆)\s*(?P<right>{_ENTITY_TOKEN_PATTERN})(?:\s*(?:联名|合作))?"
    ),
)
_NAMING_PATTERNS = (
    re.compile(rf"(?:叫|名叫|叫做|型号(?:是)?|系列(?:叫|是)?|版本(?:叫|是)?)(?:\s+)?(?P<value>{_ENTITY_TOKEN_PATTERN})"),
)
_OWNERSHIP_PATTERNS = (
    re.compile(rf"(?P<owner>{_ENTITY_TOKEN_PATTERN})\s*家(?:的|出品的?)"),
    re.compile(rf"(?:来自|是)\s*(?P<owner>{_ENTITY_TOKEN_PATTERN})\s*(?:家|品牌|出的|出品)"),
)


def _as_dict(value: object | None) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_text(value: object | None) -> str:
    return str(value).strip() if value is not None else ""


def _as_subtitle_items(value: object | None) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        items.append(dict(item) if isinstance(item, dict) else {"value": item})
    return items


def _collect_subtitle_lines(subtitle_items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in subtitle_items:
        for key in ("text_final", "text", "value"):
            value = _as_text(item.get(key))
            if value and value not in lines:
                lines.append(value)
                break
    return lines


def _collect_hint_candidates(
    candidate_hints: dict[str, Any],
    visual_hints: dict[str, Any],
    visual_semantic_evidence: dict[str, Any],
) -> list[str]:
    values: list[str] = []
    visual_semantic_candidates = _visual_semantic_text_candidates(visual_semantic_evidence)
    for source in (candidate_hints, visual_hints, visual_semantic_candidates):
        for raw in source.values():
            for normalized in _iter_text_like_values(raw):
                if normalized not in values:
                    values.append(normalized)
    return values


def _visual_semantic_text_candidates(visual_semantic_evidence: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(visual_semantic_evidence, dict):
        return {}
    allowed: dict[str, Any] = {}
    for key in (
        "object_categories",
        "visible_brands",
        "visible_models",
        "subject_candidates",
        "interaction_type",
        "scene_context",
        "evidence_notes",
    ):
        value = visual_semantic_evidence.get(key)
        if value:
            allowed[key] = value
    frame_level_findings = visual_semantic_evidence.get("frame_level_findings")
    if isinstance(frame_level_findings, list):
        allowed["frame_level_findings"] = [
            {
                "finding": str(item.get("finding") or "").strip(),
                "evidence": str(item.get("evidence") or "").strip(),
            }
            for item in frame_level_findings
            if isinstance(item, dict)
        ]
    normalized_aliases = _expand_visual_category_aliases(visual_semantic_evidence)
    if normalized_aliases:
        allowed["normalized_object_aliases"] = normalized_aliases
    return allowed


def _expand_visual_category_aliases(visual_semantic_evidence: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    for key in ("object_categories", "subject_candidates"):
        for raw in visual_semantic_evidence.get(key) or []:
            normalized = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
            for alias in _VISUAL_CATEGORY_ALIAS_MAP.get(normalized, ()):
                if alias not in aliases:
                    aliases.append(alias)
    return aliases


def _iter_text_like_values(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            for text in _iter_text_like_values(nested):
                if text not in values:
                    values.append(text)
        return values
    if isinstance(value, list):
        values: list[str] = []
        for nested in value:
            for text in _iter_text_like_values(nested):
                if text not in values:
                    values.append(text)
        return values
    normalized = _as_text(value)
    return [normalized] if normalized else []


def _relation_cue_score(text: str) -> int:
    normalized = _as_text(text)
    if not normalized:
        return 0
    score = sum(2 for cue in _RELATION_CUE_TERMS if cue in normalized)
    if any(char.isascii() and char.isalpha() for char in normalized):
        score += 1
    if re.search(r"[\u4e00-\u9fff]{2,}", normalized):
        score += 1
    return score


def _collect_cue_lines(subtitle_lines: list[str], transcript_excerpt: str) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    for index, line in enumerate(subtitle_lines):
        score = _relation_cue_score(line)
        if score <= 0:
            continue
        ranked.append((score, -index, line))
    ranked.sort(reverse=True)
    cue_lines = [line for _score, _neg_index, line in ranked[:8]]
    if not cue_lines and transcript_excerpt:
        cue_lines = [segment.strip() for segment in re.split(r"[\n。！？]", transcript_excerpt) if segment.strip()][:4]
    return cue_lines


def _product_focus_score(text: str) -> int:
    normalized = _as_text(text)
    if not normalized:
        return 0
    score = _relation_cue_score(normalized)
    score += sum(2 for term in _PRODUCT_FOCUS_TERMS if term in normalized)
    score += sum(1 for term in _ANNOUNCEMENT_CUE_TERMS if term in normalized)
    if any(char.isascii() and char.isalpha() for char in normalized):
        score += 1
    if len(normalized) >= 10:
        score += 1
    return score


def _collect_temporal_focus_lines(subtitle_items: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    if not subtitle_items:
        return [], []

    def _pick(window: list[dict[str, Any]]) -> list[str]:
        ranked: list[tuple[int, int, str]] = []
        for index, item in enumerate(window):
            text = _as_text(item.get("text_final") or item.get("text") or item.get("value"))
            score = _product_focus_score(text)
            if score <= 0:
                continue
            ranked.append((score, -index, text))
        ranked.sort(reverse=True)
        selected = [text for _score, _neg_index, text in ranked[:6]]
        selected.reverse()
        deduped: list[str] = []
        for text in selected:
            if text not in deduped:
                deduped.append(text)
        return deduped

    start_time = float(subtitle_items[0].get("start_time", 0.0) or 0.0)
    end_time = float(subtitle_items[-1].get("end_time", subtitle_items[-1].get("start_time", 0.0)) or 0.0)
    duration = max(end_time - start_time, 1.0)
    opening_cutoff = start_time + duration * 0.55
    closing_cutoff = start_time + duration * 0.55

    opening_window = [
        item for item in subtitle_items if float(item.get("start_time", 0.0) or 0.0) <= opening_cutoff
    ] or subtitle_items[: min(12, len(subtitle_items))]
    closing_window = [
        item for item in subtitle_items if float(item.get("start_time", 0.0) or 0.0) >= closing_cutoff
    ] or subtitle_items[max(0, len(subtitle_items) - 12) :]
    return _pick(opening_window), _pick(closing_window)


def _tokenize_entity_like_text(value: str) -> list[str]:
    normalized = _as_text(value)
    if not normalized:
        return []
    tokens: list[str] = []
    for match in re.findall(_ENTITY_TOKEN_PATTERN, normalized):
        token = str(match or "").strip()
        if not token:
            continue
        normalized_key = token.lower()
        if normalized_key in _GENERIC_TOKEN_STOPWORDS:
            continue
        output = token.upper() if token.isascii() else token
        if output not in tokens:
            tokens.append(output)
    return tokens


def _tokenize_source_name(value: str) -> list[str]:
    normalized = _as_text(value)
    if not normalized:
        return []
    stem = normalized.rsplit(".", 1)[0]
    tokens: list[str] = []
    for raw in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", stem):
        token = str(raw or "").strip()
        if not token:
            continue
        normalized_key = token.lower()
        if normalized_key in _GENERIC_TOKEN_STOPWORDS:
            continue
        output = token.upper() if token.isascii() else token
        if output not in tokens:
            tokens.append(output)
    return tokens


def _collect_entity_like_tokens(
    *,
    source_name: str,
    visible_text: str,
    cue_lines: list[str],
    hint_candidates: list[str],
    relation_hints: list[dict[str, str]],
) -> list[str]:
    values: list[str] = []
    for token in _tokenize_source_name(source_name):
        if token not in values:
            values.append(token)
    for raw in [visible_text, *cue_lines, *hint_candidates]:
        for token in _tokenize_entity_like_text(raw):
            if token not in values:
                values.append(token)
    for item in relation_hints:
        for key in ("left", "right", "value", "owner"):
            raw = item.get(key)
            for token in _tokenize_entity_like_text(str(raw or "")):
                if token not in values:
                    values.append(token)
    return values[:20]


def _collect_relation_hints(cue_lines: list[str], transcript_excerpt: str) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    candidate_lines = [*cue_lines]
    if transcript_excerpt:
        candidate_lines.extend(
            segment.strip()
            for segment in re.split(r"[\n。！？]", transcript_excerpt)
            if segment.strip()
        )
    for line in candidate_lines:
        for hint in _extract_relation_hints_from_line(line):
            if hint not in hints:
                hints.append(hint)
    return hints[:8]


def _extract_relation_hints_from_line(text: str) -> list[dict[str, str]]:
    normalized = _as_text(text)
    if not normalized:
        return []
    hints: list[dict[str, str]] = []
    for pattern in _COLLABORATION_PATTERNS:
        for match in pattern.finditer(normalized):
            left = _clean_relation_value(match.group("left"))
            right = _clean_relation_value(match.group("right"))
            if left and right:
                hints.append({"relation": "collaboration", "left": left, "right": right, "text": normalized})
    for pattern in _NAMING_PATTERNS:
        for match in pattern.finditer(normalized):
            value = _clean_relation_value(match.group("value"))
            if value:
                hints.append({"relation": "naming", "value": value, "text": normalized})
    for pattern in _OWNERSHIP_PATTERNS:
        for match in pattern.finditer(normalized):
            owner = _clean_relation_value(match.group("owner"))
            if owner:
                hints.append({"relation": "ownership", "owner": owner, "text": normalized})
    return hints


def _clean_relation_value(value: str) -> str:
    cleaned = _as_text(value).strip(" ,.;:()[]{}<>-_")
    return cleaned


def _merge_semantic_fact_inputs(
    provided: dict[str, Any],
    computed: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(computed)
    for key in ("source_name", "transcript_text", "visible_text"):
        value = _as_text(provided.get(key))
        if value:
            merged[key] = value
    for key in ("subtitle_lines", "cue_lines", "opening_focus_lines", "closing_focus_lines", "hint_candidates", "entity_like_tokens"):
        raw = provided.get(key)
        if isinstance(raw, list):
            values = [str(item).strip() for item in raw if str(item).strip()]
            if values:
                merged[key] = values
    raw_relation_hints = provided.get("relation_hints")
    if isinstance(raw_relation_hints, list):
        relation_hints = [
            {str(k): str(v).strip() for k, v in item.items() if str(v).strip()}
            for item in raw_relation_hints
            if isinstance(item, dict)
        ]
        relation_hints = [item for item in relation_hints if item]
        if relation_hints:
            merged["relation_hints"] = relation_hints
    return merged


def _compact_semantic_section(value: object | None) -> dict[str, Any]:
    compacted = _compact_semantic_value(value)
    return compacted if isinstance(compacted, dict) else {}


def _compact_semantic_value(value: object | None) -> Any | None:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, nested in value.items():
            normalized = _compact_semantic_value(nested)
            if normalized is not None:
                compacted[str(key)] = normalized
        return compacted or None
    if isinstance(value, list):
        compacted_list: list[Any] = []
        for nested in value:
            normalized = _compact_semantic_value(nested)
            if normalized is not None:
                compacted_list.append(normalized)
        return compacted_list or None
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    if isinstance(value, (bool, int, float)):
        return value
    text = _as_text(value)
    return text if text else None


def normalize_evidence_bundle(bundle: object | None) -> dict[str, Any]:
    raw = bundle if isinstance(bundle, dict) else {}
    source_name = _as_text(raw.get("source_name"))
    transcript_excerpt = _as_text(raw.get("transcript_excerpt"))
    subtitle_items = _as_subtitle_items(raw.get("subtitle_items"))
    ocr_profile = _as_dict(raw.get("ocr_profile"))
    visual_semantic_evidence = _as_dict(raw.get("visual_semantic_evidence"))

    visible_text = _as_text(raw.get("visible_text"))
    ocr_visible_text = _as_text(ocr_profile.get("visible_text"))
    if not visible_text:
        visible_text = ocr_visible_text

    candidate_hints = _as_dict(raw.get("candidate_hints"))
    visual_hints = _as_dict(raw.get("visual_hints"))
    if not visual_hints:
        visual_hints = _as_dict(candidate_hints.get("visual_hints"))
    if not visible_text:
        visible_text = _as_text(visual_hints.get("visible_text"))
    candidate_hints["visual_hints"] = visual_hints
    subtitle_lines = _collect_subtitle_lines(subtitle_items)
    hint_candidates = _collect_hint_candidates(candidate_hints, visual_hints, visual_semantic_evidence)
    cue_lines = _collect_cue_lines(subtitle_lines, transcript_excerpt)
    opening_focus_lines, closing_focus_lines = _collect_temporal_focus_lines(subtitle_items)
    relation_hints = _collect_relation_hints(cue_lines, transcript_excerpt)
    computed_semantic_inputs = {
        "source_name": source_name,
        "subtitle_lines": subtitle_lines,
        "cue_lines": cue_lines,
        "opening_focus_lines": opening_focus_lines,
        "closing_focus_lines": closing_focus_lines,
        "transcript_text": transcript_excerpt,
        "visible_text": visible_text,
        "hint_candidates": hint_candidates,
        "relation_hints": relation_hints,
        "entity_like_tokens": _collect_entity_like_tokens(
            source_name=source_name,
            visible_text=visible_text,
            cue_lines=cue_lines,
            hint_candidates=hint_candidates,
            relation_hints=relation_hints,
        ),
    }
    semantic_fact_inputs = _merge_semantic_fact_inputs(_as_dict(raw.get("semantic_fact_inputs")), computed_semantic_inputs)

    primary_evidence_graph = parse_primary_evidence_graph_payload(
        {
            "audio_semantic_evidence": _compact_semantic_section(
                {
                    "transcript_text": transcript_excerpt,
                    "subtitle_lines": subtitle_lines,
                    "cue_lines": cue_lines,
                    "opening_focus_lines": opening_focus_lines,
                    "closing_focus_lines": closing_focus_lines,
                    "relation_hints": relation_hints,
                }
            ),
            "visual_semantic_evidence": visual_semantic_evidence,
            "ocr_semantic_evidence": _compact_semantic_section(
                {
                    "visible_text": ocr_visible_text,
                    "ocr_profile": ocr_profile,
                }
            ),
        }
    )

    normalized: dict[str, Any] = {
        "source_name": source_name,
        "transcript_excerpt": transcript_excerpt,
        "subtitle_items": subtitle_items,
        "visible_text": visible_text,
        "ocr_profile": ocr_profile,
        **primary_evidence_graph,
        "candidate_hints": candidate_hints,
        "semantic_fact_inputs": semantic_fact_inputs,
    }
    return normalized


def build_evidence_bundle(
    *,
    source_name: str,
    subtitle_items: list[dict[str, Any]] | None = None,
    transcript_excerpt: str = "",
    visible_text: str = "",
    ocr_profile: dict[str, Any] | None = None,
    visual_semantic_evidence: dict[str, Any] | None = None,
    visual_hints: dict[str, Any] | None = None,
    candidate_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return normalize_evidence_bundle(
        {
            "source_name": source_name,
            "subtitle_items": subtitle_items or [],
            "transcript_excerpt": transcript_excerpt,
            "visible_text": visible_text,
            "ocr_profile": ocr_profile or {},
            "visual_semantic_evidence": visual_semantic_evidence or {},
            "visual_hints": visual_hints or {},
            "candidate_hints": candidate_hints or {},
        }
    )
