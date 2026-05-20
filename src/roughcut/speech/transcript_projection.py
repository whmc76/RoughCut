from __future__ import annotations

from roughcut.speech.subtitle_pipeline import (
    build_canonical_transcript_layer_from_transcript_segments,
    build_subtitle_projection_layer_from_transcript_segments,
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
