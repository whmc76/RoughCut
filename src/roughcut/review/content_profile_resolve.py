from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from roughcut.review.content_profile_scoring import ScoredIdentityCandidate


@dataclass(frozen=True)
class ResolvedIdentity:
    subject_brand: str
    subject_model: str
    subject_type: str
    video_theme: str
    conflicts: tuple[str, ...] = ()


def resolve_identity_candidates(
    scored: dict[str, list[ScoredIdentityCandidate]],
    *,
    normalize: Callable[[object], str],
    mapped_brand_for_model: Callable[[object], str],
) -> ResolvedIdentity:
    conflicts: list[str] = []
    if _has_current_identity_conflict(scored):
        conflicts.append("current_identity_conflict")
        return ResolvedIdentity(
            subject_brand="",
            subject_model="",
            subject_type=_pick_supported_candidate(scored.get("subject_type") or []),
            video_theme=_pick_supported_candidate(scored.get("video_theme") or []),
            conflicts=tuple(conflicts),
        )
    brand = _pick_supported_candidate(scored.get("subject_brand") or [])
    model = _pick_supported_candidate(scored.get("subject_model") or [])
    subject_type = _pick_supported_candidate(scored.get("subject_type") or [])
    video_theme = _pick_supported_candidate(scored.get("video_theme") or [])

    mapped_brand = mapped_brand_for_model(model) if model else ""
    if mapped_brand and brand and normalize(mapped_brand) != normalize(brand):
        conflicts.append("brand_model_conflict")
        brand = ""
    elif mapped_brand and not brand:
        brand = mapped_brand

    return ResolvedIdentity(
        subject_brand=brand,
        subject_model=model,
        subject_type=subject_type,
        video_theme=video_theme,
        conflicts=tuple(conflicts),
    )


def _pick_supported_candidate(candidates: list[ScoredIdentityCandidate]) -> str:
    if not candidates:
        return ""
    best = candidates[0]
    if best.current_source_count <= 0 or best.current_evidence_score <= 0:
        return ""
    return best.value


def _has_current_identity_conflict(
    scored: dict[str, list[ScoredIdentityCandidate]],
) -> bool:
    for field_name in ("subject_brand", "subject_model"):
        source_values = _collect_current_source_values(scored.get(field_name) or [])
        transcript_value = source_values.get("transcript_labels") or source_values.get("transcript")
        ocr_value = source_values.get("ocr") or source_values.get("visual_cluster")
        if transcript_value and ocr_value and transcript_value != ocr_value:
            return True
    return False


def _collect_current_source_values(
    candidates: list[ScoredIdentityCandidate],
) -> dict[str, str]:
    values: dict[str, str] = {}
    for candidate in candidates:
        if candidate.current_evidence_score <= 0:
            continue
        for source in candidate.all_sources:
            if source in {"profile", "memory_confirmed", "graph_confirmed"}:
                continue
            values.setdefault(source, candidate.normalized_value)
    return values
