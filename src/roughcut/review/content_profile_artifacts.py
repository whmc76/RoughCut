from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roughcut.db.models import Artifact
from roughcut.edit.strategy_review_gates import (
    build_strategy_review_gate_status,
    normalize_strategy_review_gate_confirmations,
    strategy_review_gate_evidence_fingerprint,
)
from roughcut.review.downstream_context import build_downstream_context
from roughcut.review.video_understanding import ARTIFACT_TYPE_VIDEO_UNDERSTANDING

ARTIFACT_TYPE_CONTENT_PROFILE_DRAFT = "content_profile_draft"
ARTIFACT_TYPE_CONTENT_PROFILE_FINAL = "content_profile_final"
ARTIFACT_TYPE_STRATEGY_REVIEW_GATES = "strategy_review_gates"
ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS = "strategy_review_gate_confirmations"
ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW = "strategy_storyboard_review"
ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW = "strategy_timeline_preview"


@dataclass(frozen=True, slots=True)
class ContentProfileArtifactPayloads:
    draft_profile: dict[str, Any]
    final_profile: dict[str, Any] | None
    downstream_context: dict[str, Any]
    subtitle_quality_report: dict[str, Any]
    ocr_profile: dict[str, Any] | None = None
    video_understanding: dict[str, Any] | None = None
    strategy_review_gates: dict[str, Any] | None = None
    strategy_storyboard_review: dict[str, Any] | None = None
    strategy_timeline_preview: dict[str, Any] | None = None


def _profile_capability_orchestration(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = dict(profile or {}) if isinstance(profile, dict) else {}
    orchestration = payload.get("capability_orchestration")
    return dict(orchestration) if isinstance(orchestration, dict) else None


def build_strategy_review_gates_artifact_payload(
    profile: dict[str, Any] | None,
    *,
    confirmations: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    orchestration = _profile_capability_orchestration(profile)
    if not orchestration:
        return None
    pipeline_plan = orchestration.get("pipeline_plan")
    if not isinstance(pipeline_plan, dict):
        return None
    classification = (
        dict(orchestration.get("classification") or {})
        if isinstance(orchestration.get("classification"), dict)
        else {}
    )
    normalized_confirmations = normalize_strategy_review_gate_confirmations(
        confirmations,
        pipeline_plan=pipeline_plan,
        classification=classification,
    )
    gate_status = None if normalized_confirmations else orchestration.get("review_gate_status")
    if not isinstance(gate_status, dict):
        gate_status = build_strategy_review_gate_status(
            pipeline_plan,
            confirmations=normalized_confirmations,
        )
    evidence_fingerprint = strategy_review_gate_evidence_fingerprint(
        pipeline_plan=pipeline_plan,
        classification=classification,
    )
    gate_artifacts: dict[str, dict[str, str]] = {}
    review_gates = {
        str(item or "").strip()
        for item in list(pipeline_plan.get("review_gates") or [])
        if str(item or "").strip()
    }
    if "storyboard_review_required" in review_gates:
        gate_artifacts["storyboard_review"] = {
            "artifact_type": ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
            "status": "available",
        }
    if "timeline_preview_required" in review_gates:
        gate_artifacts["timeline_preview"] = {
            "artifact_type": ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
            "status": "available",
        }
    return {
        "schema": "strategy_review_gates_artifact.v1",
        "artifact_type": ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
        "strategy_type": str(orchestration.get("strategy_type") or pipeline_plan.get("strategy_type") or "").strip(),
        "evidence_fingerprint": evidence_fingerprint,
        "classification": classification,
        "pipeline_plan": dict(pipeline_plan),
        "review_gate_status": dict(gate_status),
        "confirmations": normalized_confirmations,
        "gate_artifacts": gate_artifacts,
    }


def _profile_text(profile: dict[str, Any] | None, *keys: str) -> str:
    payload = profile if isinstance(profile, dict) else {}
    for key in keys:
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    content_understanding = payload.get("content_understanding")
    if isinstance(content_understanding, dict):
        for key in keys:
            text = str(content_understanding.get(key) or "").strip()
            if text:
                return text
    return ""


def _profile_time_spans(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = profile if isinstance(profile, dict) else {}
    candidates: list[Any] = []
    content_understanding = payload.get("content_understanding")
    if isinstance(content_understanding, dict):
        candidates.extend(list(content_understanding.get("timed_focus_spans") or []))
        candidates.extend(list(content_understanding.get("evidence_spans") or []))
    video_understanding = payload.get("video_understanding")
    if isinstance(video_understanding, dict):
        semantic_spans = video_understanding.get("semantic_spans")
        if isinstance(semantic_spans, list):
            candidates.extend(semantic_spans)
    spans: list[dict[str, Any]] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("summary") or item.get("label") or "").strip()
        timestamp = str(item.get("timestamp") or item.get("time_range") or "").strip()
        span_type = str(item.get("type") or item.get("kind") or "evidence").strip() or "evidence"
        if not text and not timestamp:
            continue
        spans.append(
            {
                "index": index,
                "timestamp": timestamp,
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
                "type": span_type,
                "text": text,
            }
        )
    return spans[:8]


def _strategy_review_artifact_source(profile: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any], str]:
    orchestration = _profile_capability_orchestration(profile)
    if not orchestration:
        return None, {}, {}, ""
    pipeline_plan = orchestration.get("pipeline_plan")
    if not isinstance(pipeline_plan, dict):
        return None, {}, {}, ""
    classification = (
        dict(orchestration.get("classification") or {})
        if isinstance(orchestration.get("classification"), dict)
        else {}
    )
    fingerprint = strategy_review_gate_evidence_fingerprint(
        pipeline_plan=pipeline_plan,
        classification=classification,
    )
    return orchestration, dict(pipeline_plan), classification, fingerprint


def build_strategy_storyboard_review_artifact_payload(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    orchestration, pipeline_plan, classification, evidence_fingerprint = _strategy_review_artifact_source(profile)
    if orchestration is None:
        return None
    review_gates = {str(item or "").strip() for item in list(pipeline_plan.get("review_gates") or [])}
    if "storyboard_review_required" not in review_gates:
        return None
    spans = _profile_time_spans(profile)
    theme = _profile_text(profile, "video_theme", "summary") or str(pipeline_plan.get("primary_type") or "storyboard").strip()
    hook = _profile_text(profile, "hook_line")
    panels: list[dict[str, Any]] = []
    if hook:
        panels.append({"panel_id": "opening_hook", "role": "hook", "text": hook, "source": "content_profile"})
    for span in spans[:5]:
        panels.append(
            {
                "panel_id": f"evidence_{span['index']}",
                "role": span["type"],
                "timestamp": span.get("timestamp"),
                "text": span.get("text"),
                "source": "timed_focus_spans",
            }
        )
    if not panels:
        panels = [
            {"panel_id": "opening_hook", "role": "hook", "text": theme, "source": "fallback"},
            {
                "panel_id": "material_assembly",
                "role": "material_insert",
                "text": "Align uploaded supporting material to subtitle or script segments.",
                "source": "pipeline_plan",
            },
            {
                "panel_id": "closing_summary",
                "role": "summary",
                "text": _profile_text(profile, "engagement_question", "summary") or theme,
                "source": "fallback",
            },
        ]
    return {
        "schema": "strategy_storyboard_review_artifact.v1",
        "artifact_type": ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
        "gate_id": "storyboard_review",
        "strategy_type": str(orchestration.get("strategy_type") or pipeline_plan.get("strategy_type") or "").strip(),
        "evidence_fingerprint": evidence_fingerprint,
        "classification": classification,
        "pipeline_plan_summary": {
            "production_mode": pipeline_plan.get("production_mode"),
            "primary_type": pipeline_plan.get("primary_type"),
            "enabled_features": list(pipeline_plan.get("enabled_features") or []),
            "reason_codes": list(pipeline_plan.get("reason_codes") or []),
        },
        "status": "draft_ready",
        "panels": panels,
    }


def build_strategy_timeline_preview_artifact_payload(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    orchestration, pipeline_plan, classification, evidence_fingerprint = _strategy_review_artifact_source(profile)
    if orchestration is None:
        return None
    review_gates = {str(item or "").strip() for item in list(pipeline_plan.get("review_gates") or [])}
    if "timeline_preview_required" not in review_gates:
        return None
    spans = _profile_time_spans(profile)
    segments: list[dict[str, Any]] = []
    for index, span in enumerate(spans[:8]):
        segments.append(
            {
                "segment_id": f"preview_{index + 1}",
                "timestamp": span.get("timestamp"),
                "start_time": span.get("start_time"),
                "end_time": span.get("end_time"),
                "role": span.get("type") or "evidence",
                "text": span.get("text"),
                "checks": ["subtitle_alignment", "material_alignment"],
            }
        )
    if not segments:
        theme = _profile_text(profile, "video_theme", "summary") or str(pipeline_plan.get("primary_type") or "timeline").strip()
        segments = [
            {
                "segment_id": "preview_opening",
                "role": "opening",
                "text": _profile_text(profile, "hook_line") or theme,
                "checks": ["subtitle_alignment"],
            },
            {
                "segment_id": "preview_body",
                "role": "assembly",
                "text": "Review material insert timing against script or subtitle segments.",
                "checks": ["material_alignment", "cut_continuity"],
            },
            {
                "segment_id": "preview_closing",
                "role": "closing",
                "text": _profile_text(profile, "engagement_question", "summary") or theme,
                "checks": ["subtitle_alignment"],
            },
        ]
    return {
        "schema": "strategy_timeline_preview_artifact.v1",
        "artifact_type": ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
        "gate_id": "timeline_preview",
        "strategy_type": str(orchestration.get("strategy_type") or pipeline_plan.get("strategy_type") or "").strip(),
        "evidence_fingerprint": evidence_fingerprint,
        "classification": classification,
        "pipeline_plan_summary": {
            "production_mode": pipeline_plan.get("production_mode"),
            "primary_type": pipeline_plan.get("primary_type"),
            "enabled_features": list(pipeline_plan.get("enabled_features") or []),
            "render_validation_policy": dict(
                ((pipeline_plan.get("strategy_policy") or {}).get("render_validation_policy") or {})
                if isinstance(pipeline_plan.get("strategy_policy"), dict)
                else {}
            ),
        },
        "status": "draft_ready",
        "segments": segments,
    }


def build_content_profile_artifact_payloads(
    *,
    draft_profile: dict[str, Any],
    final_profile: dict[str, Any] | None,
    downstream_profile: dict[str, Any],
    subtitle_quality_report: dict[str, Any],
    ocr_profile: dict[str, Any] | None = None,
    strategy_review_gate_confirmations: dict[str, Any] | None = None,
) -> ContentProfileArtifactPayloads:
    video_understanding = (
        dict(draft_profile.get("video_understanding") or {})
        if isinstance(draft_profile.get("video_understanding"), dict)
        else None
    )
    strategy_review_gates = (
        build_strategy_review_gates_artifact_payload(
            final_profile,
            confirmations=strategy_review_gate_confirmations,
        )
        or build_strategy_review_gates_artifact_payload(
            downstream_profile,
            confirmations=strategy_review_gate_confirmations,
        )
        or build_strategy_review_gates_artifact_payload(
            draft_profile,
            confirmations=strategy_review_gate_confirmations,
        )
    )
    strategy_storyboard_review = (
        build_strategy_storyboard_review_artifact_payload(final_profile)
        or build_strategy_storyboard_review_artifact_payload(downstream_profile)
        or build_strategy_storyboard_review_artifact_payload(draft_profile)
    )
    strategy_timeline_preview = (
        build_strategy_timeline_preview_artifact_payload(final_profile)
        or build_strategy_timeline_preview_artifact_payload(downstream_profile)
        or build_strategy_timeline_preview_artifact_payload(draft_profile)
    )
    return ContentProfileArtifactPayloads(
        draft_profile=dict(draft_profile),
        final_profile=dict(final_profile) if final_profile is not None else None,
        downstream_context=build_downstream_context(
            downstream_profile,
            strategy_review_gates=strategy_review_gates,
            strategy_storyboard_review=strategy_storyboard_review,
            strategy_timeline_preview=strategy_timeline_preview,
        ),
        subtitle_quality_report=dict(subtitle_quality_report),
        ocr_profile=dict(ocr_profile) if ocr_profile is not None else None,
        video_understanding=video_understanding,
        strategy_review_gates=strategy_review_gates,
        strategy_storyboard_review=strategy_storyboard_review,
        strategy_timeline_preview=strategy_timeline_preview,
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
    strategy_review_gate_confirmations: dict[str, Any] | None = None,
) -> None:
    payloads = build_content_profile_artifact_payloads(
        draft_profile=draft_profile,
        final_profile=final_profile,
        downstream_profile=downstream_profile,
        subtitle_quality_report=subtitle_quality_report,
        ocr_profile=ocr_profile,
        strategy_review_gate_confirmations=strategy_review_gate_confirmations,
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
    if payloads.video_understanding is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_VIDEO_UNDERSTANDING,
                data_json=payloads.video_understanding,
            )
        )
    if payloads.strategy_review_gates is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
                data_json=payloads.strategy_review_gates,
            )
        )
    if payloads.strategy_storyboard_review is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
                data_json=payloads.strategy_storyboard_review,
            )
        )
    if payloads.strategy_timeline_preview is not None:
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
                data_json=payloads.strategy_timeline_preview,
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
