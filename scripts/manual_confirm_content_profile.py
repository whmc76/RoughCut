from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from sqlalchemy import select

from roughcut.db.models import Artifact, Job, JobStep, SubtitleCorrection, SubtitleItem
from roughcut.db.session import get_session_factory
from roughcut.edit.presets import get_workflow_preset
from roughcut.review.content_profile import (
    apply_content_profile_feedback,
    apply_identity_review_guard,
    assess_content_profile_automation,
    build_cover_title,
    build_reviewed_transcript_excerpt,
)
from roughcut.review.content_profile_memory import (
    build_content_profile_memory_cloud,
    load_content_profile_user_memory,
    record_content_profile_feedback_memory,
)
from roughcut.review.content_profile_review_stats import (
    build_content_profile_auto_review_gate,
    record_content_profile_manual_review,
)


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Manually confirm a RoughCut content profile and persist content_profile_final."
    )
    parser.add_argument("--job-id", required=True, help="Target RoughCut job UUID.")
    parser.add_argument("--payload-json", type=Path, required=True, help="Manual confirmation payload JSON.")
    parser.add_argument(
        "--output-json",
        type=Path,
        default=ROOT / "output" / "manual-content-profile-confirm.json",
        help="Where to write the confirmation summary.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Compute final profile but do not write database changes.")
    return parser.parse_args()


def _load_payload(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("payload-json must contain a JSON object.")
    return payload


def _merge_manual_fields(draft_profile: dict[str, Any], user_feedback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(draft_profile or {})
    merged["user_feedback"] = dict(user_feedback or {})
    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
        "summary",
        "engagement_question",
        "copy_style",
        "correction_notes",
        "supplemental_context",
    ):
        value = user_feedback.get(key)
        if value:
            merged[key] = str(value).strip()
    keywords = [str(item).strip() for item in (user_feedback.get("keywords") or []) if str(item).strip()]
    if keywords:
        merged["search_queries"] = keywords
    evidence_items = []
    for item in user_feedback.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        if title or url or snippet:
            evidence_items.append({"title": title, "url": url, "snippet": snippet})
    if evidence_items:
        merged["evidence"] = evidence_items
    merged["review_mode"] = "manual_confirmed"
    return merged


async def _confirm(args: argparse.Namespace) -> dict[str, Any]:
    load_env_file(ROOT / ".env")
    payload = _load_payload(args.payload_json)
    job_uuid = uuid.UUID(args.job_id)

    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_uuid)
        if job is None:
            raise RuntimeError(f"Job not found: {args.job_id}")

        draft_result = await session.execute(
            select(Artifact)
            .where(Artifact.job_id == job.id, Artifact.artifact_type == "content_profile_draft")
            .order_by(Artifact.created_at.desc())
        )
        draft_artifact = draft_result.scalars().first()
        if draft_artifact is None:
            raise RuntimeError("content_profile_draft not found")

        subtitle_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = subtitle_result.scalars().all()

        correction_result = await session.execute(
            select(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id)
        )
        corrections = correction_result.scalars().all()
        accepted_corrections = [
            {
                "item_index": next(
                    (
                        item.item_index
                        for item in subtitle_items
                        if correction.subtitle_item_id and item.id == correction.subtitle_item_id
                    ),
                    None,
                ),
                "original": correction.original_span,
                "accepted": str(correction.human_override or correction.suggested_span or "").strip(),
            }
            for correction in corrections
            if correction.human_decision == "accepted"
        ]
        subtitle_payload = [
            {
                "index": item.item_index,
                "start_time": item.start_time,
                "end_time": item.end_time,
                "text_raw": item.text_raw,
                "text_norm": item.text_norm,
                "text_final": item.text_final,
            }
            for item in subtitle_items
        ]
        reviewed_excerpt = build_reviewed_transcript_excerpt(subtitle_payload, accepted_corrections)
        user_memory = await load_content_profile_user_memory(session, channel_profile=job.channel_profile)

        try:
            final_profile = await apply_content_profile_feedback(
                draft_profile=draft_artifact.data_json or {},
                source_name=job.source_name,
                channel_profile=job.channel_profile,
                user_feedback=payload,
                reviewed_subtitle_excerpt=reviewed_excerpt,
                accepted_corrections=accepted_corrections,
            )
        except Exception:
            final_profile = _merge_manual_fields(draft_artifact.data_json or {}, payload)
            final_profile["transcript_excerpt"] = reviewed_excerpt
            preset = get_workflow_preset(str(final_profile.get("preset_name") or job.channel_profile or "unboxing_default"))
            final_profile["cover_title"] = build_cover_title(final_profile, preset)
            final_profile = apply_identity_review_guard(
                final_profile,
                subtitle_items=subtitle_payload,
                user_memory=user_memory,
                glossary_terms=[],
                source_name=job.source_name,
            )
            final_profile["automation_review"] = assess_content_profile_automation(
                final_profile,
                subtitle_items=subtitle_payload,
                user_memory=user_memory,
                glossary_terms=[],
                source_name=job.source_name,
            )

        final_profile = _merge_manual_fields(final_profile, payload)
        final_profile["transcript_excerpt"] = reviewed_excerpt
        preset = get_workflow_preset(str(final_profile.get("preset_name") or job.channel_profile or "unboxing_default"))
        final_profile["cover_title"] = build_cover_title(final_profile, preset)
        final_profile = apply_identity_review_guard(
            final_profile,
            subtitle_items=subtitle_payload,
            user_memory=user_memory,
            glossary_terms=[],
            source_name=job.source_name,
        )
        final_profile["automation_review"] = assess_content_profile_automation(
            final_profile,
            subtitle_items=subtitle_payload,
            user_memory=user_memory,
            glossary_terms=[],
            source_name=job.source_name,
        )

        manual_review_outcome = record_content_profile_manual_review(
            job_id=str(job.id),
            draft_artifact_id=str(draft_artifact.id),
            draft_profile=draft_artifact.data_json or {},
            final_profile=final_profile,
        )
        final_profile["manual_review_outcome"] = manual_review_outcome

        automation_review = final_profile.get("automation_review")
        if isinstance(automation_review, dict):
            accuracy_gate = build_content_profile_auto_review_gate(min_accuracy=0.9, min_samples=20)
            automation_review.update(
                {
                    "approval_accuracy_gate_passed": bool(accuracy_gate["gate_passed"]),
                    "approval_accuracy": accuracy_gate["measured_accuracy"],
                    "approval_accuracy_required": accuracy_gate["required_accuracy"],
                    "approval_accuracy_sample_size": accuracy_gate["sample_size"],
                    "approval_accuracy_min_samples": accuracy_gate["minimum_sample_size"],
                    "approval_accuracy_detail": accuracy_gate["detail"],
                    "manual_review_sample_size": accuracy_gate["manual_review_total"],
                }
            )
            final_profile["automation_review"] = automation_review

        review_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
        )
        review_step = review_result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if review_step is not None:
            metadata = dict(review_step.metadata_ or {})
            metadata["label"] = "人工确认"
            metadata["detail"] = "已按 Luckykiss 含片专项审核人工确认内容摘要"
            metadata["updated_at"] = now.isoformat()
            review_step.metadata_ = metadata
            review_step.status = "done"
            review_step.started_at = review_step.started_at or now
            review_step.finished_at = now
            review_step.error_message = None

        summary = {
            "job_id": str(job.id),
            "source_name": job.source_name,
            "dry_run": bool(args.dry_run),
            "payload": payload,
            "changed_fields": list((manual_review_outcome or {}).get("changed_fields") or []),
            "review_step_status": review_step.status if review_step is not None else "missing",
            "final_subject_brand": str(final_profile.get("subject_brand") or ""),
            "final_subject_model": str(final_profile.get("subject_model") or ""),
            "final_subject_type": str(final_profile.get("subject_type") or ""),
            "final_video_theme": str(final_profile.get("video_theme") or ""),
            "final_summary": str(final_profile.get("summary") or ""),
            "blocking_reasons": list((final_profile.get("automation_review") or {}).get("blocking_reasons") or []),
            "review_reasons": list((final_profile.get("automation_review") or {}).get("review_reasons") or []),
            "memory_cloud": build_content_profile_memory_cloud(user_memory),
        }

        if not args.dry_run:
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=review_step.id if review_step is not None else None,
                    artifact_type="content_profile_final",
                    data_json=final_profile,
                )
            )
            await record_content_profile_feedback_memory(
                session,
                job=job,
                draft_profile=draft_artifact.data_json or {},
                final_profile=final_profile,
                user_feedback=payload,
            )
            job.status = "processing"
            job.updated_at = now
            await session.commit()

        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary


def main() -> None:
    args = parse_args()
    result = asyncio.run(_confirm(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
