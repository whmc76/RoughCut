"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from roughcut.avatar import list_avatar_material_profiles
from roughcut.config import get_settings
from roughcut.creative import (
    ai_director_mode_enabled,
    auto_review_mode_enabled,
    avatar_mode_enabled,
    build_ai_director_plan,
    build_avatar_commentary_plan,
    build_job_creative_profile,
    multilingual_translation_mode_enabled,
)
from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, RenderOutput, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.edit.decisions import build_edit_decision, infer_timeline_analysis
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.presets import normalize_workflow_template_name
from roughcut.edit.render_plan import (
    build_ai_effect_render_plan,
    build_avatar_render_plan,
    build_plain_render_plan,
    build_render_plan,
    build_smart_editing_accents,
    save_render_plan,
)
from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill
from roughcut.edit.timeline import save_editorial_timeline
from roughcut.media.audio import NoAudioStreamError, extract_audio, extract_audio_clip
from roughcut.media.output import (
    build_variant_output_path,
    extract_cover_frame,
    get_output_project_dir,
    load_cover_selection_summary,
    write_srt_file,
)
from roughcut.media.scene import detect_scenes
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.media.probe import probe, validate_media
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.llm_cache import build_cache_key, build_cache_metadata, digest_payload, load_cached_entry, save_cached_json
from roughcut.packaging.library import (
    list_packaging_assets,
    rank_insert_candidates_for_section,
    resolve_insert_added_duration,
    resolve_insert_effective_duration,
    resolve_insert_transition_overlap,
    resolve_packaging_plan_for_job,
)
from roughcut.providers.factory import get_avatar_provider, get_reasoning_provider, get_voice_provider
from roughcut.providers.reasoning.base import Message
from roughcut.pipeline.quality import _compute_subtitle_sync_check
from roughcut.review.content_profile import (
    apply_content_profile_feedback,
    apply_identity_review_guard,
    assess_content_profile_automation,
    build_content_profile_cache_fingerprint,
    build_review_feedback_verification_bundle,
    build_transcript_excerpt,
    enrich_content_profile,
    infer_content_profile,
    polish_subtitle_items,
    resolve_content_profile_review_feedback,
)
from roughcut.review.content_profile_memory import load_content_profile_user_memory
from roughcut.review.downstream_context import (
    build_downstream_context,
    resolve_downstream_profile,
)
from roughcut.review.domain_glossaries import (
    _CANONICAL_DOMAIN_SOURCES,
    _DOMAIN_COMPATIBILITY,
    _WORKFLOW_TEMPLATE_DOMAINS,
    detect_glossary_domains,
    filter_scoped_glossary_terms,
    merge_glossary_terms,
    normalize_subject_domain,
    resolve_builtin_glossary_terms,
    select_primary_subject_domain,
)
from roughcut.review.glossary_engine import apply_glossary_corrections
from roughcut.review.platform_copy import (
    build_packaging_fact_sheet,
    build_packaging_fact_sheet_cache_fingerprint,
    build_packaging_prompt_brief,
    build_platform_packaging_cache_fingerprint,
    generate_platform_packaging,
    packaging_fact_sheet_cache_allowed,
    save_platform_packaging_markdown,
)
from roughcut.review.evidence_types import ARTIFACT_TYPE_CONTENT_PROFILE_OCR, build_correction_framework_trace
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt
from roughcut.review.subtitle_translation import (
    detect_subtitle_language,
    languages_equivalent,
    resolve_translation_target_language,
    translate_subtitle_items,
)
from roughcut.review.telegram_bot import get_telegram_review_bot_service
from roughcut.speech.postprocess import normalize_display_text, save_subtitle_items, split_into_subtitles
from roughcut.speech.transcribe import persist_empty_transcript_result, transcribe_audio
from roughcut.storage.s3 import get_storage, job_key
from roughcut.usage import track_step_usage, track_usage_operation


STEP_LABELS = {
    "probe": "探测媒体信息",
    "extract_audio": "提取音频",
    "transcribe": "语音转写",
    "subtitle_postprocess": "字幕后处理",
    "subtitle_translation": "字幕翻译",
    "content_profile": "内容摘要",
    "summary_review": "人工确认",
    "glossary_review": "术语纠错",
    "ai_director": "AI导演",
    "avatar_commentary": "数字人解说",
    "edit_plan": "剪辑决策",
    "render": "渲染输出",
    "final_review": "成片审核",
    "platform_package": "平台文案",
}

_SUBTITLE_COPY_GENERIC_PREFIX_RE = re.compile(
    r"^(?:这里(?:开始|先)?|这边(?:开始|先)?|接下来(?:再)?|然后(?:再)?|那我们|我们(?:先|再)?|现在(?:先)?|再看|重点看|主要看)"
)
_SUBTITLE_COPY_CTA_PATTERNS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("点赞", "收藏", "关注"), "记得点赞收藏关注。"),
    (("点赞", "收藏"), "记得点赞收藏。"),
    (("关注",), "记得关注。"),
)
_SUBTITLE_COPY_DETAIL_TERMS = (
    "参数",
    "细节",
    "重点",
    "尺寸",
    "接口",
    "版本",
    "续航",
    "流明",
    "材质",
    "做工",
    "手感",
    "节点",
    "工作流",
    "模型",
    "画布",
    "分仓",
    "挂点",
    "收纳",
    "对比",
    "区别",
    "差异",
)
_SUBTITLE_COPY_HOOK_LEADS = (
    "先说结论",
    "先给结论",
    "先抛一个结论",
    "一句话",
    "直接说结论",
)

logger = logging.getLogger(__name__)

_CONTENT_PROFILE_ARTIFACT_TYPES = ("content_profile_final", "content_profile", "content_profile_draft")
_DOWNSTREAM_PROFILE_ARTIFACT_TYPES = ("downstream_context",) + _CONTENT_PROFILE_ARTIFACT_TYPES
_EDIT_PLAN_SUBTITLE_POLISH_TIMEOUT_SEC = 45.0
_EDIT_PLAN_INSERT_SLOT_TIMEOUT_SEC = 20.0
_SOURCE_NAME_TIMESTAMP_RE = re.compile(r"(?<!\d)(?P<date>\d{8})[-_ ]?(?P<time>\d{6})(?!\d)")
_SOURCE_NAME_SEQUENCE_RE = re.compile(r"(?P<prefix>[A-Za-z]+)[-_ ]?(?P<number>\d{3,6})(?!.*\d)")


def _workflow_template_subject_domain(workflow_template: str | None) -> str | None:
    normalized = normalize_workflow_template_name(workflow_template)
    if not normalized:
        return None
    if normalized == "edc_tactical":
        return "edc"
    domains = _WORKFLOW_TEMPLATE_DOMAINS.get(normalized, ())
    if not domains:
        return None
    return select_primary_subject_domain(domains)


def _infer_subject_domain_for_memory(
    *,
    workflow_template: str | None,
    subtitle_items: list[dict[str, Any]] | None = None,
    content_profile: dict[str, Any] | None = None,
    source_name: str | None = None,
    subject_domain: str | None = None,
) -> str | None:
    explicit_subject_domain = normalize_subject_domain(subject_domain or (content_profile or {}).get("subject_domain"))
    if explicit_subject_domain:
        return explicit_subject_domain
    detected_subject_domain = select_primary_subject_domain(detect_glossary_domains(
        workflow_template=None,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
    ))
    if detected_subject_domain:
        return detected_subject_domain
    return _workflow_template_subject_domain(workflow_template)


def _parse_source_name_timestamp(source_name: str) -> datetime | None:
    match = _SOURCE_NAME_TIMESTAMP_RE.search(Path(str(source_name or "")).stem)
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group('date')}{match.group('time')}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_source_name_sequence(source_name: str) -> tuple[str, int] | None:
    stem = Path(str(source_name or "")).stem
    match = _SOURCE_NAME_SEQUENCE_RE.search(stem)
    if not match:
        return None
    prefix = str(match.group("prefix") or "").strip().lower()
    if not prefix:
        return None
    try:
        return prefix, int(match.group("number"))
    except (TypeError, ValueError):
        return None


def _source_name_continuity_score(left_source_name: str, right_source_name: str) -> float:
    left_timestamp = _parse_source_name_timestamp(left_source_name)
    right_timestamp = _parse_source_name_timestamp(right_source_name)
    if left_timestamp and right_timestamp:
        gap = abs((left_timestamp - right_timestamp).total_seconds())
        if gap <= 180:
            return 1.0
        if gap <= 600:
            return 0.92
        if gap <= 1800:
            return 0.82
        if gap <= 3600:
            return 0.68
        return 0.0

    left_sequence = _parse_source_name_sequence(left_source_name)
    right_sequence = _parse_source_name_sequence(right_source_name)
    if left_sequence and right_sequence and left_sequence[0] == right_sequence[0]:
        gap = abs(left_sequence[1] - right_sequence[1])
        if gap <= 1:
            return 1.0
        if gap == 2:
            return 0.9
        if gap == 3:
            return 0.82
        if gap <= 5:
            return 0.7
    return 0.0


def _resolve_edit_plan_review_focus(step: JobStep | None) -> str:
    if step is None or not isinstance(step.metadata_, dict):
        return ""
    return str(step.metadata_.get("review_rerun_focus") or "").strip().lower()


async def _load_related_profile_source_context(
    session,
    *,
    job: Job,
    source_context: dict[str, Any] | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    payload = dict(source_context or {}) if isinstance(source_context, dict) else {}
    if not bool(payload.get("allow_related_profiles")):
        return {}
    merged_source_names = [
        str(item).strip()
        for item in (payload.get("merged_source_names") or payload.get("related_source_names") or [])
        if str(item).strip()
    ]
    preferred_source_names: list[str] = []
    seen_source_names: set[str] = set()
    for source_name in merged_source_names:
        if source_name and source_name != str(job.source_name or "").strip() and source_name not in seen_source_names:
            preferred_source_names.append(source_name)
            seen_source_names.add(source_name)
    if not preferred_source_names:
        return {}

    candidates_result = await session.execute(
        select(Job)
        .where(Job.source_name.in_(preferred_source_names), Job.id != job.id)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )
    candidates = list(candidates_result.scalars().all())
    jobs_by_source_name: dict[str, Job] = {}
    for candidate in candidates:
        candidate_source_name = str(candidate.source_name or "").strip()
        if candidate_source_name and candidate_source_name not in jobs_by_source_name:
            jobs_by_source_name[candidate_source_name] = candidate
    scored_jobs: list[tuple[Job, float]] = []
    for source_name in preferred_source_names:
        candidate = jobs_by_source_name.get(source_name)
        if candidate is not None:
            scored_jobs.append((candidate, 1.0))
    if not scored_jobs:
        return {}

    candidate_ids = [candidate.id for candidate, _score in scored_jobs]
    artifacts_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id.in_(candidate_ids),
            Artifact.artifact_type.in_(_CONTENT_PROFILE_ARTIFACT_TYPES),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts_by_job_id: dict[uuid.UUID, list[Artifact]] = {}
    for artifact in artifacts_result.scalars().all():
        artifacts_by_job_id.setdefault(artifact.job_id, []).append(artifact)

    related_profiles: list[dict[str, Any]] = []
    for candidate, score in sorted(scored_jobs, key=lambda item: item[1], reverse=True):
        artifact = _select_preferred_content_profile_artifact(artifacts_by_job_id.get(candidate.id, []))
        profile = dict((artifact.data_json if artifact else None) or {})
        if not profile:
            continue
        related_profile = {
            "source_name": str(candidate.source_name or "").strip(),
            "subject_brand": str(profile.get("subject_brand") or "").strip(),
            "subject_model": str(profile.get("subject_model") or "").strip(),
            "subject_type": str(profile.get("subject_type") or "").strip(),
            "video_theme": str(profile.get("video_theme") or "").strip(),
            "summary": str(profile.get("summary") or "").strip(),
            "search_queries": [str(item).strip() for item in (profile.get("search_queries") or []) if str(item).strip()][:6],
            "score": score,
        }
        if any(
            (
                related_profile["subject_brand"],
                related_profile["subject_model"],
                related_profile["subject_type"],
                related_profile["video_theme"],
                related_profile["summary"],
                related_profile["search_queries"],
            )
        ):
            related_profiles.append(related_profile)
        if len(related_profiles) >= limit:
            break
    if not related_profiles:
        return {}
    return {"related_profiles": related_profiles[:limit]}


def _expand_subject_domain_scope(subject_domain: str | None) -> set[str]:
    normalized_subject_domain = normalize_subject_domain(subject_domain)
    if not normalized_subject_domain:
        return set()

    queue = [normalized_subject_domain, *_CANONICAL_DOMAIN_SOURCES.get(normalized_subject_domain, (normalized_subject_domain,))]
    expanded: set[str] = set()
    seen: set[str] = set()
    while queue:
        domain = str(queue.pop(0) or "").strip().lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        expanded.add(domain)
        canonical = normalize_subject_domain(domain)
        if canonical:
            expanded.add(canonical)
            if canonical not in seen:
                queue.append(canonical)
        for related in _DOMAIN_COMPATIBILITY.get(domain, ()):
            if related not in seen:
                queue.append(related)
    return expanded


def _glossary_term_matches_subject_domain(term: dict[str, Any], subject_domain: str | None) -> bool:
    if not subject_domain:
        return True
    supported_domains = _expand_subject_domain_scope(subject_domain)
    term_domain = str(term.get("domain") or "").strip().lower()
    if term_domain:
        normalized_term_domain = normalize_subject_domain(term_domain) or term_domain
        return term_domain in supported_domains or normalized_term_domain in supported_domains

    correct_form = str(term.get("correct_form") or "").strip()
    if not correct_form:
        return False
    detected_domains = detect_glossary_domains(
        workflow_template=None,
        content_profile=None,
        subtitle_items=[{"text_final": correct_form}],
    )
    if not detected_domains:
        return True
    return bool(set(detected_domains) & supported_domains)


def _resolve_subtitle_split_profile(*, width: int | None, height: int | None) -> dict[str, float | int | str]:
    safe_width = max(0, int(width or 0))
    safe_height = max(0, int(height or 0))
    if safe_height > safe_width and safe_width > 0:
        return {
            "orientation": "portrait",
            "max_chars": 12,
            "max_duration": 2.6,
        }
    return {
        "orientation": "landscape",
        "max_chars": 18,
        "max_duration": 3.4,
    }


def _build_edit_plan_transcript_segments(
    transcript_rows: list[TranscriptSegment],
    transcript_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    artifact_segments = []
    if isinstance(transcript_evidence, dict):
        artifact_segments = list(transcript_evidence.get("segments") or [])
    if artifact_segments:
        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(artifact_segments):
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "index": int(item.get("index", index) or index),
                    "start": float(item.get("start") or 0.0),
                    "end": float(item.get("end") or 0.0),
                    "text": str(item.get("text") or item.get("raw_text") or ""),
                    "speaker": item.get("speaker"),
                    "confidence": item.get("confidence"),
                    "logprob": item.get("logprob"),
                    "alignment": item.get("alignment"),
                    "words": list(item.get("words") or []),
                }
            )
        if normalized:
            return normalized

    fallback_segments: list[dict[str, Any]] = []
    for row in transcript_rows:
        fallback_segments.append(
            {
                "index": int(row.segment_index),
                "start": float(row.start_time),
                "end": float(row.end_time),
                "text": str(row.text or ""),
                "speaker": row.speaker,
                "words": list(row.words_json or []),
            }
        )
    return fallback_segments


def _job_creative_profile(job: Job) -> dict[str, object]:
    return build_job_creative_profile(
        workflow_mode=str(getattr(job, "workflow_mode", "") or "standard_edit"),
        enhancement_modes=list(getattr(job, "enhancement_modes", []) or []),
    )


async def _set_step_progress(
    session,
    step: JobStep | None,
    *,
    detail: str,
    progress: float | None = None,
) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    metadata["detail"] = detail
    metadata["label"] = STEP_LABELS.get(step.step_name, step.step_name)
    now = datetime.now(timezone.utc)
    metadata["updated_at"] = now.isoformat()
    if progress is not None:
        metadata["progress"] = max(0.0, min(1.0, progress))
    elapsed_seconds = _compute_step_elapsed_seconds(step, now=now)
    if elapsed_seconds is not None:
        metadata["elapsed_seconds"] = round(elapsed_seconds, 3)
    step.metadata_ = metadata
    await session.commit()


def _set_step_cache_metadata(step: JobStep | None, cache_name: str, cache_metadata: dict[str, Any]) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    cache_block = dict(metadata.get("cache") or {})
    cache_block[cache_name] = cache_metadata
    metadata["cache"] = cache_block
    step.metadata_ = metadata


def _set_step_correction_framework_metadata(step: JobStep | None, settings: object) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    metadata["correction_framework"] = build_correction_framework_trace(settings)
    step.metadata_ = metadata


def _extract_usage_snapshot(metadata: dict[str, Any] | None) -> dict[str, int]:
    usage = dict((metadata or {}).get("llm_usage") or {})
    prompt_tokens = max(0, int(usage.get("prompt_tokens") or 0))
    completion_tokens = max(0, int(usage.get("completion_tokens") or 0))
    calls = max(0, int(usage.get("calls") or 0))
    return {
        "calls": calls,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _usage_delta(after: dict[str, Any] | None, before: dict[str, Any] | None) -> dict[str, int] | None:
    after_snapshot = after or {}
    before_snapshot = before or {}
    delta = {
        "calls": max(0, int(after_snapshot.get("calls") or 0) - int(before_snapshot.get("calls") or 0)),
        "prompt_tokens": max(
            0,
            int(after_snapshot.get("prompt_tokens") or 0) - int(before_snapshot.get("prompt_tokens") or 0),
        ),
        "completion_tokens": max(
            0,
            int(after_snapshot.get("completion_tokens") or 0) - int(before_snapshot.get("completion_tokens") or 0),
        ),
    }
    delta["total_tokens"] = delta["prompt_tokens"] + delta["completion_tokens"]
    return delta if delta["calls"] > 0 or delta["total_tokens"] > 0 else None


async def _read_persisted_step_usage_snapshot(step_id: uuid.UUID | None) -> dict[str, int]:
    if step_id is None:
        return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    async with get_session_factory()() as session:
        step = await session.get(JobStep, step_id)
        if step is None:
            return {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        return _extract_usage_snapshot(dict(step.metadata_ or {}))


def _spawn_step_heartbeat(
    *,
    step_id: uuid.UUID | None,
    detail: str,
    progress: float | None = None,
) -> asyncio.Task[None] | None:
    if step_id is None:
        return None

    interval_sec = max(5, int(get_settings().step_heartbeat_interval_sec or 20))

    async def _heartbeat_loop() -> None:
        factory = get_session_factory()
        while True:
            await asyncio.sleep(interval_sec)
            async with factory() as session:
                step_ref = await session.get(JobStep, step_id)
                if step_ref is None or step_ref.status != "running":
                    return
                await _set_step_progress(session, step_ref, detail=detail, progress=progress)

    return asyncio.create_task(_heartbeat_loop())


def _resolve_transcribe_runtime_timeout_seconds(settings: object) -> float:
    timeout = getattr(settings, "transcribe_runtime_timeout_sec", None)
    if timeout is None:
        timeout = getattr(settings, "step_stale_timeout_sec", 900)
    return max(0.1, float(timeout or 900))


def _content_profile_artifact_priority(artifact_type: str) -> int:
    priorities = {
        "content_profile_final": 3,
        "content_profile": 1,
        "content_profile_draft": 1,
    }
    return priorities.get(str(artifact_type or "").strip(), 0)


def _downstream_profile_artifact_priority(artifact_type: str) -> int:
    priorities = {
        "downstream_context": 4,
        "content_profile_final": 3,
        "content_profile": 2,
        "content_profile_draft": 1,
    }
    return priorities.get(str(artifact_type or "").strip(), 0)


def _select_preferred_content_profile_artifact(artifacts: list[Artifact]) -> Artifact | None:
    if not artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    finals = [artifact for artifact in artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"]
    if finals:
        return max(
            finals,
            key=lambda artifact: (
                _content_profile_artifact_priority(artifact.artifact_type),
                artifact.created_at or epoch,
            ),
        )
    return max(
        artifacts,
        key=lambda artifact: (
            _content_profile_artifact_priority(artifact.artifact_type),
            artifact.created_at or epoch,
        ),
    )


def _select_preferred_downstream_profile_artifact(artifacts: list[Artifact]) -> Artifact | None:
    if not artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(
        artifacts,
        key=lambda artifact: (
            _downstream_profile_artifact_priority(artifact.artifact_type),
            artifact.created_at or epoch,
        ),
    )


async def _load_preferred_downstream_profile(session, *, job_id: uuid.UUID) -> tuple[Artifact | None, dict[str, Any]]:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(_DOWNSTREAM_PROFILE_ARTIFACT_TYPES),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts = result.scalars().all()
    artifact = _select_preferred_downstream_profile_artifact(artifacts)
    if artifact is None:
        return None, {}
    return artifact, resolve_downstream_profile(artifact.data_json if isinstance(artifact.data_json, dict) else {})


def _compute_step_elapsed_seconds(step: JobStep | None, *, now: datetime | None = None) -> float | None:
    if step is None or step.started_at is None:
        return None
    end_time = step.finished_at or now or datetime.now(timezone.utc)
    return max(0.0, (end_time - step.started_at).total_seconds())


async def _resolve_source(
    job,
    tmpdir: str,
    *,
    expected_hash: str | None = None,
    debug_dir: Path | None = None,
) -> Path:
    """
    Return a local Path for the job's source file.
    If source_path is already a local file, return it directly.
    Otherwise download from S3 to tmpdir.
    """
    source_path = await _resolve_storage_reference(
        job.source_path,
        tmpdir=tmpdir,
        default_name=job.source_name,
    )
    if source_path.exists():
        _record_source_integrity(
            source_path,
            source_ref=job.source_path,
            expected_hash=expected_hash,
            debug_dir=debug_dir,
            downloaded=False,
        )
        return source_path
    raise FileNotFoundError(job.source_path)


async def _resolve_storage_reference(
    reference: str,
    *,
    tmpdir: str | None = None,
    default_name: str | None = None,
) -> Path:
    candidate = Path(str(reference or "")).expanduser()
    if candidate.exists():
        return candidate

    storage = get_storage()
    resolve_path = getattr(storage, "resolve_path", None)
    if callable(resolve_path):
        resolved = resolve_path(str(reference or ""))
        if resolved.exists():
            return resolved

    if tmpdir is None:
        raise FileNotFoundError(str(reference))

    local_name = default_name or candidate.name or "artifact.bin"
    local_path = Path(tmpdir) / local_name
    await storage.async_download_file(str(reference), local_path)
    return local_path


async def _get_job_and_step(job_id: str, step_name: str):
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job {job_id} not found")
        result = await session.execute(
            select(JobStep)
            .where(JobStep.job_id == job.id, JobStep.step_name == step_name)
        )
        step = result.scalar_one_or_none()
        if not step:
            raise ValueError(f"Step {step_name} not found for job {job_id}")
    return job, step


async def _load_latest_artifact(session, job_id: uuid.UUID, artifact_type: str) -> Artifact:
    result = await session.execute(
        select(Artifact)
        .where(Artifact.job_id == job_id, Artifact.artifact_type == artifact_type)
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifact = result.scalars().first()
    if artifact is None:
        raise ValueError(f"Artifact not found: {artifact_type}")
    return artifact


async def _load_latest_timeline(session, job_id: uuid.UUID, timeline_type: str) -> Timeline:
    result = await session.execute(
        select(Timeline)
        .where(Timeline.job_id == job_id, Timeline.timeline_type == timeline_type)
        .order_by(Timeline.version.desc(), Timeline.created_at.desc(), Timeline.id.desc())
    )
    timeline = result.scalars().first()
    if timeline is None:
        raise ValueError(f"Timeline not found: {timeline_type}")
    return timeline


async def _load_latest_optional_artifact(
    session,
    *,
    job_id: uuid.UUID,
    artifact_types: tuple[str, ...] | list[str],
) -> Artifact | None:
    result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(list(artifact_types)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    artifacts = result.scalars().all()
    if set(artifact_types).issuperset(_CONTENT_PROFILE_ARTIFACT_TYPES):
        return _select_preferred_content_profile_artifact(artifacts)
    return artifacts[0] if artifacts else None


def _serialize_glossary_terms(terms: list[GlossaryTerm]) -> list[dict[str, str | list[str] | None]]:
    return [
        {
            "scope_type": term.scope_type,
            "scope_value": term.scope_value,
            "wrong_forms": term.wrong_forms,
            "correct_form": term.correct_form,
            "category": term.category,
            "context_hint": term.context_hint,
        }
        for term in terms
    ]


def _build_effective_glossary_terms(
    *,
    glossary_terms: list[GlossaryTerm] | list[dict[str, Any]],
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
    subject_domain: str | None = None,
) -> list[dict[str, str | list[str] | None]]:
    effective_content_profile = dict(content_profile or {})
    if subject_domain and not effective_content_profile.get("subject_domain"):
        effective_content_profile["subject_domain"] = subject_domain
    serialized = [
        item
        if isinstance(item, dict)
        else {
            "scope_type": item.scope_type,
            "scope_value": item.scope_value,
            "wrong_forms": item.wrong_forms,
            "correct_form": item.correct_form,
            "category": item.category,
            "context_hint": item.context_hint,
        }
        for item in glossary_terms
    ]
    serialized = filter_scoped_glossary_terms(
        serialized,
        workflow_template=workflow_template,
        content_profile=effective_content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
    )
    builtin = resolve_builtin_glossary_terms(
        workflow_template=workflow_template,
        content_profile=effective_content_profile,
        subtitle_items=subtitle_items,
        source_name=source_name,
    )
    merged_terms = merge_glossary_terms(serialized, builtin)
    if not subject_domain:
        return merged_terms
    return [term for term in merged_terms if _glossary_term_matches_subject_domain(term, subject_domain)]


def _merge_execution_into_segments(
    segments: list[dict[str, Any]],
    execution_segments: list[dict[str, Any]] | None,
    *,
    media_key: str,
) -> list[dict[str, Any]]:
    if not segments or not execution_segments:
        return segments
    execution_by_id = {
        str(item.get("segment_id") or ""): item
        for item in execution_segments
        if str(item.get("segment_id") or "").strip()
    }
    merged: list[dict[str, Any]] = []
    for segment in segments:
        segment_copy = dict(segment)
        execution = execution_by_id.get(str(segment.get("segment_id") or ""))
        if execution:
            segment_copy[f"{media_key}_status"] = execution.get("status")
            if media_key == "audio":
                segment_copy["audio_url"] = execution.get("audio_url")
            elif media_key == "video":
                segment_copy["video_result"] = execution.get("result")
                segment_copy["video_local_path"] = execution.get("local_result_path")
        merged.append(segment_copy)
    return merged


async def _load_recent_subtitle_examples(
    session,
    *,
    workflow_template: str | None,
    exclude_job_id: uuid.UUID,
    limit: int = 160,
) -> list[dict[str, str]]:
    stmt = (
        select(SubtitleItem, Job.source_name)
        .join(Job, SubtitleItem.job_id == Job.id)
        .where(SubtitleItem.version == 1, SubtitleItem.job_id != exclude_job_id)
        .order_by(SubtitleItem.created_at.desc())
        .limit(limit)
    )
    if workflow_template:
        stmt = stmt.where(Job.workflow_template == workflow_template)

    result = await session.execute(stmt)
    return [
        {
            "text_raw": subtitle_item.text_raw or "",
            "text_norm": subtitle_item.text_norm or "",
            "text_final": subtitle_item.text_final or "",
            "source_name": source_name or "",
        }
        for subtitle_item, source_name in result.all()
    ]


async def _load_related_profile_subtitle_examples(
    session,
    *,
    content_profile: dict | None,
    exclude_job_id: uuid.UUID,
    limit: int = 160,
) -> list[dict[str, str]]:
    if not content_profile:
        return []

    artifact_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id != exclude_job_id,
            Artifact.artifact_type.in_(["content_profile_final", "content_profile", "content_profile_draft"]),
        )
        .order_by(Artifact.created_at.desc())
        .limit(120)
    )
    ranked_job_ids: list[uuid.UUID] = []
    seen_jobs: set[uuid.UUID] = set()
    for artifact in artifact_result.scalars().all():
        if artifact.job_id in seen_jobs:
            continue
        if _content_profile_similarity_score(content_profile, artifact.data_json or {}) <= 0:
            continue
        seen_jobs.add(artifact.job_id)
        ranked_job_ids.append(artifact.job_id)
        if len(ranked_job_ids) >= 10:
            break

    if not ranked_job_ids:
        return []

    subtitle_result = await session.execute(
        select(SubtitleItem, Job.source_name)
        .join(Job, SubtitleItem.job_id == Job.id)
        .where(SubtitleItem.version == 1, SubtitleItem.job_id.in_(ranked_job_ids))
        .order_by(SubtitleItem.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "text_raw": subtitle_item.text_raw or "",
            "text_norm": subtitle_item.text_norm or "",
            "text_final": subtitle_item.text_final or "",
            "source_name": source_name or "",
        }
        for subtitle_item, source_name in subtitle_result.all()
    ]


def _content_profile_similarity_score(current: dict, candidate: dict) -> int:
    score = 0
    for key, weight in (
        ("subject_brand", 4),
        ("subject_model", 5),
        ("subject_type", 3),
        ("video_theme", 2),
    ):
        left = _normalize_profile_value(current.get(key))
        right = _normalize_profile_value(candidate.get(key))
        if not left or not right:
            continue
        if left == right:
            score += weight
        elif left in right or right in left:
            score += max(1, weight - 1)
    return score


def _normalize_profile_value(value: object) -> str:
    return "".join(str(value or "").strip().upper().split())


async def run_probe(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "probe")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="下载源视频并准备探测媒体参数", progress=0.1)
        probe_heartbeat = _spawn_step_heartbeat(
            step_id=step.id,
            detail="下载源视频并准备探测媒体参数",
            progress=0.1,
        )

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = await _resolve_source(job, tmpdir)
                if probe_heartbeat is not None:
                    probe_heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await probe_heartbeat
                await _set_step_progress(session, step, detail="读取分辨率、时长、编码与文件哈希", progress=0.45)
                probe_heartbeat = _spawn_step_heartbeat(
                    step_id=step.id,
                    detail="读取分辨率、时长、编码与文件哈希",
                    progress=0.45,
                )
                meta = await probe(source_path)
                validate_media(meta)
                file_hash = _hash_file(source_path)
        finally:
            if probe_heartbeat is not None:
                probe_heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await probe_heartbeat

        job.file_hash = file_hash
        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="media_meta",
            data_json={
                "duration": meta.duration,
                "width": meta.width,
                "height": meta.height,
                "fps": meta.fps,
                "video_codec": meta.video_codec,
                "audio_codec": meta.audio_codec,
                "audio_sample_rate": meta.audio_sample_rate,
                "audio_channels": meta.audio_channels,
                "file_size": meta.file_size,
                "format_name": meta.format_name,
                "bit_rate": meta.bit_rate,
                "file_hash": file_hash,
            },
        )
        session.add(artifact)
        await _set_step_progress(session, step, detail="已写入媒体信息", progress=1.0)
        await session.commit()

        return {"duration": meta.duration, "file_hash": file_hash}


async def run_extract_audio(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "extract_audio")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="下载源视频", progress=0.1)

        with tempfile.TemporaryDirectory() as tmpdir:
            source_path = await _resolve_source(job, tmpdir)
            audio_path = Path(tmpdir) / "audio.wav"
            await _set_step_progress(session, step, detail="提取音频轨道", progress=0.45)
            try:
                await extract_audio(source_path, audio_path)
            except NoAudioStreamError:
                metadata = dict(step.metadata_ or {})
                metadata["has_audio"] = False
                metadata["audio_optional"] = True
                step.metadata_ = metadata
                await _set_step_progress(session, step, detail="源视频无音轨，已跳过音频提取", progress=1.0)
                await session.commit()
                return {"audio_key": None, "has_audio": False}

            # Upload to S3
            storage = get_storage()
            key = job_key(job_id, "audio.wav")
            await _set_step_progress(session, step, detail="上传音频到对象存储", progress=0.8)
            await storage.async_upload_file(audio_path, key)

        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="audio_wav",
            storage_path=key,
        )
        session.add(artifact)
        metadata = dict(step.metadata_ or {})
        metadata["has_audio"] = True
        step.metadata_ = metadata
        await _set_step_progress(session, step, detail="音频已就绪", progress=1.0)
        await session.commit()

        return {"audio_key": key}


async def run_transcribe(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "transcribe")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="加载音频并准备转写", progress=0.1)

        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=None,
            content_profile={},
            source_name=job.source_name,
        )
        user_memory = await load_content_profile_user_memory(
            session,
            subject_domain=subject_domain,
            strict_subject_domain=True,
        )
        recent_subtitles = []
        if subject_domain:
            recent_subtitles = await _load_recent_subtitle_examples(
                session,
                workflow_template=job.workflow_template,
                exclude_job_id=job.id,
            )
        effective_glossary_terms = _build_effective_glossary_terms(
            glossary_terms=glossary_terms,
            workflow_template=job.workflow_template,
            subtitle_items=recent_subtitles or None,
            source_name=job.source_name if subject_domain else None,
            subject_domain=subject_domain,
        )
        review_memory = build_subtitle_review_memory(
            workflow_template=job.workflow_template,
            subject_domain=subject_domain,
            glossary_terms=effective_glossary_terms,
            user_memory=user_memory,
            recent_subtitles=recent_subtitles,
            include_recent_terms=False,
            include_recent_examples=False,
        )
        settings = get_settings()
        _set_step_correction_framework_metadata(step, settings)
        transcription_prompt = build_transcription_prompt(
            source_name=job.source_name,
            workflow_template=job.workflow_template,
            review_memory=review_memory,
            dialect_profile=settings.transcription_dialect,
        )

        # Get audio artifact key when the source contains an audio stream.
        audio_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("audio_wav",),
        )
        extract_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "extract_audio")
        )
        extract_step = extract_step_result.scalar_one_or_none()
        extract_metadata = dict(extract_step.metadata_ or {}) if extract_step is not None and isinstance(extract_step.metadata_, dict) else {}
        has_audio = extract_metadata.get("has_audio")
        if audio_artifact is None and has_audio is False:
            await persist_empty_transcript_result(
                job_id=job.id,
                step=step,
                language=job.language,
                session=session,
                prompt=transcription_prompt,
                reason="no_audio_stream",
                glossary_terms=effective_glossary_terms,
                review_memory=review_memory,
            )
            await _set_step_progress(session, step, detail="源视频无音轨，已跳过转写", progress=1.0)
            await session.commit()
            return {"segment_count": 0, "duration": 0.0, "has_audio": False}
        if audio_artifact is None:
            raise ValueError("Artifact not found: audio_wav")

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = await _resolve_storage_reference(
                str(audio_artifact.storage_path or ""),
                tmpdir=tmpdir,
                default_name="audio.wav",
            )
            await _set_step_progress(session, step, detail=f"加载 {job.language} 转写模型", progress=0.2)

            progress_loop = asyncio.get_running_loop()
            last_progress = {"progress": 0.0, "ts": 0.0}
            accept_progress_updates = {"value": True}
            pending_progress_updates = []
            heartbeat_state = {
                "detail": f"使用 {job.language} 模型执行转写",
                "progress": 0.25,
            }
            transcribe_heartbeat: asyncio.Task[None] | None = None

            async def _persist_transcribe_progress(progress: float, detail: str) -> None:
                progress_factory = get_session_factory()
                async with progress_factory() as progress_session:
                    step_ref = await progress_session.get(JobStep, step.id)
                    if step_ref is None:
                        return
                    await _set_step_progress(progress_session, step_ref, detail=detail, progress=progress)

            async def _transcribe_heartbeat_loop() -> None:
                interval_sec = max(5, int(getattr(settings, "step_heartbeat_interval_sec", 20) or 20))
                while True:
                    await asyncio.sleep(interval_sec)
                    async with get_session_factory()() as heartbeat_session:
                        step_ref = await heartbeat_session.get(JobStep, step.id)
                        if step_ref is None or step_ref.status != "running":
                            return
                        await _set_step_progress(
                            heartbeat_session,
                            step_ref,
                            detail=str(heartbeat_state["detail"]),
                            progress=float(heartbeat_state["progress"]),
                        )

            def _on_transcribe_progress(payload: dict) -> None:
                if not accept_progress_updates["value"]:
                    return
                total_duration = float(payload.get("total_duration") or 0.0)
                segment_end = float(payload.get("segment_end") or 0.0)
                segment_count = int(payload.get("segment_count") or 0)
                raw_progress = float(payload.get("progress") or 0.0)
                scaled_progress = 0.25 + (raw_progress * 0.7)
                now = time.monotonic()
                if scaled_progress - last_progress["progress"] < 0.03 and now - last_progress["ts"] < 1.5:
                    return
                last_progress["progress"] = scaled_progress
                last_progress["ts"] = now
                detail = f"已转写 {segment_count} 段，覆盖 {segment_end:.0f}s / {total_duration:.0f}s"
                heartbeat_state["detail"] = detail
                heartbeat_state["progress"] = scaled_progress
                future = asyncio.run_coroutine_threadsafe(
                    _persist_transcribe_progress(scaled_progress, detail),
                    progress_loop,
                )
                pending_progress_updates.append(future)

            await _set_step_progress(session, step, detail=f"使用 {job.language} 模型执行转写", progress=0.25)
            transcribe_heartbeat = asyncio.create_task(_transcribe_heartbeat_loop())
            transcribe_timeout_sec = _resolve_transcribe_runtime_timeout_seconds(settings)
            try:
                result = await asyncio.wait_for(
                    transcribe_audio(
                        job.id,
                        step,
                        audio_path,
                        job.language,
                        session,
                        prompt=transcription_prompt,
                        progress_callback=_on_transcribe_progress,
                        glossary_terms=effective_glossary_terms,
                        review_memory=review_memory,
                    ),
                    timeout=transcribe_timeout_sec,
                )
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Transcribe step timed out after {transcribe_timeout_sec:.1f}s"
                ) from exc
            finally:
                accept_progress_updates["value"] = False
                if transcribe_heartbeat is not None:
                    transcribe_heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await transcribe_heartbeat
                if pending_progress_updates:
                    await asyncio.gather(
                        *(asyncio.wrap_future(future) for future in pending_progress_updates),
                        return_exceptions=True,
                    )

        await _set_step_progress(session, step, detail=f"转写完成，共 {len(result.segments)} 段", progress=1.0)
        await session.commit()
        return {"segment_count": len(result.segments), "duration": result.duration}


async def run_subtitle_postprocess(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "subtitle_postprocess")
        )
        step = step_result.scalar_one()
        started = time.perf_counter()
        await _set_step_progress(session, step, detail="加载转写结果并切分字幕", progress=0.25)

        # Load transcript segments
        seg_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        segments = seg_result.scalars().all()
        load_elapsed = time.perf_counter() - started

        media_meta = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
        media_meta_json = media_meta.data_json if media_meta and isinstance(media_meta.data_json, dict) else {}
        split_profile = _resolve_subtitle_split_profile(
            width=media_meta_json.get("width"),
            height=media_meta_json.get("height"),
        )

        split_started = time.perf_counter()
        entries = split_into_subtitles(
            segments,
            max_chars=int(split_profile["max_chars"]),
            max_duration=float(split_profile["max_duration"]),
        )
        split_elapsed = time.perf_counter() - split_started
        await _set_step_progress(
            session,
            step,
            detail=(
                f"按{split_profile['orientation']}节奏生成字幕 {len(entries)} 条，"
                f"每条最多 {int(split_profile['max_chars'])} 字 / {float(split_profile['max_duration']):.1f}s"
            ),
            progress=0.7,
        )
        save_started = time.perf_counter()
        items = await save_subtitle_items(job.id, entries, session)
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=[
                {
                    "text_raw": item.text_raw,
                    "text_norm": item.text_norm,
                    "text_final": item.text_final,
                }
                for item in items
            ],
            content_profile=content_profile,
            source_name=job.source_name,
        )
        user_memory = await load_content_profile_user_memory(
            session,
            subject_domain=subject_domain,
        )
        effective_glossary_terms = _build_effective_glossary_terms(
            glossary_terms=glossary_terms,
            workflow_template=job.workflow_template,
            content_profile=content_profile,
            subtitle_items=[
                {
                    "text_raw": item.text_raw,
                    "text_norm": item.text_norm,
                    "text_final": item.text_final,
                    "source_name": job.source_name,
                }
                for item in items
            ],
            source_name=job.source_name,
            subject_domain=subject_domain,
        )
        review_memory = build_subtitle_review_memory(
            workflow_template=job.workflow_template,
            subject_domain=subject_domain,
            glossary_terms=effective_glossary_terms,
            user_memory=user_memory,
            recent_subtitles=[
                {
                    "text_raw": item.text_raw,
                    "text_norm": item.text_norm,
                    "text_final": item.text_final,
                    "source_name": job.source_name,
                }
                for item in items
            ],
            content_profile=content_profile,
            include_recent_terms=False,
            include_recent_examples=False,
        )
        polished_count = await polish_subtitle_items(
            items,
            content_profile=content_profile or {"workflow_template": job.workflow_template or "unboxing_standard"},
            glossary_terms=effective_glossary_terms,
            review_memory=review_memory,
            allow_llm=False,
        )
        save_elapsed = time.perf_counter() - save_started
        total_elapsed = time.perf_counter() - started
        await _set_step_progress(
            session,
            step,
            detail=f"字幕后处理完成，{len(segments)} 段 -> {len(items)} 条，纠正 {polished_count} 条，用时 {total_elapsed:.1f}s",
            progress=1.0,
        )
        await session.commit()
        logger.info(
            "subtitle_postprocess finished job=%s segments=%s subtitles=%s elapsed=%.2fs load=%.2fs split=%.2fs save=%.2fs",
            job_id,
            len(segments),
            len(items),
            total_elapsed,
            load_elapsed,
            split_elapsed,
            save_elapsed,
        )

        return {
            "segment_count": len(segments),
            "subtitle_count": len(items),
            "polished_count": polished_count,
            "subtitle_profile": split_profile,
            "elapsed_seconds": round(total_elapsed, 3),
            "load_seconds": round(load_elapsed, 3),
            "split_seconds": round(split_elapsed, 3),
            "save_seconds": round(save_elapsed, 3),
        }


async def run_content_profile(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        settings = get_settings()
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "content_profile")
        )
        step = step_result.scalar_one()
        _set_step_correction_framework_metadata(step, settings)
        await _set_step_progress(session, step, detail="整理字幕上下文并识别视频类型", progress=0.15)

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
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
        transcript_excerpt = build_transcript_excerpt(subtitle_dicts)
        subtitle_digest = digest_payload(
            [
                {
                    "index": item["index"],
                    "start_time": item["start_time"],
                    "end_time": item["end_time"],
                    "text_raw": item["text_raw"],
                    "text_norm": item["text_norm"],
                    "text_final": item["text_final"],
                }
                for item in subtitle_dicts
            ]
        )
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=subtitle_dicts,
            content_profile={},
            source_name=job.source_name,
        )
        effective_glossary_terms = _build_effective_glossary_terms(
            glossary_terms=glossary_terms,
            workflow_template=job.workflow_template,
            subtitle_items=subtitle_dicts,
            source_name=job.source_name,
            subject_domain=subject_domain,
        )
        user_memory = await load_content_profile_user_memory(
            session,
            subject_domain=subject_domain,
        )
        include_research = bool(getattr(settings, "research_verifier_enabled", False))
        packaging_config = (list_packaging_assets().get("config") or {})
        source_context = dict(step.metadata_.get("source_context") or {}) if isinstance(step.metadata_, dict) else {}
        if not bool(source_context.get("allow_related_profiles")):
            source_context.pop("related_profiles", None)
            source_context.pop("adjacent_profiles", None)
        related_source_context = await _load_related_profile_source_context(session, job=job, source_context=source_context)
        if bool(source_context.get("allow_related_profiles")) and related_source_context:
            existing_related = [
                dict(item)
                for item in (source_context.get("related_profiles") or [])
                if isinstance(item, dict)
            ]
            existing_names = {str(item.get("source_name") or "").strip() for item in existing_related}
            for item in related_source_context.get("related_profiles") or []:
                source_name = str(item.get("source_name") or "").strip()
                if source_name and source_name not in existing_names:
                    existing_related.append(dict(item))
                    existing_names.add(source_name)
            if existing_related:
                source_context = {
                    **source_context,
                    "related_profiles": existing_related[:3],
                }
        # Reruns must re-infer from the current transcript and frames instead of
        # recycling a stale same-job profile artifact.
        seeded_profile: dict[str, Any] = {}
        copy_style = str(packaging_config.get("copy_style") or "attention_grabbing")
        infer_cache_namespace = "content_profile.infer"
        infer_cache_fingerprint = build_content_profile_cache_fingerprint(
            source_name=job.source_name,
            source_file_hash=job.file_hash,
            workflow_template=job.workflow_template,
            transcript_excerpt=transcript_excerpt,
            subtitle_digest=subtitle_digest,
            glossary_terms=effective_glossary_terms,
            user_memory=user_memory,
            include_research=include_research,
            copy_style=copy_style,
            source_context=source_context,
        )
        infer_cache_key = build_cache_key(infer_cache_namespace, infer_cache_fingerprint)
        cached_infer_entry = load_cached_entry(infer_cache_namespace, infer_cache_key)

        if cached_infer_entry:
            _set_step_cache_metadata(
                step,
                "content_profile",
                build_cache_metadata(
                    infer_cache_namespace,
                    infer_cache_key,
                    hit=True,
                    usage_baseline=cached_infer_entry.get("usage_baseline"),
                ),
            )
            content_profile = dict(cached_infer_entry.get("result") or {})
        elif seeded_profile:
            await _set_step_progress(session, step, detail="基于前置校正结果补强内容画像", progress=0.55)
            seeded_profile["copy_style"] = copy_style
            cache_namespace = "content_profile.enrich"
            cache_fingerprint = build_content_profile_cache_fingerprint(
                source_name=job.source_name,
                source_file_hash=job.file_hash,
                workflow_template=job.workflow_template,
                transcript_excerpt=transcript_excerpt,
                subtitle_digest=subtitle_digest,
                glossary_terms=effective_glossary_terms,
                user_memory=user_memory,
                include_research=include_research,
                copy_style=copy_style,
                seeded_profile=seeded_profile,
            )
            cache_key = build_cache_key(cache_namespace, cache_fingerprint)
            cached_profile_entry = load_cached_entry(cache_namespace, cache_key)
            _set_step_cache_metadata(
                step,
                "content_profile",
                build_cache_metadata(
                    cache_namespace,
                    cache_key,
                    hit=bool(cached_profile_entry),
                    usage_baseline=(cached_profile_entry or {}).get("usage_baseline"),
                ),
            )
            if cached_profile_entry:
                content_profile = dict(cached_profile_entry.get("result") or {})
            else:
                usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
                with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                    content_profile = await enrich_content_profile(
                        profile=seeded_profile,
                        source_name=job.source_name,
                        workflow_template=job.workflow_template,
                        transcript_excerpt=transcript_excerpt,
                        subtitle_items=subtitle_dicts,
                        glossary_terms=effective_glossary_terms,
                        user_memory=user_memory,
                        include_research=include_research,
                    )
                usage_after = await _read_persisted_step_usage_snapshot(step.id if step else None)
                usage_baseline = _usage_delta(usage_after, usage_before)
                save_cached_json(
                    cache_namespace,
                    cache_key,
                    fingerprint=cache_fingerprint,
                    result=content_profile,
                    usage_baseline=usage_baseline,
                )
        else:
            _set_step_cache_metadata(
                step,
                "content_profile",
                build_cache_metadata(infer_cache_namespace, infer_cache_key, hit=False),
            )
            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = await _resolve_source(job, tmpdir, expected_hash=job.file_hash)
                await _set_step_progress(session, step, detail="抽取画面并分析主题、主体与处理模板", progress=0.55)
                usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
                with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                    content_profile = await infer_content_profile(
                        source_path=source_path,
                        source_name=job.source_name,
                        subtitle_items=subtitle_dicts,
                        workflow_template=job.workflow_template,
                        user_memory=user_memory,
                        glossary_terms=effective_glossary_terms,
                        include_research=include_research,
                        copy_style=copy_style,
                        source_context=source_context,
                    )
                usage_after = await _read_persisted_step_usage_snapshot(step.id if step else None)
                usage_baseline = _usage_delta(usage_after, usage_before)
                save_cached_json(
                    infer_cache_namespace,
                    infer_cache_key,
                    fingerprint=infer_cache_fingerprint,
                    result=content_profile,
                    usage_baseline=usage_baseline,
                )
                enrich_cache_namespace = "content_profile.enrich"
                enrich_cache_fingerprint = build_content_profile_cache_fingerprint(
                    source_name=job.source_name,
                    source_file_hash=job.file_hash,
                    workflow_template=job.workflow_template,
                    transcript_excerpt=transcript_excerpt,
                    subtitle_digest=subtitle_digest,
                    glossary_terms=effective_glossary_terms,
                    user_memory=user_memory,
                    include_research=include_research,
                    copy_style=copy_style,
                    seeded_profile=content_profile,
                )
                enrich_cache_key = build_cache_key(enrich_cache_namespace, enrich_cache_fingerprint)
                usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
                with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                    content_profile = await enrich_content_profile(
                        profile=content_profile,
                        source_name=job.source_name,
                        workflow_template=job.workflow_template,
                        transcript_excerpt=transcript_excerpt,
                        subtitle_items=subtitle_dicts,
                        glossary_terms=effective_glossary_terms,
                        user_memory=user_memory,
                        include_research=include_research,
                    )
                usage_after = await _read_persisted_step_usage_snapshot(step.id if step else None)
                usage_baseline = _usage_delta(usage_after, usage_before)
                save_cached_json(
                    enrich_cache_namespace,
                    enrich_cache_key,
                    fingerprint=enrich_cache_fingerprint,
                    result=content_profile,
                    usage_baseline=usage_baseline,
                )
        content_profile = apply_identity_review_guard(
            content_profile,
            subtitle_items=subtitle_dicts,
            user_memory=user_memory,
            glossary_terms=effective_glossary_terms,
            source_name=job.source_name,
        )
        source_context_description = str(source_context.get("video_description") or "").strip()
        resolved_source_context_feedback: dict[str, Any] = {}
        if source_context_description:
            source_context_verification_bundle = await build_review_feedback_verification_bundle(
                draft_profile=content_profile,
                proposed_feedback=None,
                session=session,
            )
            resolved_source_context_feedback = await resolve_content_profile_review_feedback(
                draft_profile=content_profile,
                source_name=job.source_name,
                review_feedback=source_context_description,
                proposed_feedback=None,
                reviewed_subtitle_excerpt=transcript_excerpt,
                accepted_corrections=[],
                verification_bundle=source_context_verification_bundle,
            )
            if resolved_source_context_feedback:
                content_profile = await apply_content_profile_feedback(
                    draft_profile=content_profile,
                    source_name=job.source_name,
                    workflow_template=job.workflow_template,
                    user_feedback=resolved_source_context_feedback,
                    reviewed_subtitle_excerpt=transcript_excerpt,
                    accepted_corrections=[],
                )
        if source_context:
            content_profile["source_context"] = {
                **source_context,
                **({"resolved_feedback": dict(resolved_source_context_feedback)} if resolved_source_context_feedback else {}),
            }
        manual_review_feedback = dict(step.metadata_.get("review_user_feedback") or {}) if isinstance(step.metadata_, dict) else {}
        review_feedback_note = str(step.metadata_.get("review_feedback") or "").strip() if isinstance(step.metadata_, dict) else ""
        resolved_manual_review_feedback: dict[str, Any] = {}
        if manual_review_feedback:
            review_feedback_verification_bundle = await build_review_feedback_verification_bundle(
                draft_profile=content_profile,
                proposed_feedback=manual_review_feedback,
                session=session,
            )
            resolved_manual_review_feedback = await resolve_content_profile_review_feedback(
                draft_profile=content_profile,
                source_name=job.source_name,
                review_feedback=review_feedback_note,
                proposed_feedback=manual_review_feedback,
                reviewed_subtitle_excerpt=transcript_excerpt,
                accepted_corrections=[],
                verification_bundle=review_feedback_verification_bundle,
            )
        if resolved_manual_review_feedback:
            content_profile = await apply_content_profile_feedback(
                draft_profile=content_profile,
                source_name=job.source_name,
                workflow_template=job.workflow_template,
                user_feedback=resolved_manual_review_feedback,
                reviewed_subtitle_excerpt=transcript_excerpt,
                accepted_corrections=[],
            )
            content_profile["review_user_feedback"] = dict(manual_review_feedback)
            content_profile["resolved_review_user_feedback"] = dict(resolved_manual_review_feedback)
        content_profile["creative_profile"] = _job_creative_profile(job)

        auto_review_enabled = bool(settings.auto_confirm_content_profile) and auto_review_mode_enabled(
            getattr(job, "enhancement_modes", [])
        )
        automation = assess_content_profile_automation(
            content_profile,
            subtitle_items=subtitle_dicts,
            user_memory=user_memory,
            glossary_terms=effective_glossary_terms,
            source_name=job.source_name,
            auto_confirm_enabled=auto_review_enabled,
            threshold=settings.content_profile_review_threshold,
        )
        content_profile["automation_review"] = automation
        ocr_profile = None
        if bool(getattr(settings, "ocr_enabled", False)):
            candidate_ocr_profile = content_profile.pop("ocr_profile", None)
            if isinstance(candidate_ocr_profile, dict):
                ocr_profile = candidate_ocr_profile
                session.add(
                    Artifact(
                        job_id=job.id,
                        step_id=step.id,
                        artifact_type=ARTIFACT_TYPE_CONTENT_PROFILE_OCR,
                        data_json=ocr_profile,
                    )
                )
        artifact = Artifact(
            job_id=job.id,
            step_id=step.id,
            artifact_type="content_profile_draft",
            data_json=content_profile,
        )
        session.add(artifact)
        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one_or_none()

        auto_confirmed = bool(automation.get("auto_confirm"))
        context_source_profile: dict[str, Any] = dict(content_profile)
        if resolved_manual_review_feedback:
            now = datetime.now(timezone.utc)
            final_profile = dict(content_profile)
            final_profile["review_mode"] = "manual_confirmed"
            context_source_profile = dict(final_profile)
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=review_step.id if review_step else None,
                    artifact_type="content_profile_final",
                    data_json=final_profile,
                )
            )
            if review_step is not None:
                review_step.status = "done"
                review_step.started_at = review_step.started_at or now
                review_step.finished_at = now
                review_step.error_message = None
                review_step.metadata_ = {
                    **(review_step.metadata_ or {}),
                    "label": STEP_LABELS.get("summary_review", "summary_review"),
                    "detail": "已应用成片审核修正并确认内容摘要，继续后续流程。",
                    "progress": 1.0,
                    "updated_at": now.isoformat(),
                    "auto_confirmed": False,
                    "manual_confirmed": True,
                    "review_user_feedback": dict(manual_review_feedback),
                    "resolved_review_user_feedback": dict(resolved_manual_review_feedback),
                }
            job.status = "processing"
        elif auto_confirmed:
            now = datetime.now(timezone.utc)
            final_profile = dict(content_profile)
            final_profile["review_mode"] = "auto_confirmed"
            context_source_profile = dict(final_profile)
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=review_step.id if review_step else None,
                    artifact_type="content_profile_final",
                    data_json=final_profile,
                )
            )
            if review_step is not None:
                review_step.status = "done"
                review_step.started_at = review_step.started_at or now
                review_step.finished_at = now
                review_step.error_message = None
                review_step.metadata_ = {
                    **(review_step.metadata_ or {}),
                    "label": STEP_LABELS.get("summary_review", "summary_review"),
                    "detail": f"已自动确认内容摘要（置信度 {automation['score']:.2f}）",
                    "progress": 1.0,
                    "updated_at": now.isoformat(),
                    "auto_confirmed": True,
                    "confidence_score": automation["score"],
                    "threshold": automation["threshold"],
                    "review_reasons": automation["review_reasons"],
                    "blocking_reasons": automation["blocking_reasons"],
                }
            job.status = "processing"
        elif review_step is not None and bool((automation.get("identity_review") or {}).get("required")):
            now = datetime.now(timezone.utc)
            review_step.metadata_ = {
                **(review_step.metadata_ or {}),
                "label": STEP_LABELS.get("summary_review", "summary_review"),
                "detail": str((automation.get("identity_review") or {}).get("reason") or "内容摘要待人工确认"),
                "progress": 0.0,
                "updated_at": now.isoformat(),
                "auto_confirmed": False,
                "identity_review": automation.get("identity_review"),
                "review_reasons": automation["review_reasons"],
                "blocking_reasons": automation["blocking_reasons"],
            }

        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="downstream_context",
                data_json=build_downstream_context(context_source_profile),
            )
        )

        subject = " / ".join(
            part for part in [
                content_profile.get("subject_type"),
                content_profile.get("video_theme"),
            ] if part
        ).strip()
        if resolved_manual_review_feedback:
            detail = f"已应用人工修正后的内容摘要：{subject or '人工修正完成'}"
        elif auto_confirmed:
            detail = f"已自动确认内容摘要：{subject or '自动识别完成'}"
        else:
            if manual_review_feedback and review_step is not None:
                review_step.status = "pending"
                review_step.finished_at = None
                review_step.error_message = None
                review_step.metadata_ = {
                    **(review_step.metadata_ or {}),
                    "label": STEP_LABELS.get("summary_review", "summary_review"),
                    "detail": "成片审核修正尚未确认到当前主体，等待人工继续确认。",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "progress": 0.0,
                    "auto_confirmed": False,
                    "manual_confirmed": False,
                    "review_user_feedback": dict(manual_review_feedback),
                    "resolved_review_user_feedback": {},
                }
            detail = f"已生成内容摘要：{subject or '待人工确认'}"
        await _set_step_progress(session, step, detail=detail, progress=1.0)
        await session.commit()
        if not auto_confirmed and not resolved_manual_review_feedback:
            try:
                await get_telegram_review_bot_service().notify_content_profile_review(job.id)
            except Exception:
                logger.exception("Failed to send Telegram content profile review for job %s", job.id)

        return {
            "subject_brand": content_profile.get("subject_brand"),
            "subject_model": content_profile.get("subject_model"),
            "subject_type": content_profile.get("subject_type"),
            "video_theme": content_profile.get("video_theme"),
            "auto_confirmed": auto_confirmed,
            "automation_score": automation["score"],
        }


async def run_glossary_review(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        settings = get_settings()
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "glossary_review")
        )
        step = step_result.scalar_one()
        _set_step_correction_framework_metadata(step, settings)
        await _set_step_progress(session, step, detail="应用术语词表并收集字幕上下文", progress=0.15)

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()

        subtitle_dicts = [
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
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        if not content_profile:
            profile_result = await session.execute(
                select(Artifact)
                .where(
                    Artifact.job_id == job.id,
                    Artifact.artifact_type.in_(["content_profile_final", "content_profile_draft"]),
                )
                .order_by(Artifact.created_at.desc())
            )
            profile_artifacts = profile_result.scalars().all()
            content_profile = profile_artifacts[0].data_json if profile_artifacts else None
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=subtitle_dicts,
            content_profile=content_profile or {},
            source_name=job.source_name,
        )
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
        effective_glossary_terms = _build_effective_glossary_terms(
            glossary_terms=glossary_terms,
            workflow_template=job.workflow_template,
            content_profile=content_profile or {},
            subtitle_items=subtitle_dicts,
            source_name=job.source_name,
            subject_domain=subject_domain,
        )
        corrections = await apply_glossary_corrections(
            job.id,
            subtitle_items,
            session,
            glossary_terms=effective_glossary_terms,
        )
        auto_accepted_corrections = sum(
            1 for item in corrections if item.auto_applied or item.human_decision == "accepted"
        )
        pending_corrections = sum(
            1 for item in corrections if item.human_decision not in {"accepted", "rejected"}
        )
        await _set_step_progress(
            session,
            step,
            detail=f"已识别 {len(corrections)} 处术语纠错候选，自动接受 {auto_accepted_corrections} 条",
            progress=0.45,
        )
        user_memory = await load_content_profile_user_memory(
            session,
            subject_domain=subject_domain,
        )
        include_research = bool(getattr(settings, "research_verifier_enabled", False))
        if not content_profile:
            with tempfile.TemporaryDirectory() as tmpdir:
                source_path = await _resolve_source(job, tmpdir, expected_hash=job.file_hash)
                packaging_config = (list_packaging_assets().get("config") or {})
                with track_step_usage(job_id=job.id, step_id=step.id, step_name="glossary_review"):
                    content_profile = await infer_content_profile(
                        source_path=source_path,
                        source_name=job.source_name,
                        subtitle_items=subtitle_dicts,
                        workflow_template=job.workflow_template,
                        user_memory=user_memory,
                        glossary_terms=effective_glossary_terms,
                        include_research=include_research,
                        copy_style=str(packaging_config.get("copy_style") or "attention_grabbing"),
                    )
        else:
            packaging_config = (list_packaging_assets().get("config") or {})
            content_profile["copy_style"] = str(
                packaging_config.get("copy_style")
                or content_profile.get("copy_style")
                or "attention_grabbing"
            )
            with track_step_usage(job_id=job.id, step_id=step.id, step_name="glossary_review"):
                content_profile = await enrich_content_profile(
                    profile=content_profile,
                    source_name=job.source_name,
                    workflow_template=job.workflow_template,
                    transcript_excerpt=str(content_profile.get("transcript_excerpt") or ""),
                    subtitle_items=subtitle_dicts,
                    glossary_terms=effective_glossary_terms,
                    user_memory=user_memory,
                    include_research=include_research,
                )
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=subtitle_dicts,
            content_profile=content_profile,
            source_name=job.source_name,
        )
        effective_glossary_terms = _build_effective_glossary_terms(
            glossary_terms=glossary_terms,
            workflow_template=job.workflow_template,
            content_profile=content_profile,
            subtitle_items=subtitle_dicts,
            source_name=job.source_name,
            subject_domain=subject_domain,
        )
        content_profile["creative_profile"] = _job_creative_profile(job)
        recent_subtitles = await _load_recent_subtitle_examples(
            session,
            workflow_template=job.workflow_template,
            exclude_job_id=job.id,
        )
        related_subtitles = await _load_related_profile_subtitle_examples(
            session,
            content_profile=content_profile,
            exclude_job_id=job.id,
        )

        polished_count = await polish_subtitle_items(
            subtitle_items,
            content_profile=content_profile,
            glossary_terms=effective_glossary_terms,
            review_memory=build_subtitle_review_memory(
                workflow_template=job.workflow_template,
                subject_domain=subject_domain,
                glossary_terms=effective_glossary_terms,
                user_memory=user_memory,
                recent_subtitles=subtitle_dicts + related_subtitles + recent_subtitles,
                content_profile=content_profile,
                include_recent_terms=False,
                include_recent_examples=False,
            ),
            allow_llm=False,
        )

        artifact = Artifact(
            job_id=job.id,
            step_id=None,
            artifact_type="content_profile",
            data_json=content_profile,
        )
        session.add(artifact)
        session.add(
            Artifact(
                job_id=job.id,
                step_id=None,
                artifact_type="downstream_context",
                data_json=build_downstream_context(content_profile),
            )
        )
        await _set_step_progress(
            session,
            step,
            detail=(
                f"字幕润色完成，更新 {polished_count} 条；"
                f"术语自动接受 {auto_accepted_corrections} 条，待确认 {pending_corrections} 条"
            ),
            progress=1.0,
        )
        await session.commit()
        if pending_corrections > 0:
            try:
                await get_telegram_review_bot_service().notify_subtitle_review(job.id)
            except Exception:
                logger.exception("Failed to send Telegram subtitle review for job %s", job.id)

        return {
            "correction_count": len(corrections),
            "auto_accepted_correction_count": auto_accepted_corrections,
            "pending_correction_count": pending_corrections,
            "polished_count": polished_count,
            "workflow_template": content_profile.get("workflow_template"),
            "subject": " ".join(
                part for part in [
                    content_profile.get("subject_brand"),
                    content_profile.get("subject_model"),
                ] if part
            ).strip(),
        }


async def run_subtitle_translation(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "subtitle_translation")
        )
        step = step_result.scalar_one()

        if not multilingual_translation_mode_enabled(getattr(job, "enhancement_modes", [])):
            await _set_step_progress(session, step, detail="未启用多语言翻译模式，跳过。", progress=1.0)
            await session.commit()
            return {"enabled": False, "skipped": True}

        await _set_step_progress(session, step, detail="读取校对后的字幕，准备生成英文译文", progress=0.18)
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
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
        preferred_ui_language = str(get_settings().preferred_ui_language or "zh-CN")
        source_language = detect_subtitle_language(subtitle_dicts)
        target_language = resolve_translation_target_language(
            source_language=source_language,
            target_language=None,
            target_language_mode="auto",
            preferred_ui_language=preferred_ui_language,
        )
        if languages_equivalent(source_language, target_language):
            await _set_step_progress(
                session,
                step,
                detail=f"源字幕语言与目标语言一致（{source_language} -> {target_language}），跳过翻译。",
                progress=1.0,
            )
            await session.commit()
            return {
                "enabled": True,
                "skipped": True,
                "reason": "same_language",
                "source_language": source_language,
                "target_language_mode": "auto",
                "target_language": target_language,
                "translated_count": 0,
            }

        await _set_step_progress(
            session,
            step,
            detail=f"翻译校对后的字幕（{source_language} -> {target_language}）",
            progress=0.72,
        )
        with track_step_usage(job_id=job.id, step_id=step.id, step_name="subtitle_translation"):
            translation = await translate_subtitle_items(
                subtitle_dicts,
                target_language_mode="auto",
                preferred_ui_language=preferred_ui_language,
            )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="subtitle_translation",
                data_json=translation,
            )
        )
        await _set_step_progress(
            session,
            step,
            detail=f"已生成英文字幕译文，共 {translation.get('item_count') or 0} 条。",
            progress=1.0,
        )
        await session.commit()
        return {
            "enabled": True,
            "source_language": translation.get("source_language"),
            "target_language_mode": translation.get("target_language_mode"),
            "target_language": translation.get("target_language"),
            "translated_count": translation.get("item_count"),
        }


async def run_ai_director(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "ai_director")
        )
        step = step_result.scalar_one()

        if not ai_director_mode_enabled(getattr(job, "enhancement_modes", [])):
            await _set_step_progress(session, step, detail="未启用 AI 导演模式，跳过。", progress=1.0)
            await session.commit()
            return {"enabled": False, "skipped": True}

        await _set_step_progress(session, step, detail="加载字幕与内容画像，准备导演分析", progress=0.18)
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
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
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        await _set_step_progress(session, step, detail="生成导演建议稿与重配音计划", progress=0.68)
        with track_step_usage(job_id=job.id, step_id=step.id, step_name="ai_director"):
            plan = await build_ai_director_plan(
                job_id=str(job.id),
                source_name=job.source_name,
                subtitle_items=subtitle_dicts,
                content_profile=content_profile,
            )
        voice_execution: dict[str, Any] | None = None
        voice_segments = list(plan.get("voiceover_segments") or [])
        if voice_segments:
            try:
                await _set_step_progress(session, step, detail="上传参考音频并执行 AI 导演重配音", progress=0.84)
                audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")
                with tempfile.TemporaryDirectory() as tmpdir:
                    reference_audio_path = await _resolve_storage_reference(
                        str(audio_artifact.storage_path or ""),
                        tmpdir=tmpdir,
                        default_name="director_reference.wav",
                    )
                    voice_execution = await asyncio.to_thread(
                        get_voice_provider().execute_dubbing,
                        job_id=str(job.id),
                        request=dict(plan.get("dubbing_request") or {}),
                        reference_audio_path=reference_audio_path,
                    )
                plan["dubbing_execution"] = voice_execution
                plan["voiceover_segments"] = _merge_execution_into_segments(
                    voice_segments,
                    voice_execution.get("segments") if voice_execution else None,
                    media_key="audio",
                )
            except Exception as exc:
                plan["dubbing_execution"] = {
                    "provider": plan.get("voice_provider"),
                    "status": "failed",
                    "error": str(exc),
                }
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="ai_director_plan",
                data_json=plan,
            )
        )
        await _set_step_progress(session, step, detail="AI 导演建议已生成", progress=1.0)
        await session.commit()
        return {
            "enabled": True,
            "voiceover_segment_count": len(plan.get("voiceover_segments") or []),
            "voice_provider": plan.get("voice_provider"),
            "dubbing_status": (voice_execution or plan.get("dubbing_execution") or {}).get("status"),
        }


async def run_avatar_commentary(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "avatar_commentary")
        )
        step = step_result.scalar_one()

        if not avatar_mode_enabled(getattr(job, "enhancement_modes", [])):
            await _set_step_progress(session, step, detail="未启用数字人解说模式，跳过。", progress=1.0)
            await session.commit()
            return {"enabled": False, "skipped": True}

        await _set_step_progress(session, step, detail="整理解说脚本和时间轴插槽", progress=0.2)
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
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
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        director_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("ai_director_plan",),
        )
        ai_director_plan = director_artifact.data_json if director_artifact and director_artifact.data_json else {}

        await _set_step_progress(session, step, detail="生成数字人解说分镜与 provider 请求体", progress=0.72)
        plan = build_avatar_commentary_plan(
            job_id=str(job.id),
            source_name=job.source_name,
            subtitle_items=subtitle_dicts,
            content_profile=content_profile,
            ai_director_plan=ai_director_plan,
        )
        packaging_config = dict((list_packaging_assets().get("config") or {}))
        voice_execution: dict[str, Any] | None = None
        render_execution: dict[str, Any] | None = None
        render_executed_in_mode = False
        avatar_segments = list(plan.get("segments") or [])
        if plan.get("mode") == "full_track_audio_passthrough":
            avatar_profile = _select_default_avatar_profile()
            avatar_video_path = _pick_avatar_profile_speaking_video_path(avatar_profile)
            if avatar_profile and avatar_video_path:
                plan["integration_mode"] = "picture_in_picture"
                plan["avatar_profile_id"] = str(avatar_profile.get("id") or "")
                plan["avatar_profile_name"] = str(avatar_profile.get("display_name") or "")
                plan["presenter_id"] = str(avatar_video_path)
                plan["overlay_position"] = str(packaging_config.get("avatar_overlay_position") or "bottom_right")
                plan["overlay_scale"] = float(
                    packaging_config.get("avatar_overlay_scale") or plan.get("overlay_scale") or 0.22
                )
                plan["overlay_corner_radius"] = int(packaging_config.get("avatar_overlay_corner_radius") or 0)
                plan["overlay_border_width"] = int(packaging_config.get("avatar_overlay_border_width") or 0)
                plan["overlay_border_color"] = str(packaging_config.get("avatar_overlay_border_color") or "#F4E4B8")
                plan["overlay_margin"] = 28
                render_request = dict(plan.get("render_request") or {})
                render_request["presenter_id"] = str(avatar_video_path)
                render_request["layout_template"] = plan.get("layout_template")
                plan["render_request"] = render_request
            plan["dubbing_execution"] = {
                "provider": "passthrough",
                "status": "skipped",
                "reason": "full_track_audio_passthrough",
            }
            plan["render_execution"] = {
                "provider": plan.get("provider"),
                "status": "deferred_to_render",
                "reason": "full_track_audio_passthrough",
            }
        elif plan.get("mode") == "segmented_audio_passthrough" and avatar_segments:
            audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")
            avatar_profile = _select_default_avatar_profile()
            avatar_video_path = _pick_avatar_profile_speaking_video_path(avatar_profile)
            if avatar_profile and avatar_video_path:
                plan["integration_mode"] = "picture_in_picture"
                plan["avatar_profile_id"] = str(avatar_profile.get("id") or "")
                plan["avatar_profile_name"] = str(avatar_profile.get("display_name") or "")
                plan["presenter_id"] = str(avatar_video_path)
                plan["overlay_position"] = str(packaging_config.get("avatar_overlay_position") or "bottom_right")
                plan["overlay_scale"] = float(
                    packaging_config.get("avatar_overlay_scale") or plan.get("overlay_scale") or 0.22
                )
                plan["overlay_corner_radius"] = int(packaging_config.get("avatar_overlay_corner_radius") or 0)
                plan["overlay_border_width"] = int(packaging_config.get("avatar_overlay_border_width") or 0)
                plan["overlay_border_color"] = str(packaging_config.get("avatar_overlay_border_color") or "#F4E4B8")
                plan["overlay_margin"] = 28
                render_request = dict(plan.get("render_request") or {})
                render_request["presenter_id"] = str(avatar_video_path)
                render_request["layout_template"] = plan.get("layout_template")
                plan["render_request"] = render_request
            try:
                await _set_step_progress(session, step, detail="切分原声并逐段生成数字人口播", progress=0.84)
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_root = Path(tmpdir)
                    source_audio_path = await _resolve_storage_reference(
                        str(audio_artifact.storage_path or ""),
                        tmpdir=tmpdir,
                        default_name="avatar_reference.wav",
                    )
                    staged_segments: list[dict[str, Any]] = []
                    for segment in avatar_segments:
                        clip_path = tmp_root / f"{segment.get('segment_id')}.wav"
                        await extract_audio_clip(
                            source_audio_path,
                            clip_path,
                            start_time=float(segment.get("start_time") or 0.0),
                            end_time=float(segment.get("end_time") or segment.get("start_time") or 0.0),
                        )
                        staged_segments.append(
                            {
                                **segment,
                                "audio_url": str(clip_path),
                            }
                        )
                    plan["segments"] = staged_segments
                    plan["dubbing_execution"] = {
                        "provider": "passthrough",
                        "status": "skipped",
                        "reason": "segmented_audio_passthrough",
                    }
                    render_request = dict(plan.get("render_request") or {})
                    render_request["segments"] = staged_segments
                    await _set_step_progress(session, step, detail="调用数字人 provider 逐段生成口播", progress=0.92)
                    render_execution = await asyncio.to_thread(
                        get_avatar_provider().execute_render,
                        job_id=str(job.id),
                        request=render_request,
                    )
                    render_executed_in_mode = True
                    plan["render_execution"] = render_execution
                    plan["segments"] = _merge_execution_into_segments(
                        staged_segments,
                        render_execution.get("segments") if render_execution else None,
                        media_key="video",
                    )
                    plan["render_request"] = render_request
            except Exception as exc:
                plan["render_execution"] = {
                    "provider": plan.get("provider"),
                    "status": "failed",
                    "error": str(exc),
                }
        elif avatar_segments:
            try:
                await _set_step_progress(session, step, detail="为数字人段落生成配音", progress=0.82)
                audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")
                avatar_dubbing_request = get_voice_provider().build_dubbing_request(
                    job_id=str(job.id),
                    segments=[
                        {
                            "segment_id": segment.get("segment_id"),
                            "rewritten_text": segment.get("script"),
                            "target_duration_sec": segment.get("duration_sec"),
                            "purpose": segment.get("purpose"),
                        }
                        for segment in avatar_segments
                    ],
                    metadata={
                        "source_name": job.source_name,
                        "mode": "avatar_commentary",
                    },
                )
                with tempfile.TemporaryDirectory() as tmpdir:
                    reference_audio_path = await _resolve_storage_reference(
                        str(audio_artifact.storage_path or ""),
                        tmpdir=tmpdir,
                        default_name="avatar_reference.wav",
                    )
                    voice_execution = await asyncio.to_thread(
                        get_voice_provider().execute_dubbing,
                        job_id=str(job.id),
                        request=avatar_dubbing_request,
                        reference_audio_path=reference_audio_path,
                    )
                plan["dubbing_request"] = avatar_dubbing_request
                plan["dubbing_execution"] = voice_execution
                plan["segments"] = _merge_execution_into_segments(
                    avatar_segments,
                    voice_execution.get("segments") if voice_execution else None,
                    media_key="audio",
                )
            except Exception as exc:
                plan["dubbing_execution"] = {
                    "provider": get_settings().voice_provider,
                    "status": "failed",
                    "error": str(exc),
                }

        render_request = dict(plan.get("render_request") or {})
        render_request["segments"] = list(plan.get("segments") or [])
        if render_request.get("segments") and not render_executed_in_mode:
            try:
                await _set_step_progress(session, step, detail="调用数字人 provider 生成解说画中画", progress=0.92)
                render_execution = await asyncio.to_thread(
                    get_avatar_provider().execute_render,
                    job_id=str(job.id),
                    request=render_request,
                )
                plan["render_execution"] = render_execution
                plan["segments"] = _merge_execution_into_segments(
                    list(plan.get("segments") or []),
                    render_execution.get("segments") if render_execution else None,
                    media_key="video",
                )
                plan["render_request"] = render_request
            except Exception as exc:
                plan["render_execution"] = {
                    "provider": plan.get("provider"),
                    "status": "failed",
                    "error": str(exc),
                }
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="avatar_commentary_plan",
                data_json=plan,
            )
        )
        await _set_step_progress(session, step, detail="数字人解说计划已生成", progress=1.0)
        await session.commit()
        return {
            "enabled": True,
            "segment_count": len(plan.get("segments") or []),
            "mode": plan.get("mode"),
            "provider": plan.get("provider"),
            "dubbing_status": (voice_execution or plan.get("dubbing_execution") or {}).get("status"),
            "render_status": (render_execution or plan.get("render_execution") or {}).get("status"),
        }


async def run_edit_plan(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "edit_plan")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="加载媒体参数、字幕与音频", progress=0.15)

        # Get media meta for duration
        meta_artifact = await _load_latest_artifact(session, job.id, "media_meta")
        duration = meta_artifact.data_json["duration"]

        # Get audio for silence detection
        audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")

        # Get subtitle items for filler detection
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        transcript_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        transcript_rows = transcript_result.scalars().all()
        subtitle_dicts = [
            {
                "index": si.item_index,
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]
        transcript_evidence_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("transcript_evidence",),
        )
        transcript_segment_dicts = _build_edit_plan_transcript_segments(
            transcript_rows,
            transcript_evidence_artifact.data_json if transcript_evidence_artifact is not None else None,
        )

        profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        ai_director_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("ai_director_plan",),
        )
        avatar_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("avatar_commentary_plan",),
        )

        if (
            profile_artifact is not None
            and str(profile_artifact.artifact_type or "").strip().lower() in {"content_profile_final", "downstream_context"}
            and isinstance(content_profile, dict)
        ):
            try:
                subject_domain = _infer_subject_domain_for_memory(
                    workflow_template=job.workflow_template,
                    subtitle_items=subtitle_dicts,
                    content_profile=content_profile,
                    source_name=job.source_name,
                )
                glossary_result = await session.execute(select(GlossaryTerm))
                glossary_terms = glossary_result.scalars().all()
                effective_glossary_terms = _build_effective_glossary_terms(
                    glossary_terms=glossary_terms,
                    workflow_template=job.workflow_template,
                    content_profile=content_profile,
                    subtitle_items=subtitle_dicts,
                    source_name=job.source_name,
                    subject_domain=subject_domain,
                )
                user_memory = await load_content_profile_user_memory(
                    session,
                    subject_domain=subject_domain,
                )
                recent_subtitles = await _load_recent_subtitle_examples(
                    session,
                    workflow_template=job.workflow_template,
                    exclude_job_id=job.id,
                )
                related_subtitles = await _load_related_profile_subtitle_examples(
                    session,
                    content_profile=content_profile,
                    exclude_job_id=job.id,
                )
                review_memory = build_subtitle_review_memory(
                    workflow_template=job.workflow_template,
                    subject_domain=subject_domain,
                    glossary_terms=effective_glossary_terms,
                    user_memory=user_memory,
                    recent_subtitles=subtitle_dicts + related_subtitles + recent_subtitles,
                    content_profile=content_profile,
                    include_recent_terms=False,
                    include_recent_examples=False,
                )
                try:
                    await asyncio.wait_for(
                        polish_subtitle_items(
                            subtitle_items,
                            content_profile=content_profile,
                            glossary_terms=effective_glossary_terms,
                            review_memory=review_memory,
                            allow_llm=True,
                        ),
                        timeout=_EDIT_PLAN_SUBTITLE_POLISH_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        "Formal subtitle polish timed out during edit_plan for job %s; using rule-based fallback",
                        job.id,
                    )
                    await polish_subtitle_items(
                        subtitle_items,
                        content_profile=content_profile,
                        glossary_terms=effective_glossary_terms,
                        review_memory=review_memory,
                        allow_llm=False,
                    )
                except Exception:
                    logger.exception("LLM subtitle polish failed during edit_plan for job %s", job.id)
                    await polish_subtitle_items(
                        subtitle_items,
                        content_profile=content_profile,
                        glossary_terms=effective_glossary_terms,
                        review_memory=review_memory,
                        allow_llm=False,
                    )
            except Exception:
                logger.exception("Formal subtitle polish failed during edit_plan for job %s", job.id)
            finally:
                subtitle_dicts = [
                    {
                        "index": si.item_index,
                        "start_time": si.start_time,
                        "end_time": si.end_time,
                        "text_raw": si.text_raw,
                        "text_norm": si.text_norm,
                        "text_final": si.text_final,
                    }
                    for si in subtitle_items
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = await _resolve_storage_reference(
                str(audio_artifact.storage_path or ""),
                tmpdir=tmpdir,
                default_name="audio.wav",
            )
            await _set_step_progress(session, step, detail="检测静音和明显废话段", progress=0.5)
            silences = detect_silence(audio_path)
            scene_boundaries = []
            local_source_candidate = Path(str(job.source_path or "")).expanduser()
            if not local_source_candidate.exists():
                storage = get_storage()
                resolve_path = getattr(storage, "resolve_path", None)
                if callable(resolve_path):
                    resolved_source = resolve_path(str(job.source_path or ""))
                    if resolved_source.exists():
                        local_source_candidate = resolved_source
            if local_source_candidate.exists():
                try:
                    scene_boundaries = detect_scenes(local_source_candidate)
                except Exception:
                    logger.exception("Scene detection failed during edit_plan for job %s", job.id)

        review_rerun_focus = _resolve_edit_plan_review_focus(step)
        editing_skill = apply_review_focus_overrides(
            resolve_editing_skill(
                workflow_template=job.workflow_template or "unboxing_standard",
                content_profile=content_profile,
            ),
            review_focus=review_rerun_focus,
        )
        decision = build_edit_decision(
            source_path=job.source_path,
            duration=duration,
            silence_segments=silences,
            subtitle_items=subtitle_dicts,
            content_profile=content_profile,
            transcript_segments=transcript_segment_dicts,
            scene_boundaries=scene_boundaries,
            editing_skill=editing_skill,
        )
        await _set_step_progress(session, step, detail="生成剪辑时间线与渲染计划", progress=0.85)

        editorial_timeline = await save_editorial_timeline(job.id, decision, session)

        # Export OTIO
        try:
            otio_str = export_to_otio(decision.to_dict())
            editorial_timeline.otio_data = otio_str
        except Exception:
            pass  # OTIO optional

        packaging_plan = resolve_packaging_plan_for_job(str(job.id), content_profile=content_profile)
        keep_segments = [segment for segment in decision.to_dict().get("segments", []) if segment.get("type") == "keep"]
        remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)
        packaged_timeline_analysis = infer_timeline_analysis(
            remapped_subtitles,
            content_profile=content_profile,
            duration=max((float(item.get("end_time", 0.0) or 0.0) for item in remapped_subtitles), default=0.0),
            editing_skill=editing_skill,
        )
        with track_step_usage(job_id=job.id, step_id=step.id, step_name="edit_plan"):
            try:
                packaging_plan["insert"] = await asyncio.wait_for(
                    _plan_insert_asset_slot(
                        job_id=str(job.id),
                        insert_plan=packaging_plan.get("insert"),
                        subtitle_items=remapped_subtitles,
                        content_profile=content_profile,
                        timeline_analysis=packaged_timeline_analysis,
                        allow_llm=True,
                    ),
                    timeout=_EDIT_PLAN_INSERT_SLOT_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Insert-slot planning timed out during edit_plan for job %s; using deterministic fallback",
                    job.id,
                )
                packaging_plan["insert"] = await _plan_insert_asset_slot(
                    job_id=str(job.id),
                    insert_plan=packaging_plan.get("insert"),
                    subtitle_items=remapped_subtitles,
                    content_profile=content_profile,
                    timeline_analysis=packaged_timeline_analysis,
                    allow_llm=False,
                )
        packaging_plan["music"] = await _plan_music_entry(
            music_plan=packaging_plan.get("music"),
            subtitle_items=remapped_subtitles,
            content_profile=content_profile,
            timeline_analysis=packaged_timeline_analysis,
        )

        render_plan_dict = build_render_plan(
            editorial_timeline_id=editorial_timeline.id,
            workflow_preset=job.workflow_template or "unboxing_standard",
            subtitle_style=str(packaging_plan.get("subtitle_style") or "bold_yellow_outline"),
            subtitle_motion_style=str(packaging_plan.get("subtitle_motion_style") or "motion_static"),
            smart_effect_style=str(packaging_plan.get("smart_effect_style") or "smart_effect_rhythm"),
            cover_style=(
                None
                if str(packaging_plan.get("cover_style") or "preset_default") == "preset_default"
                else str(packaging_plan.get("cover_style"))
            ),
            title_style=str(packaging_plan.get("title_style") or "preset_default"),
            intro=packaging_plan.get("intro"),
            outro=packaging_plan.get("outro"),
            insert=packaging_plan.get("insert"),
            watermark=packaging_plan.get("watermark"),
            music=packaging_plan.get("music"),
            timeline_analysis=packaged_timeline_analysis,
            editing_skill=editing_skill,
            editing_accents=build_smart_editing_accents(
                keep_segments=keep_segments,
                subtitle_items=remapped_subtitles,
                timeline_analysis=packaged_timeline_analysis,
                editing_skill=editing_skill,
                style=str(packaging_plan.get("smart_effect_style") or "smart_effect_rhythm"),
            ),
            export_resolution_mode=str(packaging_plan.get("export_resolution_mode") or "source"),
            export_resolution_preset=str(packaging_plan.get("export_resolution_preset") or "1080p"),
            creative_profile=_job_creative_profile(job),
            ai_director_plan=ai_director_artifact.data_json if ai_director_artifact else None,
            avatar_commentary_plan=avatar_artifact.data_json if avatar_artifact else None,
        )
        await save_render_plan(job.id, render_plan_dict, session)

        await _set_step_progress(session, step, detail="剪辑决策已生成", progress=1.0)
        await session.commit()
        return {"timeline_id": str(editorial_timeline.id)}


async def run_render(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        from roughcut.db.models import RenderOutput

        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "render")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="准备时间线、字幕和输出目录", progress=0.05)

        # Get timelines
        editorial_timeline = await _load_latest_timeline(session, job.id, "editorial")
        render_plan_timeline = await _load_latest_timeline(session, job.id, "render_plan")
        has_packaging = any(
            render_plan_timeline.data_json.get(key)
            for key in ("intro", "outro", "insert", "watermark", "music")
        )
        has_editing_accents = bool(
            (render_plan_timeline.data_json.get("editing_accents") or {}).get("transitions", {}).get("boundary_indexes")
            or (render_plan_timeline.data_json.get("editing_accents") or {}).get("emphasis_overlays")
            or (render_plan_timeline.data_json.get("editing_accents") or {}).get("sound_effects")
        )

        content_profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        # Get subtitle items
        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]

        stale_render_outputs_result = await session.execute(
            select(RenderOutput).where(RenderOutput.job_id == job.id, RenderOutput.status == "running")
        )
        for stale_render_output in stale_render_outputs_result.scalars().all():
            stale_render_output.status = "failed"

        # Create render output record
        render_output = RenderOutput(
            job_id=job.id,
            timeline_id=editorial_timeline.id,
            status="running",
            progress=0.05,
        )
        session.add(render_output)
        await session.flush()
        render_output_id = render_output.id

        await session.commit()

    # Render (outside transaction — can be long)
    out_dir = get_output_project_dir(
        job.source_name,
        job.created_at,
        content_profile=content_profile,
        output_dir=job.output_dir,
    )
    out_name = out_dir.name
    debug_dir = Path(get_settings().render_debug_dir) / f"{job_id}_{out_name}"
    debug_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        render_heartbeat: asyncio.Task[None] | None = None
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            if render_step:
                await _set_step_progress(
                    session,
                    render_step,
                    detail=(
                        "先渲染素版，再生成包装版"
                        if (has_packaging or has_editing_accents)
                        else "执行 FFmpeg 渲染成片"
                    ),
                    progress=0.35,
                )
                render_heartbeat = _spawn_step_heartbeat(
                    step_id=render_step.id,
                    detail=(
                        "先渲染素版，再生成包装版"
                        if (has_packaging or has_editing_accents)
                        else "执行 FFmpeg 渲染成片"
                    ),
                    progress=0.35,
                )
        source_path = await _resolve_source(
            job,
            tmpdir,
            expected_hash=job.file_hash,
            debug_dir=debug_dir,
        )
        tmp_plain_mp4 = Path(tmpdir) / "output_plain.mp4"
        tmp_avatar_mp4 = Path(tmpdir) / "output_avatar.mp4"
        tmp_ai_effect_mp4 = Path(tmpdir) / "output_ai_effect.mp4"
        tmp_packaged_mp4 = Path(tmpdir) / "output_packaged.mp4"
        tmp_cover_plain_mp4 = Path(tmpdir) / "output_cover_plain.mp4"
        plain_render_plan = build_plain_render_plan(render_plan_timeline.data_json)
        avatar_render_plan = build_avatar_render_plan(render_plan_timeline.data_json)
        await render_video(
            source_path=source_path,
            render_plan=plain_render_plan,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_plain_mp4,
            subtitle_items=None,
            debug_dir=debug_dir / "plain",
        )
        import shutil
        shutil.copy2(tmp_plain_mp4, tmp_cover_plain_mp4)
        keep_segments = [
            s for s in editorial_timeline.data_json.get("segments", [])
            if s.get("type") == "keep"
        ]
        remapped_subtitles = remap_subtitles_to_timeline(subtitle_dicts, keep_segments)
        ai_effect_render_plan = build_ai_effect_render_plan(
            render_plan_timeline.data_json,
            keep_segments=keep_segments,
            subtitle_items=remapped_subtitles,
        )
        packaged_subtitles = await _map_subtitles_to_packaged_timeline(
            remapped_subtitles,
            render_plan_timeline.data_json,
            keep_segments=keep_segments,
        )
        final_overlay_accents = await _map_editing_accents_to_packaged_timeline(
            render_plan_timeline.data_json.get("editing_accents"),
            render_plan_timeline.data_json,
            keep_segments=keep_segments,
        )
        ai_effect_overlay_accents = await _map_editing_accents_to_packaged_timeline(
            ai_effect_render_plan.get("editing_accents"),
            ai_effect_render_plan,
            keep_segments=keep_segments,
        )
        packaged_transition_offsets = _resolve_transition_overlap_offsets(
            render_plan_timeline.data_json,
            keep_segments=keep_segments,
        )
        ai_effect_transition_offsets = _resolve_transition_overlap_offsets(
            ai_effect_render_plan,
            keep_segments=keep_segments,
        )
        avatar_plan = render_plan_timeline.data_json.get("avatar_commentary") or {}
        avatar_result: dict[str, Any] | None = None
        avatar_variant_source_path: Path | None = None
        avatar_variant_editorial_timeline: dict[str, Any] | None = None
        avatar_variant_subtitle_items: list[dict[str, Any]] | None = None
        avatar_overlay_accents: dict[str, Any] | None = None
        (
            packaged_source_path,
            packaged_editorial_timeline,
            packaged_subtitle_items,
        ) = _resolve_packaged_render_variant(
            original_source_path=source_path,
            original_editorial_timeline=editorial_timeline.data_json,
            original_subtitle_items=subtitle_dicts,
        )
        if (
            "avatar_commentary" in set(getattr(job, "enhancement_modes", []) or [])
            and str(avatar_plan.get("mode") or "") == "full_track_audio_passthrough"
        ):
            avatar_result = {
                "enabled": True,
                "status": "pending",
                "mode": str(avatar_plan.get("mode") or ""),
                "integration_mode": str(avatar_plan.get("integration_mode") or ""),
                "provider": str(avatar_plan.get("provider") or ""),
                "detail": "等待渲染阶段处理数字人口播。",
            }
            try:
                avatar_rendered_path = await _render_full_track_avatar_video(
                    job_id=str(job.id),
                    avatar_plan=avatar_plan,
                    source_plain_video_path=tmp_plain_mp4,
                    debug_dir=debug_dir / "avatar_full_track",
                )
                if avatar_rendered_path is not None and avatar_rendered_path.exists():
                    pip_output_path = Path(tmpdir) / "output_plain.avatar_pip.mp4"
                    await _overlay_avatar_picture_in_picture(
                        base_video_path=tmp_plain_mp4,
                        avatar_video_path=avatar_rendered_path,
                        output_path=pip_output_path,
                        position=str(avatar_plan.get("overlay_position") or "bottom_right"),
                        scale=float(avatar_plan.get("overlay_scale") or 0.22),
                        margin=int(avatar_plan.get("overlay_margin") or 28),
                        safe_margin_ratio=float(avatar_plan.get("safe_margin") or 0.1),
                        corner_radius=int(avatar_plan.get("overlay_corner_radius") or 0),
                        border_width=int(avatar_plan.get("overlay_border_width") or 0),
                        border_color=str(avatar_plan.get("overlay_border_color") or "#F4E4B8"),
                    )
                    pip_duration = float((await probe(pip_output_path)).duration or 0.0)
                    (
                        avatar_variant_source_path,
                        avatar_variant_editorial_timeline,
                        avatar_variant_subtitle_items,
                    ) = _resolve_packaged_render_variant(
                        original_source_path=source_path,
                        original_editorial_timeline=editorial_timeline.data_json,
                        original_subtitle_items=subtitle_dicts,
                        variant_source_path=pip_output_path,
                        variant_duration_sec=pip_duration,
                        variant_subtitle_items=remapped_subtitles,
                    )
                    packaged_source_path = avatar_variant_source_path
                    packaged_editorial_timeline = avatar_variant_editorial_timeline
                    avatar_result = {
                        **(avatar_result or {}),
                        "status": "done",
                        "detail": "数字人口播已作为画中画写入成片。",
                        "profile_name": str(avatar_plan.get("avatar_profile_name") or ""),
                        "output_path": str(pip_output_path),
                    }
                else:
                    avatar_result = {
                        **(avatar_result or {}),
                        "status": "degraded",
                        "reason": "missing_avatar_render",
                        "detail": "没有拿到可用数字人视频，已自动回退普通成片。",
                    }
            except Exception as exc:
                logger.exception("Avatar overlay degraded to plain render for job %s", job_id)
                avatar_result = {
                    **(avatar_result or {}),
                    "status": "degraded",
                    "reason": "avatar_render_failed",
                    "detail": f"数字人渲染失败，已自动回退普通成片：{exc}",
                }
        elif (
            "avatar_commentary" in set(getattr(job, "enhancement_modes", []) or [])
            and str(avatar_plan.get("mode") or "") == "segmented_audio_passthrough"
        ):
            avatar_result = {
                "enabled": True,
                "status": "pending",
                "mode": str(avatar_plan.get("mode") or ""),
                "integration_mode": str(avatar_plan.get("integration_mode") or ""),
                "provider": str(avatar_plan.get("provider") or ""),
                "detail": "等待渲染阶段拼接数字人口播片段。",
            }
            try:
                remapped_avatar_segments = _remap_avatar_segments_to_timeline(
                    list(avatar_plan.get("segments") or []),
                    keep_segments,
                )
                if remapped_avatar_segments:
                    pip_output_path = Path(tmpdir) / "output_plain.avatar_segments_pip.mp4"
                    await _overlay_avatar_segments_picture_in_picture(
                        base_video_path=tmp_plain_mp4,
                        avatar_segments=remapped_avatar_segments,
                        output_path=pip_output_path,
                        position=str(avatar_plan.get("overlay_position") or "bottom_right"),
                        scale=float(avatar_plan.get("overlay_scale") or 0.22),
                        margin=int(avatar_plan.get("overlay_margin") or 28),
                        safe_margin_ratio=float(avatar_plan.get("safe_margin") or 0.1),
                        corner_radius=int(avatar_plan.get("overlay_corner_radius") or 0),
                        border_width=int(avatar_plan.get("overlay_border_width") or 0),
                        border_color=str(avatar_plan.get("overlay_border_color") or "#F4E4B8"),
                    )
                    pip_duration = float((await probe(pip_output_path)).duration or 0.0)
                    (
                        avatar_variant_source_path,
                        avatar_variant_editorial_timeline,
                        avatar_variant_subtitle_items,
                    ) = _resolve_packaged_render_variant(
                        original_source_path=source_path,
                        original_editorial_timeline=editorial_timeline.data_json,
                        original_subtitle_items=subtitle_dicts,
                        variant_source_path=pip_output_path,
                        variant_duration_sec=pip_duration,
                        variant_subtitle_items=remapped_subtitles,
                    )
                    packaged_source_path = avatar_variant_source_path
                    packaged_editorial_timeline = avatar_variant_editorial_timeline
                    avatar_result = {
                        **(avatar_result or {}),
                        "status": "done",
                        "detail": "数字人口播片段已作为画中画写入成片。",
                        "profile_name": str(avatar_plan.get("avatar_profile_name") or ""),
                        "output_path": str(pip_output_path),
                        "segments": [
                            {
                                "segment_id": segment.get("segment_id"),
                                "start_time": segment.get("start_time"),
                                "end_time": segment.get("end_time"),
                            }
                            for segment in remapped_avatar_segments
                        ],
                    }
                else:
                    avatar_result = {
                        **(avatar_result or {}),
                        "status": "degraded",
                        "reason": "missing_avatar_segments",
                        "detail": "没有拿到可用数字人片段，已自动回退普通成片。",
                    }
            except Exception as exc:
                logger.exception("Avatar segmented overlay degraded to plain render for job %s", job_id)
                avatar_result = {
                    **(avatar_result or {}),
                    "status": "degraded",
                    "reason": "avatar_segment_render_failed",
                    "detail": f"数字人片段渲染失败，已自动回退普通成片：{exc}",
                }
        if render_heartbeat is not None:
            render_heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await render_heartbeat
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            render_output = await session.get(RenderOutput, render_output_id)
            if render_step:
                await _set_step_progress(
                    session,
                    render_step,
                    detail="素版已完成，开始生成包装版",
                    progress=0.55,
                )
            if render_output:
                render_output.progress = 0.55
                await session.commit()
            packaging_heartbeat = _spawn_step_heartbeat(
                step_id=render_step.id if render_step else None,
                detail="素版已完成，开始生成包装版",
                progress=0.55,
            )
        if (
            avatar_variant_source_path is not None
            and avatar_variant_editorial_timeline is not None
            and avatar_variant_subtitle_items is not None
        ):
            avatar_overlay_accents = await _map_editing_accents_to_packaged_timeline(
                avatar_render_plan.get("editing_accents"),
                avatar_render_plan,
                keep_segments=keep_segments,
            )
            await render_video(
                source_path=avatar_variant_source_path,
                render_plan=avatar_render_plan,
                editorial_timeline=avatar_variant_editorial_timeline,
                output_path=tmp_avatar_mp4,
                subtitle_items=packaged_subtitles,
                overlay_editing_accents=avatar_overlay_accents,
                debug_dir=debug_dir / "avatar_variant",
            )
        await render_video(
            source_path=source_path,
            render_plan=ai_effect_render_plan,
            editorial_timeline=editorial_timeline.data_json,
            output_path=tmp_ai_effect_mp4,
            subtitle_items=packaged_subtitles,
            overlay_editing_accents=ai_effect_overlay_accents,
            debug_dir=debug_dir / "ai_effect_variant",
        )
        await render_video(
            source_path=packaged_source_path,
            render_plan=render_plan_timeline.data_json,
            editorial_timeline=packaged_editorial_timeline,
            output_path=tmp_packaged_mp4,
            subtitle_items=packaged_subtitles,
            overlay_editing_accents=final_overlay_accents,
            debug_dir=debug_dir / "packaged",
        )
        if packaging_heartbeat is not None:
            packaging_heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await packaging_heartbeat
        plain_meta = await probe(tmp_plain_mp4)
        packaged_meta = await probe(tmp_packaged_mp4)
        ai_effect_meta = await probe(tmp_ai_effect_mp4)
        avatar_meta = await probe(tmp_avatar_mp4) if tmp_avatar_mp4.exists() else None

        local_plain_mp4 = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="素板",
            extension=".mp4",
            width=plain_meta.width,
            height=plain_meta.height,
        )
        local_packaged_mp4 = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="成片",
            extension=".mp4",
            width=packaged_meta.width,
            height=packaged_meta.height,
        )
        local_ai_effect_mp4 = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="AI特效版",
            extension=".mp4",
            width=ai_effect_meta.width,
            height=ai_effect_meta.height,
        )
        local_avatar_mp4 = (
            build_variant_output_path(
                out_dir,
                out_name,
                variant_label="数字人版",
                extension=".mp4",
                width=avatar_meta.width,
                height=avatar_meta.height,
            )
            if avatar_meta is not None
            else None
        )
        local_plain_srt = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="素板",
            extension=".srt",
            width=plain_meta.width,
            height=plain_meta.height,
        )
        local_packaged_srt = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="成片",
            extension=".srt",
            width=packaged_meta.width,
            height=packaged_meta.height,
        )
        local_ai_effect_srt = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="AI特效版",
            extension=".srt",
            width=ai_effect_meta.width,
            height=ai_effect_meta.height,
        )
        local_avatar_srt = (
            build_variant_output_path(
                out_dir,
                out_name,
                variant_label="数字人版",
                extension=".srt",
                width=avatar_meta.width,
                height=avatar_meta.height,
            )
            if avatar_meta is not None
            else None
        )
        local_cover = build_variant_output_path(
            out_dir,
            out_name,
            variant_label="封面",
            extension=".jpg",
            width=plain_meta.width,
            height=plain_meta.height,
        )

        shutil.copy2(tmp_plain_mp4, local_plain_mp4)
        if tmp_avatar_mp4.exists() and local_avatar_mp4 is not None:
            shutil.copy2(tmp_avatar_mp4, local_avatar_mp4)
        shutil.copy2(tmp_ai_effect_mp4, local_ai_effect_mp4)
        shutil.copy2(tmp_packaged_mp4, local_packaged_mp4)
        async with get_session_factory()() as session:
            step_result = await session.execute(
                select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
            )
            render_step = step_result.scalar_one_or_none()
            render_output = await session.get(RenderOutput, render_output_id)
            if render_step:
                await _set_step_progress(session, render_step, detail="生成字幕文件与封面图", progress=0.75)
            if render_output:
                render_output.progress = 0.75
                await session.commit()

        # Write SRT with remapped timestamps (matches the edited video)
        write_srt_file(packaged_subtitles, local_packaged_srt)
        write_srt_file(remapped_subtitles, local_plain_srt)
        if tmp_avatar_mp4.exists() and local_avatar_srt is not None:
            write_srt_file(packaged_subtitles, local_avatar_srt)
        write_srt_file(packaged_subtitles, local_ai_effect_srt)
        packaged_subtitle_sync = _compute_subtitle_sync_check(local_packaged_mp4, local_packaged_srt)
        plain_subtitle_sync = _compute_subtitle_sync_check(local_plain_mp4, local_plain_srt)
        avatar_subtitle_sync = (
            _compute_subtitle_sync_check(local_avatar_mp4, local_avatar_srt)
            if local_avatar_mp4 is not None and local_avatar_srt is not None and tmp_avatar_mp4.exists()
            else None
        )
        ai_effect_subtitle_sync = _compute_subtitle_sync_check(local_ai_effect_mp4, local_ai_effect_srt)

        # Extract cover frame from the plain render so burned subtitles never leak into thumbnails.
        try:
            meta_result = await _get_cover_seek(job.id, tmpdir)
            cover_source_path = _select_cover_source_video(tmp_cover_plain_mp4, tmp_packaged_mp4)
            cover_variants = await extract_cover_frame(
                cover_source_path,
                local_cover,
                seek_sec=meta_result,
                content_profile=content_profile,
                cover_style=(render_plan_timeline.data_json.get("cover") or {}).get("style"),
                title_style=(render_plan_timeline.data_json.get("cover") or {}).get("title_style"),
            )
            cover_selection = load_cover_selection_summary(local_cover)
        except Exception:
            local_cover = None  # Cover is non-critical
            cover_variants = []
            cover_selection = None

    # Update render output
    local_paths = {
        "mp4": str(local_packaged_mp4),
        "srt": str(local_packaged_srt),
        "packaged_mp4": str(local_packaged_mp4),
        "plain_mp4": str(local_plain_mp4),
        "avatar_mp4": str(local_avatar_mp4) if local_avatar_mp4 is not None and local_avatar_mp4.exists() else None,
        "ai_effect_mp4": str(local_ai_effect_mp4),
        "packaged_srt": str(local_packaged_srt),
        "plain_srt": str(local_plain_srt),
        "avatar_srt": str(local_avatar_srt) if local_avatar_srt is not None and local_avatar_srt.exists() else None,
        "ai_effect_srt": str(local_ai_effect_srt),
        "cover": str(local_cover) if local_cover else None,
        "cover_variants": [str(path) for path in cover_variants] if local_cover else [],
        "cover_selection": cover_selection,
        "output_name": out_name,
        "variants": {
            "packaged": str(local_packaged_mp4),
            "plain": str(local_plain_mp4),
            "avatar": str(local_avatar_mp4) if local_avatar_mp4 is not None and local_avatar_mp4.exists() else None,
            "ai_effect": str(local_ai_effect_mp4),
        },
    }
    variant_timeline_bundle = _build_variant_timeline_bundle(
        editorial_timeline_id=editorial_timeline.id,
        render_plan_timeline_id=render_plan_timeline.id,
        keep_segments=keep_segments,
        editorial_analysis=(editorial_timeline.data_json or {}).get("analysis") or {},
        render_plan=render_plan_timeline.data_json,
        variants={
            "plain": _build_variant_timeline_entry(
                media_path=local_plain_mp4,
                srt_path=local_plain_srt,
                media_meta=plain_meta,
                subtitle_events=remapped_subtitles,
                transition_offsets=[],
                segments=editorial_timeline.data_json.get("segments") or [],
                quality_check=plain_subtitle_sync or {},
            ),
            "packaged": _build_variant_timeline_entry(
                media_path=local_packaged_mp4,
                srt_path=local_packaged_srt,
                media_meta=packaged_meta,
                subtitle_events=packaged_subtitles,
                transition_offsets=packaged_transition_offsets,
                segments=packaged_editorial_timeline.get("segments") or [],
                overlay_events=final_overlay_accents,
                quality_check=packaged_subtitle_sync or {},
            ),
            "ai_effect": _build_variant_timeline_entry(
                media_path=local_ai_effect_mp4,
                srt_path=local_ai_effect_srt,
                media_meta=ai_effect_meta,
                subtitle_events=packaged_subtitles,
                transition_offsets=ai_effect_transition_offsets,
                segments=editorial_timeline.data_json.get("segments") or [],
                overlay_events=ai_effect_overlay_accents,
                quality_check=ai_effect_subtitle_sync or {},
            ),
            **(
                {
                    "avatar": _build_variant_timeline_entry(
                        media_path=local_avatar_mp4,
                        srt_path=local_avatar_srt,
                        media_meta=avatar_meta,
                        subtitle_events=packaged_subtitles,
                        transition_offsets=[],
                        segments=(avatar_variant_editorial_timeline or {}).get("segments") or [],
                        overlay_events=avatar_overlay_accents,
                        quality_check=avatar_subtitle_sync or {},
                    )
                }
                if local_avatar_mp4 is not None and local_avatar_srt is not None and avatar_meta is not None
                else {}
            ),
        },
    )
    async with get_session_factory()() as session:
        render_output = await session.get(RenderOutput, render_output_id)
        render_output.output_path = str(local_packaged_mp4)
        render_output.status = "done"
        render_output.progress = 1.0
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
        )
        render_step = step_result.scalar_one_or_none()
        session.add(
            Artifact(
                job_id=uuid.UUID(job_id),
                step_id=render_step.id if render_step else None,
                artifact_type="render_outputs",
                data_json={
                    "plain_mp4": str(local_plain_mp4),
                    "packaged_mp4": str(local_packaged_mp4),
                    "avatar_mp4": str(local_avatar_mp4) if local_avatar_mp4 is not None and local_avatar_mp4.exists() else None,
                    "ai_effect_mp4": str(local_ai_effect_mp4),
                    "plain_srt": str(local_plain_srt),
                    "packaged_srt": str(local_packaged_srt),
                    "avatar_srt": str(local_avatar_srt) if local_avatar_srt is not None and local_avatar_srt.exists() else None,
                    "ai_effect_srt": str(local_ai_effect_srt),
                    "cover": str(local_cover) if local_cover else None,
                    "cover_variants": [str(path) for path in cover_variants] if local_cover else [],
                    "cover_selection": cover_selection,
                    "avatar_result": avatar_result,
                    "quality_checks": {
                        "subtitle_sync": packaged_subtitle_sync,
                        "plain_subtitle_sync": plain_subtitle_sync,
                        "avatar_subtitle_sync": avatar_subtitle_sync,
                        "ai_effect_subtitle_sync": ai_effect_subtitle_sync,
                    },
                },
            )
        )
        session.add(
            Artifact(
                job_id=uuid.UUID(job_id),
                step_id=render_step.id if render_step else None,
                artifact_type="variant_timeline_bundle",
                data_json=variant_timeline_bundle,
            )
        )
        if render_step:
            cover_detail = ""
            if cover_selection:
                cover_detail = (
                    "，封面分差接近，可确认首选"
                    if cover_selection.get("review_recommended")
                    else "，封面已自动选优"
                )
            await _set_step_progress(
                session,
                render_step,
                detail=(
                    f"素版与包装版均已输出{cover_detail}"
                    if (has_packaging or has_editing_accents)
                    else f"渲染完成，成片与字幕已输出{cover_detail}"
                ),
                progress=1.0,
            )
        await session.commit()
        try:
            await get_telegram_review_bot_service().notify_final_review(uuid.UUID(job_id))
        except Exception:
            logger.exception("Failed to send Telegram final review for job %s", job_id)

    return {"output_path": str(local_packaged_mp4), "local": local_paths}


async def run_platform_package(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        if not job:
            raise ValueError(f"Job {job_id} not found")

        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "platform_package")
        )
        step = step_result.scalar_one_or_none()
        await _set_step_progress(session, step, detail="整理成片信息并生成平台文案", progress=0.2)

        content_profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        item_result = await session.execute(
            select(SubtitleItem)
            .where(SubtitleItem.job_id == job.id, SubtitleItem.version == 1)
            .order_by(SubtitleItem.item_index)
        )
        subtitle_items = item_result.scalars().all()
        subtitle_dicts = [
            {
                "index": si.item_index,
                "start_time": si.start_time,
                "end_time": si.end_time,
                "text_raw": si.text_raw,
                "text_norm": si.text_norm,
                "text_final": si.text_final,
            }
            for si in subtitle_items
        ]

        render_output_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_output_result.scalars().first()
        if not render_output or not render_output.output_path:
            raise ValueError("Rendered output not found; platform package requires a finished render")

    packaging_config = (list_packaging_assets().get("config") or {})
    author_profile = _select_default_avatar_profile()
    copy_style = str(
        packaging_config.get("copy_style")
        or (content_profile or {}).get("copy_style")
        or "attention_grabbing"
    )
    prompt_brief = build_packaging_prompt_brief(
        source_name=job.source_name,
        content_profile=content_profile,
        subtitle_items=subtitle_dicts,
    )

    fact_sheet_cache_metadata: dict[str, Any] | None = None
    if packaging_fact_sheet_cache_allowed(content_profile):
        fact_sheet_cache_namespace = "platform_package.fact_sheet"
        fact_sheet_cache_fingerprint = build_packaging_fact_sheet_cache_fingerprint(
            source_name=job.source_name,
            content_profile=content_profile,
            subtitle_items=subtitle_dicts,
        )
        fact_sheet_cache_key = build_cache_key(fact_sheet_cache_namespace, fact_sheet_cache_fingerprint)
        cached_fact_sheet_entry = load_cached_entry(fact_sheet_cache_namespace, fact_sheet_cache_key)
        fact_sheet_cache_metadata = build_cache_metadata(
            fact_sheet_cache_namespace,
            fact_sheet_cache_key,
            hit=bool(cached_fact_sheet_entry),
            usage_baseline=(cached_fact_sheet_entry or {}).get("usage_baseline"),
        )
        if cached_fact_sheet_entry:
            fact_sheet = dict(cached_fact_sheet_entry.get("result") or {})
        else:
            usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
            with track_step_usage(job_id=job.id, step_id=step.id if step else None, step_name="platform_package"):
                fact_sheet = await build_packaging_fact_sheet(
                    source_name=job.source_name,
                    content_profile=content_profile,
                    subtitle_items=subtitle_dicts,
                )
            usage_after = await _read_persisted_step_usage_snapshot(step.id if step else None)
            usage_baseline = _usage_delta(usage_after, usage_before)
            save_cached_json(
                fact_sheet_cache_namespace,
                fact_sheet_cache_key,
                fingerprint=fact_sheet_cache_fingerprint,
                result=fact_sheet,
                usage_baseline=usage_baseline,
            )
    else:
        with track_step_usage(job_id=job.id, step_id=step.id if step else None, step_name="platform_package"):
            fact_sheet = await build_packaging_fact_sheet(
                source_name=job.source_name,
                content_profile=content_profile,
                subtitle_items=subtitle_dicts,
            )

    packaging_cache_namespace = "platform_package.generate"
    packaging_cache_fingerprint = build_platform_packaging_cache_fingerprint(
        source_name=job.source_name,
        prompt_brief=prompt_brief,
        fact_sheet=fact_sheet,
        copy_style=copy_style,
        author_profile=author_profile,
    )
    packaging_cache_key = build_cache_key(packaging_cache_namespace, packaging_cache_fingerprint)
    cached_packaging_entry = load_cached_entry(packaging_cache_namespace, packaging_cache_key)
    packaging_cache_metadata = build_cache_metadata(
        packaging_cache_namespace,
        packaging_cache_key,
        hit=bool(cached_packaging_entry),
        usage_baseline=(cached_packaging_entry or {}).get("usage_baseline"),
    )
    if cached_packaging_entry:
        packaging = dict(cached_packaging_entry.get("result") or {})
        packaging["fact_sheet"] = fact_sheet
    else:
        usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
        with track_step_usage(job_id=job.id, step_id=step.id if step else None, step_name="platform_package"):
            packaging = await generate_platform_packaging(
                source_name=job.source_name,
                content_profile=content_profile,
                subtitle_items=subtitle_dicts,
                copy_style=copy_style,
                author_profile=author_profile,
                prompt_brief=prompt_brief,
                fact_sheet=fact_sheet,
            )
        usage_after = await _read_persisted_step_usage_snapshot(step.id if step else None)
        usage_baseline = _usage_delta(usage_after, usage_before)
        save_cached_json(
            packaging_cache_namespace,
            packaging_cache_key,
            fingerprint=packaging_cache_fingerprint,
            result=packaging,
            usage_baseline=usage_baseline,
        )

    output_mp4 = Path(render_output.output_path)
    output_md = output_mp4.with_name(f"{output_mp4.stem}_publish.md")
    save_platform_packaging_markdown(output_md, packaging)

    async with get_session_factory()() as session:
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "platform_package")
        )
        current_step = step_result.scalar_one_or_none()
        fact_sheet = packaging.get("fact_sheet") if isinstance(packaging, dict) else None
        if isinstance(fact_sheet, dict):
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=current_step.id if current_step else None,
                    artifact_type="product_fact_sheet",
                    data_json=fact_sheet,
                )
            )
        artifact = Artifact(
            job_id=job.id,
            step_id=current_step.id if current_step else None,
            artifact_type="platform_packaging_md",
            storage_path=str(output_md),
            data_json=packaging,
        )
        session.add(artifact)
        if current_step is not None:
            _set_step_cache_metadata(current_step, "platform_packaging", packaging_cache_metadata)
            if fact_sheet_cache_metadata is not None:
                _set_step_cache_metadata(current_step, "platform_fact_sheet", fact_sheet_cache_metadata)
            await _set_step_progress(session, current_step, detail="平台文案已生成", progress=1.0)
        await session.commit()

    return {"markdown": str(output_md)}


async def _get_cover_seek(job_id, tmpdir: str) -> float:
    """
    Determine a good seek time for cover frame extraction.
    Uses ~18% of video duration, with 6s minimum and 45s maximum.
    Falls back to 6.0s if no media_meta artifact found.
    """
    del tmpdir
    factory = get_session_factory()
    async with factory() as session:
        try:
            artifact = await _load_latest_artifact(session, job_id, "media_meta")
        except ValueError:
            artifact = None
        if artifact and artifact.data_json:
            duration = artifact.data_json.get("duration", 60.0)
            seek = max(6.0, min(45.0, duration * 0.18))
            return round(seek, 1)
    return 6.0


def _select_cover_source_video(plain_video_path: Path, packaged_video_path: Path) -> Path:
    del packaged_video_path
    if plain_video_path.exists():
        return plain_video_path
    raise FileNotFoundError("Plain render is required for cover extraction")


def _subtitle_text(item: dict[str, Any]) -> str:
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()


def _subtitle_section_profile_for_time(
    render_plan: dict[str, Any],
    time_sec: float,
) -> dict[str, Any] | None:
    for profile in list(((render_plan.get("subtitles") or {}).get("section_profiles") or [])):
        if not isinstance(profile, dict):
            continue
        start_sec = float(profile.get("start_sec", 0.0) or 0.0)
        end_sec = float(profile.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return profile
    directive = _section_directive_for_time(render_plan.get("timeline_analysis") or {}, time_sec)
    if not isinstance(directive, dict):
        return None
    return {
        "role": str(directive.get("role") or ""),
        "start_sec": float(directive.get("start_sec", 0.0) or 0.0),
        "end_sec": float(directive.get("end_sec", 0.0) or 0.0),
    }


def _extract_subtitle_copy_clauses(text: str) -> list[str]:
    normalized = normalize_display_text(str(text or ""))
    if not normalized:
        return []
    clauses = [
        clause.strip()
        for clause in re.split(r"[，,。！？!?；;：:\s]+", normalized)
        if clause and clause.strip()
    ]
    if clauses:
        return clauses
    return [normalized]


def _strip_subtitle_copy_prefix(text: str) -> str:
    cleaned = _SUBTITLE_COPY_GENERIC_PREFIX_RE.sub("", str(text or "").strip()).strip("，,：: ")
    if re.match(r"^[讲说看](?:参数|细节|尺寸|接口|版本|续航|流明|材质|做工|手感|节点|工作流|模型|画布|分仓|挂点|收纳|对比|区别|差异)", cleaned):
        cleaned = cleaned[1:]
    return cleaned or str(text or "").strip()


def _finalize_packaged_subtitle_text(text: str) -> str:
    normalized = normalize_display_text(str(text or ""))
    if not normalized:
        return ""
    if normalized[-1] not in "。！？!?；;":
        normalized += "。"
    return normalized


def _rewrite_hook_subtitle_text(text: str, clauses: list[str]) -> str:
    if not clauses:
        return ""
    first_clause = clauses[0]
    if first_clause.startswith(_SUBTITLE_COPY_HOOK_LEADS) and len(clauses) >= 2:
        first_clause = clauses[1]
    elif len(first_clause) <= 4 and len(clauses) >= 2:
        first_clause = f"{first_clause}{clauses[1]}"
    return _finalize_packaged_subtitle_text(_strip_subtitle_copy_prefix(first_clause))


def _score_detail_clause(clause: str) -> float:
    score = 0.0
    compact = str(clause or "").strip()
    if not compact:
        return score
    if re.search(r"\d", compact):
        score += 1.2
    if re.search(r"[A-Z]{2,}", compact):
        score += 1.0
    if 5 <= len(compact) <= 18:
        score += 0.6
    elif len(compact) <= 24:
        score += 0.2
    if compact.startswith(("重点", "主要", "参数", "区别", "差异")):
        score += 0.8
    if _SUBTITLE_COPY_GENERIC_PREFIX_RE.match(compact):
        score -= 0.4
    score += min(
        1.6,
        sum(0.35 for term in _SUBTITLE_COPY_DETAIL_TERMS if term in compact),
    )
    return score


def _rewrite_detail_subtitle_text(text: str, clauses: list[str]) -> str:
    if not clauses:
        return ""
    scored = sorted(
        ((_score_detail_clause(clause), clause) for clause in clauses),
        key=lambda item: (-item[0], len(item[1])),
    )
    best_clause = scored[0][1]
    stripped = _strip_subtitle_copy_prefix(best_clause)
    if len(stripped) >= 4:
        best_clause = stripped
    return _finalize_packaged_subtitle_text(best_clause)


def _rewrite_cta_subtitle_text(text: str) -> str:
    normalized = normalize_display_text(str(text or ""))
    compact = normalized.replace(" ", "")
    for keywords, rewritten in _SUBTITLE_COPY_CTA_PATTERNS:
        if all(keyword in compact for keyword in keywords):
            return rewritten
    clauses = _extract_subtitle_copy_clauses(normalized)
    return _finalize_packaged_subtitle_text(clauses[0] if clauses else normalized)


def _rewrite_packaged_subtitle_copy(
    subtitle_items: list[dict[str, Any]],
    *,
    render_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    rewritten_items: list[dict[str, Any]] = []
    for item in subtitle_items:
        rewritten = dict(item)
        original_text = _subtitle_text(rewritten)
        if not original_text:
            rewritten_items.append(rewritten)
            continue
        midpoint = (
            float(rewritten.get("start_time", 0.0) or 0.0)
            + float(rewritten.get("end_time", rewritten.get("start_time", 0.0)) or 0.0)
        ) / 2.0
        profile = _subtitle_section_profile_for_time(render_plan, midpoint)
        if not isinstance(profile, dict):
            rewritten_items.append(rewritten)
            continue
        role = str(profile.get("role") or "").strip().lower()
        clauses = _extract_subtitle_copy_clauses(original_text)
        rewritten_text = ""
        strategy = ""
        if role == "hook":
            rewritten_text = _rewrite_hook_subtitle_text(original_text, clauses)
            strategy = "hook_compact"
        elif role == "detail":
            rewritten_text = _rewrite_detail_subtitle_text(original_text, clauses)
            strategy = "detail_focus"
        elif role == "cta":
            rewritten_text = _rewrite_cta_subtitle_text(original_text)
            strategy = "cta_compact"
        if rewritten_text and rewritten_text != original_text:
            rewritten.setdefault("text_original_final", original_text)
            rewritten["text_final"] = rewritten_text
            rewritten["subtitle_copy_strategy"] = strategy
            rewritten["subtitle_section_role"] = role
        rewritten_items.append(rewritten)
    return rewritten_items


def _subtitle_signoff_clause(text: str) -> str:
    for clause in _extract_subtitle_copy_clauses(text):
        candidate = _finalize_packaged_subtitle_text(_strip_subtitle_copy_prefix(clause))
        compact = candidate.replace(" ", "")
        if any(keyword in compact for keyword in ("点赞", "收藏", "关注")):
            continue
        if len(compact.rstrip("。！？!?；;")) >= 4:
            return candidate
    return ""


def _detail_setup_clause(text: str, *, focused_text: str) -> str:
    candidates: list[tuple[float, str]] = []
    for clause in _extract_subtitle_copy_clauses(text):
        candidate = _finalize_packaged_subtitle_text(_strip_subtitle_copy_prefix(clause))
        if not candidate or candidate == focused_text:
            continue
        compact = candidate.rstrip("。！？!?；;")
        if len(compact) < 4:
            continue
        score = _score_detail_clause(compact)
        if score <= 0.4:
            continue
        candidates.append((score, candidate))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates[0][1]


def _hook_support_clause(text: str, *, primary_text: str) -> str:
    for clause in _extract_subtitle_copy_clauses(text):
        raw_clause = str(clause or "").strip()
        if raw_clause.startswith(_SUBTITLE_COPY_HOOK_LEADS):
            continue
        candidate = _finalize_packaged_subtitle_text(_strip_subtitle_copy_prefix(clause))
        if not candidate or candidate == primary_text:
            continue
        compact = candidate.rstrip("。！？!?；;")
        if len(compact) >= 4:
            return candidate
    return ""


def _resolve_resegmented_subtitle_texts(
    item: dict[str, Any],
    *,
    role: str,
) -> list[str]:
    primary_text = _subtitle_text(item)
    if not primary_text:
        return []
    original_text = str(item.get("text_original_final") or primary_text)
    duration_sec = max(
        0.0,
        float(item.get("end_time", item.get("start_time", 0.0)) or 0.0)
        - float(item.get("start_time", 0.0) or 0.0),
    )
    if role == "hook" and duration_sec >= 2.6:
        support = _hook_support_clause(original_text, primary_text=primary_text)
        if support:
            return [primary_text, support]
    if role == "detail" and duration_sec >= 2.8:
        setup = _detail_setup_clause(original_text, focused_text=primary_text)
        if setup:
            return [setup, primary_text]
    if role == "cta" and duration_sec >= 2.2:
        signoff = _subtitle_signoff_clause(original_text)
        if signoff and signoff != primary_text:
            return [primary_text, signoff]
    return [primary_text]


def _resolve_subtitle_unit_roles(role: str, count: int) -> list[str]:
    normalized_role = str(role or "").strip().lower()
    if count <= 1:
        return [normalized_role or "single"]
    if normalized_role == "hook":
        return ["lead", "support"][:count]
    if normalized_role == "detail":
        return ["setup", "focus"][:count]
    if normalized_role == "cta":
        return ["action", "signoff"][:count]
    return [f"unit_{index}" for index in range(count)]


def _allocate_subtitle_unit_durations(
    total_duration_sec: float,
    texts: list[str],
    *,
    min_unit_sec: float = 0.62,
) -> list[float]:
    count = len(texts)
    if count <= 1:
        return [round(max(0.0, total_duration_sec), 3)]
    minimum_total = min_unit_sec * count
    if total_duration_sec <= minimum_total + 0.02:
        return [round(max(0.0, total_duration_sec / count), 3) for _ in texts]
    weights = [max(1.0, float(len(text.rstrip("。！？!?；;")))) for text in texts]
    remaining = float(total_duration_sec)
    remaining_weight = float(sum(weights))
    durations: list[float] = []
    for index, weight in enumerate(weights):
        slots_left = count - index - 1
        minimum_for_rest = min_unit_sec * slots_left
        ideal = total_duration_sec * (weight / remaining_weight) if remaining_weight > 0 else total_duration_sec / count
        duration = min(
            max(min_unit_sec, ideal),
            max(min_unit_sec, remaining - minimum_for_rest),
        )
        duration = round(duration, 3)
        durations.append(duration)
        remaining -= duration
        remaining_weight -= weight
    if durations:
        durations[-1] = round(max(min_unit_sec, durations[-1] + remaining), 3)
    return durations


def _resegment_packaged_subtitles(
    subtitle_items: list[dict[str, Any]],
    *,
    render_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    resegmented: list[dict[str, Any]] = []
    for item in subtitle_items:
        original_start = float(item.get("start_time", 0.0) or 0.0)
        original_end = max(original_start, float(item.get("end_time", original_start) or original_start))
        midpoint = (original_start + original_end) / 2.0
        profile = _subtitle_section_profile_for_time(render_plan, midpoint)
        role = str((profile or {}).get("role") or "").strip().lower()
        texts = _resolve_resegmented_subtitle_texts(item, role=role)
        if len(texts) <= 1:
            resegmented.append(dict(item))
            continue
        unit_roles = _resolve_subtitle_unit_roles(role, len(texts))
        durations = _allocate_subtitle_unit_durations(original_end - original_start, texts)
        cursor = original_start
        for index, (text, duration_sec) in enumerate(zip(texts, durations)):
            unit = dict(item)
            unit["start_time"] = round(cursor, 3)
            next_cursor = original_end if index == len(texts) - 1 else min(original_end, cursor + max(0.18, duration_sec))
            unit["end_time"] = round(next_cursor, 3)
            unit["text_final"] = text
            unit["subtitle_copy_strategy"] = (
                f"{str(item.get('subtitle_copy_strategy') or role or 'packaged')}_resegmented"
            )
            unit["subtitle_unit_index"] = index
            unit["subtitle_unit_count"] = len(texts)
            unit["subtitle_unit_role"] = unit_roles[index] if index < len(unit_roles) else f"unit_{index}"
            resegmented.append(unit)
            cursor = next_cursor
    for index, item in enumerate(resegmented):
        item["index"] = index
    return resegmented


def _score_music_entry_candidates(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[dict[str, Any]]:
    workflow_template = str((content_profile or {}).get("workflow_template") or (content_profile or {}).get("preset_name") or "").strip()
    scored: list[dict[str, Any]] = []
    for index, item in enumerate(subtitle_items):
        end_time = float(item.get("end_time", 0.0) or 0.0)
        if end_time < 1.5 or end_time > 18.0:
            continue
        text = _subtitle_text(item)
        next_item = subtitle_items[index + 1] if index + 1 < len(subtitle_items) else None
        next_start = float(next_item.get("start_time", end_time) or end_time) if next_item else end_time
        gap = max(0.0, next_start - end_time)

        score = 0.28
        reasons: list[str] = []
        if 3.0 <= end_time <= 8.5:
            score += 0.24
            reasons.append("位于开场钩子之后的自然进入区间")
        elif 2.0 <= end_time <= 12.0:
            score += 0.12
        if gap >= 0.35:
            score += 0.2
            reasons.append("后面有明显停顿")
        elif gap >= 0.18:
            score += 0.1
        if text.endswith(("。", "！", "？", "；", ".", "!", "?", ";")):
            score += 0.14
            reasons.append("句子在这里收束")
        if len(text) >= 10:
            score += 0.08
        if _workflow_template_subject_domain(workflow_template) == "gear" and 5.0 <= end_time <= 14.0:
            score += 0.08
            reasons.append("适合在主体介绍后进入 BGM")

        scored.append(
            {
                "index": index,
                "enter_sec": round(end_time, 2),
                "score": round(min(score, 0.99), 3),
                "reasons": reasons,
            }
        )

    scored.sort(key=lambda item: (-float(item["score"]), float(item["enter_sec"])))
    return scored


def _build_timing_summary(
    rankings: list[dict[str, Any]],
    *,
    review_gap: float,
    min_score: float,
    low_confidence_reason: str,
) -> dict[str, Any]:
    if not rankings:
        return {
            "selected_score": 0.0,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "review_recommended": True,
            "review_reason": low_confidence_reason,
        }
    primary = rankings[0]
    runner_up = rankings[1] if len(rankings) > 1 else None
    primary_score = float(primary.get("score") or 0.0)
    runner_up_score = float(runner_up.get("score") or 0.0) if runner_up else 0.0
    score_gap = round(max(0.0, primary_score - runner_up_score), 3)
    review_recommended = primary_score < min_score or (runner_up is not None and score_gap <= review_gap)
    return {
        "selected_score": round(primary_score, 3),
        "runner_up_score": round(runner_up_score, 3),
        "score_gap": score_gap,
        "review_recommended": review_recommended,
        "review_reason": low_confidence_reason if review_recommended else "",
    }


def _section_directive_for_time(
    timeline_analysis: dict[str, Any] | None,
    time_sec: float,
) -> dict[str, Any] | None:
    for directive in list((timeline_analysis or {}).get("section_directives") or []):
        if not isinstance(directive, dict):
            continue
        start_sec = float(directive.get("start_sec", 0.0) or 0.0)
        end_sec = float(directive.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return directive
    return None


async def _plan_music_entry(
    *,
    music_plan: dict | None,
    subtitle_items: list[dict],
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict | None:
    if not music_plan:
        return None
    if not subtitle_items:
        music_plan["enter_sec"] = 0.0
        music_plan["entry_reason"] = "没有可用字幕，背景音乐从开头进入。"
        music_plan["timing_summary"] = {
            "selected_score": 0.0,
            "runner_up_score": 0.0,
            "score_gap": 0.0,
            "review_recommended": True,
            "review_reason": "缺少字幕节奏信息，建议确认 BGM 进入点。",
        }
        return music_plan

    settings = get_settings()
    hook_end_sec = float((timeline_analysis or {}).get("hook_end_sec") or 0.0)
    cta_start_sec = (timeline_analysis or {}).get("cta_start_sec")
    rankings = [
        dict(item) for item in _score_music_entry_candidates(subtitle_items, content_profile=content_profile)
        if float(item.get("enter_sec", 0.0) or 0.0) >= max(0.0, hook_end_sec - 0.05)
        and (
            cta_start_sec is None
            or float(item.get("enter_sec", 0.0) or 0.0) <= max(float(hook_end_sec), float(cta_start_sec) - 0.35)
        )
    ]
    allowed_rankings: list[dict[str, Any]] = []
    for item in rankings:
        directive = _section_directive_for_time(timeline_analysis, float(item.get("enter_sec", 0.0) or 0.0))
        if directive is None:
            allowed_rankings.append(item)
            continue
        if not bool(directive.get("music_entry_allowed", True)):
            continue
        item["score"] = round(
            min(0.99, float(item.get("score", 0.0) or 0.0) + float(directive.get("music_entry_bonus", 0.08) or 0.08)),
            3,
        )
        reasons = list(item.get("reasons") or [])
        reasons.append(f"落在 {str(directive.get('role') or '主体')} 段的安全音乐区间")
        item["reasons"] = reasons
        allowed_rankings.append(item)
    if allowed_rankings:
        allowed_rankings.sort(key=lambda item: (-float(item["score"]), float(item["enter_sec"])))
        rankings = allowed_rankings
    if not rankings:
        fallback_sec = round(float(subtitle_items[0].get("end_time", 0.0) or 0.0), 2)
        music_plan["enter_sec"] = max(0.0, fallback_sec)
        music_plan["entry_reason"] = "缺少可靠停顿点，回退到第一句结束后进入背景音乐。"
        music_plan["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="缺少可靠停顿点，建议确认 BGM 进入点。",
        )
        return music_plan

    chosen = rankings[0]
    music_plan["enter_sec"] = float(chosen["enter_sec"])
    music_plan["entry_reason"] = "；".join(chosen.get("reasons") or []) or "选择了最自然的语义停顿点进入背景音乐。"
    music_plan["timing_summary"] = _build_timing_summary(
        rankings,
        review_gap=float(settings.packaging_selection_review_gap),
        min_score=float(settings.packaging_selection_min_score),
        low_confidence_reason="BGM 候选进入点分差过小或信号不足，建议确认。",
    )
    return music_plan


async def _plan_insert_asset_slot(
    *,
    job_id: str,
    insert_plan: dict | None,
    subtitle_items: list[dict],
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None = None,
    allow_llm: bool = True,
) -> dict | None:
    if not insert_plan:
        return None
    settings = get_settings()
    if not subtitle_items:
        insert_plan["insert_after_sec"] = 0.0
        insert_plan["reason"] = "没有可用字幕，默认插入到开头。"
        insert_plan["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="缺少字幕节奏信息，建议确认插入位置。",
        )
        return insert_plan

    hook_end_sec = float((timeline_analysis or {}).get("hook_end_sec") or 0.0)
    cta_start_sec = (timeline_analysis or {}).get("cta_start_sec")
    semantic_sections = list((timeline_analysis or {}).get("semantic_sections") or [])
    section_directives = list((timeline_analysis or {}).get("section_directives") or [])
    section_actions = list((timeline_analysis or {}).get("section_actions") or [])
    resolved_editing_skill = (timeline_analysis or {}).get("editing_skill") or {}

    candidates = [
        item for item in subtitle_items
        if float(item.get("end_time", 0.0) or 0.0) > max(8.0, hook_end_sec + 0.15)
        and (
            cta_start_sec is None
            or float(item.get("end_time", 0.0) or 0.0) < float(cta_start_sec) - 0.4
        )
    ]
    detail_starts = {
        round(float(section.get("start_sec", 0.0) or 0.0), 2)
        for section in semantic_sections
        if str(section.get("role") or "") in {"detail", "body"}
    }
    allowed_windows = [
        {
            "index": int(section.get("index", -1) or -1),
            "role": str(section.get("role") or ""),
            "start_sec": float(section.get("start_sec", 0.0) or 0.0),
            "end_sec": float(section.get("end_sec", 0.0) or 0.0),
            "priority": float(section.get("insert_priority", 0.0) or 0.0),
            "anchor_sec": float(
                section.get(
                    "anchor_sec",
                    (float(section.get("start_sec", 0.0) or 0.0) + float(section.get("end_sec", 0.0) or 0.0)) / 2.0,
                )
                or 0.0
            ),
        }
        for section in section_directives
        if isinstance(section, dict) and bool(section.get("insert_allowed"))
    ]
    action_windows = [
        {
            "index": int(action.get("index", -1) or -1),
            "role": str(action.get("role") or ""),
            "start_sec": float(action.get("start_sec", 0.0) or 0.0),
            "end_sec": float(action.get("end_sec", 0.0) or 0.0),
            "priority": float(action.get("action_priority", 0.0) or 0.0),
            "anchor_sec": float(action.get("broll_anchor_sec", action.get("start_sec", 0.0)) or 0.0),
            "packaging_intent": str(action.get("packaging_intent") or ""),
        }
        for action in section_actions
        if isinstance(action, dict) and bool(action.get("broll_allowed"))
    ]

    def _windows_containing_time(windows: list[dict[str, float | int | str]], time_sec: float) -> list[dict[str, float | int | str]]:
        return [
            window
            for window in windows
            if float(window.get("start_sec", 0.0) or 0.0) - 1e-6 <= time_sec <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
        ]

    def _nearest_window(windows: list[dict[str, float | int | str]], time_sec: float) -> dict[str, float | int | str] | None:
        if not windows:
            return None
        return sorted(
            windows,
            key=lambda window: (
                -float(window.get("priority", 0.0) or 0.0),
                abs(time_sec - float(window.get("anchor_sec", 0.0) or 0.0)),
                float(window.get("start_sec", 0.0) or 0.0),
            ),
        )[0]

    preferred_insert_windows: list[dict[str, float | int | str]] = []

    def _apply_insert_window(plan: dict, chosen_sec: float) -> dict:
        primary_windows = preferred_insert_windows or action_windows or allowed_windows
        primary_match = _nearest_window(_windows_containing_time(primary_windows, chosen_sec), chosen_sec)
        selected_window = primary_match or _nearest_window(primary_windows, chosen_sec)
        if not selected_window:
            plan["insert_after_sec"] = round(float(chosen_sec), 3)
            return plan

        window_start = float(selected_window.get("start_sec", chosen_sec) or chosen_sec)
        window_end = float(selected_window.get("end_sec", chosen_sec) or chosen_sec)
        window_anchor = float(selected_window.get("anchor_sec", chosen_sec) or chosen_sec)
        if window_end < window_start:
            window_start, window_end = window_end, window_start
        resolved_sec = float(chosen_sec)
        if resolved_sec < window_start - 1e-6 or resolved_sec > window_end + 1e-6:
            resolved_sec = window_anchor
        resolved_sec = max(window_start, min(resolved_sec, window_end))
        plan["insert_after_sec"] = round(resolved_sec, 3)
        plan["insert_section_role"] = str(selected_window.get("role") or "")
        plan["insert_packaging_intent"] = str(selected_window.get("packaging_intent") or "")
        if int(selected_window.get("index", -1) or -1) >= 0:
            plan["insert_section_index"] = int(selected_window.get("index", -1) or -1)
        plan["broll_window"] = {
            "start_sec": round(window_start, 3),
            "end_sec": round(window_end, 3),
            "anchor_sec": round(max(window_start, min(window_anchor, window_end)), 3),
            "priority": round(float(selected_window.get("priority", 0.0) or 0.0), 3),
        }
        return plan

    def _apply_insert_asset_strategy(plan: dict) -> dict:
        candidate_assets = list(plan.get("candidate_assets") or [])
        if not candidate_assets:
            if plan.get("asset_id") and plan.get("path"):
                candidate_assets = [
                    {
                        "asset_id": str(plan.get("asset_id") or ""),
                        "path": str(plan.get("path") or ""),
                        "original_name": str(plan.get("original_name") or ""),
                        "insert_archetype": str(plan.get("insert_archetype") or ""),
                        "insert_motion_profile": str(plan.get("insert_motion_profile") or ""),
                        "insert_transition_style": str(plan.get("insert_transition_style") or ""),
                        "insert_target_duration_sec": float(plan.get("insert_target_duration_sec", 0.0) or 0.0),
                        "selection_score": 0.0,
                        "selection_reasons": [],
                    }
                ]
            else:
                return plan

        rankings = rank_insert_candidates_for_section(
            candidate_assets,
            section_role=str(plan.get("insert_section_role") or ""),
            packaging_intent=str(plan.get("insert_packaging_intent") or ""),
            content_profile=content_profile,
            editing_skill=resolved_editing_skill if isinstance(resolved_editing_skill, dict) else None,
        )
        if not rankings:
            return plan
        selected = dict(rankings[0]["candidate"])
        plan["asset_id"] = str(selected.get("asset_id") or plan.get("asset_id") or "")
        plan["path"] = str(selected.get("path") or plan.get("path") or "")
        plan["original_name"] = str(selected.get("original_name") or plan.get("original_name") or "")
        plan["insert_archetype"] = str(selected.get("insert_archetype") or plan.get("insert_archetype") or "generic_broll")
        plan["insert_motion_profile"] = str(selected.get("insert_motion_profile") or plan.get("insert_motion_profile") or "balanced_hold")
        plan["insert_transition_style"] = str(selected.get("insert_transition_style") or plan.get("insert_transition_style") or "straight_cut")
        plan["insert_target_duration_sec"] = round(float(selected.get("insert_target_duration_sec", 0.0) or 0.0), 3)
        plan["insert_strategy_summary"] = {
            "selected_asset_id": plan["asset_id"],
            "selected_score": round(float(rankings[0].get("score", 0.0) or 0.0), 3),
            "reasons": list(rankings[0].get("reasons") or []),
        }
        return plan
    if detail_starts:
        prioritized = [
            item for item in candidates
            if round(float(item.get("start_time", 0.0) or 0.0), 2) in detail_starts
            or round(float(item.get("end_time", 0.0) or 0.0), 2) in detail_starts
        ]
        if prioritized:
            candidates = prioritized
    elif action_windows:
        action_windows.sort(key=lambda item: (-float(item.get("priority", 0.0) or 0.0), float(item.get("start_sec", 0.0) or 0.0)))
        top_priority = float(action_windows[0].get("priority", 0.0) or 0.0)
        preferred_windows = [
            window
            for window in action_windows
            if abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
        ]
        prioritized = [
            item for item in candidates
            if any(
                float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                <= float(item.get("end_time", 0.0) or 0.0)
                <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                for window in preferred_windows
            )
        ]
        if prioritized:
            preferred_insert_windows = preferred_windows
            candidates = sorted(
                prioritized,
                key=lambda item: min(
                    abs(float(item.get("end_time", 0.0) or 0.0) - float(window.get("anchor_sec", 0.0) or 0.0))
                    for window in preferred_windows
                ),
            )
    elif allowed_windows:
        allowed_windows.sort(key=lambda item: (-float(item.get("priority", 0.0) or 0.0), float(item.get("start_sec", 0.0) or 0.0)))
        prioritized = [
            item for item in candidates
            if any(
                float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                <= float(item.get("end_time", 0.0) or 0.0)
                <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                for window in allowed_windows
            )
        ]
        if prioritized:
            top_priority = max(
                (
                    float(window.get("priority", 0.0) or 0.0)
                    for window in allowed_windows
                    if any(
                        float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                        <= float(item.get("end_time", 0.0) or 0.0)
                        <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                        for item in prioritized
                    )
                ),
                default=0.0,
            )
            preferred_insert_windows = [
                window
                for window in allowed_windows
                if abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
            ]
            candidates = [
                item for item in prioritized
                if any(
                    float(window.get("start_sec", 0.0) or 0.0) - 1e-6
                    <= float(item.get("end_time", 0.0) or 0.0)
                    <= float(window.get("end_sec", 0.0) or 0.0) + 1e-6
                    and abs(float(window.get("priority", 0.0) or 0.0) - top_priority) < 1e-6
                    for window in allowed_windows
                )
            ] or prioritized
    if not candidates:
        first = subtitle_items[min(len(subtitle_items) - 1, max(0, len(subtitle_items) // 2))]
        insert_plan["insert_after_sec"] = float(first.get("end_time", 0.0) or 0.0)
        insert_plan["reason"] = "字幕太短，回退到中间位置插入。"
        insert_plan["timing_summary"] = _build_timing_summary(
            [],
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="字幕太短，建议确认插入位置。",
        )
        return _apply_insert_asset_strategy(_apply_insert_window(insert_plan, float(insert_plan["insert_after_sec"] or 0.0)))

    transcript_excerpt = "\n".join(
        f"[{float(item.get('start_time', 0.0)):.1f}-{float(item.get('end_time', 0.0)):.1f}] "
        f"{_subtitle_text(item)}"
        for item in candidates[:48]
    )
    fallback = candidates[0] if action_windows else candidates[len(candidates) // 2]
    fallback_sec = float(fallback.get("end_time", 0.0) or 0.0)
    fallback_plan = dict(insert_plan)
    fallback_plan["insert_after_sec"] = fallback_sec
    fallback_plan["reason"] = "回退到中间自然停顿。"
    fallback_plan["timing_summary"] = _build_timing_summary(
        [],
        review_gap=float(settings.packaging_selection_review_gap),
        min_score=float(settings.packaging_selection_min_score),
        low_confidence_reason="插入点回退到默认停顿，建议确认。",
    )

    if not allow_llm:
        return _apply_insert_asset_strategy(_apply_insert_window(fallback_plan, float(fallback_plan["insert_after_sec"] or 0.0)))

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在给一条中文短视频安排一段植入素材的插入点。"
            "请根据字幕节奏和内容结构，找一个最自然、不打断关键论点的位置。"
            "优先选择一句话讲完之后、下一个话题开始之前；不要插在开场 8 秒内，也不要插在结尾收束段。"
            "如果视频主题是开箱评测，优先放在产品基础介绍讲完、进入细节体验之前。"
            "输出 JSON："
            '{"insert_after_sec":0.0,"reason":""}'
            f"\n视频信息：{json.dumps(content_profile or {}, ensure_ascii=False)}"
            f"\n候选字幕（已映射到剪后时间轴）：\n{transcript_excerpt}"
            f"\n如果拿不准，就返回 {fallback_sec:.1f} 附近的自然停顿。"
        )
        with track_usage_operation("render.insert_slot"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是短视频植入编排助手，只输出 JSON。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.1,
                max_tokens=300,
                json_mode=True,
            )
        data = response.as_json()
        chosen = float(data.get("insert_after_sec", fallback_sec) or fallback_sec)
        max_sec = float(candidates[-1].get("end_time", fallback_sec) or fallback_sec)
        insert_plan = _apply_insert_window(insert_plan, chosen)
        insert_plan["insert_after_sec"] = round(
            max(8.0, min(float(insert_plan.get("insert_after_sec", fallback_sec) or fallback_sec), max_sec)),
            3,
        )
        insert_plan["reason"] = str(data.get("reason") or "").strip() or "LLM 选择了较自然的转场点。"
        rankings = [
            {"score": 0.78, "enter_sec": insert_plan["insert_after_sec"]},
            {"score": 0.7, "enter_sec": fallback_sec},
        ]
        insert_plan["timing_summary"] = _build_timing_summary(
            rankings,
            review_gap=float(settings.packaging_selection_review_gap),
            min_score=float(settings.packaging_selection_min_score),
            low_confidence_reason="插入点候选分差过小或语义证据不足，建议确认。",
        )
        return _apply_insert_asset_strategy(insert_plan)
    except Exception:
        fallback_plan["reason"] = "LLM 未返回可靠结果，回退到中间自然停顿。"
        return _apply_insert_asset_strategy(_apply_insert_window(fallback_plan, float(fallback_plan["insert_after_sec"] or 0.0)))


async def _map_subtitles_to_packaged_timeline(
    subtitle_items: list[dict],
    render_plan: dict,
    *,
    keep_segments: list[dict[str, Any]] | None = None,
) -> list[dict]:
    if not subtitle_items:
        return []

    mapped = [dict(item) for item in subtitle_items]
    transition_offsets = _resolve_transition_overlap_offsets(
        render_plan,
        keep_segments=keep_segments or [],
    )
    if transition_offsets:
        mapped = _shift_timed_items_for_transition_overlaps(mapped, transition_offsets=transition_offsets)
    leading_offset = 0.0

    intro_plan = render_plan.get("intro")
    if intro_plan and intro_plan.get("path"):
        intro_duration = await _probe_media_duration(Path(intro_plan["path"]))
        if intro_duration > 0:
            leading_offset += intro_duration
            for item in mapped:
                item["start_time"] = float(item["start_time"]) + intro_duration
                item["end_time"] = float(item["end_time"]) + intro_duration

    insert_plan = render_plan.get("insert")
    if insert_plan and insert_plan.get("path"):
        insert_duration = await _probe_media_duration(Path(insert_plan["path"]))
        insert_after_sec = float(insert_plan.get("insert_after_sec", 0.0) or 0.0) + leading_offset
        effective_insert_duration = resolve_insert_effective_duration(insert_plan, source_duration=insert_duration)
        current_timeline_duration = max(
            (
                float(item.get("end_time", item.get("start_time", 0.0)) or 0.0)
                for item in mapped
            ),
            default=insert_after_sec,
        )
        added_insert_duration = resolve_insert_added_duration(
            insert_plan,
            runtime_duration_sec=effective_insert_duration,
            insert_after_sec=insert_after_sec,
            source_duration=current_timeline_duration,
        )
        if added_insert_duration > 0:
            mapped = _shift_subtitles_for_insert(
                mapped,
                insert_after_sec=insert_after_sec,
                insert_duration=added_insert_duration,
            )

    return _resegment_packaged_subtitles(
        _rewrite_packaged_subtitle_copy(
            mapped,
            render_plan=render_plan,
        ),
        render_plan=render_plan,
    )


async def _map_editing_accents_to_packaged_timeline(
    editing_accents: dict[str, Any] | None,
    render_plan: dict,
    *,
    keep_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    mapped = {
        **base,
        "transitions": dict(base.get("transitions") or {}),
        "emphasis_overlays": [dict(item) for item in base.get("emphasis_overlays") or []],
        "sound_effects": [dict(item) for item in base.get("sound_effects") or []],
    }
    transition_offsets = _resolve_transition_overlap_offsets(
        render_plan,
        keep_segments=keep_segments or [],
    )
    if transition_offsets:
        mapped["emphasis_overlays"] = _shift_timed_items_for_transition_overlaps(
            mapped.get("emphasis_overlays") or [],
            transition_offsets=transition_offsets,
        )
        mapped["sound_effects"] = _shift_sound_effects_for_transition_overlaps(
            mapped.get("sound_effects") or [],
            transition_offsets=transition_offsets,
        )
    leading_offset = 0.0

    intro_plan = render_plan.get("intro")
    if intro_plan and intro_plan.get("path"):
        intro_duration = await _probe_media_duration(Path(intro_plan["path"]))
        if intro_duration > 0:
            leading_offset += intro_duration
            for collection_name in ("emphasis_overlays", "sound_effects"):
                for item in mapped.get(collection_name) or []:
                    item["start_time"] = float(item.get("start_time", 0.0) or 0.0) + intro_duration
                    if "end_time" in item:
                        item["end_time"] = float(item.get("end_time", 0.0) or 0.0) + intro_duration

    insert_plan = render_plan.get("insert")
    if insert_plan and insert_plan.get("path"):
        insert_duration = await _probe_media_duration(Path(insert_plan["path"]))
        insert_after_sec = float(insert_plan.get("insert_after_sec", 0.0) or 0.0) + leading_offset
        effective_insert_duration = resolve_insert_effective_duration(insert_plan, source_duration=insert_duration)
        current_timeline_duration = max(
            (
                float(
                    item.get(
                        "end_time",
                        float(item.get("start_time", 0.0) or 0.0) + float(item.get("duration_sec", 0.0) or 0.0),
                    )
                    or 0.0
                )
                for collection_name in ("emphasis_overlays", "sound_effects")
                for item in mapped.get(collection_name) or []
            ),
            default=insert_after_sec,
        )
        added_insert_duration = resolve_insert_added_duration(
            insert_plan,
            runtime_duration_sec=effective_insert_duration,
            insert_after_sec=insert_after_sec,
            source_duration=current_timeline_duration,
        )
        if added_insert_duration > 0:
            mapped["emphasis_overlays"] = _shift_timed_items_for_insert(
                mapped.get("emphasis_overlays") or [],
                insert_after_sec=insert_after_sec,
                insert_duration=added_insert_duration,
            )
            mapped["sound_effects"] = _shift_sound_effects_for_insert(
                mapped.get("sound_effects") or [],
                insert_after_sec=insert_after_sec,
                insert_duration=added_insert_duration,
            )
        mapped = _apply_insert_accent_choreography(
            mapped,
            insert_plan=insert_plan,
            insert_after_sec=insert_after_sec,
            effective_insert_duration=effective_insert_duration,
            source_duration=max(current_timeline_duration, insert_after_sec),
        )

    return mapped


def _apply_insert_accent_choreography(
    editing_accents: dict[str, Any],
    *,
    insert_plan: dict[str, Any] | None,
    insert_after_sec: float,
    effective_insert_duration: float,
    source_duration: float,
) -> dict[str, Any]:
    if not isinstance(editing_accents, dict):
        return {}
    focus = str((insert_plan or {}).get("insert_overlay_focus") or "medium").strip().lower()
    packaging_intent = str((insert_plan or {}).get("insert_packaging_intent") or "").strip().lower()
    cta_protection = bool((insert_plan or {}).get("insert_cta_protection"))
    if not cta_protection and focus not in {"none", "medium", "high"}:
        return editing_accents

    overlap = resolve_insert_transition_overlap(
        insert_plan,
        runtime_duration_sec=effective_insert_duration,
        insert_after_sec=insert_after_sec,
        source_duration=source_duration,
    )
    window_start = round(max(0.0, insert_after_sec - float(overlap.get("entry_sec", 0.0) or 0.0)), 3)
    window_end = round(max(window_start, window_start + max(0.0, float(effective_insert_duration or 0.0))), 3)
    guard = 0.28 if focus == "high" else 0.1 if focus == "medium" else 0.16
    nearby_start = max(0.0, window_start - guard)
    nearby_end = window_end + guard

    def _overlay_midpoint(item: dict[str, Any]) -> float:
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", start_time) or start_time)
        return (start_time + end_time) / 2.0

    overlays = [dict(item) for item in editing_accents.get("emphasis_overlays") or []]
    sounds = [dict(item) for item in editing_accents.get("sound_effects") or []]
    near_overlays = [item for item in overlays if nearby_start - 1e-6 <= _overlay_midpoint(item) <= nearby_end + 1e-6]
    far_overlays = [item for item in overlays if item not in near_overlays]
    near_sounds = [
        item
        for item in sounds
        if nearby_start - 1e-6 <= float(item.get("start_time", 0.0) or 0.0) <= nearby_end + 1e-6
    ]
    far_sounds = [item for item in sounds if item not in near_sounds]

    if cta_protection or focus == "none":
        editing_accents["emphasis_overlays"] = far_overlays
        editing_accents["sound_effects"] = far_sounds
        return editing_accents

    if focus == "medium":
        editing_accents["emphasis_overlays"] = [
            item
            for item in overlays
            if not (window_start - 1e-6 <= _overlay_midpoint(item) <= window_end + 1e-6)
        ]
        editing_accents["sound_effects"] = [
            item
            for item in sounds
            if not (window_start - 1e-6 <= float(item.get("start_time", 0.0) or 0.0) <= window_end + 1e-6)
        ]
        return editing_accents

    anchor_start = round(min(window_end, window_start + min(0.08, max(0.04, effective_insert_duration * 0.15))), 3)
    primary_overlay = None
    if near_overlays:
        primary_overlay = min(
            near_overlays,
            key=lambda item: abs(_overlay_midpoint(item) - anchor_start),
        )
        primary_overlay = dict(primary_overlay)
        original_duration = max(
            0.32,
            float(primary_overlay.get("end_time", anchor_start + 0.45) or anchor_start + 0.45)
            - float(primary_overlay.get("start_time", anchor_start) or anchor_start),
        )
        overlay_duration = min(max(original_duration, 0.38), max(0.4, min(0.72, effective_insert_duration * 0.6)))
        primary_overlay["start_time"] = anchor_start
        primary_overlay["end_time"] = round(min(window_end, anchor_start + overlay_duration), 3)
        far_overlays.append(primary_overlay)

    if near_sounds or primary_overlay is not None:
        sound_tokens = _resolve_insert_sound_tokens(packaging_intent)
        primary_sound = dict(near_sounds[0]) if near_sounds else {}
        primary_sound["start_time"] = anchor_start
        primary_sound["duration_sec"] = sound_tokens["duration_sec"]
        primary_sound["frequency"] = sound_tokens["frequency"]
        primary_sound["volume"] = sound_tokens["volume"]
        far_sounds.append(primary_sound)

    editing_accents["emphasis_overlays"] = sorted(far_overlays, key=lambda item: float(item.get("start_time", 0.0) or 0.0))
    editing_accents["sound_effects"] = sorted(far_sounds, key=lambda item: float(item.get("start_time", 0.0) or 0.0))
    return editing_accents


def _resolve_insert_sound_tokens(packaging_intent: str) -> dict[str, float]:
    intent = str(packaging_intent or "").strip().lower()
    mapping = {
        "detail_support": {"duration_sec": 0.07, "frequency": 1120.0, "volume": 0.045},
        "body_support": {"duration_sec": 0.075, "frequency": 980.0, "volume": 0.042},
        "hook_focus": {"duration_sec": 0.08, "frequency": 1240.0, "volume": 0.048},
    }
    return mapping.get(intent, {"duration_sec": 0.075, "frequency": 1040.0, "volume": 0.042})


def _resolve_packaged_render_variant(
    *,
    original_source_path: Path,
    original_editorial_timeline: dict[str, Any],
    original_subtitle_items: list[dict[str, Any]],
    variant_source_path: Path | None = None,
    variant_duration_sec: float | None = None,
    variant_subtitle_items: list[dict[str, Any]] | None = None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    if variant_source_path is None:
        return (
            original_source_path,
            dict(original_editorial_timeline),
            [dict(item) for item in original_subtitle_items],
        )

    duration = max(0.0, float(variant_duration_sec or 0.0))
    if duration <= 0.0:
        raise ValueError("variant_duration_sec must be positive when variant_source_path is provided")

    return (
        variant_source_path,
        {
            "segments": [
                {
                    "type": "keep",
                    "start": 0.0,
                    "end": duration,
                }
            ]
        },
        [dict(item) for item in (variant_subtitle_items or [])],
    )


async def _render_full_track_avatar_video(
    *,
    job_id: str,
    avatar_plan: dict[str, Any],
    source_plain_video_path: Path,
    debug_dir: Path | None,
) -> Path | None:
    presenter_id = str(avatar_plan.get("presenter_id") or "").strip()
    if not presenter_id:
        return None

    audio_drive_path = source_plain_video_path.with_name(f"{source_plain_video_path.stem}.avatar_drive.wav")
    await extract_audio(source_plain_video_path, audio_drive_path)
    duration = float((await probe(source_plain_video_path)).duration or 0.0)
    if duration <= 0:
        return None

    render_request = {
        "provider": avatar_plan.get("provider") or get_settings().avatar_provider,
        "base_url": get_settings().avatar_api_base_url.rstrip("/"),
        "submit_endpoint": get_settings().avatar_api_base_url.rstrip("/") + "/easy/submit",
        "query_endpoint": get_settings().avatar_api_base_url.rstrip("/") + "/easy/query",
        "job_id": job_id,
        "presenter_id": presenter_id,
        "layout_template": avatar_plan.get("layout_template") or get_settings().avatar_layout_template,
        "segments": [
            {
                "segment_id": "avatar_full_track",
                "script": "",
                "start_time": 0.0,
                "duration_sec": round(duration, 3),
                "audio_url": str(audio_drive_path),
            }
        ],
    }
    render_execution = await asyncio.to_thread(
        get_avatar_provider().execute_render,
        job_id=job_id,
        request=render_request,
    )
    segments = list(render_execution.get("segments") or [])
    if not segments:
        return None
    first_segment = segments[0] or {}
    if str(first_segment.get("status") or "") != "success":
        raise RuntimeError(str(first_segment.get("error") or "avatar_full_track_render_failed"))
    result_value = str(first_segment.get("local_result_path") or "").strip()
    if not result_value:
        raise RuntimeError("avatar_full_track_result_missing")
    result_path = Path(result_value)
    if not result_path.exists():
        if debug_dir is not None:
            debug_dir.mkdir(parents=True, exist_ok=True)
            (debug_dir / "avatar.render_execution.json").write_text(
                json.dumps(render_execution, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return None
    return result_path


def _remap_avatar_segments_to_timeline(
    avatar_segments: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    remapped = remap_subtitles_to_timeline(
        [
            {
                **segment,
                "text_raw": segment.get("script"),
                "text_norm": segment.get("script"),
                "text_final": segment.get("script"),
                "end_time": float(segment.get("end_time") or 0.0)
                or (float(segment.get("start_time") or 0.0) + float(segment.get("duration_sec") or 0.0)),
            }
            for segment in avatar_segments
        ],
        keep_segments,
    )
    normalized: list[dict[str, Any]] = []
    for item in remapped:
        start = float(item.get("start_time") or 0.0)
        end = float(item.get("end_time") or start)
        normalized.append(
            {
                **item,
                "start_time": start,
                "end_time": end,
                "duration_sec": round(max(0.1, end - start), 3),
            }
        )
    return normalized


async def _overlay_avatar_segments_picture_in_picture(
    *,
    base_video_path: Path,
    avatar_segments: list[dict[str, Any]],
    output_path: Path,
    position: str,
    scale: float,
    margin: int,
    safe_margin_ratio: float = 0.08,
    corner_radius: int = 0,
    border_width: int = 0,
    border_color: str = "#F4E4B8",
) -> Path:
    available_segments = [
        segment
        for segment in avatar_segments
        if str(segment.get("video_local_path") or "").strip() and Path(str(segment.get("video_local_path"))).exists()
    ]
    if not available_segments:
        raise RuntimeError("avatar_segment_result_missing")

    base_probe = await probe(base_video_path)
    base_width = max(1, int(getattr(base_probe, "width", 0) or 0))
    base_height = max(1, int(getattr(base_probe, "height", 0) or 0))
    if base_width <= 1:
        raise RuntimeError("Unable to determine base video width for avatar picture-in-picture overlay")

    sample_probe = await probe(Path(str(available_segments[0]["video_local_path"])))
    avatar_width = max(1, int(getattr(sample_probe, "width", 0) or 1))
    avatar_height = max(1, int(getattr(sample_probe, "height", 0) or 1))
    overlay_width = max(180, int(round(base_width * max(0.12, min(scale, 0.45)))))
    overlay_height = max(180, int(round(overlay_width * (avatar_height / avatar_width))))
    resolved_margin = max(margin, int(round(min(base_width, base_height) * max(0.02, min(safe_margin_ratio, 0.2)))))
    resolved_border_width = max(0, min(12, int(border_width)))
    frame_width = overlay_width + resolved_border_width * 2
    frame_height = overlay_height + resolved_border_width * 2
    safe_border_color = str(border_color or "#F4E4B8").strip()
    if not safe_border_color.startswith("#"):
        safe_border_color = f"#{safe_border_color}"
    border_rgb = f"0x{safe_border_color.lstrip('#')}"
    position_map = {
        "top_left": (str(resolved_margin), str(resolved_margin)),
        "top_right": (f"main_w-overlay_w-{resolved_margin}", str(resolved_margin)),
        "bottom_left": (str(resolved_margin), f"main_h-overlay_h-{resolved_margin}"),
        "bottom_right": (f"main_w-overlay_w-{resolved_margin}", f"main_h-overlay_h-{resolved_margin}"),
    }
    overlay_x, overlay_y = position_map.get(position, position_map["bottom_right"])
    resolved_corner_radius = _resolve_overlay_corner_radius(
        corner_radius=corner_radius,
        width=frame_width if resolved_border_width > 0 else overlay_width,
        height=frame_height if resolved_border_width > 0 else overlay_height,
    )
    avatar_corner_radius = _resolve_overlay_corner_radius(
        corner_radius=max(0, resolved_corner_radius - resolved_border_width),
        width=overlay_width,
        height=overlay_height,
    )

    cmd = ["ffmpeg", "-y", "-i", str(base_video_path)]
    for segment in available_segments:
        cmd.extend(["-i", str(segment["video_local_path"])])

    filter_parts: list[str] = []
    current_label = "0:v"
    for index, segment in enumerate(available_segments, start=1):
        start_time = max(0.0, float(segment.get("start_time") or 0.0))
        avatar_filter = _build_rounded_rgba_filter(
            input_label=f"{index}:v",
            output_label=f"pipfg{index}",
            width=overlay_width,
            height=overlay_height,
            corner_radius=avatar_corner_radius,
            extra_filters=f"setpts=PTS+{start_time}/TB,scale={overlay_width}:{overlay_height}",
        )
        filter_parts.append(avatar_filter)
        if resolved_border_width > 0:
            filter_parts.append(_build_rounded_color_filter(
                output_label=f"pipbg{index}",
                color=border_rgb,
                width=frame_width,
                height=frame_height,
                corner_radius=resolved_corner_radius,
            ))
            filter_parts.append(
                f"[pipbg{index}][pipfg{index}]overlay={resolved_border_width}:{resolved_border_width}:format=auto:alpha=straight[pip{index}]"
            )
        else:
            filter_parts.append(f"[pipfg{index}]copy[pip{index}]")
        next_label = f"vseg{index}"
        filter_parts.append(
            f"[{current_label}][pip{index}]overlay=x={overlay_x}:y={overlay_y}:eof_action=pass:format=auto:alpha=straight[{next_label}]"
        )
        current_label = next_label

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{current_label}]",
            "-map",
            "0:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-c:a",
            "copy",
            str(output_path),
        ]
    )
    result = await asyncio.get_running_loop().run_in_executor(
        None,
        lambda: subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=get_settings().ffmpeg_timeout_sec,
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg avatar segments picture-in-picture overlay failed: {result.stderr[-2000:]}")
    return output_path


async def _overlay_avatar_picture_in_picture(
    *,
    base_video_path: Path,
    avatar_video_path: Path,
    output_path: Path,
    position: str,
    scale: float,
    margin: int,
    safe_margin_ratio: float = 0.08,
    corner_radius: int = 0,
    border_width: int = 0,
    border_color: str = "#F4E4B8",
) -> Path:
    base_probe = await probe(base_video_path)
    base_width = max(1, int(getattr(base_probe, "width", 0) or 0))
    base_height = max(1, int(getattr(base_probe, "height", 0) or 0))
    if base_width <= 1:
        raise RuntimeError("Unable to determine base video width for avatar picture-in-picture overlay")
    avatar_probe = await probe(avatar_video_path)
    avatar_width = max(1, int(getattr(avatar_probe, "width", 0) or 1))
    avatar_height = max(1, int(getattr(avatar_probe, "height", 0) or 1))
    overlay_width = max(180, int(round(base_width * max(0.12, min(scale, 0.45)))))
    overlay_height = max(180, int(round(overlay_width * (avatar_height / avatar_width))))
    avatar_extra_filters = _build_avatar_picture_in_picture_filters(
        base_duration=float(getattr(base_probe, "duration", 0.0) or 0.0),
        base_fps=float(getattr(base_probe, "fps", 0.0) or 0.0),
        avatar_duration=float(getattr(avatar_probe, "duration", 0.0) or 0.0),
        avatar_fps=float(getattr(avatar_probe, "fps", 0.0) or 0.0),
        overlay_width=overlay_width,
        overlay_height=overlay_height,
    )
    resolved_margin = max(margin, int(round(min(base_width, base_height) * max(0.02, min(safe_margin_ratio, 0.2)))))
    resolved_border_width = max(0, min(12, int(border_width)))
    frame_width = overlay_width + resolved_border_width * 2
    frame_height = overlay_height + resolved_border_width * 2
    safe_border_color = str(border_color or "#F4E4B8").strip()
    if not safe_border_color.startswith("#"):
        safe_border_color = f"#{safe_border_color}"
    border_rgb = f"0x{safe_border_color.lstrip('#')}"
    position_map = {
        "top_left": (str(resolved_margin), str(resolved_margin)),
        "top_right": (f"main_w-overlay_w-{resolved_margin}", str(resolved_margin)),
        "bottom_left": (str(resolved_margin), f"main_h-overlay_h-{resolved_margin}"),
        "bottom_right": (f"main_w-overlay_w-{resolved_margin}", f"main_h-overlay_h-{resolved_margin}"),
    }
    overlay_x, overlay_y = position_map.get(position, position_map["bottom_right"])
    resolved_corner_radius = _resolve_overlay_corner_radius(
        corner_radius=corner_radius,
        width=frame_width if resolved_border_width > 0 else overlay_width,
        height=frame_height if resolved_border_width > 0 else overlay_height,
    )
    avatar_corner_radius = _resolve_overlay_corner_radius(
        corner_radius=max(0, resolved_corner_radius - resolved_border_width),
        width=overlay_width,
        height=overlay_height,
    )

    if resolved_border_width > 0:
        filter_chain = (
            f"{_build_rounded_color_filter(output_label='pipbg', color=border_rgb, width=frame_width, height=frame_height, corner_radius=resolved_corner_radius)};"
            f"{_build_rounded_rgba_filter(input_label='1:v', output_label='pipfg', width=overlay_width, height=overlay_height, corner_radius=avatar_corner_radius, extra_filters=avatar_extra_filters)};"
            f"[pipbg][pipfg]overlay={resolved_border_width}:{resolved_border_width}:format=auto:alpha=straight[pip];"
            f"[0:v][pip]overlay=x={overlay_x}:y={overlay_y}:eof_action=pass:format=auto:alpha=straight[vout]"
        )
    else:
        filter_chain = (
            f"{_build_rounded_rgba_filter(input_label='1:v', output_label='pip', width=overlay_width, height=overlay_height, corner_radius=avatar_corner_radius, extra_filters=avatar_extra_filters)};"
            f"[0:v][pip]overlay=x={overlay_x}:y={overlay_y}:eof_action=pass:format=auto:alpha=straight[vout]"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(base_video_path),
        "-i",
        str(avatar_video_path),
        "-filter_complex",
        filter_chain,
        "-map",
        "[vout]",
        "-map",
        "0:a:0",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-c:a",
        "copy",
        str(output_path),
    ]
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
        timeout=get_settings().ffmpeg_timeout_sec,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg avatar picture-in-picture overlay failed: {result.stderr[-2000:]}")
    return output_path


def _resolve_overlay_corner_radius(*, corner_radius: int, width: int, height: int) -> int:
    return max(0, min(int(corner_radius or 0), max(0, width // 2), max(0, height // 2)))


def _build_avatar_picture_in_picture_filters(
    *,
    base_duration: float,
    base_fps: float,
    avatar_duration: float,
    avatar_fps: float,
    overlay_width: int,
    overlay_height: int,
) -> str:
    filters = [f"scale={overlay_width}:{overlay_height}"]
    if avatar_duration > 0 and base_duration > 0:
        duration_ratio = max(0.5, min(2.0, base_duration / avatar_duration))
        if abs(duration_ratio - 1.0) >= 0.0005:
            filters.append(f"setpts=PTS*{duration_ratio:.8f}")
        filters.append(f"trim=duration={base_duration:.6f}")
    if base_fps > 0:
        fps_expr = _ffmpeg_fps_expr(base_fps)
        fps_gap = abs(base_fps - avatar_fps)
        if avatar_fps > 0 and fps_gap >= 0.5 and avatar_fps < base_fps:
            filters.append(
                f"settb=AVTB,framerate=fps={fps_expr}:interp_start=15:interp_end=240:scene=100"
            )
        else:
            filters.append(f"fps={fps_expr}")
    return ",".join(filters)


def _ffmpeg_fps_expr(fps: float) -> str:
    canonical = (
        (23.976, "24000/1001"),
        (24.0, "24"),
        (25.0, "25"),
        (29.97, "30000/1001"),
        (30.0, "30"),
        (50.0, "50"),
        (59.94, "60000/1001"),
        (60.0, "60"),
    )
    for target, expr in canonical:
        if abs(fps - target) < 0.05:
            return expr
    rounded = round(fps)
    if abs(fps - rounded) < 0.01 and rounded > 0:
        return str(int(rounded))
    return f"{fps:.6f}"


def _build_rounded_color_filter(
    *,
    output_label: str,
    color: str,
    width: int,
    height: int,
    corner_radius: int,
) -> str:
    if corner_radius <= 0:
        return f"color=c={color}:s={width}x{height},format=rgba[{output_label}]"
    alpha_expr = _build_rounded_alpha_expr(width=width, height=height, corner_radius=corner_radius)
    return (
        f"color=c={color}:s={width}x{height},format=yuva444p,"
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':alpha_expr='{alpha_expr}'[{output_label}]"
    )


def _build_rounded_rgba_filter(
    *,
    input_label: str,
    output_label: str,
    width: int,
    height: int,
    corner_radius: int,
    extra_filters: str = "",
) -> str:
    filter_prefix = f"[{input_label}]"
    if extra_filters:
        filter_prefix += f"{extra_filters},"
    filter_prefix += "format=yuva444p"
    if corner_radius <= 0:
        return f"{filter_prefix}[{output_label}]"
    alpha_expr = _build_rounded_alpha_expr(width=width, height=height, corner_radius=corner_radius)
    return (
        f"{filter_prefix},"
        f"geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':alpha_expr='{alpha_expr}'[{output_label}]"
    )


def _build_rounded_alpha_expr(*, width: int, height: int, corner_radius: int) -> str:
    radius = _resolve_overlay_corner_radius(corner_radius=corner_radius, width=width, height=height)
    if radius <= 0:
        return "255"
    max(0, width - 1)
    max(0, height - 1)
    right_center = width - radius - 1
    bottom_center = height - radius - 1
    radius_sq = radius * radius
    inner_right = max(radius, width - radius - 1)
    inner_bottom = max(radius, height - radius - 1)
    core_checks = [
        f"between(X,{radius},{inner_right})",
        f"between(Y,{radius},{inner_bottom})",
        f"lt(X,{radius})*lt(Y,{radius})*lte((X-{radius})*(X-{radius})+(Y-{radius})*(Y-{radius}),{radius_sq})",
        f"gte(X,{inner_right})*lt(Y,{radius})*lte((X-{right_center})*(X-{right_center})+(Y-{radius})*(Y-{radius}),{radius_sq})",
        f"lt(X,{radius})*gte(Y,{inner_bottom})*lte((X-{radius})*(X-{radius})+(Y-{bottom_center})*(Y-{bottom_center}),{radius_sq})",
        f"gte(X,{inner_right})*gte(Y,{inner_bottom})*lte((X-{right_center})*(X-{right_center})+(Y-{bottom_center})*(Y-{bottom_center}),{radius_sq})",
    ]
    inside_expr = "+".join(core_checks)
    return f"if(gt({inside_expr},0),255,0)"


async def _probe_media_duration(path: Path) -> float:
    try:
        return max(0.0, float((await probe(path)).duration or 0.0))
    except Exception:
        return 0.0


async def _wait_for_media_ready(path: Path, *, timeout_sec: float = 20.0) -> Path:
    started = time.monotonic()
    last_error: Exception | None = None
    while time.monotonic() - started < timeout_sec:
        if path.exists() and path.stat().st_size > 0:
            try:
                await probe(path)
                return path
            except Exception as exc:
                last_error = exc
        await asyncio.sleep(0.5)
    if last_error is not None:
        raise last_error
    raise FileNotFoundError(path)


def _shift_subtitles_for_insert(
    subtitle_items: list[dict],
    *,
    insert_after_sec: float,
    insert_duration: float,
) -> list[dict]:
    return _shift_timed_items_for_insert(
        subtitle_items,
        insert_after_sec=insert_after_sec,
        insert_duration=insert_duration,
    )


def _shift_timed_items_for_insert(
    items: list[dict],
    *,
    insert_after_sec: float,
    insert_duration: float,
) -> list[dict]:
    shifted: list[dict] = []
    for item in items:
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", start_time + float(item.get("duration_sec", 0.0) or 0.0)) or 0.0)
        if end_time <= insert_after_sec:
            shifted.append(dict(item))
            continue
        if start_time >= insert_after_sec:
            shifted_item = dict(item)
            shifted_item["start_time"] = start_time + insert_duration
            if "end_time" in item or "duration_sec" in item:
                shifted_item["end_time"] = end_time + insert_duration
            shifted.append(shifted_item)
            continue

        head = dict(item)
        head["start_time"] = start_time
        if "end_time" in item or "duration_sec" in item:
            head["end_time"] = insert_after_sec

        tail = dict(item)
        tail["start_time"] = insert_after_sec + insert_duration
        if "end_time" in item or "duration_sec" in item:
            tail["end_time"] = end_time + insert_duration
        shifted.extend([head, tail])
    return shifted


def _shift_sound_effects_for_insert(
    items: list[dict],
    *,
    insert_after_sec: float,
    insert_duration: float,
) -> list[dict]:
    shifted: list[dict] = []
    for item in items:
        shifted_item = dict(item)
        start_time = float(item.get("start_time", 0.0) or 0.0)
        if start_time >= insert_after_sec:
            shifted_item["start_time"] = start_time + insert_duration
        shifted.append(shifted_item)
    return shifted


def _build_variant_timeline_bundle(
    *,
    editorial_timeline_id: Any,
    render_plan_timeline_id: Any,
    keep_segments: list[dict[str, Any]],
    editorial_analysis: dict[str, Any] | None = None,
    render_plan: dict[str, Any],
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cloned_editorial_analysis = _clone_json_like(editorial_analysis or {})
    bundle = {
        "timeline_rules": {
            "editorial_timeline_id": str(editorial_timeline_id or "").strip() or None,
            "render_plan_timeline_id": str(render_plan_timeline_id or "").strip() or None,
            "keep_segments": [dict(segment) for segment in keep_segments],
            "editorial_analysis": cloned_editorial_analysis,
            "timeline_analysis": _clone_json_like(render_plan.get("timeline_analysis") or {}),
            "editing_skill": _clone_json_like(render_plan.get("editing_skill") or {}),
            "section_choreography": _clone_json_like(render_plan.get("section_choreography") or {}),
            "diagnostics": _build_variant_timeline_diagnostics(
                editorial_analysis=cloned_editorial_analysis,
                timeline_analysis=render_plan.get("timeline_analysis") or {},
            ),
            "packaging": {
                "intro": _clone_json_like(render_plan.get("intro")),
                "outro": _clone_json_like(render_plan.get("outro")),
                "insert": _clone_json_like(render_plan.get("insert")),
                "watermark": _clone_json_like(render_plan.get("watermark")),
                "music": _clone_json_like(render_plan.get("music")),
            },
            "editing_accents": _clone_json_like(render_plan.get("editing_accents") or {}),
        },
        "variants": {name: dict(payload) for name, payload in variants.items() if isinstance(payload, dict)},
    }
    bundle["validation"] = _validate_variant_timeline_bundle(bundle)
    return bundle


def _build_variant_timeline_diagnostics(
    *,
    editorial_analysis: dict[str, Any] | None,
    timeline_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    keep_energy_segments = [
        dict(item)
        for item in list((editorial_analysis or {}).get("keep_energy_segments") or [])
        if isinstance(item, dict)
    ]
    accepted_cuts = [
        dict(item)
        for item in list((editorial_analysis or {}).get("accepted_cuts") or [])
        if isinstance(item, dict)
    ]
    high_energy_keeps = [
        {
            "start": round(float(item.get("start", 0.0) or 0.0), 3),
            "end": round(float(item.get("end", 0.0) or 0.0), 3),
            "keep_energy": round(float(item.get("keep_energy", 0.0) or 0.0), 3),
            "section_role": str(item.get("section_role") or ""),
            "packaging_intent": str(item.get("packaging_intent") or ""),
        }
        for item in keep_energy_segments
        if float(item.get("keep_energy", 0.0) or 0.0) >= 1.0
    ]
    high_risk_cuts = [
        {
            "start": round(float(item.get("start", 0.0) or 0.0), 3),
            "end": round(float(item.get("end", 0.0) or 0.0), 3),
            "reason": str(item.get("reason") or ""),
            "boundary_keep_energy": round(float(item.get("boundary_keep_energy", 0.0) or 0.0), 3),
            "left_keep_role": str(item.get("left_keep_role") or ""),
            "right_keep_role": str(item.get("right_keep_role") or ""),
        }
        for item in accepted_cuts
        if float(item.get("boundary_keep_energy", 0.0) or 0.0) >= 1.0
    ]
    review_reasons: list[str] = []
    if high_risk_cuts:
        review_reasons.append("存在贴近高能量保留段的 cut，建议复核边界。")
    if any(str(item.get("section_role") or "") == "hook" for item in high_energy_keeps):
        review_reasons.append("Hook 段存在高能量保留片段，建议确认开场节奏。")
    return {
        "keep_energy_summary": _clone_json_like((editorial_analysis or {}).get("keep_energy_summary") or {}),
        "high_energy_keeps": high_energy_keeps[:8],
        "high_risk_cuts": high_risk_cuts[:8],
        "review_flags": {
            "review_recommended": bool(high_risk_cuts),
            "review_reasons": review_reasons,
            "hook_end_sec": round(float((timeline_analysis or {}).get("hook_end_sec") or 0.0), 3),
            "cta_start_sec": (
                round(float((timeline_analysis or {}).get("cta_start_sec") or 0.0), 3)
                if (timeline_analysis or {}).get("cta_start_sec") is not None
                else None
            ),
        },
    }


def _build_variant_timeline_entry(
    *,
    media_path: Path | None,
    srt_path: Path | None,
    media_meta: Any | None,
    subtitle_events: list[dict[str, Any]] | None,
    transition_offsets: list[tuple[float, float]] | None,
    segments: list[dict[str, Any]] | None,
    overlay_events: dict[str, Any] | None = None,
    quality_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "media": _build_variant_media_payload(
            media_path=media_path,
            srt_path=srt_path,
            media_meta=media_meta,
        ),
        "segments": [dict(segment) for segment in (segments or [])],
        "transitions": [
            {
                "boundary_time_sec": round(float(boundary_time), 3),
                "overlap_sec": round(float(overlap), 3),
            }
            for boundary_time, overlap in (transition_offsets or [])
        ],
        "subtitle_events": [_normalize_subtitle_event(item) for item in (subtitle_events or [])],
        "overlay_events": {
            "emphasis_overlays": [dict(item) for item in ((overlay_events or {}).get("emphasis_overlays") or [])],
            "sound_effects": [dict(item) for item in ((overlay_events or {}).get("sound_effects") or [])],
        },
        "quality_checks": dict(quality_check or {}),
    }


def _build_variant_media_payload(
    *,
    media_path: Path | None,
    srt_path: Path | None,
    media_meta: Any | None,
) -> dict[str, Any]:
    return {
        "path": str(media_path) if media_path else None,
        "srt_path": str(srt_path) if srt_path else None,
        "duration_sec": round(float(getattr(media_meta, "duration", 0.0) or 0.0), 3),
        "width": int(getattr(media_meta, "width", 0) or 0),
        "height": int(getattr(media_meta, "height", 0) or 0),
    }


def _normalize_subtitle_event(item: dict[str, Any]) -> dict[str, Any]:
    start_time = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
    end_time = float(item.get("end_time", item.get("end", start_time)) or start_time)
    return {
        "index": int(item.get("index", 0) or 0),
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "text": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or item.get("text") or "").strip(),
    }


def _clone_json_like(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clone_json_like(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json_like(item) for item in value]
    return value


def _validate_variant_timeline_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    variants = bundle.get("variants")
    if not isinstance(variants, dict):
        return {"status": "warning", "issues": ["variants payload missing"]}

    for variant_name, variant in variants.items():
        if not isinstance(variant, dict):
            issues.append(f"{variant_name}: variant payload is not a dict")
            continue
        media = variant.get("media")
        duration_sec = 0.0
        if isinstance(media, dict):
            duration_sec = float(media.get("duration_sec") or 0.0)

        previous_end: float | None = None
        for index, event in enumerate(variant.get("subtitle_events") or [], start=1):
            if not isinstance(event, dict):
                issues.append(f"{variant_name}: subtitle event {index} is not a dict")
                continue
            start_time = float(event.get("start_time", event.get("start", 0.0)) or 0.0)
            end_time = float(event.get("end_time", event.get("end", start_time)) or start_time)
            if end_time < start_time:
                issues.append(f"{variant_name}: subtitle event {index} has end before start")
            if previous_end is not None and start_time < previous_end - 1e-6:
                issues.append(f"{variant_name}: subtitle events are not monotonic at index {index}")
            if duration_sec > 0 and end_time > duration_sec + 0.05:
                issues.append(f"{variant_name}: subtitle event {index} extends beyond media duration")
            previous_end = max(previous_end or end_time, end_time)

    timeline_rules = bundle.get("timeline_rules")
    if isinstance(timeline_rules, dict):
        timeline_analysis = timeline_rules.get("timeline_analysis")
        if isinstance(timeline_analysis, dict):
            previous_section_end: float | None = None
            for section_index, section in enumerate(timeline_analysis.get("semantic_sections") or [], start=1):
                if not isinstance(section, dict):
                    issues.append(f"timeline_analysis: semantic section {section_index} is not a dict")
                    continue
                start_sec = float(section.get("start_sec") or 0.0)
                end_sec = float(section.get("end_sec") or 0.0)
                if end_sec < start_sec:
                    issues.append(f"timeline_analysis: semantic section {section_index} has end before start")
                if previous_section_end is not None and start_sec < previous_section_end - 1e-6:
                    issues.append(f"timeline_analysis: semantic sections are not monotonic at index {section_index}")
                previous_section_end = max(previous_section_end or end_sec, end_sec)
            previous_directive_end: float | None = None
            for directive_index, directive in enumerate(timeline_analysis.get("section_directives") or [], start=1):
                if not isinstance(directive, dict):
                    issues.append(f"timeline_analysis: section directive {directive_index} is not a dict")
                    continue
                start_sec = float(directive.get("start_sec") or 0.0)
                end_sec = float(directive.get("end_sec") or 0.0)
                if end_sec < start_sec:
                    issues.append(f"timeline_analysis: section directive {directive_index} has end before start")
                if previous_directive_end is not None and start_sec < previous_directive_end - 1e-6:
                    issues.append(f"timeline_analysis: section directives are not monotonic at index {directive_index}")
                previous_directive_end = max(previous_directive_end or end_sec, end_sec)
            previous_action_end: float | None = None
            for action_index, action in enumerate(timeline_analysis.get("section_actions") or [], start=1):
                if not isinstance(action, dict):
                    issues.append(f"timeline_analysis: section action {action_index} is not a dict")
                    continue
                start_sec = float(action.get("start_sec") or 0.0)
                end_sec = float(action.get("end_sec") or 0.0)
                anchor_sec = float(action.get("broll_anchor_sec", start_sec) or start_sec)
                transition_anchor_sec = float(action.get("transition_anchor_sec", start_sec) or start_sec)
                if end_sec < start_sec:
                    issues.append(f"timeline_analysis: section action {action_index} has end before start")
                if not (start_sec - 1e-6 <= anchor_sec <= end_sec + 1e-6):
                    issues.append(f"timeline_analysis: section action {action_index} has anchor outside section window")
                if not (start_sec - 1e-6 <= transition_anchor_sec <= end_sec + 1e-6):
                    issues.append(f"timeline_analysis: section action {action_index} has transition anchor outside section window")
                if previous_action_end is not None and start_sec < previous_action_end - 1e-6:
                    issues.append(f"timeline_analysis: section actions are not monotonic at index {action_index}")
                previous_action_end = max(previous_action_end or end_sec, end_sec)
        editing_skill = timeline_rules.get("editing_skill")
        if isinstance(editing_skill, dict):
            if not str(editing_skill.get("key") or "").strip():
                issues.append("editing_skill: key missing")
            section_policy = editing_skill.get("section_policy")
            if section_policy is not None and not isinstance(section_policy, dict):
                issues.append("editing_skill: section_policy is not a dict")
        section_choreography = timeline_rules.get("section_choreography")
        if isinstance(section_choreography, dict):
            previous_section_end: float | None = None
            for section_index, section in enumerate(section_choreography.get("sections") or [], start=1):
                if not isinstance(section, dict):
                    issues.append(f"section_choreography: section {section_index} is not a dict")
                    continue
                start_sec = float(section.get("start_sec") or 0.0)
                end_sec = float(section.get("end_sec") or 0.0)
                transition_anchor_sec = float(section.get("transition_anchor_sec", start_sec) or start_sec)
                if end_sec < start_sec:
                    issues.append(f"section_choreography: section {section_index} has end before start")
                if not (start_sec - 1e-6 <= transition_anchor_sec <= end_sec + 1e-6):
                    issues.append(f"section_choreography: section {section_index} has transition anchor outside section window")
                if previous_section_end is not None and start_sec < previous_section_end - 1e-6:
                    issues.append(f"section_choreography: sections are not monotonic at index {section_index}")
                previous_section_end = max(previous_section_end or end_sec, end_sec)
        diagnostics = timeline_rules.get("diagnostics")
        if isinstance(diagnostics, dict):
            keep_energy_summary = diagnostics.get("keep_energy_summary")
            if keep_energy_summary is not None and not isinstance(keep_energy_summary, dict):
                issues.append("diagnostics: keep_energy_summary is not a dict")
            for field_name in ("high_energy_keeps", "high_risk_cuts"):
                items = diagnostics.get(field_name)
                if items is not None and not isinstance(items, list):
                    issues.append(f"diagnostics: {field_name} is not a list")
            review_flags = diagnostics.get("review_flags")
            if review_flags is not None and not isinstance(review_flags, dict):
                issues.append("diagnostics: review_flags is not a dict")

    return {"status": "warning" if issues else "ok", "issues": issues}


def _resolve_transition_overlap_offsets(
    render_plan: dict[str, Any] | None,
    *,
    keep_segments: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    if len(keep_segments) < 2:
        return []

    transitions = ((render_plan or {}).get("editing_accents") or {}).get("transitions") or {}
    if not transitions.get("enabled"):
        return []

    raw_duration = float(transitions.get("duration_sec") or 0.12)
    requested_indexes: list[int] = []
    for raw_index in transitions.get("boundary_indexes") or []:
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(keep_segments) - 1:
            requested_indexes.append(index)
    if not requested_indexes:
        return []

    boundary_positions: list[float] = []
    elapsed = 0.0
    for segment in keep_segments:
        elapsed += max(0.0, float(segment.get("end", 0.0) or 0.0) - float(segment.get("start", 0.0) or 0.0))
        boundary_positions.append(elapsed)

    offsets: list[tuple[float, float]] = []
    for index in requested_indexes:
        current = keep_segments[index]
        following = keep_segments[index + 1]
        current_duration = max(0.0, float(current.get("end", 0.0) or 0.0) - float(current.get("start", 0.0) or 0.0))
        next_duration = max(0.0, float(following.get("end", 0.0) or 0.0) - float(following.get("start", 0.0) or 0.0))
        transition_duration = min(max(raw_duration, 0.08), current_duration / 4, next_duration / 4, 0.18)
        if transition_duration < 0.08:
            continue
        offsets.append((boundary_positions[index], round(transition_duration, 3)))

    offsets.sort(key=lambda item: item[0])
    return offsets


def _shift_timed_items_for_transition_overlaps(
    items: list[dict],
    *,
    transition_offsets: list[tuple[float, float]],
) -> list[dict]:
    shifted: list[dict] = []
    for item in items:
        shifted_item = dict(item)
        start_time = float(item.get("start_time", 0.0) or 0.0)
        end_time = float(item.get("end_time", start_time + float(item.get("duration_sec", 0.0) or 0.0)) or 0.0)
        shifted_item["start_time"] = _shift_time_for_transition_overlaps(
            start_time,
            transition_offsets=transition_offsets,
            inclusive=True,
        )
        if "end_time" in item:
            shifted_item["end_time"] = max(
                shifted_item["start_time"],
                _shift_time_for_transition_overlaps(
                    end_time,
                    transition_offsets=transition_offsets,
                    inclusive=False,
                ),
            )
        shifted.append(shifted_item)
    return shifted


def _shift_sound_effects_for_transition_overlaps(
    items: list[dict],
    *,
    transition_offsets: list[tuple[float, float]],
) -> list[dict]:
    shifted: list[dict] = []
    for item in items:
        shifted_item = dict(item)
        shifted_item["start_time"] = _shift_time_for_transition_overlaps(
            float(item.get("start_time", 0.0) or 0.0),
            transition_offsets=transition_offsets,
            inclusive=True,
        )
        shifted.append(shifted_item)
    return shifted


def _shift_time_for_transition_overlaps(
    value: float,
    *,
    transition_offsets: list[tuple[float, float]],
    inclusive: bool,
) -> float:
    shifted = float(value or 0.0)
    for boundary_time, overlap in transition_offsets:
        if shifted > boundary_time or (inclusive and shifted >= boundary_time):
            shifted -= overlap
    return max(0.0, shifted)


def _select_default_avatar_profile() -> dict[str, Any] | None:
    profiles = list_avatar_material_profiles()
    if not profiles:
        return None
    candidates = []
    for profile in profiles:
        files = list(profile.get("files") or [])
        has_speaking_video = any(str(item.get("role") or "") == "speaking_video" for item in files)
        if not has_speaking_video:
            continue
        capability = profile.get("capability_status") or {}
        score = 0
        if str(capability.get("preview") or "") == "ready":
            score += 2
        if str(capability.get("heygem_avatar") or "") == "ready":
            score += 1
        candidates.append((score, str(profile.get("created_at") or ""), profile))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _pick_avatar_profile_speaking_video_path(profile: dict[str, Any] | None) -> Path | None:
    if not profile:
        return None
    for file_record in profile.get("files") or []:
        if str(file_record.get("role") or "") != "speaking_video":
            continue
        path = Path(str(file_record.get("path") or ""))
        if path.exists():
            return path
    return None


def _hash_file(path: Path, chunk_size: int = 65536) -> str:
    sha256 = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            sha256.update(chunk)
    return sha256.hexdigest()


def _record_source_integrity(
    local_path: Path,
    *,
    source_ref: str,
    expected_hash: str | None,
    debug_dir: Path | None,
    downloaded: bool,
) -> str:
    actual_hash = _hash_file(local_path)
    payload = {
        "source_ref": source_ref,
        "local_path": str(local_path),
        "downloaded_from_storage": downloaded,
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
        "hash_match": expected_hash in (None, "", actual_hash),
        "size_bytes": local_path.stat().st_size,
    }
    if debug_dir is not None:
        (debug_dir / "source.integrity.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(
            f"Downloaded source hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    return actual_hash


def run_step_sync(step_name: str, job_id: str) -> dict:
    """Synchronous entry point for Celery tasks."""
    # Force-reset engine singleton so asyncpg doesn't reuse connections from a previous event loop
    import roughcut.db.session as _sess
    _sess._engine = None
    _sess._session_factory = None

    step_map = {
        "probe": run_probe,
        "extract_audio": run_extract_audio,
        "transcribe": run_transcribe,
        "subtitle_postprocess": run_subtitle_postprocess,
        "subtitle_translation": run_subtitle_translation,
        "content_profile": run_content_profile,
        "glossary_review": run_glossary_review,
        "ai_director": run_ai_director,
        "avatar_commentary": run_avatar_commentary,
        "edit_plan": run_edit_plan,
        "render": run_render,
        "platform_package": run_platform_package,
    }
    fn = step_map.get(step_name)
    if not fn:
        raise ValueError(f"Unknown step: {step_name}")
    return asyncio.run(fn(job_id))
