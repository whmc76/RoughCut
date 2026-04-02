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
    source_maps: list[tuple[str, dict[str, str]]] = [
        ("transcript_labels", bundle.transcript_source_labels),
        ("ocr", bundle.ocr_hints),
        ("profile", bundle.profile_identity),
        ("memory_confirmed", bundle.memory_confirmed_hints),
        ("transcript", bundle.transcript_hints),
        ("source_name", bundle.source_hints),
        ("visual_cluster", bundle.visual_cluster_hints),
    ]
    if _legacy_visual_hints_add_new_signal(bundle):
        source_maps.append(("visual", bundle.visual_hints))
    source_maps.append(("visible_text", bundle.visible_text_hints))
    for source_type, hints in source_maps:
        for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme"):
            for value in _collect_field_values(hints, field_name):
                candidates.append(
                    IdentityCandidate(
                        field_name=field_name,
                        value=value,
                        source_type=source_type,
                        excerpt=_source_excerpt(bundle, source_type),
                    )
                )
    for entity in bundle.graph_confirmed_entities or []:
        for field_name, key in (
            ("subject_brand", "brand"),
            ("subject_model", "model"),
            ("subject_type", "subject_type"),
        ):
            value = str(entity.get(key) or "").strip()
            if value:
                candidates.append(
                    IdentityCandidate(
                        field_name=field_name,
                        value=value,
                        source_type="graph_confirmed",
                        excerpt=_source_excerpt(bundle, "graph_confirmed"),
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
    if source_type == "ocr":
        return str((bundle.ocr_hints or {}).get("visible_text") or "").strip()
    if source_type == "visual_cluster":
        return str((bundle.visual_cluster_hints or {}).get("visible_text") or "").strip()
    if source_type == "visual":
        return str((bundle.visual_hints or {}).get("visible_text") or "").strip()
    if source_type == "graph_confirmed":
        return "graph_confirmed"
    return ""


def _legacy_visual_hints_add_new_signal(bundle: IdentityEvidenceBundle) -> bool:
    legacy = bundle.visual_hints or {}
    cluster = bundle.visual_cluster_hints or {}
    for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme", "visible_text"):
        legacy_values = _collect_field_values(legacy, field_name)
        cluster_values = _collect_field_values(cluster, field_name)
        if legacy_values and legacy_values != cluster_values:
            return True
    return False


def _collect_field_values(hints: dict[str, str], field_name: str) -> list[str]:
    values: list[str] = []
    direct = str((hints or {}).get(field_name) or "").strip()
    if direct:
        values.append(direct)
    for item in (hints or {}).get(f"{field_name}_candidates") or []:
        text = str(item or "").strip()
        if text and text not in values:
            values.append(text)
    return values
