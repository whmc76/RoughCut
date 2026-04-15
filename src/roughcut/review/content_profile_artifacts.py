from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roughcut.db.models import Artifact
from roughcut.review.downstream_context import build_downstream_context

ARTIFACT_TYPE_CONTENT_PROFILE_DRAFT = "content_profile_draft"
ARTIFACT_TYPE_CONTENT_PROFILE_FINAL = "content_profile_final"


@dataclass(frozen=True, slots=True)
class ContentProfileArtifactPayloads:
    draft_profile: dict[str, Any]
    final_profile: dict[str, Any] | None
    downstream_context: dict[str, Any]
    subtitle_quality_report: dict[str, Any]
    ocr_profile: dict[str, Any] | None = None


def build_content_profile_artifact_payloads(
    *,
    draft_profile: dict[str, Any],
    final_profile: dict[str, Any] | None,
    downstream_profile: dict[str, Any],
    subtitle_quality_report: dict[str, Any],
    ocr_profile: dict[str, Any] | None = None,
) -> ContentProfileArtifactPayloads:
    return ContentProfileArtifactPayloads(
        draft_profile=dict(draft_profile),
        final_profile=dict(final_profile) if final_profile is not None else None,
        downstream_context=build_downstream_context(downstream_profile),
        subtitle_quality_report=dict(subtitle_quality_report),
        ocr_profile=dict(ocr_profile) if ocr_profile is not None else None,
    )


def persist_content_profile_artifacts(
    session,
    *,
    job,
    step,
    review_step,
    draft_profile: dict[str, Any],
    final_profile: dict[str, Any] | None,
    downstream_profile: dict[str, Any],
    subtitle_quality_report: dict[str, Any],
    ocr_profile: dict[str, Any] | None = None,
) -> None:
    payloads = build_content_profile_artifact_payloads(
        draft_profile=draft_profile,
        final_profile=final_profile,
        downstream_profile=downstream_profile,
        subtitle_quality_report=subtitle_quality_report,
        ocr_profile=ocr_profile,
    )
    if payloads.ocr_profile is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="content_profile_ocr",
                data_json=payloads.ocr_profile,
            )
        )
    session.add(
        Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type=ARTIFACT_TYPE_CONTENT_PROFILE_DRAFT,
            data_json=payloads.draft_profile,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="subtitle_quality_report",
            data_json=payloads.subtitle_quality_report,
        )
    )
    session.add(
        Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="downstream_context",
            data_json=payloads.downstream_context,
        )
    )
    if payloads.final_profile is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=review_step.id if review_step else None,
                artifact_type=ARTIFACT_TYPE_CONTENT_PROFILE_FINAL,
                data_json=payloads.final_profile,
            )
        )
