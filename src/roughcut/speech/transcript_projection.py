from __future__ import annotations

from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    CanonicalTranscriptLayer,
    CanonicalTranscriptSegment,
    SubtitleProjectionEntry,
    SubtitleProjectionLayer,
    TranscriptSourceSegment,
    TranscriptFactLayer,
    TranscriptFactSegment,
    TranscriptFactWord,
    build_canonical_transcript_layer,
    build_canonical_transcript_layer_from_transcript_segments,
    build_subtitle_projection_layer_from_transcript_segments,
    build_subtitle_architecture_artifacts,
    build_subtitle_projection_layer,
    build_transcript_fact_layer,
)


def build_transcript_first_canonical_transcript_layer(
    transcript_segments,
    *,
    corrections=None,
    source_basis: str = "transcript_first",
    reference_segments=None,
):
    return build_canonical_transcript_layer_from_transcript_segments(
        transcript_segments,
        corrections=corrections,
        source_basis=source_basis,
        reference_segments=reference_segments,
    )


def build_transcript_projection_layer(
    transcript_segments,
    *,
    segmentation_analysis,
    split_profile,
    boundary_refine,
    quality_report,
    projection_basis: str = "transcript_first",
    transcript_layer: str = "transcript_projection",
):
    return build_subtitle_projection_layer_from_transcript_segments(
        transcript_segments,
        segmentation_analysis=segmentation_analysis,
        split_profile=split_profile,
        boundary_refine=boundary_refine,
        quality_report=quality_report,
        projection_basis=projection_basis,
        transcript_layer=transcript_layer,
    )
