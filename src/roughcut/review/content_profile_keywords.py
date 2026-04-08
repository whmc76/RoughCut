from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable, Mapping

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


def _default_clean_line(text: Any) -> str:
    return " ".join(str(text or "").replace("\u3000", " ").split())


def _default_normalize_profile_value(text: Any) -> str:
    return "".join(_default_clean_line(text).casefold().split())


def _default_extract_topic_terms(_text: str) -> list[str]:
    return []


def _default_extract_search_signal_terms(
    _transcript_excerpt: str,
    _visible_text: str,
    _source_name: str,
) -> list[str]:
    return []


def _default_extract_query_support_terms(_text: str) -> list[str]:
    return []


def _default_looks_like_camera_stem(_text: str) -> bool:
    return False


def _default_normalize_main_content_type(value: str) -> str:
    return str(value or "").strip().lower()


def _default_is_informative_source_hint(_text: str) -> bool:
    return True


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


def _collect_review_keyword_piece(
    token: str,
    seen: set[str],
    *,
    normalize_value: Callable[[Any], str],
    min_len: int,
) -> list[str]:
    normalized = normalize_value(token)
    if not normalized or len(normalized) < min_len:
        return []
    if normalized in seen:
        return []
    seen.add(normalized)
    return [token]


def _expand_long_review_keyword_chunk(
    chunk: str,
    seed_terms: list[str],
    *,
    normalize_value: Callable[[Any], str],
    min_len: int,
    noise_chunks: set[str],
) -> list[str]:
    normalized_chunk = chunk.strip(_KEYWORD_TOKEN_STRIP_CHARS).strip()
    if not normalized_chunk:
        return []
    extracted: list[str] = []
    seen: set[str] = set()
    remainder = normalized_chunk
    for term in seed_terms:
        if len(term) < min_len:
            continue
        if term in remainder:
            if re.fullmatch(r"[一-龥]+", term) and len(term) > 4:
                continue
            extracted.extend(
                _collect_review_keyword_piece(
                    term,
                    seen,
                    normalize_value=normalize_value,
                    min_len=min_len,
                )
            )
            if not extracted:
                continue
            remainder = remainder.replace(term, " ")
    for part in _REVIEW_KEYWORD_TERM_SPLIT_RE.split(remainder):
        segment = part.strip()
        if not segment:
            continue
        if len(segment) <= 4:
            extracted.extend(
                _collect_review_keyword_piece(
                    segment,
                    seen,
                    normalize_value=normalize_value,
                    min_len=min_len,
                )
            )
            continue
        for window in (4, 3, 2):
            if len(extracted) >= 8:
                break
            for index in range(0, max(0, len(segment) - window + 1), 2):
                token = segment[index : index + window]
                if token in noise_chunks:
                    continue
                extracted.extend(
                    _collect_review_keyword_piece(
                        token,
                        seen,
                        normalize_value=normalize_value,
                        min_len=min_len,
                    )
                )
                if len(extracted) >= 8:
                    break
        if len(extracted) >= 8:
            break
    return extracted


def extract_review_keyword_tokens(
    text: str,
    *,
    seed_terms: list[str] | None = None,
    clean_line: Callable[[Any], str] | None = None,
    normalize_value: Callable[[Any], str] | None = None,
    min_len: int = _REVIEW_KEYWORDS_MIN_LEN,
    noise_chunks: set[str] | None = None,
) -> list[str]:
    clean_line_fn = clean_line or _default_clean_line
    normalize_value_fn = normalize_value or _default_normalize_profile_value
    noise = noise_chunks or _REVIEW_KEYWORD_NOISE_CHUNKS

    normalized = clean_line_fn(text).strip()
    if not normalized:
        return []

    seeds = [str(term or "").strip() for term in (seed_terms or []) if str(term or "").strip()]
    if seeds:
        sorted_seeds = [item for item in sorted(set(seeds), key=len, reverse=True) if len(item) >= min_len]
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
                tokens.extend(
                    _expand_long_review_keyword_chunk(
                        segment,
                        sorted_seeds,
                        normalize_value=normalize_value_fn,
                        min_len=min_len,
                        noise_chunks=noise,
                    )
                )
                continue
            tokens.extend(_REVIEW_KEYWORD_CHUNK_FALLBACK_PART_RE.findall(segment))

    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if not token or token in noise:
            continue
        normalized_token = normalize_value_fn(token)
        if len(normalized_token) < min_len:
            continue
        if normalized_token in seen:
            continue
        seen.add(normalized_token)
        deduped.append(token)
    return deduped


def collect_review_keyword_seed_terms(
    profile_values: Mapping[str, Any],
    *,
    extract_tokens: Callable[..., list[str]] = extract_review_keyword_tokens,
    clean_line: Callable[[Any], str] | None = None,
    normalize_value: Callable[[Any], str] | None = None,
    min_len: int = _REVIEW_KEYWORDS_MIN_LEN,
    noise_chunks: set[str] | None = None,
) -> list[str]:
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
        raw_terms.extend(
            extract_tokens(
                source_name,
                seed_terms=[],
                clean_line=clean_line,
                normalize_value=normalize_value,
                min_len=min_len,
                noise_chunks=noise_chunks,
            )
        )
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


def build_review_keywords(
    profile: Mapping[str, Any],
    *,
    collect_seed_terms: Callable[..., list[str]] = collect_review_keyword_seed_terms,
    extract_tokens: Callable[..., list[str]] = extract_review_keyword_tokens,
    clean_line: Callable[[Any], str] | None = None,
    normalize_value: Callable[[Any], str] | None = None,
    looks_like_camera_stem: Callable[[str], bool] | None = None,
    extract_topic_terms: Callable[[str], list[str]] | None = None,
    extract_search_signal_terms: Callable[[str, str, str], list[str]] | None = None,
    extract_query_support_terms: Callable[[str], list[str]] | None = None,
    keywords_limit: int = _REVIEW_KEYWORDS_LIMIT,
    min_keyword_len: int = _REVIEW_KEYWORDS_MIN_LEN,
    min_keyword_count: int = _REVIEW_KEYWORD_MIN_COUNT,
    noise_chunks: set[str] | None = None,
) -> list[str]:
    clean_line_fn = clean_line or _default_clean_line
    normalize_value_fn = normalize_value or _default_normalize_profile_value
    looks_like_camera_stem_fn = looks_like_camera_stem or _default_looks_like_camera_stem
    extract_topic_terms_fn = extract_topic_terms or _default_extract_topic_terms
    extract_search_signal_terms_fn = extract_search_signal_terms or _default_extract_search_signal_terms
    extract_query_support_terms_fn = extract_query_support_terms or _default_extract_query_support_terms

    profile_values = dict(profile or {})
    brand = str(profile_values.get("subject_brand") or "").strip()
    model = str(profile_values.get("subject_model") or "").strip()
    subject_type = str(profile_values.get("subject_type") or "").strip()
    visible_text = str(profile_values.get("visible_text") or "").strip()
    video_theme = str(profile_values.get("video_theme") or "").strip()
    raw_queries = [str(item).strip() for item in (profile_values.get("search_queries") or []) if str(item).strip()]
    transcript_excerpt = str(profile_values.get("transcript_excerpt") or "").strip()
    seed_terms = collect_seed_terms(
        profile_values,
        extract_tokens=extract_tokens,
        clean_line=clean_line_fn,
        normalize_value=normalize_value_fn,
        min_len=min_keyword_len,
        noise_chunks=noise_chunks,
    )

    candidates: list[tuple[int, int, str]] = []
    seen: dict[str, int] = {}

    def add(term: str, weight: int) -> None:
        cleaned = str(term or "").strip()
        if not cleaned:
            return
        normalized = normalize_value_fn(cleaned)
        if not normalized or len(normalized) < min_keyword_len:
            return
        if looks_like_camera_stem_fn(normalized):
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
    for term in extract_topic_terms_fn(video_theme):
        add(term, 110)
    for term in extract_search_signal_terms_fn(transcript_excerpt, visible_text, clean_line_fn(profile_values.get("source_name") or "")):
        add(term, 105)
    for term in extract_tokens(
        visible_text,
        seed_terms=seed_terms,
        clean_line=clean_line_fn,
        normalize_value=normalize_value_fn,
        min_len=min_keyword_len,
        noise_chunks=noise_chunks,
    ):
        add(term, 95)
    for query in raw_queries:
        for token in extract_tokens(
            query,
            seed_terms=seed_terms,
            clean_line=clean_line_fn,
            normalize_value=normalize_value_fn,
            min_len=min_keyword_len,
            noise_chunks=noise_chunks,
        ):
            add(token, 90)
    for term in extract_query_support_terms_fn(video_theme):
        add(term, 85)
    for term in extract_topic_terms_fn(visible_text):
        add(term, 80)
    for term in seed_terms:
        add(term, 70)

    ordered = [item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))]
    if ordered:
        if len(ordered) < min_keyword_count and seed_terms:
            for term in seed_terms:
                add(term, 65)
            ordered = [item[2] for item in sorted(candidates, key=lambda item: (-item[0], item[1]))]
        return ordered[:keywords_limit]

    fallback = extract_tokens(
        " ".join(part for part in (brand, model, subject_type, video_theme, visible_text) if part),
        seed_terms=seed_terms,
        clean_line=clean_line_fn,
        normalize_value=normalize_value_fn,
        min_len=min_keyword_len,
        noise_chunks=noise_chunks,
    )
    fallback_keywords: list[str] = []
    fallback_seen: set[str] = set()
    for token in fallback:
        normalized = normalize_value_fn(token)
        if not normalized:
            continue
        key = "".join(normalized.upper().split())
        if key in fallback_seen:
            continue
        fallback_seen.add(key)
        fallback_keywords.append(token)
    return fallback_keywords[:keywords_limit]


def fallback_search_queries_for_profile(
    profile: Mapping[str, Any],
    source_name: str,
    *,
    normalize_main_content_type: Callable[[str], str] | None = None,
    content_kind_default_subject_type: Mapping[str, str] | None = None,
    is_informative_source_hint: Callable[[str], bool] | None = None,
    clean_line: Callable[[Any], str] | None = None,
    default_query: str = "视频内容",
) -> list[str]:
    normalize_main_content_type_fn = normalize_main_content_type or _default_normalize_main_content_type
    is_informative_source_hint_fn = is_informative_source_hint or _default_is_informative_source_hint
    clean_line_fn = clean_line or _default_clean_line
    content_kind_default_subject_type_map = dict(content_kind_default_subject_type or {})

    normalized_subject_type = normalize_main_content_type_fn(str(profile.get("subject_type") or ""))
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
    content_kind = normalize_main_content_type_fn(str(profile.get("content_kind") or ""))
    content_kind_fallback = str(content_kind_default_subject_type_map.get(content_kind, "")).strip()
    if brand:
        fallback.append(brand)
    if model:
        fallback.append(model)
    if content_kind_fallback and content_kind_fallback != normalized_subject_type:
        fallback.append(content_kind_fallback)
    if source_stem and is_informative_source_hint_fn(source_stem):
        fallback.append(clean_line_fn(source_stem))
    if not fallback:
        fallback.append(default_query)
    return [query for query in fallback if query]


__all__ = [
    "build_review_keywords",
    "collect_review_keyword_seed_terms",
    "extract_review_keyword_tokens",
    "fallback_search_queries_for_profile",
    "normalize_query_list",
]
