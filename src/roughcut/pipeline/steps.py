"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import copy
import asyncio
import hashlib
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import delete, select

from roughcut.avatar import list_avatar_material_profiles
from roughcut.config import get_settings, llm_task_route, normalize_transcription_settings, should_enable_task_search
from roughcut.creative import (
    ai_director_mode_enabled,
    avatar_mode_enabled,
    build_ai_director_plan,
    build_avatar_commentary_plan,
    build_job_creative_profile,
    multilingual_translation_mode_enabled,
)
from roughcut.creative.avatar import refine_avatar_commentary_segments_for_media_duration
from roughcut.docker_gpu_guard import _acquire_operation_lock, _release_operation_lock
from roughcut.db.models import Artifact, GlossaryTerm, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline, TranscriptSegment
from roughcut.db.session import get_session_factory
from roughcut.edit.decisions import (
    EditDecision,
    EditSegment,
    _build_keep_energy_segments_analysis,
    _summarize_keep_energy_segments,
    build_edit_decision,
    infer_timeline_analysis,
)
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.presets import normalize_workflow_template_name
from roughcut.edit.render_plan import (
    build_ai_effect_render_plan,
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
from roughcut.media.subtitle_text import clean_final_subtitle_text
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.media.probe import probe, validate_media
from roughcut.media.render import render_video
from roughcut.media.silence import detect_silence
from roughcut.llm_cache import build_cache_key, build_cache_metadata, digest_payload, load_cached_entry, save_cached_json
from roughcut.naming import AVATAR_CAPABILITY_GENERATION, normalize_avatar_capability_status
from roughcut.packaging.library import (
    list_packaging_assets,
    rank_insert_candidates_for_section,
    resolve_insert_added_duration,
    resolve_insert_effective_duration,
    resolve_insert_transition_overlap,
    resolve_packaging_plan_for_job,
)
from roughcut.prompts.edit_decision import build_high_risk_cut_review_prompt
from roughcut.providers.factory import get_avatar_provider, get_reasoning_provider, get_voice_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.providers.transcription.chunking import (
    build_audio_chunk_specs,
    probe_audio_duration,
    resolve_audio_chunk_config,
    should_chunk_audio,
)
from roughcut.pipeline.quality import _compute_subtitle_sync_check, evaluate_profile_identity_gate
from roughcut.review.content_profile import (
    _build_conservative_identity_summary,
    apply_source_identity_constraints,
    apply_content_profile_feedback,
    apply_identity_review_guard,
    assess_content_profile_automation,
    build_content_profile_cache_fingerprint,
    build_review_feedback_verification_bundle,
    build_reviewed_transcript_excerpt,
    build_transcript_excerpt,
    extract_source_identity_constraints,
    enrich_content_profile,
    infer_content_profile,
    polish_subtitle_items,
    resolve_content_profile_review_feedback,
)
from roughcut.review.content_profile_memory import (
    load_content_profile_user_memory,
    merge_content_profile_creative_preferences,
    record_content_profile_feedback_memory,
)
from roughcut.review.content_profile_artifacts import persist_content_profile_artifacts
from roughcut.review.downstream_context import (
    build_downstream_context,
    resolve_downstream_profile,
)
from roughcut.review.model_identity import filter_conflicting_model_wrong_forms as _shared_filter_conflicting_model_wrong_forms
from roughcut.review.domain_glossaries import (
    _CANONICAL_DOMAIN_SOURCES,
    _RELATED_DOMAINS,
    detect_glossary_domains,
    filter_scoped_glossary_terms,
    merge_glossary_terms,
    normalize_subject_domain,
    resolve_builtin_glossary_terms,
    select_primary_subject_domain,
)
from roughcut.review.intelligent_copy_topics import build_intelligent_copy_topic_hints
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
from roughcut.review.evidence_types import build_correction_framework_trace
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt, resolve_transcription_category_scope
from roughcut.review.subtitle_consistency import (
    ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
    build_subtitle_consistency_report,
)
from roughcut.review.subtitle_quality import (
    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
    build_subtitle_quality_report,
    build_subtitle_quality_report_from_items,
)
from roughcut.review.subtitle_term_resolution import (
    ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
    build_subtitle_term_resolution_patch,
)
from roughcut.review.subtitle_translation import (
    detect_subtitle_language,
    languages_equivalent,
    resolve_translation_target_language,
    translate_subtitle_items,
)
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.review.telegram_bot import get_telegram_review_bot_service
from roughcut.speech.postprocess import (
    SubtitleEntry,
    _reindex_subtitle_entries,
    analyze_subtitle_segmentation,
    generate_subtitle_window_candidates,
    normalize_display_text,
    resegment_subtitle_window_from_cuts,
    save_subtitle_items,
    score_subtitle_entries,
    segment_subtitles,
)
from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    build_canonical_transcript_layer,
    build_subtitle_architecture_artifacts,
    build_subtitle_projection_layer,
    build_transcript_fact_layer,
)
from roughcut.speech.transcribe import _normalize_semantic_contamination_text, persist_empty_transcript_result, transcribe_audio
from roughcut.storage.s3 import get_storage, job_key
from roughcut.telegram.review_notification_service import enqueue_review_notification
from roughcut.usage import track_step_usage, track_usage_operation

_AVATAR_SEGMENT_READY_RETRIES = 60
_AVATAR_SEGMENT_READY_RETRY_SECONDS = 1.0


STEP_LABELS = {
    "probe": "探测媒体信息",
    "extract_audio": "提取音频",
    "transcribe": "语音转写",
    "subtitle_postprocess": "字幕后处理",
    "subtitle_term_resolution": "术语解析",
    "subtitle_consistency_review": "一致性审校",
    "transcript_review": "转写审校",
    "subtitle_translation": "字幕翻译",
    "content_profile": "内容摘要",
    "summary_review": "内容异常门",
    "glossary_review": "术语纠错",
    "ai_director": "AI导演",
    "avatar_commentary": "数字人解说",
    "edit_plan": "剪辑决策",
    "render": "渲染输出",
    "final_review": "成片异常门",
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


def _resolve_subtitle_semantic_cleanup_scope(
    *,
    job: Any,
    content_profile: dict[str, Any] | None,
    review_memory: dict[str, Any] | None,
) -> str:
    scope_hint = " ".join(
        str(value or "")
        for value in (
            getattr(job, "source_name", ""),
            (content_profile or {}).get("subject_domain"),
            (content_profile or {}).get("subject_type"),
            (content_profile or {}).get("video_theme"),
            (content_profile or {}).get("summary"),
        )
    ).lower()
    if "折刀" in scope_hint or "knife" in scope_hint:
        return "knife"
    if any(token in scope_hint for token in ("手电", "电筒", "flashlight", "edc17", "edc23", "edc37")):
        return "flashlight"
    if any(token in scope_hint for token in ("双肩包", "机能包", "背包", "bag")):
        return "bag"
    category_scope = resolve_transcription_category_scope(review_memory)
    if category_scope in {"knife", "flashlight", "bag"}:
        return category_scope
    return category_scope


def _apply_subtitle_semantic_cleanup(
    subtitle_items: list[Any],
    *,
    job: Any,
    content_profile: dict[str, Any] | None,
    review_memory: dict[str, Any] | None,
) -> int:
    category_scope = _resolve_subtitle_semantic_cleanup_scope(
        job=job,
        content_profile=content_profile,
        review_memory=review_memory,
    )
    cleaned_count = 0
    for item in subtitle_items:
        original_text = str(getattr(item, "text_final", None) or getattr(item, "text_norm", None) or getattr(item, "text_raw", None) or "").strip()
        cleaned_text = _normalize_semantic_contamination_text(original_text, category_scope=category_scope)
        if cleaned_text != original_text:
            item.text_final = cleaned_text
            cleaned_count += 1
    return cleaned_count


_TRANSCRIPTION_PROVIDER_LABELS: dict[str, str] = {
    "openai": "OpenAI",
    "local_http_asr": "Local HTTP ASR",
    "funasr": "FunASR",
    "faster_whisper": "faster-whisper",
}


def _describe_transcription_route(*, provider: object, model: object, language: object | None = None) -> str:
    provider_value, model_value = normalize_transcription_settings(provider, model)
    provider_label = _TRANSCRIPTION_PROVIDER_LABELS.get(provider_value, provider_value)
    label = f"{provider_label} / {model_value}"
    language_value = str(language or "").strip()
    if language_value:
        return f"{label} · {language_value}"
    return label

_CONTENT_PROFILE_ARTIFACT_TYPES = ("content_profile_final", "content_profile", "content_profile_draft")
_DOWNSTREAM_PROFILE_ARTIFACT_TYPES = ("downstream_context",) + _CONTENT_PROFILE_ARTIFACT_TYPES
_EDIT_PLAN_INSERT_SLOT_TIMEOUT_SEC = 20.0
_EDIT_PLAN_CUT_REVIEW_TIMEOUT_SEC = 30.0
_SUBTITLE_POSTPROCESS_BOUNDARY_REFINE_TIMEOUT_SEC = 20.0
_SUBTITLE_BOUNDARY_REFINE_MIN_SCORE_GAIN = 2.0
_SUBTITLE_BOUNDARY_LOCAL_FALLBACK_MIN_SCORE_GAIN = 8.0
_SUBTITLE_BOUNDARY_LOCAL_EARLY_ACCEPT_SCORE_GAIN = 12.0
_SUBTITLE_BOUNDARY_REFINE_MAX_WINDOWS = 8
_SOURCE_NAME_TIMESTAMP_RE = re.compile(r"(?<!\d)(?P<date>\d{8})[-_ ]?(?P<time>\d{6})(?!\d)")
_SOURCE_NAME_SEQUENCE_RE = re.compile(r"(?P<prefix>[A-Za-z]+)[-_ ]?(?P<number>\d{3,6})(?!.*\d)")
_EDIT_DECISION_REVIEW_CONTEXT_WINDOW_SEC = 1.2
_EDIT_DECISION_REVIEW_MAX_CONTEXT_ITEMS = 2
_EDIT_DECISION_REVIEW_REASON_PRIORITY = {
    "restart_retake": 0,
    "low_signal_subtitle": 1,
    "long_non_dialogue": 2,
    "silence": 3,
}


def _workflow_template_subject_domain(workflow_template: str | None) -> str | None:
    # Workflow presets are too broad to scope memory by themselves.
    normalize_workflow_template_name(workflow_template)
    return None


def _supported_memory_subject_domain(value: str | None) -> str | None:
    normalized = normalize_subject_domain(value)
    if not normalized:
        return None
    known_domains = {
        "edc",
        "outdoor",
        "tech",
        "ai",
        "functional",
        "tools",
        "travel",
        "food",
        "finance",
        "news",
        "sports",
        "gear",
        "knife",
        "flashlight",
        "bag",
        "lighter",
        "tactical",
        "functional_wear",
        "toy",
        "coding",
    }
    return normalized if normalized in known_domains else None


def _infer_subject_domain_from_profile_subject_type(content_profile: dict[str, Any] | None) -> str | None:
    profile = content_profile or {}
    subject_type = str(profile.get("subject_type") or "").strip()
    if not subject_type:
        return None
    detected_domains = detect_glossary_domains(
        workflow_template=None,
        content_profile={"subject_type": subject_type},
        subtitle_items=None,
    )
    detected = select_primary_subject_domain(detected_domains)
    return _supported_memory_subject_domain(detected)


def _infer_subject_domain_for_memory(
    *,
    workflow_template: str | None,
    subtitle_items: list[dict[str, Any]] | None = None,
    content_profile: dict[str, Any] | None = None,
    source_name: str | None = None,
    subject_domain: str | None = None,
) -> str | None:
    explicit_subject_domain = _supported_memory_subject_domain(subject_domain or (content_profile or {}).get("subject_domain"))
    if explicit_subject_domain:
        return explicit_subject_domain
    subject_type_domain = _infer_subject_domain_from_profile_subject_type(content_profile)
    if subject_type_domain:
        return subject_type_domain
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


def _cut_review_candidate_id(item: dict[str, Any]) -> str:
    return (
        f"{str(item.get('reason') or '').strip()}:"
        f"{float(item.get('start', 0.0) or 0.0):.3f}:"
        f"{float(item.get('end', 0.0) or 0.0):.3f}"
    )


def _segment_cut_key(segment: EditSegment) -> str:
    return f"{segment.reason}:{float(segment.start):.3f}:{float(segment.end):.3f}"


def _review_candidate_priority(item: dict[str, Any]) -> tuple[int, float, float]:
    return (
        _EDIT_DECISION_REVIEW_REASON_PRIORITY.get(str(item.get("reason") or "").strip(), 99),
        -float(item.get("boundary_keep_energy", 0.0) or 0.0),
        -(float(item.get("end", 0.0) or 0.0) - float(item.get("start", 0.0) or 0.0)),
    )


def _find_section_action_for_cut(
    start_sec: float,
    end_sec: float,
    *,
    timeline_analysis: dict[str, Any] | None,
) -> dict[str, Any] | None:
    midpoint = start_sec + max(0.0, end_sec - start_sec) * 0.5
    for action in list((timeline_analysis or {}).get("section_actions") or []):
        if not isinstance(action, dict):
            continue
        action_start = float(action.get("start_sec", 0.0) or 0.0)
        action_end = float(action.get("end_sec", action_start) or action_start)
        if action_start - 1e-6 <= midpoint <= action_end + 1e-6:
            return action
    return None


def _context_items_around_cut(
    *,
    start_sec: float,
    end_sec: float,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    previous_subtitles = [
        dict(item)
        for item in subtitle_items
        if float(item.get("end_time", 0.0) or 0.0) <= start_sec + 1e-6
        and start_sec - float(item.get("end_time", 0.0) or 0.0) <= _EDIT_DECISION_REVIEW_CONTEXT_WINDOW_SEC
    ][-_EDIT_DECISION_REVIEW_MAX_CONTEXT_ITEMS:]
    next_subtitles = [
        dict(item)
        for item in subtitle_items
        if float(item.get("start_time", 0.0) or 0.0) >= end_sec - 1e-6
        and float(item.get("start_time", 0.0) or 0.0) - end_sec <= _EDIT_DECISION_REVIEW_CONTEXT_WINDOW_SEC
    ][:_EDIT_DECISION_REVIEW_MAX_CONTEXT_ITEMS]
    transcript_context = [
        dict(item)
        for item in transcript_segments
        if float(item.get("end", 0.0) or 0.0) >= start_sec - _EDIT_DECISION_REVIEW_CONTEXT_WINDOW_SEC
        and float(item.get("start", 0.0) or 0.0) <= end_sec + _EDIT_DECISION_REVIEW_CONTEXT_WINDOW_SEC
    ][: 2 * _EDIT_DECISION_REVIEW_MAX_CONTEXT_ITEMS + 1]
    return previous_subtitles, next_subtitles, transcript_context


def _should_review_cut_with_llm(item: dict[str, Any]) -> bool:
    reason = str(item.get("reason") or "").strip()
    if reason in {"restart_retake", "low_signal_subtitle", "long_non_dialogue"}:
        return True
    if reason != "silence":
        return False
    if float(item.get("boundary_keep_energy", 0.0) or 0.0) >= 1.0:
        return True
    return any(
        token in str(signal or "")
        for signal in (item.get("signals") or [])
        for token in ("semantic_bridge", "visual_showcase_gap", "continuation_guard")
    )


def _build_edit_decision_llm_review_candidates(
    *,
    decision: EditDecision,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    settings,
) -> list[dict[str, Any]]:
    analysis = dict(getattr(decision, "analysis", {}) or {})
    accepted_cuts = [
        dict(item)
        for item in list(analysis.get("accepted_cuts") or [])
        if isinstance(item, dict) and _should_review_cut_with_llm(item)
    ]
    accepted_cuts.sort(key=_review_candidate_priority)
    max_candidates = max(0, int(getattr(settings, "edit_decision_llm_review_max_candidates", 6) or 6))
    candidates: list[dict[str, Any]] = []
    for item in accepted_cuts[:max_candidates]:
        start_sec = float(item.get("start", 0.0) or 0.0)
        end_sec = float(item.get("end", 0.0) or 0.0)
        previous_subtitles, next_subtitles, transcript_context = _context_items_around_cut(
            start_sec=start_sec,
            end_sec=end_sec,
            subtitle_items=subtitle_items,
            transcript_segments=transcript_segments,
        )
        action = _find_section_action_for_cut(start_sec, end_sec, timeline_analysis=analysis)
        candidates.append(
            {
                "candidate_id": _cut_review_candidate_id(item),
                "start": round(start_sec, 3),
                "end": round(end_sec, 3),
                "duration_sec": round(max(0.0, end_sec - start_sec), 3),
                "reason": str(item.get("reason") or ""),
                "boundary_keep_energy": round(float(item.get("boundary_keep_energy", 0.0) or 0.0), 3),
                "signals": [str(signal) for signal in (item.get("signals") or []) if str(signal)],
                "evidence": dict(item.get("evidence") or {}) if isinstance(item.get("evidence"), dict) else {},
                "left_keep_role": str(item.get("left_keep_role") or ""),
                "right_keep_role": str(item.get("right_keep_role") or ""),
                "section_role": str((action or {}).get("role") or ""),
                "broll_allowed": bool((action or {}).get("broll_allowed")),
                "packaging_intent": str((action or {}).get("packaging_intent") or ""),
                "previous_subtitles": [
                    {
                        "start_time": round(float(entry.get("start_time", 0.0) or 0.0), 3),
                        "end_time": round(float(entry.get("end_time", 0.0) or 0.0), 3),
                        "text": str(entry.get("text_final") or entry.get("text_norm") or entry.get("text_raw") or ""),
                    }
                    for entry in previous_subtitles
                ],
                "next_subtitles": [
                    {
                        "start_time": round(float(entry.get("start_time", 0.0) or 0.0), 3),
                        "end_time": round(float(entry.get("end_time", 0.0) or 0.0), 3),
                        "text": str(entry.get("text_final") or entry.get("text_norm") or entry.get("text_raw") or ""),
                    }
                    for entry in next_subtitles
                ],
                "transcript_context": [
                    {
                        "start": round(float(entry.get("start", 0.0) or 0.0), 3),
                        "end": round(float(entry.get("end", 0.0) or 0.0), 3),
                        "text": str(entry.get("text") or ""),
                        "speaker": str(entry.get("speaker") or ""),
                        "confidence": round(float(entry.get("confidence", 0.0) or 0.0), 3)
                        if entry.get("confidence") is not None
                        else None,
                    }
                    for entry in transcript_context
                ],
            }
        )
    return candidates


def _resolve_edit_decision_llm_review_timeout_seconds(settings: object, *, candidate_count: int) -> float:
    try:
        configured_timeout = float(getattr(settings, "edit_decision_llm_review_timeout_sec", _EDIT_PLAN_CUT_REVIEW_TIMEOUT_SEC) or _EDIT_PLAN_CUT_REVIEW_TIMEOUT_SEC)
    except (TypeError, ValueError):
        configured_timeout = _EDIT_PLAN_CUT_REVIEW_TIMEOUT_SEC
    configured_timeout = max(10.0, configured_timeout)
    scaled_timeout = 8.0 + max(1, int(candidate_count)) * 6.0
    return max(configured_timeout, scaled_timeout)


def _merge_edit_segments(segments: list[EditSegment]) -> list[EditSegment]:
    ordered = sorted(
        (segment for segment in segments if segment.end > segment.start),
        key=lambda segment: (segment.start, segment.end),
    )
    merged: list[EditSegment] = []
    for segment in ordered:
        if (
            merged
            and merged[-1].type == segment.type
            and abs(merged[-1].end - segment.start) <= 1e-6
            and (merged[-1].type != "remove" or merged[-1].reason == segment.reason)
        ):
            merged[-1].end = segment.end
            continue
        merged.append(EditSegment(start=segment.start, end=segment.end, type=segment.type, reason=segment.reason))
    return merged


def _normalize_cut_review_decisions(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for item in list((payload or {}).get("decisions") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = str(item.get("candidate_id") or "").strip()
        verdict = str(item.get("verdict") or "").strip().lower()
        if not candidate_id or verdict not in {"cut", "keep", "unsure"}:
            continue
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        evidence = [str(entry).strip() for entry in (item.get("evidence") or []) if str(entry).strip()]
        decisions.append(
            {
                "candidate_id": candidate_id,
                "verdict": verdict,
                "confidence": round(confidence, 3),
                "reason": str(item.get("reason") or "").strip(),
                "evidence": evidence[:4],
            }
        )
    return decisions


def _apply_llm_cut_review_to_decision(
    *,
    decision: EditDecision,
    review_result: dict[str, Any],
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
) -> EditDecision:
    if not hasattr(decision, "analysis") or not isinstance(getattr(decision, "analysis", None), dict):
        setattr(decision, "analysis", {})
    normalized_reviews = _normalize_cut_review_decisions(review_result)
    review_by_id = {item["candidate_id"]: item for item in normalized_reviews}
    min_confidence = float(review_result.get("min_confidence", 0.72) or 0.72)
    restore_ids = {
        candidate_id
        for candidate_id, item in review_by_id.items()
        if str(item.get("verdict") or "") == "keep" and float(item.get("confidence", 0.0) or 0.0) >= min_confidence
    }

    if restore_ids:
        updated_segments: list[EditSegment] = []
        for segment in decision.segments:
            if segment.type == "remove" and _segment_cut_key(segment) in restore_ids:
                updated_segments.append(EditSegment(start=segment.start, end=segment.end, type="keep"))
            else:
                updated_segments.append(EditSegment(start=segment.start, end=segment.end, type=segment.type, reason=segment.reason))
        decision.segments = _merge_edit_segments(updated_segments)

    accepted_cuts: list[dict[str, Any]] = []
    for item in list((decision.analysis or {}).get("accepted_cuts") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = _cut_review_candidate_id(item)
        if candidate_id in restore_ids:
            continue
        payload = dict(item)
        if candidate_id in review_by_id:
            payload["llm_review"] = dict(review_by_id[candidate_id])
        accepted_cuts.append(payload)
    decision.analysis["accepted_cuts"] = accepted_cuts

    keep_energy_segments = _build_keep_energy_segments_analysis(
        decision.segments,
        subtitle_items=subtitle_items,
        timeline_analysis=decision.analysis,
        content_profile=content_profile,
    )
    decision.analysis["keep_energy_segments"] = keep_energy_segments
    decision.analysis["keep_energy_summary"] = _summarize_keep_energy_segments(keep_energy_segments)
    decision.analysis["llm_cut_review"] = {
        "reviewed": bool(normalized_reviews),
        "candidate_count": len(list(review_result.get("candidates") or [])),
        "decision_count": len(normalized_reviews),
        "restored_cut_count": len(restore_ids),
        "cached": bool(review_result.get("cached")),
        "provider": str(review_result.get("provider") or ""),
        "model": str(review_result.get("model") or ""),
        "summary": str(review_result.get("summary") or ""),
        "decisions": normalized_reviews,
    }
    return decision


async def _maybe_review_edit_decision_cuts_with_llm(
    *,
    job_id: uuid.UUID,
    source_name: str,
    decision: EditDecision,
    subtitle_items: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
) -> EditDecision:
    if not hasattr(decision, "analysis") or not isinstance(getattr(decision, "analysis", None), dict):
        setattr(decision, "analysis", {})
    settings = get_settings()
    if not bool(getattr(settings, "edit_decision_llm_review_enabled", True)):
        decision.analysis["llm_cut_review"] = {"reviewed": False, "disabled": True}
        return decision

    candidates = _build_edit_decision_llm_review_candidates(
        decision=decision,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
        settings=settings,
    )
    if not candidates:
        decision.analysis["llm_cut_review"] = {"reviewed": False, "candidate_count": 0}
        return decision

    source_meta = {
        "job_id": str(job_id),
        "source_name": str(source_name or "").strip(),
        "subject_brand": str((content_profile or {}).get("subject_brand") or "").strip(),
        "subject_model": str((content_profile or {}).get("subject_model") or "").strip(),
        "subject_type": str((content_profile or {}).get("subject_type") or "").strip(),
    }
    cache_namespace = "edit_plan.cut_review"
    with llm_task_route("edit_plan", search_enabled=False, settings=settings):
        active_provider = get_settings().active_reasoning_provider
        active_model = get_settings().active_reasoning_model
    fingerprint = {
        "source_meta": source_meta,
        "provider": active_provider,
        "model": active_model,
        "candidates_sha256": digest_payload(candidates),
        "min_confidence": float(getattr(settings, "edit_decision_llm_review_min_confidence", 0.72) or 0.72),
    }
    cache_key = build_cache_key(cache_namespace, fingerprint)
    cached_entry = load_cached_entry(cache_namespace, cache_key)
    if cached_entry is not None:
        cached_result = dict(cached_entry.get("result") or {})
        cached_result["cached"] = True
        cached_result["candidates"] = candidates
        cached_result["min_confidence"] = float(getattr(settings, "edit_decision_llm_review_min_confidence", 0.72) or 0.72)
        return _apply_llm_cut_review_to_decision(
            decision=decision,
            review_result=cached_result,
            subtitle_items=subtitle_items,
            content_profile=content_profile,
        )

    prompt_messages = build_high_risk_cut_review_prompt(source_meta=source_meta, candidates=candidates)
    review_timeout_sec = _resolve_edit_decision_llm_review_timeout_seconds(
        settings,
        candidate_count=len(candidates),
    )
    try:
        with llm_task_route("edit_plan", search_enabled=False, settings=settings):
            provider = get_reasoning_provider()
            prompt_message_objects = [Message(role=str(item["role"]), content=str(item["content"])) for item in prompt_messages]
            with track_usage_operation("edit_plan.cut_review"):
                response = await asyncio.wait_for(
                    provider.complete(
                        prompt_message_objects,
                        temperature=0.1,
                        max_tokens=1200,
                        json_mode=True,
                    ),
                    timeout=review_timeout_sec,
                )
            review_payload = await _load_edit_decision_cut_review_json_payload(
                provider=provider,
                response=response,
                prompt_messages=prompt_message_objects,
                timeout_sec=review_timeout_sec,
                expected_decision_count=len(candidates),
            )
            if not isinstance(review_payload, dict):
                raise ValueError("edit decision cut review payload was not a JSON object")
            result = {
                "provider": str(get_settings().active_reasoning_provider or ""),
                "model": str(get_settings().active_reasoning_model or ""),
                "summary": str(review_payload.get("summary") or "").strip(),
                "decisions": _normalize_cut_review_decisions(review_payload),
                "cached": False,
                "candidates": candidates,
                "min_confidence": float(getattr(settings, "edit_decision_llm_review_min_confidence", 0.72) or 0.72),
            }
            save_cached_json(
                cache_namespace,
                cache_key,
                fingerprint=fingerprint,
                result={
                    "provider": result["provider"],
                    "model": result["model"],
                    "summary": result["summary"],
                    "decisions": list(result["decisions"]),
                },
                usage_baseline=response.usage,
            )
            return _apply_llm_cut_review_to_decision(
                decision=decision,
                review_result=result,
                subtitle_items=subtitle_items,
                content_profile=content_profile,
            )
    except asyncio.TimeoutError:
        logger.warning("LLM cut review timed out during edit_plan for job %s", job_id)
        decision.analysis["llm_cut_review"] = {
            "reviewed": False,
            "candidate_count": len(candidates),
            "error": "llm_cut_review_timeout",
            "timeout": True,
            "fallback": "deterministic_evidence",
        }
        return decision
    except ValueError as exc:
        message = str(exc).strip()
        if "credential is not configured" not in message and "no helper command or token is configured" not in message:
            raise
        logger.warning(
            "LLM cut review skipped during edit_plan for job %s because provider credentials are not configured: %s",
            job_id,
            message,
        )
        decision.analysis["llm_cut_review"] = {
            "reviewed": False,
            "candidate_count": len(candidates),
            "error": "llm_cut_review_unconfigured",
            "fallback": "deterministic_evidence",
        }
        return decision
    except Exception:
        logger.exception("LLM cut review failed during edit_plan for job %s", job_id)
        decision.analysis["llm_cut_review"] = {
            "reviewed": False,
            "candidate_count": len(candidates),
            "error": "llm_cut_review_failed",
            "fallback": "deterministic_evidence",
        }
        return decision


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
    if not candidates:
        return {}

    candidate_ids = [candidate.id for candidate in candidates]
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

    profiles_by_source_name: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_source_name = str(candidate.source_name or "").strip()
        if not candidate_source_name:
            continue
        artifact = _select_preferred_content_profile_artifact(artifacts_by_job_id.get(candidate.id, []))
        profile = dict((artifact.data_json if artifact else None) or {})
        if not profile:
            continue
        review_mode = str(profile.get("review_mode") or "").strip().lower()
        artifact_type = str(artifact.artifact_type or "").strip().lower() if artifact is not None else ""
        rank = (
            2 if review_mode == "manual_confirmed" else 1 if review_mode == "auto_confirmed" else 0,
            2 if artifact_type == "content_profile_final" else 1 if artifact_type == "content_profile" else 0,
            candidate.created_at or datetime.min.replace(tzinfo=timezone.utc),
            candidate.id,
        )
        existing = profiles_by_source_name.get(candidate_source_name)
        if existing is not None and tuple(existing.get("_rank") or ()) >= rank:
            continue
        profiles_by_source_name[candidate_source_name] = {
            "_rank": rank,
            "job": candidate,
            "artifact": artifact,
            "profile": profile,
        }

    scored_jobs: list[tuple[Job, float, Artifact | None, dict[str, Any]]] = []
    for source_name in preferred_source_names:
        selected = profiles_by_source_name.get(source_name)
        if selected is not None:
            scored_jobs.append((selected["job"], 1.0, selected["artifact"], selected["profile"]))
    if not scored_jobs:
        return {}

    related_profiles: list[dict[str, Any]] = []
    for candidate, score, artifact, profile in sorted(scored_jobs, key=lambda item: item[1], reverse=True):
        review_mode = str(profile.get("review_mode") or "").strip().lower()
        related_profile = {
            "source_name": str(candidate.source_name or "").strip(),
            "subject_brand": str(profile.get("subject_brand") or "").strip(),
            "subject_model": str(profile.get("subject_model") or "").strip(),
            "subject_type": str(profile.get("subject_type") or "").strip(),
            "video_theme": str(profile.get("video_theme") or "").strip(),
            "summary": str(profile.get("summary") or "").strip(),
            "search_queries": [str(item).strip() for item in (profile.get("search_queries") or []) if str(item).strip()][:6],
            "score": score,
            "review_mode": review_mode,
            "manual_confirmed": review_mode == "manual_confirmed",
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
        for related in _RELATED_DOMAINS.get(domain, ()):
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


def _subtitle_window_text_excerpt(window: dict[str, Any]) -> str:
    texts = [str(item).strip() for item in (window.get("texts") or []) if str(item).strip()]
    return " / ".join(texts)


def _tokenize_subtitle_text_for_boundary_refine(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return []
    return [token for token in re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]|.", compact) if token.strip()]


def _flatten_subtitle_window_words(entries: list[Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    word_index = 0
    for entry_index, entry in enumerate(entries):
        entry_words = tuple(getattr(entry, "words", ()) or ())
        if entry_words:
            for word in entry_words:
                text = str(word.get("word") or "").strip()
                if not text:
                    continue
                flattened.append(
                    {
                        "word_index": word_index,
                        "entry_index": entry_index,
                        "text": text,
                        "start": float(word.get("start") or 0.0),
                        "end": float(word.get("end") or 0.0),
                    }
                )
                word_index += 1
            continue

        fallback_tokens = _tokenize_subtitle_text_for_boundary_refine(getattr(entry, "text_raw", ""))
        if not fallback_tokens:
            continue
        entry_start = float(getattr(entry, "start", 0.0) or 0.0)
        entry_end = float(getattr(entry, "end", entry_start) or entry_start)
        duration = max(entry_end - entry_start, 0.001)
        token_span = duration / max(len(fallback_tokens), 1)
        for token_position, token in enumerate(fallback_tokens):
            token_start = entry_start + token_position * token_span
            token_end = min(entry_end, token_start + token_span)
            flattened.append(
                {
                    "word_index": word_index,
                    "entry_index": entry_index,
                    "text": token,
                    "start": token_start,
                    "end": token_end,
                }
            )
            word_index += 1
    return flattened


def _subtitle_boundary_refine_llm_supported() -> bool:
    return True


def _subtitle_window_current_cut_indices(flattened_words: list[dict[str, Any]], entry_count: int) -> list[int]:
    if entry_count <= 1 or len(flattened_words) < 2:
        return []
    entry_last_word_index: dict[int, int] = {}
    for item in flattened_words:
        entry_last_word_index[int(item["entry_index"])] = int(item["word_index"])
    cuts: list[int] = []
    last_allowed = len(flattened_words) - 2
    for entry_index in range(max(0, entry_count - 1)):
        cut = entry_last_word_index.get(entry_index)
        if cut is None or cut > last_allowed:
            continue
        if cuts and cut <= cuts[-1]:
            continue
        cuts.append(cut)
    return cuts


def _subtitle_boundary_token_line(flattened_words: list[dict[str, Any]]) -> str:
    return " ".join(f"{int(item['word_index'])}:{str(item['text'])}" for item in flattened_words)


def _normalize_subtitle_cut_indices(raw_value: Any) -> list[int] | None:
    if raw_value is None:
        return None
    if not isinstance(raw_value, (list, tuple)):
        return None
    normalized: list[int] = []
    for raw_item in raw_value:
        try:
            cut = int(raw_item)
        except (TypeError, ValueError):
            return None
        if normalized and cut <= normalized[-1]:
            return None
        normalized.append(cut)
    return normalized


def _iter_subtitle_boundary_cut_candidates(data: dict[str, Any], *, current_cuts: list[int]) -> list[list[int]]:
    raw_candidates = [
        data.get("best_cut_after_word_indices"),
        data.get("cut_after_word_indices"),
        data.get("alternate_cut_after_word_indices"),
    ]
    alternates = data.get("alternate_candidates")
    if isinstance(alternates, (list, tuple)):
        raw_candidates.extend(alternates)
    raw_candidates.append(current_cuts)

    normalized_candidates: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    for raw_candidate in raw_candidates:
        normalized = _normalize_subtitle_cut_indices(raw_candidate)
        if normalized is None:
            continue
        key = tuple(normalized)
        if key in seen:
            continue
        seen.add(key)
        normalized_candidates.append(normalized)
    return normalized_candidates


def _normalize_subtitle_candidate_index(raw_value: Any, *, limit: int) -> int | None:
    try:
        candidate_index = int(raw_value)
    except (TypeError, ValueError):
        return None
    if candidate_index < 0 or candidate_index >= limit:
        return None
    return candidate_index


def _iter_subtitle_candidate_selection_indices(
    data: dict[str, Any],
    *,
    current_index: int,
    limit: int,
) -> list[int]:
    raw_candidates = [
        data.get("best_candidate_index"),
        data.get("selected_candidate_index"),
        data.get("alternate_candidate_index"),
    ]
    normalized: list[int] = []
    seen: set[int] = set()
    for raw_candidate in raw_candidates:
        candidate_index = _normalize_subtitle_candidate_index(raw_candidate, limit=limit)
        if candidate_index is None or candidate_index in seen:
            continue
        seen.add(candidate_index)
        normalized.append(candidate_index)
    if current_index not in seen and 0 <= current_index < limit:
        normalized.append(current_index)
    return normalized


def _should_accept_strong_local_boundary_candidate(
    *,
    current_score: float,
    current_entry_count: int,
    best_local_candidate: list[Any] | None,
    best_local_score: float,
    min_score_gain: float,
    current_analysis: dict[str, Any] | None = None,
    best_local_analysis: dict[str, Any] | None = None,
) -> bool:
    base_accept = (
        best_local_candidate is not None
        and current_score < 0.0
        and len(best_local_candidate) <= current_entry_count
        and best_local_score >= current_score + min_score_gain
    )
    if base_accept:
        return True
    if (
        best_local_candidate is None
        or current_score >= 0.0
        or len(best_local_candidate) > current_entry_count
        or best_local_score < current_score + _SUBTITLE_BOUNDARY_REFINE_MIN_SCORE_GAIN
        or not isinstance(current_analysis, dict)
        or not isinstance(best_local_analysis, dict)
    ):
        return False

    current_metrics = (
        int(current_analysis.get("fragment_start_count") or 0),
        int(current_analysis.get("fragment_end_count") or 0),
        int(current_analysis.get("suspicious_boundary_count") or 0),
        int(current_analysis.get("low_confidence_window_count") or 0),
    )
    candidate_metrics = (
        int(best_local_analysis.get("fragment_start_count") or 0),
        int(best_local_analysis.get("fragment_end_count") or 0),
        int(best_local_analysis.get("suspicious_boundary_count") or 0),
        int(best_local_analysis.get("low_confidence_window_count") or 0),
    )
    if candidate_metrics < current_metrics and len(best_local_candidate) <= current_entry_count:
        return True
    return (
        candidate_metrics < current_metrics
        and len(best_local_candidate) == current_entry_count + 1
        and current_score <= -120.0
        and best_local_score >= current_score + max(min_score_gain, 24.0)
    )


def _subtitle_boundary_candidate_rank(
    *,
    candidate: list[Any],
    candidate_score: float,
    candidate_analysis: dict[str, Any],
    current_score: float,
    current_entry_count: int,
    current_analysis: dict[str, Any],
) -> tuple[float, ...]:
    current_fragment_total = int(current_analysis.get("fragment_start_count") or 0) + int(current_analysis.get("fragment_end_count") or 0)
    candidate_fragment_total = int(candidate_analysis.get("fragment_start_count") or 0) + int(candidate_analysis.get("fragment_end_count") or 0)
    current_suspicious = int(current_analysis.get("suspicious_boundary_count") or 0)
    candidate_suspicious = int(candidate_analysis.get("suspicious_boundary_count") or 0)
    current_low_conf = int(current_analysis.get("low_confidence_window_count") or 0)
    candidate_low_conf = int(candidate_analysis.get("low_confidence_window_count") or 0)
    entry_delta = len(candidate) - current_entry_count
    return (
        float(current_low_conf - candidate_low_conf),
        float(current_suspicious - candidate_suspicious),
        float(current_fragment_total - candidate_fragment_total),
        float(1 if entry_delta <= 0 else 0),
        float(-abs(entry_delta)),
        float(candidate_score - current_score),
    )


async def _complete_subtitle_boundary_json(
    *,
    provider: object,
    messages: list[Message],
    followup_retry_message: str | None = None,
    final_retry_message: str | None = None,
) -> dict[str, Any] | None:
    response = await provider.complete(
        messages,
        temperature=0.1,
        max_tokens=600,
        json_mode=True,
    )
    try:
        data = response.as_json()
        return data if isinstance(data, dict) else None
    except Exception:
        raw_content = str(getattr(response, "raw_content", "") or "").strip()
        if not raw_content:
            return None

    followup_messages = list(messages)
    followup_messages.append(Message(role="assistant", content=raw_content))
    followup_messages.append(
        Message(
            role="user",
            content=followup_retry_message
            or (
                "停止继续分析。现在只输出最终 JSON 对象 "
                "{\"best_cut_after_word_indices\":[...],"
                "\"alternate_cut_after_word_indices\":[...]}。"
                "不要解释，不要 markdown，不要代码块。"
            ),
        )
    )
    followup = await provider.complete(
        followup_messages,
        temperature=0.0,
        max_tokens=180,
        json_mode=False,
    )
    try:
        data = followup.as_json()
    except Exception:
        data = None
    if isinstance(data, dict):
        return data

    if not final_retry_message:
        return None
    final_messages = list(messages)
    final_messages.append(
        Message(
            role="user",
            content=final_retry_message,
        )
    )
    final_response = await provider.complete(
        final_messages,
        temperature=0.0,
        max_tokens=120,
        json_mode=False,
    )
    try:
        data = final_response.as_json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


async def _load_edit_decision_cut_review_json_payload(
    *,
    provider: object,
    response: object,
    prompt_messages: list[Message],
    timeout_sec: float,
    expected_decision_count: int = 0,
) -> dict[str, Any]:
    def _payload_needs_repair(payload: Any) -> bool:
        if not isinstance(payload, dict):
            return True
        decisions = payload.get("decisions")
        if not isinstance(decisions, list):
            return True
        if expected_decision_count > 0 and not _normalize_cut_review_decisions(payload):
            return True
        return False

    payload = _parse_reasoning_json_payload(response)

    if _payload_needs_repair(payload):
        raw_content = str(getattr(response, "raw_content", "") or getattr(response, "content", "") or "").strip()
        if not raw_content and isinstance(payload, dict):
            raw_content = json.dumps(payload, ensure_ascii=False)
        if not raw_content:
            raise ValueError("edit decision cut review payload missing repairable content")

        repair_messages = list(prompt_messages)
        repair_messages.append(Message(role="assistant", content=raw_content))
        repair_messages.append(
            Message(
                role="user",
                content=(
                    "停止继续分析。把你上一条输出修复成一个严格 JSON 对象。"
                    "不要 Markdown，不要代码块，不要解释。"
                    "只保留这个结构："
                    '{"decisions":[{"candidate_id":"","verdict":"cut|keep|unsure","confidence":0.0,"reason":"","evidence":[]}],"summary":""}'
                ),
            )
        )
        repaired = await asyncio.wait_for(
            provider.complete(
                repair_messages,
                temperature=0.0,
                max_tokens=900,
                json_mode=False,
            ),
            timeout=max(8.0, min(float(timeout_sec), 16.0)),
        )
        payload = _parse_reasoning_json_payload(repaired)
        if _payload_needs_repair(payload):
            repair_prompt = (
                "把下面的模型输出修复成一个严格 JSON 对象。"
                "不要 Markdown，不要代码块，不要解释。"
                '必须保留字段：decisions, summary。'
                '如果缺字段就补成：{"decisions":[],"summary":""}。'
                f"\n原始输出:\n{getattr(repaired, 'content', '') or raw_content}"
            )
            final_response = await asyncio.wait_for(
                provider.complete(
                    [
                        Message(role="system", content="你是 JSON 修复器，只输出严格 JSON。"),
                        Message(role="user", content=repair_prompt),
                    ],
                    temperature=0.0,
                    max_tokens=900,
                    json_mode=True,
                ),
                timeout=max(8.0, min(float(timeout_sec), 16.0)),
            )
            payload = _parse_reasoning_json_payload(final_response)
    if _payload_needs_repair(payload):
        raise ValueError("edit decision cut review payload remained unusable after repair")
    return payload if isinstance(payload, dict) else {}


def _parse_reasoning_json_payload(response: object) -> dict[str, Any] | None:
    try:
        payload = response.as_json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        return payload

    text = str(getattr(response, "content", "") or getattr(response, "raw_content", "") or "").strip()
    if not text:
        return None
    try:
        repaired = json.loads(extract_json_text(text))
    except Exception:
        return None
    return repaired if isinstance(repaired, dict) else None


async def _llm_refine_subtitle_window(
    *,
    provider: object,
    window_entries: list[Any],
    window_summary: dict[str, Any],
    max_chars: int,
    max_duration: float,
    content_profile: dict[str, Any] | None,
) -> list[Any] | None:
    flattened_words = _flatten_subtitle_window_words(window_entries)
    if len(flattened_words) < 2:
        return None

    current_score = score_subtitle_entries(
        window_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    relaxed_max_chars = max_chars + 2
    relaxed_max_duration = max_duration + 0.5
    local_candidates = generate_subtitle_window_candidates(
        window_entries,
        max_chars=relaxed_max_chars,
        max_duration=relaxed_max_duration,
        top_k=8,
    )
    current_candidate = list(window_entries)
    current_key = tuple(str(getattr(entry, "text_raw", "") or "") for entry in window_entries)
    deduped_candidates: list[list[Any]] = []
    seen_candidate_keys = {current_key}
    for candidate in local_candidates:
        key = tuple(str(getattr(entry, "text_raw", "") or "") for entry in candidate)
        if not key or key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(key)
        deduped_candidates.append(candidate)

    ranked_candidates: list[tuple[float, int, int, list[Any]]] = []
    for candidate in deduped_candidates:
        candidate_score = score_subtitle_entries(
            candidate,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        entry_delta = abs(len(candidate) - len(window_entries))
        ranked_candidates.append(
            (
                candidate_score,
                1 if len(candidate) <= len(window_entries) else 0,
                -entry_delta,
                candidate,
            )
        )
    ranked_candidates.sort(key=lambda item: (item[1], item[0], item[2]), reverse=True)

    candidate_pool: list[list[Any]] = [current_candidate] + [candidate for _score, _same_or_less, _delta, candidate in ranked_candidates[:8]]
    if len(candidate_pool) <= 1:
        return None

    candidate_scores = [
        score_subtitle_entries(
            candidate,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        for candidate in candidate_pool
    ]
    candidate_descriptions = []
    current_analysis = analyze_subtitle_segmentation(current_candidate).as_dict()
    for candidate_index, candidate in enumerate(candidate_pool):
        candidate_analysis = analyze_subtitle_segmentation(candidate).as_dict()
        candidate_descriptions.append(
            {
                "candidate_index": candidate_index,
                "entry_count": len(candidate),
                "score_delta_vs_current": round(candidate_scores[candidate_index] - current_score, 3),
                "fragment_start_count": int(candidate_analysis.get("fragment_start_count") or 0),
                "fragment_end_count": int(candidate_analysis.get("fragment_end_count") or 0),
                "suspicious_boundary_count": int(candidate_analysis.get("suspicious_boundary_count") or 0),
                "low_confidence_window_count": int(candidate_analysis.get("low_confidence_window_count") or 0),
                "texts": [str(getattr(entry, "text_raw", "") or "") for entry in candidate],
            }
        )
    best_local_candidate: list[Any] | None = None
    best_local_score = current_score
    best_local_analysis: dict[str, Any] | None = None
    best_local_rank: tuple[float, ...] | None = None
    for candidate_index, candidate in enumerate(candidate_pool[1:], start=1):
        candidate_score = candidate_scores[candidate_index]
        candidate_analysis = candidate_descriptions[candidate_index]
        candidate_rank = _subtitle_boundary_candidate_rank(
            candidate=candidate,
            candidate_score=candidate_score,
            candidate_analysis=candidate_analysis,
            current_score=current_score,
            current_entry_count=len(window_entries),
            current_analysis=current_analysis,
        )
        if (
            candidate_score <= current_score
            and int(candidate_analysis.get("low_confidence_window_count") or 0) >= int(current_analysis.get("low_confidence_window_count") or 0)
            and int(candidate_analysis.get("suspicious_boundary_count") or 0) >= int(current_analysis.get("suspicious_boundary_count") or 0)
            and (
                int(candidate_analysis.get("fragment_start_count") or 0) + int(candidate_analysis.get("fragment_end_count") or 0)
            ) >= (
                int(current_analysis.get("fragment_start_count") or 0) + int(current_analysis.get("fragment_end_count") or 0)
            )
        ):
            continue
        if best_local_rank is not None and candidate_rank <= best_local_rank:
            continue
        best_local_candidate = candidate
        best_local_score = candidate_score
        best_local_analysis = candidate_analysis
        best_local_rank = candidate_rank
    if _should_accept_strong_local_boundary_candidate(
        current_score=current_score,
        current_entry_count=len(window_entries),
        best_local_candidate=best_local_candidate,
        best_local_score=best_local_score,
        min_score_gain=_SUBTITLE_BOUNDARY_LOCAL_EARLY_ACCEPT_SCORE_GAIN,
        current_analysis=current_analysis,
        best_local_analysis=best_local_analysis,
    ):
        return best_local_candidate
    prompt = (
        "任务：重构这个中文字幕低置信窗口的条目边界。\n"
        "你只能做三件事：决定哪些词放在同一条字幕、决定在哪里切条、决定这些切条对应的时间切点。"
        "你必须严格复用给定 tokens 的原始顺序，不能改字、不能删字、不能增字、不能换说法、不能润色。\n"
        f"约束：避免断词、断固定短语、断残句；尽量保持单条<= {max_chars}字、{max_duration:.1f}秒；"
        "必要时可轻微超限以避免残句。\n"
        "优先选择 fragment_start_count、fragment_end_count、suspicious_boundary_count 更低的方案；"
        "如果候选不理想，你可以直接返回基于 tokens 的切分点，而不是只选候选编号。\n"
        "输出 JSON："
        "{\"best_candidate_index\":0,\"alternate_candidate_index\":1,"
        "\"best_cut_after_word_indices\":[],\"alternate_cut_after_word_indices\":[]}。\n"
        "如果当前分段已经最好，就让 best_candidate_index=0，且 best_cut_after_word_indices 为空数组。\n"
        f"窗口：{_subtitle_window_text_excerpt(window_summary)}\n"
        f"tokens：{_subtitle_boundary_token_line(flattened_words)}\n"
        f"候选：{json.dumps(candidate_descriptions, ensure_ascii=False)}"
    )
    data = await _complete_subtitle_boundary_json(
        provider=provider,
        messages=[
            Message(role="system", content="你是严谨的中文字幕断句助手，只输出 JSON。"),
            Message(role="user", content=prompt),
        ],
        followup_retry_message=(
            "停止继续分析。现在只输出最终 JSON 对象 "
            "{\"best_candidate_index\":0,\"alternate_candidate_index\":0,"
            "\"best_cut_after_word_indices\":[],\"alternate_cut_after_word_indices\":[]}。"
            "不要解释，不要 markdown，不要代码块。"
        ),
        final_retry_message=(
            "最后一次，不要解释，不要思考过程。"
            "直接输出一行 JSON，对象格式必须是 "
            "{\"best_candidate_index\":0,\"alternate_candidate_index\":0,"
            "\"best_cut_after_word_indices\":[],\"alternate_cut_after_word_indices\":[]}。"
            f"如果当前分段已经最好，就输出 {json.dumps({'best_candidate_index': 0, 'alternate_candidate_index': 0, 'best_cut_after_word_indices': [], 'alternate_cut_after_word_indices': []}, ensure_ascii=False)}。"
        ),
    )
    current_cuts = _subtitle_window_current_cut_indices(flattened_words, len(window_entries))
    if not data:
        if _should_accept_strong_local_boundary_candidate(
            current_score=current_score,
            current_entry_count=len(window_entries),
            best_local_candidate=best_local_candidate,
            best_local_score=best_local_score,
            min_score_gain=_SUBTITLE_BOUNDARY_LOCAL_FALLBACK_MIN_SCORE_GAIN,
            current_analysis=current_analysis,
            best_local_analysis=best_local_analysis,
        ):
            return best_local_candidate
        return None

    best_candidate: list[Any] | None = None
    best_score = current_score
    selected_indices = _iter_subtitle_candidate_selection_indices(
        data,
        current_index=0,
        limit=len(candidate_pool),
    )
    for candidate_index in selected_indices:
        candidate = candidate_pool[candidate_index]
        if len(candidate) > len(window_entries):
            continue
        candidate_score = candidate_scores[candidate_index]
        if candidate_score <= best_score:
            continue
        best_candidate = candidate
        best_score = candidate_score

    if best_candidate is None:
        for cut_indices in _iter_subtitle_boundary_cut_candidates(data, current_cuts=current_cuts):
            candidate = resegment_subtitle_window_from_cuts(
                window_entries,
                cut_after_word_indices=cut_indices,
            )
            if not candidate:
                continue
            if len(candidate) > len(window_entries):
                continue
            candidate_score = score_subtitle_entries(
                candidate,
                max_chars=max_chars,
                max_duration=max_duration,
            )
            if candidate_score <= best_score:
                continue
            best_candidate = candidate
            best_score = candidate_score

    if best_candidate is None and _should_accept_strong_local_boundary_candidate(
        current_score=current_score,
        current_entry_count=len(window_entries),
        best_local_candidate=best_local_candidate,
        best_local_score=best_local_score,
        min_score_gain=_SUBTITLE_BOUNDARY_LOCAL_FALLBACK_MIN_SCORE_GAIN,
        current_analysis=current_analysis,
        best_local_analysis=best_local_analysis,
    ):
        best_candidate = best_local_candidate
        best_score = best_local_score

    if best_candidate is None:
        return None
    if best_score < current_score + _SUBTITLE_BOUNDARY_REFINE_MIN_SCORE_GAIN:
        return None
    return best_candidate


def _select_low_confidence_windows_for_llm(
    windows: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    ordered = sorted(
        [dict(item) for item in windows if isinstance(item, dict)],
        key=lambda item: (int(item.get("start_index") or 0), int(item.get("end_index") or 0)),
    )
    usable = [
        item
        for item in ordered
        if int(item.get("end_index") or 0) > int(item.get("start_index") or 0)
    ]
    candidates = usable or ordered
    if len(candidates) <= limit:
        return candidates

    def _priority(item: dict[str, Any]) -> tuple[int, int]:
        entry_count = int(item.get("entry_count") or 0)
        total_chars = sum(len(str(text or "").strip()) for text in list(item.get("texts") or []))
        return entry_count, total_chars

    selected: list[dict[str, Any]] = []
    total = len(candidates)
    for bucket_index in range(limit):
        bucket_start = round(bucket_index * total / limit)
        bucket_end = round((bucket_index + 1) * total / limit)
        bucket = candidates[bucket_start:bucket_end] or [candidates[min(bucket_start, total - 1)]]
        selected.append(max(bucket, key=_priority))
    return selected


async def _maybe_refine_subtitle_boundaries_with_llm(
    *,
    job: Job,
    step: JobStep | None,
    entries: list[Any],
    segmentation_analysis: dict[str, Any],
    split_profile: dict[str, Any],
    content_profile: dict[str, Any] | None,
) -> tuple[list[Any], dict[str, int]]:
    raw_windows = segmentation_analysis.get("low_confidence_windows") or segmentation_analysis.get("sample_low_confidence_windows") or []
    windows = [dict(item) for item in raw_windows if isinstance(item, dict)]
    if not windows:
        return entries, {"attempted_windows": 0, "accepted_windows": 0}
    if not _subtitle_boundary_refine_llm_supported():
        return entries, {"attempted_windows": 0, "accepted_windows": 0}

    try:
        provider = get_reasoning_provider()
    except Exception:
        return entries, {"attempted_windows": 0, "accepted_windows": 0}

    selected_windows = _select_low_confidence_windows_for_llm(
        windows,
        limit=_SUBTITLE_BOUNDARY_REFINE_MAX_WINDOWS,
    )
    refined_entries = list(entries)
    attempted_windows = 0
    accepted_windows = 0
    for window in sorted(selected_windows, key=lambda item: int(item.get("start_index") or 0), reverse=True):
        start_index = int(window.get("start_index") or 0)
        end_index = int(window.get("end_index") or start_index)
        if start_index < 0 or end_index >= len(refined_entries) or start_index >= end_index:
            continue
        window_entries = refined_entries[start_index:end_index + 1]
        if len(_flatten_subtitle_window_words(window_entries)) < 2:
            continue
        attempted_windows += 1
        try:
            with llm_task_route("subtitle_postprocess", search_enabled=False, settings=get_settings()):
                with track_step_usage(job_id=job.id, step_id=step.id if step else None, step_name="subtitle_postprocess"):
                    candidate = await asyncio.wait_for(
                        _llm_refine_subtitle_window(
                            provider=provider,
                            window_entries=window_entries,
                            window_summary=window,
                            max_chars=int(split_profile["max_chars"]),
                            max_duration=float(split_profile["max_duration"]),
                            content_profile=content_profile,
                        ),
                        timeout=_SUBTITLE_POSTPROCESS_BOUNDARY_REFINE_TIMEOUT_SEC,
                    )
        except Exception:
            candidate = None
        if not candidate:
            continue
        refined_entries = refined_entries[:start_index] + candidate + refined_entries[end_index + 1:]
        refined_entries = _reindex_subtitle_entries(refined_entries)
        accepted_windows += 1
    return refined_entries, {"attempted_windows": attempted_windows, "accepted_windows": accepted_windows}


def _build_edit_plan_transcript_segments(
    transcript_rows: list[TranscriptSegment],
    transcript_evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    artifact_segments: list[dict[str, Any]] = []
    if isinstance(transcript_evidence, dict):
        artifact_segments = _normalize_transcript_segment_payloads(
            list(transcript_evidence.get("segments") or transcript_evidence.get("items") or [])
        )
    if artifact_segments:
        return artifact_segments

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


def _normalize_transcript_segment_payloads(raw_segments: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(list(raw_segments or [])):
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "index": int(item.get("index", index) or index),
                "start": float(item.get("start_time") or item.get("start") or 0.0),
                "end": float(item.get("end_time") or item.get("end") or 0.0),
                "text": str(item.get("text") or item.get("raw_text") or item.get("text_raw") or ""),
                "speaker": item.get("speaker"),
                "confidence": item.get("confidence"),
                "logprob": item.get("logprob"),
                "alignment": item.get("alignment"),
                "words": list(item.get("words") or []),
            }
        )
    return normalized


def _build_transcript_context_payload(
    transcript_rows: list[TranscriptSegment],
    canonical_transcript_layer: dict[str, Any] | None,
    transcript_fact_layer: dict[str, Any] | None,
    transcript_evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(transcript_evidence) if isinstance(transcript_evidence, dict) else {}
    canonical_segments = _normalize_transcript_segment_payloads(
        list((canonical_transcript_layer or {}).get("segments") or [])
    )
    fact_segments = _normalize_transcript_segment_payloads(
        list((transcript_fact_layer or {}).get("segments") or [])
    )
    if canonical_segments:
        payload["segments"] = canonical_segments
        payload["layer"] = str(
            (canonical_transcript_layer or {}).get("layer")
            or payload.get("layer")
            or "canonical_transcript"
        )
        payload["correction_metrics"] = dict((canonical_transcript_layer or {}).get("correction_metrics") or {})
        payload["source_basis"] = str((canonical_transcript_layer or {}).get("source_basis") or payload.get("source_basis") or "")
    elif fact_segments:
        payload["segments"] = fact_segments
        payload["layer"] = str((transcript_fact_layer or {}).get("layer") or payload.get("layer") or "transcript_fact")
    elif payload:
        normalized_segments = _normalize_transcript_segment_payloads(
            list(payload.get("segments") or payload.get("items") or [])
        )
        if normalized_segments:
            payload["segments"] = normalized_segments
    if not list(payload.get("segments") or []):
        payload["segments"] = _build_edit_plan_transcript_segments(transcript_rows, None)
        payload["layer"] = str(payload.get("layer") or "transcript_rows")
    payload["segment_count"] = len(list(payload.get("segments") or []))
    return payload


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
    metadata_updates: dict[str, Any] | None = None,
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
    if metadata_updates:
        metadata.update(metadata_updates)
    step.metadata_ = metadata
    await session.commit()


def _build_content_profile_learning_fingerprint(
    *,
    feedback_source: str,
    user_feedback: dict[str, Any],
    final_profile: dict[str, Any],
) -> str:
    payload = {
        "feedback_source": feedback_source,
        "user_feedback": dict(user_feedback or {}),
        "subject_brand": str((final_profile or {}).get("subject_brand") or "").strip(),
        "subject_model": str((final_profile or {}).get("subject_model") or "").strip(),
        "subject_type": str((final_profile or {}).get("subject_type") or "").strip(),
        "subject_domain": str((final_profile or {}).get("subject_domain") or "").strip(),
        "search_queries": list((final_profile or {}).get("search_queries") or []),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


async def _persist_content_profile_learning_once(
    session,
    *,
    step: JobStep | None,
    job: Job,
    draft_profile: dict[str, Any],
    final_profile: dict[str, Any],
    user_feedback: dict[str, Any],
    feedback_source: str,
    observation_type: str,
    context_hint: str,
) -> bool:
    normalized_feedback = dict(user_feedback or {})
    if not normalized_feedback:
        return False

    fingerprint = _build_content_profile_learning_fingerprint(
        feedback_source=feedback_source,
        user_feedback=normalized_feedback,
        final_profile=final_profile,
    )
    metadata = dict(step.metadata_ or {}) if step is not None and isinstance(step.metadata_, dict) else {}
    learning_fingerprints = dict(metadata.get("learning_fingerprints") or {})
    if learning_fingerprints.get(feedback_source) == fingerprint:
        return False

    await record_content_profile_feedback_memory(
        session,
        job=job,
        draft_profile=draft_profile,
        final_profile=final_profile,
        user_feedback=normalized_feedback,
        observation_type=observation_type,
        feedback_source=feedback_source,
    )
    from roughcut.api.jobs import _persist_confirmed_content_profile_glossary_terms

    await _persist_confirmed_content_profile_glossary_terms(
        session,
        job=job,
        draft_profile=draft_profile,
        final_profile=final_profile,
        user_feedback=normalized_feedback,
        context_hint=context_hint,
    )
    if step is not None:
        learning_fingerprints[feedback_source] = fingerprint
        metadata["learning_fingerprints"] = learning_fingerprints
        step.metadata_ = metadata
    return True


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

    settings = get_settings()
    interval_sec = max(5, int(getattr(settings, "step_heartbeat_interval_sec", 20) or 20))

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


def _current_step_heartbeat_progress(step: JobStep | None) -> float | None:
    metadata = dict((step.metadata_ or {}) if step is not None else {})
    raw_progress = metadata.get("progress")
    if raw_progress is None:
        return None
    try:
        return float(raw_progress)
    except (TypeError, ValueError):
        return None


@asynccontextmanager
async def _maintain_step_heartbeat(step: JobStep | None):
    heartbeat = _spawn_step_heartbeat(
        step_id=step.id if step is not None else None,
        detail=str((step.metadata_ or {}).get("detail") or STEP_LABELS.get(step.step_name, step.step_name) if step else ""),
        progress=_current_step_heartbeat_progress(step),
    )
    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


def _resolve_transcribe_runtime_timeout_seconds(settings: object, *, audio_path: Path | None = None) -> float:
    timeout = getattr(settings, "transcribe_runtime_timeout_sec", None)
    if timeout is None:
        timeout = getattr(settings, "step_stale_timeout_sec", 900)
    base_timeout = max(0.1, float(timeout or 900))
    if audio_path is None:
        return base_timeout

    try:
        duration = probe_audio_duration(audio_path)
    except Exception:
        duration = 0.0
    if duration <= 0:
        return base_timeout

    chunk_config = resolve_audio_chunk_config(settings)
    if not should_chunk_audio(duration=duration, config=chunk_config):
        dynamic_timeout = max(300.0, (duration * 0.75) + 180.0)
        return min(7200.0, max(base_timeout, dynamic_timeout))

    chunk_specs = build_audio_chunk_specs(duration, config=chunk_config)
    if not chunk_specs:
        return base_timeout

    retry_backoff_budget = sum(
        float(chunk_config.request_retry_backoff_sec) * (2 ** attempt)
        for attempt in range(int(chunk_config.request_max_retries))
    )
    request_budget = min(
        float(chunk_config.request_timeout_sec),
        max(45.0, float(chunk_config.chunk_size_sec) * 0.9 + 15.0),
    )
    export_budget = min(float(chunk_config.export_timeout_sec), 20.0)
    per_chunk_budget = request_budget + export_budget + retry_backoff_budget
    dynamic_timeout = (len(chunk_specs) * per_chunk_budget) + 180.0
    return min(7200.0, max(base_timeout, dynamic_timeout))


def _resolve_transcribe_no_progress_timeout_seconds(settings: object, *, audio_path: Path | None = None) -> float:
    runtime_timeout = _resolve_transcribe_runtime_timeout_seconds(settings, audio_path=audio_path)
    heartbeat_interval = max(5.0, float(getattr(settings, "step_heartbeat_interval_sec", 20) or 20))
    chunk_request_timeout = max(
        30.0,
        float(getattr(settings, "transcription_chunk_request_timeout_sec", 180.0) or 180.0),
    )
    grace_sec = max(45.0, heartbeat_interval * 3.0)
    if audio_path is not None:
        try:
            duration = probe_audio_duration(audio_path)
        except Exception:
            duration = 0.0
        if duration > 0:
            chunk_config = resolve_audio_chunk_config(settings)
            if not should_chunk_audio(duration=duration, config=chunk_config):
                single_request_budget = max(240.0, (duration * 1.25) + grace_sec)
                return min(runtime_timeout, max(90.0, single_request_budget))
    return min(runtime_timeout, max(90.0, chunk_request_timeout + grace_sec))


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
    latest_downstream_context = max(
        (artifact for artifact in artifacts if str(artifact.artifact_type or "").strip() == "downstream_context"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    latest_content_profile_final = max(
        (artifact for artifact in artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    if latest_content_profile_final is not None and (
        latest_downstream_context is None
        or (latest_content_profile_final.created_at or epoch) > (latest_downstream_context.created_at or epoch)
    ):
        return latest_content_profile_final
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


async def _load_content_profile_source_context(session, *, job_id: uuid.UUID) -> dict[str, Any]:
    result = await session.execute(
        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "content_profile")
    )
    step = result.scalar_one_or_none()
    if step is None or not isinstance(step.metadata_, dict):
        return {}
    payload = step.metadata_.get("source_context")
    return dict(payload) if isinstance(payload, dict) else {}


def _build_projection_entries_from_subtitle_items(
    subtitle_items: list[SubtitleItem],
    *,
    use_final_text: bool = False,
) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    ordered = sorted(
        list(subtitle_items or []),
        key=lambda item: (
            float(getattr(item, "start_time", 0.0) or 0.0),
            float(getattr(item, "end_time", 0.0) or 0.0),
            int(getattr(item, "item_index", 0) or 0),
        ),
    )
    for item in ordered:
        display_text = (
            str(getattr(item, "text_final", None) or getattr(item, "text_norm", None) or getattr(item, "text_raw", "") or "")
            if use_final_text
            else str(getattr(item, "text_raw", "") or "")
        )
        entries.append(
            SubtitleEntry(
                index=int(getattr(item, "item_index", 0) or 0),
                start=float(getattr(item, "start_time", 0.0) or 0.0),
                end=float(getattr(item, "end_time", 0.0) or 0.0),
                text_raw=display_text,
                text_norm=normalize_display_text(display_text),
                words=(),
            )
        )
    return entries


def _build_projection_items_from_entries(entries: list[SubtitleEntry]) -> list[SimpleNamespace]:
    projection_items: list[SimpleNamespace] = []
    for index, entry in enumerate(list(entries or [])):
        display_text = str(getattr(entry, "text_raw", "") or "")
        projection_items.append(
            SimpleNamespace(
                item_index=int(getattr(entry, "index", index) or index),
                start_time=float(getattr(entry, "start", 0.0) or 0.0),
                end_time=float(getattr(entry, "end", 0.0) or 0.0),
                text_raw=display_text,
                text_norm=str(getattr(entry, "text_norm", None) or normalize_display_text(display_text)),
                text_final=display_text,
            )
        )
    return projection_items


def _build_segmentation_segments_from_canonical_layer(canonical_transcript_layer: Any) -> list[SimpleNamespace]:
    segments: list[SimpleNamespace] = []
    raw_segments = list(getattr(canonical_transcript_layer, "segments", None) or [])
    for index, segment in enumerate(raw_segments):
        words = [
            {
                "word": str(getattr(word, "word", "") or ""),
                "start": float(getattr(word, "start", 0.0) or 0.0),
                "end": float(getattr(word, "end", 0.0) or 0.0),
                "alignment": dict(getattr(word, "alignment", {}) or {}),
            }
            for word in list(getattr(segment, "words", None) or [])
            if str(getattr(word, "word", "") or "").strip()
        ]
        segments.append(
            SimpleNamespace(
                segment_index=int(getattr(segment, "index", index) or index),
                start_time=float(getattr(segment, "start", 0.0) or 0.0),
                end_time=float(getattr(segment, "end", 0.0) or 0.0),
                text=str(getattr(segment, "text_canonical", None) or getattr(segment, "text_raw", "") or ""),
                words_json=words,
            )
        )
    return segments


def _build_reference_segment_adapters(transcript_rows: list[TranscriptSegment]) -> list[SimpleNamespace]:
    adapters: list[SimpleNamespace] = []
    for index, row in enumerate(list(transcript_rows or [])):
        adapters.append(
            SimpleNamespace(
                segment_index=int(getattr(row, "segment_index", index) or index),
                start_time=float(getattr(row, "start_time", 0.0) or 0.0),
                end_time=float(getattr(row, "end_time", 0.0) or 0.0),
                text=str(getattr(row, "text", "") or ""),
                words_json=list(getattr(row, "words_json", None) or []),
            )
        )
    return adapters


async def _build_canonical_refresh_projection(
    session,
    *,
    job_id: uuid.UUID,
    source_name: str,
    subtitle_items: list[SubtitleItem],
    canonical_transcript_layer: Any,
    projection_data: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any]]:
    effective_projection_data = dict(projection_data or {})
    split_profile = dict(effective_projection_data.get("split_profile") or {})
    if not split_profile:
        media_meta = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("media_meta",))
        media_meta_json = media_meta.data_json if media_meta and isinstance(media_meta.data_json, dict) else {}
        split_profile = _resolve_subtitle_split_profile(
            width=media_meta_json.get("width"),
            height=media_meta_json.get("height"),
        )
    boundary_refine = dict(effective_projection_data.get("boundary_refine") or {})
    canonical_segmentation_segments = _build_segmentation_segments_from_canonical_layer(canonical_transcript_layer)
    canonical_segmentation_result = (
        segment_subtitles(
            canonical_segmentation_segments,
            max_chars=int(split_profile.get("max_chars") or 30),
            max_duration=float(split_profile.get("max_duration") or 5.0),
        )
        if canonical_segmentation_segments
        else None
    )
    projection_entries = list(canonical_segmentation_result.entries) if canonical_segmentation_result else []
    if not projection_entries:
        projection_entries = _build_projection_entries_from_subtitle_items(
            subtitle_items,
            use_final_text=True,
        )
        projection_analysis = analyze_subtitle_segmentation(projection_entries)
    else:
        projection_analysis = canonical_segmentation_result.analysis
    projection_items = _build_projection_items_from_entries(projection_entries)
    subtitle_quality_report = build_subtitle_quality_report_from_items(
        subtitle_items=projection_items,
        source_name=source_name,
        content_profile={},
    )
    refreshed_projection_layer = build_subtitle_projection_layer(
        projection_items,
        segmentation_analysis=projection_analysis,
        split_profile=split_profile,
        boundary_refine=boundary_refine,
        quality_report=subtitle_quality_report,
        projection_basis="canonical_refresh",
        transcript_layer="canonical_transcript",
    )
    return refreshed_projection_layer, subtitle_quality_report


async def _persist_transcript_review_artifacts(
    session,
    *,
    job_id: uuid.UUID,
    step_id: uuid.UUID | None,
    canonical_transcript_layer: Any,
    refreshed_projection_layer: Any,
    subtitle_quality_report: dict[str, Any],
    subtitle_consistency_report: dict[str, Any],
    subtitle_term_resolution_patch: dict[str, Any],
) -> None:
    await session.execute(
        delete(Artifact).where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(
                (
                    ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
                    ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
                    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
                    ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
                    ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
                )
            ),
        )
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,
            data_json=canonical_transcript_layer.as_dict(),
        )
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
            data_json=refreshed_projection_layer.as_dict(),
        )
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
            data_json=subtitle_quality_report,
        )
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
            data_json=subtitle_consistency_report,
        )
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
            data_json=subtitle_term_resolution_patch,
        )
    )


def _build_transcript_review_result_payload(
    *,
    canonical_transcript_layer: Any,
    refreshed_projection_layer: Any,
) -> tuple[str, dict[str, Any]]:
    correction_metrics = dict(getattr(canonical_transcript_layer, "correction_metrics", {}) or {})
    accepted_count = int(correction_metrics.get("accepted_correction_count") or 0)
    pending_count = int(correction_metrics.get("pending_correction_count") or 0)
    segment_count = len(list(getattr(canonical_transcript_layer, "segments", ()) or ()))
    projection_count = len(list(getattr(refreshed_projection_layer, "entries", ()) or ()))
    detail = (
        f"已生成 {segment_count} 段 canonical transcript，刷新 {projection_count} 条字幕投影；"
        f"已接受修正 {accepted_count} 条，待确认 {pending_count} 条"
    )
    return detail, {
        "segment_count": segment_count,
        "projection_entry_count": projection_count,
        "accepted_correction_count": accepted_count,
        "pending_correction_count": pending_count,
        "source_basis": getattr(canonical_transcript_layer, "source_basis", ""),
        "projection_basis": "canonical_refresh",
    }


def _subtitle_correction_attr(correction: Any, key: str) -> Any:
    if isinstance(correction, dict):
        return correction.get(key)
    return getattr(correction, key, None)


def _serialize_transcript_review_correction(correction: Any) -> dict[str, Any]:
    human_decision = str(_subtitle_correction_attr(correction, "human_decision") or "").strip().lower()
    auto_applied = bool(_subtitle_correction_attr(correction, "auto_applied"))
    status = "accepted" if auto_applied or human_decision == "accepted" else "pending" if human_decision != "rejected" else "rejected"
    accepted = str(
        _subtitle_correction_attr(correction, "human_override")
        or _subtitle_correction_attr(correction, "suggested_span")
        or ""
    ).strip()
    original = str(_subtitle_correction_attr(correction, "original_span") or "").strip()
    return {
        "subtitle_item_id": str(_subtitle_correction_attr(correction, "subtitle_item_id") or ""),
        "original": original,
        "accepted": accepted,
        "status": status,
        "original_span": original,
        "suggested_span": accepted,
        "human_decision": _subtitle_correction_attr(correction, "human_decision"),
        "human_override": _subtitle_correction_attr(correction, "human_override"),
        "auto_applied": bool(_subtitle_correction_attr(correction, "auto_applied")),
        "source": str(_subtitle_correction_attr(correction, "source") or "").strip(),
        "change_type": str(_subtitle_correction_attr(correction, "change_type") or "").strip(),
        "confidence": _subtitle_correction_attr(correction, "confidence"),
    }


def _normalize_review_term_token(value: Any) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").strip()).lower()


def _filter_redundant_corrections_for_current_subtitles(
    corrections: list[Any],
    subtitle_items: list[SubtitleItem],
) -> list[Any]:
    subtitle_by_id = {
        str(getattr(item, "id", "") or ""): item
        for item in subtitle_items
        if getattr(item, "id", None) is not None
    }
    filtered: list[Any] = []
    for correction in corrections:
        subtitle_item_id = str(_subtitle_correction_attr(correction, "subtitle_item_id") or "").strip()
        original_span = str(_subtitle_correction_attr(correction, "original_span") or "").strip()
        suggested_span = str(_subtitle_correction_attr(correction, "suggested_span") or "").strip()
        subtitle_item = subtitle_by_id.get(subtitle_item_id)
        current_text = ""
        if subtitle_item is not None:
            current_text = str(
                getattr(subtitle_item, "text_final", None)
                or getattr(subtitle_item, "text_norm", None)
                or getattr(subtitle_item, "text_raw", None)
                or ""
            ).strip()
        normalized_text = _normalize_review_term_token(current_text)
        normalized_original = _normalize_review_term_token(original_span)
        normalized_suggested = _normalize_review_term_token(suggested_span)
        if (
            normalized_text
            and normalized_original
            and normalized_suggested
            and normalized_original != normalized_suggested
            and normalized_suggested in normalized_text
        ):
            continue
        filtered.append(correction)
    return filtered


def _timeline_overlap_seconds(
    left_start: float,
    left_end: float,
    right_start: float,
    right_end: float,
) -> float:
    return max(0.0, min(float(left_end), float(right_end)) - max(float(left_start), float(right_start)))


def _select_transcript_segments_for_correction(
    *,
    correction_payload: dict[str, Any],
    subtitle_item: SubtitleItem | None,
    transcript_rows: list[TranscriptSegment],
) -> list[TranscriptSegment]:
    if not transcript_rows:
        return []
    if subtitle_item is None:
        return transcript_rows[:1]

    subtitle_start = float(getattr(subtitle_item, "start_time", 0.0) or 0.0)
    subtitle_end = float(getattr(subtitle_item, "end_time", subtitle_start) or subtitle_start)
    original = str(correction_payload.get("original") or "").strip()
    accepted = str(correction_payload.get("accepted") or "").strip()

    candidates: list[tuple[float, int, TranscriptSegment]] = []
    for transcript_row in transcript_rows:
        overlap = _timeline_overlap_seconds(
            subtitle_start,
            subtitle_end,
            float(getattr(transcript_row, "start_time", 0.0) or 0.0),
            float(getattr(transcript_row, "end_time", 0.0) or 0.0),
        )
        if overlap <= 0.0:
            continue
        transcript_text = str(getattr(transcript_row, "text", "") or "")
        direct_match = int(bool(original and original in transcript_text) or bool(accepted and accepted in transcript_text))
        candidates.append((overlap, direct_match, transcript_row))

    if not candidates:
        return transcript_rows[:1]

    matched = [row for overlap, direct_match, row in candidates if direct_match]
    if matched:
        return matched[:1]

    candidates.sort(
        key=lambda item: (
            float(item[0]),
            -int(getattr(item[2], "segment_index", 0) or 0),
        ),
        reverse=True,
    )
    return [candidates[0][2]]


def _build_transcript_first_canonical_layer(
    *,
    transcript_rows: list[TranscriptSegment],
    subtitle_items: list[SubtitleItem],
    corrections: list[SubtitleCorrection],
    category_scope: str = "",
) -> Any:
    if not transcript_rows:
        return build_canonical_transcript_layer(
            subtitle_items,
            corrections=corrections,
            source_basis="subtitle_projection_review",
            reference_segments=_build_reference_segment_adapters(transcript_rows),
        )

    synthetic_items: list[SimpleNamespace] = []
    synthetic_corrections: list[dict[str, Any]] = []
    subtitle_by_id = {
        str(getattr(item, "id", "") or ""): item
        for item in list(subtitle_items or [])
        if str(getattr(item, "id", "") or "")
    }
    transcript_rows_ordered = sorted(
        list(transcript_rows or []),
        key=lambda row: (
            int(getattr(row, "segment_index", 0) or 0),
            float(getattr(row, "start_time", 0.0) or 0.0),
            float(getattr(row, "end_time", 0.0) or 0.0),
        ),
    )
    synthetic_ids = {
        int(getattr(row, "segment_index", index) or index): f"transcript-segment-{int(getattr(row, 'segment_index', index) or index)}"
        for index, row in enumerate(transcript_rows_ordered)
    }
    seen_corrections: set[tuple[str, str, str, str]] = set()

    for index, transcript_row in enumerate(transcript_rows_ordered):
        segment_index = int(getattr(transcript_row, "segment_index", index) or index)
        synthetic_id = synthetic_ids[segment_index]
        transcript_text = str(getattr(transcript_row, "text", "") or "")
        canonical_text = _normalize_semantic_contamination_text(
            transcript_text,
            category_scope=category_scope,
        )
        synthetic_items.append(
            SimpleNamespace(
                id=synthetic_id,
                item_index=segment_index,
                start_time=float(getattr(transcript_row, "start_time", 0.0) or 0.0),
                end_time=float(getattr(transcript_row, "end_time", 0.0) or 0.0),
                text_raw=transcript_text,
                text_norm=transcript_text,
                text_final=canonical_text,
            )
        )

    for correction in list(corrections or []):
        correction_payload = _serialize_transcript_review_correction(correction)
        subtitle_item = subtitle_by_id.get(str(correction_payload.get("subtitle_item_id") or ""))
        for transcript_row in _select_transcript_segments_for_correction(
            correction_payload=correction_payload,
            subtitle_item=subtitle_item,
            transcript_rows=transcript_rows_ordered,
        ):
            segment_index = int(getattr(transcript_row, "segment_index", 0) or 0)
            synthetic_id = synthetic_ids.get(segment_index)
            if not synthetic_id:
                continue
            key = (
                synthetic_id,
                str(correction_payload.get("original") or ""),
                str(correction_payload.get("accepted") or ""),
                str(correction_payload.get("status") or ""),
            )
            if key in seen_corrections:
                continue
            seen_corrections.add(key)
            synthetic_corrections.append(
                {
                    **correction_payload,
                    "subtitle_item_id": synthetic_id,
                }
            )

    return build_canonical_transcript_layer(
        synthetic_items,
        corrections=synthetic_corrections,
        source_basis="transcript_fact_review",
        reference_segments=_build_reference_segment_adapters(transcript_rows_ordered),
    )


def _resolve_keep_segment_bounds(segment: dict[str, Any]) -> tuple[float, float]:
    start = float(segment.get("start", segment.get("start_time", 0.0)) or 0.0)
    end = float(segment.get("end", segment.get("end_time", start)) or start)
    return start, max(start, end)


def _resolve_projection_split_profile(projection_data: dict[str, Any] | None, media_meta_json: dict[str, Any] | None) -> dict[str, Any]:
    split_profile = dict((projection_data or {}).get("split_profile") or {})
    if split_profile:
        return split_profile
    media_meta = media_meta_json or {}
    return _resolve_subtitle_split_profile(
        width=media_meta.get("width"),
        height=media_meta.get("height"),
    )


def _build_fallback_canonical_words(segment: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(segment.get("text_canonical") or segment.get("text") or segment.get("text_raw") or "").strip()
    tokens = tokenize_alignment_text(text)
    if not tokens:
        return []
    start = float(segment.get("start", 0.0) or 0.0)
    end = float(segment.get("end", start) or start)
    duration = max(0.001, end - start)
    token_span = duration / max(len(tokens), 1)
    words: list[dict[str, Any]] = []
    for token_index, token in enumerate(tokens):
        token_start = start + token_index * token_span
        token_end = end if token_index == len(tokens) - 1 else min(end, token_start + token_span)
        words.append(
            {
                "word": token,
                "start": round(token_start, 3),
                "end": round(max(token_start, token_end), 3),
                "alignment": {"source": "canonical_segment_fallback"},
            }
        )
    return words


def _project_canonical_transcript_to_timeline(
    canonical_transcript_layer: dict[str, Any] | None,
    keep_segments: list[dict[str, Any]],
    *,
    split_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    canonical_data = canonical_transcript_layer if isinstance(canonical_transcript_layer, dict) else {}
    canonical_segments = list(canonical_data.get("segments") or [])
    if not canonical_segments or not keep_segments:
        return []

    ordered_keep_segments = sorted(keep_segments, key=lambda segment: _resolve_keep_segment_bounds(segment))
    keep_map: list[dict[str, float]] = []
    out_cursor = 0.0
    for segment in ordered_keep_segments:
        in_start, in_end = _resolve_keep_segment_bounds(segment)
        keep_map.append(
            {
                "in_start": in_start,
                "in_end": in_end,
                "out_start": out_cursor,
            }
        )
        out_cursor += max(0.0, in_end - in_start)

    projected_words: list[dict[str, Any]] = []
    for segment_index, segment in enumerate(canonical_segments):
        segment_words = [
            dict(word)
            for word in list(segment.get("words") or [])
            if isinstance(word, dict) and str(word.get("word") or "").strip()
        ]
        if not segment_words:
            segment_words = _build_fallback_canonical_words(segment)
        for word_index, word in enumerate(segment_words):
            raw_start = float(word.get("start", segment.get("start", 0.0)) or 0.0)
            raw_end = float(word.get("end", raw_start) or raw_start)
            if raw_end <= raw_start:
                continue
            for keep in keep_map:
                overlap_start = max(raw_start, keep["in_start"])
                overlap_end = min(raw_end, keep["in_end"])
                if overlap_end <= overlap_start + 0.001:
                    continue
                projected_words.append(
                    {
                        "word": str(word.get("word") or "").strip(),
                        "start": round(keep["out_start"] + (overlap_start - keep["in_start"]), 3),
                        "end": round(keep["out_start"] + (overlap_end - keep["in_start"]), 3),
                        "alignment": dict(word.get("alignment") or {}),
                        "segment_index": segment_index,
                        "word_index": word_index,
                    }
                )

    if not projected_words:
        return []

    projected_words.sort(
        key=lambda word: (
            float(word.get("start", 0.0) or 0.0),
            float(word.get("end", 0.0) or 0.0),
            int(word.get("segment_index", 0) or 0),
            int(word.get("word_index", 0) or 0),
        )
    )
    projected_text = "".join(str(word.get("word") or "").strip() for word in projected_words)
    projected_segment = SimpleNamespace(
        segment_index=0,
        start_time=float(projected_words[0]["start"]),
        end_time=float(projected_words[-1]["end"]),
        text=projected_text,
        words_json=projected_words,
    )
    segmentation_result = segment_subtitles(
        [projected_segment],
        max_chars=int(split_profile.get("max_chars") or 30),
        max_duration=float(split_profile.get("max_duration") or 5.0),
    )
    projected_entries: list[dict[str, Any]] = []
    for entry in list(segmentation_result.entries or []):
        projected_entries.append(
            {
                "index": int(getattr(entry, "index", len(projected_entries)) or len(projected_entries)),
                "start_time": float(getattr(entry, "start", 0.0) or 0.0),
                "end_time": float(getattr(entry, "end", 0.0) or 0.0),
                "text_raw": str(getattr(entry, "text_raw", "") or ""),
                "text_norm": str(getattr(entry, "text_norm", None) or getattr(entry, "text_raw", "") or ""),
                "text_final": str(getattr(entry, "text_norm", None) or getattr(entry, "text_raw", "") or ""),
            }
        )
    return projected_entries


async def _build_edited_subtitle_projection(
    session,
    *,
    job_id: uuid.UUID,
    keep_segments: list[dict[str, Any]],
    projection_data: dict[str, Any] | None,
    fallback_subtitles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    canonical_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,),
    )
    media_meta = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("media_meta",))
    media_meta_json = media_meta.data_json if media_meta and isinstance(media_meta.data_json, dict) else {}
    split_profile = _resolve_projection_split_profile(projection_data, media_meta_json)
    canonical_data = canonical_artifact.data_json if canonical_artifact and isinstance(canonical_artifact.data_json, dict) else {}
    projected_entries = _project_canonical_transcript_to_timeline(
        canonical_data,
        keep_segments,
        split_profile=split_profile,
    )
    if projected_entries:
        return projected_entries
    return remap_subtitles_to_timeline(fallback_subtitles, keep_segments)


def _manual_editor_subtitle_items_from_editorial(editorial_timeline: dict[str, Any] | None) -> list[dict[str, Any]]:
    subtitle_projection = (editorial_timeline or {}).get("subtitle_projection")
    if not isinstance(subtitle_projection, dict):
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(list(subtitle_projection.get("items") or [])):
        if not isinstance(item, dict):
            continue
        start_time = max(0.0, float(item.get("start_time", 0.0) or 0.0))
        end_time = max(start_time, float(item.get("end_time", start_time) or start_time))
        if end_time <= start_time:
            continue
        items.append(
            {
                **dict(item),
                "index": int(item.get("index", index) or index),
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text_raw": str(item.get("text_raw") or ""),
                "text_norm": str(item.get("text_norm") or item.get("text_final") or item.get("text_raw") or ""),
                "text_final": str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""),
            }
        )
    return items


def _subtitle_item_payload(item: SubtitleItem) -> dict[str, Any]:
    return {
        "index": item.item_index,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "text_raw": item.text_raw,
        "text_norm": item.text_norm,
        "text_final": item.text_final,
    }


def _subtitle_projection_entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": int(entry.get("index", 0) or 0),
        "start_time": entry.get("start"),
        "end_time": entry.get("end"),
        "text_raw": entry.get("text_raw"),
        "text_norm": entry.get("text_norm"),
        "text_final": entry.get("text_final"),
    }


async def _load_latest_subtitle_projection_entries(
    session,
    *,
    job_id: uuid.UUID,
    fallback_items: list[SubtitleItem] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    projection_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,),
    )
    projection_data = projection_artifact.data_json if projection_artifact and isinstance(projection_artifact.data_json, dict) else {}
    projection_entries = [
        _subtitle_projection_entry_payload(entry)
        for entry in list(projection_data.get("entries") or [])
        if isinstance(entry, dict)
    ]
    if projection_entries:
        return projection_entries, projection_data
    return [_subtitle_item_payload(item) for item in list(fallback_items or [])], {}


async def _load_latest_subtitle_payloads(
    session,
    *,
    job_id: uuid.UUID,
    fallback_to_items: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    subtitle_dicts, projection_data = await _load_latest_subtitle_projection_entries(
        session,
        job_id=job_id,
        fallback_items=None,
    )
    if subtitle_dicts or not fallback_to_items:
        return subtitle_dicts, projection_data
    subtitle_items = await _load_subtitle_items(session, job_id=job_id)
    return [_subtitle_item_payload(item) for item in subtitle_items], {}


async def _load_subtitle_items(session, *, job_id: uuid.UUID) -> list[SubtitleItem]:
    item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    return list(item_result.scalars().all())


async def _load_subtitle_corrections(session, *, job_id: uuid.UUID) -> list[SubtitleCorrection]:
    result = await session.execute(
        select(SubtitleCorrection)
        .where(SubtitleCorrection.job_id == job_id)
        .order_by(SubtitleCorrection.created_at.asc())
    )
    return list(result.scalars().all())


async def _load_subtitle_transcript_context(
    session,
    *,
    job_id: uuid.UUID,
    include_canonical: bool = True,
    prefer_latest_projection: bool = False,
    include_subtitle_items: bool = True,
) -> tuple[
    list[SubtitleItem],
    list[dict[str, Any]],
    list[TranscriptSegment],
    list[dict[str, Any]],
    dict[str, Any],
]:
    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id, TranscriptSegment.version == 1)
        .order_by(TranscriptSegment.segment_index)
    )
    transcript_rows = list(transcript_result.scalars().all())
    subtitle_items: list[SubtitleItem] = []
    if prefer_latest_projection:
        subtitle_dicts, _projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job_id,
            fallback_to_items=True,
        )
    else:
        subtitle_items = await _load_subtitle_items(session, job_id=job_id)
        subtitle_dicts = [_subtitle_item_payload(item) for item in subtitle_items]
    if include_subtitle_items and not subtitle_items:
        subtitle_items = await _load_subtitle_items(session, job_id=job_id)
    transcript_evidence_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=("transcript_evidence",),
    )
    canonical_transcript_artifact = (
        await _load_latest_optional_artifact(
            session,
            job_id=job_id,
            artifact_types=(ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,),
        )
        if include_canonical
        else None
    )
    transcript_fact_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,),
    )
    transcript_context = _build_transcript_context_payload(
        transcript_rows,
        canonical_transcript_artifact.data_json if canonical_transcript_artifact is not None else None,
        transcript_fact_artifact.data_json if transcript_fact_artifact is not None else None,
        transcript_evidence_artifact.data_json if transcript_evidence_artifact is not None else None,
    )
    transcript_segment_dicts = _build_edit_plan_transcript_segments(
        transcript_rows,
        transcript_context,
    )
    return subtitle_items, subtitle_dicts, transcript_rows, transcript_segment_dicts, transcript_context


async def _load_content_profile_context(
    session,
    *,
    job_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id, TranscriptSegment.version == 1)
        .order_by(TranscriptSegment.segment_index)
    )
    transcript_rows = list(transcript_result.scalars().all())
    subtitle_dicts, _projection_data = await _load_latest_subtitle_payloads(
        session,
        job_id=job_id,
        fallback_to_items=True,
    )
    transcript_evidence_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=("transcript_evidence",),
    )
    canonical_transcript_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,),
    )
    transcript_fact_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,),
    )
    transcript_context = _build_transcript_context_payload(
        transcript_rows,
        canonical_transcript_artifact.data_json if canonical_transcript_artifact is not None else None,
        transcript_fact_artifact.data_json if transcript_fact_artifact is not None else None,
        transcript_evidence_artifact.data_json if transcript_evidence_artifact is not None else None,
    )
    transcript_segment_dicts = _build_edit_plan_transcript_segments(
        transcript_rows,
        transcript_context,
    )
    return subtitle_dicts, transcript_segment_dicts, transcript_context


async def _load_current_content_profile(session, *, job_id: uuid.UUID) -> dict[str, Any] | None:
    _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job_id)
    if content_profile:
        return dict(content_profile)
    profile_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_(["content_profile_final", "content_profile_draft"]),
        )
        .order_by(Artifact.created_at.desc())
    )
    profile_artifacts = profile_result.scalars().all()
    if not profile_artifacts:
        return None
    data_json = profile_artifacts[0].data_json
    return dict(data_json) if isinstance(data_json, dict) else None


async def _resolve_glossary_review_content_profile(
    *,
    session,
    job: Job,
    step: JobStep,
    settings,
    content_profile: dict[str, Any] | None,
    subtitle_dicts: list[dict[str, Any]],
    transcript_segment_dicts: list[dict[str, Any]],
    transcript_evidence: dict[str, Any] | None,
    effective_glossary_terms: list[GlossaryTerm | dict[str, Any]],
    user_memory: dict[str, Any],
) -> dict[str, Any]:
    include_research = bool(getattr(settings, "research_verifier_enabled", False))
    packaging_config = (list_packaging_assets().get("config") or {})
    if not content_profile:
        # glossary_review only needs a stable identity scaffold for lexical polishing.
        # Defer expensive full content_profile inference to the dedicated content_profile step.
        transcript_excerpt = build_transcript_excerpt(
            transcript_segment_dicts or subtitle_dicts,
            max_items=120,
            max_chars=6000,
        )
        lightweight_profile: dict[str, Any] = {
            "workflow_template": str(job.workflow_template or "").strip(),
            "copy_style": str(packaging_config.get("copy_style") or "attention_grabbing"),
            "transcript_excerpt": transcript_excerpt,
        }
        if transcript_evidence:
            lightweight_profile["transcript_evidence"] = dict(transcript_evidence)
        lightweight_profile = apply_source_identity_constraints(
            lightweight_profile,
            source_name=job.source_name,
            transcript_excerpt=transcript_excerpt,
        )
        lightweight_profile["creative_profile"] = _job_creative_profile(job)
        return lightweight_profile

    profile = dict(content_profile)
    if transcript_evidence:
        profile["transcript_evidence"] = dict(transcript_evidence)
    profile["copy_style"] = str(
        packaging_config.get("copy_style")
        or profile.get("copy_style")
        or "attention_grabbing"
    )
    topic_registry_hints = _resolve_topic_registry_hints_for_profile_short_circuit(
        source_name=job.source_name,
        transcript_excerpt=str(profile.get("transcript_excerpt") or ""),
        source_context=profile.get("source_context"),
    )
    if _profile_matches_topic_registry_hints(profile, topic_hints=topic_registry_hints):
        profile["topic_registry_short_circuit"] = {
            "enabled": True,
            "reason": "glossary_review_topic_registry_hint_aligned",
            "topic_hints": topic_registry_hints,
        }
        profile["creative_profile"] = _job_creative_profile(job)
        return profile
    enrich_search_enabled = should_enable_task_search(
        "content_profile",
        default_enabled=include_research,
        profile=profile,
        settings=settings,
    )
    async with _maintain_step_heartbeat(step):
        with llm_task_route("content_profile", search_enabled=enrich_search_enabled, settings=settings):
            with track_step_usage(job_id=job.id, step_id=step.id, step_name="glossary_review"):
                return await enrich_content_profile(
                    profile=profile,
                    source_name=job.source_name,
                    workflow_template=job.workflow_template,
                    transcript_excerpt=str(profile.get("transcript_excerpt") or ""),
                    subtitle_items=subtitle_dicts,
                    transcript_items=transcript_segment_dicts,
                    transcript_evidence=transcript_evidence,
                    glossary_terms=effective_glossary_terms,
                    user_memory=user_memory,
                    include_research=enrich_search_enabled,
                )


async def _evaluate_content_profile_automation_and_reports(
    session,
    *,
    job: Job,
    settings,
    content_profile: dict[str, Any],
    transcript_evidence: dict[str, Any] | None,
    subtitle_dicts: list[dict[str, Any]],
    user_memory: dict[str, Any],
    effective_glossary_terms: list[GlossaryTerm | dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    runtime_profile = dict(content_profile)
    if transcript_evidence:
        runtime_profile["transcript_evidence"] = dict(transcript_evidence)
    # Review is now exception-only: every job auto-continues unless a blocking
    # content, subtitle, or identity conflict is detected.
    auto_review_enabled = True
    automation = assess_content_profile_automation(
        runtime_profile,
        subtitle_items=subtitle_dicts,
        user_memory=user_memory,
        glossary_terms=effective_glossary_terms,
        source_name=job.source_name,
        auto_confirm_enabled=auto_review_enabled,
        threshold=settings.content_profile_review_threshold,
    )
    if bool((automation.get("identity_review") or {}).get("conservative_summary")):
        content_profile = apply_identity_review_guard(
            runtime_profile,
            subtitle_items=subtitle_dicts,
            user_memory=user_memory,
            glossary_terms=effective_glossary_terms,
            source_name=job.source_name,
        )
        runtime_profile = dict(content_profile)
        if transcript_evidence:
            runtime_profile["transcript_evidence"] = dict(transcript_evidence)
        automation = assess_content_profile_automation(
            runtime_profile,
            subtitle_items=subtitle_dicts,
            user_memory=user_memory,
            glossary_terms=effective_glossary_terms,
            source_name=job.source_name,
            auto_confirm_enabled=auto_review_enabled,
            threshold=settings.content_profile_review_threshold,
        )
    subtitle_quality_report = build_subtitle_quality_report(
        subtitle_items=subtitle_dicts,
        source_name=job.source_name,
        content_profile=content_profile,
    )
    corrections = await _load_subtitle_corrections(session, job_id=job.id)
    subtitle_consistency_report = build_subtitle_consistency_report(
        subtitle_items=subtitle_dicts,
        corrections=corrections,
        source_name=job.source_name,
        content_profile=content_profile,
        subtitle_quality_report=subtitle_quality_report,
    )
    if subtitle_quality_report.get("blocking"):
        content_profile, automation = _apply_blocking_report_to_content_profile(
            content_profile=content_profile,
            automation=automation,
            blocking_reasons=list(subtitle_quality_report.get("blocking_reasons") or []),
            prefix="字幕质检未通过",
        )
    if subtitle_consistency_report.get("blocking"):
        content_profile, automation = _apply_blocking_report_to_content_profile(
            content_profile=content_profile,
            automation=automation,
            blocking_reasons=list(subtitle_consistency_report.get("blocking_reasons") or []),
            prefix="字幕一致性未通过",
        )
    updated_profile = dict(content_profile)
    updated_profile["automation_review"] = automation
    updated_profile["subtitle_quality_report"] = subtitle_quality_report
    updated_profile["subtitle_consistency_report"] = subtitle_consistency_report
    return updated_profile, automation, subtitle_quality_report, subtitle_consistency_report


def _resolve_topic_registry_hints_for_profile_short_circuit(
    *,
    source_name: str,
    transcript_excerpt: str,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(source_context or {}) if isinstance(source_context, dict) else {}
    merged_source_names = [
        str(item).strip()
        for item in (payload.get("merged_source_names") or [])
        if str(item).strip()
    ]
    combined = " ".join(
        part
        for part in (
            str(source_name or "").strip(),
            transcript_excerpt,
            str(payload.get("video_description") or "").strip(),
            *merged_source_names[:3],
        )
        if part
    ).strip()
    return dict(build_intelligent_copy_topic_hints(combined) or {})


def _profile_matches_topic_registry_hints(
    profile: dict[str, Any] | None,
    *,
    topic_hints: dict[str, Any],
) -> bool:
    candidate = dict(profile or {})
    if not topic_hints:
        return False
    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        expected = str(topic_hints.get(key) or "").strip()
        actual = str(candidate.get(key) or "").strip()
        if expected and actual != expected:
            return False
    if not str(candidate.get("summary") or "").strip():
        return False
    if not str(candidate.get("engagement_question") or "").strip():
        return False
    return True


async def _apply_source_context_feedback_to_content_profile(
    session,
    *,
    job: Job,
    step: JobStep,
    settings,
    content_profile: dict[str, Any],
    source_context: dict[str, Any],
    transcript_excerpt: str,
    include_research: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_context_description = str(source_context.get("video_description") or "").strip()
    resolved_source_context_feedback: dict[str, Any] = {}
    if not source_context_description:
        return dict(content_profile), resolved_source_context_feedback

    source_context_draft_profile = dict(content_profile)
    feedback_search_enabled = should_enable_task_search(
        "content_profile",
        default_enabled=include_research,
        profile=content_profile,
        settings=settings,
    )
    with llm_task_route("content_profile", search_enabled=feedback_search_enabled, settings=settings):
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
            await _persist_content_profile_learning_once(
                session,
                step=step,
                job=job,
                draft_profile=source_context_draft_profile,
                final_profile=content_profile,
                user_feedback=resolved_source_context_feedback,
                feedback_source="task_description",
                observation_type="task_description",
                context_hint=f"task_description:{job.workflow_template or 'auto'}",
            )
    updated_profile = dict(content_profile)
    if source_context:
        updated_profile["source_context"] = {
            **source_context,
            **({"resolved_feedback": dict(resolved_source_context_feedback)} if resolved_source_context_feedback else {}),
        }
    return updated_profile, resolved_source_context_feedback


async def _apply_manual_review_feedback_to_content_profile(
    session,
    *,
    job: Job,
    step: JobStep,
    content_profile: dict[str, Any],
    transcript_excerpt: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manual_review_feedback = dict(step.metadata_.get("review_user_feedback") or {}) if isinstance(step.metadata_, dict) else {}
    review_feedback_note = str(step.metadata_.get("review_feedback") or "").strip() if isinstance(step.metadata_, dict) else ""
    resolved_manual_review_feedback: dict[str, Any] = {}
    manual_review_draft_profile = dict(content_profile)
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
    updated_profile = dict(content_profile)
    if resolved_manual_review_feedback:
        updated_profile = await apply_content_profile_feedback(
            draft_profile=content_profile,
            source_name=job.source_name,
            workflow_template=job.workflow_template,
            user_feedback=resolved_manual_review_feedback,
            reviewed_subtitle_excerpt=transcript_excerpt,
            accepted_corrections=[],
        )
        updated_profile["review_user_feedback"] = dict(manual_review_feedback)
        updated_profile["resolved_review_user_feedback"] = dict(resolved_manual_review_feedback)
    return updated_profile, manual_review_feedback, resolved_manual_review_feedback, manual_review_draft_profile


def _apply_identity_gate_to_content_profile(content_profile: dict[str, Any]) -> dict[str, Any]:
    identity_gate = evaluate_profile_identity_gate(content_profile)
    gate_reasons = [str(item).strip() for item in list(identity_gate.get("review_reasons") or []) if str(item).strip()]
    updated_profile = dict(content_profile)
    if identity_gate.get("needs_review"):
        updated_profile["needs_review"] = True
        review_reasons = [
            str(item).strip()
            for item in list(updated_profile.get("review_reasons") or [])
            if str(item).strip()
        ]
        for reason in gate_reasons:
            if reason not in review_reasons:
                review_reasons.append(reason)
        updated_profile["review_reasons"] = review_reasons
    updated_profile["verification_gate"] = identity_gate
    return updated_profile


def _merge_review_step_detail(existing_detail: str, new_detail: str) -> str:
    existing = str(existing_detail or "").strip()
    incoming = str(new_detail or "").strip()
    if not existing:
        return incoming
    if not incoming or incoming in existing:
        return existing
    return f"{existing}；{incoming}"


def _set_summary_review_state(
    review_step: JobStep,
    *,
    now: datetime,
    status: str,
    detail: str,
    progress: float,
    metadata_updates: dict[str, Any] | None = None,
    clear_finished_at: bool = False,
) -> None:
    review_step.status = status
    review_step.started_at = review_step.started_at or now
    review_step.finished_at = None if clear_finished_at else now if status == "done" else review_step.finished_at
    if status == "pending":
        review_step.finished_at = None
    review_step.error_message = None
    review_step.metadata_ = {
        **(review_step.metadata_ or {}),
        "label": STEP_LABELS.get("summary_review", "summary_review"),
        "detail": detail,
        "progress": progress,
        "updated_at": now.isoformat(),
        **(metadata_updates or {}),
    }


def _set_summary_review_done_for_manual_profile(
    review_step: JobStep,
    *,
    now: datetime,
    manual_review_feedback: dict[str, Any],
    resolved_manual_review_feedback: dict[str, Any],
) -> None:
    _set_summary_review_state(
        review_step,
        now=now,
        status="done",
        detail="已应用成片审核修正并确认内容摘要，继续后续流程。",
        progress=1.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": True,
            "review_user_feedback": dict(manual_review_feedback),
            "resolved_review_user_feedback": dict(resolved_manual_review_feedback),
        },
    )


def _set_summary_review_done_for_auto_profile(
    review_step: JobStep,
    *,
    now: datetime,
    automation: dict[str, Any],
) -> None:
    _set_summary_review_state(
        review_step,
        now=now,
        status="done",
        detail=f"已自动确认内容摘要（置信度 {automation['score']:.2f}）",
        progress=1.0,
        metadata_updates={
            "auto_confirmed": True,
            "exception_only_auto_confirmed": bool(automation.get("exception_only_auto_confirmed")),
            "confidence_score": automation["score"],
            "threshold": automation["threshold"],
            "review_reasons": automation["review_reasons"],
            "blocking_reasons": automation["blocking_reasons"],
        },
    )


def _set_summary_review_pending_for_identity(
    review_step: JobStep,
    *,
    now: datetime,
    automation: dict[str, Any],
) -> None:
    _set_summary_review_state(
        review_step,
        now=now,
        status="pending",
        detail=str((automation.get("identity_review") or {}).get("reason") or "内容摘要待人工确认"),
        progress=0.0,
        metadata_updates={
            "auto_confirmed": False,
            "identity_review": automation.get("identity_review"),
            "review_reasons": automation["review_reasons"],
            "blocking_reasons": automation["blocking_reasons"],
        },
        clear_finished_at=True,
    )


def _set_summary_review_pending_for_manual_feedback(
    review_step: JobStep,
    *,
    now: datetime,
    manual_review_feedback: dict[str, Any],
) -> None:
    _set_summary_review_state(
        review_step,
        now=now,
        status="pending",
        detail="成片审核修正尚未确认到当前主体，等待人工继续确认。",
        progress=0.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "review_user_feedback": dict(manual_review_feedback),
            "resolved_review_user_feedback": {},
        },
        clear_finished_at=True,
    )


def _set_summary_review_pending_for_subtitle_gate(
    review_step: JobStep,
    *,
    now: datetime,
    automation: dict[str, Any],
    subtitle_quality_report: dict[str, Any],
    subtitle_consistency_report: dict[str, Any],
) -> None:
    detail_bits: list[str] = []
    if subtitle_quality_report.get("blocking"):
        detail_bits.append("字幕质检未通过")
    if subtitle_consistency_report.get("blocking"):
        detail_bits.append("字幕一致性未通过")
    subtitle_review_detail = "、".join(detail_bits) + "，等待人工确认后再继续后续流程。"
    existing_detail = str((review_step.metadata_ or {}).get("detail") or "").strip()
    _set_summary_review_state(
        review_step,
        now=now,
        status="pending",
        detail=_merge_review_step_detail(existing_detail, subtitle_review_detail),
        progress=0.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "subtitle_quality_report": {
                "score": subtitle_quality_report.get("score"),
                "blocking_reasons": list(subtitle_quality_report.get("blocking_reasons") or []),
                "warning_reasons": list(subtitle_quality_report.get("warning_reasons") or []),
            },
            "subtitle_consistency_report": {
                "score": subtitle_consistency_report.get("score"),
                "blocking_reasons": list(subtitle_consistency_report.get("blocking_reasons") or []),
                "warning_reasons": list(subtitle_consistency_report.get("warning_reasons") or []),
            },
            "review_reasons": list(automation.get("review_reasons") or []),
            "blocking_reasons": list(automation.get("blocking_reasons") or []),
        },
        clear_finished_at=True,
    )


def _set_summary_review_pending_for_content_exception(
    review_step: JobStep,
    *,
    now: datetime,
    automation: dict[str, Any],
) -> None:
    blocking_reasons = [
        str(item).strip()
        for item in (automation.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    detail = "内容异常门发现阻塞问题，等待人工处理后再继续。"
    if blocking_reasons:
        detail = f"{detail} {'；'.join(blocking_reasons[:3])}"
    _set_summary_review_state(
        review_step,
        now=now,
        status="pending",
        detail=detail,
        progress=0.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "exception_gate": True,
            "review_reasons": list(automation.get("review_reasons") or []),
            "blocking_reasons": blocking_reasons,
        },
        clear_finished_at=True,
    )


def _apply_blocking_report_to_content_profile(
    *,
    content_profile: dict[str, Any],
    automation: dict[str, Any],
    blocking_reasons: list[str],
    prefix: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not blocking_reasons:
        return dict(content_profile), dict(automation)

    updated_profile = dict(content_profile)
    updated_profile["needs_review"] = True
    review_reasons = [
        str(item).strip()
        for item in list(updated_profile.get("review_reasons") or [])
        if str(item).strip()
    ]
    automation_review_reasons = [
        str(item).strip()
        for item in list(automation.get("review_reasons") or [])
        if str(item).strip()
    ]
    automation_blocking_reasons = [
        str(item).strip()
        for item in list(automation.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    for reason in blocking_reasons:
        normalized = f"{prefix}：{str(reason).strip()}"
        if normalized not in review_reasons:
            review_reasons.append(normalized)
        if normalized not in automation_review_reasons:
            automation_review_reasons.append(normalized)
        if normalized not in automation_blocking_reasons:
            automation_blocking_reasons.append(normalized)
    updated_profile["review_reasons"] = review_reasons
    updated_automation = dict(automation)
    updated_automation["review_reasons"] = automation_review_reasons
    updated_automation["blocking_reasons"] = automation_blocking_reasons
    updated_automation["quality_gate_passed"] = False
    updated_automation["auto_confirm"] = False
    return updated_profile, updated_automation


async def _finalize_content_profile_review_state(
    session,
    *,
    job: Job,
    step: JobStep,
    review_step: JobStep | None,
    content_profile: dict[str, Any],
    automation: dict[str, Any],
    manual_review_feedback: dict[str, Any],
    resolved_manual_review_feedback: dict[str, Any],
    manual_review_draft_profile: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None, dict[str, Any]]:
    auto_confirmed = not bool(automation.get("blocking_reasons"))
    context_source_profile: dict[str, Any] = dict(content_profile)
    final_profile: dict[str, Any] | None = None

    if resolved_manual_review_feedback:
        now = datetime.now(timezone.utc)
        final_profile = dict(content_profile)
        final_profile["review_mode"] = "manual_confirmed"
        context_source_profile = dict(final_profile)
        await _persist_content_profile_learning_once(
            session,
            step=step,
            job=job,
            draft_profile=manual_review_draft_profile,
            final_profile=final_profile,
            user_feedback=resolved_manual_review_feedback,
            feedback_source="final_review_feedback",
            observation_type="manual_confirm",
            context_hint=f"final_review_feedback:{job.workflow_template or 'auto'}",
        )
        if review_step is not None:
            _set_summary_review_done_for_manual_profile(
                review_step,
                now=now,
                manual_review_feedback=manual_review_feedback,
                resolved_manual_review_feedback=resolved_manual_review_feedback,
            )
        job.status = "processing"
        return auto_confirmed, final_profile, context_source_profile

    if auto_confirmed:
        now = datetime.now(timezone.utc)
        final_profile = dict(content_profile)
        final_profile["review_mode"] = "auto_confirmed"
        context_source_profile = dict(final_profile)
        if review_step is not None:
            _set_summary_review_done_for_auto_profile(
                review_step,
                now=now,
                automation={
                    **automation,
                    "auto_confirm": True,
                    "exception_only_auto_confirmed": True,
                },
            )
        job.status = "processing"
        return auto_confirmed, final_profile, context_source_profile

    if review_step is not None and bool((automation.get("identity_review") or {}).get("required")):
        _set_summary_review_pending_for_identity(
            review_step,
            now=datetime.now(timezone.utc),
            automation=automation,
        )
    elif review_step is not None and automation.get("blocking_reasons"):
        _set_summary_review_pending_for_content_exception(
            review_step,
            now=datetime.now(timezone.utc),
            automation=automation,
        )
    return auto_confirmed, final_profile, context_source_profile


def _build_content_profile_step_outcome(
    *,
    content_profile: dict[str, Any],
    automation: dict[str, Any],
    auto_confirmed: bool,
    resolved_manual_review_feedback: dict[str, Any],
    manual_review_feedback: dict[str, Any],
    review_step: JobStep | None,
    subtitle_quality_report: dict[str, Any],
    subtitle_consistency_report: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    subject = " / ".join(
        part
        for part in [
            content_profile.get("subject_type"),
            content_profile.get("video_theme"),
        ]
        if part
    ).strip()
    if resolved_manual_review_feedback:
        detail = f"已应用人工修正后的内容摘要：{subject or '人工修正完成'}"
    elif auto_confirmed:
        detail = f"已自动确认内容摘要：{subject or '自动识别完成'}"
    else:
        if manual_review_feedback and review_step is not None:
            _set_summary_review_pending_for_manual_feedback(
                review_step,
                now=datetime.now(timezone.utc),
                manual_review_feedback=manual_review_feedback,
            )
        elif review_step is not None and (
            subtitle_quality_report.get("blocking") or subtitle_consistency_report.get("blocking")
        ):
            _set_summary_review_pending_for_subtitle_gate(
                review_step,
                now=datetime.now(timezone.utc),
                automation=automation,
                subtitle_quality_report=subtitle_quality_report,
                subtitle_consistency_report=subtitle_consistency_report,
            )
        detail = f"已生成内容摘要：{subject or '待人工确认'}"
    return detail, {
        "subject_brand": content_profile.get("subject_brand"),
        "subject_model": content_profile.get("subject_model"),
        "subject_type": content_profile.get("subject_type"),
        "video_theme": content_profile.get("video_theme"),
        "auto_confirmed": auto_confirmed,
        "automation_score": automation["score"],
        "subtitle_quality_score": subtitle_quality_report.get("score"),
        "subtitle_quality_blocking": bool(subtitle_quality_report.get("blocking")),
        "subtitle_consistency_score": subtitle_consistency_report.get("score"),
        "subtitle_consistency_blocking": bool(subtitle_consistency_report.get("blocking")),
    }


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


def _dedupe_glossary_wrong_forms(*values: Any, correct_form: str) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    normalized_correct = _normalize_profile_value(correct_form)
    for raw in values:
        candidates = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
        for item in candidates:
            text = str(item or "").strip()
            normalized = _normalize_profile_value(text)
            if not text or not normalized or normalized == normalized_correct or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(text)
    return deduped


def _filter_conflicting_model_wrong_forms(*, correct_form: str, wrong_forms: list[str]) -> list[str]:
    return _shared_filter_conflicting_model_wrong_forms(correct_form=correct_form, wrong_forms=wrong_forms)


def _suppress_conflicting_model_glossary_terms(
    terms: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    for term in terms:
        correct_form = str(term.get("correct_form") or "").strip()
        wrong_forms = [str(item or "").strip() for item in (term.get("wrong_forms") or []) if str(item or "").strip()]
        if not correct_form or not wrong_forms:
            filtered.append(term)
            continue
        next_term = dict(term)
        next_term["wrong_forms"] = _filter_conflicting_model_wrong_forms(
            correct_form=correct_form,
            wrong_forms=wrong_forms,
        )
        filtered.append(next_term)
    return filtered


def _build_source_identity_glossary_terms(
    content_profile: dict[str, Any] | None,
    *,
    raw_profile: dict[str, Any] | None = None,
    source_name: str = "",
) -> list[dict[str, Any]]:
    effective_profile = dict(content_profile or {})
    original_profile = dict(raw_profile or {})
    constraints = extract_source_identity_constraints(effective_profile, source_name=source_name)
    if not constraints:
        return []

    context_hint = "文件名/任务说明经 LLM 解析后的品牌型号约束，后续字幕与文案必须按此校正。"
    terms: list[dict[str, Any]] = []
    for field_name in ("subject_brand", "subject_model"):
        correct_form = str(constraints.get(field_name) or "").strip()
        if not correct_form:
            continue
        wrong_forms = _dedupe_glossary_wrong_forms(
            constraints.get(f"{field_name}_candidates"),
            original_profile.get(field_name),
            correct_form=correct_form,
        )
        if field_name == "subject_model":
            wrong_forms = _filter_conflicting_model_wrong_forms(
                correct_form=correct_form,
                wrong_forms=wrong_forms,
            )
        terms.append(
            {
                "correct_form": correct_form,
                "wrong_forms": wrong_forms,
                "category": "source_identity",
                "context_hint": context_hint,
            }
        )

    brand = str(constraints.get("subject_brand") or "").strip()
    model = str(constraints.get("subject_model") or "").strip()
    if brand and model:
        combined_correct = f"{brand} {model}".strip()
        terms.append(
            {
                "correct_form": combined_correct,
                "wrong_forms": _dedupe_glossary_wrong_forms(
                    [f"{brand}{model}", f"{brand}·{model}", f"{brand}-{model}"],
                    correct_form=combined_correct,
                ),
                "category": "source_identity",
                "context_hint": context_hint,
            }
        )
    return terms


def _build_effective_glossary_terms(
    *,
    glossary_terms: list[GlossaryTerm] | list[dict[str, Any]],
    workflow_template: str | None,
    content_profile: dict[str, Any] | None = None,
    subtitle_items: list[dict[str, Any]] | None = None,
    source_name: str | None = None,
    subject_domain: str | None = None,
) -> list[dict[str, str | list[str] | None]]:
    raw_content_profile = dict(content_profile or {})
    effective_content_profile = apply_source_identity_constraints(
        raw_content_profile,
        source_name=source_name or "",
    )
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
    merged_terms = merge_glossary_terms(
        merged_terms,
        _build_source_identity_glossary_terms(
            effective_content_profile,
            raw_profile=raw_content_profile,
            source_name=source_name or "",
        ),
    )
    merged_terms = _suppress_conflicting_model_glossary_terms(merged_terms)
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


async def _persist_avatar_segment_outputs(
    job_id: str,
    execution_segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not execution_segments:
        return list(execution_segments or [])
    storage = get_storage()
    persisted: list[dict[str, Any]] = []
    for segment in execution_segments:
        segment_copy = dict(segment)
        local_result_raw = str(segment_copy.get("local_result_path") or "").strip()
        if segment_copy.get("status") != "success" or not local_result_raw:
            persisted.append(segment_copy)
            continue
        local_result_path = Path(local_result_raw).expanduser()
        for _ in range(_AVATAR_SEGMENT_READY_RETRIES):
            if local_result_path.exists():
                break
            await asyncio.sleep(_AVATAR_SEGMENT_READY_RETRY_SECONDS)
        if not local_result_path.exists():
            persisted.append(segment_copy)
            continue
        segment_id = str(segment_copy.get("segment_id") or uuid.uuid4().hex).strip() or uuid.uuid4().hex
        suffix = local_result_path.suffix or ".avi"
        target_key = job_key(job_id, f"avatar_segments/{segment_id}{suffix}")
        try:
            resolved_local_path = storage.resolve_path(target_key) if hasattr(storage, "resolve_path") else local_result_path
            if Path(resolved_local_path).resolve() != local_result_path.resolve():
                await storage.async_upload_file(local_result_path, target_key)
            segment_copy["video_storage_key"] = target_key
            segment_copy["local_result_path"] = str(resolved_local_path)
        except Exception:
            logger.exception(
                "Failed to persist avatar segment output for job %s segment %s",
                job_id,
                segment_id,
            )
        persisted.append(segment_copy)
    return persisted


async def _materialize_avatar_plan_segments(
    job_id: str,
    avatar_segments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not avatar_segments:
        return list(avatar_segments or [])
    execution_like_segments = [
        {
            "segment_id": segment.get("segment_id"),
            "status": "success" if str(segment.get("video_local_path") or "").strip() else segment.get("video_status"),
            "local_result_path": segment.get("video_local_path"),
            "result": segment.get("video_result"),
            "video_storage_key": segment.get("video_storage_key"),
        }
        for segment in avatar_segments
    ]
    materialized = await _persist_avatar_segment_outputs(job_id, execution_like_segments)
    materialized_by_id = {
        str(item.get("segment_id") or ""): item
        for item in materialized
        if str(item.get("segment_id") or "").strip()
    }
    updated_segments: list[dict[str, Any]] = []
    for segment in avatar_segments:
        segment_copy = dict(segment)
        persisted = materialized_by_id.get(str(segment.get("segment_id") or ""))
        if persisted and str(persisted.get("local_result_path") or "").strip():
            segment_copy["video_local_path"] = persisted.get("local_result_path")
            segment_copy["video_storage_key"] = persisted.get("video_storage_key")
            if persisted.get("result") is not None:
                segment_copy["video_result"] = persisted.get("result")
        updated_segments.append(segment_copy)
    return updated_segments


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
        source_context = await _load_content_profile_source_context(session, job_id=job.id)
        source_context_profile = {"source_context": source_context} if source_context else {}
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=None,
            content_profile=source_context_profile,
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
            content_profile=source_context_profile,
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
            content_profile=source_context_profile,
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
            content_profile=source_context_profile,
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
            transcription_route_label = _describe_transcription_route(
                provider=settings.transcription_provider,
                model=settings.transcription_model,
                language=job.language,
            )
            await _set_step_progress(session, step, detail=f"加载转写模型：{transcription_route_label}", progress=0.2)

            progress_loop = asyncio.get_running_loop()
            transcribe_timeout_sec = _resolve_transcribe_runtime_timeout_seconds(settings, audio_path=audio_path)
            last_progress = {"progress": 0.0, "ts": 0.0}
            last_detail = {"value": ""}
            accept_progress_updates = {"value": True}
            pending_progress_updates = []
            heartbeat_state = {
                "detail": f"使用 {transcription_route_label} 执行转写",
                "progress": 0.25,
            }
            transcribe_heartbeat: asyncio.Task[None] | None = None
            transcribe_watchdog: asyncio.Task[None] | None = None
            provider_activity_state = {
                "last_event_ts": time.monotonic(),
                "last_progress_ts": time.monotonic(),
                "last_event_iso": datetime.now(timezone.utc).isoformat(),
                "last_progress_iso": None,
                "phase": "startup",
                "chunk_index": 0,
                "chunk_count": 0,
            }
            stalled_reason = {"value": None}
            no_progress_timeout_sec = _resolve_transcribe_no_progress_timeout_seconds(settings, audio_path=audio_path)

            async def _persist_transcribe_progress(
                progress: float,
                detail: str,
                *,
                metadata_updates: dict[str, Any] | None = None,
            ) -> None:
                progress_factory = get_session_factory()
                async with progress_factory() as progress_session:
                    step_ref = await progress_session.get(JobStep, step.id)
                    if step_ref is None:
                        return
                    await _set_step_progress(
                        progress_session,
                        step_ref,
                        detail=detail,
                        progress=progress,
                        metadata_updates=metadata_updates,
                    )

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
                            metadata_updates={
                                "transcribe_provider_phase": provider_activity_state["phase"],
                                "transcribe_last_provider_event_at": provider_activity_state["last_event_iso"],
                                "transcribe_last_provider_progress_at": provider_activity_state["last_progress_iso"],
                                "transcribe_chunk_index": int(provider_activity_state["chunk_index"]),
                                "transcribe_chunk_count": int(provider_activity_state["chunk_count"]),
                                "transcribe_stalled": False,
                            },
                        )

            async def _transcribe_watchdog_loop(transcribe_task: asyncio.Task[TranscriptResult]) -> None:
                interval_sec = max(5.0, float(getattr(settings, "step_heartbeat_interval_sec", 20) or 20))
                while True:
                    await asyncio.sleep(interval_sec)
                    if transcribe_task.done():
                        return
                    idle_sec = max(0.0, time.monotonic() - float(provider_activity_state["last_event_ts"]))
                    if idle_sec < no_progress_timeout_sec:
                        continue
                    stalled_reason["value"] = (
                        f"转写超过 {idle_sec:.0f}s 无新进度，已判定为卡住并取消"
                    )
                    heartbeat_state["detail"] = str(stalled_reason["value"])
                    heartbeat_state["progress"] = max(float(heartbeat_state["progress"]), 0.25)
                    await _persist_transcribe_progress(
                        float(heartbeat_state["progress"]),
                        str(heartbeat_state["detail"]),
                        metadata_updates={
                            "transcribe_provider_phase": provider_activity_state["phase"],
                            "transcribe_last_provider_event_at": provider_activity_state["last_event_iso"],
                            "transcribe_last_provider_progress_at": provider_activity_state["last_progress_iso"],
                            "transcribe_chunk_index": int(provider_activity_state["chunk_index"]),
                            "transcribe_chunk_count": int(provider_activity_state["chunk_count"]),
                            "transcribe_stalled": True,
                            "transcribe_no_progress_timeout_sec": round(no_progress_timeout_sec, 3),
                        },
                    )
                    transcribe_task.cancel()
                    return

            def _on_transcribe_progress(payload: dict) -> None:
                if not accept_progress_updates["value"]:
                    return
                total_duration = float(payload.get("total_duration") or 0.0)
                segment_end = float(payload.get("segment_end") or 0.0)
                segment_count = int(payload.get("segment_count") or 0)
                chunk_index = int(payload.get("chunk_index") or 0)
                chunk_count = int(payload.get("chunk_count") or 0)
                raw_progress = float(payload.get("progress") or 0.0)
                phase = str(payload.get("phase") or "").strip()
                provider_detail = str(payload.get("detail") or "").strip()
                scaled_progress = 0.25 + (raw_progress * 0.7)
                now = time.monotonic()
                provider_activity_state["last_event_ts"] = now
                provider_activity_state["last_event_iso"] = datetime.now(timezone.utc).isoformat()
                provider_activity_state["phase"] = phase or "segment"
                provider_activity_state["chunk_index"] = chunk_index
                provider_activity_state["chunk_count"] = chunk_count
                if scaled_progress > last_progress["progress"] + 1e-6:
                    provider_activity_state["last_progress_ts"] = now
                    provider_activity_state["last_progress_iso"] = provider_activity_state["last_event_iso"]
                detail = provider_detail or f"已转写 {segment_count} 段，覆盖 {segment_end:.0f}s / {total_duration:.0f}s"
                if chunk_count > 0 and "chunk" not in detail.lower():
                    detail += f"（chunk {chunk_index}/{chunk_count}）"
                if (
                    scaled_progress - last_progress["progress"] < 0.01
                    and detail == last_detail["value"]
                    and now - last_progress["ts"] < 1.5
                ):
                    return
                last_progress["progress"] = scaled_progress
                last_progress["ts"] = now
                last_detail["value"] = detail
                heartbeat_state["detail"] = detail
                heartbeat_state["progress"] = scaled_progress
                future = asyncio.run_coroutine_threadsafe(
                    _persist_transcribe_progress(
                        scaled_progress,
                        detail,
                        metadata_updates={
                            "transcribe_provider_phase": provider_activity_state["phase"],
                            "transcribe_last_provider_event_at": provider_activity_state["last_event_iso"],
                            "transcribe_last_provider_progress_at": provider_activity_state["last_progress_iso"],
                            "transcribe_chunk_index": int(provider_activity_state["chunk_index"]),
                            "transcribe_chunk_count": int(provider_activity_state["chunk_count"]),
                            "transcribe_stalled": False,
                            "transcribe_no_progress_timeout_sec": round(no_progress_timeout_sec, 3),
                        },
                    ),
                    progress_loop,
                )
                pending_progress_updates.append(future)

            await _set_step_progress(
                session,
                step,
                detail=f"使用 {transcription_route_label} 执行转写",
                progress=0.25,
                metadata_updates={
                    "transcribe_runtime_timeout_sec": round(transcribe_timeout_sec, 3),
                    "transcribe_no_progress_timeout_sec": round(no_progress_timeout_sec, 3),
                },
            )
            transcribe_heartbeat = asyncio.create_task(_transcribe_heartbeat_loop())
            transcribe_task = asyncio.create_task(
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
                )
            )
            transcribe_watchdog = asyncio.create_task(_transcribe_watchdog_loop(transcribe_task))
            try:
                result = await asyncio.wait_for(transcribe_task, timeout=transcribe_timeout_sec)
            except asyncio.TimeoutError as exc:
                timeout_detail = f"转写超时，已等待 {transcribe_timeout_sec:.0f}s"
                heartbeat_state["detail"] = timeout_detail
                await _persist_transcribe_progress(
                    float(heartbeat_state["progress"]),
                    timeout_detail,
                    metadata_updates={
                        "transcribe_provider_phase": provider_activity_state["phase"],
                        "transcribe_last_provider_event_at": provider_activity_state["last_event_iso"],
                        "transcribe_last_provider_progress_at": provider_activity_state["last_progress_iso"],
                        "transcribe_chunk_index": int(provider_activity_state["chunk_index"]),
                        "transcribe_chunk_count": int(provider_activity_state["chunk_count"]),
                        "transcribe_stalled": bool(stalled_reason["value"]),
                        "transcribe_no_progress_timeout_sec": round(no_progress_timeout_sec, 3),
                    },
                )
                raise TimeoutError(
                    f"Transcribe step timed out after {transcribe_timeout_sec:.1f}s"
                ) from exc
            except asyncio.CancelledError as exc:
                if stalled_reason["value"]:
                    await _persist_transcribe_progress(
                        float(heartbeat_state["progress"]),
                        str(stalled_reason["value"]),
                        metadata_updates={
                            "transcribe_provider_phase": provider_activity_state["phase"],
                            "transcribe_last_provider_event_at": provider_activity_state["last_event_iso"],
                            "transcribe_last_provider_progress_at": provider_activity_state["last_progress_iso"],
                            "transcribe_chunk_index": int(provider_activity_state["chunk_index"]),
                            "transcribe_chunk_count": int(provider_activity_state["chunk_count"]),
                            "transcribe_stalled": True,
                            "transcribe_no_progress_timeout_sec": round(no_progress_timeout_sec, 3),
                        },
                    )
                    raise TimeoutError(str(stalled_reason["value"])) from exc
                raise
            finally:
                accept_progress_updates["value"] = False
                if transcribe_watchdog is not None:
                    transcribe_watchdog.cancel()
                    with suppress(asyncio.CancelledError):
                        await transcribe_watchdog
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
        transcript_fact_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,),
        )
        transcript_fact_layer = build_transcript_fact_layer(segments)
        load_elapsed = time.perf_counter() - started

        media_meta = await _load_latest_optional_artifact(session, job_id=job.id, artifact_types=("media_meta",))
        media_meta_json = media_meta.data_json if media_meta and isinstance(media_meta.data_json, dict) else {}
        split_profile = _resolve_subtitle_split_profile(
            width=media_meta_json.get("width"),
            height=media_meta_json.get("height"),
        )

        split_started = time.perf_counter()
        segmentation_result = segment_subtitles(
            segments,
            max_chars=int(split_profile["max_chars"]),
            max_duration=float(split_profile["max_duration"]),
        )
        entries = segmentation_result.entries
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        source_context = await _load_content_profile_source_context(session, job_id=job.id)
        if source_context:
            content_profile = {
                **dict(content_profile or {}),
                "source_context": {
                    **source_context,
                    **(
                        dict((content_profile or {}).get("source_context") or {})
                        if isinstance((content_profile or {}).get("source_context"), dict)
                        else {}
                    ),
                },
            }
        segmentation_input_stats = {
            "provider_word_segment_count": int(segmentation_result.analysis.provider_word_segment_count or 0),
            "synthetic_word_segment_count": int(segmentation_result.analysis.synthetic_word_segment_count or 0),
            "untrusted_word_segment_count": int(segmentation_result.analysis.untrusted_word_segment_count or 0),
            "text_only_segment_count": int(segmentation_result.analysis.text_only_segment_count or 0),
            "global_word_segmentation_used": bool(segmentation_result.analysis.global_word_segmentation_used),
        }
        llm_boundary_refine = {"attempted_windows": 0, "accepted_windows": 0}
        if segmentation_result.analysis.low_confidence_window_count > 0:
            segmentation_analysis_payload = segmentation_result.analysis.as_dict()
            segmentation_analysis_payload["low_confidence_windows"] = [
                dict(item)
                for item in (segmentation_result.analysis.low_confidence_windows or ())
                if isinstance(item, dict)
            ]
            await _set_step_progress(
                session,
                step,
                detail=(
                    f"检测到 {segmentation_result.analysis.low_confidence_window_count} 个低置信度断句窗口，"
                    "尝试做边界复判"
                ),
                progress=0.55,
            )
            entries, llm_boundary_refine = await _maybe_refine_subtitle_boundaries_with_llm(
                job=job,
                step=step,
                entries=entries,
                segmentation_analysis=segmentation_analysis_payload,
                split_profile=split_profile,
                content_profile=content_profile,
            )
            segmentation_result.analysis = analyze_subtitle_segmentation(entries)
            segmentation_result.analysis.provider_word_segment_count = segmentation_input_stats["provider_word_segment_count"]
            segmentation_result.analysis.synthetic_word_segment_count = segmentation_input_stats["synthetic_word_segment_count"]
            segmentation_result.analysis.untrusted_word_segment_count = segmentation_input_stats["untrusted_word_segment_count"]
            segmentation_result.analysis.text_only_segment_count = segmentation_input_stats["text_only_segment_count"]
            segmentation_result.analysis.global_word_segmentation_used = segmentation_input_stats["global_word_segmentation_used"]
        split_elapsed = time.perf_counter() - split_started
        await _set_step_progress(
            session,
            step,
            detail=(
                f"按{split_profile['orientation']}节奏生成字幕 {len(entries)} 条，"
                f"每条最多 {int(split_profile['max_chars'])} 字 / {float(split_profile['max_duration']):.1f}s"
                + (
                    f"，已使用 {int(segmentation_result.analysis.synthetic_word_segment_count)} 段合成词级锚点"
                    if int(segmentation_result.analysis.synthetic_word_segment_count) > 0
                    else ""
                )
                + (
                    f"，另有 {int(segmentation_result.analysis.untrusted_word_segment_count) + int(segmentation_result.analysis.text_only_segment_count)} 段文本回退对齐"
                    if (
                        int(segmentation_result.analysis.untrusted_word_segment_count)
                        + int(segmentation_result.analysis.text_only_segment_count)
                    ) > 0
                    else ""
                )
            ),
            progress=0.7,
        )
        step_metadata = dict(step.metadata_ or {})
        step_metadata["subtitle_segmentation"] = segmentation_result.analysis.as_dict()
        step_metadata["subtitle_boundary_refine"] = llm_boundary_refine
        step.metadata_ = step_metadata
        save_started = time.perf_counter()
        items = await save_subtitle_items(job.id, entries, session)
        glossary_result = await session.execute(select(GlossaryTerm))
        glossary_terms = glossary_result.scalars().all()
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
        semantic_cleanup_count = _apply_subtitle_semantic_cleanup(
            items,
            job=job,
            content_profile=content_profile,
            review_memory=review_memory,
        )
        polished_count += semantic_cleanup_count
        subtitle_quality_report = build_subtitle_quality_report_from_items(
            subtitle_items=items,
            source_name=job.source_name,
            content_profile=content_profile,
        )
        subtitle_projection_layer = build_subtitle_projection_layer(
            items,
            segmentation_analysis=segmentation_result.analysis,
            split_profile=split_profile,
            boundary_refine=llm_boundary_refine,
            quality_report=subtitle_quality_report,
            projection_basis="display_baseline",
            transcript_layer="transcript_fact",
        )
        architecture_artifacts = build_subtitle_architecture_artifacts(
            job_id=job.id,
            step_id=step.id,
            transcript_fact_layer=transcript_fact_layer,
            canonical_transcript_layer=None,
            subtitle_projection_layer=subtitle_projection_layer,
        )
        if transcript_fact_artifact is None:
            session.add(architecture_artifacts[0])
        session.add(architecture_artifacts[1])
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
                data_json=subtitle_quality_report,
            )
        )
        step_metadata = dict(step.metadata_ or {})
        step_metadata["subtitle_quality_report"] = {
            "score": subtitle_quality_report.get("score"),
            "blocking": bool(subtitle_quality_report.get("blocking")),
            "blocking_reasons": list(subtitle_quality_report.get("blocking_reasons") or []),
            "warning_reasons": list(subtitle_quality_report.get("warning_reasons") or []),
        }
        step.metadata_ = step_metadata
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
            "subtitle_quality_score": subtitle_quality_report.get("score"),
            "subtitle_quality_blocking": bool(subtitle_quality_report.get("blocking")),
            "subtitle_quality_blocking_reasons": list(subtitle_quality_report.get("blocking_reasons") or []),
            "subtitle_profile": split_profile,
            "subtitle_segmentation": segmentation_result.analysis.as_dict(),
            "subtitle_boundary_refine": llm_boundary_refine,
            "transcript_fact_layer_artifact_type": ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
            "subtitle_projection_layer_artifact_type": ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,
            "elapsed_seconds": round(total_elapsed, 3),
            "load_seconds": round(load_elapsed, 3),
            "split_seconds": round(split_elapsed, 3),
            "save_seconds": round(save_elapsed, 3),
        }


async def run_subtitle_term_resolution(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "subtitle_term_resolution")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="解析术语候选并生成纠偏 patch", progress=0.1)

        subtitle_dicts, _projection_data = await _load_latest_subtitle_payloads(session, job_id=job.id)

        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        source_context = await _load_content_profile_source_context(session, job_id=job.id)
        if source_context:
            content_profile = {
                **dict(content_profile or {}),
                "source_context": {
                    **source_context,
                    **(
                        dict((content_profile or {}).get("source_context") or {})
                        if isinstance((content_profile or {}).get("source_context"), dict)
                        else {}
                    ),
                },
            }
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
        source_constrained_profile = apply_source_identity_constraints(
            dict(content_profile or {}),
            source_name=job.source_name,
        )

        await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
        subtitle_items = await _load_subtitle_items(session, job_id=job.id)
        corrections = await apply_glossary_corrections(
            job.id,
            subtitle_items,
            session,
            glossary_terms=effective_glossary_terms,
            content_profile=source_constrained_profile,
        )
        patch = build_subtitle_term_resolution_patch(
            corrections=corrections,
            source_name=job.source_name,
            content_profile=source_constrained_profile,
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
                data_json=patch,
            )
        )
        step.metadata_ = {
            **(step.metadata_ or {}),
            "term_resolution_patch": {
                "patch_count": patch["metrics"]["patch_count"],
                "pending_count": patch["metrics"]["pending_count"],
                "auto_applied_count": patch["metrics"]["auto_applied_count"],
                "autocorrect_policy": str(patch.get("autocorrect_policy") or "lexical_only"),
                "confidence": patch.get("confidence"),
            },
        }
        await _set_step_progress(
            session,
            step,
            detail=(
                f"术语候选 {patch['metrics']['patch_count']} 条，"
                f"词级自动接受 {patch['metrics']['auto_applied_count']} 条，"
                f"待确认 {patch['metrics']['pending_count']} 条"
            ),
            progress=1.0,
        )
        await session.commit()
        return {
            "patch_count": patch["metrics"]["patch_count"],
            "auto_applied_count": patch["metrics"]["auto_applied_count"],
            "pending_count": patch["metrics"]["pending_count"],
            "blocking": bool(patch.get("blocking")),
        }


async def run_subtitle_consistency_review(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "subtitle_consistency_review")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="检查字幕与文件名/纠偏结果是否一致", progress=0.12)

        subtitle_dicts, _projection_data = await _load_latest_subtitle_payloads(session, job_id=job.id)
        corrections = await _load_subtitle_corrections(session, job_id=job.id)
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        quality_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,),
        )
        quality_report = quality_artifact.data_json if quality_artifact and isinstance(quality_artifact.data_json, dict) else None
        consistency_report = build_subtitle_consistency_report(
            subtitle_items=subtitle_dicts,
            corrections=corrections,
            source_name=job.source_name,
            content_profile=content_profile,
            subtitle_quality_report=quality_report,
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
                data_json=consistency_report,
            )
        )
        step.metadata_ = {
            **(step.metadata_ or {}),
            "subtitle_consistency_report": {
                "score": consistency_report.get("score"),
                "blocking": bool(consistency_report.get("blocking")),
                "blocking_reasons": list(consistency_report.get("blocking_reasons") or []),
                "warning_reasons": list(consistency_report.get("warning_reasons") or []),
            },
        }
        await _set_step_progress(
            session,
            step,
            detail=(
                "字幕一致性存在阻断项，已等待后续人工复核"
                if consistency_report.get("blocking")
                else "字幕一致性审校通过"
            ),
            progress=1.0,
        )
        await session.commit()
        return {
            "score": consistency_report.get("score"),
            "blocking": bool(consistency_report.get("blocking")),
            "blocking_reasons": list(consistency_report.get("blocking_reasons") or []),
            "warning_reasons": list(consistency_report.get("warning_reasons") or []),
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
        (
            subtitle_dicts,
            transcript_dicts,
            transcript_evidence,
        ) = await _load_content_profile_context(
            session,
            job_id=job.id,
        )
        reviewed_subtitle_excerpt = build_reviewed_transcript_excerpt(subtitle_dicts)
        transcript_excerpt = (
            build_transcript_excerpt(transcript_dicts)
            or reviewed_subtitle_excerpt
            or build_transcript_excerpt(subtitle_dicts)
        )
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
        transcript_digest = digest_payload(
            [
                {
                    "index": item.get("index"),
                    "start": item.get("start"),
                    "end": item.get("end"),
                    "text": item.get("text"),
                    "speaker": item.get("speaker"),
                }
                for item in transcript_dicts
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
        existing_profile_artifact_result = await session.execute(
            select(Artifact.id)
            .where(
                Artifact.job_id == job.id,
                Artifact.artifact_type.in_(_CONTENT_PROFILE_ARTIFACT_TYPES),
            )
            .limit(1)
        )
        has_existing_profile_artifact = existing_profile_artifact_result.scalar_one_or_none() is not None
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
            transcript_digest=transcript_digest,
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
                transcript_digest=transcript_digest,
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
                seeded_search_enabled = should_enable_task_search(
                    "content_profile",
                    default_enabled=include_research,
                    profile=seeded_profile,
                    settings=settings,
                )
                async with _maintain_step_heartbeat(step):
                    with llm_task_route("content_profile", search_enabled=seeded_search_enabled, settings=settings):
                        with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                            content_profile = await enrich_content_profile(
                                profile=seeded_profile,
                                source_name=job.source_name,
                                workflow_template=job.workflow_template,
                                transcript_excerpt=transcript_excerpt,
                                subtitle_items=subtitle_dicts,
                                transcript_items=transcript_dicts,
                                transcript_evidence=transcript_evidence,
                                glossary_terms=effective_glossary_terms,
                                user_memory=user_memory,
                                include_research=seeded_search_enabled,
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
                initial_search_enabled = should_enable_task_search(
                    "content_profile",
                    default_enabled=include_research,
                    profile=seeded_profile or None,
                    settings=settings,
                )
                async with _maintain_step_heartbeat(step):
                    with llm_task_route("content_profile", search_enabled=initial_search_enabled, settings=settings):
                        with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                            content_profile = await infer_content_profile(
                                source_path=source_path,
                                source_name=job.source_name,
                                subtitle_items=subtitle_dicts,
                                transcript_items=transcript_dicts,
                                transcript_evidence=transcript_evidence,
                                workflow_template=job.workflow_template,
                                user_memory=user_memory,
                                glossary_terms=effective_glossary_terms,
                                include_research=initial_search_enabled,
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
                if not has_existing_profile_artifact:
                    topic_registry_hints = _resolve_topic_registry_hints_for_profile_short_circuit(
                        source_name=job.source_name,
                        transcript_excerpt=transcript_excerpt,
                        source_context=source_context,
                    )
                    enrich_cache_namespace = "content_profile.enrich"
                    enrich_cache_fingerprint = build_content_profile_cache_fingerprint(
                        source_name=job.source_name,
                        source_file_hash=job.file_hash,
                        workflow_template=job.workflow_template,
                        transcript_excerpt=transcript_excerpt,
                        subtitle_digest=subtitle_digest,
                        transcript_digest=transcript_digest,
                        glossary_terms=effective_glossary_terms,
                        user_memory=user_memory,
                        include_research=include_research,
                        copy_style=copy_style,
                        seeded_profile=content_profile,
                    )
                    enrich_cache_key = build_cache_key(enrich_cache_namespace, enrich_cache_fingerprint)
                    usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
                    enrich_search_enabled = should_enable_task_search(
                        "content_profile",
                        default_enabled=include_research,
                        profile=content_profile,
                        settings=settings,
                    )
                    if _profile_matches_topic_registry_hints(content_profile, topic_hints=topic_registry_hints):
                        content_profile = {
                            **dict(content_profile or {}),
                            "topic_registry_short_circuit": {
                                "enabled": True,
                                "reason": "topic_registry_hint_aligned",
                                "topic_hints": topic_registry_hints,
                            },
                        }
                    else:
                        async with _maintain_step_heartbeat(step):
                            with llm_task_route("content_profile", search_enabled=enrich_search_enabled, settings=settings):
                                with track_step_usage(job_id=job.id, step_id=step.id, step_name="content_profile"):
                                    content_profile = await enrich_content_profile(
                                        profile=content_profile,
                                        source_name=job.source_name,
                                        workflow_template=job.workflow_template,
                                        transcript_excerpt=transcript_excerpt,
                                        subtitle_items=subtitle_dicts,
                                        transcript_items=transcript_dicts,
                                        transcript_evidence=transcript_evidence,
                                        glossary_terms=effective_glossary_terms,
                                        user_memory=user_memory,
                                        include_research=enrich_search_enabled,
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
        content_profile, _resolved_source_context_feedback = await _apply_source_context_feedback_to_content_profile(
            session,
            job=job,
            step=step,
            settings=settings,
            content_profile=content_profile,
            source_context=source_context,
            transcript_excerpt=transcript_excerpt,
            include_research=include_research,
        )
        (
            content_profile,
            manual_review_feedback,
            resolved_manual_review_feedback,
            manual_review_draft_profile,
        ) = await _apply_manual_review_feedback_to_content_profile(
            session,
            job=job,
            step=step,
            content_profile=content_profile,
            transcript_excerpt=transcript_excerpt,
        )
        content_profile = apply_source_identity_constraints(
            content_profile,
            source_name=job.source_name,
            transcript_excerpt=transcript_excerpt,
        )
        content_profile["creative_preferences"] = merge_content_profile_creative_preferences(
            content_profile,
            user_memory=user_memory,
        )
        content_profile["creative_profile"] = _job_creative_profile(job)
        (
            content_profile,
            automation,
            subtitle_quality_report,
            subtitle_consistency_report,
        ) = await _evaluate_content_profile_automation_and_reports(
            session,
            job=job,
            settings=settings,
            content_profile=content_profile,
            transcript_evidence=transcript_evidence,
            subtitle_dicts=subtitle_dicts,
            user_memory=user_memory,
            effective_glossary_terms=effective_glossary_terms,
        )
        ocr_profile = None
        if bool(getattr(settings, "ocr_enabled", False)):
            candidate_ocr_profile = content_profile.pop("ocr_profile", None)
            if isinstance(candidate_ocr_profile, dict):
                ocr_profile = candidate_ocr_profile
        review_step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "summary_review")
        )
        review_step = review_step_result.scalar_one_or_none()
        auto_confirmed, final_profile, context_source_profile = await _finalize_content_profile_review_state(
            session,
            job=job,
            step=step,
            review_step=review_step,
            content_profile=content_profile,
            automation=automation,
            manual_review_feedback=manual_review_feedback,
            resolved_manual_review_feedback=resolved_manual_review_feedback,
            manual_review_draft_profile=manual_review_draft_profile,
        )

        persist_content_profile_artifacts(
            session,
            job=job,
            step=step,
            review_step=review_step,
            draft_profile=content_profile,
            final_profile=final_profile,
            downstream_profile=context_source_profile,
            subtitle_quality_report=subtitle_quality_report,
            ocr_profile=ocr_profile,
        )
        detail, result_payload = _build_content_profile_step_outcome(
            content_profile=content_profile,
            automation=automation,
            auto_confirmed=auto_confirmed,
            resolved_manual_review_feedback=resolved_manual_review_feedback,
            manual_review_feedback=manual_review_feedback,
            review_step=review_step,
            subtitle_quality_report=subtitle_quality_report,
            subtitle_consistency_report=subtitle_consistency_report,
        )
        await _set_step_progress(session, step, detail=detail, progress=1.0)
        await session.commit()
        if not auto_confirmed and not resolved_manual_review_feedback:
            try:
                await get_telegram_review_bot_service().notify_content_profile_review(job.id)
            except Exception:
                logger.exception("Failed to send Telegram content profile review for job %s", job.id)
                enqueue_review_notification(
                    kind="content_profile",
                    job_id=str(job.id),
                )

        return result_payload


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
        (
            subtitle_items,
            subtitle_dicts,
            _transcript_rows,
            transcript_segment_dicts,
            transcript_evidence,
        ) = await _load_subtitle_transcript_context(
            session,
            job_id=job.id,
            include_canonical=False,
            prefer_latest_projection=True,
        )
        content_profile = await _load_current_content_profile(session, job_id=job.id)
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
        source_constrained_profile = apply_source_identity_constraints(
            dict(content_profile or {}),
            source_name=job.source_name,
        )
        corrections = await _load_subtitle_corrections(session, job_id=job.id)
        if not corrections:
            corrections = await apply_glossary_corrections(
                job.id,
                subtitle_items,
                session,
                glossary_terms=effective_glossary_terms,
                content_profile=source_constrained_profile,
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
        reviewed_transcript_layer = _build_transcript_first_canonical_layer(
            transcript_rows=_transcript_rows,
            subtitle_items=subtitle_items,
            corrections=corrections,
            category_scope=_resolve_subtitle_semantic_cleanup_scope(
                job=job,
                content_profile=content_profile,
                review_memory={"terms": [{"category_scope": subject_domain or ""}]},
            ),
        )
        reviewed_transcript_context = reviewed_transcript_layer.as_dict()
        reviewed_transcript_dicts = _normalize_transcript_segment_payloads(
            list(reviewed_transcript_context.get("segments") or [])
        )
        user_memory = await load_content_profile_user_memory(session, subject_domain=subject_domain)
        content_profile = await _resolve_glossary_review_content_profile(
            session=session,
            job=job,
            step=step,
            settings=settings,
            content_profile=content_profile,
            subtitle_dicts=subtitle_dicts,
            transcript_segment_dicts=reviewed_transcript_dicts or transcript_segment_dicts,
            transcript_evidence=reviewed_transcript_context or transcript_evidence,
            effective_glossary_terms=effective_glossary_terms,
            user_memory=user_memory,
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
        polished_count = await polish_subtitle_items(
            subtitle_items,
            content_profile=content_profile,
            glossary_terms=effective_glossary_terms,
            review_memory=review_memory,
            allow_llm=False,
        )
        polished_count += _apply_subtitle_semantic_cleanup(
            subtitle_items,
            job=job,
            content_profile=content_profile,
            review_memory=review_memory,
        )

        content_profile = _apply_identity_gate_to_content_profile(content_profile)
        identity_gate = content_profile.get("verification_gate") if isinstance(content_profile.get("verification_gate"), dict) else {}

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
                + ("；实体身份需复核" if identity_gate.get("needs_review") else "")
            ),
            progress=1.0,
        )
        await session.commit()
        if pending_corrections > 0:
            try:
                await get_telegram_review_bot_service().notify_subtitle_review(job.id)
            except Exception:
                logger.exception("Failed to send Telegram subtitle review for job %s", job.id)
                enqueue_review_notification(
                    kind="subtitle_review",
                    job_id=str(job.id),
                )

        return {
            "correction_count": len(corrections),
            "auto_accepted_correction_count": auto_accepted_corrections,
            "pending_correction_count": pending_corrections,
            "polished_count": polished_count,
            "review_required": bool(identity_gate.get("needs_review")),
            "identity_gate_conflicts": list(identity_gate.get("conflicts") or []),
            "identity_gate_missing_supported_fields": list(identity_gate.get("missing_supported_fields") or []),
            "workflow_template": content_profile.get("workflow_template"),
            "subject": " ".join(
                part for part in [
                    content_profile.get("subject_brand"),
                    content_profile.get("subject_model"),
                ] if part
            ).strip(),
        }


async def run_transcript_review(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "transcript_review")
        )
        step = step_result.scalar_one()
        await _set_step_progress(session, step, detail="读取字幕修订结果并生成 canonical transcript", progress=0.2)
        (
            subtitle_items,
            subtitle_dicts,
            _transcript_rows,
            _transcript_segment_dicts,
            _transcript_evidence,
        ) = await _load_subtitle_transcript_context(
            session,
            job_id=job.id,
            include_canonical=False,
        )
        corrections = await _load_subtitle_corrections(session, job_id=job.id)
        active_corrections = _filter_redundant_corrections_for_current_subtitles(corrections, subtitle_items)
        content_profile = await _load_current_content_profile(session, job_id=job.id)
        subject_domain = _infer_subject_domain_for_memory(
            workflow_template=job.workflow_template,
            subtitle_items=subtitle_dicts,
            content_profile=content_profile or {},
            source_name=job.source_name,
        )
        category_scope = _resolve_subtitle_semantic_cleanup_scope(
            job=job,
            content_profile=content_profile,
            review_memory={"terms": [{"category_scope": subject_domain or ""}]},
        )
        canonical_transcript_layer = _build_transcript_first_canonical_layer(
            transcript_rows=_transcript_rows,
            subtitle_items=subtitle_items,
            corrections=corrections,
            category_scope=category_scope,
        )
        projection_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,),
        )
        projection_data = projection_artifact.data_json if projection_artifact and isinstance(projection_artifact.data_json, dict) else {}
        refreshed_projection_layer, subtitle_quality_report = await _build_canonical_refresh_projection(
            session,
            job_id=job.id,
            source_name=job.source_name,
            subtitle_items=subtitle_items,
            canonical_transcript_layer=canonical_transcript_layer,
            projection_data=projection_data,
        )
        refreshed_projection_payload = (
            refreshed_projection_layer.as_dict()
            if hasattr(refreshed_projection_layer, "as_dict")
            else {}
        )
        refreshed_projection_entries = [
            dict(entry)
            for entry in list(refreshed_projection_payload.get("entries") or [])
            if isinstance(entry, dict)
        ]
        subtitle_consistency_report = build_subtitle_consistency_report(
            subtitle_items=refreshed_projection_entries,
            corrections=active_corrections,
            source_name=job.source_name,
            content_profile={},
            subtitle_quality_report=subtitle_quality_report,
        )
        subtitle_term_resolution_patch = build_subtitle_term_resolution_patch(
            corrections=active_corrections,
            source_name=job.source_name,
            content_profile={},
        )
        await _set_step_progress(session, step, detail="写入 canonical transcript 并刷新 subtitle projection", progress=0.75)
        await _persist_transcript_review_artifacts(
            session,
            job_id=job.id,
            step_id=step.id,
            canonical_transcript_layer=canonical_transcript_layer,
            refreshed_projection_layer=refreshed_projection_layer,
            subtitle_quality_report=subtitle_quality_report,
            subtitle_consistency_report=subtitle_consistency_report,
            subtitle_term_resolution_patch=subtitle_term_resolution_patch,
        )
        detail, result_payload = _build_transcript_review_result_payload(
            canonical_transcript_layer=canonical_transcript_layer,
            refreshed_projection_layer=refreshed_projection_layer,
        )
        await _set_step_progress(
            session,
            step,
            detail=detail,
            progress=1.0,
        )
        await session.commit()
        return result_payload


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
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
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
            detail=(
                f"翻译校对后的字幕（{source_language} -> {target_language}）"
                + (
                    f"，来源 {projection_data.get('projection_kind') or 'subtitle_projection'}"
                    if projection_data
                    else ""
                )
            ),
            progress=0.72,
        )
        async with _maintain_step_heartbeat(step):
            with llm_task_route("subtitle_translation", search_enabled=False, settings=get_settings()):
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
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        await _set_step_progress(
            session,
            step,
            detail=(
                "生成导演建议稿与重配音计划"
                + (f"，字幕来源 {projection_data.get('projection_kind')}" if projection_data else "")
            ),
            progress=0.68,
        )
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
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
        _profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        director_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("ai_director_plan",),
        )
        ai_director_plan = director_artifact.data_json if director_artifact and director_artifact.data_json else {}

        await _set_step_progress(
            session,
            step,
            detail=(
                "生成数字人解说分镜与 provider 请求体"
                + (f"，字幕来源 {projection_data.get('projection_kind')}" if projection_data else "")
            ),
            progress=0.72,
        )
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
                    source_audio_meta = await probe(source_audio_path)
                    source_audio_duration = float(getattr(source_audio_meta, "duration", 0.0) or 0.0)
                    avatar_segments = refine_avatar_commentary_segments_for_media_duration(
                        avatar_segments,
                        subtitle_dicts,
                        media_duration_sec=source_audio_duration,
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
                    render_execution["segments"] = await _persist_avatar_segment_outputs(
                        str(job.id),
                        render_execution.get("segments") if render_execution else None,
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
                render_execution["segments"] = await _persist_avatar_segment_outputs(
                    str(job.id),
                    render_execution.get("segments") if render_execution else None,
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
        await _set_step_progress(session, step, detail="加载媒体参数、冻结字幕与音频", progress=0.15)

        # Get media meta for duration
        meta_artifact = await _load_latest_artifact(session, job.id, "media_meta")
        duration = meta_artifact.data_json["duration"]

        # Get audio for silence detection
        audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")

        # Get subtitle payloads for filler detection
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
        transcript_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        transcript_rows = transcript_result.scalars().all()
        transcript_evidence_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=("transcript_evidence",),
        )
        canonical_transcript_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,),
        )
        transcript_fact_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,),
        )
        transcript_context = _build_transcript_context_payload(
            transcript_rows,
            canonical_transcript_artifact.data_json if canonical_transcript_artifact is not None else None,
            transcript_fact_artifact.data_json if transcript_fact_artifact is not None else None,
            transcript_evidence_artifact.data_json if transcript_evidence_artifact is not None else None,
        )
        transcript_segment_dicts = _build_edit_plan_transcript_segments(
            transcript_rows,
            transcript_context,
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
        decision = await _maybe_review_edit_decision_cuts_with_llm(
            job_id=job.id,
            source_name=str(job.source_name or ""),
            decision=decision,
            subtitle_items=subtitle_dicts,
            transcript_segments=transcript_segment_dicts,
            content_profile=content_profile,
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
        remapped_subtitles = await _build_edited_subtitle_projection(
            session,
            job_id=job.id,
            keep_segments=keep_segments,
            projection_data=projection_data,
            fallback_subtitles=subtitle_dicts,
        )
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
        await _set_step_progress(
            session,
            step,
            detail="准备时间线、字幕和输出目录",
            progress=0.05,
        )

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
        manual_editor_meta = render_plan_timeline.data_json.get("manual_editor") or {}
        manual_subtitle_only_render = (
            isinstance(manual_editor_meta, dict)
            and str(manual_editor_meta.get("change_scope") or "") == "subtitle_only"
            and str(manual_editor_meta.get("render_strategy") or "") == "reuse_timeline_effect_plan"
        )

        content_profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        # Get subtitle payloads
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )

        stale_render_outputs_result = await session.execute(
            select(RenderOutput).where(RenderOutput.job_id == job.id, RenderOutput.status == "running")
        )
        for stale_render_output in stale_render_outputs_result.scalars().all():
            stale_render_output.status = "failed"

        reusable_render_outputs: dict[str, Any] | None = None
        if manual_subtitle_only_render:
            reusable_artifact_result = await session.execute(
                select(Artifact)
                .where(Artifact.job_id == job.id, Artifact.artifact_type == "render_outputs")
                .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            )
            for artifact in reusable_artifact_result.scalars().all():
                if isinstance(artifact.data_json, dict) and artifact.data_json.get("plain_mp4"):
                    reusable_render_outputs = dict(artifact.data_json)
                    break

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

        async def _refresh_render_progress(*, detail: str, progress: float) -> asyncio.Task[None] | None:
            nonlocal render_heartbeat
            if render_heartbeat is not None:
                render_heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await render_heartbeat
            async with get_session_factory()() as progress_session:
                step_result = await progress_session.execute(
                    select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
                )
                render_step = step_result.scalar_one_or_none()
                if render_step:
                    await _set_step_progress(progress_session, render_step, detail=detail, progress=progress)
                render_output_ref = await progress_session.get(RenderOutput, render_output_id)
                if render_output_ref:
                    render_output_ref.progress = progress
                    await progress_session.commit()
                render_heartbeat = _spawn_step_heartbeat(
                    step_id=render_step.id if render_step else None,
                    detail=detail,
                    progress=progress,
                )
            return render_heartbeat

        try:
            render_heartbeat = await _refresh_render_progress(
                detail=(
                    "先渲染素版，再生成包装版"
                    if (has_packaging or has_editing_accents)
                    else "执行 FFmpeg 渲染成片"
                ),
                progress=0.35,
            )
            tmp_plain_mp4 = Path(tmpdir) / "output_plain.mp4"
            tmp_avatar_mp4 = Path(tmpdir) / "output_avatar.mp4"
            tmp_ai_effect_mp4 = Path(tmpdir) / "output_ai_effect.mp4"
            tmp_packaged_mp4 = Path(tmpdir) / "output_packaged.mp4"
            tmp_cover_plain_mp4 = Path(tmpdir) / "output_cover_plain.mp4"
            reusable_plain_path = (
                Path(str(reusable_render_outputs.get("plain_mp4"))).expanduser()
                if reusable_render_outputs
                else None
            )
            if reusable_plain_path is not None and reusable_plain_path.exists():
                await _refresh_render_progress(
                    detail="字幕微调：复用既有素版底片，跳过原片重切",
                    progress=0.22,
                )
                await _copy_file_with_retry(reusable_plain_path, tmp_plain_mp4)
            else:
                source_path = await _resolve_source(
                    job,
                    tmpdir,
                    expected_hash=job.file_hash,
                    debug_dir=debug_dir,
                )
                plain_render_plan = build_plain_render_plan(render_plan_timeline.data_json)
                await render_video(
                    source_path=source_path,
                    render_plan=plain_render_plan,
                    editorial_timeline=editorial_timeline.data_json,
                    output_path=tmp_plain_mp4,
                    subtitle_items=None,
                    debug_dir=debug_dir / "plain",
                )
            await _copy_file_with_retry(tmp_plain_mp4, tmp_cover_plain_mp4)
            plain_duration = float((await _probe_with_retry(tmp_plain_mp4)).duration or 0.0)
            plain_variant_editorial_timeline = _build_full_length_variant_timeline(plain_duration)
            keep_segments = [
                s for s in editorial_timeline.data_json.get("segments", [])
                if s.get("type") == "keep"
            ]
            async with get_session_factory()() as projection_session:
                remapped_subtitles = await _build_edited_subtitle_projection(
                    projection_session,
                    job_id=uuid.UUID(job_id),
                    keep_segments=keep_segments,
                    projection_data=projection_data,
                    fallback_subtitles=subtitle_dicts,
                )
            manual_editor_subtitles = _manual_editor_subtitle_items_from_editorial(editorial_timeline.data_json)
            if manual_editor_subtitles:
                remapped_subtitles = manual_editor_subtitles
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
            if (
                "avatar_commentary" in set(getattr(job, "enhancement_modes", []) or [])
                and str(avatar_plan.get("mode") or "") == "segmented_audio_passthrough"
            ):
                avatar_plan["segments"] = await _materialize_avatar_plan_segments(
                    str(job.id),
                    list(avatar_plan.get("segments") or []),
                )
            avatar_result: dict[str, Any] | None = None
            avatar_variant_source_path: Path | None = None
            avatar_variant_duration_sec: float | None = None
            avatar_variant_editorial_timeline: dict[str, Any] | None = None
            avatar_overlay_accents: dict[str, Any] | None = None
            reusable_avatar_path = (
                Path(str(reusable_render_outputs.get("avatar_mp4"))).expanduser()
                if reusable_render_outputs and reusable_render_outputs.get("avatar_mp4")
                else None
            )
            if manual_subtitle_only_render and reusable_avatar_path is not None and reusable_avatar_path.exists():
                avatar_duration = float((await probe(reusable_avatar_path)).duration or 0.0)
                avatar_variant_source_path = reusable_avatar_path
                avatar_variant_duration_sec = avatar_duration
                avatar_variant_editorial_timeline = _build_full_length_variant_timeline(avatar_duration)
                tmp_avatar_mp4 = reusable_avatar_path
                avatar_result = {
                    "enabled": True,
                    "status": "reused",
                    "mode": str(avatar_plan.get("mode") or ""),
                    "integration_mode": str(avatar_plan.get("integration_mode") or ""),
                    "provider": str(avatar_plan.get("provider") or ""),
                    "output_path": str(reusable_avatar_path),
                    "detail": "字幕微调复用既有数字人画中画底片。",
                }
            if (
                avatar_variant_source_path is None
                and
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
                    render_heartbeat = await _refresh_render_progress(
                        detail="素版已完成，等待数字人口播全轨插槽",
                        progress=0.42,
                    )
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
                        avatar_variant_source_path = pip_output_path
                        avatar_variant_duration_sec = pip_duration
                        avatar_variant_editorial_timeline = _build_full_length_variant_timeline(pip_duration)
                        tmp_avatar_mp4 = avatar_variant_source_path
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
                avatar_variant_source_path is None
                and
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
                        avatar_variant_source_path = pip_output_path
                        avatar_variant_duration_sec = pip_duration
                        avatar_variant_editorial_timeline = _build_full_length_variant_timeline(pip_duration)
                        tmp_avatar_mp4 = avatar_variant_source_path
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
            packaging_heartbeat = await _refresh_render_progress(
                detail="素版已完成，开始生成包装版",
                progress=0.55,
            )
            packaged_source_path, packaged_editorial_timeline, packaged_subtitles = _resolve_packaged_render_variant(
                original_source_path=tmp_plain_mp4,
                original_editorial_timeline=plain_variant_editorial_timeline,
                original_subtitle_items=packaged_subtitles,
                variant_source_path=avatar_variant_source_path,
                variant_duration_sec=avatar_variant_duration_sec,
                variant_subtitle_items=packaged_subtitles,
            )
            ai_effect_source_path, ai_effect_editorial_timeline, ai_effect_subtitles = _resolve_packaged_render_variant(
                original_source_path=tmp_plain_mp4,
                original_editorial_timeline=plain_variant_editorial_timeline,
                original_subtitle_items=packaged_subtitles,
                variant_source_path=avatar_variant_source_path,
                variant_duration_sec=avatar_variant_duration_sec,
                variant_subtitle_items=packaged_subtitles,
            )
            if avatar_variant_source_path is not None and avatar_variant_duration_sec is not None:
                ai_effect_render_plan["avatar_commentary"] = copy.deepcopy(avatar_plan)
            await render_video(
                source_path=ai_effect_source_path,
                render_plan=ai_effect_render_plan,
                editorial_timeline=ai_effect_editorial_timeline,
                output_path=tmp_ai_effect_mp4,
                subtitle_items=ai_effect_subtitles,
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
            plain_meta = await _probe_with_retry(tmp_plain_mp4)
            packaged_meta = await _probe_with_retry(tmp_packaged_mp4)
            ai_effect_meta = await _probe_with_retry(tmp_ai_effect_mp4)
            avatar_meta = await _probe_with_retry(tmp_avatar_mp4) if tmp_avatar_mp4.exists() else None

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

            await _copy_file_with_retry(tmp_plain_mp4, local_plain_mp4)
            if tmp_avatar_mp4.exists() and local_avatar_mp4 is not None:
                await _copy_file_with_retry(tmp_avatar_mp4, local_avatar_mp4)
            await _copy_file_with_retry(tmp_ai_effect_mp4, local_ai_effect_mp4)
            await _copy_file_with_retry(tmp_packaged_mp4, local_packaged_mp4)
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
            write_srt_file(ai_effect_subtitles, local_ai_effect_srt)
            plain_subtitle_sync = _compute_subtitle_sync_check(local_plain_mp4, local_plain_srt)
            packaged_trailing_allowance = _variant_expected_trailing_gap(
                base_sync_check=plain_subtitle_sync,
                packaging_allowance_sec=await _resolve_packaging_trailing_gap_allowance(render_plan_timeline.data_json),
            )
            ai_effect_trailing_allowance = _variant_expected_trailing_gap(
                base_sync_check=plain_subtitle_sync,
                packaging_allowance_sec=await _resolve_packaging_trailing_gap_allowance(ai_effect_render_plan),
            )
            packaged_subtitle_sync = _compute_subtitle_sync_check(
                local_packaged_mp4,
                local_packaged_srt,
                allowed_trailing_gap_sec=packaged_trailing_allowance,
            )
            avatar_subtitle_sync = (
                _compute_subtitle_sync_check(local_avatar_mp4, local_avatar_srt)
                if local_avatar_mp4 is not None and local_avatar_srt is not None and tmp_avatar_mp4.exists()
                else None
            )
            ai_effect_subtitle_sync = _compute_subtitle_sync_check(
                local_ai_effect_mp4,
                local_ai_effect_srt,
                allowed_trailing_gap_sec=ai_effect_trailing_allowance,
            )
            blocking_sync_issues = _collect_blocking_variant_sync_issues(
                {
                    "packaged": packaged_subtitle_sync,
                    "plain": plain_subtitle_sync,
                    "avatar": avatar_subtitle_sync,
                    "ai_effect": ai_effect_subtitle_sync,
                }
            )
            if blocking_sync_issues:
                raise RuntimeError(
                    "render_variant_sync_blocked: "
                    + "; ".join(blocking_sync_issues)
                )

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
                logger.exception("Cover export failed for job %s", job_id)
                local_cover = None  # Cover is non-critical
                cover_variants = []
                cover_selection = None
        except Exception:
            async with get_session_factory()() as failure_session:
                render_output = await failure_session.get(RenderOutput, render_output_id)
                if render_output is not None:
                    render_output.status = "failed"
                    await failure_session.commit()
            raise
        finally:
            if render_heartbeat is not None:
                render_heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await render_heartbeat

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
                subtitle_events=ai_effect_subtitles,
                transition_offsets=ai_effect_transition_offsets,
                segments=ai_effect_editorial_timeline.get("segments") or [],
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

    return {"output_path": str(local_packaged_mp4), "local": local_paths}


async def run_platform_package(job_id: str) -> dict:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, uuid.UUID(job_id))
        settings = get_settings()
        if not job:
            raise ValueError(f"Job {job_id} not found")

        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == "platform_package")
        )
        step = step_result.scalar_one_or_none()
        await _set_step_progress(session, step, detail="整理成片信息并生成平台文案", progress=0.2)

        content_profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)

        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
        editorial_timeline = await _load_latest_timeline(session, job.id, "editorial")
        manual_editor_subtitles = _manual_editor_subtitle_items_from_editorial(editorial_timeline.data_json if editorial_timeline else None)
        if manual_editor_subtitles:
            subtitle_dicts = manual_editor_subtitles

        render_output_result = await session.execute(
            select(RenderOutput)
            .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
            .order_by(RenderOutput.created_at.desc())
        )
        render_output = render_output_result.scalars().first()
        renderless_mode = not bool(render_output and render_output.output_path)

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
            fact_search_enabled = should_enable_task_search(
                "copy_verify",
                default_enabled=True,
                profile=content_profile,
                settings=settings,
            )
            with llm_task_route("copy_verify", search_enabled=fact_search_enabled, settings=settings):
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
        fact_search_enabled = should_enable_task_search(
            "copy_verify",
            default_enabled=True,
            profile=content_profile,
            settings=settings,
        )
        with llm_task_route("copy_verify", search_enabled=fact_search_enabled, settings=settings):
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
        copy_search_enabled = should_enable_task_search(
            "copy",
            default_enabled=True,
            profile=content_profile,
            settings=settings,
        )
        with llm_task_route("copy", search_enabled=copy_search_enabled, settings=settings):
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

    if renderless_mode:
        project_dir = get_output_project_dir(
            job.source_name,
            job.created_at,
            content_profile=content_profile,
            output_dir=job.output_dir,
        )
        output_md = project_dir / "platform_packaging_renderless.md"
    else:
        output_mp4 = Path(render_output.output_path)
        output_md = output_mp4.with_name(f"{output_mp4.stem}_publish.md")
    if isinstance(packaging, dict):
        packaging["generation_mode"] = "renderless_copy_only" if renderless_mode else "rendered_video"
        if renderless_mode:
            packaging["generation_note"] = "No finished render output was available; packaging was generated from content profile and subtitles only."
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


async def _copy_file_with_retry(
    source_path: Path,
    dest_path: Path,
    *,
    attempts: int = 6,
    retry_delay_sec: float = 0.25,
) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            shutil.copy2(source_path, dest_path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            await asyncio.sleep(retry_delay_sec * attempt)
    if last_error is not None:
        raise last_error


async def _probe_with_retry(
    path: Path,
    *,
    attempts: int = 6,
    retry_delay_sec: float = 0.25,
):
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await probe(path)
        except PermissionError as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            await asyncio.sleep(retry_delay_sec * attempt)
    if last_error is not None:
        raise last_error
    return await probe(path)


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


def _normalize_packaged_subtitle_copy_signature(text: str) -> str:
    normalized = normalize_display_text(str(text or ""))
    normalized = re.sub(r"\s+", "", normalized)
    normalized = normalized.rstrip("。！？!?；;，,：:")
    return normalized


def _packaged_subtitle_copy_rewrite_is_material(original_text: str, rewritten_text: str) -> bool:
    original_signature = _normalize_packaged_subtitle_copy_signature(original_text)
    rewritten_signature = _normalize_packaged_subtitle_copy_signature(rewritten_text)
    if not original_signature or not rewritten_signature:
        return False
    return original_signature != rewritten_signature


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
        if rewritten_text and _packaged_subtitle_copy_rewrite_is_material(original_text, rewritten_text):
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
    if not _packaged_subtitle_copy_rewrite_is_material(original_text, primary_text):
        return [primary_text]
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
    workflow_template = str((content_profile or {}).get("workflow_template") or "").strip()
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


def _build_full_length_variant_timeline(duration_sec: float) -> dict[str, Any]:
    duration = max(0.0, float(duration_sec or 0.0))
    if duration <= 0.0:
        raise ValueError("variant duration must be positive")
    return {
        "segments": [
            {
                "type": "keep",
                "start": 0.0,
                "end": duration,
            }
        ]
    }


async def _resolve_packaging_trailing_gap_allowance(render_plan: dict[str, Any] | None) -> float:
    plan = render_plan or {}
    outro_plan = plan.get("outro") if isinstance(plan, dict) else None
    outro_path = str((outro_plan or {}).get("path") or "").strip()
    if not outro_path:
        return 0.0
    try:
        return max(0.0, float((await probe(Path(outro_path))).duration or 0.0))
    except Exception:
        return 0.0


def _variant_sync_is_blocking(sync_check: dict[str, Any] | None) -> bool:
    if not isinstance(sync_check, dict):
        return False
    warning_codes = {str(code) for code in sync_check.get("warning_codes") or []}
    if warning_codes.intersection(
        {
            "audio_video_duration_gap_large",
            "subtitle_out_of_bounds",
            "subtitle_timestamp_disorder",
            "subtitle_overlap_detected",
            "subtitle_invalid_range",
            "subtitle_trailing_gap_large",
            "subtitle_duration_gap_large",
        }
    ):
        return True
    video_duration = float(sync_check.get("video_duration_sec", 0.0) or 0.0)
    effective_trailing_gap = float(
        sync_check.get("effective_trailing_gap_sec", sync_check.get("trailing_gap_sec", 0.0)) or 0.0
    )
    effective_duration_gap = float(
        sync_check.get("effective_duration_gap_sec", sync_check.get("duration_gap_sec", 0.0)) or 0.0
    )
    trailing_threshold = max(2.0, video_duration * 0.12) if video_duration > 0 else 2.0
    duration_threshold = max(2.5, video_duration * 0.15) if video_duration > 0 else 2.5
    return effective_trailing_gap > trailing_threshold or effective_duration_gap > duration_threshold


def _variant_expected_trailing_gap(
    *,
    base_sync_check: dict[str, Any] | None,
    packaging_allowance_sec: float = 0.0,
) -> float:
    base_gap = 0.0
    if isinstance(base_sync_check, dict):
        base_gap = float(base_sync_check.get("trailing_gap_sec", 0.0) or 0.0)
    return max(0.0, base_gap + max(0.0, float(packaging_allowance_sec or 0.0)))


def _collect_blocking_variant_sync_issues(sync_checks: dict[str, dict[str, Any] | None]) -> list[str]:
    issues: list[str] = []
    for variant_name, sync_check in sync_checks.items():
        if not _variant_sync_is_blocking(sync_check):
            continue
        warning_codes = ", ".join(str(code) for code in sync_check.get("warning_codes") or [])
        if not warning_codes and isinstance(sync_check, dict):
            trailing_gap = float(
                sync_check.get("effective_trailing_gap_sec", sync_check.get("trailing_gap_sec", 0.0)) or 0.0
            )
            duration_gap = float(
                sync_check.get("effective_duration_gap_sec", sync_check.get("duration_gap_sec", 0.0)) or 0.0
            )
            warning_codes = f"effective_trailing_gap={trailing_gap:.3f}s,effective_duration_gap={duration_gap:.3f}s"
        if not warning_codes:
            warning_codes = "unknown"
        issues.append(f"{variant_name}: {warning_codes}")
    return issues


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
    render_execution = await _execute_avatar_full_track_render_request(
        job_id=job_id,
        render_request=render_request,
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


_AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS = (5.0, 10.0, 20.0, 30.0)
_AVATAR_FULL_TRACK_SLOT_KEY = "avatar_full_track"
_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SEC = 7200
_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS = 900.0


@asynccontextmanager
async def _hold_avatar_full_track_slot(*, job_id: str):
    logger.info("Waiting for avatar full-track slot job=%s", job_id)
    acquired, token = await asyncio.to_thread(
        _acquire_operation_lock,
        _AVATAR_FULL_TRACK_SLOT_KEY,
        timeout_sec=_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SEC,
    )
    if not acquired:
        raise RuntimeError("avatar_full_track_slot_timeout")
    logger.info("Avatar full-track slot acquired job=%s", job_id)
    try:
        yield
    finally:
        await asyncio.to_thread(_release_operation_lock, _AVATAR_FULL_TRACK_SLOT_KEY, token)
        logger.info("Avatar full-track slot released job=%s", job_id)


def _is_avatar_service_busy_message(message: object) -> bool:
    normalized = str(message or "").strip().lower()
    if not normalized:
        return False
    busy_tokens = (
        "busy",
        "resource busy",
        "device busy",
        "service unavailable",
        "temporarily unavailable",
        "all connection attempts failed",
        "忙碌",
        "繁忙",
        "请稍后",
        "稍后重试",
    )
    return any(token in normalized for token in busy_tokens)


async def _execute_avatar_full_track_render_request(
    *,
    job_id: str,
    render_request: dict[str, Any],
) -> dict[str, Any]:
    async with _hold_avatar_full_track_slot(job_id=job_id):
        last_error: Exception | None = None
        attempt = 0
        busy_waited_seconds = 0.0
        while True:
            try:
                render_execution = await asyncio.to_thread(
                    get_avatar_provider().execute_render,
                    job_id=job_id,
                    request=render_request,
                )
            except Exception as exc:
                last_error = exc
                if _is_avatar_service_busy_message(exc):
                    delay = _AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS[
                        min(attempt, len(_AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS) - 1)
                    ]
                    if busy_waited_seconds + delay > _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS:
                        raise
                    attempt += 1
                    busy_waited_seconds += delay
                    logger.warning(
                        "Avatar full-track render retrying after busy response job=%s attempt=%s waited=%.1fs/%.1fs delay=%.1fs",
                        job_id,
                        attempt + 1,
                        busy_waited_seconds,
                        _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            segments = list(render_execution.get("segments") or [])
            if not segments:
                return render_execution
            first_segment = segments[0] or {}
            if str(first_segment.get("status") or "") == "success":
                return render_execution
            error_text = str(first_segment.get("error") or render_execution.get("error") or "avatar_full_track_render_failed")
            if _is_avatar_service_busy_message(error_text):
                delay = _AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS[
                    min(attempt, len(_AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS) - 1)
                ]
                if busy_waited_seconds + delay > _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS:
                    raise RuntimeError(error_text)
                attempt += 1
                busy_waited_seconds += delay
                last_error = RuntimeError(error_text)
                logger.warning(
                    "Avatar full-track render retrying after busy response job=%s attempt=%s waited=%.1fs/%.1fs delay=%.1fs",
                    job_id,
                    attempt + 1,
                    busy_waited_seconds,
                    _AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise RuntimeError(error_text)
        if last_error is not None:
            raise last_error
        raise RuntimeError("avatar_full_track_render_failed")


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
        end_time = max(start_time, float(segment.get("end_time") or start_time))
        segment_duration = max(
            0.1,
            float(segment.get("duration_sec") or 0.0) or max(0.0, end_time - start_time),
        )
        if end_time <= start_time:
            end_time = start_time + segment_duration
        enable_expr = f"between(t,{start_time:.6f},{end_time:.6f})"
        avatar_filter = _build_rounded_rgba_filter(
            input_label=f"{index}:v",
            output_label=f"pipfg{index}",
            width=overlay_width,
            height=overlay_height,
            corner_radius=avatar_corner_radius,
            extra_filters=(
                f"trim=duration={segment_duration:.6f},"
                f"setpts=PTS-STARTPTS+{start_time:.6f}/TB,"
                f"scale={overlay_width}:{overlay_height}"
            ),
        )
        filter_parts.append(avatar_filter)
        if resolved_border_width > 0:
            filter_parts.append(
                _build_timed_rounded_color_filter(
                    output_label=f"pipbg{index}",
                    color=border_rgb,
                    width=frame_width,
                    height=frame_height,
                    corner_radius=resolved_corner_radius,
                    start_time=start_time,
                    duration=segment_duration,
                )
            )
            filter_parts.append(
                f"[pipbg{index}][pipfg{index}]overlay={resolved_border_width}:{resolved_border_width}:"
                f"eof_action=pass:repeatlast=0:format=auto:alpha=straight[pip{index}]"
            )
        else:
            filter_parts.append(f"[pipfg{index}]copy[pip{index}]")
        next_label = f"vseg{index}"
        filter_parts.append(
            f"[{current_label}][pip{index}]overlay=x={overlay_x}:y={overlay_y}:enable='{enable_expr}':"
            f"eof_action=pass:repeatlast=0:format=auto:alpha=straight[{next_label}]"
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


def _build_timed_rounded_color_filter(
    *,
    output_label: str,
    color: str,
    width: int,
    height: int,
    corner_radius: int,
    start_time: float,
    duration: float,
) -> str:
    duration_expr = max(0.1, float(duration or 0.0))
    filter_prefix = (
        f"color=c={color}:s={width}x{height}:d={duration_expr:.6f},"
        f"setpts=PTS-STARTPTS+{max(0.0, float(start_time or 0.0)):.6f}/TB"
    )
    if corner_radius <= 0:
        return f"{filter_prefix},format=rgba[{output_label}]"
    alpha_expr = _build_rounded_alpha_expr(width=width, height=height, corner_radius=corner_radius)
    return (
        f"{filter_prefix},format=yuva444p,"
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
            "evidence": _compact_cut_evidence_payload(item.get("evidence")),
        }
        for item in accepted_cuts
        if float(item.get("boundary_keep_energy", 0.0) or 0.0) >= 1.0
    ]
    raw_llm_cut_review = (editorial_analysis or {}).get("llm_cut_review")
    llm_cut_review = (
        {
            "reviewed": bool(raw_llm_cut_review.get("reviewed")),
            "candidate_count": int(raw_llm_cut_review.get("candidate_count") or 0),
            "decision_count": int(raw_llm_cut_review.get("decision_count") or 0),
            "restored_cut_count": int(raw_llm_cut_review.get("restored_cut_count") or 0),
            "cached": bool(raw_llm_cut_review.get("cached")),
            "provider": str(raw_llm_cut_review.get("provider") or ""),
            "model": str(raw_llm_cut_review.get("model") or ""),
            "summary": str(raw_llm_cut_review.get("summary") or ""),
            "error": str(raw_llm_cut_review.get("error") or ""),
            "timeout": bool(raw_llm_cut_review.get("timeout")),
        }
        if isinstance(raw_llm_cut_review, dict)
        else {}
    )
    review_reasons: list[str] = []
    if high_risk_cuts:
        review_reasons.append("存在贴近高能量保留段的 cut，建议复核边界。")
    if any(
        float(((item.get("evidence") or {}).get("protection_score") or 0.0)) >= 0.72
        for item in high_risk_cuts
        if isinstance(item.get("evidence"), dict)
    ):
        review_reasons.append("部分 cut 带有展示、语言或语义保护证据，建议重点核对是否误删。")
    if any(str(item.get("section_role") or "") == "hook" for item in high_energy_keeps):
        review_reasons.append("Hook 段存在高能量保留片段，建议确认开场节奏。")
    return {
        "keep_energy_summary": _clone_json_like((editorial_analysis or {}).get("keep_energy_summary") or {}),
        "cut_evidence_summary": _clone_json_like((editorial_analysis or {}).get("cut_evidence_summary") or {}),
        "high_energy_keeps": high_energy_keeps[:8],
        "high_risk_cuts": high_risk_cuts[:8],
        "llm_cut_review": llm_cut_review,
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


def _compact_cut_evidence_payload(value: Any) -> dict[str, Any]:
    evidence = value if isinstance(value, dict) else {}
    if not evidence:
        return {}
    return {
        "visual_showcase_score": round(float(evidence.get("visual_showcase_score", 0.0) or 0.0), 3),
        "language_score": round(float(evidence.get("language_score", 0.0) or 0.0), 3),
        "retake_score": round(float(evidence.get("retake_score", 0.0) or 0.0), 3),
        "protection_score": round(float(evidence.get("protection_score", 0.0) or 0.0), 3),
        "removal_score": round(float(evidence.get("removal_score", 0.0) or 0.0), 3),
        "tags": [str(tag) for tag in (evidence.get("tags") or []) if str(tag)][:6],
        "previous_text": str(evidence.get("previous_text") or "")[:40],
        "next_text": str(evidence.get("next_text") or "")[:40],
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
        "subtitle_events": [
            event
            for item in (subtitle_events or [])
            if (event := _normalize_subtitle_event(item)) is not None
        ],
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


def _normalize_subtitle_event(item: dict[str, Any]) -> dict[str, Any] | None:
    start_time = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
    end_time = float(item.get("end_time", item.get("end", start_time)) or start_time)
    text = clean_final_subtitle_text(
        item.get("text_final")
        or item.get("text_norm")
        or item.get("text_raw")
        or item.get("text")
        or ""
    )
    if not text:
        return None
    return {
        "index": int(item.get("index", 0) or 0),
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "text": text,
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
            llm_cut_review = diagnostics.get("llm_cut_review")
            if llm_cut_review is not None and not isinstance(llm_cut_review, dict):
                issues.append("diagnostics: llm_cut_review is not a dict")
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
        capability = normalize_avatar_capability_status(profile.get("capability_status") or {})
        score = 0
        if str(capability.get("preview") or "") == "ready":
            score += 2
        if str(capability.get(AVATAR_CAPABILITY_GENERATION) or "") == "ready":
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
    "subtitle_term_resolution": run_subtitle_term_resolution,
    "subtitle_consistency_review": run_subtitle_consistency_review,
    "transcript_review": run_transcript_review,
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
