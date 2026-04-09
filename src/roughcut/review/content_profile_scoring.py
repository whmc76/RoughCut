from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from roughcut.review.content_profile_candidates import IdentityCandidate

_CURRENT_EVIDENCE_WEIGHTS: dict[str, int] = {
    "transcript_labels": 5,
    "source_context": 2,
    "ocr": 4,
    "transcript": 4,
    "source_name": 3,
    "visual_cluster": 4,
    "visual": 3,
    "visible_text": 2,
    "memory_confirmed": 2,
    "graph_confirmed": 1,
    "profile": 0,
}
_NON_CURRENT_EVIDENCE_SOURCES = {"profile", "memory_confirmed", "graph_confirmed"}


@dataclass(frozen=True)
class ScoredIdentityCandidate:
    field_name: str
    value: str
    normalized_value: str
    total_score: int
    current_evidence_score: int
    current_source_count: int
    all_sources: tuple[str, ...]


def score_identity_candidates(
    candidates: list[IdentityCandidate],
    *,
    normalize: Callable[[object], str],
) -> dict[str, list[ScoredIdentityCandidate]]:
    grouped: dict[tuple[str, str], dict[str, object]] = {}
    for candidate in candidates:
        normalized = normalize(candidate.value)
        if not normalized:
            continue
        key = (candidate.field_name, normalized)
        current = grouped.setdefault(
            key,
            {
                "field_name": candidate.field_name,
                "value": candidate.value,
                "sources": set(),
                "current_evidence_score": 0,
                "total_score": 0,
            },
        )
        sources = current["sources"]
        if candidate.source_type in sources:
            continue
        sources.add(candidate.source_type)
        weight = _CURRENT_EVIDENCE_WEIGHTS.get(candidate.source_type, 0)
        current["total_score"] += weight
        if candidate.source_type not in _NON_CURRENT_EVIDENCE_SOURCES:
            current["current_evidence_score"] += weight
        if len(str(candidate.value)) > len(str(current["value"])):
            current["value"] = candidate.value

    scored: dict[str, list[ScoredIdentityCandidate]] = {}
    for (field_name, normalized), item in grouped.items():
        sources = tuple(sorted(item["sources"]))
        scored.setdefault(field_name, []).append(
            ScoredIdentityCandidate(
                field_name=field_name,
                value=str(item["value"]),
                normalized_value=normalized,
                total_score=int(item["total_score"]),
                current_evidence_score=int(item["current_evidence_score"]),
                current_source_count=sum(1 for source in sources if source not in _NON_CURRENT_EVIDENCE_SOURCES),
                all_sources=sources,
            )
        )
    for field_name in scored:
        scored[field_name].sort(
            key=lambda item: (
                item.current_evidence_score,
                item.current_source_count,
                item.total_score,
                len(item.value),
            ),
            reverse=True,
        )
    return scored
