from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("TELEGRAM_REMOTE_REVIEW_ENABLED", "false")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from scripts.build_batch_output_scorecard import build_scorecard, render_markdown as render_scorecard_markdown
from scripts.build_job_audit_pack import build_markdown as build_audit_markdown
from scripts.export_job_audit_snapshot import DEFAULT_KEYWORDS, export_snapshot
from roughcut.api.jobs import (
    _build_manual_editor_readiness,
    _manual_editor_base_keep_segment_dicts,
    _build_manual_editor_session,
    _load_latest_timeline_by_type,
    _load_latest_optional_artifact,
    _manual_editor_apply_frontend_managed_auto_cuts,
    _manual_editor_change_plan,
    _manual_editor_deleted_ranges_from_keep_segments,
    _manual_editor_frontend_managed_auto_cut_ranges,
    _manual_editor_restore_frontend_managed_auto_cuts,
    _manual_keep_segments_from_editorial_payload,
    _manual_video_transform_from_render_plan,
)
from roughcut.db.models import Artifact, Job, JobStep, SubtitleItem, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.edit.cut_analysis import cut_analysis_accepted_cuts, cut_analysis_effective_applied_cuts, cut_analysis_rule_candidates
from roughcut.edit.manual_editor_contract import (
    manual_editor_change_contract,
    manual_editor_change_contract_is_consistent,
    manual_editor_is_subtitle_only_render,
    manual_editor_rerun_plan,
)
from roughcut.edit.refine_decisions import resolve_refine_keep_segments_for_timeline
from roughcut.media.variant_timeline_bundle import variant_high_risk_cuts
from roughcut.pipeline.live_readiness import build_live_readiness_summary
from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.review.content_profile import extract_source_identity_constraints
from roughcut.watcher.folder_watcher import create_jobs_for_inventory_paths
from scripts.run_fullchain_batch import (
    JobRunReport,
    _classify_avatar_runtime_reason_category,
    _configure_local_event_loop_policy,
    build_console_summary,
    ensure_batch_runtime_ready,
    load_previous_batch_summaries,
    render_markdown,
    run_job,
)


@dataclass(slots=True)
class GoldenJobCase:
    case_id: str
    scenario: str
    source_name: str = ""
    source_path: str = ""
    reference_job_id: str = ""
    reference_risk_job_id: str = ""
    workflow_template: str = ""
    language: str = ""
    enhancement_modes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    required_checks: list[str] = field(default_factory=list)
    notes: str = ""
    risk_hints: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PreparedGoldenJob:
    case: GoldenJobCase
    job_id: str
    mode: str
    item: dict[str, Any]


SUPPORTED_REQUIRED_CHECKS = frozenset(
    {
        "cut_analysis_traceability",
        "low_signal_traceability",
        "manual_editor_apply_semantics",
        "manual_editor_ready",
        "model_token_integrity",
        "subtitle_projection",
        "term_format_consistency",
    }
)


def _segment_dicts(segments: list[Any]) -> list[dict[str, float]]:
    normalized: list[dict[str, float]] = []
    for segment in segments:
        if hasattr(segment, "model_dump"):
            payload = segment.model_dump(include={"start", "end"})
        elif isinstance(segment, dict):
            payload = segment
        else:
            continue
        try:
            start = round(float(payload.get("start", 0.0) or 0.0), 3)
            end = round(float(payload.get("end", start) or start), 3)
        except (AttributeError, TypeError, ValueError):
            continue
        normalized.append({"start": start, "end": end})
    return normalized


def _same_segments(left: list[dict[str, float]], right: list[dict[str, float]]) -> bool:
    return _segment_dicts(left) == _segment_dicts(right)


def _manual_editor_apply_semantics_payload(
    change_plan: dict[str, Any] | None,
    *,
    session_baseline_matches_restored: bool,
    roundtrip_matches_editorial: bool,
) -> dict[str, Any]:
    change_contract = manual_editor_change_contract(change_plan)
    rerun_plan = manual_editor_rerun_plan(change_contract)
    return {
        "change_scope": str(change_contract.get("change_scope") or ""),
        "timeline_changed": bool(change_contract.get("timeline_changed")),
        "subtitle_changed": bool(change_contract.get("subtitle_changed")),
        "render_strategy": str(change_contract.get("render_strategy") or ""),
        "rerun_start_step": str(rerun_plan.get("rerun_start_step") or ""),
        "rerun_steps": list(rerun_plan.get("rerun_steps") or []),
        "ok": (
            session_baseline_matches_restored
            and roundtrip_matches_editorial
            and manual_editor_change_contract_is_consistent(change_contract)
        ),
    }


def _previous_effective_keep_segments(
    *,
    editorial_timeline_payload: dict[str, Any] | None,
    refine_plan_payload: dict[str, Any] | None,
    editorial_timeline_id: str,
    editorial_timeline_version: int,
) -> list[dict[str, float]]:
    editorial_segments = list((editorial_timeline_payload or {}).get("segments") or [])
    resolved = resolve_refine_keep_segments_for_timeline(
        refine_plan_payload,
        editorial_timeline_id=editorial_timeline_id,
        editorial_timeline_version=editorial_timeline_version,
        fallback_segments=editorial_segments,
    )
    return _segment_dicts(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the auto-edit recovery golden job set from a rich manifest of real jobs."
    )
    parser.add_argument("--manifest", type=Path, required=True, help="Golden job manifest JSON.")
    parser.add_argument(
        "--case-id",
        dest="case_ids",
        action="append",
        default=[],
        help="Optional case_id filter. Repeat to run multiple explicit cases.",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Optional tag filter. Repeat to keep cases matching any selected tag.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "output" / "test" / "auto-edit-recovery-golden",
        help="Parent report directory. A timestamped subdirectory will be created.",
    )
    parser.add_argument(
        "--locate-root",
        action="append",
        default=[],
        help="Optional roots used to locate source files when manifest does not include source_path.",
    )
    parser.add_argument(
        "--workflow-template",
        default="edc_tactical",
        help="Default workflow template when a manifest case does not override it.",
    )
    parser.add_argument(
        "--language",
        default="zh-CN",
        help="Default language when a manifest case does not override it.",
    )
    parser.add_argument(
        "--stop-after",
        default=None,
        help="Optional pipeline stop step, passed through to the golden run.",
    )
    parser.add_argument(
        "--audit-threshold",
        type=float,
        default=75.0,
        help="Quality score threshold below which a job gets an audit pack.",
    )
    parser.add_argument(
        "--previous-batch-report",
        dest="previous_batch_reports",
        action="append",
        default=[],
        help="Repeatable prior batch_report.json path used for live readiness comparison.",
    )
    return parser.parse_args()


def _normalize_string_list(values: Any) -> list[str]:
    normalized: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_risk_hints(value: Any) -> dict[str, Any]:
    raw_hints = value if isinstance(value, dict) else {}
    normalized: dict[str, Any] = {}
    for key, raw_value in raw_hints.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        if isinstance(raw_value, dict):
            child: dict[str, Any] = {}
            for child_key, child_value in raw_value.items():
                normalized_child_key = str(child_key or "").strip()
                if not normalized_child_key:
                    continue
                child[normalized_child_key] = child_value
            normalized[normalized_key] = child
            continue
        if isinstance(raw_value, list):
            normalized[normalized_key] = [
                item
                for item in raw_value
                if isinstance(item, (str, int, float, bool)) or item is None
            ]
            continue
        normalized[normalized_key] = raw_value
    return normalized


def load_golden_job_manifest(path: Path) -> list[GoldenJobCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_cases = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(raw_cases, list):
        raise ValueError("golden job manifest must be a JSON array or an object with a jobs array")

    cases: list[GoldenJobCase] = []
    seen_case_ids: set[str] = set()
    seen_reference_jobs: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValueError(f"golden job case #{index + 1} must be an object")
        case_id = str(raw_case.get("case_id") or raw_case.get("id") or f"case_{index + 1}").strip()
        if not case_id:
            raise ValueError(f"golden job case #{index + 1} is missing case_id")
        if case_id in seen_case_ids:
            raise ValueError(f"duplicate golden job case_id: {case_id}")
        seen_case_ids.add(case_id)

        case = GoldenJobCase(
            case_id=case_id,
            scenario=str(raw_case.get("scenario") or raw_case.get("name") or "").strip(),
            source_name=str(raw_case.get("source_name") or "").strip(),
            source_path=str(raw_case.get("source_path") or "").strip(),
            reference_job_id=str(raw_case.get("reference_job_id") or raw_case.get("job_id") or "").strip(),
            reference_risk_job_id=str(raw_case.get("reference_risk_job_id") or "").strip(),
            workflow_template=str(raw_case.get("workflow_template") or "").strip(),
            language=str(raw_case.get("language") or "").strip(),
            enhancement_modes=_normalize_string_list(raw_case.get("enhancement_modes")),
            tags=_normalize_string_list(raw_case.get("tags")),
            required_checks=_normalize_string_list(raw_case.get("required_checks")),
            notes=str(raw_case.get("notes") or "").strip(),
            risk_hints=_normalize_risk_hints(raw_case.get("risk_hints")),
        )
        unknown_required_checks = [
            check
            for check in case.required_checks
            if check not in SUPPORTED_REQUIRED_CHECKS
        ]
        if unknown_required_checks:
            raise ValueError(
                f"golden job case {case.case_id} has unsupported required_checks: {', '.join(unknown_required_checks)}"
            )
        if not (case.reference_job_id or case.source_name or case.source_path):
            raise ValueError(f"golden job case {case.case_id} must provide reference_job_id, source_name, or source_path")
        if case.reference_job_id:
            if case.reference_job_id in seen_reference_jobs:
                raise ValueError(f"duplicate reference_job_id in golden manifest: {case.reference_job_id}")
            seen_reference_jobs.add(case.reference_job_id)
        cases.append(case)
    return cases


def select_golden_job_cases(
    cases: list[GoldenJobCase],
    *,
    case_ids: list[str] | None = None,
    tags: list[str] | None = None,
) -> list[GoldenJobCase]:
    normalized_case_ids = [str(value or "").strip() for value in list(case_ids or []) if str(value or "").strip()]
    normalized_tags = {str(value or "").strip().lower() for value in list(tags or []) if str(value or "").strip()}
    if normalized_case_ids:
        known_case_ids = {case.case_id for case in cases}
        missing_case_ids = [case_id for case_id in normalized_case_ids if case_id not in known_case_ids]
        if missing_case_ids:
            raise ValueError(f"unknown golden case_id filter(s): {', '.join(missing_case_ids)}")

    selected: list[GoldenJobCase] = []
    for case in cases:
        if normalized_case_ids and case.case_id not in normalized_case_ids:
            continue
        if normalized_tags and not ({tag.lower() for tag in case.tags} & normalized_tags):
            continue
        selected.append(case)
    if not selected:
        raise ValueError("golden case filters matched no cases")
    return selected


def _slugify(value: str) -> str:
    safe = [
        char.lower() if char.isalnum() else "-"
        for char in str(value or "").strip()
    ]
    slug = "".join(safe).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "case"


def _resolve_source_candidate(case: GoldenJobCase, locate_roots: list[str]) -> Path | None:
    if case.source_path:
        path = Path(case.source_path).expanduser()
        return path if path.exists() else None
    if not case.source_name:
        return None
    for raw_root in locate_roots:
        root = Path(raw_root).expanduser()
        if not root.exists():
            continue
        try:
            candidates = list(root.rglob(case.source_name))
        except OSError:
            continue
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


async def _clone_evaluation_job_from_existing(
    session,
    *,
    source_job: Job,
    workflow_template: str,
    language: str,
    enhancement_modes: list[str],
) -> tuple[uuid.UUID, str]:
    transcript_rows = (
        await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == source_job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
    ).scalars().all()
    subtitle_rows = (
        await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == source_job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
    ).scalars().all()
    media_meta_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "media_meta")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()
    audio_artifact = (
        await session.execute(
            select(Artifact)
            .where(Artifact.job_id == source_job.id, Artifact.artifact_type == "audio_wav")
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
    ).scalars().first()

    job_id = uuid.uuid4()
    cloned_job = Job(
        id=job_id,
        source_path=source_job.source_path,
        source_name=source_job.source_name,
        file_hash=source_job.file_hash,
        status="pending",
        error_message=None,
        workflow_template=workflow_template or source_job.workflow_template,
        output_dir=source_job.output_dir,
        config_profile_id=source_job.config_profile_id,
        config_profile_snapshot_json=dict(source_job.config_profile_snapshot_json or {}) or None,
        packaging_snapshot_json=dict(source_job.packaging_snapshot_json or {}) or None,
        language=language or source_job.language,
        workflow_mode=source_job.workflow_mode,
        enhancement_modes=enhancement_modes or list(source_job.enhancement_modes or []),
    )
    session.add(cloned_job)
    step_map: dict[str, JobStep] = {}
    now = datetime.now(timezone.utc)
    for step in create_job_steps(job_id):
        if step.step_name in {"probe", "extract_audio", "transcribe", "subtitle_postprocess"} and (
            media_meta_artifact is not None or transcript_rows or subtitle_rows or audio_artifact is not None
        ):
            step.status = "done"
            step.started_at = now
            step.finished_at = now
            step.metadata_ = {
                "detail": f"cloned_from:{source_job.id}",
                "progress": 1.0,
                "label": step.step_name,
                "updated_at": now.isoformat(),
            }
        session.add(step)
        step_map[step.step_name] = step

    if media_meta_artifact is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map.get("probe").id if step_map.get("probe") else None,
                artifact_type="media_meta",
                storage_path=media_meta_artifact.storage_path,
                data_json=dict(media_meta_artifact.data_json or {}) or None,
            )
        )
    if audio_artifact is not None:
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step_map.get("extract_audio").id if step_map.get("extract_audio") else None,
                artifact_type="audio_wav",
                storage_path=audio_artifact.storage_path,
                data_json=dict(audio_artifact.data_json or {}) or None,
            )
        )
    for row in transcript_rows:
        session.add(
            TranscriptSegment(
                job_id=job_id,
                version=row.version,
                segment_index=row.segment_index,
                start_time=row.start_time,
                end_time=row.end_time,
                speaker=row.speaker,
                text=row.text,
                words_json=list(row.words_json or []),
            )
        )
    for row in subtitle_rows:
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=row.version,
                item_index=row.item_index,
                start_time=row.start_time,
                end_time=row.end_time,
                text_raw=row.text_raw,
                text_norm=row.text_norm,
                text_final=row.text_final,
            )
        )

    rerun_mode = "cloned_profile_only" if transcript_rows and subtitle_rows else "cloned_full_chain"
    return job_id, rerun_mode


async def prepare_golden_job(
    case: GoldenJobCase,
    *,
    default_workflow_template: str,
    default_language: str,
    locate_roots: list[str],
) -> PreparedGoldenJob:
    workflow_template = case.workflow_template or default_workflow_template
    language = case.language or default_language
    enhancement_modes = list(case.enhancement_modes or [])
    factory = get_session_factory()
    async with factory() as session:
        source_job: Job | None = None
        mode = ""
        if case.reference_job_id:
            source_job = await session.get(Job, uuid.UUID(case.reference_job_id))
            if source_job is None:
                raise RuntimeError(f"reference_job_id not found: {case.reference_job_id}")
        elif case.source_name:
            source_job = (
                await session.execute(
                    select(Job)
                    .where(Job.source_name == case.source_name)
                    .order_by(Job.created_at.desc(), Job.id.desc())
                )
            ).scalars().first()
        if source_job is not None:
            cloned_job_id, mode = await _clone_evaluation_job_from_existing(
                session,
                source_job=source_job,
                workflow_template=workflow_template,
                language=language,
                enhancement_modes=enhancement_modes,
            )
            await session.commit()
            return PreparedGoldenJob(
                case=case,
                job_id=str(cloned_job_id),
                mode=mode,
                item={
                    "path": str(source_job.source_path or case.source_path or ""),
                    "source_name": str(source_job.source_name or case.source_name or source_job.id),
                },
            )

    source_candidate = _resolve_source_candidate(case, locate_roots)
    if source_candidate is None:
        raise RuntimeError(
            f"golden case {case.case_id} could not resolve a source file from source_path/source_name/locate_root"
        )
    created = await create_jobs_for_inventory_paths(
        [str(source_candidate)],
        workflow_template=workflow_template,
        language=language,
    )
    job_id = str(created[0].get("job_id") or "").strip()
    if not job_id:
        raise RuntimeError(f"failed to create job for golden case {case.case_id}")
    return PreparedGoldenJob(
        case=case,
        job_id=job_id,
        mode="fresh_full_chain",
        item={"path": str(source_candidate), "source_name": source_candidate.name},
    )


def job_requires_audit(report: JobRunReport, *, audit_threshold: float) -> bool:
    if str(report.status or "").strip().lower() != "done":
        return True
    if report.quality_score is None or float(report.quality_score) < float(audit_threshold):
        return True
    return any(str(item.status or "").strip().lower() != "pass" for item in list(report.live_stage_validations or []))


async def inspect_manual_editor_apply_semantics(
    case: GoldenJobCase,
    *,
    job_id: str = "",
    source_name: str = "",
) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        job: Job | None = None
        normalized_job_id = str(job_id or "").strip()
        normalized_source_name = str(source_name or "").strip()
        if normalized_job_id:
            job = (
                await session.execute(
                    select(Job)
                    .options(selectinload(Job.steps))
                    .where(Job.id == uuid.UUID(normalized_job_id))
                )
            ).scalar_one_or_none()
        elif case.reference_job_id:
            job = (
                await session.execute(
                    select(Job)
                    .options(selectinload(Job.steps))
                    .where(Job.id == uuid.UUID(case.reference_job_id))
                )
            ).scalar_one_or_none()
        elif normalized_source_name:
            job = (
                await session.execute(
                    select(Job)
                    .options(selectinload(Job.steps))
                    .where(Job.source_name == normalized_source_name)
                    .order_by(Job.created_at.desc(), Job.id.desc())
                )
            ).scalars().first()
        elif case.source_name:
            job = (
                await session.execute(
                    select(Job)
                    .options(selectinload(Job.steps))
                    .where(Job.source_name == case.source_name)
                    .order_by(Job.created_at.desc(), Job.id.desc())
                )
            ).scalars().first()
        if job is None:
            raise RuntimeError(f"could not resolve job for case {case.case_id}")

        editorial_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="editorial")
        render_plan_timeline = await _load_latest_timeline_by_type(session, job_id=job.id, timeline_type="render_plan")
        refine_decision_plan_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("refine_decision_plan",),
        )
        if editorial_timeline is None or render_plan_timeline is None:
            raise RuntimeError(f"case {case.case_id} is missing editorial/render_plan timelines")

        session_payload = await _build_manual_editor_session(job=job, session=session)
        source_duration_sec = float(session_payload.source_duration_sec or 0.0)
        cut_analysis = session_payload.cut_analysis if isinstance(session_payload.cut_analysis, dict) else {}
        previous_effective_keep_segments = _manual_editor_base_keep_segment_dicts(
            editorial_timeline.data_json if isinstance(editorial_timeline.data_json, dict) else {},
            refine_plan_payload=(
                refine_decision_plan_artifact.data_json
                if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
                else None
            ),
            editorial_timeline_id=str(editorial_timeline.id),
            editorial_timeline_version=int(editorial_timeline.version or 1),
            source_duration_sec=source_duration_sec,
            prefer_refine_plan=True,
        )
        restored_keep_segments = _manual_editor_restore_frontend_managed_auto_cuts(
            previous_effective_keep_segments,
            analysis_payload=cut_analysis,
            source_duration_sec=source_duration_sec,
        )
        requested_keep_segments = _segment_dicts(list(session_payload.base_keep_segments or []))
        effective_keep_segments = _manual_editor_apply_frontend_managed_auto_cuts(
            requested_keep_segments,
            analysis_payload=cut_analysis,
            source_duration_sec=source_duration_sec,
            current_keep_segments=previous_effective_keep_segments,
        )
        previous_video_transform = _manual_video_transform_from_render_plan(
            render_plan_timeline.data_json if isinstance(render_plan_timeline.data_json, dict) else {}
        )
        projected_subtitles = list(session_payload.projected_subtitles or [])
        if projected_subtitles:
            first = projected_subtitles[0]
            sample_text = str(
                getattr(first, "text_final", None)
                or getattr(first, "text_norm", None)
                or getattr(first, "text_raw", None)
                or ""
            ).strip()
            sample_override = [{"index": int(getattr(first, "index", 0) or 0), "text_final": sample_text or "字幕验证"}]
        else:
            sample_override = [{"index": 0, "text_final": "字幕验证"}]
        change_plan = _manual_editor_change_plan(
            previous_keep_segments=restored_keep_segments,
            next_keep_segments=requested_keep_segments,
            subtitle_overrides=sample_override,
            previous_video_transform=previous_video_transform,
            next_video_transform=previous_video_transform,
        )
        managed_auto_cut_ranges = _manual_editor_frontend_managed_auto_cut_ranges(
            cut_analysis,
            current_deleted_ranges=_manual_editor_deleted_ranges_from_keep_segments(
                previous_effective_keep_segments,
                source_duration_sec=source_duration_sec,
            ),
        )
        session_baseline_matches_restored = _same_segments(requested_keep_segments, restored_keep_segments)
        roundtrip_matches_editorial = _same_segments(effective_keep_segments, previous_effective_keep_segments)
        semantics_payload = _manual_editor_apply_semantics_payload(
            change_plan,
            session_baseline_matches_restored=session_baseline_matches_restored,
            roundtrip_matches_editorial=roundtrip_matches_editorial,
        )
        return {
            "case_id": case.case_id,
            "source_name": str(job.source_name or ""),
            "job_id": str(job.id),
            "managed_auto_cut_count": len(managed_auto_cut_ranges),
            "raw_keep_segment_count": len(previous_effective_keep_segments),
            "restored_keep_segment_count": len(restored_keep_segments),
            "requested_keep_segment_count": len(requested_keep_segments),
            "effective_keep_segment_count": len(effective_keep_segments),
            "session_baseline_matches_restored": session_baseline_matches_restored,
            "roundtrip_matches_editorial": roundtrip_matches_editorial,
            "restored_differs_from_editorial": not _same_segments(restored_keep_segments, previous_effective_keep_segments),
            **semantics_payload,
        }


async def collect_manual_editor_apply_semantics(
    cases: list[GoldenJobCase],
    prepared_jobs: list[PreparedGoldenJob] | None = None,
) -> dict[str, dict[str, Any]]:
    prepared_by_case = {
        item.case.case_id: item
        for item in list(prepared_jobs or [])
        if isinstance(item, PreparedGoldenJob)
    }
    results: dict[str, dict[str, Any]] = {}
    for case in cases:
        prepared = prepared_by_case.get(case.case_id)
        prepared_source_name = prepared.item.get("source_name") if prepared and isinstance(prepared.item, dict) else ""
        try:
            results[case.case_id] = await inspect_manual_editor_apply_semantics(
                case,
                job_id=prepared.job_id if prepared else "",
                source_name=str(prepared_source_name or case.source_name or "").strip(),
            )
        except Exception as exc:
            results[case.case_id] = {
                "case_id": case.case_id,
                "source_name": str(prepared_source_name or case.source_name or "").strip(),
                "job_id": prepared.job_id if prepared else case.reference_job_id,
                "managed_auto_cut_count": 0,
                "ok": False,
                "error": str(exc),
            }
    return results


async def inspect_reference_risk_snapshot(case: GoldenJobCase) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        job: Job | None = None
        reference_risk_job_id = str(case.reference_risk_job_id or case.reference_job_id or "").strip()
        if reference_risk_job_id:
            job = await session.get(Job, uuid.UUID(reference_risk_job_id))
        elif case.source_name:
            job = (
                await session.execute(
                    select(Job)
                    .where(Job.source_name == case.source_name)
                    .order_by(Job.created_at.desc(), Job.id.desc())
                )
            ).scalars().first()
        if job is None:
            raise RuntimeError(f"could not resolve job for case {case.case_id}")

        artifact_rows = (
            await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job.id,
                    Artifact.artifact_type.in_(
                        [
                            "variant_timeline_bundle",
                            "render_outputs",
                            "cut_analysis",
                            "multimodal_trim_review",
                            "refine_decision_plan",
                            "editorial",
                        ]
                    ),
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().all()
        latest_by_type: dict[str, Artifact] = {}
        for row in artifact_rows:
            latest_by_type.setdefault(str(row.artifact_type or "").strip(), row)

        return _build_job_risk_snapshot_from_artifacts(
            case_id=case.case_id,
            job=job,
            latest_by_type=latest_by_type,
        )


def _build_job_risk_snapshot_from_artifacts(
    *,
    case_id: str,
    job: Job,
    latest_by_type: dict[str, Artifact],
) -> dict[str, Any]:
    variant_bundle = latest_by_type.get("variant_timeline_bundle")
    bundle_payload = dict(variant_bundle.data_json or {}) if variant_bundle and isinstance(variant_bundle.data_json, dict) else {}
    diagnostics = (((bundle_payload.get("timeline_rules") or {}).get("diagnostics")) or {}) if bundle_payload else {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}

    cut_analysis_artifact = latest_by_type.get("cut_analysis")
    cut_analysis_payload = (
        dict(cut_analysis_artifact.data_json or {})
        if cut_analysis_artifact and isinstance(cut_analysis_artifact.data_json, dict)
        else {}
    )
    refine_artifact = latest_by_type.get("refine_decision_plan")
    refine_payload = (
        dict(refine_artifact.data_json or {})
        if refine_artifact and isinstance(refine_artifact.data_json, dict)
        else {}
    )
    multimodal_artifact = latest_by_type.get("multimodal_trim_review")
    multimodal_payload = (
        dict(multimodal_artifact.data_json or {})
        if multimodal_artifact and isinstance(multimodal_artifact.data_json, dict)
        else {}
    )
    editorial_artifact = latest_by_type.get("editorial")
    editorial_payload = (
        dict(editorial_artifact.data_json or {})
        if editorial_artifact and isinstance(editorial_artifact.data_json, dict)
        else {}
    )

    cut_analysis_summary = dict(diagnostics.get("cut_analysis_summary") or {})
    refine_decision_summary = dict(diagnostics.get("refine_decision_summary") or {})
    multimodal_trim_review_summary = dict(diagnostics.get("multimodal_trim_review_summary") or {})
    llm_cut_review = dict(diagnostics.get("llm_cut_review") or {})
    review_flags = dict(diagnostics.get("review_flags") or {})
    high_risk_cuts = [
        dict(item)
        for item in list(diagnostics.get("high_risk_cuts") or [])
        if isinstance(item, dict)
    ]
    if not cut_analysis_summary and cut_analysis_payload:
        cut_analysis_summary = {
            "candidate_count": int(cut_analysis_payload.get("candidate_count") or 0),
            "accepted_cut_count": int(cut_analysis_payload.get("accepted_cut_count") or 0),
            "rule_candidate_count": int(cut_analysis_payload.get("rule_candidate_count") or 0),
            "auto_apply_candidate_count": int(cut_analysis_payload.get("auto_apply_candidate_count") or 0),
            "manual_confirm_candidate_count": int(cut_analysis_payload.get("manual_confirm_candidate_count") or 0),
            "candidate_risk_summary": dict(cut_analysis_payload.get("candidate_risk_summary") or {}),
        }
    if not refine_decision_summary and refine_payload:
        candidate_summary = (
            refine_payload.get("candidate_summary")
            if isinstance(refine_payload.get("candidate_summary"), dict)
            else {}
        )
        refine_decision_summary = {
            "candidate_total": int(candidate_summary.get("total") or 0),
            "candidate_auto_apply": int(candidate_summary.get("auto_apply") or 0),
            "candidate_manual_confirm": int(candidate_summary.get("manual_confirm") or 0),
            "rule_auto_apply_cut_count": int(
                refine_payload.get("rule_auto_apply_cut_count")
                or candidate_summary.get("rule_auto_apply")
                or 0
            ),
            "multimodal_auto_apply_cut_count": int(candidate_summary.get("multimodal_auto_apply") or 0),
            "risk_levels": dict(candidate_summary.get("risk_levels") or {}),
        }
    if not multimodal_trim_review_summary and multimodal_payload:
        multimodal_trim_review_summary = dict(multimodal_payload.get("summary") or {})
    if not llm_cut_review and editorial_payload:
        analysis_payload = editorial_payload.get("analysis") if isinstance(editorial_payload.get("analysis"), dict) else {}
        llm_cut_review = dict(analysis_payload.get("llm_cut_review") or {})
    return {
        "case_id": str(case_id or "").strip(),
        "job_id": str(job.id),
        "source_name": str(job.source_name or ""),
        "artifact_types": sorted(latest_by_type.keys()),
        "variant_bundle_present": bool(variant_bundle),
        "has_render_outputs": "render_outputs" in latest_by_type,
        "has_cut_analysis": "cut_analysis" in latest_by_type,
        "high_risk_cut_count": len(high_risk_cuts),
        "auto_apply_candidate_count": int(cut_analysis_summary.get("auto_apply_candidate_count") or 0),
        "manual_confirm_candidate_count": int(cut_analysis_summary.get("manual_confirm_candidate_count") or 0),
        "candidate_risk_summary": dict(cut_analysis_summary.get("candidate_risk_summary") or {}),
        "refine_candidate_manual_confirm": int(refine_decision_summary.get("candidate_manual_confirm") or 0),
        "rule_auto_apply_cut_count": int(refine_decision_summary.get("rule_auto_apply_cut_count") or 0),
        "multimodal_auto_apply_cut_count": int(refine_decision_summary.get("multimodal_auto_apply_cut_count") or 0),
        "risk_levels": dict(refine_decision_summary.get("risk_levels") or {}),
        "multimodal_pending_count": int(multimodal_trim_review_summary.get("pending_count") or 0),
        "llm_reviewed": bool(llm_cut_review.get("reviewed")),
        "llm_candidate_count": int(llm_cut_review.get("candidate_count") or 0),
        "llm_error": str(llm_cut_review.get("error") or "").strip() or None,
        "review_recommended": bool(review_flags.get("review_recommended")),
        "review_reasons": [str(item) for item in list(review_flags.get("review_reasons") or []) if str(item).strip()],
        "first_high_risk_cut_reason": (
            str(((high_risk_cuts[0] if high_risk_cuts else {}).get("reason")) or "").strip() or None
        ),
    }


async def collect_reference_risk_snapshots(cases: list[GoldenJobCase]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for case in cases:
        try:
            results[case.case_id] = await inspect_reference_risk_snapshot(case)
        except Exception as exc:
            results[case.case_id] = {
                "case_id": case.case_id,
                "job_id": str(case.reference_risk_job_id or case.reference_job_id or "").strip(),
                "source_name": case.source_name,
                "variant_bundle_present": False,
                "has_render_outputs": False,
                "has_cut_analysis": False,
                "high_risk_cut_count": 0,
                "llm_reviewed": False,
                "review_recommended": False,
                "artifact_types": [],
                "error": str(exc),
            }
    return results


async def inspect_evaluation_risk_snapshot(prepared_job: PreparedGoldenJob) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(prepared_job.job_id))
        if job is None:
            raise RuntimeError(f"could not resolve evaluation job for case {prepared_job.case.case_id}")

        artifact_rows = (
            await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job.id,
                    Artifact.artifact_type.in_(
                        [
                            "variant_timeline_bundle",
                            "render_outputs",
                            "cut_analysis",
                            "multimodal_trim_review",
                            "refine_decision_plan",
                            "editorial",
                        ]
                    ),
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().all()
        latest_by_type: dict[str, Artifact] = {}
        for row in artifact_rows:
            latest_by_type.setdefault(str(row.artifact_type or "").strip(), row)

        return _build_job_risk_snapshot_from_artifacts(
            case_id=prepared_job.case.case_id,
            job=job,
            latest_by_type=latest_by_type,
        )


async def collect_evaluation_risk_snapshots(prepared_jobs: list[PreparedGoldenJob]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for prepared_job in prepared_jobs:
        case_id = prepared_job.case.case_id
        try:
            results[case_id] = await inspect_evaluation_risk_snapshot(prepared_job)
        except Exception as exc:
            results[case_id] = {
                "case_id": case_id,
                "job_id": prepared_job.job_id,
                "source_name": str((prepared_job.item or {}).get("source_name") or prepared_job.case.source_name or ""),
                "variant_bundle_present": False,
                "has_render_outputs": False,
                "has_cut_analysis": False,
                "high_risk_cut_count": 0,
                "llm_reviewed": False,
                "review_recommended": False,
                "artifact_types": [],
                "error": str(exc),
            }
    return results


def _evaluate_required_checks(
    case: GoldenJobCase,
    report: JobRunReport | None,
    *,
    manual_editor_apply_semantics: dict[str, Any] | None = None,
    check_statuses: dict[str, dict[str, Any]] | None = None,
) -> tuple[bool, list[str]]:
    status_by_stage = {
        str(item.stage).strip().lower(): str(item.status).strip().lower()
        for item in list(report.live_stage_validations or [])
    } if report else {}
    normalized_check_statuses = {
        str(name or "").strip().lower(): dict(payload or {})
        for name, payload in dict(check_statuses or {}).items()
        if str(name or "").strip() and isinstance(payload, dict)
    }
    failed_required_checks: list[str] = []
    for raw_check in list(case.required_checks or []):
        normalized_check = str(raw_check or "").strip()
        if not normalized_check:
            continue
        if normalized_check.lower() == "manual_editor_apply_semantics":
            if not bool((manual_editor_apply_semantics or {}).get("ok")):
                failed_required_checks.append(normalized_check)
            continue
        status_payload = normalized_check_statuses.get(normalized_check.lower())
        if status_payload is not None:
            if not bool(status_payload.get("passed")):
                failed_required_checks.append(normalized_check)
            continue
        if status_by_stage.get(normalized_check.lower()) != "pass":
            failed_required_checks.append(normalized_check)
    if not case.required_checks:
        return True, []
    if report is None:
        unresolved_checks = [
            str(item).strip()
            for item in case.required_checks
            if str(item).strip()
            and str(item).strip().lower() != "manual_editor_apply_semantics"
            and str(item).strip().lower() not in normalized_check_statuses
        ]
        failed_required_checks = list(dict.fromkeys([*failed_required_checks, *unresolved_checks]))
    return not failed_required_checks, failed_required_checks


def _traceable_cut_candidate(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return False
    if not str(item.get("reason") or "").strip():
        return False
    if not str(item.get("rule_id") or item.get("candidate_id") or item.get("id") or "").strip():
        return False
    if not str(item.get("risk_level") or "").strip():
        return False
    if not str(item.get("match_surface_layer") or "").strip():
        return False
    has_surface = bool(str(item.get("match_surface") or "").strip() or str(item.get("source_text") or "").strip())
    has_structured_evidence = bool(list(item.get("signals") or [])) or isinstance(item.get("evidence"), dict)
    if not has_surface and not has_structured_evidence:
        return False
    return True


def _model_token_integrity_status(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    quality_issue_codes: set[str],
) -> dict[str, Any]:
    profile = dict(content_profile or {}) if isinstance(content_profile, dict) else {}
    constraints = extract_source_identity_constraints(profile, source_name=source_name)
    expected_brand = str(constraints.get("subject_brand") or "").strip()
    expected_model = str(constraints.get("subject_model") or "").strip()
    actual_brand = str(profile.get("subject_brand") or "").strip()
    actual_model = str(profile.get("subject_model") or "").strip()

    mismatch_fields: list[str] = []
    missing_fields: list[str] = []
    if expected_brand:
        if not actual_brand:
            missing_fields.append("subject_brand")
        elif actual_brand != expected_brand:
            mismatch_fields.append("subject_brand")
    if expected_model:
        if not actual_model:
            missing_fields.append("subject_model")
        elif actual_model != expected_model:
            mismatch_fields.append("subject_model")

    contamination_codes = sorted(
        code
        for code in quality_issue_codes
        if code in {"subtitle_semantic_contamination", "identity_narrative_conflict"}
    )
    passed = not mismatch_fields and not missing_fields and not contamination_codes
    details: list[str] = []
    if expected_brand or expected_model:
        details.append(
            "expected="
            + "/".join(part for part in (expected_brand, expected_model) if part)
        )
    if actual_brand or actual_model:
        details.append(
            "actual="
            + "/".join(part for part in (actual_brand, actual_model) if part)
        )
    if missing_fields:
        details.append("missing=" + ",".join(missing_fields))
    if mismatch_fields:
        details.append("mismatch=" + ",".join(mismatch_fields))
    if contamination_codes:
        details.append("issue_codes=" + ",".join(contamination_codes))
    return {
        "passed": passed,
        "detail": " | ".join(details),
        "expected_brand": expected_brand,
        "expected_model": expected_model,
        "actual_brand": actual_brand,
        "actual_model": actual_model,
        "missing_fields": missing_fields,
        "mismatch_fields": mismatch_fields,
        "issue_codes": contamination_codes,
    }


def _term_format_consistency_status(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    quality_issue_codes: set[str],
) -> dict[str, Any]:
    model_status = _model_token_integrity_status(
        source_name=source_name,
        content_profile=content_profile,
        quality_issue_codes=quality_issue_codes,
    )
    blocking_issue_codes = sorted(
        code
        for code in quality_issue_codes
        if code in {"subtitle_terms_pending", "subtitle_semantic_contamination", "identity_narrative_conflict"}
    )
    passed = bool(model_status.get("passed")) and not blocking_issue_codes
    details: list[str] = []
    if str(model_status.get("detail") or "").strip():
        details.append(str(model_status.get("detail") or "").strip())
    if blocking_issue_codes:
        details.append("issue_codes=" + ",".join(blocking_issue_codes))
    return {
        "passed": passed,
        "detail": " | ".join(details),
        "issue_codes": blocking_issue_codes,
        "expected_brand": model_status.get("expected_brand"),
        "expected_model": model_status.get("expected_model"),
        "actual_brand": model_status.get("actual_brand"),
        "actual_model": model_status.get("actual_model"),
        "mismatch_fields": list(model_status.get("mismatch_fields") or []),
        "missing_fields": list(model_status.get("missing_fields") or []),
    }


def _low_signal_traceability_status(cut_analysis: dict[str, Any] | None) -> dict[str, Any]:
    analysis = dict(cut_analysis or {}) if isinstance(cut_analysis, dict) else {}
    accepted_cuts = [item for item in cut_analysis_effective_applied_cuts(analysis) if isinstance(item, dict)]
    rule_candidates = [item for item in cut_analysis_rule_candidates(analysis) if isinstance(item, dict)]
    low_signal_items = [
        item
        for item in [*accepted_cuts, *rule_candidates]
        if str(item.get("reason") or "").strip() == "low_signal_subtitle"
    ]
    missing_traceability = sum(1 for item in low_signal_items if not _traceable_cut_candidate(item))
    return {
        "passed": bool(low_signal_items) and missing_traceability == 0,
        "detail": (
            f"missing_traceability_items={missing_traceability}"
            if missing_traceability
            else f"traceability_items={len(low_signal_items)}"
        ),
        "target_count": len(low_signal_items),
        "missing_count": missing_traceability,
    }


def _subtitle_projection_required_check_status(
    subtitle_projection_layer: dict[str, Any] | None,
    quality_issue_codes: set[str],
) -> dict[str, Any]:
    blocking_issue_codes = sorted(
        code
        for code in quality_issue_codes
        if code in {"missing_subtitles", "subtitle_semantic_contamination"}
        or (code.startswith("canonical_projection_quality") and code.endswith("_blocking"))
    )
    warning_codes = sorted(
        code
        for code in quality_issue_codes
        if code.startswith("canonical_projection_quality") and code.endswith("_warning")
    )
    details: list[str] = []
    if blocking_issue_codes:
        details.append(",".join(blocking_issue_codes))
    if warning_codes:
        details.append("warnings=" + ",".join(warning_codes))
    return {
        "passed": bool(subtitle_projection_layer) and not blocking_issue_codes,
        "detail": "; ".join(details),
        "issue_codes": blocking_issue_codes,
        "warning_codes": warning_codes,
    }


async def inspect_evaluation_required_checks(
    case: GoldenJobCase,
    prepared_job: PreparedGoldenJob,
    report: JobRunReport | None,
) -> dict[str, dict[str, Any]]:
    factory = get_session_factory()
    async with factory() as session:
        job = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.steps))
                .where(Job.id == uuid.UUID(prepared_job.job_id))
            )
        ).scalar_one_or_none()
        if job is None:
            raise RuntimeError(f"could not resolve evaluation job for case {case.case_id}")

        artifact_rows = (
            await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job.id,
                    Artifact.artifact_type.in_(
                        [
                            "cut_analysis",
                            "variant_timeline_bundle",
                            "subtitle_projection_layer",
                            "content_profile_final",
                        ]
                    ),
                )
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
        ).scalars().all()
        artifacts_by_type: dict[str, Artifact] = {}
        for artifact in artifact_rows:
            if artifact.artifact_type and artifact.artifact_type not in artifacts_by_type:
                artifacts_by_type[artifact.artifact_type] = artifact

        readiness = await _build_manual_editor_readiness(job=job, session=session)
        quality_issue_codes = {
            str(code).strip()
            for code in list((report.quality_issue_codes if report else []) or [])
            if str(code).strip()
        }
        cut_analysis = (
            artifacts_by_type.get("cut_analysis").data_json
            if artifacts_by_type.get("cut_analysis") is not None and isinstance(artifacts_by_type["cut_analysis"].data_json, dict)
            else {}
        )
        variant_bundle = (
            artifacts_by_type.get("variant_timeline_bundle").data_json
            if artifacts_by_type.get("variant_timeline_bundle") is not None and isinstance(artifacts_by_type["variant_timeline_bundle"].data_json, dict)
            else {}
        )
        subtitle_projection_layer = (
            artifacts_by_type.get("subtitle_projection_layer").data_json
            if artifacts_by_type.get("subtitle_projection_layer") is not None and isinstance(artifacts_by_type["subtitle_projection_layer"].data_json, dict)
            else {}
        )
        content_profile_final = (
            artifacts_by_type.get("content_profile_final").data_json
            if artifacts_by_type.get("content_profile_final") is not None and isinstance(artifacts_by_type["content_profile_final"].data_json, dict)
            else {}
        )

        accepted_cuts = cut_analysis_effective_applied_cuts(cut_analysis)
        rule_candidates = cut_analysis_rule_candidates(cut_analysis)
        high_risk_cuts = variant_high_risk_cuts(variant_bundle)
        traceability_targets = [*accepted_cuts, *high_risk_cuts] or rule_candidates
        traceability_missing = sum(1 for item in traceability_targets if not _traceable_cut_candidate(item))

        return {
            "manual_editor_ready": {
                "passed": bool(readiness.can_open_editor),
                "detail": str(readiness.detail or ""),
                "status": str(readiness.status or ""),
            },
            "subtitle_projection": _subtitle_projection_required_check_status(
                subtitle_projection_layer,
                quality_issue_codes,
            ),
            "cut_analysis_traceability": {
                "passed": bool(cut_analysis) and traceability_missing == 0,
                "detail": (
                    f"missing_traceability_items={traceability_missing}"
                    if traceability_missing
                    else f"traceability_items={len(traceability_targets)}"
                ),
                "target_count": len(traceability_targets),
                "missing_count": traceability_missing,
            },
            "model_token_integrity": _model_token_integrity_status(
                source_name=str(job.source_name or prepared_job.case.source_name or ""),
                content_profile=content_profile_final,
                quality_issue_codes=quality_issue_codes,
            ),
            "term_format_consistency": _term_format_consistency_status(
                source_name=str(job.source_name or prepared_job.case.source_name or ""),
                content_profile=content_profile_final,
                quality_issue_codes=quality_issue_codes,
            ),
            "low_signal_traceability": _low_signal_traceability_status(cut_analysis),
        }


async def collect_evaluation_required_checks(
    cases: list[GoldenJobCase],
    prepared_jobs: list[PreparedGoldenJob],
    reports: list[JobRunReport],
) -> dict[str, dict[str, dict[str, Any]]]:
    prepared_by_case = {item.case.case_id: item for item in prepared_jobs}
    reports_by_job = {item.job_id: item for item in reports}
    results: dict[str, dict[str, dict[str, Any]]] = {}
    for case in cases:
        prepared = prepared_by_case.get(case.case_id)
        if prepared is None:
            continue
        try:
            results[case.case_id] = await inspect_evaluation_required_checks(
                case,
                prepared,
                reports_by_job.get(prepared.job_id),
            )
        except Exception as exc:
            results[case.case_id] = {
                check: {"passed": False, "detail": str(exc)}
                for check in case.required_checks
                if str(check).strip().lower() != "manual_editor_apply_semantics"
            }
    return results


def build_case_result_rows(
    cases: list[GoldenJobCase],
    prepared_jobs: list[PreparedGoldenJob],
    reports: list[JobRunReport],
    scorecard: dict[str, Any],
    *,
    manual_editor_apply_semantics_by_case: dict[str, dict[str, Any]] | None = None,
    reference_risk_snapshots_by_case: dict[str, dict[str, Any]] | None = None,
    evaluation_risk_snapshots_by_case: dict[str, dict[str, Any]] | None = None,
    required_check_statuses_by_case: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    prepared_by_case = {item.case.case_id: item for item in prepared_jobs}
    report_by_job = {item.job_id: item for item in reports}
    scorecard_jobs = {
        str(item.get("source_name") or ""): item
        for item in list(scorecard.get("jobs") or [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for case in cases:
        prepared = prepared_by_case.get(case.case_id)
        report = report_by_job.get(prepared.job_id) if prepared else None
        score = scorecard_jobs.get(report.source_name if report else "")
        manual_editor_apply_semantics = dict((manual_editor_apply_semantics_by_case or {}).get(case.case_id) or {})
        reference_risk_snapshot = dict((reference_risk_snapshots_by_case or {}).get(case.case_id) or {})
        evaluation_risk_snapshot = dict((evaluation_risk_snapshots_by_case or {}).get(case.case_id) or {})
        required_check_statuses = dict((required_check_statuses_by_case or {}).get(case.case_id) or {})
        risk_alignment = _build_case_risk_alignment(
            case,
            score,
            report=report,
            reference_risk_snapshot=reference_risk_snapshot,
            evaluation_risk_snapshot=evaluation_risk_snapshot,
        )
        required_checks_passed, failed_required_checks = _evaluate_required_checks(
            case,
            report,
            manual_editor_apply_semantics=manual_editor_apply_semantics,
            check_statuses=required_check_statuses,
        )
        manual_editor_ready = False
        status_by_stage = {
            str(item.stage).strip().lower(): str(item.status).strip().lower()
            for item in list(report.live_stage_validations or [])
        } if report else {}
        if isinstance(required_check_statuses.get("manual_editor_ready"), dict):
            manual_editor_ready = bool(required_check_statuses["manual_editor_ready"].get("passed"))
        else:
            manual_editor_ready = status_by_stage.get("manual_editor_ready") == "pass"
        rows.append(
            {
                "case_id": case.case_id,
                "scenario": case.scenario,
                "tags": list(case.tags),
                "required_checks": list(case.required_checks),
                "reference_job_id": case.reference_job_id,
                "reference_risk_job_id": case.reference_risk_job_id,
                "evaluation_job_id": prepared.job_id if prepared else "",
                "evaluation_mode": prepared.mode if prepared else "",
                "source_name": report.source_name if report else case.source_name,
                "status": report.status if report else "missing",
                "quality_score": report.quality_score if report else None,
                "quality_grade": report.quality_grade if report else None,
                "editing_score": ((score or {}).get("editing") or {}).get("score"),
                "subtitle_quality_score": ((score or {}).get("subtitle_quality") or {}).get("score"),
                "manual_editor_ready": manual_editor_ready,
                "manual_editor_apply_semantics_ok": bool(manual_editor_apply_semantics.get("ok")),
                "manual_editor_managed_auto_cut_count": manual_editor_apply_semantics.get("managed_auto_cut_count"),
                "manual_editor_change_scope": manual_editor_apply_semantics.get("change_scope"),
                "manual_editor_timeline_changed": manual_editor_apply_semantics.get("timeline_changed"),
                "manual_editor_render_strategy": manual_editor_apply_semantics.get("render_strategy"),
                "manual_editor_roundtrip_matches_editorial": manual_editor_apply_semantics.get("roundtrip_matches_editorial"),
                "manual_editor_session_baseline_matches_restored": manual_editor_apply_semantics.get("session_baseline_matches_restored"),
                "manual_editor_semantics_error": manual_editor_apply_semantics.get("error"),
                "required_checks_passed": required_checks_passed,
                "required_checks_failed": failed_required_checks,
                "required_check_statuses": required_check_statuses,
                "notes": case.notes,
                "risk_hints": dict(case.risk_hints),
                "reference_risk_snapshot": reference_risk_snapshot,
                "evaluation_risk_snapshot": evaluation_risk_snapshot,
                "risk_alignment": risk_alignment,
            }
        )
    return rows


def _build_case_risk_alignment(
    case: GoldenJobCase,
    score: dict[str, Any] | None,
    *,
    report: JobRunReport | None = None,
    reference_risk_snapshot: dict[str, Any] | None = None,
    evaluation_risk_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    risk_hints = case.risk_hints if isinstance(case.risk_hints, dict) else {}
    reference_risk_snapshot = (
        dict(reference_risk_snapshot) if isinstance(reference_risk_snapshot, dict) else {}
    )
    evaluation_risk_snapshot = (
        dict(evaluation_risk_snapshot) if isinstance(evaluation_risk_snapshot, dict) else {}
    )
    editing_risk_metrics = (score or {}).get("editing_risk_metrics") if isinstance(score, dict) else {}
    editing_risk_metrics = dict(editing_risk_metrics) if isinstance(editing_risk_metrics, dict) else {}
    reference_high_risk_cut_count = int(
        reference_risk_snapshot.get("high_risk_cut_count")
        or risk_hints.get("reference_high_risk_cut_count")
        or 0
    )
    reference_expected_stage = str(risk_hints.get("reference_expected_stage") or "").strip() or None
    reference_expected_source = (
        str(risk_hints.get("reference_expected_source") or "").strip()
        or ("variant_timeline_bundle" if bool(reference_risk_snapshot.get("variant_bundle_present")) else None)
    )
    fresh_high_risk_cut_count = int(
        evaluation_risk_snapshot.get("high_risk_cut_count")
        or editing_risk_metrics.get("high_risk_cut_count")
        or 0
    )
    fresh_source = (
        str(editing_risk_metrics.get("source") or "").strip()
        or ("variant_timeline_bundle" if bool(evaluation_risk_snapshot.get("variant_bundle_present")) else "")
        or None
    )
    fresh_source_reason = (
        str(editing_risk_metrics.get("source_reason") or "").strip()
        or ("variant_bundle_available" if bool(evaluation_risk_snapshot.get("variant_bundle_present")) else "")
        or None
    )
    fresh_manual_confirm_count = int(
        evaluation_risk_snapshot.get("manual_confirm_candidate_count")
        or editing_risk_metrics.get("manual_confirm_count")
        or 0
    )
    fresh_multimodal_pending_count = int(
        evaluation_risk_snapshot.get("multimodal_pending_count")
        or editing_risk_metrics.get("multimodal_pending_count")
        or 0
    )
    fresh_llm_reviewed = bool(
        evaluation_risk_snapshot.get("llm_reviewed")
        if "llm_reviewed" in evaluation_risk_snapshot
        else editing_risk_metrics.get("llm_reviewed")
    )
    reference_candidate_risk_summary = dict(reference_risk_snapshot.get("candidate_risk_summary") or {})
    fresh_candidate_risk_summary = dict(evaluation_risk_snapshot.get("candidate_risk_summary") or {})
    reference_risk_levels = dict(reference_risk_snapshot.get("risk_levels") or {})
    fresh_risk_levels = dict(evaluation_risk_snapshot.get("risk_levels") or {})
    reference_auto_apply_candidate_count = int(reference_risk_snapshot.get("auto_apply_candidate_count") or 0)
    fresh_auto_apply_candidate_count = int(evaluation_risk_snapshot.get("auto_apply_candidate_count") or 0)
    reference_rule_auto_apply_cut_count = int(reference_risk_snapshot.get("rule_auto_apply_cut_count") or 0)
    fresh_rule_auto_apply_cut_count = int(evaluation_risk_snapshot.get("rule_auto_apply_cut_count") or 0)
    reference_risk_contract_complete = bool(reference_candidate_risk_summary) and bool(reference_risk_levels)
    fresh_risk_contract_complete = bool(fresh_candidate_risk_summary) and bool(fresh_risk_levels)
    comparison_deferred = bool(
        reference_high_risk_cut_count > 0
        and reference_expected_stage
        and not _golden_report_reached_expected_stage(report, reference_expected_stage)
    )
    mismatch_codes: list[str] = []
    if not comparison_deferred and reference_high_risk_cut_count > 0 and fresh_high_risk_cut_count <= 0:
        mismatch_codes.append("reference_high_risk_not_reproduced")
    if not comparison_deferred and reference_expected_source and fresh_source and reference_expected_source != fresh_source:
        mismatch_codes.append("fresh_source_mismatch")
    if (
        reference_expected_source == "cut_analysis_refine_decision_plan"
        and fresh_risk_contract_complete
        and not reference_risk_contract_complete
    ):
        mismatch_codes.append("reference_risk_contract_incomplete")
    return {
        "reference_high_risk_cut_count": reference_high_risk_cut_count,
        "reference_expected_stage": reference_expected_stage,
        "reference_expected_source": reference_expected_source,
        "fresh_high_risk_cut_count": fresh_high_risk_cut_count,
        "fresh_source": fresh_source,
        "fresh_source_reason": fresh_source_reason,
        "fresh_manual_confirm_count": fresh_manual_confirm_count,
        "fresh_multimodal_pending_count": fresh_multimodal_pending_count,
        "fresh_llm_reviewed": fresh_llm_reviewed,
        "reference_llm_reviewed": bool(reference_risk_snapshot.get("llm_reviewed")),
        "reference_manual_confirm_candidate_count": int(reference_risk_snapshot.get("manual_confirm_candidate_count") or 0),
        "reference_multimodal_pending_count": int(reference_risk_snapshot.get("multimodal_pending_count") or 0),
        "reference_auto_apply_candidate_count": reference_auto_apply_candidate_count,
        "fresh_auto_apply_candidate_count": fresh_auto_apply_candidate_count,
        "reference_rule_auto_apply_cut_count": reference_rule_auto_apply_cut_count,
        "fresh_rule_auto_apply_cut_count": fresh_rule_auto_apply_cut_count,
        "reference_candidate_risk_summary": reference_candidate_risk_summary,
        "fresh_candidate_risk_summary": fresh_candidate_risk_summary,
        "reference_risk_levels": reference_risk_levels,
        "fresh_risk_levels": fresh_risk_levels,
        "reference_risk_contract_complete": reference_risk_contract_complete,
        "fresh_risk_contract_complete": fresh_risk_contract_complete,
        "high_risk_reproduced": comparison_deferred or reference_high_risk_cut_count <= 0 or fresh_high_risk_cut_count > 0,
        "comparison_deferred": comparison_deferred,
        "comparison_deferred_reason": (
            f"reference_expected_stage_not_reached:{reference_expected_stage}"
            if comparison_deferred and reference_expected_stage
            else None
        ),
        "mismatch_codes": mismatch_codes,
        "status": "mismatch" if mismatch_codes else "aligned",
    }


def _golden_report_reached_expected_stage(report: JobRunReport | None, expected_stage: str) -> bool:
    normalized_stage = str(expected_stage or "").strip().lower()
    if not normalized_stage or report is None:
        return True
    if str(report.status or "").strip().lower() in {"done", "failed"}:
        return True
    if normalized_stage not in PIPELINE_STEPS:
        return True
    stage_statuses = {
        str(item.stage).strip().lower(): str(item.status).strip().lower()
        for item in list(report.live_stage_validations or [])
        if str(item.stage).strip()
    }
    observed_status = stage_statuses.get(normalized_stage, "")
    if observed_status in {"pass", "warn", "fail"}:
        return True
    if observed_status == "skipped":
        return False
    return PIPELINE_STEPS.index(normalized_stage) <= PIPELINE_STEPS.index("edit_plan")


def summarize_case_risk_alignment(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatch_case_ids: list[str] = []
    mismatch_code_counts: dict[str, int] = {}
    reference_high_risk_case_count = 0
    reproduced_case_count = 0
    for row in case_rows:
        risk_alignment = row.get("risk_alignment") if isinstance(row.get("risk_alignment"), dict) else {}
        if bool(risk_alignment.get("comparison_deferred")):
            continue
        reference_high_risk_cut_count = int(risk_alignment.get("reference_high_risk_cut_count") or 0)
        mismatch_codes = [
            str(item).strip()
            for item in list(risk_alignment.get("mismatch_codes") or [])
            if str(item).strip()
        ]
        if mismatch_codes:
            case_id = str(row.get("case_id") or "").strip()
            if case_id:
                mismatch_case_ids.append(case_id)
        for code in mismatch_codes:
            mismatch_code_counts[code] = mismatch_code_counts.get(code, 0) + 1
        if reference_high_risk_cut_count <= 0:
            continue
        reference_high_risk_case_count += 1
        if bool(risk_alignment.get("high_risk_reproduced")):
            reproduced_case_count += 1
    return {
        "reference_high_risk_case_count": reference_high_risk_case_count,
        "reproduced_case_count": reproduced_case_count,
        "unreproduced_case_count": max(0, reference_high_risk_case_count - reproduced_case_count),
        "mismatch_case_ids": mismatch_case_ids,
        "mismatch_code_counts": mismatch_code_counts,
    }


def summarize_reference_refresh_candidates(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in case_rows:
        risk_alignment = row.get("risk_alignment") if isinstance(row.get("risk_alignment"), dict) else {}
        mismatch_codes = {
            str(item).strip()
            for item in list(risk_alignment.get("mismatch_codes") or [])
            if str(item).strip()
        }
        if "reference_risk_contract_incomplete" not in mismatch_codes:
            continue
        evaluation_risk_snapshot = (
            dict(row.get("evaluation_risk_snapshot") or {})
            if isinstance(row.get("evaluation_risk_snapshot"), dict)
            else {}
        )
        if not evaluation_risk_snapshot:
            continue
        candidates.append(
            {
                "case_id": str(row.get("case_id") or "").strip(),
                "scenario": str(row.get("scenario") or "").strip(),
                "reference_job_id": str(row.get("reference_job_id") or "").strip(),
                "evaluation_job_id": str(row.get("evaluation_job_id") or "").strip(),
                "evaluation_mode": str(row.get("evaluation_mode") or "").strip(),
                "reference_expected_source": str(risk_alignment.get("reference_expected_source") or "").strip() or None,
                "fresh_source": str(risk_alignment.get("fresh_source") or "").strip() or None,
                "reference_auto_apply_candidate_count": int(risk_alignment.get("reference_auto_apply_candidate_count") or 0),
                "fresh_auto_apply_candidate_count": int(risk_alignment.get("fresh_auto_apply_candidate_count") or 0),
                "reference_rule_auto_apply_cut_count": int(risk_alignment.get("reference_rule_auto_apply_cut_count") or 0),
                "fresh_rule_auto_apply_cut_count": int(risk_alignment.get("fresh_rule_auto_apply_cut_count") or 0),
                "reference_manual_confirm_candidate_count": int(risk_alignment.get("reference_manual_confirm_candidate_count") or 0),
                "fresh_manual_confirm_count": int(risk_alignment.get("fresh_manual_confirm_count") or 0),
                "fresh_multimodal_pending_count": int(risk_alignment.get("fresh_multimodal_pending_count") or 0),
                "fresh_high_risk_cut_count": int(risk_alignment.get("fresh_high_risk_cut_count") or 0),
                "fresh_llm_reviewed": bool(risk_alignment.get("fresh_llm_reviewed")),
                "fresh_candidate_risk_summary": dict(risk_alignment.get("fresh_candidate_risk_summary") or {}),
                "fresh_risk_levels": dict(risk_alignment.get("fresh_risk_levels") or {}),
                "mismatch_codes": sorted(mismatch_codes),
                "refresh_reason": "reference risk contract is incomplete; evaluation snapshot carries the current contract",
            }
        )
    return candidates


def summarize_required_checks(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    total_cases = len(case_rows)
    cases_with_checks = sum(1 for row in case_rows if row.get("required_checks"))
    required_checks_total = sum(len(row.get("required_checks") or []) for row in case_rows)
    required_checks_passed_cases = sum(1 for row in case_rows if row.get("required_checks") and row.get("required_checks_passed"))
    required_checks_failed_cases = [row.get("case_id") for row in case_rows if row.get("required_checks") and not row.get("required_checks_passed")]
    required_checks_contracts_passed = sum(
        1
        for row in case_rows
        for check in list(row.get("required_checks") or [])
        if str(check).strip()
        and str(check).strip() not in {str(item).strip() for item in list(row.get("required_checks_failed") or [])}
    )
    required_checks_contract_failures = required_checks_total - required_checks_contracts_passed
    return {
        "total_cases": total_cases,
        "cases_with_checks": cases_with_checks,
        "required_checks_case_passed": required_checks_passed_cases,
        "required_checks_case_failed": len(required_checks_failed_cases),
        "required_checks_failed_case_ids": required_checks_failed_cases,
        "required_checks_total": required_checks_total,
        "required_checks_contract_passed": required_checks_contracts_passed,
        "required_checks_contract_failed": required_checks_contract_failures,
        "required_checks_contract_pass_rate": (
            float(required_checks_contracts_passed) / float(required_checks_total) if required_checks_total else 1.0
        ),
    }


def summarize_manual_editor_apply_semantics(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible_rows = [
        row
        for row in case_rows
        if "manual_editor_apply_semantics"
        in {
            str(item).strip()
            for item in list(row.get("required_checks") or [])
            if str(item).strip()
        }
    ]
    total_cases = len(eligible_rows)
    failed_case_ids = [
        str(row.get("case_id") or "").strip()
        for row in eligible_rows
        if not bool(row.get("manual_editor_apply_semantics_ok"))
    ]
    passed_case_count = total_cases - len(failed_case_ids)
    return {
        "total_cases": total_cases,
        "passed_case_count": passed_case_count,
        "failed_case_count": len(failed_case_ids),
        "failed_case_ids": [item for item in failed_case_ids if item],
        "pass_rate": (float(passed_case_count) / float(total_cases)) if total_cases else 1.0,
    }


def summarize_render_diagnostics(reports: list[JobRunReport]) -> dict[str, Any]:
    failed_render_job_ids: list[str] = []
    avatar_degraded_job_ids: list[str] = []
    failed_render_reason_counts: dict[str, int] = {}
    avatar_degraded_reason_counts: dict[str, int] = {}
    avatar_degraded_reason_category_counts: dict[str, int] = {}
    evaluated_job_count = 0
    for report in reports:
        diagnostics = report.render_diagnostics if isinstance(report.render_diagnostics, dict) else {}
        render_step = diagnostics.get("render_step") if isinstance(diagnostics.get("render_step"), dict) else {}
        avatar_result = diagnostics.get("avatar_result") if isinstance(diagnostics.get("avatar_result"), dict) else {}
        if not render_step and not avatar_result:
            continue
        evaluated_job_count += 1
        identifier = str(report.job_id or report.source_name or "").strip()
        if str(render_step.get("status") or "").strip().lower() == "failed" and identifier:
            failed_render_job_ids.append(identifier)
            reason = str(render_step.get("reason") or "").strip()
            if reason:
                failed_render_reason_counts[reason] = failed_render_reason_counts.get(reason, 0) + 1
        if str(avatar_result.get("status") or "").strip().lower() == "degraded" and identifier:
            avatar_degraded_job_ids.append(identifier)
            reason = str(avatar_result.get("reason") or "").strip()
            if reason:
                avatar_degraded_reason_counts[reason] = avatar_degraded_reason_counts.get(reason, 0) + 1
                category = str(avatar_result.get("reason_category") or "").strip() or _classify_avatar_runtime_reason_category(reason) or ""
                if category:
                    avatar_degraded_reason_category_counts[category] = (
                        avatar_degraded_reason_category_counts.get(category, 0) + 1
                    )
    return {
        "evaluated_job_count": evaluated_job_count,
        "failed_render_job_count": len(failed_render_job_ids),
        "failed_render_job_ids": failed_render_job_ids,
        "failed_render_reasons": failed_render_reason_counts,
        "cover_degraded_job_count": 0,
        "cover_degraded_job_ids": [],
        "cover_degraded_reasons": {},
        "avatar_degraded_job_count": len(avatar_degraded_job_ids),
        "avatar_degraded_job_ids": avatar_degraded_job_ids,
        "avatar_degraded_reasons": avatar_degraded_reason_counts,
        "avatar_degraded_reason_categories": avatar_degraded_reason_category_counts,
    }


def render_case_summary_markdown(
    *,
    manifest_path: Path,
    case_rows: list[dict[str, Any]],
    required_checks_summary: dict[str, Any],
    render_diagnostics_summary: dict[str, Any] | None,
    risk_alignment_summary: dict[str, Any] | None,
    reference_refresh_candidates: list[dict[str, Any]] | None,
    batch_report_path: Path,
    scorecard_path: Path,
    audit_paths: dict[str, Path],
) -> str:
    lines = [
        "# Auto Edit Recovery Golden Set",
        "",
        f"- manifest: `{manifest_path}`",
        f"- batch_report: `{batch_report_path}`",
        f"- scorecard: `{scorecard_path}`",
        f"- required_checks_passed: {required_checks_summary.get('required_checks_contract_passed') or 0}/{required_checks_summary.get('required_checks_total') or 0}",
        f"- required_checks_failed_cases: {required_checks_summary.get('required_checks_case_failed') or 0}/{required_checks_summary.get('cases_with_checks') or 0}",
        f"- case_count: `{len(case_rows)}`",
        "",
    ]
    if isinstance(render_diagnostics_summary, dict) and int(render_diagnostics_summary.get("evaluated_job_count") or 0) > 0:
        lines.extend(
            [
                "## Render Diagnostics Summary",
                f"- evaluated_job_count: {render_diagnostics_summary.get('evaluated_job_count') or 0}",
                f"- failed_render_job_count: {render_diagnostics_summary.get('failed_render_job_count') or 0}",
                f"- avatar_degraded_job_count: {render_diagnostics_summary.get('avatar_degraded_job_count') or 0}",
            ]
        )
        for label, key in (
            ("failed_render_reasons", "failed_render_reasons"),
            ("avatar_degraded_reasons", "avatar_degraded_reasons"),
            ("avatar_degraded_reason_categories", "avatar_degraded_reason_categories"),
        ):
            reason_counts = render_diagnostics_summary.get(key) if isinstance(render_diagnostics_summary.get(key), dict) else {}
            if reason_counts:
                rendered = ", ".join(
                    f"{reason}={count}"
                    for reason, count in sorted(reason_counts.items())
                    if str(reason).strip()
                )
                lines.append(f"- {label}: {rendered}")
        lines.append("")
    if isinstance(risk_alignment_summary, dict) and int(risk_alignment_summary.get("reference_high_risk_case_count") or 0) > 0:
        lines.extend(
            [
                "## Risk Alignment Summary",
                f"- reference_high_risk_case_count: {risk_alignment_summary.get('reference_high_risk_case_count') or 0}",
                f"- reproduced_case_count: {risk_alignment_summary.get('reproduced_case_count') or 0}",
                f"- unreproduced_case_count: {risk_alignment_summary.get('unreproduced_case_count') or 0}",
            ]
        )
        mismatch_code_counts = (
            risk_alignment_summary.get("mismatch_code_counts")
            if isinstance(risk_alignment_summary.get("mismatch_code_counts"), dict)
            else {}
        )
        if mismatch_code_counts:
            rendered = ", ".join(
                f"{code}={count}"
                for code, count in sorted(mismatch_code_counts.items())
                if str(code).strip()
            )
            lines.append(f"- mismatch_codes: {rendered}")
        lines.append("")
    if reference_refresh_candidates:
        lines.extend(
            [
                "## Reference Refresh Candidates",
                f"- candidate_count: {len(reference_refresh_candidates)}",
            ]
        )
        for candidate in reference_refresh_candidates:
            case_id = str(candidate.get("case_id") or "").strip() or "case"
            lines.append(f"- {case_id}:")
            lines.extend(_render_risk_hint_lines(candidate, indent="  "))
        lines.append("")
    for row in case_rows:
        lines.append(f"## {row.get('case_id')}")
        lines.append(f"- scenario: {row.get('scenario') or ''}")
        lines.append(f"- source_name: {row.get('source_name') or ''}")
        lines.append(f"- reference_job_id: `{row.get('reference_job_id') or ''}`")
        if str(row.get("reference_risk_job_id") or "").strip():
            lines.append(f"- reference_risk_job_id: `{row.get('reference_risk_job_id') or ''}`")
        lines.append(f"- evaluation_job_id: `{row.get('evaluation_job_id') or ''}`")
        lines.append(f"- evaluation_mode: `{row.get('evaluation_mode') or ''}`")
        lines.append(f"- status: `{row.get('status') or ''}`")
        lines.append(f"- quality: `{row.get('quality_grade') or 'N/A'}` {row.get('quality_score')}")
        lines.append(f"- subtitle_quality_score: {row.get('subtitle_quality_score')}")
        lines.append(f"- editing_score: {row.get('editing_score')}")
        lines.append(f"- manual_editor_ready: {row.get('manual_editor_ready')}")
        lines.append(f"- manual_editor_apply_semantics_ok: {row.get('manual_editor_apply_semantics_ok')}")
        lines.append(f"- manual_editor_managed_auto_cut_count: {row.get('manual_editor_managed_auto_cut_count')}")
        if row.get("manual_editor_change_scope") or row.get("manual_editor_render_strategy"):
            lines.append(
                "- manual_editor_apply: "
                + " / ".join(
                    [
                        f"change_scope={row.get('manual_editor_change_scope')}",
                        f"timeline_changed={row.get('manual_editor_timeline_changed')}",
                        f"render_strategy={row.get('manual_editor_render_strategy')}",
                        f"roundtrip_matches_editorial={row.get('manual_editor_roundtrip_matches_editorial')}",
                        f"session_baseline_matches_restored={row.get('manual_editor_session_baseline_matches_restored')}",
                    ]
                )
            )
        if row.get("manual_editor_semantics_error"):
            lines.append(f"- manual_editor_semantics_error: {row.get('manual_editor_semantics_error')}")
        lines.append(f"- required_checks_passed: {row.get('required_checks_passed')}")
        if row.get("tags"):
            lines.append("- tags: " + ", ".join(row["tags"]))
        if row.get("required_checks"):
            lines.append("- required_checks: " + ", ".join(row["required_checks"]))
        failed_checks = row.get("required_checks_failed") or []
        if failed_checks:
            lines.append("- required_checks_failed: " + ", ".join(map(str, failed_checks)))
        if row.get("notes"):
            lines.append("- notes: " + str(row["notes"]))
        risk_hints = row.get("risk_hints") if isinstance(row.get("risk_hints"), dict) else {}
        if risk_hints:
            lines.append("- risk_hints:")
            lines.extend(_render_risk_hint_lines(risk_hints))
        reference_risk_snapshot = (
            row.get("reference_risk_snapshot")
            if isinstance(row.get("reference_risk_snapshot"), dict)
            else {}
        )
        if reference_risk_snapshot:
            lines.append("- reference_risk_snapshot:")
            lines.extend(_render_risk_hint_lines(reference_risk_snapshot))
        evaluation_risk_snapshot = (
            row.get("evaluation_risk_snapshot")
            if isinstance(row.get("evaluation_risk_snapshot"), dict)
            else {}
        )
        if evaluation_risk_snapshot:
            lines.append("- evaluation_risk_snapshot:")
            lines.extend(_render_risk_hint_lines(evaluation_risk_snapshot))
        risk_alignment = row.get("risk_alignment") if isinstance(row.get("risk_alignment"), dict) else {}
        if risk_alignment:
            lines.append("- risk_alignment:")
            lines.extend(_render_risk_hint_lines(risk_alignment))
        audit_path = audit_paths.get(str(row.get("evaluation_job_id") or ""))
        if audit_path is not None:
            lines.append(f"- audit_pack: `{audit_path}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _render_risk_hint_lines(risk_hints: dict[str, Any], *, indent: str = "  ") -> list[str]:
    lines: list[str] = []
    for key, value in risk_hints.items():
        if isinstance(value, dict):
            lines.append(f"{indent}- {key}:")
            lines.extend(_render_risk_hint_lines(value, indent=indent + "  "))
            continue
        if isinstance(value, list):
            rendered_items = ", ".join(str(item) for item in value)
            lines.append(f"{indent}- {key}: {rendered_items}")
            continue
        lines.append(f"{indent}- {key}: {value}")
    return lines


async def _write_audit_pack_for_job(
    *,
    report: JobRunReport,
    audit_dir: Path,
    locate_roots: list[str],
) -> Path:
    slug = _slugify(report.source_name or report.job_id)
    snapshot_path = audit_dir / f"{slug}.{report.job_id}.snapshot.json"
    markdown_path = audit_dir / f"{slug}.{report.job_id}.md"
    export_args = argparse.Namespace(
        job_id=report.job_id,
        keywords=list(DEFAULT_KEYWORDS),
        locate_root=list(locate_roots or []),
        output_json=snapshot_path,
    )
    snapshot = await export_snapshot(export_args)
    markdown = build_audit_markdown(snapshot, {})
    markdown_path.write_text(markdown, encoding="utf-8")
    return markdown_path


def main() -> None:
    _configure_local_event_loop_policy()
    args = parse_args()
    ensure_batch_runtime_ready()

    cases = select_golden_job_cases(
        load_golden_job_manifest(args.manifest),
        case_ids=list(args.case_ids or []),
        tags=list(args.tags or []),
    )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = args.report_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    prepared_jobs: list[PreparedGoldenJob] = []
    reports: list[JobRunReport] = []
    for case in cases:
        prepared = asyncio.run(
            prepare_golden_job(
                case,
                default_workflow_template=args.workflow_template,
                default_language=args.language,
                locate_roots=list(args.locate_root or []),
            )
        )
        prepared_jobs.append(prepared)
        reports.append(run_job(prepared.job_id, prepared.item, stop_after=args.stop_after))
    manual_editor_apply_semantics = asyncio.run(collect_manual_editor_apply_semantics(cases, prepared_jobs))
    reference_risk_snapshots = asyncio.run(collect_reference_risk_snapshots(cases))
    evaluation_risk_snapshots = asyncio.run(collect_evaluation_risk_snapshots(prepared_jobs))
    required_check_statuses = asyncio.run(collect_evaluation_required_checks(cases, prepared_jobs, reports))

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(args.manifest.resolve()),
        "stop_after": args.stop_after,
        "source_dir": "",
        "channel_profile": args.workflow_template,
        "language": args.language,
        "output_dir": None,
        "enhancement_modes": [],
        "job_count": len(reports),
        "success_count": sum(1 for report in reports if report.status == "done"),
        "partial_count": sum(1 for report in reports if report.status == "partial"),
        "failed_count": sum(1 for report in reports if report.status == "failed"),
        "jobs": [asdict(report) for report in reports],
        "golden_cases": [
            {
                **asdict(prepared.case),
                "evaluation_job_id": prepared.job_id,
                "evaluation_mode": prepared.mode,
            }
            for prepared in prepared_jobs
        ],
        "manual_editor_apply_semantics": manual_editor_apply_semantics,
        "required_check_statuses": required_check_statuses,
    }
    previous_summaries = load_previous_batch_summaries(args.previous_batch_reports)
    batch_report_path = run_dir / "batch_report.json"
    batch_markdown_path = run_dir / "batch_report.md"

    scorecard_path = run_dir / "detailed_output_scorecard.json"
    scorecard_markdown_path = run_dir / "detailed_output_scorecard.md"
    preflight_scorecard = asyncio.run(build_scorecard(summary))
    preflight_scorecard["batch_report"] = str(batch_report_path)

    audit_dir = run_dir / "audit_packs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_paths: dict[str, Path] = {}
    for report in reports:
        if not job_requires_audit(report, audit_threshold=args.audit_threshold):
            continue
        try:
            audit_paths[report.job_id] = asyncio.run(
                _write_audit_pack_for_job(
                    report=report,
                    audit_dir=audit_dir,
                    locate_roots=list(args.locate_root or []),
                )
            )
        except Exception as exc:
            failure_path = audit_dir / f"{_slugify(report.source_name or report.job_id)}.{report.job_id}.error.txt"
            failure_path.write_text(str(exc), encoding="utf-8")

    case_rows = build_case_result_rows(
        cases,
        prepared_jobs,
        reports,
        preflight_scorecard,
        manual_editor_apply_semantics_by_case=manual_editor_apply_semantics,
        reference_risk_snapshots_by_case=reference_risk_snapshots,
        evaluation_risk_snapshots_by_case=evaluation_risk_snapshots,
        required_check_statuses_by_case=required_check_statuses,
    )
    required_checks_summary = summarize_required_checks(case_rows)
    manual_editor_apply_semantics_summary = summarize_manual_editor_apply_semantics(case_rows)
    render_diagnostics_summary = summarize_render_diagnostics(reports)
    risk_alignment_summary = summarize_case_risk_alignment(case_rows)
    reference_refresh_candidates = summarize_reference_refresh_candidates(case_rows)
    summary["required_checks"] = required_checks_summary
    summary["golden_case_rows"] = case_rows
    summary["manual_editor_apply_semantics_summary"] = manual_editor_apply_semantics_summary
    summary["render_diagnostics_summary"] = render_diagnostics_summary
    summary["risk_alignment_summary"] = risk_alignment_summary
    summary["reference_refresh_candidates"] = reference_refresh_candidates
    summary["reference_risk_snapshots"] = reference_risk_snapshots
    summary["evaluation_risk_snapshots"] = evaluation_risk_snapshots

    live_readiness = asdict(
        build_live_readiness_summary(
            summary,
            golden_source_names=[report.source_name for report in reports if report.source_name],
            previous_summaries=previous_summaries,
        )
    )
    summary["live_readiness"] = live_readiness
    scorecard = asyncio.run(build_scorecard(summary))
    scorecard["batch_report"] = str(batch_report_path)
    scorecard_path.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    scorecard_markdown_path.write_text(
        render_scorecard_markdown(scorecard, batch_report_path),
        encoding="utf-8",
    )
    batch_report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    batch_markdown_path.write_text(render_markdown(summary), encoding="utf-8")
    overview_path = run_dir / "golden_set_summary.md"
    overview_path.write_text(
        render_case_summary_markdown(
            manifest_path=args.manifest.resolve(),
            case_rows=case_rows,
            required_checks_summary=required_checks_summary,
            render_diagnostics_summary=render_diagnostics_summary,
            risk_alignment_summary=risk_alignment_summary,
            reference_refresh_candidates=reference_refresh_candidates,
            batch_report_path=batch_report_path,
            scorecard_path=scorecard_path,
            audit_paths=audit_paths,
        ),
        encoding="utf-8",
    )

    console_summary = build_console_summary(summary)
    console_summary["golden_manifest"] = str(args.manifest.resolve())
    console_summary["run_dir"] = str(run_dir)
    console_summary["audit_pack_count"] = len(audit_paths)
    if isinstance(summary.get("required_checks"), dict):
        console_summary["required_checks"] = summary["required_checks"]
    print(json.dumps(console_summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
