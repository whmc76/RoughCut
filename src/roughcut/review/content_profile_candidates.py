from __future__ import annotations

from dataclasses import dataclass

from roughcut.review.content_profile_evidence import IdentityEvidenceBundle


@dataclass(frozen=True)
class IdentityCandidate:
    field_name: str
    value: str
    source_type: str
    excerpt: str = ""


def build_identity_candidates(bundle: IdentityEvidenceBundle) -> list[IdentityCandidate]:
    candidates: list[IdentityCandidate] = []
    source_maps = (
        ("profile", bundle.profile_identity),
        ("transcript", bundle.transcript_hints),
        ("source_name", bundle.source_hints),
        ("visual", bundle.visual_hints),
        ("visible_text", bundle.visible_text_hints),
    )
    for source_type, hints in source_maps:
        for field_name in ("subject_brand", "subject_model", "subject_type"):
            value = str((hints or {}).get(field_name) or "").strip()
            if value:
                candidates.append(
                    IdentityCandidate(
                        field_name=field_name,
                        value=value,
                        source_type=source_type,
                        excerpt=_source_excerpt(bundle, source_type),
                    )
                )
    return candidates


def _source_excerpt(bundle: IdentityEvidenceBundle, source_type: str) -> str:
    if source_type == "transcript":
        return bundle.transcript_excerpt
    if source_type == "source_name":
        return bundle.source_name
    if source_type == "visible_text":
        return str((bundle.visible_text_hints or {}).get("visible_text") or "").strip()
    if source_type == "visual":
        return str((bundle.visual_hints or {}).get("visible_text") or "").strip()
    return ""
