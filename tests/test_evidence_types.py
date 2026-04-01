from __future__ import annotations

from types import SimpleNamespace

from roughcut.review.evidence_types import (
    ARTIFACT_TYPE_CONTENT_PROFILE_OCR,
    ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE,
    ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
    build_correction_framework_trace,
    enabled_evidence_artifact_types,
)


def test_build_correction_framework_trace_reports_disabled_flags_by_default():
    settings = SimpleNamespace(
        correction_framework_version="multisource_v1",
        ocr_enabled=False,
        entity_graph_enabled=False,
        asr_evidence_enabled=False,
        research_verifier_enabled=False,
    )

    trace = build_correction_framework_trace(settings)

    assert trace == {
        "version": "multisource_v1",
        "flags": {
            "ocr_enabled": False,
            "entity_graph_enabled": False,
            "asr_evidence_enabled": False,
            "research_verifier_enabled": False,
        },
    }


def test_enabled_evidence_artifact_types_respect_feature_flags():
    disabled = SimpleNamespace(
        ocr_enabled=False,
        entity_graph_enabled=False,
        asr_evidence_enabled=False,
        research_verifier_enabled=False,
    )
    enabled = SimpleNamespace(
        ocr_enabled=True,
        entity_graph_enabled=True,
        asr_evidence_enabled=True,
        research_verifier_enabled=False,
    )

    assert enabled_evidence_artifact_types(disabled) == set()
    assert enabled_evidence_artifact_types(enabled) == {
        ARTIFACT_TYPE_CONTENT_PROFILE_OCR,
        ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE,
        ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
    }
