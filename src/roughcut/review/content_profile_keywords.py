from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Mapping

from roughcut.review.content_understanding_schema import normalize_video_type

_KEYWORD_TOKEN_STRIP_CHARS = "：:;；,.!?!?！？`“”‘’'\"()[]{}<>《》"
_REVIEW_KEYWORDS_LIMIT = 10
_REVIEW_KEYWORDS_MIN_LEN = 2
_REVIEW_KEYWORD_MIN_COUNT = 4
_REVIEW_KEYWORD_TERM_SPLIT_RE = re.compile(r"[\s,，、/\\|+*×xX·•_=\-]+")
_REVIEW_KEYWORD_CONNECTOR_RE = re.compile(r"(?:与|和|及|及其|以及|并|并且|对比|联名|或|还是|以及)")
_REVIEW_KEYWORD_CHUNK_FALLBACK_PART_RE = re.compile(r"[一-龥]{2,4}|[A-Za-z0-9+#\-]{2,}", re.IGNORECASE)
_REVIEW_KEYWORD_NOISE_CHUNKS = {
    "开箱",
    "评测",
    "测评",
    "实测",
    "介绍",
    "对比",
    "上手",
    "内容",
    "产品",
    "视频",
    "主题",
}
_REVIEW_KEYWORD_EXPLICIT_ANCHORS = (
    "双肩包",
    "机能包",
    "机能",
    "背包",
    "斜挎包",
    "胸包",
    "快取包",
    "副包",
    "收纳包",
    "收纳盒",
    "防水盒",
    "手电筒",
    "手电",
    "电筒",
    "工具钳",
    "折刀",
    "重力刀",
    "联名",
    "限定版",
    "限定",
    "纪念版",
    "特别版",
    "升级版",
    "背负",
    "挂点",
    "收纳",
    "夜骑",
    "泛光",
    "聚光",
    "流明",
)
_REVIEW_KEYWORD_COMPOUNDABLE_ANCHORS = {
    "双肩包",
    "机能包",
    "背包",
    "斜挎包",
    "胸包",
    "快取包",
    "副包",
    "收纳包",
    "收纳盒",
    "防水盒",
    "手电筒",
    "手电",
    "电筒",
    "工具钳",
    "折刀",
    "重力刀",
}
_REVIEW_KEYWORD_MIXED_STOP_TAILS = {
    "这次",
    "这个",
    "今天",
    "一款",
    "一个",
    "主打",
    "通勤",
    "真的",
}
_REVIEW_KEYWORD_CHINESE_STOP_PREFIXES = {
    "这次",
    "这个",
    "今天",
    "主要",
    "主打",
    "最近",
    "然后",
    "一下",
    "一款",
    "一个",
    "我们",
    "你们",
    "大家",
}
_REVIEW_KEYWORD_COLOR_RE = re.compile(r"[黑白灰银红蓝绿黄橙紫粉棕]{1,4}(?:拼色|配色|双色|三色|撞色)")
_REVIEW_KEYWORD_TRAILING_NOISE_RE = re.compile(r"(?:开箱|评测|测评|实测|介绍|对比|上手)+$")
_SEMANTIC_FACT_KEYWORD_FIELDS: tuple[tuple[str, int], ...] = (
    ("product_name_candidates", 136),
    ("product_type_candidates", 134),
    ("model_candidates", 132),
    ("brand_candidates", 130),
    ("primary_subject_candidates", 128),
    ("collaboration_pairs", 126),
    ("aspect_candidates", 124),
    ("supporting_subject_candidates", 122),
    ("supporting_product_candidates", 120),
    ("comparison_subject_candidates", 118),
    ("search_expansions", 116),
)
_CONTENT_KIND_DEFAULT_SUBJECT_TYPE = {
    "tutorial": "录屏教学",
    "vlog": "Vlog日常",
    "commentary": "口播观点",
    "gameplay": "游戏实况",
    "food": "探店试吃",
}
_TECH_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("无限画布", re.compile(r"(无限画布|无边画布|无限画板|无限canvas|infinite\s+canvas)", re.IGNORECASE)),
    ("工作流", re.compile(r"(工作流|workflow|节点流|流程编排)", re.IGNORECASE)),
    ("节点编排", re.compile(r"(节点编排|节点连接|节点搭建|节点串联)", re.IGNORECASE)),
    ("漫剧工作流", re.compile(r"(漫剧工作流|漫剧制作|漫画剧|短剧工作流|剧情工作流)", re.IGNORECASE)),
    ("智能体", re.compile(r"(智能体|agent mode|agents?|multi-agent|多智能体)", re.IGNORECASE)),
    ("提示词", re.compile(r"(提示词|prompt)", re.IGNORECASE)),
    ("LoRA", re.compile(r"(lora|罗拉)", re.IGNORECASE)),
    ("RAG", re.compile(r"(?<![A-Za-z])(rag|RAG)(?![A-Za-z])", re.IGNORECASE)),
    ("工作流编排", re.compile(r"(工作流编排|流程编排)", re.IGNORECASE)),
]
_SEARCH_SIGNAL_STOPWORDS: set[str] = {
    "ASMR",
    "DIY",
    "EDC",
    "POV",
    "VLOG",
}


def _clean_line(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip("，。！？：:;；、")


def _normalize_profile_value(value: Any) -> str:
    return "".join(str(value or "").strip().upper().split())


def _looks_like_camera_stem(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(r"(img|dsc|mvimg|pxl|cimg|vid)[-_]?\d+(?:[_-]\d+)*", normalized)
        or re.fullmatch(r"\d{8}[_-].+", normalized)
    )


def _is_informative_source_hint(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return False
    if _looks_like_camera_stem(normalized):
        return False
    if re.fullmatch(r"[\d_-]+", normalized):
        return False
    return True


def _normalize_main_content_type(value: str) -> str:
    return normalize_video_type(value)


def _extract_topic_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for label, pattern in _TECH_TOPIC_PATTERNS:
        if pattern.search(str(text or "")) and label not in seen:
            seen.add(label)
            terms.append(label)
    return terms


def _extract_search_signal_terms(*texts: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        normalized = str(text).upper()
        for match in re.finditer(r"(?<![A-Z0-9])([A-Z][A-Z0-9-]{1,17})(?![A-Z0-9])", normalized):
            token = match.group(1).strip("-")
            if not token or token in _SEARCH_SIGNAL_STOPWORDS:
                continue
            if re.fullmatch(r"\d+", token) or _looks_like_camera_stem(token):
                continue
            if token not in seen:
                seen.add(token)
                terms.append(token)
    return terms


def _extract_query_support_terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    compact = str(text or "").strip()
    if not compact:
        return terms

    def remember(token: str) -> None:
        normalized = _normalize_profile_value(token)
        if not normalized or len(normalized) < 2:
            return
        if token in {"主要围绕", "内容方向", "产品开箱与上手体验"}:
            return
        if normalized in seen:
            return
        seen.add(normalized)
        terms.append(token)

    for part in re.split(r"[，。,、；;：:\(\)（）\[\]【】\s]+", compact):
        segment = part.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
        if not segment:
            continue
        if re.search(r"[一-龥]", segment) and re.search(r"[A-Za-z0-9]", segment):
            remember(segment)
            continue
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9+-]{1,23}", segment):
            remember(segment)
            continue
        if re.fullmatch(r"[一-龥]{2,8}", segment):
            remember(segment)
            continue
        if re.fullmatch(r"[一-龥]{9,}", segment):
            for token in _extract_long_chinese_keyword_candidates(segment, seed_terms=[]):
                remember(token)
    return terms


def normalize_query_list(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        query = str(item or "").strip()
        if not query:
            continue
        key = "".join(query.upper().split())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(query)
    return deduped


def _collect_review_keyword_piece(token: str, seen: set[str]) -> list[str]:
    cleaned = _clean_keyword_candidate(token)
    normalized = _normalize_profile_value(cleaned)
    if not normalized or len(normalized) < _REVIEW_KEYWORDS_MIN_LEN:
        return []
    if cleaned in _REVIEW_KEYWORD_NOISE_CHUNKS:
        return []
    if normalized in seen:
        return []
    seen.add(normalized)
    return [cleaned]


def _is_noisy_chinese_keyword(token: str) -> bool:
    cleaned = _clean_keyword_candidate(token)
    if not re.fullmatch(r"[一-龥]{2,8}", cleaned):
        return False
    if cleaned in _REVIEW_KEYWORD_EXPLICIT_ANCHORS:
        return False
    return any(cleaned.startswith(prefix) for prefix in _REVIEW_KEYWORD_CHINESE_STOP_PREFIXES)


def _clean_keyword_candidate(token: str) -> str:
    cleaned = str(token or "").strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
    if not cleaned:
        return ""
    return _REVIEW_KEYWORD_TRAILING_NOISE_RE.sub("", cleaned).strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()


def _extract_long_chinese_keyword_candidates(chunk: str, seed_terms: list[str]) -> list[str]:
    normalized_chunk = _clean_keyword_candidate(chunk)
    if not normalized_chunk:
        return []

    extracted: list[str] = []
    seen: set[str] = set()

    for term in seed_terms:
        cleaned_term = _clean_keyword_candidate(term)
        if len(cleaned_term) < _REVIEW_KEYWORDS_MIN_LEN:
            continue
        if cleaned_term in normalized_chunk:
            extracted.extend(_collect_review_keyword_piece(cleaned_term, seen))

    for match in _REVIEW_KEYWORD_COLOR_RE.finditer(normalized_chunk):
        extracted.extend(_collect_review_keyword_piece(match.group(0), seen))

    for anchor in _REVIEW_KEYWORD_EXPLICIT_ANCHORS:
        start = normalized_chunk.find(anchor)
        while start >= 0:
            extracted.extend(_collect_review_keyword_piece(anchor, seen))
            prefix = normalized_chunk[max(0, start - 2):start]
            if anchor in _REVIEW_KEYWORD_COMPOUNDABLE_ANCHORS and re.fullmatch(r"[一-龥]{2}", prefix):
                extracted.extend(_collect_review_keyword_piece(f"{prefix}{anchor}", seen))
            start = normalized_chunk.find(anchor, start + len(anchor))

    return extracted


def _is_concise_keyword_candidate(value: str) -> bool:
    cleaned = _clean_keyword_candidate(value)
    if not cleaned or cleaned in _REVIEW_KEYWORD_NOISE_CHUNKS:
        return False
    if re.fullmatch(r"[A-Za-z0-9+#\- ]{2,32}", cleaned):
        return True
    if re.search(r"[一-龥]", cleaned) and re.search(r"[A-Za-z0-9]", cleaned):
        return len(cleaned) <= 18 or any(char.isdigit() for char in cleaned)
    if re.fullmatch(r"[一-龥]{2,8}", cleaned):
        return True
    return False


def _iter_semantic_fact_terms(profile_values: Mapping[str, Any]) -> list[tuple[str, int]]:
    content_understanding = profile_values.get("content_understanding")
    if not isinstance(content_understanding, Mapping):
        return []
    semantic_facts = content_understanding.get("semantic_facts")
    if not isinstance(semantic_facts, Mapping):
        return []

    terms: list[tuple[str, int]] = []
    seen: set[str] = set()
    for field_name, weight in _SEMANTIC_FACT_KEYWORD_FIELDS:
        for item in list(semantic_facts.get(field_name) or []):
            term = _clean_keyword_candidate(item)
            normalized = _normalize_profile_value(term)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            terms.append((term, weight))
    return terms


def _keyword_chinese_core(value: str) -> str:
    return "".join(re.findall(r"[一-龥]+", str(value or "")))


def _filter_redundant_keywords(values: list[str]) -> list[str]:
    filtered: list[str] = []
    filtered_cores: list[str] = []
    for token in values:
        core = _keyword_chinese_core(token)
        if core:
            if any(core == existing for existing in filtered_cores if existing):
                continue
            if any(len(existing) >= 3 and existing in core for existing in filtered_cores if existing) and len(core) - max(
                (len(existing) for existing in filtered_cores if existing and existing in core),
                default=0,
            ) <= 2:
                continue
            covered_parts = [
                existing
                for existing in filtered_cores
                if existing and len(existing) >= 2 and existing in core and existing != core
            ]
            if len(core) >= 4 and len(covered_parts) >= 2:
                continue
        filtered.append(token)
        filtered_cores.append(core)
    return filtered


def extract_review_keyword_tokens(
    text: str,
    *,
    seed_terms: list[str] | None = None,
) -> list[str]:
    normalized = _clean_line(text).strip()
    if not normalized:
        return []

    seeds = [str(term or "").strip() for term in (seed_terms or []) if str(term or "").strip()]
    if seeds:
        sorted_seeds = [item for item in sorted(set(seeds), key=len, reverse=True) if len(item) >= _REVIEW_KEYWORDS_MIN_LEN]
    else:
        sorted_seeds = []

    tokens: list[str] = []
    for chunk in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(normalized):
        candidate = chunk.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
        if not candidate:
            continue
        if "联名" in candidate:
            tokens.append("联名")
        normalized_candidate = _REVIEW_KEYWORD_CONNECTOR_RE.sub(" ", candidate)
        for part in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(normalized_candidate):
            segment = part.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
            if not segment:
                continue
            if re.search(r"[一-龥]", segment) and re.search(r"[A-Za-z0-9]", segment):
                chinese_only = "".join(re.findall(r"[一-龥]+", segment))
                if (
                    (len(segment) <= 18 or any(char.isdigit() for char in segment))
                    and not (
                        chinese_only
                        and not any(char.isdigit() for char in segment)
                        and any(chinese_only.startswith(prefix) for prefix in _REVIEW_KEYWORD_MIXED_STOP_TAILS)
                    )
                ):
                    tokens.append(segment)
                else:
                    tokens.extend(re.findall(r"[A-Za-z0-9+#\-]{2,}", segment))
                    chinese_tail = re.sub(r"[A-Za-z0-9+#\-]+", " ", segment)
                    for chinese_part in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(chinese_tail):
                        chinese_segment = chinese_part.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
                        if not chinese_segment:
                            continue
                        if len(chinese_segment) > 6:
                            tokens.extend(_extract_long_chinese_keyword_candidates(chinese_segment, sorted_seeds))
                        else:
                            tokens.append(chinese_segment)
                continue
            if re.fullmatch(r"[A-Za-z0-9+#\-]+", segment):
                tokens.append(segment)
                continue
            if re.fullmatch(r"[一-龥]{2,}", segment) and len(segment) > 6:
                tokens.extend(_extract_long_chinese_keyword_candidates(segment, sorted_seeds))
                continue
            tokens.extend(_REVIEW_KEYWORD_CHUNK_FALLBACK_PART_RE.findall(segment))

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in _REVIEW_KEYWORD_NOISE_CHUNKS or _is_noisy_chinese_keyword(token):
            continue
        normalized_token = _normalize_profile_value(token)
        if len(normalized_token) < _REVIEW_KEYWORDS_MIN_LEN:
            continue
        if normalized_token in seen:
            continue
        seen.add(normalized_token)
        deduped.append(token)
    return deduped


def collect_review_keyword_seed_terms(profile_values: Mapping[str, Any]) -> list[str]:
    raw_terms: list[str] = []
    for field_name in ("subject_brand", "subject_model", "subject_type"):
        text = str(profile_values.get(field_name) or "").strip()
        if not text:
            continue
        for token in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(text):
            token = token.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
            if token:
                raw_terms.append(token)
    for field_name in ("video_theme", "visible_text", "transcript_excerpt"):
        text = str(profile_values.get(field_name) or "").strip()
        if not text:
            continue
        raw_terms.extend(extract_review_keyword_tokens(text, seed_terms=[]))
    source_name = str(profile_values.get("source_name") or profile_values.get("source_file_name") or "").strip()
    if source_name:
        raw_terms.extend(extract_review_keyword_tokens(source_name, seed_terms=[]))
    return list(dict.fromkeys(raw_terms))


def _is_fragment_of_mixed_product_term(token: str, existing_terms: list[str]) -> bool:
    stripped = str(token or "").strip()
    if not re.fullmatch(r"[A-Za-z]{2,8}", stripped):
        return False
    compact = "".join(stripped.casefold().split())
    for existing in existing_terms:
        normalized_existing = "".join(str(existing or "").casefold().split())
        if compact == normalized_existing:
            continue
        if compact in normalized_existing and any(char.isdigit() for char in normalized_existing):
            return True
    return False


def build_review_keywords(profile: Mapping[str, Any]) -> list[str]:
    profile_values = dict(profile or {})
    brand = str(profile_values.get("subject_brand") or "").strip()
    model = str(profile_values.get("subject_model") or "").strip()
    subject_type = str(profile_values.get("subject_type") or "").strip()
    visible_text = str(profile_values.get("visible_text") or "").strip()
    video_theme = str(profile_values.get("video_theme") or "").strip()
    raw_queries = [str(item).strip() for item in (profile_values.get("search_queries") or []) if str(item).strip()]
    transcript_excerpt = str(profile_values.get("transcript_excerpt") or "").strip()
    source_name = str(profile_values.get("source_name") or profile_values.get("source_file_name") or "").strip()
    seed_terms = collect_review_keyword_seed_terms(profile_values)

    candidates: list[tuple[int, int, str]] = []
    seen: dict[str, int] = {}

    def add(term: str, weight: int) -> None:
        cleaned = _clean_keyword_candidate(term)
        if not cleaned:
            return
        normalized = _normalize_profile_value(cleaned)
        if not normalized or len(normalized) < _REVIEW_KEYWORDS_MIN_LEN:
            return
        if cleaned in _REVIEW_KEYWORD_NOISE_CHUNKS:
            return
        if _is_noisy_chinese_keyword(cleaned):
            return
        if _looks_like_camera_stem(normalized):
            return
        if re.fullmatch(r"[\d._:-]+", normalized):
            return
        if re.fullmatch(r"\d{8}[_-].+", normalized):
            return
        if _is_fragment_of_mixed_product_term(cleaned, [item[2] for item in candidates]):
            return
        norm_key = "".join(normalized.upper().split())
        if norm_key in seen:
            return
        seen[norm_key] = len(candidates)
        candidates.append((weight, len(candidates), cleaned))

    add(brand, 140)
    add(model, 130)
    add(subject_type, 120)
    for term, weight in _iter_semantic_fact_terms(profile_values):
        add(term, weight)
    for term in _extract_topic_terms(video_theme):
        add(term, 110)
    for term in _extract_search_signal_terms(transcript_excerpt, visible_text, _clean_line(source_name)):
        add(term, 105)
    for term in extract_review_keyword_tokens(visible_text, seed_terms=seed_terms):
        add(term, 95)
    for query in raw_queries:
        if _is_concise_keyword_candidate(query):
            add(query, 92)
        for token in extract_review_keyword_tokens(query, seed_terms=seed_terms):
            add(token, 90)
    for term in _extract_query_support_terms(video_theme):
        add(term, 85)
    for term in _extract_topic_terms(visible_text):
        add(term, 80)
    for term in seed_terms:
        add(term, 70)

    ordered = _filter_redundant_keywords([item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))])
    if ordered:
        if len(ordered) < _REVIEW_KEYWORD_MIN_COUNT and seed_terms:
            for term in seed_terms:
                add(term, 65)
            ordered = _filter_redundant_keywords([item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))])
        return ordered[:_REVIEW_KEYWORDS_LIMIT]

    fallback = extract_review_keyword_tokens(
        " ".join(part for part in (brand, model, subject_type, video_theme, visible_text) if part),
        seed_terms=seed_terms,
    )
    fallback_keywords: list[str] = []
    fallback_seen: set[str] = set()
    for token in fallback:
        normalized = _normalize_profile_value(token)
        if not normalized:
            continue
        key = "".join(normalized.upper().split())
        if key in fallback_seen:
            continue
        fallback_seen.add(key)
        fallback_keywords.append(token)
    return fallback_keywords[:_REVIEW_KEYWORDS_LIMIT]


def fallback_search_queries_for_profile(profile: Mapping[str, Any], source_name: str) -> list[str]:
    normalized_subject_type = _normalize_main_content_type(str(profile.get("subject_type") or ""))
    source_stem = Path(source_name).stem
    fallback: list[str] = []
    if normalized_subject_type == "unboxing":
        fallback.append("开箱")
    elif normalized_subject_type == "tutorial":
        fallback.append("教程")
    elif normalized_subject_type == "vlog":
        fallback.append("VLOG")
    elif normalized_subject_type == "commentary":
        fallback.append("观点")
    elif normalized_subject_type == "gameplay":
        fallback.append("游戏实况")
    elif normalized_subject_type == "food":
        fallback.append("探店")

    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    content_kind = _normalize_main_content_type(str(profile.get("content_kind") or ""))
    content_kind_fallback = _CONTENT_KIND_DEFAULT_SUBJECT_TYPE.get(content_kind, "").strip()
    if brand:
        fallback.append(brand)
    if model:
        fallback.append(model)
    if content_kind_fallback and content_kind_fallback != normalized_subject_type:
        fallback.append(content_kind_fallback)
    if source_stem and _is_informative_source_hint(source_stem):
        fallback.append(_clean_line(source_stem))
    return [query for query in fallback if query]


__all__ = [
    "build_review_keywords",
    "collect_review_keyword_seed_terms",
    "extract_review_keyword_tokens",
    "fallback_search_queries_for_profile",
    "normalize_query_list",
]
