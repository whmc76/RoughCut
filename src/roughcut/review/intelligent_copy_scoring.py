from __future__ import annotations


def score_title_candidate(
    text: str,
    *,
    topic_subject: str,
    anchor_terms: list[str],
    forbidden_terms: list[str],
) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return -100

    score = 0
    if topic_subject and topic_subject in normalized:
        score += 5
    if any(term and term in normalized for term in anchor_terms[:3]):
        score += 3
    if any(marker in normalized for marker in ("怎么", "值不值", "到底", "开箱", "教程", "对比")):
        score += 2

    text_len = len(normalized)
    if 10 <= text_len <= 22:
        score += 2
    elif text_len < 8:
        score -= 4
    elif text_len > 34:
        score -= 2

    if normalized.count("这期") and not topic_subject:
        score -= 2
    if all(term not in normalized for term in anchor_terms[:2] if term):
        score -= 2
    if any(term and term in normalized for term in forbidden_terms):
        score -= 20
    return score


def score_description(
    text: str,
    *,
    topic_subject: str,
    anchor_terms: list[str],
    question: str,
    forbidden_terms: list[str],
) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return -100

    score = 0
    if topic_subject and topic_subject in normalized:
        score += 5
    if any(term and term in normalized for term in anchor_terms[:4]):
        score += 4
    if question and question in normalized:
        score += 2
    elif "？" in normalized or "?" in normalized:
        score += 1

    text_len = len(normalized)
    if text_len >= 40:
        score += 2
    elif text_len < 24:
        score -= 5

    if any(term and term in normalized for term in forbidden_terms):
        score -= 20
    if "这期" in normalized and not any(term and term in normalized for term in anchor_terms[:2]):
        score -= 2
    return score
