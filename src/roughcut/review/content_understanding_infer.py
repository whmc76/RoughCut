from __future__ import annotations

from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity


def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    payload = data if isinstance(data, dict) else {}

    subject_entities: list[SubjectEntity] = []
    for item in list(payload.get("subject_entities") or []):
        if not isinstance(item, dict):
            continue
        subject_entities.append(
            SubjectEntity(
                kind=str(item.get("kind") or "").strip(),
                name=str(item.get("name") or "").strip(),
                brand=str(item.get("brand") or "").strip(),
                model=str(item.get("model") or "").strip(),
            )
        )

    confidence: dict[str, float] = {}
    raw_confidence = payload.get("confidence")
    if isinstance(raw_confidence, dict):
        for key, value in raw_confidence.items():
            try:
                confidence[str(key)] = float(value)
            except (TypeError, ValueError):
                continue

    return ContentUnderstanding(
        video_type=str(payload.get("video_type") or "").strip(),
        content_domain=str(payload.get("content_domain") or "").strip(),
        primary_subject=str(payload.get("primary_subject") or "").strip(),
        subject_entities=subject_entities,
        video_theme=str(payload.get("video_theme") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        hook_line=str(payload.get("hook_line") or "").strip(),
        engagement_question=str(payload.get("engagement_question") or "").strip(),
        search_queries=[str(item).strip() for item in list(payload.get("search_queries") or []) if str(item).strip()],
        evidence_spans=[dict(item) for item in list(payload.get("evidence_spans") or []) if isinstance(item, dict)],
        uncertainties=[str(item).strip() for item in list(payload.get("uncertainties") or []) if str(item).strip()],
        confidence=confidence,
        needs_review=bool(payload.get("needs_review", True)),
        review_reasons=[str(item).strip() for item in list(payload.get("review_reasons") or []) if str(item).strip()],
    )


async def infer_content_understanding(evidence_bundle: dict[str, Any]) -> ContentUnderstanding:
    provider = get_reasoning_provider()
    transcript_excerpt = str(evidence_bundle.get("transcript_excerpt") or "").strip()
    prompt = (
        "你是严谨的视频内容理解引擎。根据证据包推断一个通用内容理解结果，"
        "只输出 JSON，字段必须包括 video_type, content_domain, primary_subject, subject_entities, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        f"\n证据包: {evidence_bundle}"
    )
    if transcript_excerpt:
        prompt += f"\n转写片段: {transcript_excerpt}"

    response = await provider.complete(
        [
            Message(role="system", content="你是内容理解分析器，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=1200,
        json_mode=True,
    )
    return parse_content_understanding_payload(response.as_json())
