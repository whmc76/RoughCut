from __future__ import annotations

from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    CanonicalTranscriptLayer,
    CanonicalTranscriptSegment,
    SubtitleProjectionEntry,
    SubtitleProjectionLayer,
    TranscriptFactLayer,
    TranscriptFactSegment,
    TranscriptFactWord,
    build_canonical_transcript_layer,
    build_subtitle_architecture_artifacts,
    build_subtitle_projection_layer,
    build_transcript_fact_layer,
)
