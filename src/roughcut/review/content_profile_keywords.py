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
    "实测",
    "介绍",
    "对比",
    "上手",
    "内容",
    "产品",
    "视频",
    "主题",
}
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
    for match in re.finditer(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9+-]{1,23}", str(text or "")):
        token = match.group(0).strip()
        if len(token) < 2:
            continue
        if token in {"主要围绕", "内容方向", "产品开箱与上手体验"}:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
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
    normalized = _normalize_profile_value(token)
    if not normalized or len(normalized) < _REVIEW_KEYWORDS_MIN_LEN:
        return []
    if normalized in seen:
        return []
    seen.add(normalized)
    return [token]


def _expand_long_review_keyword_chunk(chunk: str, seed_terms: list[str]) -> list[str]:
    normalized_chunk = chunk.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
    if not normalized_chunk:
        return []
    extracted: list[str] = []
    seen: set[str] = set()
    remainder = normalized_chunk
    for term in seed_terms:
        if len(term) < _REVIEW_KEYWORDS_MIN_LEN:
            continue
        if term in remainder:
            if re.fullmatch(r"[一-龥]+", term) and len(term) > 4:
                continue
            extracted.extend(_collect_review_keyword_piece(term, seen))
            if not extracted:
                continue
            remainder = remainder.replace(term, " ")
    for part in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(remainder):
        segment = part.strip()
        if not segment:
            continue
        if len(segment) <= 4:
            extracted.extend(_collect_review_keyword_piece(segment, seen))
            continue
        for window in (4, 3, 2):
            if len(extracted) >= 8:
                break
            for index in range(0, max(0, len(segment) - window + 1), 2):
                token = segment[index : index + window]
                if token in _REVIEW_KEYWORD_NOISE_CHUNKS:
                    continue
                extracted.extend(_collect_review_keyword_piece(token, seen))
                if len(extracted) >= 8:
                    break
        if len(extracted) >= 8:
            break
    return extracted


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
        normalized_candidate = _REVIEW_KEYWORD_CONNECTOR_RE.sub(" ", candidate)
        for part in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(normalized_candidate):
            segment = part.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
            if not segment:
                continue
            if re.search(r"[一-龥]", segment) and re.search(r"[A-Za-z0-9]", segment):
                tokens.append(segment)
                continue
            if re.fullmatch(r"[A-Za-z0-9+#\-]+", segment):
                tokens.append(segment)
                continue
            if re.fullmatch(r"[一-龥]{2,}", segment) and len(segment) > 6:
                tokens.extend(_expand_long_review_keyword_chunk(segment, sorted_seeds))
                continue
            tokens.extend(_REVIEW_KEYWORD_CHUNK_FALLBACK_PART_RE.findall(segment))

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in _REVIEW_KEYWORD_NOISE_CHUNKS:
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
    for field_name in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "visible_text",
        "transcript_excerpt",
    ):
        text = str(profile_values.get(field_name) or "").strip()
        if not text:
            continue
        for token in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(text):
            token = token.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
            if token:
                raw_terms.append(token)
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
        cleaned = str(term or "").strip()
        if not cleaned:
            return
        normalized = _normalize_profile_value(cleaned)
        if not normalized or len(normalized) < _REVIEW_KEYWORDS_MIN_LEN:
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
    for term in _extract_topic_terms(video_theme):
        add(term, 110)
    for term in _extract_search_signal_terms(transcript_excerpt, visible_text, _clean_line(source_name)):
        add(term, 105)
    for term in extract_review_keyword_tokens(visible_text, seed_terms=seed_terms):
        add(term, 95)
    for query in raw_queries:
        for token in extract_review_keyword_tokens(query, seed_terms=seed_terms):
            add(token, 90)
    for term in _extract_query_support_terms(video_theme):
        add(term, 85)
    for term in _extract_topic_terms(visible_text):
        add(term, 80)
    for term in seed_terms:
        add(term, 70)

    ordered = [item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))]
    if ordered:
        if len(ordered) < _REVIEW_KEYWORD_MIN_COUNT and seed_terms:
            for term in seed_terms:
                add(term, 65)
            ordered = [item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))]
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
