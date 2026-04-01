from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ARTIFACT_TYPE_CONTENT_PROFILE_OCR = "content_profile_ocr"
ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE = "transcript_evidence"
ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE = "entity_resolution_trace"


def _flag(settings: object, name: str) -> bool:
    return bool(getattr(settings, name, False))


def build_correction_framework_trace(settings: object) -> dict[str, Any]:
    return {
        "version": str(getattr(settings, "correction_framework_version", "multisource_v1") or "multisource_v1"),
        "flags": {
            "ocr_enabled": _flag(settings, "ocr_enabled"),
            "entity_graph_enabled": _flag(settings, "entity_graph_enabled"),
            "asr_evidence_enabled": _flag(settings, "asr_evidence_enabled"),
            "research_verifier_enabled": _flag(settings, "research_verifier_enabled"),
        },
    }


def enabled_evidence_artifact_types(settings: object) -> set[str]:
    artifact_types: set[str] = set()
    if _flag(settings, "ocr_enabled"):
        artifact_types.add(ARTIFACT_TYPE_CONTENT_PROFILE_OCR)
    if _flag(settings, "entity_graph_enabled"):
        artifact_types.add(ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE)
    if _flag(settings, "asr_evidence_enabled"):
        artifact_types.add(ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE)
    return artifact_types


@dataclass(slots=True)
class EvidenceHit:
    source: str
    value: str
    confidence: float | None = None
    start_time: float | None = None
    end_time: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EntityCandidate:
    field_name: str
    canonical_value: str
    confidence: float | None = None
    evidence: list[EvidenceHit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EntityObservation:
    field_name: str
    observed_value: str
    source: str
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OcrFrameResult:
    frame_index: int
    timestamp: float | None = None
    lines: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TranscriptEvidence:
    provider: str | None = None
    model: str | None = None
    prompt: str | None = None
    hotwords: list[str] = field(default_factory=list)
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
