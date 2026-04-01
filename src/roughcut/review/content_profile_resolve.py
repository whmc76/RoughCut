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
