"""
Business logic for each pipeline step.
Each function takes job_id + step info and does the actual work.
These are called by Celery tasks (which handle the async→sync bridge).
"""
from __future__ import annotations

import copy
import asyncio
import hashlib
import httpx
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from statistics import median
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import NullPool

from roughcut.avatar import list_avatar_material_profiles, resolve_avatar_material_path
from roughcut.config import get_settings, llm_task_route, normalize_transcription_settings, should_enable_task_search
from roughcut.creator_asset_runtime import (
    normalize_creator_asset_category,
    pick_creator_avatar_presenter_asset,
    resolve_creator_asset_path,
)
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
from roughcut.db.models import (
    Artifact,
    CreatorCard,
    CreatorPreference,
    GlossaryTerm,
    Job,
    JobStep,
    RenderOutput,
    SubtitleCorrection,
    SubtitleItem,
    Timeline,
    TranscriptSegment,
)
from roughcut.db.session import get_session_factory, reset_session_state, reset_session_state_sync
from roughcut.edit.decisions import (
    EditDecision,
    EditSegment,
    _build_keep_energy_segments_analysis,
    _summarize_keep_energy_segments,
    build_edit_decision,
    infer_timeline_analysis,
    refresh_source_timeline_contract_analysis,
)
from roughcut.edit.cut_analysis import (
    ARTIFACT_TYPE_CUT_ANALYSIS,
    build_cut_analysis_payload,
    cut_analysis_accepted_cuts,
    cut_analysis_effective_applied_cuts,
    cut_analysis_rule_candidates,
    summarize_cut_analysis_candidate_metrics,
)
from roughcut.edit.editorial_timeline import (
    editorial_timeline_analysis,
    editorial_timeline_segments,
    editorial_timeline_subtitle_projection,
    resolve_refine_keep_segments_for_timeline,
)
from roughcut.edit.local_audio_cues import plan_local_music_entry, score_local_music_entry_candidates
from roughcut.edit.local_focus_plan import build_local_focus_plan
from roughcut.edit.local_insert_plan import plan_local_insert_slot
from roughcut.edit.otio_export import export_to_otio
from roughcut.edit.packaging_timeline import (
    build_packaging_timeline_payload,
    packaging_timeline_asset_plan,
    packaging_timeline_analysis,
    packaging_timeline_editing_skill,
    packaging_timeline_focus_plan,
    packaging_timeline_insert_plan,
    packaging_timeline_local_audio_cues,
    packaging_timeline_music_plan,
    packaging_timeline_section_choreography,
    packaging_timeline_subtitles,
    packaging_timeline_transitions,
    resolve_packaging_timeline_payload,
)
from roughcut.edit.presets import normalize_workflow_template_name
from roughcut.edit.refine_decisions import (
    ARTIFACT_TYPE_REFINE_DECISION_PLAN,
    build_refine_decision_plan_from_render_plan,
)
from roughcut.edit.multimodal_trim_review import (
    ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,
    apply_multimodal_trim_review_to_cut_analysis,
    build_multimodal_trim_review_payload,
    review_multimodal_trim_review_payload,
)
from roughcut.edit.manual_editor_contract import manual_editor_is_subtitle_only_render
from roughcut.edit.smart_cut_rules import (
    default_smart_cut_rules_payload,
    normalize_smart_cut_rules_payload,
)
from roughcut.edit.render_plan import (
    build_ai_effect_render_plan,
    build_plain_render_plan,
    build_render_plan,
    build_smart_editing_accents,
    render_plan_automatic_gate,
    render_plan_avatar_commentary,
    render_plan_delivery,
    render_plan_loudness,
    render_plan_manual_editor,
    render_plan_strategy_review_context,
    render_plan_video_transform,
    render_plan_voice_processing,
    save_render_plan,
)
from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill
from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_explicit_text,
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_explicit_text,
    subtitle_raw_rule_text,
    subtitle_semantic_item_text,
    subtitle_surface_item_dict,
)
from roughcut.edit.timeline import save_editorial_timeline
from roughcut.media.audio import NoAudioStreamError, extract_audio, extract_audio_clip
from roughcut.media.output import (
    build_variant_output_path,
    get_output_project_dir,
    write_srt_file,
)
from roughcut.media.manual_editor_assets import (
    ensure_manual_editor_preview_assets,
    mark_manual_editor_preview_assets_queued,
)
from roughcut.media.scene import detect_scenes
from roughcut.media.subtitle_spans import drop_redundant_synthetic_word_payloads, sanitize_transcript_segment_word_rows
from roughcut.media.subtitle_text import (
    clean_final_subtitle_text,
    clean_subtitle_payloads,
    normalize_contextual_noc_alias_text,
    normalize_contextual_unboxing_sale_text,
    normalize_flashlight_model_alias_text,
    preserve_subtitle_payloads,
)
from roughcut.media.subtitle_fingerprint import subtitle_payload_fingerprint
from roughcut.media.subtitle_projection_validation import (
    validate_projected_subtitles_against_source,
    validate_projected_subtitles_against_transcript,
)
from roughcut.media.subtitles import remap_subtitles_to_timeline
from roughcut.media.probe import probe, validate_media
from roughcut.media.render import burn_subtitles_on_rendered_video, render_video
from roughcut.media.silence import detect_silence
from roughcut.llm_cache import (
    build_cache_key,
    build_cache_metadata,
    digest_payload,
    get_cache_path,
    load_cached_entry,
    save_cached_json,
)
from roughcut.naming import AVATAR_CAPABILITY_GENERATION, normalize_avatar_capability_status
from roughcut.production_readiness import (
    insert_plan_output_fallback_reasons,
    projection_output_fallback_reasons,
    render_output_blocking_reasons,
    strategy_render_validation_summary,
)
from roughcut.packaging.library import (
    list_packaging_assets,
    resolve_insert_added_duration,
    resolve_insert_effective_duration,
    resolve_insert_transition_overlap,
    resolve_packaging_plan_for_job,
)
from roughcut.edit.rule_registry import rule_requires_llm_review
from roughcut.prompts.edit_decision import build_high_risk_cut_review_prompt, build_waste_segment_discovery_prompt
from roughcut.providers.factory import get_avatar_provider, get_reasoning_provider, get_voice_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.providers.transcription.local_http_asr import LocalHTTPASRProvider
from roughcut.providers.zhipu_compat import resolve_zhipu_reasoning_base_url
from roughcut.providers.zhipu_http import provider_cooldown_remaining_seconds_for_url, zhipu_response_diagnostics
from roughcut.providers.transcription.base import TranscriptResult
from roughcut.providers.transcription.chunking import (
    build_audio_chunk_specs,
    probe_audio_duration,
    resolve_audio_chunk_config,
    should_chunk_audio,
)
from roughcut.pipeline.quality import (
    _compute_subtitle_sync_check,
    _subtitle_timing_structure_diagnostics,
    evaluate_profile_identity_gate,
)
from roughcut.review.content_profile import (
    _resolve_content_understanding_timeout_seconds,
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
from roughcut.review.content_profile_artifacts import (
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS,
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
    ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
    ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
    persist_content_profile_artifacts,
)
from roughcut.review.content_profile_strategy import attach_content_profile_capability_orchestration
from roughcut.review.downstream_context import (
    attach_strategy_review_context,
    build_downstream_context,
    resolve_downstream_profile,
    select_strategy_review_artifact_context,
    strip_publication_only_profile_fields,
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
from roughcut.review.evidence_types import build_correction_framework_trace
from roughcut.review.subtitle_memory import build_subtitle_review_memory, build_transcription_prompt, resolve_transcription_category_scope
from roughcut.review.transcription_context_prior import infer_transcription_context_prior
from roughcut.review.subtitle_consistency import (
    ARTIFACT_TYPE_SUBTITLE_CONSISTENCY_REPORT,
    build_subtitle_consistency_report,
)
from roughcut.review.subtitle_quality import (
    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
    apply_subtitle_alignment_quality_guard,
    build_subtitle_alignment_source_metrics,
    build_subtitle_quality_report,
    build_subtitle_quality_report_from_items,
    subtitle_alignment_source_metrics_has_missing_word_alignment,
    subtitle_items_have_output_fallback_alignment,
    subtitle_quality_report_has_missing_word_alignment,
    subtitle_quality_report_has_output_fallback,
)
from roughcut.review.subtitle_term_resolution import (
    ARTIFACT_TYPE_SUBTITLE_TERM_RESOLUTION_PATCH,
    build_subtitle_term_resolution_patch,
)
from roughcut.review.topic_fact_confirmation import (
    topic_fact_confirmation_present,
    topic_fact_is_confirmed,
)
from roughcut.review.subtitle_translation import (
    detect_subtitle_language,
    languages_equivalent,
    resolve_translation_target_language,
    translate_subtitle_items,
)
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.review.telegram_bot import get_telegram_review_bot_service
from roughcut.remix.alignment import audit_subtitle_timing_alignment, normalize_eval_text
from roughcut.remix.contracts import AsrToken, SubtitleTiming
from roughcut.speech.postprocess import (
    SubtitleEntry,
    _fragment_window_candidate_is_acceptable,
    _rebalance_semantic_boundaries,
    _reindex_subtitle_entries,
    analyze_subtitle_segmentation,
    generate_subtitle_window_candidates,
    normalize_display_text,
    normalize_projection_display_text,
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
    build_canonical_transcript_layer_from_transcript_segments,
    build_subtitle_architecture_artifacts,
    build_subtitle_projection_layer,
    build_transcript_fact_layer,
    canonical_transcript_data_is_current,
    subtitle_projection_data_is_current,
)
from roughcut.speech.transcribe import (
    AsrQualityGateError,
    persist_asr_quality_gate_artifact,
    persist_empty_transcript_result,
    transcribe_audio,
)
from roughcut.storage.s3 import get_storage, job_key
from roughcut.telegram.review_notification_service import enqueue_review_notification
from roughcut.usage import track_step_usage, track_usage_operation

ARTIFACT_TYPE_TRANSCRIPT_CORRECTION_SCORE_REPORT = "transcript_correction_score_report"
ARTIFACT_TYPE_RENDER_RUNTIME_DIAGNOSTICS = "render_runtime_diagnostics"
ARTIFACT_TYPE_STRATEGY_CUT_BOUNDARY_SAMPLES = "strategy_cut_boundary_samples"
ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT = "render_subtitle_asr_alignment"
_MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE = "manual_editor_draft"

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
    context_text = " ".join(
        str(value or "")
        for value in (
            getattr(job, "source_name", ""),
            (content_profile or {}).get("subject_brand"),
            (content_profile or {}).get("subject_model"),
            (content_profile or {}).get("subject_type"),
            (content_profile or {}).get("video_theme"),
            (content_profile or {}).get("summary"),
            (content_profile or {}).get("hook_line"),
        )
    )
    changed = 0
    for item in subtitle_items:
        current = _subtitle_surface_display_text(item)
        normalized = normalize_contextual_noc_alias_text(current, context_text=context_text)
        normalized = normalize_contextual_unboxing_sale_text(normalized, context_text=context_text)
        if normalized == current:
            continue
        if hasattr(item, "text_norm"):
            item.text_norm = normalized
        if hasattr(item, "text_final"):
            item.text_final = normalized
        changed += 1
    return changed


def _subtitle_surface_payload(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    return {
        "transcript_text_raw": getattr(item, "transcript_text_raw", None),
        "raw_text": getattr(item, "raw_text", None),
        "text_raw": getattr(item, "text_raw", None),
        "timing_text": getattr(item, "timing_text", None),
        "transcript_text": getattr(item, "transcript_text", None),
        "text_canonical": getattr(item, "text_canonical", None),
        "text_norm": getattr(item, "text_norm", None),
        "text_final": getattr(item, "text_final", None),
        "display_text": getattr(item, "display_text", None),
        "display_source_text": getattr(item, "display_source_text", None),
        "projection_text": getattr(item, "projection_text", None),
        "text": getattr(item, "text", None),
        "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
    }


def _subtitle_surface_display_text(item: Any) -> str:
    return subtitle_display_rule_text(_subtitle_surface_payload(item))


def _subtitle_surface_canonical_text(item: Any) -> str:
    return subtitle_canonical_rule_text(_subtitle_surface_payload(item))


def _subtitle_surface_raw_text(item: Any) -> str:
    return subtitle_raw_rule_text(_subtitle_surface_payload(item))


def _transcript_segment_surface_payload(segment: Any) -> dict[str, Any]:
    if isinstance(segment, dict):
        return dict(segment)
    return {
        "id": getattr(segment, "id", None),
        "index": getattr(segment, "index", None),
        "segment_index": getattr(segment, "segment_index", None),
        "start": getattr(segment, "start", None),
        "end": getattr(segment, "end", None),
        "start_time": getattr(segment, "start_time", None),
        "end_time": getattr(segment, "end_time", None),
        "speaker": getattr(segment, "speaker", None),
        "text": getattr(segment, "text", None),
        "text_raw": getattr(segment, "text_raw", None),
        "text_norm": getattr(segment, "text_norm", None),
        "text_canonical": getattr(segment, "text_canonical", None),
        "text_final": getattr(segment, "text_final", None),
        "display_suppressed_reason": getattr(segment, "display_suppressed_reason", None),
        "words": getattr(segment, "words", None),
        "words_json": getattr(segment, "words_json", None),
    }


def _build_transcript_segment_adapter(segment: Any, *, index: int) -> SimpleNamespace:
    payload = _transcript_segment_surface_payload(segment)
    surfaces = subtitle_surface_item_dict(
        payload,
        generic_fallback_text=str(payload.get("text") or payload.get("text_raw") or ""),
    )
    words_json = payload.get("words_json", None) or payload.get("words", None) or []
    return SimpleNamespace(
        id=payload.get("id"),
        segment_index=int(payload.get("segment_index", payload.get("index", index)) or index),
        start_time=float(payload.get("start_time", payload.get("start", 0.0)) or 0.0),
        end_time=float(payload.get("end_time", payload.get("end", 0.0)) or 0.0),
        speaker=payload.get("speaker"),
        text=str(surfaces["text_raw"] or payload.get("text") or ""),
        text_raw=surfaces["text_raw"],
        text_norm=surfaces["text_norm"],
        text_canonical=surfaces["text_norm"],
        text_final=surfaces["text_final"],
        display_suppressed_reason=payload.get("display_suppressed_reason"),
        words_json=drop_redundant_synthetic_word_payloads(copy.deepcopy(list(words_json))),
    )


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
_DOWNSTREAM_PROFILE_ARTIFACT_TYPES = (
    "downstream_context",
    *_CONTENT_PROFILE_ARTIFACT_TYPES,
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
    ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
    ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
)
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
    "rollback_instruction": 0,
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
    raw = str(value or "").strip().lower()
    if raw in known_domains:
        return raw
    normalized = normalize_subject_domain(value)
    if not normalized:
        return None
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
    transcription_prior = (content_profile or {}).get("transcription_context_prior")
    if isinstance(transcription_prior, dict):
        try:
            prior_confidence = float(transcription_prior.get("confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            prior_confidence = 0.0
        if prior_confidence >= 0.55:
            prior_subject_domain = _supported_memory_subject_domain(transcription_prior.get("category_scope"))
            if not prior_subject_domain:
                prior_subject_domain = _supported_memory_subject_domain(transcription_prior.get("subject_domain"))
            if prior_subject_domain:
                return prior_subject_domain
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
    if rule_requires_llm_review(reason, risk_level=item.get("risk_level")):
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
                        "text": subtitle_display_rule_text(entry),
                    }
                    for entry in previous_subtitles
                ],
                "next_subtitles": [
                    {
                        "start_time": round(float(entry.get("start_time", 0.0) or 0.0), 3),
                        "end_time": round(float(entry.get("end_time", 0.0) or 0.0), 3),
                        "text": subtitle_display_rule_text(entry),
                    }
                    for entry in next_subtitles
                ],
                "transcript_context": [
                    {
                        "start": round(float(entry.get("start", 0.0) or 0.0), 3),
                        "end": round(float(entry.get("end", 0.0) or 0.0), 3),
                        "text": subtitle_canonical_rule_text(entry) or str(entry.get("text") or ""),
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
    timeout_budget = max(configured_timeout, scaled_timeout)
    active_provider = str(getattr(settings, "active_reasoning_provider", "") or "").strip().lower()
    if active_provider == "zhipu":
        timeout_budget = max(timeout_budget, 90.0)
        base_url = resolve_zhipu_reasoning_base_url(
            base_url=str(getattr(settings, "zhipu_base_url", "") or ""),
            coding_base_url=str(getattr(settings, "zhipu_coding_base_url", "") or ""),
            model=str(getattr(settings, "active_reasoning_model", "") or ""),
        )
        cooldown_budget = provider_cooldown_remaining_seconds_for_url(base_url)
        if cooldown_budget > 0.0:
            timeout_budget += cooldown_budget + 10.0
    return timeout_budget


_WASTE_SEGMENT_DISCOVERY_REASONS = {
    "failed_attempt",
    "restart_retake",
    "rollback_instruction",
    "off_topic_interruption",
    "long_non_dialogue",
}
_RESTART_RETAKE_EXPLICIT_CUE_RE = re.compile(
    r"(重来|重新来|再来一遍|重新说|重说|说错|讲错|不对|错了|前面不要|剪掉|删掉|回删|卡住|卡壳|口误)"
)
_RESTART_RETAKE_INFORMATION_MARKERS = (
    "配置",
    "参数",
    "功能",
    "模式",
    "区别",
    "对比",
    "结构",
    "机构",
    "模块",
    "设计",
    "教程",
    "指南",
    "操作",
    "拆装",
    "安装",
    "使用",
    "手感",
    "体验",
    "弹力",
    "声音",
    "降低",
    "提供",
    "可以",
    "能够",
    "因为",
    "所以",
    "建议",
    "推荐",
)
SEMANTIC_TIMELINE_ANALYSIS_STAGE = "semantic_timeline_analysis"
SEMANTIC_TIMELINE_ANALYSIS_SCHEMA_VERSION = "semantic_timeline_analysis.v1"


def _build_waste_segment_discovery_subtitle_context(
    subtitle_items: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    ordered = sorted(
        [dict(item) for item in subtitle_items if isinstance(item, dict)],
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", 0.0) or 0.0),
        ),
    )
    if max_items > 0:
        ordered = ordered[:max_items]
    return [
        {
            "index": int(item.get("index", item.get("item_index", index)) or index),
            "start": round(float(item.get("start_time", 0.0) or 0.0), 3),
            "end": round(float(item.get("end_time", item.get("start_time", 0.0)) or item.get("start_time", 0.0) or 0.0), 3),
            "text": subtitle_display_rule_text(item),
        }
        for index, item in enumerate(ordered)
    ]


def _build_waste_segment_discovery_subtitle_context_windows(
    subtitle_items: list[dict[str, Any]],
    *,
    max_items: int,
) -> list[list[dict[str, Any]]]:
    context = _build_waste_segment_discovery_subtitle_context(
        subtitle_items,
        max_items=0,
    )
    if not context:
        return []
    if max_items <= 0 or len(context) <= max_items:
        return [context]
    overlap = min(max(8, max_items // 10), max_items - 1)
    step = max(1, max_items - overlap)
    windows: list[list[dict[str, Any]]] = []
    start_index = 0
    while start_index < len(context):
        window = context[start_index : start_index + max_items]
        if window:
            windows.append(window)
        if start_index + max_items >= len(context):
            break
        start_index += step
    return windows


def _compact_waste_discovery_text(value: Any) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value or "").strip().lower())


def _waste_candidate_subtitle_text(
    subtitle_context: list[dict[str, Any]] | None,
    *,
    start: float,
    end: float,
) -> str:
    parts: list[str] = []
    for item in list(subtitle_context or []):
        if not isinstance(item, dict):
            continue
        try:
            item_start = float(item.get("start", item.get("start_time", 0.0)) or 0.0)
            item_end = float(item.get("end", item.get("end_time", item_start)) or item_start)
        except (TypeError, ValueError):
            continue
        if min(end, item_end) - max(start, item_start) <= 0.02:
            continue
        text = str(item.get("text") or item.get("text_final") or item.get("text_raw") or "").strip()
        if text:
            parts.append(text)
    return "".join(parts)


def _restart_retake_candidate_is_overbroad(
    raw: dict[str, Any],
    *,
    start: float,
    end: float,
    subtitle_context: list[dict[str, Any]] | None,
) -> bool:
    duration_sec = max(0.0, end - start)
    if duration_sec < 20.0 or not subtitle_context:
        return False
    candidate_text = _waste_candidate_subtitle_text(subtitle_context, start=start, end=end)
    compact_text = _compact_waste_discovery_text(candidate_text)
    if len(compact_text) < 80:
        return False
    summary = str(raw.get("summary") or "")
    evidence_text = " ".join(str(item or "") for item in list(raw.get("evidence") or []))
    cue_surface = f"{candidate_text} {summary} {evidence_text}"
    if _RESTART_RETAKE_EXPLICIT_CUE_RE.search(cue_surface):
        return False
    marker_count = sum(1 for marker in _RESTART_RETAKE_INFORMATION_MARKERS if marker in candidate_text)
    return marker_count >= 4


def _normalize_waste_segment_discovery_candidates(
    payload: dict[str, Any] | None,
    *,
    duration: float,
    min_confidence: float,
    max_candidates: int,
    subtitle_context: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()
    for raw in list(payload.get("candidates") or []):
        if not isinstance(raw, dict):
            continue
        reason = str(raw.get("reason") or "").strip()
        if reason not in _WASTE_SEGMENT_DISCOVERY_REASONS:
            continue
        try:
            start = max(0.0, min(float(duration or 0.0), float(raw.get("start", 0.0) or 0.0)))
            end = max(start, min(float(duration or 0.0), float(raw.get("end", start) or start)))
            confidence = max(0.0, min(1.0, float(raw.get("confidence", 0.0) or 0.0)))
        except (TypeError, ValueError):
            continue
        if end - start < 0.18 or confidence < min_confidence:
            continue
        if reason == "restart_retake" and _restart_retake_candidate_is_overbroad(
            raw,
            start=start,
            end=end,
            subtitle_context=subtitle_context,
        ):
            continue
        key = (reason, round(start, 3), round(end, 3))
        if key in seen:
            continue
        seen.add(key)
        evidence = [str(item).strip() for item in list(raw.get("evidence") or []) if str(item).strip()]
        summary = str(raw.get("summary") or "").strip()
        candidates.append(
            {
                "start": round(start, 4),
                "end": round(end, 4),
                "reason": reason,
                "risk_level": "high",
                "score": round(confidence, 4),
                "auto_applied": False,
                "candidate_stage": SEMANTIC_TIMELINE_ANALYSIS_STAGE,
                "semantic_role": "waste_candidate",
                "semantic_source": "llm_waste_segment_discovery",
                "source_text": summary or reason,
                "match_surface": summary or reason,
                "match_surface_layer": "raw",
                "multimodal_review_required": reason in {"failed_attempt", "off_topic_interruption", "long_non_dialogue"},
                "llm_discovery": {
                    "confidence": round(confidence, 3),
                    "summary": summary,
                    "evidence": evidence[:6],
                },
            }
        )
        if max_candidates > 0 and len(candidates) >= max_candidates:
            break
    return candidates


def _merge_waste_segment_candidates_into_cut_analysis(
    cut_analysis: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        return cut_analysis
    analysis = dict(cut_analysis)
    existing = [dict(item) for item in list(analysis.get("rule_candidates") or []) if isinstance(item, dict)]
    seen = {
        (
            str(item.get("reason") or "").strip(),
            round(float(item.get("start", 0.0) or 0.0), 3),
            round(float(item.get("end", 0.0) or 0.0), 3),
        )
        for item in existing
    }
    merged = list(existing)
    added = 0
    for candidate in candidates:
        key = (
            str(candidate.get("reason") or "").strip(),
            round(float(candidate.get("start", 0.0) or 0.0), 3),
            round(float(candidate.get("end", 0.0) or 0.0), 3),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(candidate))
        added += 1
    analysis["rule_candidates"] = merged
    analysis.update(summarize_cut_analysis_candidate_metrics(analysis.get("accepted_cuts"), merged))
    sources = {
        str(item.get("candidate_stage") or "accepted_cut").strip() or "accepted_cut"
        for item in [*list(analysis.get("accepted_cuts") or []), *merged]
        if isinstance(item, dict)
    }
    analysis["candidate_sources"] = sorted(sources)
    analysis["waste_segment_discovery_summary"] = {
        "enabled": True,
        "candidate_count": len(candidates),
        "added_count": added,
        "stage": SEMANTIC_TIMELINE_ANALYSIS_STAGE,
        "semantic_source": "llm_waste_segment_discovery",
    }
    return analysis


def _attach_semantic_timeline_analysis_summary(cut_analysis: dict[str, Any]) -> dict[str, Any]:
    analysis = dict(cut_analysis)
    candidates = [dict(item) for item in list(analysis.get("rule_candidates") or []) if isinstance(item, dict)]
    waste_count = sum(1 for item in candidates if str(item.get("semantic_role") or "") == "waste_candidate")
    highlight_count = sum(
        1
        for item in candidates
        if str(item.get("reason") or "") == "highlight_window"
        or str(item.get("semantic_role") or "") == "highlight_candidate"
    )
    boundary_count = sum(1 for item in candidates if str(item.get("semantic_role") or "") == "segment_boundary")
    analysis["semantic_timeline_analysis_summary"] = {
        "schema_version": SEMANTIC_TIMELINE_ANALYSIS_SCHEMA_VERSION,
        "stage": SEMANTIC_TIMELINE_ANALYSIS_STAGE,
        "subtitle_cleanup_required": True,
        "waste_candidate_count": waste_count,
        "highlight_candidate_count": highlight_count,
        "segment_boundary_candidate_count": boundary_count,
    }
    return analysis


async def _maybe_discover_waste_segments_with_llm(
    *,
    job_id: uuid.UUID,
    source_name: str,
    cut_analysis: dict[str, Any],
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
    duration: float,
) -> dict[str, Any]:
    settings = get_settings()
    if not bool(getattr(settings, "edit_decision_waste_discovery_enabled", True)):
        updated = dict(cut_analysis)
        updated["waste_segment_discovery_summary"] = {"enabled": False}
        return updated
    try:
        max_subtitles = max(0, int(getattr(settings, "edit_decision_waste_discovery_max_subtitles", 160) or 160))
    except (TypeError, ValueError):
        max_subtitles = 160
    subtitle_windows = _build_waste_segment_discovery_subtitle_context_windows(
        subtitle_items,
        max_items=max_subtitles,
    )
    if not subtitle_windows:
        updated = dict(cut_analysis)
        updated["waste_segment_discovery_summary"] = {"enabled": True, "candidate_count": 0}
        return updated
    try:
        timeout_sec = max(10.0, float(getattr(settings, "edit_decision_waste_discovery_timeout_sec", 45) or 45))
    except (TypeError, ValueError):
        timeout_sec = 45.0
    try:
        max_candidates = max(0, int(getattr(settings, "edit_decision_waste_discovery_max_candidates", 8) or 8))
    except (TypeError, ValueError):
        max_candidates = 8
    try:
        min_confidence = max(0.0, min(1.0, float(getattr(settings, "edit_decision_waste_discovery_min_confidence", 0.68) or 0.68)))
    except (TypeError, ValueError):
        min_confidence = 0.68
    try:
        all_candidates: list[dict[str, Any]] = []
        summaries: list[str] = []
        source_meta_base = {
            "job_id": str(job_id),
            "source_name": str(source_name or "").strip(),
            "subject_brand": str((content_profile or {}).get("subject_brand") or "").strip(),
            "subject_model": str((content_profile or {}).get("subject_model") or "").strip(),
            "subject_type": str((content_profile or {}).get("subject_type") or "").strip(),
            "content_kind": str((content_profile or {}).get("content_kind") or "").strip(),
        }
        with llm_task_route("edit_plan", search_enabled=False, settings=settings):
            provider = get_reasoning_provider()
            for window_index, subtitle_context in enumerate(subtitle_windows):
                first_item = subtitle_context[0] if subtitle_context else {}
                last_item = subtitle_context[-1] if subtitle_context else {}
                source_meta = {
                    **source_meta_base,
                    "window_index": window_index,
                    "window_count": len(subtitle_windows),
                    "window_start": first_item.get("start"),
                    "window_end": last_item.get("end"),
                }
                prompt_messages = build_waste_segment_discovery_prompt(
                    source_meta=source_meta,
                    subtitle_context=subtitle_context,
                )
                messages = [Message(role=str(item["role"]), content=str(item["content"])) for item in prompt_messages]
                with track_usage_operation("edit_plan.waste_segment_discovery"):
                    response = await _complete_reasoning_with_timeout(
                        provider,
                        messages,
                        temperature=0.1,
                        max_tokens=1400,
                        json_mode=True,
                        timeout_sec=timeout_sec,
                    )
                payload = json.loads(extract_json_text(str(getattr(response, "content", "") or getattr(response, "raw_content", "") or "")))
                window_candidates = _normalize_waste_segment_discovery_candidates(
                    payload,
                    duration=duration,
                    min_confidence=min_confidence,
                    max_candidates=max_candidates,
                    subtitle_context=subtitle_context,
                )
                for candidate in window_candidates:
                    candidate.setdefault("llm_discovery", {})
                    if isinstance(candidate.get("llm_discovery"), dict):
                        candidate["llm_discovery"]["window_index"] = window_index
                        candidate["llm_discovery"]["window_count"] = len(subtitle_windows)
                    all_candidates.append(candidate)
                summary_text = str(payload.get("summary") or "").strip()
                if summary_text:
                    summaries.append(summary_text)
                if max_candidates > 0 and len(all_candidates) >= max_candidates:
                    break
        deduped_candidates: list[dict[str, Any]] = []
        seen_candidates: set[tuple[str, float, float]] = set()
        for candidate in all_candidates:
            key = (
                str(candidate.get("reason") or "").strip(),
                round(float(candidate.get("start", 0.0) or 0.0), 3),
                round(float(candidate.get("end", 0.0) or 0.0), 3),
            )
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            deduped_candidates.append(candidate)
            if max_candidates > 0 and len(deduped_candidates) >= max_candidates:
                break
        candidates = deduped_candidates
        if not candidates:
            updated = dict(cut_analysis)
            updated["waste_segment_discovery_summary"] = {
                "enabled": True,
                "reviewed": True,
                "candidate_count": 0,
                "added_count": 0,
                "stage": SEMANTIC_TIMELINE_ANALYSIS_STAGE,
                "semantic_source": "llm_waste_segment_discovery",
                "provider": str(get_settings().active_reasoning_provider or ""),
                "model": str(get_settings().active_reasoning_model or ""),
                "summary": " | ".join(summaries[:4]),
                "window_count": len(subtitle_windows),
            }
            return updated
        updated = _merge_waste_segment_candidates_into_cut_analysis(cut_analysis, candidates)
        summary = dict(updated.get("waste_segment_discovery_summary") or {})
        summary.update(
            {
                "reviewed": True,
                "provider": str(get_settings().active_reasoning_provider or ""),
                "model": str(get_settings().active_reasoning_model or ""),
                "summary": " | ".join(summaries[:4]),
                "window_count": len(subtitle_windows),
            }
        )
        updated["waste_segment_discovery_summary"] = summary
        return updated
    except Exception as exc:
        logger.warning("LLM waste segment discovery failed during edit_plan for job %s: %s", job_id, str(exc).strip())
        updated = dict(cut_analysis)
        updated["waste_segment_discovery_summary"] = {
            "enabled": True,
            "reviewed": False,
            "candidate_count": 0,
            "error": "llm_waste_segment_discovery_failed",
        }
        return updated


async def _maybe_enrich_cut_analysis_with_semantic_timeline_analysis(
    *,
    job_id: uuid.UUID,
    source_name: str,
    cut_analysis: dict[str, Any],
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
    duration: float,
) -> dict[str, Any]:
    enriched = await _maybe_discover_waste_segments_with_llm(
        job_id=job_id,
        source_name=source_name,
        cut_analysis=cut_analysis,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        duration=duration,
    )
    return _attach_semantic_timeline_analysis_summary(enriched)


async def _complete_reasoning_with_timeout(
    provider: object,
    messages: list[Message],
    *,
    temperature: float,
    max_tokens: int,
    json_mode: bool,
    timeout_sec: float,
) -> Any:
    completion = provider.complete(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )
    if bool(getattr(provider, "_bridge_mode", False)):
        return await completion
    return await asyncio.wait_for(completion, timeout=timeout_sec)


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
    keep_restore_ids = {
        candidate_id
        for candidate_id, item in review_by_id.items()
        if str(item.get("verdict") or "") == "keep" and float(item.get("confidence", 0.0) or 0.0) >= min_confidence
    }
    unsure_demote_ids = {
        candidate_id
        for candidate_id, item in review_by_id.items()
        if str(item.get("verdict") or "") == "unsure"
    }
    restore_ids = keep_restore_ids | unsure_demote_ids

    if restore_ids:
        updated_segments: list[EditSegment] = []
        for segment in decision.segments:
            if segment.type == "remove" and _segment_cut_key(segment) in restore_ids:
                updated_segments.append(EditSegment(start=segment.start, end=segment.end, type="keep"))
            else:
                updated_segments.append(EditSegment(start=segment.start, end=segment.end, type=segment.type, reason=segment.reason))
        decision.segments = _merge_edit_segments(updated_segments)

    accepted_cuts: list[dict[str, Any]] = []
    existing_rule_candidates = [
        dict(item)
        for item in list((decision.analysis or {}).get("manual_editor_rule_candidates") or [])
        if isinstance(item, dict)
    ]
    demoted_rule_candidates: list[dict[str, Any]] = []
    for item in list((decision.analysis or {}).get("accepted_cuts") or []):
        if not isinstance(item, dict):
            continue
        candidate_id = _cut_review_candidate_id(item)
        if candidate_id in restore_ids:
            if candidate_id in unsure_demote_ids:
                payload = dict(item)
                payload["auto_applied"] = False
                if candidate_id in review_by_id:
                    payload["llm_review"] = dict(review_by_id[candidate_id])
                demoted_rule_candidates.append(payload)
            continue
        payload = dict(item)
        if candidate_id in review_by_id:
            payload["llm_review"] = dict(review_by_id[candidate_id])
        accepted_cuts.append(payload)
    decision.analysis["accepted_cuts"] = accepted_cuts
    if demoted_rule_candidates:
        merged_rule_candidates: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in [*existing_rule_candidates, *demoted_rule_candidates]:
            candidate_id = _cut_review_candidate_id(item)
            if candidate_id and candidate_id in seen_ids:
                continue
            if candidate_id:
                seen_ids.add(candidate_id)
            merged_rule_candidates.append(item)
        decision.analysis["manual_editor_rule_candidates"] = merged_rule_candidates

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
        "restored_cut_count": len(keep_restore_ids),
        "demoted_cut_count": len(unsure_demote_ids),
        "cached": bool(review_result.get("cached")),
        "provider": str(review_result.get("provider") or ""),
        "model": str(review_result.get("model") or ""),
        "summary": str(review_result.get("summary") or ""),
        "decisions": normalized_reviews,
    }
    return decision


def _load_compatible_cross_job_cut_review_cache(
    cache_namespace: str,
    *,
    source_meta: dict[str, Any],
    provider: str,
    model: str,
    candidates_sha256: str,
    min_confidence: float,
) -> dict[str, Any] | None:
    namespace_dir = get_cache_path(cache_namespace, "probe").parent
    if not namespace_dir.exists():
        return None
    expected_source_meta = {
        "source_name": str(source_meta.get("source_name") or "").strip(),
        "subject_brand": str(source_meta.get("subject_brand") or "").strip(),
        "subject_model": str(source_meta.get("subject_model") or "").strip(),
        "subject_type": str(source_meta.get("subject_type") or "").strip(),
    }
    for path in sorted(namespace_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        fingerprint = payload.get("fingerprint")
        result = payload.get("result")
        if not isinstance(fingerprint, dict) or not isinstance(result, dict):
            continue
        cached_source_meta = fingerprint.get("source_meta")
        if not isinstance(cached_source_meta, dict):
            continue
        comparable_source_meta = {
            "source_name": str(cached_source_meta.get("source_name") or "").strip(),
            "subject_brand": str(cached_source_meta.get("subject_brand") or "").strip(),
            "subject_model": str(cached_source_meta.get("subject_model") or "").strip(),
            "subject_type": str(cached_source_meta.get("subject_type") or "").strip(),
        }
        if comparable_source_meta != expected_source_meta:
            continue
        if str(fingerprint.get("provider") or "").strip() != str(provider or "").strip():
            continue
        if str(fingerprint.get("model") or "").strip() != str(model or "").strip():
            continue
        if str(fingerprint.get("candidates_sha256") or "").strip() != str(candidates_sha256 or "").strip():
            continue
        try:
            cached_min_confidence = float(fingerprint.get("min_confidence") or 0.0)
        except (TypeError, ValueError):
            continue
        if cached_min_confidence != float(min_confidence or 0.0):
            continue
        return {
            "namespace": str(payload.get("namespace") or cache_namespace).strip(),
            "key": str(payload.get("key") or "").strip(),
            "result": dict(result),
            "usage_baseline": payload.get("usage_baseline"),
        }
    return None


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
    if cached_entry is None:
        cached_entry = _load_compatible_cross_job_cut_review_cache(
            cache_namespace,
            source_meta=source_meta,
            provider=str(active_provider or ""),
            model=str(active_model or ""),
            candidates_sha256=str(fingerprint.get("candidates_sha256") or ""),
            min_confidence=float(fingerprint.get("min_confidence") or 0.72),
        )
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
                response = await _complete_reasoning_with_timeout(
                    provider,
                    prompt_message_objects,
                    temperature=0.1,
                    max_tokens=1200,
                    json_mode=True,
                    timeout_sec=review_timeout_sec,
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
    except (asyncio.TimeoutError, TimeoutError):
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
        if "credential is not configured" in message or "no helper command or token is configured" in message:
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
        logger.warning(
            "LLM cut review produced an unusable payload during edit_plan for job %s; falling back to deterministic evidence: %s",
            job_id,
            message,
        )
        decision.analysis["llm_cut_review"] = {
            "reviewed": False,
            "candidate_count": len(candidates),
            "error": "llm_cut_review_failed",
            "fallback": "deterministic_evidence",
        }
        return decision
    except Exception as exc:
        logger.exception("LLM cut review failed during edit_plan for job %s", job_id)
        failure_payload: dict[str, Any] = {
            "reviewed": False,
            "candidate_count": len(candidates),
            "error": "llm_cut_review_failed",
            "fallback": "deterministic_evidence",
        }
        if isinstance(exc, httpx.HTTPStatusError) and getattr(exc, "response", None) is not None:
            diagnostics = zhipu_response_diagnostics(exc.response)
            if diagnostics.get("status_code") is not None:
                failure_payload["upstream_status"] = diagnostics["status_code"]
            if diagnostics.get("error_code"):
                failure_payload["upstream_error_code"] = diagnostics["error_code"]
            if diagnostics.get("error_message"):
                failure_payload["upstream_error_message"] = diagnostics["error_message"]
            if diagnostics.get("retry_after_seconds") is not None:
                failure_payload["retry_after_seconds"] = diagnostics["retry_after_seconds"]
            if diagnostics.get("x_log_id"):
                failure_payload["x_log_id"] = diagnostics["x_log_id"]
            if diagnostics.get("body_excerpt"):
                failure_payload["upstream_body_excerpt"] = diagnostics["body_excerpt"]
        decision.analysis["llm_cut_review"] = failure_payload
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
            "max_chars": 18,
            "max_duration": 4.2,
        }
    return {
        "orientation": "landscape",
        "max_chars": 34,
        "max_duration": 5.8,
    }


def _subtitle_segmentation_defect_rank(analysis: Any) -> tuple[int, int, int, int]:
    protected_or_word_split = int(getattr(analysis, "protected_term_split_count", 0) or 0) + int(
        getattr(analysis, "generic_word_split_count", 0) or 0
    )
    fragment_count = int(getattr(analysis, "fragment_start_count", 0) or 0) + int(
        getattr(analysis, "fragment_end_count", 0) or 0
    )
    suspicious_count = int(getattr(analysis, "suspicious_boundary_count", 0) or 0)
    low_confidence_count = int(getattr(analysis, "low_confidence_window_count", 0) or 0)
    return protected_or_word_split, fragment_count, suspicious_count, low_confidence_count


def _subtitle_segmentation_needs_profile_retry(analysis: Any) -> bool:
    word_split_count, fragment_count, suspicious_count, low_confidence_count = _subtitle_segmentation_defect_rank(
        analysis
    )
    return (
        word_split_count > 0
        or fragment_count > 0
        or suspicious_count > 0
        or low_confidence_count >= 6
    )


def _subtitle_segmentation_candidate_is_better(base_analysis: Any, candidate_analysis: Any) -> bool:
    return _subtitle_segmentation_defect_rank(candidate_analysis) < _subtitle_segmentation_defect_rank(base_analysis)


def _relaxed_subtitle_split_profile(split_profile: dict[str, Any]) -> dict[str, Any] | None:
    if bool(split_profile.get("auto_relaxed")):
        return None
    orientation = str(split_profile.get("orientation") or "landscape")
    max_chars = int(split_profile.get("max_chars") or 30)
    max_duration = float(split_profile.get("max_duration") or 5.0)
    if orientation == "portrait":
        relaxed_chars = min(24, max_chars + 4)
        relaxed_duration = min(5.2, max_duration + 0.8)
    else:
        relaxed_chars = min(42, max_chars + 6)
        relaxed_duration = min(7.0, max_duration + 1.0)
    if relaxed_chars <= max_chars and relaxed_duration <= max_duration:
        return None
    return {
        **dict(split_profile),
        "max_chars": relaxed_chars,
        "max_duration": round(relaxed_duration, 3),
        "auto_relaxed": True,
        "base_max_chars": max_chars,
        "base_max_duration": max_duration,
    }


def _subtitle_segmentation_retry_summary(
    *,
    attempted: bool = False,
    accepted: bool = False,
    reason: str = "",
    base_profile: dict[str, Any] | None = None,
    candidate_profile: dict[str, Any] | None = None,
    base_rank: tuple[int, int, int, int] | None = None,
    candidate_rank: tuple[int, int, int, int] | None = None,
) -> dict[str, Any]:
    return {
        "attempted": bool(attempted),
        "accepted": bool(accepted),
        "reason": reason,
        "base_profile": dict(base_profile or {}),
        "candidate_profile": dict(candidate_profile or {}),
        "base_defect_rank": list(base_rank or ()),
        "candidate_defect_rank": list(candidate_rank or ()),
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
        repaired = await _complete_reasoning_with_timeout(
            provider,
            repair_messages,
            temperature=0.0,
            max_tokens=900,
            json_mode=False,
            timeout_sec=max(8.0, min(float(timeout_sec), 16.0)),
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
            final_response = await _complete_reasoning_with_timeout(
                provider,
                [
                    Message(role="system", content="你是 JSON 修复器，只输出严格 JSON。"),
                    Message(role="user", content=repair_prompt),
                ],
                temperature=0.0,
                max_tokens=900,
                json_mode=True,
                timeout_sec=max(8.0, min(float(timeout_sec), 16.0)),
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
        text = str(row.text or "")
        fallback_segments.append(
            {
                "index": int(row.segment_index),
                "start": float(row.start_time),
                "end": float(row.end_time),
                "text": text,
                "text_raw": text,
                "text_canonical": text,
                "text_norm": text,
                "text_final": text,
                "speaker": row.speaker,
                "words": drop_redundant_synthetic_word_payloads(list(row.words_json or [])),
            }
        )
    return fallback_segments


def _normalize_transcript_segment_payloads(raw_segments: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(list(raw_segments or [])):
        if not isinstance(item, dict):
            continue
        surfaces = subtitle_surface_item_dict(
            item,
            generic_fallback_text=str(item.get("text") or item.get("raw_text") or item.get("text_raw") or ""),
        )
        normalized.append(
            {
                "index": int(item.get("index", index) or index),
                "start": float(item.get("start_time") or item.get("start") or 0.0),
                "end": float(item.get("end_time") or item.get("end") or 0.0),
                "text": str(surfaces["text_norm"] or surfaces["text_raw"] or item.get("text") or ""),
                "text_raw": surfaces["text_raw"],
                "text_canonical": surfaces["text_norm"],
                "text_norm": surfaces["text_norm"],
                "text_final": surfaces["text_final"],
                "speaker": item.get("speaker"),
                "confidence": item.get("confidence"),
                "logprob": item.get("logprob"),
                "alignment": item.get("alignment"),
                "words": drop_redundant_synthetic_word_payloads(list(item.get("words") or [])),
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


_STEP_RUNTIME_BUDGET_METADATA_KEYS = (
    "runtime_budget_phase",
    "runtime_budget_sec",
    "runtime_budget_started_at",
)


async def _set_step_runtime_budget(
    session,
    step: JobStep | None,
    *,
    phase: str,
    timeout_sec: float,
) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    now = datetime.now(timezone.utc)
    metadata["updated_at"] = now.isoformat()
    elapsed_seconds = _compute_step_elapsed_seconds(step, now=now)
    if elapsed_seconds is not None:
        metadata["elapsed_seconds"] = round(elapsed_seconds, 3)
    metadata["runtime_budget_phase"] = str(phase or "").strip()
    metadata["runtime_budget_sec"] = max(1.0, float(timeout_sec))
    metadata["runtime_budget_started_at"] = now.isoformat()
    step.metadata_ = metadata
    await session.commit()


async def _clear_step_runtime_budget(session, step: JobStep | None) -> None:
    if step is None:
        return
    metadata = dict(step.metadata_ or {})
    changed = False
    for key in _STEP_RUNTIME_BUDGET_METADATA_KEYS:
        if key in metadata:
            metadata.pop(key, None)
            changed = True
    if not changed:
        return
    now = datetime.now(timezone.utc)
    metadata["updated_at"] = now.isoformat()
    elapsed_seconds = _compute_step_elapsed_seconds(step, now=now)
    if elapsed_seconds is not None:
        metadata["elapsed_seconds"] = round(elapsed_seconds, 3)
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
async def _maintain_step_heartbeat(
    step: JobStep | None,
    *,
    detail: str | None = None,
    progress: float | None = None,
):
    heartbeat_detail = detail
    if heartbeat_detail is None:
        heartbeat_detail = (
            str((step.metadata_ or {}).get("detail") or STEP_LABELS.get(step.step_name, step.step_name))
            if step is not None
            else ""
        )
    heartbeat = _spawn_step_heartbeat(
        step_id=step.id if step is not None else None,
        detail=str(heartbeat_detail),
        progress=progress if progress is not None else _current_step_heartbeat_progress(step),
    )
    try:
        yield
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat


def _write_blocking_step_heartbeat(
    *,
    step_id: uuid.UUID,
    detail: str,
    progress: float | None = None,
) -> bool:
    settings = get_settings()

    async def _write() -> bool:
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            poolclass=NullPool,
        )
        try:
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                step_ref = await session.get(JobStep, step_id)
                if step_ref is None or step_ref.status != "running":
                    return False
                await _set_step_progress(session, step_ref, detail=detail, progress=progress)
                return True
        finally:
            await engine.dispose()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return bool(asyncio.run(_write()))

    result: list[bool] = [False]
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result[0] = bool(asyncio.run(_write()))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(
        target=_runner,
        name=f"roughcut-step-heartbeat-write-{step_id}",
        daemon=True,
    )
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


@contextmanager
def _maintain_blocking_step_heartbeat(
    step: JobStep | None,
    *,
    detail: str,
    progress: float | None = None,
):
    if step is None or step.id is None:
        yield
        return

    settings = get_settings()
    interval_sec = max(5.0, float(getattr(settings, "step_heartbeat_interval_sec", 20) or 20))
    stop_event = threading.Event()

    try:
        heartbeat_running = _write_blocking_step_heartbeat(
            step_id=step.id,
            detail=detail,
            progress=progress,
        )
    except Exception:
        logger.debug("Initial blocking step heartbeat failed step_id=%s", step.id, exc_info=True)
        heartbeat_running = True

    if not heartbeat_running:
        yield
        return

    def _heartbeat_loop() -> None:
        while not stop_event.wait(interval_sec):
            try:
                still_running = _write_blocking_step_heartbeat(
                    step_id=step.id,
                    detail=detail,
                    progress=progress,
                )
            except Exception:
                logger.debug("Blocking step heartbeat failed step_id=%s", step.id, exc_info=True)
                continue
            if not still_running:
                return

    thread = threading.Thread(
        target=_heartbeat_loop,
        name=f"roughcut-step-heartbeat-{step.step_name}-{step.id}",
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=1.0)


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
    profile_artifacts = [
        artifact
        for artifact in artifacts or []
        if str(artifact.artifact_type or "").strip() in _CONTENT_PROFILE_ARTIFACT_TYPES
    ]
    if not profile_artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    finals = [artifact for artifact in profile_artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"]
    if finals:
        return max(
            finals,
            key=lambda artifact: (
                _content_profile_artifact_priority(artifact.artifact_type),
                artifact.created_at or epoch,
            ),
        )
    return max(
        profile_artifacts,
        key=lambda artifact: (
            _content_profile_artifact_priority(artifact.artifact_type),
            artifact.created_at or epoch,
        ),
    )


def _select_preferred_downstream_profile_artifact(artifacts: list[Artifact]) -> Artifact | None:
    profile_artifacts = [
        artifact
        for artifact in artifacts or []
        if _downstream_profile_artifact_priority(str(artifact.artifact_type or "").strip()) > 0
    ]
    if not profile_artifacts:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    latest_downstream_context = max(
        (artifact for artifact in profile_artifacts if str(artifact.artifact_type or "").strip() == "downstream_context"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    latest_content_profile_final = max(
        (artifact for artifact in profile_artifacts if str(artifact.artifact_type or "").strip() == "content_profile_final"),
        key=lambda artifact: artifact.created_at or epoch,
        default=None,
    )
    if latest_content_profile_final is not None and (
        latest_downstream_context is None
        or (latest_content_profile_final.created_at or epoch) > (latest_downstream_context.created_at or epoch)
    ):
        return latest_content_profile_final
    return max(
        profile_artifacts,
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
    profile = resolve_downstream_profile(artifact.data_json if isinstance(artifact.data_json, dict) else {})
    return artifact, attach_strategy_review_context(
        profile,
        select_strategy_review_artifact_context(artifacts),
    )


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
        payload = _subtitle_surface_payload(item)
        surfaces = subtitle_surface_item_dict(
            payload,
            generic_fallback_text=str(payload.get("text") or payload.get("text_raw") or ""),
        )
        canonical_text = str(surfaces["text_norm"] or surfaces["text_raw"] or "")
        entry_text = str(
            surfaces["text_final"] if use_final_text else surfaces["text_raw"] or canonical_text
        )
        entries.append(
            SubtitleEntry(
                index=int(getattr(item, "item_index", 0) or 0),
                start=float(getattr(item, "start_time", 0.0) or 0.0),
                end=float(getattr(item, "end_time", 0.0) or 0.0),
                text_raw=entry_text,
                text_norm=normalize_projection_display_text(canonical_text or entry_text),
                words=(),
            )
        )
    return entries


def _build_projection_items_from_entries(entries: list[SubtitleEntry]) -> list[SimpleNamespace]:
    projection_items: list[SimpleNamespace] = []
    for index, entry in enumerate(list(entries or [])):
        raw_text = str(getattr(entry, "text_raw", "") or "")
        normalized_text = str(getattr(entry, "text_norm", "") or "")
        canonical_text = normalize_projection_display_text(normalized_text or raw_text)
        display_source = _projection_display_source_text(raw_text, normalized_text)
        display_norm = normalize_projection_display_text(display_source)
        projection_items.append(
            SimpleNamespace(
                item_index=int(getattr(entry, "index", index) or index),
                start_time=float(getattr(entry, "start", 0.0) or 0.0),
                end_time=float(getattr(entry, "end", 0.0) or 0.0),
                text_raw=raw_text,
                text_norm=canonical_text,
                text_final=display_norm,
                words=tuple(getattr(entry, "words", ()) or ()),
            )
        )
    return projection_items


def _projection_display_source_text(raw_text: str, normalized_text: str) -> str:
    raw_value = str(raw_text or "").strip()
    normalized_value = str(normalized_text or "").strip()
    if not raw_value:
        return normalized_value
    if not normalized_value:
        return raw_value

    raw_compact = _projection_compact_text(raw_value)
    normalized_compact = _projection_compact_text(normalized_value)
    if not raw_compact or not normalized_compact:
        return normalized_value or raw_value
    if raw_compact == normalized_compact:
        return normalized_value
    if _projection_normalized_text_drops_content(raw_compact, normalized_compact):
        return raw_value
    return normalized_value


def _projection_normalized_text_drops_content(raw_compact: str, normalized_compact: str) -> bool:
    if not raw_compact or not normalized_compact:
        return False
    if len(raw_compact) <= len(normalized_compact):
        return False
    if normalized_compact in raw_compact and len(raw_compact) - len(normalized_compact) >= 2:
        return True
    prefix_len = 0
    for left_char, right_char in zip(raw_compact, normalized_compact):
        if left_char != right_char:
            break
        prefix_len += 1
    raw_remaining = raw_compact[prefix_len:]
    normalized_remaining = normalized_compact[prefix_len:]
    while raw_remaining and normalized_remaining and raw_remaining[-1] == normalized_remaining[-1]:
        raw_remaining = raw_remaining[:-1]
        normalized_remaining = normalized_remaining[:-1]
    return len(raw_remaining) >= 2 and len(normalized_remaining) == 0


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
        adapters.append(_build_transcript_segment_adapter(row, index=index))
    return adapters


async def _build_canonical_refresh_projection(
    session,
    *,
    job_id: uuid.UUID,
    source_name: str,
    subtitle_items: list[SubtitleItem],
    canonical_transcript_layer: Any,
    projection_data: dict[str, Any] | None,
    allow_display_baseline_preserved: bool = False,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    effective_projection_data = dict(projection_data or {})
    split_profile = (
        dict(effective_projection_data.get("split_profile") or {})
        if subtitle_projection_data_is_current(effective_projection_data)
        else {}
    )
    if not split_profile:
        media_meta = await _load_latest_optional_artifact(session, job_id=job_id, artifact_types=("media_meta",))
        media_meta_json = media_meta.data_json if media_meta and isinstance(media_meta.data_json, dict) else {}
        split_profile = _resolve_subtitle_split_profile(
            width=media_meta_json.get("width"),
            height=media_meta_json.get("height"),
        )
    boundary_refine = dict(effective_projection_data.get("boundary_refine") or {})
    existing_entries = _build_projection_entries_from_subtitle_items(
        subtitle_items,
        use_final_text=True,
    )
    existing_projection_items = _build_projection_items_from_entries(existing_entries)
    existing_quality_report = build_subtitle_quality_report_from_items(
        subtitle_items=existing_projection_items,
        source_name=source_name,
        content_profile={},
        require_word_alignment=True,
    )
    existing_projection_analysis = analyze_subtitle_segmentation(existing_entries)

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
        projection_entries = existing_entries
        projection_analysis = analyze_subtitle_segmentation(projection_entries)
    else:
        projection_analysis = canonical_segmentation_result.analysis
    canonical_projection_items = _build_projection_items_from_entries(projection_entries)
    canonical_quality_report = build_subtitle_quality_report_from_items(
        subtitle_items=canonical_projection_items,
        source_name=source_name,
        content_profile={},
        require_word_alignment=True,
    )
    display_boundary_hybrid_entries = _build_display_boundary_hybrid_projection_entries(
        canonical_entries=projection_entries,
        display_entries=existing_entries,
        split_profile=split_profile,
    )
    hybrid_projection_items = _build_projection_items_from_entries(display_boundary_hybrid_entries)
    hybrid_projection_analysis = analyze_subtitle_segmentation(display_boundary_hybrid_entries)
    hybrid_quality_report = build_subtitle_quality_report_from_items(
        subtitle_items=hybrid_projection_items,
        source_name=source_name,
        content_profile={},
        require_word_alignment=True,
    )
    canonical_output_fallback_detected = subtitle_quality_report_has_output_fallback(
        canonical_quality_report
    )
    hybrid_output_fallback_detected = subtitle_quality_report_has_output_fallback(
        hybrid_quality_report
    )
    existing_output_fallback_detected = (
        subtitle_quality_report_has_output_fallback(existing_quality_report)
        or subtitle_items_have_output_fallback_alignment(existing_projection_items)
    )
    existing_word_alignment_missing = (
        subtitle_quality_report_has_missing_word_alignment(existing_quality_report, blocking_only=True)
        or subtitle_alignment_source_metrics_has_missing_word_alignment(
            build_subtitle_alignment_source_metrics(existing_projection_items),
            blocking_only=True,
        )
    )
    force_display_baseline_for_output_fallback = (
        bool(existing_projection_items)
        and not existing_output_fallback_detected
        and not existing_word_alignment_missing
        and (
            canonical_output_fallback_detected
            or hybrid_output_fallback_detected
        )
    )
    preferred_basis = None
    if _display_boundary_hybrid_candidate_worth_adding(
        canonical_quality_report=canonical_quality_report,
        hybrid_quality_report=hybrid_quality_report,
    ):
        preferred_basis = "canonical_display_boundary_hybrid"
    # Canonical transcript segmentation is the single projection authority.
    # Legacy subtitle-item baselines are only eligible when a caller explicitly
    # opts into that compatibility path.
    keep_existing_projection = force_display_baseline_for_output_fallback or (
        bool(allow_display_baseline_preserved)
        and _should_keep_existing_subtitle_projection(
            existing_quality_report=existing_quality_report,
            refreshed_quality_report=canonical_quality_report,
            canonical_transcript_layer=canonical_transcript_layer,
            existing_projection_items=existing_projection_items,
            refreshed_projection_items=canonical_projection_items,
        )
    )
    candidate_pool = _build_projection_candidate_pool(
        canonical_projection_items=canonical_projection_items,
        projection_analysis=projection_analysis,
        canonical_quality_report=canonical_quality_report,
        hybrid_projection_items=hybrid_projection_items,
        hybrid_projection_analysis=hybrid_projection_analysis,
        hybrid_quality_report=hybrid_quality_report,
        existing_projection_items=existing_projection_items,
        existing_projection_analysis=existing_projection_analysis,
        existing_quality_report=existing_quality_report,
        allow_display_baseline_preserved=keep_existing_projection,
        suppress_canonical_refresh=canonical_output_fallback_detected and not existing_word_alignment_missing,
        suppress_hybrid_projection=hybrid_output_fallback_detected and not existing_word_alignment_missing,
    )
    selected_candidate, correction_score_report = _select_projection_candidate(
        candidates=candidate_pool,
        reference_items=canonical_projection_items,
        canonical_transcript_layer=canonical_transcript_layer,
        preferred_basis=(
            "display_baseline_preserved"
            if force_display_baseline_for_output_fallback or keep_existing_projection
            else preferred_basis
        ),
    )
    projection_items = list(selected_candidate["items"])
    projection_analysis = selected_candidate["analysis"]
    subtitle_quality_report = dict(selected_candidate["quality_report"] or {})
    projection_basis = str(selected_candidate["basis"])
    transcript_layer = str(selected_candidate["transcript_layer"])
    correction_score_report = {
        **dict(correction_score_report or {}),
        "selected_basis": projection_basis,
        "canonical_output_fallback_detected": canonical_output_fallback_detected,
        "hybrid_output_fallback_detected": hybrid_output_fallback_detected,
        "existing_output_fallback_detected": existing_output_fallback_detected,
        "existing_word_alignment_missing": existing_word_alignment_missing,
        "output_fallback_guard_applied": force_display_baseline_for_output_fallback,
        "selection_policy": _projection_selection_policy(
            selected_basis=projection_basis,
            canonical_projection_items=canonical_projection_items,
            keep_existing_projection=keep_existing_projection,
            output_fallback_guard_applied=force_display_baseline_for_output_fallback,
        ),
    }
    subtitle_quality_report["correction_score"] = correction_score_report
    refreshed_projection_layer = build_subtitle_projection_layer(
        projection_items,
        segmentation_analysis=projection_analysis,
        split_profile=split_profile,
        boundary_refine=boundary_refine,
        quality_report=subtitle_quality_report,
        projection_basis=projection_basis,
        transcript_layer=transcript_layer,
    )
    return refreshed_projection_layer, subtitle_quality_report, correction_score_report


def _projection_selection_policy(
    *,
    selected_basis: str,
    canonical_projection_items: list[Any],
    keep_existing_projection: bool,
    output_fallback_guard_applied: bool = False,
) -> str:
    if selected_basis == "display_baseline_preserved":
        if output_fallback_guard_applied:
            return "display_baseline_preserved_for_output_fallback_guard"
        if canonical_projection_items and keep_existing_projection:
            return "display_baseline_preserved_for_quality_guard"
        return "display_baseline_preserved_as_legacy_fallback"
    return "canonical_transcript_is_single_projection_authority"


def _should_keep_existing_subtitle_projection(
    *,
    existing_quality_report: dict[str, Any],
    refreshed_quality_report: dict[str, Any],
    canonical_transcript_layer: Any,
    existing_projection_items: list[Any] | None = None,
    refreshed_projection_items: list[Any] | None = None,
) -> bool:
    correction_metrics = dict(getattr(canonical_transcript_layer, "correction_metrics", {}) or {})
    if int(correction_metrics.get("accepted_correction_count") or 0) > 0:
        return False
    if _projection_has_material_content_drift(
        baseline_items=existing_projection_items or [],
        candidate_items=refreshed_projection_items or [],
    ):
        return False
    if not existing_quality_report:
        return False
    existing_blocking = bool(existing_quality_report.get("blocking"))
    refreshed_blocking = bool(refreshed_quality_report.get("blocking"))
    if not existing_blocking and refreshed_blocking:
        return True
    if existing_blocking and not refreshed_blocking:
        return False
    existing_rank = _subtitle_projection_quality_rank(existing_quality_report)
    refreshed_rank = _subtitle_projection_quality_rank(refreshed_quality_report)
    return existing_rank >= refreshed_rank


def _subtitle_projection_quality_rank(report: dict[str, Any]) -> tuple[float, int, int, int, int]:
    metrics = dict((report or {}).get("metrics") or {})
    try:
        score = float((report or {}).get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    warning_count = len(list((report or {}).get("warning_reasons") or []))
    short_fragment_count = int(metrics.get("short_fragment_count") or 0)
    generic_word_split_count = int(metrics.get("generic_word_split_count") or 0)
    subtitle_count = int(metrics.get("subtitle_count") or 0)
    return (
        round(score, 3),
        -warning_count,
        -short_fragment_count,
        -generic_word_split_count,
        -subtitle_count,
    )


def _build_local_hybrid_projection_entries(
    entries: list[SubtitleEntry],
    *,
    split_profile: dict[str, Any],
) -> list[SubtitleEntry]:
    # Projection no longer owns segmentation repair. Keep this helper as a
    # contract-preserving pass-through so stale callers cannot reintroduce a
    # hidden second segmentation stage after canonical segmentation.
    return _reindex_subtitle_entries(list(entries or []))


def _build_projection_candidate_pool(
    *,
    canonical_projection_items: list[SimpleNamespace],
    projection_analysis: Any,
    canonical_quality_report: dict[str, Any],
    hybrid_projection_items: list[SimpleNamespace],
    hybrid_projection_analysis: Any,
    hybrid_quality_report: dict[str, Any],
    existing_projection_items: list[SimpleNamespace],
    existing_projection_analysis: Any,
    existing_quality_report: dict[str, Any],
    allow_display_baseline_preserved: bool = False,
    suppress_canonical_refresh: bool = False,
    suppress_hybrid_projection: bool = False,
) -> list[dict[str, Any]]:
    # Canonical transcript segmentation is the only segmentation authority.
    # Projection may preserve or display it, but it must not compete with a
    # second local resegmentation candidate in the automatic pipeline.
    candidate_pool: list[dict[str, Any]] = []
    if not suppress_canonical_refresh:
        candidate_pool.append(
            {
                "basis": "canonical_refresh",
                "transcript_layer": "canonical_transcript",
                "items": canonical_projection_items,
                "analysis": projection_analysis,
                "quality_report": canonical_quality_report,
            }
        )
    if (
        not suppress_hybrid_projection
        and canonical_projection_items
        and hybrid_projection_items
        and _display_boundary_hybrid_candidate_worth_adding(
            canonical_quality_report=canonical_quality_report,
            hybrid_quality_report=hybrid_quality_report,
        )
        and _display_boundary_hybrid_candidate_shape_is_acceptable(
            canonical_projection_items=canonical_projection_items,
            hybrid_projection_items=hybrid_projection_items,
        )
    ):
        candidate_pool.append(
            {
                "basis": "canonical_display_boundary_hybrid",
                "transcript_layer": "canonical_transcript",
                "items": hybrid_projection_items,
                "analysis": hybrid_projection_analysis,
                "quality_report": hybrid_quality_report,
            }
        )
    if allow_display_baseline_preserved or not candidate_pool:
        candidate_pool.append(
            {
                "basis": "display_baseline_preserved",
                "transcript_layer": "subtitle_item",
                "items": existing_projection_items,
                "analysis": existing_projection_analysis,
                "quality_report": existing_quality_report,
            }
        )
    return candidate_pool


def _display_boundary_hybrid_candidate_worth_adding(
    *,
    canonical_quality_report: dict[str, Any],
    hybrid_quality_report: dict[str, Any],
) -> bool:
    canonical_generic_splits = _generic_word_split_metric(canonical_quality_report)
    hybrid_generic_splits = _generic_word_split_metric(hybrid_quality_report)
    if canonical_generic_splits <= 0 or hybrid_generic_splits >= canonical_generic_splits:
        return False
    hybrid_warning_count = len(list((hybrid_quality_report or {}).get("warning_reasons") or []))
    canonical_warning_count = len(list((canonical_quality_report or {}).get("warning_reasons") or []))
    return hybrid_warning_count <= canonical_warning_count


def _display_boundary_hybrid_candidate_shape_is_acceptable(
    *,
    canonical_projection_items: list[Any],
    hybrid_projection_items: list[Any],
) -> bool:
    if _projection_has_material_content_drift(
        baseline_items=canonical_projection_items,
        candidate_items=hybrid_projection_items,
    ):
        return False
    return _projection_items_preserve_segmentation_shape(
        canonical_projection_items,
        hybrid_projection_items,
    ) or _projection_items_have_moderate_shape_drift(
        canonical_projection_items,
        hybrid_projection_items,
    )


def _generic_word_split_metric(report: dict[str, Any]) -> int:
    metrics = dict((report or {}).get("metrics") or {})
    try:
        count = int(metrics.get("generic_word_split_count") or 0)
    except (TypeError, ValueError):
        count = 0
    if count > 0:
        return count
    for reason in list((report or {}).get("warning_reasons") or []):
        reason_text = str(reason or "").strip()
        if "普通词跨字幕截断" not in reason_text:
            continue
        match = re.search(r"(\d+)\s*处", reason_text)
        if match:
            return int(match.group(1))
    return 0


def _projection_items_allow_hybrid_candidate(
    *,
    baseline_items: list[Any],
    baseline_quality_report: dict[str, Any],
    candidate_items: list[Any],
    candidate_quality_report: dict[str, Any],
) -> bool:
    if not baseline_items:
        return True
    if _projection_has_material_content_drift(
        baseline_items=baseline_items,
        candidate_items=candidate_items,
    ):
        return False
    if _projection_items_preserve_segmentation_shape(
        baseline_items,
        candidate_items,
    ):
        return True
    baseline_rank = _subtitle_projection_quality_rank(baseline_quality_report)
    candidate_rank = _subtitle_projection_quality_rank(candidate_quality_report)
    if candidate_rank <= baseline_rank:
        return False
    return _projection_items_have_moderate_shape_drift(
        baseline_items,
        candidate_items,
    )


def _projection_items_have_moderate_shape_drift(
    baseline_items: list[Any],
    candidate_items: list[Any],
    *,
    start_end_slack: float = 0.2,
) -> bool:
    if not baseline_items or not candidate_items:
        return False
    baseline_count = len(baseline_items)
    candidate_count = len(candidate_items)
    if baseline_count <= 12 and candidate_count != baseline_count:
        return False
    count_delta = abs(baseline_count - candidate_count)
    allowed_delta = max(4, min(24, math.ceil(baseline_count * 0.15)))
    if count_delta > allowed_delta:
        return False
    ratio = candidate_count / max(baseline_count, 1)
    if ratio < 0.82 or ratio > 1.18:
        return False
    baseline_start = _projection_item_start(baseline_items[0])
    candidate_start = _projection_item_start(candidate_items[0])
    baseline_end = _projection_item_end(baseline_items[-1])
    candidate_end = _projection_item_end(candidate_items[-1])
    if abs(baseline_start - candidate_start) > start_end_slack:
        return False
    if abs(baseline_end - candidate_end) > start_end_slack:
        return False
    return True


def _projection_items_preserve_segmentation_shape(
    baseline_items: list[Any],
    candidate_items: list[Any],
    *,
    boundary_slack: float = 0.06,
) -> bool:
    if not baseline_items:
        return not candidate_items
    if len(baseline_items) != len(candidate_items):
        return False
    for baseline_item, candidate_item in zip(baseline_items, candidate_items):
        if abs(_projection_item_start(baseline_item) - _projection_item_start(candidate_item)) > boundary_slack:
            return False
        if abs(_projection_item_end(baseline_item) - _projection_item_end(candidate_item)) > boundary_slack:
            return False
    return True


def _best_local_projection_window_candidate(
    window_entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry] | None:
    current_analysis = analyze_subtitle_segmentation(window_entries)
    current_quality = build_subtitle_quality_report_from_items(
        subtitle_items=_build_projection_items_from_entries(window_entries),
        source_name="",
        content_profile={},
    )
    current_rank = _subtitle_projection_quality_rank(current_quality)
    current_score = score_subtitle_entries(
        window_entries,
        max_chars=max_chars,
        max_duration=max_duration,
    )
    best_candidate: list[SubtitleEntry] | None = None
    best_rank = current_rank
    best_score = current_score
    for candidate in generate_subtitle_window_candidates(
        window_entries,
        max_chars=max_chars + 2,
        max_duration=max_duration + 0.5,
        top_k=8,
    ):
        if len(candidate) > len(window_entries):
            continue
        if _entries_split_projection_material_tokens(candidate):
            continue
        candidate_quality = build_subtitle_quality_report_from_items(
            subtitle_items=_build_projection_items_from_entries(candidate),
            source_name="",
            content_profile={},
        )
        candidate_rank = _subtitle_projection_quality_rank(candidate_quality)
        candidate_score = score_subtitle_entries(
            candidate,
            max_chars=max_chars,
            max_duration=max_duration,
        )
        candidate_analysis = analyze_subtitle_segmentation(candidate)
        if not _fragment_window_candidate_is_acceptable(
            current_entries=window_entries,
            candidate_entries=candidate,
            current_score=current_score,
            candidate_score=candidate_score,
            current_analysis=current_analysis,
            candidate_analysis=candidate_analysis,
            max_chars=max_chars,
            max_duration=max_duration,
        ):
            continue
        if candidate_rank > best_rank or (candidate_rank == best_rank and candidate_score > best_score):
            best_candidate = candidate
            best_rank = candidate_rank
            best_score = candidate_score
    return best_candidate if best_rank > current_rank else None


def _entries_split_projection_material_tokens(entries: list[SubtitleEntry]) -> bool:
    ordered = list(entries or [])
    for left, right in zip(ordered, ordered[1:]):
        if _projection_boundary_splits_material_token(
            _projection_item_text(left),
            _projection_item_text(right),
        ):
            return True
    return False


def _merge_material_split_projection_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    ordered = _reindex_subtitle_entries(list(entries or []))
    if not ordered:
        return ordered
    merged: list[SubtitleEntry] = []
    index = 0
    while index < len(ordered):
        current = ordered[index]
        if (
            index + 1 < len(ordered)
            and _projection_boundary_splits_material_token(
                _projection_item_text(current),
                _projection_item_text(ordered[index + 1]),
            )
        ):
            merged.append(_merge_projection_entries(current, ordered[index + 1], len(merged)))
            index += 2
            continue
        merged.append(current)
        index += 1
    return _reindex_subtitle_entries(merged)


def _projection_boundary_splits_material_token(left_text: str, right_text: str) -> bool:
    left_compact = _projection_compact_text(left_text)
    right_compact = _projection_compact_text(right_text)
    if not left_compact or not right_compact:
        return False
    joined_text = normalize_projection_display_text(f"{left_text}{right_text}")
    joined_compact = _projection_compact_text(joined_text)
    if not joined_compact:
        return False
    material_tokens = set(_projection_material_tokens(joined_text))
    material_tokens.update(_projection_material_tokens(joined_compact))
    for token in material_tokens:
        token_compact = _projection_compact_text(token)
        if not token_compact or token_compact not in joined_compact:
            continue
        if token_compact in left_compact or token_compact in right_compact:
            continue
        return True
    return False


def _build_display_boundary_hybrid_projection_entries(
    *,
    canonical_entries: list[SubtitleEntry],
    display_entries: list[SubtitleEntry],
    split_profile: dict[str, Any],
) -> list[SubtitleEntry]:
    canonical_entries = list(canonical_entries or [])
    display_entries = list(display_entries or [])
    if not canonical_entries or not display_entries:
        return _reindex_subtitle_entries(canonical_entries)

    groups: list[list[SubtitleEntry]] = [[] for _entry in display_entries]
    for canonical_entry in canonical_entries:
        target_index = _best_display_boundary_target_index(canonical_entry, display_entries)
        if target_index is None:
            continue
        groups[target_index].append(canonical_entry)

    rebuilt: list[SubtitleEntry] = []
    for display_index, group in enumerate(groups):
        if not group:
            continue
        group = sorted(group, key=lambda entry: (float(entry.start), float(entry.end), int(entry.index)))
        text = _join_projection_entry_texts(group)
        if not text:
            continue
        words = tuple(word for entry in group for word in tuple(entry.words or ()))
        rebuilt.append(
            SubtitleEntry(
                index=display_index,
                start=float(group[0].start),
                end=float(group[-1].end),
                text_raw=text,
                text_norm=normalize_projection_display_text(text),
                words=words,
            )
        )
    return _merge_short_display_boundary_entries(
        _reindex_subtitle_entries(rebuilt),
        max_chars=int(split_profile.get("max_chars") or 30),
    )


def _best_display_boundary_target_index(
    canonical_entry: SubtitleEntry,
    display_entries: list[SubtitleEntry],
) -> int | None:
    if not display_entries:
        return None
    canonical_start = float(canonical_entry.start)
    canonical_end = float(canonical_entry.end)
    midpoint = (canonical_start + canonical_end) / 2.0
    containing = [
        (index, entry)
        for index, entry in enumerate(display_entries)
        if float(entry.start) - 1e-6 <= midpoint <= float(entry.end) + 1e-6
    ]
    if containing:
        return min(
            containing,
            key=lambda item: (
                float(item[1].end) - float(item[1].start),
                abs(((float(item[1].start) + float(item[1].end)) / 2.0) - midpoint),
            ),
        )[0]
    overlaps = [
        (
            max(0.0, min(canonical_end, float(entry.end)) - max(canonical_start, float(entry.start))),
            index,
            entry,
        )
        for index, entry in enumerate(display_entries)
    ]
    best_overlap, best_index, _best_entry = max(
        overlaps,
        key=lambda item: (
            item[0],
            -abs(((float(item[2].start) + float(item[2].end)) / 2.0) - midpoint),
        ),
    )
    if best_overlap > 0.0:
        return best_index
    return min(
        enumerate(display_entries),
        key=lambda item: abs(((float(item[1].start) + float(item[1].end)) / 2.0) - midpoint),
    )[0]


def _join_projection_entry_texts(entries: list[SubtitleEntry]) -> str:
    parts = [str(entry.text_norm or entry.text_raw or "").strip() for entry in list(entries or [])]
    parts = [part for part in parts if part]
    if not parts:
        return ""
    text = "".join(parts)
    return normalize_projection_display_text(text)


def _merge_short_display_boundary_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
) -> list[SubtitleEntry]:
    merged: list[SubtitleEntry] = []
    index = 0
    soft_limit = max(max_chars, int(max_chars * 1.8))
    while index < len(entries):
        current = entries[index]
        current_text = normalize_projection_display_text(current.text_norm or current.text_raw)
        if (
            _is_short_display_boundary_entry(current_text)
            and index + 1 < len(entries)
            and len(
                current_text
                + normalize_projection_display_text(entries[index + 1].text_norm or entries[index + 1].text_raw)
            )
            <= soft_limit
        ):
            merged.append(_merge_projection_entries(current, entries[index + 1], len(merged)))
            index += 2
            continue
        if (
            _is_short_display_boundary_entry(current_text)
            and merged
            and len(normalize_projection_display_text(merged[-1].text_norm or merged[-1].text_raw) + current_text)
            <= soft_limit
        ):
            merged[-1] = _merge_projection_entries(merged[-1], current, len(merged) - 1)
            index += 1
            continue
        merged.append(current)
        index += 1
    return _reindex_subtitle_entries(merged)


def _is_short_display_boundary_entry(text: str) -> bool:
    compact = re.sub(r"[，。！？；：,.!?;:\s]+", "", normalize_projection_display_text(text))
    return 0 < len(compact) <= 4


def _merge_projection_entries(left: SubtitleEntry, right: SubtitleEntry, index: int) -> SubtitleEntry:
    text = _join_projection_entry_texts([left, right])
    return SubtitleEntry(
        index=index,
        start=float(left.start),
        end=float(right.end),
        text_raw=text,
        text_norm=normalize_projection_display_text(text),
        words=tuple(left.words or ()) + tuple(right.words or ()),
    )


def _select_projection_candidate(
    *,
    candidates: list[dict[str, Any]],
    reference_items: list[Any],
    canonical_transcript_layer: Any,
    preferred_basis: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    correction_metrics = dict(getattr(canonical_transcript_layer, "correction_metrics", {}) or {})
    assessed_candidates: list[dict[str, Any]] = []
    for candidate in candidates:
        assessment = _build_projection_correction_assessment(
            basis=str(candidate.get("basis") or ""),
            reference_items=reference_items,
            candidate_items=list(candidate.get("items") or []),
            display_quality_report=dict(candidate.get("quality_report") or {}),
            segmentation_analysis=candidate.get("analysis"),
        )
        assessed_candidates.append({**candidate, "assessment": assessment})
    display_baseline_candidates = [
        candidate
        for candidate in assessed_candidates
        if str(candidate.get("basis") or "") == "display_baseline_preserved"
    ]
    canonical_refresh_candidates = [
        candidate
        for candidate in assessed_candidates
        if str(candidate.get("basis") or "") in {"canonical_refresh", "canonical_display_boundary_hybrid"}
        and str(candidate.get("transcript_layer") or "") == "canonical_transcript"
    ]
    if canonical_refresh_candidates and not display_baseline_candidates:
        assessed_candidates = canonical_refresh_candidates
    preferred_candidate = None
    if preferred_basis:
        preferred_candidate = next(
            (
                candidate
                for candidate in assessed_candidates
                if str(candidate.get("basis") or "") == preferred_basis
            ),
            None,
        )
    selected = preferred_candidate or max(
        assessed_candidates,
        key=lambda candidate: _projection_candidate_rank(candidate["assessment"]),
    )
    report = {
        "artifact_type": ARTIFACT_TYPE_TRANSCRIPT_CORRECTION_SCORE_REPORT,
        "score": selected["assessment"]["score"],
        "selected_projection_basis": selected.get("basis"),
        "selected_transcript_layer": selected.get("transcript_layer"),
        "blocking": bool(selected["assessment"].get("blocking")),
        "issue_codes": list(selected["assessment"].get("issue_codes") or []),
        "accepted_correction_count": int(correction_metrics.get("accepted_correction_count") or 0),
        "pending_correction_count": int(correction_metrics.get("pending_correction_count") or 0),
        "candidates": [candidate["assessment"] for candidate in assessed_candidates],
    }
    return selected, report


def _projection_candidate_rank(assessment: dict[str, Any]) -> tuple[float, int, int, int, int, int, float, float, int, int]:
    metrics = dict(assessment.get("metrics") or {})
    fragment_total = int(metrics.get("fragment_start_count") or 0) + int(metrics.get("fragment_end_count") or 0)
    return (
        float(assessment.get("content_fidelity_score") or 0.0),
        -int(metrics.get("missing_material_token_count") or 0),
        -int(metrics.get("unsupported_material_token_count") or 0),
        float(assessment.get("score") or 0.0),
        float(assessment.get("display_quality_score") or 0.0),
        float(assessment.get("segmentation_quality_score") or 0.0),
        -int(metrics.get("low_confidence_window_count") or 0),
        -int(metrics.get("suspicious_boundary_count") or 0),
        -fragment_total,
        -int(metrics.get("short_fragment_count") or 0),
        -int(metrics.get("subtitle_count") or 0),
    )


def _build_projection_correction_assessment(
    *,
    basis: str,
    reference_items: list[Any],
    candidate_items: list[Any],
    display_quality_report: dict[str, Any],
    segmentation_analysis: Any = None,
) -> dict[str, Any]:
    unsupported_boundary_slack = _projection_unsupported_boundary_slack(
        basis=basis,
        reference_items=reference_items,
        candidate_items=candidate_items,
    )
    missing_examples = _find_local_material_token_drift(reference_items, candidate_items)
    # Allow small local boundary shifts to reassign material tokens between adjacent rows
    # without treating the candidate as content drift. Missing tokens remain strict.
    unsupported_examples = _find_local_material_token_drift(
        candidate_items,
        reference_items,
        boundary_slack=unsupported_boundary_slack,
    )
    missing_count = len(missing_examples)
    unsupported_count = len(unsupported_examples)
    display_metrics = dict(display_quality_report.get("metrics") or {})
    segmentation_metrics = _projection_segmentation_analysis_metrics(segmentation_analysis)
    display_score = float(display_quality_report.get("score") or 0.0)
    content_score = max(0.0, round(100.0 - min(70.0, missing_count * 14.0) - min(30.0, unsupported_count * 6.0), 2))
    segmentation_score = max(
        0.0,
        round(
            100.0
            - min(36.0, float(segmentation_metrics.get("fragment_start_count") or 0) * 6.0)
            - min(36.0, float(segmentation_metrics.get("fragment_end_count") or 0) * 6.0)
            - min(18.0, float(segmentation_metrics.get("suspicious_boundary_count") or 0) * 6.0)
            - min(24.0, float(segmentation_metrics.get("low_confidence_window_count") or 0) * 8.0),
            2,
        ),
    )
    score = round(content_score * 0.62 + display_score * 0.2 + segmentation_score * 0.18, 2)
    issue_codes: list[str] = []
    if missing_count:
        issue_codes.append("projection_missing_material_tokens")
    if unsupported_count:
        issue_codes.append("projection_unsupported_material_tokens")
    return {
        "basis": basis,
        "score": score,
        "content_fidelity_score": content_score,
        "display_quality_score": round(display_score, 2),
        "segmentation_quality_score": segmentation_score,
        "blocking": bool(missing_count),
        "issue_codes": issue_codes,
        "metrics": {
            "subtitle_count": int(display_metrics.get("subtitle_count") or len(candidate_items)),
            "short_fragment_count": int(display_metrics.get("short_fragment_count") or 0),
            "generic_word_split_count": int(display_metrics.get("generic_word_split_count") or 0),
            "missing_material_token_count": missing_count,
            "unsupported_material_token_count": unsupported_count,
            "fragment_start_count": int(segmentation_metrics.get("fragment_start_count") or 0),
            "fragment_end_count": int(segmentation_metrics.get("fragment_end_count") or 0),
            "suspicious_boundary_count": int(segmentation_metrics.get("suspicious_boundary_count") or 0),
            "low_confidence_window_count": int(segmentation_metrics.get("low_confidence_window_count") or 0),
        },
        "missing_material_examples": missing_examples[:8],
        "unsupported_material_examples": unsupported_examples[:8],
    }


def _projection_unsupported_boundary_slack(
    *,
    basis: str,
    reference_items: list[Any],
    candidate_items: list[Any],
) -> float:
    if str(basis or "") == "canonical_local_hybrid" and _projection_items_have_moderate_shape_drift(
        reference_items,
        candidate_items,
    ):
        return 1.2
    return 0.45


def _projection_segmentation_analysis_metrics(analysis: Any) -> dict[str, int]:
    if hasattr(analysis, "as_dict"):
        analysis = analysis.as_dict()
    if not isinstance(analysis, dict):
        return {
            "fragment_start_count": 0,
            "fragment_end_count": 0,
            "suspicious_boundary_count": 0,
            "low_confidence_window_count": 0,
        }
    return {
        "fragment_start_count": int(analysis.get("fragment_start_count") or 0),
        "fragment_end_count": int(analysis.get("fragment_end_count") or 0),
        "suspicious_boundary_count": int(analysis.get("suspicious_boundary_count") or 0),
        "low_confidence_window_count": int(analysis.get("low_confidence_window_count") or 0),
    }


def _find_local_material_token_drift(
    reference_items: list[Any],
    candidate_items: list[Any],
    *,
    boundary_slack: float = 0.0,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for reference_item in list(reference_items or []):
        reference_text = _projection_item_text(reference_item)
        reference_tokens = _projection_material_tokens(reference_text)
        if not reference_tokens:
            continue
        candidate_text = _projection_overlapping_text(
            reference_item,
            candidate_items,
            boundary_slack=boundary_slack,
        )
        missing_tokens = [
            token
            for token in sorted(reference_tokens)
            if not _projection_text_supports_material_token(candidate_text, token)
        ]
        if not missing_tokens:
            continue
        examples.append(
            {
                "start": round(_projection_item_start(reference_item), 3),
                "end": round(_projection_item_end(reference_item), 3),
                "reference_text": reference_text,
                "candidate_text": candidate_text,
                "tokens": missing_tokens,
            }
        )
    return examples


def _projection_text_supports_material_token(text: str, token: str) -> bool:
    token_compact = _projection_compact_text(token)
    candidate_compact = _projection_compact_text(text)
    if token_compact and token_compact in candidate_compact:
        return True

    normalized_token = re.sub(r"\s+", "", normalize_projection_display_text(str(token or "")))
    numeric_match = _NUMERIC_UNIT_MATERIAL_TOKEN_RE.fullmatch(normalized_token)
    if not numeric_match:
        return False
    try:
        target_value = Decimal(str(numeric_match.group("number") or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return False
    unit = str(numeric_match.group("unit") or "")
    normalized_text = normalize_projection_display_text(str(text or ""))
    for unit_match in re.finditer(re.escape(unit), normalized_text, re.IGNORECASE):
        prefix = normalized_text[max(0, unit_match.start() - 32) : unit_match.start()]
        sequence_match = _NUMERIC_CHUNK_SEQUENCE_SUFFIX_RE.search(prefix)
        if not sequence_match:
            continue
        chunks = re.findall(r"\d+(?:\.\d+)?", sequence_match.group(1))
        if len(chunks) < 2:
            continue
        try:
            total = sum(Decimal(chunk) for chunk in chunks)
        except (InvalidOperation, TypeError, ValueError):
            continue
        if total == target_value:
            return True
    return False


def _projection_overlapping_text(
    reference_item: Any,
    candidate_items: list[Any],
    *,
    boundary_slack: float = 0.0,
) -> str:
    reference_start = _projection_item_start(reference_item) - max(0.0, boundary_slack)
    reference_end = _projection_item_end(reference_item) + max(0.0, boundary_slack)
    reference_duration = max(reference_end - reference_start, 0.001)
    overlapping: list[Any] = []
    for candidate_item in list(candidate_items or []):
        overlap = max(0.0, min(reference_end, _projection_item_end(candidate_item)) - max(reference_start, _projection_item_start(candidate_item)))
        if overlap / reference_duration >= 0.15:
            overlapping.append(candidate_item)
    if not overlapping:
        overlapping = [
            candidate_item
            for candidate_item in list(candidate_items or [])
            if max(0.0, min(reference_end, _projection_item_end(candidate_item)) - max(reference_start, _projection_item_start(candidate_item))) > 0.02
        ]
    return "\n".join(_projection_item_text(item) for item in overlapping if _projection_item_text(item))


def _projection_item_text(item: Any) -> str:
    return normalize_projection_display_text(_subtitle_surface_display_text(item))


def _projection_item_start(item: Any) -> float:
    return float(getattr(item, "start_time", getattr(item, "start", 0.0)) or 0.0)


def _projection_item_end(item: Any) -> float:
    return float(getattr(item, "end_time", getattr(item, "end", 0.0)) or 0.0)


def _projection_compact_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", normalize_projection_display_text(str(text or "")), flags=re.UNICODE).upper()


_MATERIAL_PROJECTION_TOKEN_RE = re.compile(
    r"(?:"
    r"\b(?:EDC|MT|UHD|FXX|S|PC)\s*\d+[A-Z]*\b"
    r"|\b(?:NITECORE|OLIGHT|NOC|EXO|FAS|UV|LED)\b"
    r"|奈特科尔"
    r"|\d+(?:\.\d+)?(?:毫安|流明|档|挡|米|克|分钟|秒钟?|小时|瓦|W|mAh|lm)"
    r")",
    re.IGNORECASE,
)

_NUMERIC_UNIT_MATERIAL_TOKEN_RE = re.compile(
    r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>毫安|流明|档|挡|米|克|分钟|秒钟?|小时|瓦|W|mAh|lm)$",
    re.IGNORECASE,
)

_NUMERIC_CHUNK_SEQUENCE_SUFFIX_RE = re.compile(
    r"(\d+(?:\.\d+)?(?:[^\dA-Za-z\u4e00-\u9fff]{0,4}\d+(?:\.\d+)?)+)\s*$",
    re.IGNORECASE,
)


def _projection_has_material_content_drift(*, baseline_items: list[Any], candidate_items: list[Any]) -> bool:
    if not baseline_items or not candidate_items:
        return False
    baseline_text = _projection_material_text(baseline_items)
    candidate_text = _projection_material_text(candidate_items)
    if not baseline_text or not candidate_text:
        return False
    candidate_item_texts = [
        normalize_projection_display_text(_subtitle_surface_display_text(item))
        for item in list(candidate_items or [])
    ]
    for token in _projection_split_ascii_model_tokens(candidate_item_texts):
        if _projection_text_supports_material_token(baseline_text, token):
            return True
    candidate_tokens = _projection_material_tokens(candidate_text)
    if not candidate_tokens:
        return False
    for token in candidate_tokens:
        if not _projection_text_supports_material_token(baseline_text, token):
            return True
    baseline_tokens = _projection_material_tokens(baseline_text)
    for token in baseline_tokens:
        if not _projection_text_supports_material_token(candidate_text, token):
            continue
        if not any(_projection_text_supports_material_token(text, token) for text in candidate_item_texts):
            return True
    return False


def _projection_split_ascii_model_tokens(candidate_item_texts: list[str]) -> set[str]:
    tokens: set[str] = set()
    compact_items = [_projection_compact_text(text) for text in candidate_item_texts]
    for left, right in zip(compact_items, compact_items[1:]):
        left_match = re.search(r"([A-Z]{2,})$", left)
        right_match = re.match(r"(\d+[A-Z]*)", right)
        if not left_match or not right_match:
            continue
        token = f"{left_match.group(1)}{right_match.group(1)}"
        if _MATERIAL_PROJECTION_TOKEN_RE.fullmatch(token):
            tokens.add(token)
    return tokens


def _projection_material_text(items: list[Any]) -> str:
    parts: list[str] = []
    for item in list(items or []):
        text = _subtitle_surface_display_text(item)
        if text.strip():
            parts.append(normalize_projection_display_text(text))
    return "\n".join(parts)


def _projection_material_tokens(text: str) -> set[str]:
    normalized = normalize_projection_display_text(str(text or ""))
    return {
        match.group(0).strip()
        for match in _MATERIAL_PROJECTION_TOKEN_RE.finditer(normalized)
        if match.group(0).strip()
    }


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
    correction_score_report: dict[str, Any],
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
                    ARTIFACT_TYPE_TRANSCRIPT_CORRECTION_SCORE_REPORT,
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
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_TRANSCRIPT_CORRECTION_SCORE_REPORT,
            data_json=correction_score_report,
        )
    )


async def _persist_projection_layer_to_subtitle_items(
    session,
    *,
    job_id: uuid.UUID,
    refreshed_projection_layer: Any,
    version: int = 1,
) -> int:
    entries = list(getattr(refreshed_projection_layer, "entries", ()) or ())
    if not entries:
        return 0
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.version == version))
    persisted_count = 0
    for index, entry in enumerate(entries):
        payload = _subtitle_surface_payload(entry)
        text_raw = subtitle_raw_explicit_text(payload)
        text_norm = subtitle_canonical_explicit_text(payload)
        if not text_norm and text_raw:
            text_norm = normalize_projection_display_text(text_raw)
        text_final = _subtitle_surface_display_text(payload)
        if not text_final.strip():
            continue
        session.add(
            SubtitleItem(
                job_id=job_id,
                version=version,
                item_index=persisted_count,
                start_time=float(getattr(entry, "start", 0.0) or 0.0),
                end_time=float(getattr(entry, "end", 0.0) or 0.0),
                text_raw=text_raw,
                text_norm=normalize_projection_display_text(text_norm),
                text_final=normalize_projection_display_text(text_final),
            )
        )
        persisted_count += 1
    await session.flush()
    return persisted_count


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
        "projection_basis": getattr(refreshed_projection_layer, "projection_basis", ""),
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
            current_text = subtitle_display_rule_text(
                {
                    "text_raw": str(getattr(subtitle_item, "text_raw", "") or ""),
                    "text_norm": str(getattr(subtitle_item, "text_norm", "") or ""),
                    "text_final": str(getattr(subtitle_item, "text_final", "") or ""),
                    "display_suppressed_reason": str(
                        getattr(subtitle_item, "display_suppressed_reason", "") or ""
                    ),
                }
            )
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
    for index, transcript_row in enumerate(transcript_rows_ordered):
        segment_index = int(getattr(transcript_row, "segment_index", index) or index)
        synthetic_id = synthetic_ids[segment_index]
        transcript_payload = _transcript_segment_surface_payload(transcript_row)
        transcript_text = str(transcript_payload.get("text") or "")
        surfaces = subtitle_surface_item_dict(
            transcript_payload,
            generic_fallback_text=str(transcript_text or transcript_payload.get("text_raw") or ""),
        )
        raw_text = str(surfaces["text_raw"] or transcript_text or "")
        canonical_text = str(surfaces["text_norm"] or raw_text)
        display_text = str(surfaces["text_final"] or canonical_text)
        if str(category_scope or "").strip().lower() == "flashlight":
            raw_text = normalize_flashlight_model_alias_text(raw_text)
            canonical_text = normalize_flashlight_model_alias_text(canonical_text)
            if display_text:
                display_text = normalize_flashlight_model_alias_text(display_text)
        synthetic_items.append(
            SimpleNamespace(
                id=synthetic_id,
                item_index=segment_index,
                start_time=float(getattr(transcript_row, "start_time", 0.0) or 0.0),
                end_time=float(getattr(transcript_row, "end_time", 0.0) or 0.0),
                text_raw=raw_text,
                text_norm=canonical_text,
                text_final=display_text,
                display_suppressed_reason=transcript_payload.get("display_suppressed_reason"),
            )
        )

    subtitle_by_id = {
        str(getattr(item, "id", "") or ""): item
        for item in list(subtitle_items or [])
        if getattr(item, "id", None) is not None
    }
    seen_synthetic_correction_keys: set[tuple[str, str, str]] = set()
    for correction in list(corrections or []):
        original = str(_subtitle_correction_attr(correction, "original_span") or "").strip()
        accepted = str(
            _subtitle_correction_attr(correction, "human_override")
            or _subtitle_correction_attr(correction, "suggested_span")
            or ""
        ).strip()
        if not original or not accepted or original == accepted:
            continue
        subtitle_item_id = str(_subtitle_correction_attr(correction, "subtitle_item_id") or "").strip()
        subtitle_item = subtitle_by_id.get(subtitle_item_id)
        target_rows = _select_transcript_segments_for_correction(
            correction_payload={"original": original, "accepted": accepted},
            subtitle_item=subtitle_item,
            transcript_rows=transcript_rows_ordered,
        )
        for target_row in target_rows[:1]:
            segment_index = int(getattr(target_row, "segment_index", 0) or 0)
            synthetic_id = synthetic_ids.get(segment_index)
            if not synthetic_id:
                continue
            correction_key = (synthetic_id, original, accepted)
            if correction_key in seen_synthetic_correction_keys:
                continue
            seen_synthetic_correction_keys.add(correction_key)
            synthetic_corrections.append(
                {
                    "subtitle_item_id": synthetic_id,
                    "original_span": original,
                    "suggested_span": str(_subtitle_correction_attr(correction, "suggested_span") or accepted),
                    "human_override": str(_subtitle_correction_attr(correction, "human_override") or "").strip() or None,
                    "human_decision": _subtitle_correction_attr(correction, "human_decision"),
                    "auto_applied": bool(_subtitle_correction_attr(correction, "auto_applied")),
                    "change_type": _subtitle_correction_attr(correction, "change_type"),
                    "confidence": _subtitle_correction_attr(correction, "confidence"),
                    "source": _subtitle_correction_attr(correction, "source"),
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
    split_profile = (
        dict((projection_data or {}).get("split_profile") or {})
        if subtitle_projection_data_is_current(projection_data)
        else {}
    )
    if split_profile:
        return split_profile
    media_meta = media_meta_json or {}
    return _resolve_subtitle_split_profile(
        width=media_meta.get("width"),
        height=media_meta.get("height"),
    )


_CANONICAL_WORD_MIN_KEEP_OVERLAP_RATIO = 0.35
_CANONICAL_WORD_MIN_KEEP_OVERLAP_SEC = 0.035
_CANONICAL_COLLAPSED_TIMING_MIN_UNITS = 14
_CANONICAL_COLLAPSED_TIMING_MAX_WINDOW_SEC = 0.9


def _build_fallback_canonical_words(segment: dict[str, Any]) -> list[dict[str, Any]]:
    text = subtitle_semantic_item_text(
        segment,
        generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
    )
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


def _projected_word_compact_length(text: str) -> int:
    return len(re.sub(r"\s+", "", str(text or "").strip()))


def _projected_word_time_bounds(word: dict[str, Any]) -> tuple[float, float]:
    try:
        start = float(word.get("start", 0.0) or 0.0)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = float(word.get("end", start) or start)
    except (TypeError, ValueError):
        end = start
    return start, max(start, end)


def _canonical_segment_words_have_collapsed_timing(
    words: list[dict[str, Any]],
    *,
    split_profile: dict[str, Any],
) -> bool:
    timed_words: list[tuple[float, float, int]] = []
    for word in list(words or []):
        text_units = _projected_word_compact_length(str(word.get("word") or ""))
        if text_units <= 0:
            continue
        start, end = _projected_word_time_bounds(word)
        if end <= start:
            continue
        timed_words.append((start, end, text_units))
    if len(timed_words) < 4:
        return False

    timed_words.sort(key=lambda item: (item[0], item[1]))
    max_chars = int(split_profile.get("max_chars") or 30)
    min_units = max(
        _CANONICAL_COLLAPSED_TIMING_MIN_UNITS,
        int(max_chars * 0.55),
    )

    for start_index, (window_start, _window_end, _units) in enumerate(timed_words):
        total_units = 0
        for end_index in range(start_index, len(timed_words)):
            total_units += timed_words[end_index][2]
            if total_units < min_units:
                continue
            window_duration = max(0.0, timed_words[end_index][1] - window_start)
            if window_duration <= _CANONICAL_COLLAPSED_TIMING_MAX_WINDOW_SEC:
                return True
            break
    return False


def _projected_word_needs_forced_split(
    word: dict[str, Any],
    *,
    max_chars: int,
    max_duration: float,
) -> bool:
    text = str(word.get("word") or "").strip()
    if not text:
        return False
    compact_len = _projected_word_compact_length(text)
    if compact_len <= 1:
        return False
    start, end = _projected_word_time_bounds(word)
    duration = max(0.0, end - start)
    hard_char_limit = max(max_chars + 4, 24)
    hard_duration_limit = max(float(max_duration) + 2.0, 7.0)
    return compact_len > hard_char_limit or (
        duration > hard_duration_limit and compact_len > max(8, int(max_chars * 0.35))
    )


def _split_overlong_projected_word(
    word: dict[str, Any],
    *,
    max_chars: int,
    max_duration: float,
) -> list[dict[str, Any]]:
    text = str(word.get("word") or "").strip()
    if not _projected_word_needs_forced_split(word, max_chars=max_chars, max_duration=max_duration):
        return [word]
    tokens = tokenize_alignment_text(text)
    if len(tokens) <= 1:
        return [word]

    start, end = _projected_word_time_bounds(word)
    duration = max(0.0, end - start)
    weights = [max(0.5, float(_projected_word_compact_length(token))) for token in tokens]
    total_weight = sum(weights) or float(len(tokens))
    cursor = start
    try:
        base_word_index = int(word.get("word_index", 0) or 0)
    except (TypeError, ValueError):
        base_word_index = 0
    split_words: list[dict[str, Any]] = []
    for token_index, (token, weight) in enumerate(zip(tokens, weights)):
        token_end = end if token_index == len(tokens) - 1 else cursor + duration * weight / total_weight
        alignment = dict(word.get("alignment") or {})
        alignment["projection_split"] = {
            "source": "overlong_canonical_word",
            "token_index": token_index,
            "token_count": len(tokens),
        }
        split_words.append(
            {
                **word,
                "word": token,
                "start": round(cursor, 3),
                "end": round(max(cursor, token_end), 3),
                "word_index": base_word_index * 1000 + token_index,
                "alignment": alignment,
            }
        )
        cursor = token_end
    return split_words


def _normalize_projected_words_for_segmentation(
    projected_words: list[dict[str, Any]],
    *,
    split_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    max_chars = int(split_profile.get("max_chars") or 30)
    max_duration = float(split_profile.get("max_duration") or 5.0)
    normalized: list[dict[str, Any]] = []
    for word in projected_words:
        normalized.extend(
            _split_overlong_projected_word(
                word,
                max_chars=max_chars,
                max_duration=max_duration,
            )
        )
    return normalized


_CANONICAL_SYNTHETIC_BOUNDARY_PUNCTUATION = "。.!！？"


def _strip_synthetic_canonical_boundary_punctuation(
    entries: list[dict[str, Any]],
    *,
    source_text: str,
) -> list[dict[str, Any]]:
    if len(entries) < 2 or not source_text:
        return entries
    source_compact = re.sub(r"\s+", "", str(source_text or ""))
    if not source_compact:
        return entries

    def boundary_text(value: Any) -> str:
        return re.sub(r"\s+", "", normalize_projection_display_text(str(value or "")))

    def should_strip(left_text: str, right_text: str) -> bool:
        left = boundary_text(left_text)
        right = boundary_text(right_text)
        if not left or not right or left[-1] not in _CANONICAL_SYNTHETIC_BOUNDARY_PUNCTUATION:
            return False
        left_core = left.rstrip(_CANONICAL_SYNTHETIC_BOUNDARY_PUNCTUATION)
        if not left_core:
            return False
        punctuation_pattern = r"[，,。.!！？；;：:、…]+"
        tail_source = re.sub(punctuation_pattern, "", left_core)
        head = re.sub(punctuation_pattern, "", right)[:4]
        tail = tail_source[-8:]
        if not tail or not head:
            return False
        for tail_length in range(len(tail), max(1, min(3, len(tail))) - 1, -1):
            tail_candidate = tail[-tail_length:]
            search_from = 0
            while True:
                position = source_compact.find(tail_candidate, search_from)
                if position < 0:
                    break
                after_tail = source_compact[position + len(tail_candidate):]
                if after_tail and after_tail[0] in "，,。.!！？；;：:、…":
                    return False
                after_significant = re.sub(punctuation_pattern, "", after_tail)
                if after_significant.startswith(head):
                    return True
                search_from = position + 1
        return False

    cleaned: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        current = dict(entry)
        if index + 1 < len(entries):
            next_entry = entries[index + 1]
            if should_strip(current.get("text_final"), next_entry.get("text_final")):
                for key in ("text_raw", "text_norm", "text_final"):
                    value = str(current.get(key) or "")
                    current[key] = value.rstrip().rstrip(_CANONICAL_SYNTHETIC_BOUNDARY_PUNCTUATION)
        cleaned.append(current)
    return cleaned


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
    canonical_source_text_parts: list[str] = []
    for segment_index, segment in enumerate(canonical_segments):
        segment_text = str(segment.get("text") or "").strip()
        if segment_text:
            canonical_source_text_parts.append(segment_text)
        segment_words = [
            dict(word)
            for word in list(segment.get("words") or [])
            if isinstance(word, dict) and str(word.get("word") or "").strip()
        ]
        if segment_words and _canonical_segment_words_have_collapsed_timing(
            segment_words,
            split_profile=split_profile,
        ):
            segment_words = _build_fallback_canonical_words(segment)
        elif not segment_words:
            segment_words = _build_fallback_canonical_words(segment)
        for word_index, word in enumerate(segment_words):
            word.setdefault("word_index", word_index)
        segment_words = _normalize_projected_words_for_segmentation(segment_words, split_profile=split_profile)
        for word_index, word in enumerate(segment_words):
            raw_start = float(word.get("start", segment.get("start", 0.0)) or 0.0)
            raw_end = float(word.get("end", raw_start) or raw_start)
            if raw_end <= raw_start:
                continue
            raw_duration = max(0.001, raw_end - raw_start)
            for keep in keep_map:
                overlap_start = max(raw_start, keep["in_start"])
                overlap_end = min(raw_end, keep["in_end"])
                overlap_sec = overlap_end - overlap_start
                if overlap_sec <= max(0.001, _CANONICAL_WORD_MIN_KEEP_OVERLAP_SEC):
                    continue
                overlap_ratio = overlap_sec / raw_duration
                if overlap_ratio < _CANONICAL_WORD_MIN_KEEP_OVERLAP_RATIO:
                    continue
                projected_words.append(
                    {
                        "word": str(word.get("word") or "").strip(),
                        "start": round(keep["out_start"] + (overlap_start - keep["in_start"]), 3),
                        "end": round(keep["out_start"] + (overlap_end - keep["in_start"]), 3),
                        "alignment": dict(word.get("alignment") or {}),
                        "source_start": round(raw_start, 3),
                        "source_end": round(raw_end, 3),
                        "source_keep_overlap_ratio": round(overlap_ratio, 4),
                        "segment_index": segment_index,
                        "word_index": int(word.get("word_index", word_index) or word_index),
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
    projected_words = _normalize_projected_words_for_segmentation(projected_words, split_profile=split_profile)
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
        text_raw = str(getattr(entry, "text_raw", "") or "")
        text_norm = str(getattr(entry, "text_norm", "") or "")
        display_text = normalize_projection_display_text(text_norm or text_raw)
        projected_entries.append(
            {
                "index": int(getattr(entry, "index", len(projected_entries)) or len(projected_entries)),
                "start_time": float(getattr(entry, "start", 0.0) or 0.0),
                "end_time": float(getattr(entry, "end", 0.0) or 0.0),
                "text_raw": text_raw,
                "text_norm": normalize_projection_display_text(text_norm or text_raw),
                "text_final": display_text,
                "projection_source": "canonical_transcript",
            }
        )
    return _strip_synthetic_canonical_boundary_punctuation(
        projected_entries,
        source_text="".join(canonical_source_text_parts) or projected_text,
    )


def _projection_has_suspicious_subtitle_timing(
    entries: list[dict[str, Any]],
    *,
    split_profile: dict[str, Any],
) -> bool:
    if subtitle_items_have_output_fallback_alignment(entries):
        return True
    max_chars = int(split_profile.get("max_chars") or 30)
    max_duration = float(split_profile.get("max_duration") or 5.0)
    duration_limit = max(8.0, max_duration * 1.6)
    compact_limit = max(8, int(max_chars * 0.45))
    for entry in entries:
        try:
            start = float(entry.get("start_time", entry.get("start", 0.0)) or 0.0)
            end = float(entry.get("end_time", entry.get("end", start)) or start)
        except (TypeError, ValueError):
            continue
        duration = max(0.0, end - start)
        text = subtitle_surface_item_dict(entry, generic_fallback_text=str(entry.get("text") or ""))["text_final"]
        if not text.strip():
            continue
        compact_len = len(re.sub(r"[\s，。！？!?；;：:,、（）()[]【】{}\"'《》<>]+", "", text))
        if duration > duration_limit and compact_len <= compact_limit:
            return True
    return False


async def _build_edited_subtitle_projection(
    session,
    *,
    job_id: uuid.UUID,
    keep_segments: list[dict[str, Any]],
    projection_data: dict[str, Any] | None,
    fallback_subtitles: list[dict[str, Any]],
    prefer_source_subtitles: bool = False,
) -> list[dict[str, Any]]:
    if prefer_source_subtitles:
        return remap_subtitles_to_timeline(fallback_subtitles, keep_segments)
    projection_payload = projection_data if isinstance(projection_data, dict) else {}
    transcript_layer = str(projection_payload.get("transcript_layer") or "").strip() or "subtitle_projection"
    projection_entries = [
        {
            **_subtitle_projection_entry_payload(entry),
            "projection_source": str(entry.get("projection_source") or transcript_layer),
        }
        for entry in list(projection_payload.get("entries") or [])
        if isinstance(entry, dict)
    ]
    cleaned_projection_entries = preserve_subtitle_payloads(projection_entries, drop_empty=True)
    split_profile = (
        projection_payload.get("split_profile")
        if isinstance(projection_payload.get("split_profile"), dict)
        else {}
    )
    if cleaned_projection_entries and not _projection_has_suspicious_subtitle_timing(
        cleaned_projection_entries,
        split_profile=split_profile,
    ):
        return remap_subtitles_to_timeline(cleaned_projection_entries, keep_segments)
    return remap_subtitles_to_timeline(fallback_subtitles, keep_segments)


def _manual_editor_subtitle_items_from_editorial(editorial_timeline: dict[str, Any] | None) -> list[dict[str, Any]]:
    subtitle_projection = editorial_timeline_subtitle_projection(editorial_timeline)
    if not subtitle_projection:
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(list(subtitle_projection.get("items") or [])):
        if not isinstance(item, dict):
            continue
        start_time = max(0.0, float(item.get("start_time", item.get("start", 0.0)) or 0.0))
        end_time = max(start_time, float(item.get("end_time", item.get("end", start_time)) or start_time))
        if end_time <= start_time:
            continue
        text_final = subtitle_display_rule_text(item)
        text_raw = subtitle_raw_explicit_text(item)
        text_norm = subtitle_canonical_explicit_text(item)
        payload = dict(item)
        payload.pop("start", None)
        payload.pop("end", None)
        items.append(
            {
                **payload,
                "index": int(item.get("index", index) or index),
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "text_raw": text_raw,
                "text_norm": text_norm,
                "text_final": text_final,
            }
        )
    split_profile = subtitle_projection.get("split_profile") if isinstance(subtitle_projection.get("split_profile"), dict) else {}
    if _projection_has_suspicious_subtitle_timing(items, split_profile=split_profile):
        return []
    return items


def _subtitle_item_payload(item: SubtitleItem) -> dict[str, Any]:
    return {
        "index": item.item_index,
        "start_time": item.start_time,
        "end_time": item.end_time,
        "text_raw": item.text_raw,
        "text_norm": item.text_norm,
        "text_final": item.text_final,
        "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
        "projection_source": "subtitle_item",
    }


def _subtitle_projection_entry_payload(entry: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "index": int(entry.get("index", 0) or 0),
        "start_time": entry.get("start_time", entry.get("start")),
        "end_time": entry.get("end_time", entry.get("end")),
        "text_raw": entry.get("text_raw"),
        "text_norm": entry.get("text_norm"),
        "text_final": entry.get("text_final"),
        "display_suppressed_reason": entry.get("display_suppressed_reason"),
        "projection_source": entry.get("projection_source"),
    }
    words = drop_redundant_synthetic_word_payloads(list(entry.get("words") or entry.get("words_json") or []))
    if words:
        payload["words"] = words
    return payload


async def _load_latest_subtitle_projection_entries(
    session,
    *,
    job_id: uuid.UUID,
    fallback_items: list[SubtitleItem] | None = None,
    projection_entry_payload: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    projection_artifact_slot: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    projection_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_SUBTITLE_PROJECTION_LAYER,),
    )
    if projection_artifact_slot is not None:
        projection_artifact_slot["projection_artifact"] = projection_artifact
    projection_data = projection_artifact.data_json if projection_artifact and isinstance(projection_artifact.data_json, dict) else {}
    entry_payload = _subtitle_projection_entry_payload if projection_entry_payload is None else projection_entry_payload
    projection_entries = [
        entry_payload(entry)
        for entry in list(projection_data.get("entries") or [])
        if isinstance(entry, dict)
    ]
    if projection_entries:
        return projection_entries, projection_data
    return [_subtitle_item_payload(item) for item in list(fallback_items or [])], {}


def _canonical_transcript_layer_namespace(canonical_layer: dict[str, Any] | None) -> SimpleNamespace:
    raw_segments = list((canonical_layer or {}).get("segments") or [])
    segments: list[SimpleNamespace] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            continue
        words = []
        for raw_word in list(segment.get("words") or []):
            if not isinstance(raw_word, dict):
                continue
            word = str(raw_word.get("word") or "").strip()
            if not word:
                continue
            words.append(
                SimpleNamespace(
                    word=word,
                    start=float(raw_word.get("start", 0.0) or 0.0),
                    end=float(raw_word.get("end", 0.0) or 0.0),
                    alignment=dict(raw_word.get("alignment") or {}),
                )
            )
        surfaces = subtitle_surface_item_dict(
            segment,
            generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
        )
        segments.append(
            SimpleNamespace(
                index=int(segment.get("index", index) or index),
                start=float(segment.get("start", segment.get("start_time", 0.0)) or 0.0),
                end=float(segment.get("end", segment.get("end_time", 0.0)) or 0.0),
                text_raw=surfaces["text_raw"] or surfaces["text_norm"],
                text_norm=surfaces["text_norm"],
                text_canonical=surfaces["text_norm"],
                text_final=surfaces["text_final"],
                display_suppressed_reason=str(segment.get("display_suppressed_reason") or "").strip() or None,
                accepted_corrections=tuple(segment.get("accepted_corrections") or ()),
                pending_corrections=tuple(segment.get("pending_corrections") or ()),
                words=tuple(words),
            )
        )
    return SimpleNamespace(
        segments=tuple(segments),
        source_basis=str((canonical_layer or {}).get("source_basis") or "canonical_transcript"),
        correction_metrics=dict((canonical_layer or {}).get("correction_metrics") or {}),
        alignment_engine_version=str((canonical_layer or {}).get("alignment_engine_version") or ""),
    )


async def _rebuild_current_subtitle_projection_entries(
    session,
    *,
    job_id: uuid.UUID,
    projection_data: dict[str, Any] | None,
    drop_empty: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canonical_layer = await _load_latest_current_canonical_transcript_data(
        session,
        job_id=job_id,
    )
    if not list(canonical_layer.get("segments") or []):
        return [], dict(projection_data or {})
    subtitle_items = await _load_subtitle_items(session, job_id=job_id)
    if not subtitle_items:
        return [], dict(projection_data or {})
    job_source_result = await session.execute(select(Job.source_name).where(Job.id == job_id))
    source_name = str(job_source_result.scalar_one_or_none() or "")
    refreshed_projection_layer, _subtitle_quality_report, _correction_score_report = await _build_canonical_refresh_projection(
        session,
        job_id=job_id,
        source_name=source_name,
        subtitle_items=subtitle_items,
        canonical_transcript_layer=_canonical_transcript_layer_namespace(canonical_layer),
        projection_data=projection_data,
    )
    refreshed_projection_data = (
        refreshed_projection_layer.as_dict() if hasattr(refreshed_projection_layer, "as_dict") else {}
    )
    refreshed_entries = [
        _subtitle_projection_entry_payload(entry)
        for entry in list(refreshed_projection_data.get("entries") or [])
        if isinstance(entry, dict)
    ]
    return preserve_subtitle_payloads(refreshed_entries, drop_empty=drop_empty), refreshed_projection_data


async def _load_latest_current_canonical_transcript_data(
    session,
    *,
    job_id: uuid.UUID,
) -> dict[str, Any]:
    canonical_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_CANONICAL_TRANSCRIPT_LAYER,),
    )
    canonical_layer = (
        canonical_artifact.data_json
        if canonical_artifact is not None and isinstance(canonical_artifact.data_json, dict)
        else {}
    )
    if list(canonical_layer.get("segments") or []) and canonical_transcript_data_is_current(canonical_layer):
        return dict(canonical_layer)

    subtitle_items = await _load_subtitle_items(session, job_id=job_id)
    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id, TranscriptSegment.version == 1)
        .order_by(TranscriptSegment.segment_index)
    )
    transcript_rows = list(transcript_result.scalars().all())
    sanitize_transcript_segment_word_rows(transcript_rows)
    corrections = await _load_subtitle_corrections(session, job_id=job_id)
    job = await session.get(Job, job_id)
    content_profile = await _load_current_content_profile(session, job_id=job_id)
    subtitle_dicts = [
        {
            "text_raw": item.text_raw,
            "text_norm": item.text_norm,
            "text_final": item.text_final,
            "display_suppressed_reason": getattr(item, "display_suppressed_reason", None),
        }
        for item in subtitle_items
    ]
    subject_domain = _infer_subject_domain_for_memory(
        workflow_template=getattr(job, "workflow_template", None),
        subtitle_items=subtitle_dicts,
        content_profile=content_profile or {},
        source_name=getattr(job, "source_name", None),
    )
    category_scope = _resolve_subtitle_semantic_cleanup_scope(
        job=job,
        content_profile=content_profile,
        review_memory={"terms": [{"category_scope": subject_domain or ""}]},
    )
    rebuilt_layer = _build_transcript_first_canonical_layer(
        transcript_rows=transcript_rows,
        subtitle_items=subtitle_items,
        corrections=corrections,
        category_scope=category_scope,
    )
    return rebuilt_layer.as_dict() if hasattr(rebuilt_layer, "as_dict") else {}


async def _load_latest_subtitle_payloads(
    session,
    *,
    job_id: uuid.UUID,
    fallback_to_items: bool = True,
    drop_empty: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    subtitle_dicts, projection_data = await _load_latest_subtitle_projection_entries(
        session,
        job_id=job_id,
        fallback_items=None,
    )
    projection_is_current = subtitle_projection_data_is_current(projection_data)
    projection_rebuild_rejected = False
    if subtitle_dicts:
        if not projection_is_current:
            rebuilt_subtitles, rebuilt_projection_data = await _rebuild_current_subtitle_projection_entries(
                session,
                job_id=job_id,
                projection_data=projection_data,
                drop_empty=drop_empty,
            )
            if rebuilt_subtitles:
                rebuilt_split_profile = (
                    rebuilt_projection_data.get("split_profile")
                    if isinstance(rebuilt_projection_data.get("split_profile"), dict)
                    else {}
                )
                if not fallback_to_items or not _projection_has_suspicious_subtitle_timing(
                    rebuilt_subtitles,
                    split_profile=rebuilt_split_profile,
                ):
                    return rebuilt_subtitles, rebuilt_projection_data
                projection_rebuild_rejected = True
            else:
                projection_rebuild_rejected = True
        cleaned_subtitles = preserve_subtitle_payloads(subtitle_dicts, drop_empty=drop_empty)
        split_profile = projection_data.get("split_profile") if isinstance(projection_data.get("split_profile"), dict) else {}
        if (
            not projection_rebuild_rejected
            and (
                not fallback_to_items
                or not _projection_has_suspicious_subtitle_timing(
                    cleaned_subtitles,
                    split_profile=split_profile,
                )
            )
        ):
            return cleaned_subtitles, projection_data
    elif not fallback_to_items:
        return [], projection_data
    subtitle_items = await _load_subtitle_items(session, job_id=job_id) if fallback_to_items else []
    if subtitle_items:
        subtitle_item_projection_data = {
            **dict(projection_data or {}),
            "projection_kind": "subtitle_item_baseline",
            "transcript_layer": "subtitle_item",
        }
        return (
            preserve_subtitle_payloads([_subtitle_item_payload(item) for item in subtitle_items], drop_empty=drop_empty),
            subtitle_item_projection_data,
        )
    return preserve_subtitle_payloads([_subtitle_item_payload(item) for item in subtitle_items], drop_empty=drop_empty), {}


async def _load_subtitle_items(session, *, job_id: uuid.UUID) -> list[SubtitleItem]:
    item_result = await session.execute(
        select(SubtitleItem)
        .where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1)
        .order_by(SubtitleItem.item_index)
    )
    return list(item_result.scalars().all())


async def _load_source_subtitle_payloads_for_projection_validation(
    session,
    *,
    job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    canonical_layer = await _load_latest_current_canonical_transcript_data(
        session,
        job_id=job_id,
    )
    canonical_segments = [
        segment
        for segment in list(canonical_layer.get("segments") or [])
        if isinstance(segment, dict)
    ]
    if canonical_segments:
        return clean_subtitle_payloads(
            [
                {
                    **{
                        "index": int(segment.get("index", index) or index),
                        "source_index": int(segment.get("index", index) or index),
                        "source_indexes": [int(segment.get("index", index) or index)],
                        "start_time": float(segment.get("start", segment.get("start_time", 0.0)) or 0.0),
                        "end_time": float(segment.get("end", segment.get("end_time", 0.0)) or 0.0),
                        "words": [dict(word) for word in list(segment.get("words") or []) if isinstance(word, dict)],
                        "projection_source": "canonical_transcript",
                    },
                    **(
                        lambda surfaces: {
                            "text_raw": surfaces["text_raw"],
                            "text_norm": surfaces["text_norm"],
                            "transcript_text": surfaces["text_raw"] or surfaces["text_norm"],
                            "display_suppressed_reason": segment.get("display_suppressed_reason"),
                        }
                    )(
                        subtitle_surface_item_dict(
                            segment,
                            generic_fallback_text=str(segment.get("text") or segment.get("text_raw") or ""),
                        )
                    ),
                }
                for index, segment in enumerate(canonical_segments)
            ],
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
        )
    transcript_result = await session.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.job_id == job_id)
        .order_by(TranscriptSegment.version.desc(), TranscriptSegment.segment_index.asc())
    )
    transcript_rows = transcript_result.scalars().all()
    if transcript_rows:
        sanitize_transcript_segment_word_rows(transcript_rows)
        latest_version = max(int(row.version or 1) for row in transcript_rows)
        transcript_payloads = [
            {
                "index": int(row.segment_index if row.segment_index is not None else index),
                "source_index": int(row.segment_index if row.segment_index is not None else index),
                "source_indexes": [int(row.segment_index if row.segment_index is not None else index)],
                "start_time": float(row.start_time),
                "end_time": float(row.end_time),
                "text_raw": str(row.text or ""),
                "text_norm": str(row.text or ""),
                "transcript_text": str(row.text or ""),
                "display_suppressed_reason": getattr(row, "display_suppressed_reason", None),
                "words": drop_redundant_synthetic_word_payloads([dict(word) for word in list(row.words_json or []) if isinstance(word, dict)]),
                "projection_source": "transcript_segment",
            }
            for index, row in enumerate(transcript_rows)
            if int(row.version or 1) == latest_version
        ]
        if transcript_payloads:
            return clean_subtitle_payloads(
                transcript_payloads,
                drop_empty=False,
                collapse_repeats=False,
                clean_text=False,
            )
    return clean_subtitle_payloads(
        [_subtitle_item_payload(item) for item in await _load_subtitle_items(session, job_id=job_id)],
        drop_empty=False,
        collapse_repeats=False,
        clean_text=False,
    )


async def _load_edit_plan_source_subtitles(
    session,
    *,
    job: Job,
) -> list[dict[str, Any]]:
    from roughcut.api.jobs import _load_manual_editor_aligned_source_subtitle_dicts

    try:
        aligned_rows = await _load_manual_editor_aligned_source_subtitle_dicts(
            session,
            job=job,
            clean_text=False,
        )
    except Exception:
        logger.exception("Failed to load aligned source subtitles for edit plan job=%s", job.id)
        aligned_rows = []
    if aligned_rows:
        return clean_subtitle_payloads(
            aligned_rows,
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
        )
    return await _load_source_subtitle_payloads_for_projection_validation(session, job_id=job.id)


def _source_subtitle_basis(source_subtitles: list[dict[str, Any]]) -> str:
    sources = {
        str(item.get("projection_source") or "").strip()
        for item in source_subtitles
        if isinstance(item, dict)
    }
    for basis in ("canonical_transcript", "transcript_segment", "subtitle_item"):
        if basis in sources:
            return basis
    return "subtitle_projection"


def _subtitle_projection_repair_summary(
    *,
    validation: Any,
    apply_repair: bool,
) -> dict[str, Any]:
    mismatch_detected = bool(getattr(validation, "mismatch_detected", False))
    fallback_used = bool(getattr(validation, "fallback_used", False))
    changed = bool(getattr(validation, "changed", False))
    input_count = int(getattr(validation, "input_count", 0) or 0)
    output_count = int(getattr(validation, "output_count", 0) or 0)
    repair_applied = bool(apply_repair and changed and (mismatch_detected or fallback_used))
    if repair_applied and fallback_used:
        repair_mode = "source_fallback_remap"
    elif repair_applied and mismatch_detected:
        repair_mode = "projection_annotation_repair"
    else:
        repair_mode = None
    return {
        "repair_requested": bool(apply_repair),
        "repair_applied": repair_applied,
        "mismatch_detected": mismatch_detected,
        "fallback_used": fallback_used,
        "changed": changed,
        "annotation_changed": bool(changed and not mismatch_detected and not fallback_used),
        "input_count": input_count,
        "output_count": output_count,
        "repair_mode": repair_mode,
    }


async def _validated_subtitle_projection_for_timeline(
    session,
    *,
    job_id: uuid.UUID,
    projected_subtitles: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
    source_subtitles: list[dict[str, Any]] | None = None,
    fallback_source_subtitles: list[dict[str, Any]] | None = None,
    allow_source_fallback_repair: bool = False,
    apply_repair: bool = False,
    diagnostics_slot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    effective_source_subtitles = source_subtitles or await _load_source_subtitle_payloads_for_projection_validation(session, job_id=job_id)
    effective_fallback_source_subtitles = (
        fallback_source_subtitles
        if allow_source_fallback_repair and fallback_source_subtitles is not None
        else None
    )
    validation = validate_projected_subtitles_against_source(
        projected_subtitles,
        source_subtitles=effective_source_subtitles,
        keep_segments=keep_segments,
        fallback_source_subtitles=effective_fallback_source_subtitles,
        apply_annotation_repair=apply_repair,
    )
    if diagnostics_slot is not None:
        diagnostics_slot.update(
            _subtitle_projection_repair_summary(
                validation=validation,
                apply_repair=apply_repair,
            )
        )
    if bool(getattr(validation, "mismatch_detected", False)) and not apply_repair:
        logger.debug(
            "subtitle_projection_validation_mismatch job_id=%s mismatch=%s fallback_used=%s",
            str(job_id),
            bool(getattr(validation, "mismatch_detected", False)),
            bool(getattr(validation, "fallback_used", False)),
        )
    if apply_repair:
        return validation.subtitles
    return list(projected_subtitles)


def _build_source_transcript_projection_validation(
    *,
    remapped_subtitles: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
    keep_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    return validate_projected_subtitles_against_transcript(
        remapped_subtitles,
        transcript_segments=transcript_segments,
        keep_segments=keep_segments,
    )


def _merge_automatic_gate_with_subtitle_projection(
    automatic_gate: dict[str, Any],
    subtitle_source_projection_validation: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(automatic_gate or {})
    reasons = [
        str(item)
        for item in list(merged.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    if bool(subtitle_source_projection_validation.get("blocking")):
        if "subtitle_source_projection_validation_blocking" not in reasons:
            reasons.append("subtitle_source_projection_validation_blocking")
        merged["blocking"] = True
        merged["subtitle_source_projection_validation"] = {
            "blocking_issue_count": int(
                subtitle_source_projection_validation.get("blocking_issue_count") or 0
            ),
            "issue_counts": dict(subtitle_source_projection_validation.get("issue_counts") or {}),
        }
    else:
        merged["blocking"] = bool(merged.get("blocking"))
    merged["blocking_reasons"] = reasons
    return merged


def _attach_edit_decision_projection_gate_analysis(
    decision: Any,
    *,
    subtitle_source_projection_validation: dict[str, Any],
    automatic_gate: dict[str, Any],
    subtitle_projection_repair: dict[str, Any] | None = None,
) -> None:
    if not hasattr(decision, "analysis") or not isinstance(getattr(decision, "analysis", None), dict):
        decision.analysis = {}
    decision.analysis["subtitle_source_projection_validation"] = subtitle_source_projection_validation
    decision.analysis["automatic_gate"] = automatic_gate
    decision.analysis["subtitle_projection_repair"] = dict(subtitle_projection_repair or {})


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
    sanitize_transcript_segment_word_rows(transcript_rows)
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
    canonical_transcript_data = (
        await _load_latest_current_canonical_transcript_data(session, job_id=job_id)
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
        canonical_transcript_data,
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
    sanitize_transcript_segment_word_rows(transcript_rows)
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
    canonical_transcript_data = await _load_latest_current_canonical_transcript_data(
        session,
        job_id=job_id,
    )
    transcript_fact_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,),
    )
    transcript_context = _build_transcript_context_payload(
        transcript_rows,
        canonical_transcript_data,
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
    automation = _drop_soft_content_understanding_blockers(automation)
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
            str(payload.get("manual_video_summary") or "").strip(),
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


def _content_profile_confident_enough_to_skip_enrich(profile: dict[str, Any] | None) -> bool:
    candidate = dict(profile or {})
    understanding = candidate.get("content_understanding") if isinstance(candidate.get("content_understanding"), dict) else {}
    confidence = (understanding.get("confidence") if isinstance(understanding, dict) else {}) or {}
    try:
        overall_confidence = float(confidence.get("overall") or 0.0)
    except (TypeError, ValueError):
        overall_confidence = 0.0
    if overall_confidence < 0.86:
        return False
    if bool(understanding.get("needs_review")):
        return False

    subject_type = str(candidate.get("subject_type") or "").strip()
    video_theme = str(candidate.get("video_theme") or "").strip()
    summary = str(candidate.get("summary") or "").strip()
    if not subject_type or not video_theme or not summary:
        return False
    if any(token in subject_type for token in ("内容", "视频", "产品", "待确认")):
        return False

    identity_terms = [
        str(candidate.get("subject_brand") or "").strip(),
        str(candidate.get("subject_model") or "").strip(),
        str(understanding.get("primary_subject") or "").strip(),
    ]
    observed_entities = understanding.get("observed_entities") if isinstance(understanding, dict) else []
    if isinstance(observed_entities, list):
        identity_terms.extend(
            str((item or {}).get("name") or "").strip()
            for item in observed_entities
            if isinstance(item, dict)
        )
    if not any(identity_terms):
        return False

    return bool([item for item in (candidate.get("search_queries") or []) if str(item).strip()])


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
    source_context_description = "\n".join(
        part
        for part in (
            str(source_context.get("video_description") or "").strip(),
            f"人工视频摘要（强证据）：{str(source_context.get('manual_video_summary') or '').strip()}"
            if str(source_context.get("manual_video_summary") or "").strip()
            else "",
        )
        if part
    ).strip()
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
    source_context_feedback_error = ""
    try:
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
    except Exception as exc:
        source_context_feedback_error = f"{type(exc).__name__}: {' '.join(str(exc or '').split())}"[:240]
    updated_profile = dict(content_profile)
    if source_context:
        updated_profile["source_context"] = {
            **source_context,
            **({"resolved_feedback": dict(resolved_source_context_feedback)} if resolved_source_context_feedback else {}),
            **({"source_context_feedback_error": source_context_feedback_error} if source_context_feedback_error else {}),
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
        status="done",
        detail=str((automation.get("identity_review") or {}).get("reason") or "内容摘要存在身份提示，已保留到手动调整。"),
        progress=1.0,
        metadata_updates={
            "auto_confirmed": False,
            "identity_review": automation.get("identity_review"),
            "manual_adjustment_advisory": True,
            "review_reasons": automation["review_reasons"],
            "blocking_reasons": automation["blocking_reasons"],
        },
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
        status="done",
        detail="成片审核修正尚未确认到当前主体，已保留为手动调整提示并继续后续流程。",
        progress=1.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "manual_adjustment_advisory": True,
            "review_user_feedback": dict(manual_review_feedback),
            "resolved_review_user_feedback": {},
        },
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
    subtitle_review_detail = "、".join(detail_bits) + "，已保留为手动调整提示并继续后续流程。"
    existing_detail = str((review_step.metadata_ or {}).get("detail") or "").strip()
    _set_summary_review_state(
        review_step,
        now=now,
        status="done",
        detail=_merge_review_step_detail(existing_detail, subtitle_review_detail),
        progress=1.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "manual_adjustment_advisory": True,
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
    detail = "内容异常门发现需关注问题，已保留为手动调整提示并继续后续流程。"
    if blocking_reasons:
        detail = f"{detail} {'；'.join(blocking_reasons[:3])}"
    _set_summary_review_state(
        review_step,
        now=now,
        status="done",
        detail=detail,
        progress=1.0,
        metadata_updates={
            "auto_confirmed": False,
            "manual_confirmed": False,
            "exception_gate": True,
            "manual_adjustment_advisory": True,
            "review_reasons": list(automation.get("review_reasons") or []),
            "blocking_reasons": blocking_reasons,
        },
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


def _drop_soft_content_understanding_blockers(automation: dict[str, Any]) -> dict[str, Any]:
    soft_blockers = {
        "内容理解推断失败",
        "内容理解暂不可用",
        "LLM 内容理解结果要求人工复核",
        "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认",
        "开箱类视频命中首次品牌/型号且缺少交叉印证，已按保守摘要继续",
        "开箱类视频命中首次品牌/型号，默认待人工确认",
        "开箱类视频命中首次品牌/型号，已作为身份置信度警告继续",
    }
    original_blocking_reasons = [
        str(item).strip()
        for item in list(automation.get("blocking_reasons") or [])
        if str(item).strip()
    ]
    blocking_reasons = [
        reason
        for reason in original_blocking_reasons
        if reason not in soft_blockers
    ]
    if blocking_reasons == original_blocking_reasons:
        return automation
    updated = dict(automation)
    updated["blocking_reasons"] = blocking_reasons
    if not blocking_reasons:
        updated["auto_confirm"] = True
        updated["quality_gate_passed"] = True
    return updated


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
            feedback_source="summary_review_feedback",
            observation_type="manual_confirm",
            context_hint=f"summary_review_feedback:{job.workflow_template or 'auto'}",
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
    final_profile = dict(content_profile)
    final_profile["review_mode"] = "manual_adjustment_advisory"
    final_profile["needs_review"] = True
    context_source_profile = dict(final_profile)
    job.status = "processing"
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


def _resolve_local_preview_source(job: Job) -> Path | None:
    source_path = Path(str(job.source_path or "")).expanduser()
    if source_path.exists() and source_path.is_file():
        return source_path
    resolve_path = getattr(get_storage(), "resolve_path", None)
    if callable(resolve_path):
        resolved = resolve_path(str(job.source_path or ""))
        if resolved.exists() and resolved.is_file():
            return resolved
    return None


async def _warm_manual_editor_preview_assets_for_job(
    session,
    *,
    job: Job,
    step: JobStep,
    duration_sec: float,
    content_profile: dict[str, Any],
) -> dict[str, Any] | None:
    if str(getattr(job, "job_flow_mode", "") or "").strip() != "smart_assist":
        return None
    preview_timeout_sec = max(
        30.0,
        float(getattr(get_settings(), "manual_editor_preview_runtime_timeout_sec", 300) or 300),
    )
    source_path = _resolve_local_preview_source(job)
    if source_path is None:
        await _set_step_progress(
            session,
            step,
            detail="剪辑决策已生成；源片不在本机可直接读取路径，跳过手动预览代理预热",
            progress=0.94,
            metadata_updates={"manual_editor_preview_assets": {"status": "skipped", "reason": "source_not_local"}},
        )
        return None

    output_project_dir = get_output_project_dir(
        str(job.source_name or ""),
        job.created_at,
        content_profile=content_profile,
        output_dir=job.output_dir,
    )
    asset_dir = output_project_dir / "manual-editor"
    queued_payload = mark_manual_editor_preview_assets_queued(job.id, asset_dir=asset_dir)
    await _set_step_progress(
        session,
        step,
        detail=f"预生成手动调整轻量预览代理（最多 {int(round(preview_timeout_sec))}s）",
        progress=0.93,
        metadata_updates={
            "manual_editor_preview_assets": queued_payload,
            "manual_editor_preview_timeout_sec": preview_timeout_sec,
        },
    )
    try:
        await _set_step_runtime_budget(
            session,
            step,
            phase="manual_editor_preview_assets",
            timeout_sec=preview_timeout_sec,
        )
        try:
            async def _build_preview_assets_with_orientation() -> dict[str, Any]:
                from roughcut.media.rotation import detect_video_rotation_decision

                orientation_decision = (await detect_video_rotation_decision(source_path)).to_dict()
                return await asyncio.to_thread(
                    ensure_manual_editor_preview_assets,
                    job_id=job.id,
                    source_path=source_path,
                    duration_sec=float(duration_sec or 0.0),
                    asset_dir=asset_dir,
                    orientation_decision=orientation_decision,
                )

            async with _maintain_step_heartbeat(
                step,
                detail=f"预生成手动调整轻量预览代理（最多 {int(round(preview_timeout_sec))}s）",
                progress=0.93,
            ):
                payload = await asyncio.wait_for(
                    _build_preview_assets_with_orientation(),
                    timeout=preview_timeout_sec,
                )
        finally:
            await _clear_step_runtime_budget(session, step)
    except asyncio.TimeoutError:
        await _set_step_progress(
            session,
            step,
            detail=f"轻量预览代理预生成超时（{int(round(preview_timeout_sec))}s），进入编辑器时仍可按需生成",
            progress=0.96,
            metadata_updates={
                "manual_editor_preview_assets": {
                    "status": "failed",
                    "stage": "timeout",
                    "error": f"manual_editor_preview_timeout>{preview_timeout_sec:.1f}s",
                }
            },
        )
        return None
    except Exception as exc:
        logger.exception("Manual editor preview asset prewarm failed for job %s", job.id)
        await _set_step_progress(
            session,
            step,
            detail="轻量预览代理预生成失败，进入编辑器时仍可重试生成",
            progress=0.96,
            metadata_updates={
                "manual_editor_preview_assets": {
                    "status": "failed",
                    "stage": "failed",
                    "error": str(exc)[-500:],
                }
            },
        )
        return None
    await _set_step_progress(
        session,
        step,
        detail="手动调整轻量预览代理已生成",
        progress=0.98,
        metadata_updates={
            "manual_editor_preview_assets": {
                "status": str(payload.get("status") or "ready"),
                "stage": str(payload.get("stage") or "ready"),
                "progress": float(payload.get("progress") or 1.0),
                "asset_version": int(payload.get("asset_version") or 0),
                "orientation_decision": payload.get("orientation_decision")
                if isinstance(payload.get("orientation_decision"), dict)
                else {},
                "video_ready": bool(payload.get("video_ready")),
                "audio_ready": bool(payload.get("audio_ready")),
                "thumbnail_count": len(list(payload.get("thumbnail_items") or [])),
            }
        },
    )
    return payload


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


def _artifact_file_is_readable(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


async def _resolve_audio_artifact_or_rebuild(
    session,
    *,
    job: Job,
    step: JobStep | None,
    audio_artifact: Artifact,
    tmpdir: str,
    default_name: str = "audio.wav",
    progress: float = 0.2,
) -> Path | None:
    reference = str(audio_artifact.storage_path or "")
    try:
        audio_path = await _resolve_storage_reference(
            reference,
            tmpdir=tmpdir,
            default_name=default_name,
        )
        if _artifact_file_is_readable(audio_path):
            return audio_path
        raise FileNotFoundError(str(audio_path))
    except FileNotFoundError:
        logger.warning(
            "Audio artifact missing; rebuilding from source job=%s storage_path=%s",
            job.id,
            reference,
        )
        await _set_step_progress(
            session,
            step,
            detail="音频派生文件缺失，正在从源视频重新提取",
            progress=progress,
            metadata_updates={
                "audio_artifact_rebuilt": True,
                "missing_audio_artifact_path": reference,
            },
        )
        source_for_audio = await _resolve_source(job, tmpdir)
        rebuilt_audio_path = Path(tmpdir) / default_name
        try:
            await extract_audio(source_for_audio, rebuilt_audio_path)
        except NoAudioStreamError:
            metadata = dict(step.metadata_ or {}) if step is not None else {}
            metadata["has_audio"] = False
            metadata["audio_optional"] = True
            if step is not None:
                step.metadata_ = metadata
                await session.commit()
            return None
        if not _artifact_file_is_readable(rebuilt_audio_path):
            raise FileNotFoundError(str(rebuilt_audio_path))
        audio_key = job_key(str(job.id), "audio.wav")
        storage = get_storage()
        await storage.async_upload_file(rebuilt_audio_path, audio_key)
        resolve_path = getattr(storage, "resolve_path", None)
        if callable(resolve_path):
            stored_audio_path = resolve_path(audio_key)
            if not _artifact_file_is_readable(stored_audio_path):
                raise FileNotFoundError(str(stored_audio_path))
        audio_artifact.storage_path = audio_key
        metadata = dict(step.metadata_ or {}) if step is not None else {}
        metadata["has_audio"] = True
        if step is not None:
            step.metadata_ = metadata
        await session.commit()
        return rebuilt_audio_path


async def _get_job_and_step(job_id: str, step_name: str):
    factory = get_session_factory()
    async with factory() as session:
        job = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.steps))
                .where(Job.id == uuid.UUID(job_id))
            )
        ).scalar_one()
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


async def _persist_render_runtime_diagnostics(
    session,
    *,
    job_id: uuid.UUID,
    step_id: uuid.UUID | None,
    avatar_result: dict[str, Any] | None = None,
    strategy_render_validation: dict[str, Any] | None = None,
) -> None:
    latest_artifact = await _load_latest_optional_artifact(
        session,
        job_id=job_id,
        artifact_types=(ARTIFACT_TYPE_RENDER_RUNTIME_DIAGNOSTICS,),
    )
    latest_payload = latest_artifact.data_json if latest_artifact and isinstance(latest_artifact.data_json, dict) else {}
    payload: dict[str, Any] = {}
    if isinstance(avatar_result, dict) and avatar_result:
        payload["avatar_result"] = _merge_render_runtime_result(
            latest_payload.get("avatar_result"),
            avatar_result,
        )
    elif isinstance(latest_payload.get("avatar_result"), dict):
        payload["avatar_result"] = copy.deepcopy(latest_payload["avatar_result"])
    if isinstance(strategy_render_validation, dict) and strategy_render_validation:
        payload["strategy_render_validation"] = copy.deepcopy(strategy_render_validation)
    elif isinstance(latest_payload.get("strategy_render_validation"), dict):
        payload["strategy_render_validation"] = copy.deepcopy(latest_payload["strategy_render_validation"])
    if not payload:
        return
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step_id,
            artifact_type=ARTIFACT_TYPE_RENDER_RUNTIME_DIAGNOSTICS,
            data_json=payload,
        )
    )
    await session.commit()


def _merge_render_runtime_result(
    previous_value: Any,
    current_value: dict[str, Any] | None,
) -> dict[str, Any]:
    current = copy.deepcopy(current_value) if isinstance(current_value, dict) else {}
    previous = previous_value if isinstance(previous_value, dict) else {}
    if not previous:
        return current
    previous_status = str(previous.get("status") or "").strip().lower()
    current_status = str(current.get("status") or "").strip().lower()
    previous_reason = str(previous.get("reason") or "").strip().lower()
    current_reason = str(current.get("reason") or "").strip().lower()
    previous_is_specific_degraded = previous_status == "degraded" and previous_reason and not previous_reason.startswith("missing_")
    current_is_weaker_missing = current_status == "degraded" and current_reason.startswith("missing_")
    if previous_is_specific_degraded and current_is_weaker_missing:
        merged = copy.deepcopy(previous)
        for key, value in current.items():
            if key not in merged and value not in (None, "", []):
                merged[key] = copy.deepcopy(value)
        return merged
    merged = copy.deepcopy(previous)
    if current_status in {"done", "success"}:
        for stale_key in ("reason", "retryable", "error_metadata"):
            if stale_key not in current:
                merged.pop(stale_key, None)
    merged.update(current)
    return merged


async def _resolve_auto_smart_cut_rules(
    session,
    *,
    job_id: uuid.UUID,
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    rules_artifacts_result = await session.execute(
        select(Artifact)
        .where(
            Artifact.job_id == job_id,
            Artifact.artifact_type.in_((_MANUAL_EDITOR_DRAFT_ARTIFACT_TYPE, ARTIFACT_TYPE_REFINE_DECISION_PLAN)),
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )
    rule_artifacts = rules_artifacts_result.scalars().all()
    content_profile_rules = None
    if isinstance(content_profile, dict):
        content_profile_rules = content_profile.get("smart_cut_rules")
    for payload_source in rule_artifacts:
        if not isinstance(payload_source, Artifact) or not isinstance(payload_source.data_json, dict):
            continue
        raw_rules = payload_source.data_json.get("smart_cut_rules")
        if raw_rules is None:
            continue
        normalized = normalize_smart_cut_rules_payload(raw_rules)
        if normalized:
            return normalized

    if isinstance(content_profile_rules, dict):
        normalized = normalize_smart_cut_rules_payload(content_profile_rules)
        if normalized:
            return normalized

    return default_smart_cut_rules_payload()


def _resolve_keep_segments_from_refine_plan(
    refine_plan_payload: dict[str, Any] | None,
    *,
    editorial_timeline_id: str,
    editorial_timeline_version: int,
    fallback_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {"start": float(item.get("start", 0.0) or 0.0), "end": float(item.get("end", 0.0) or 0.0)}
        for item in resolve_refine_keep_segments_for_timeline(
            refine_plan_payload,
            editorial_timeline_id=editorial_timeline_id,
            editorial_timeline_version=editorial_timeline_version,
            fallback_segments=fallback_segments,
        )
    ]

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
    if (
        not topic_fact_confirmation_present(effective_content_profile)
        or topic_fact_is_confirmed(effective_content_profile)
    ):
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
        job = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.steps))
                .where(Job.id == uuid.UUID(job_id))
            )
        ).scalar_one()
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
            resolve_path = getattr(storage, "resolve_path", None)
            if callable(resolve_path):
                stored_audio_path = resolve_path(key)
                if not _artifact_file_is_readable(stored_audio_path):
                    raise FileNotFoundError(str(stored_audio_path))

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
        settings = get_settings()
        with llm_task_route("subtitle", search_enabled=False, settings=settings):
            transcription_context_prior = await infer_transcription_context_prior(
                source_name=job.source_name,
                source_context=source_context,
                workflow_template=job.workflow_template,
            )
        if transcription_context_prior:
            source_context_profile["transcription_context_prior"] = transcription_context_prior
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
            source_name=job.source_name,
            glossary_terms=effective_glossary_terms,
            user_memory=user_memory,
            recent_subtitles=recent_subtitles,
            content_profile=source_context_profile,
            include_recent_terms=False,
            include_recent_examples=False,
        )
        _set_step_correction_framework_metadata(step, settings)
        if transcription_context_prior:
            metadata = dict(step.metadata_ or {})
            metadata["transcription_context_prior"] = transcription_context_prior
            step.metadata_ = metadata
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
            audio_path = await _resolve_audio_artifact_or_rebuild(
                session,
                job=job,
                step=step,
                audio_artifact=audio_artifact,
                tmpdir=tmpdir,
                default_name="audio.wav",
                progress=0.16,
            )
            if audio_path is None:
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
            except AsrQualityGateError as exc:
                await persist_asr_quality_gate_artifact(
                    job_id=job.id,
                    step=step,
                    session=session,
                    language=job.language,
                    prompt=transcription_prompt,
                    error=exc,
                )
                await _set_step_progress(
                    session,
                    step,
                    detail="ASR 质量门拒绝，已保存结构化证据",
                    progress=float(heartbeat_state["progress"]),
                    metadata_updates={
                        "asr_quality_gate_artifact": True,
                        "asr_quality_gate_rejected_attempt_count": len(exc.rejected_attempts),
                    },
                )
                await session.commit()
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
        sanitize_transcript_segment_word_rows(segments)
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
        segmentation_segments = [
            _build_transcript_segment_adapter(segment, index=index) for index, segment in enumerate(segments)
        ]
        canonical_transcript_layer = build_canonical_transcript_layer_from_transcript_segments(
            segmentation_segments,
            source_basis="subtitle_postprocess",
        )
        canonical_segmentation_segments = _build_segmentation_segments_from_canonical_layer(canonical_transcript_layer)
        effective_segmentation_segments = canonical_segmentation_segments or segmentation_segments

        split_started = time.perf_counter()
        async with _maintain_step_heartbeat(
            step,
            detail="正在生成字幕切分",
            progress=0.45,
        ):
            segmentation_result = await asyncio.to_thread(
                segment_subtitles,
                effective_segmentation_segments,
                max_chars=int(split_profile["max_chars"]),
                max_duration=float(split_profile["max_duration"]),
            )
        subtitle_profile_retry = _subtitle_segmentation_retry_summary()
        if _subtitle_segmentation_needs_profile_retry(segmentation_result.analysis):
            base_split_profile = dict(split_profile)
            base_defect_rank = _subtitle_segmentation_defect_rank(segmentation_result.analysis)
            relaxed_split_profile = _relaxed_subtitle_split_profile(base_split_profile)
            if relaxed_split_profile:
                await _set_step_progress(
                    session,
                    step,
                    detail="检测到字幕断句缺陷，尝试放宽节奏重新切分",
                    progress=0.5,
                )
                async with _maintain_step_heartbeat(
                    step,
                    detail="正在用放宽节奏重新生成字幕切分",
                    progress=0.5,
                ):
                    candidate_segmentation_result = await asyncio.to_thread(
                        segment_subtitles,
                        effective_segmentation_segments,
                        max_chars=int(relaxed_split_profile["max_chars"]),
                        max_duration=float(relaxed_split_profile["max_duration"]),
                    )
                candidate_defect_rank = _subtitle_segmentation_defect_rank(candidate_segmentation_result.analysis)
                accepted_retry = _subtitle_segmentation_candidate_is_better(
                    segmentation_result.analysis,
                    candidate_segmentation_result.analysis,
                )
                subtitle_profile_retry = _subtitle_segmentation_retry_summary(
                    attempted=True,
                    accepted=accepted_retry,
                    reason="defect_rank_improved" if accepted_retry else "candidate_not_better",
                    base_profile=base_split_profile,
                    candidate_profile=relaxed_split_profile,
                    base_rank=base_defect_rank,
                    candidate_rank=candidate_defect_rank,
                )
                if accepted_retry:
                    split_profile = relaxed_split_profile
                    segmentation_result = candidate_segmentation_result
            else:
                subtitle_profile_retry = _subtitle_segmentation_retry_summary(
                    attempted=False,
                    accepted=False,
                    reason="no_relaxed_profile_available",
                    base_profile=base_split_profile,
                    base_rank=base_defect_rank,
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
            async with _maintain_step_heartbeat(
                step,
                detail=(
                    f"正在复判 {segmentation_result.analysis.low_confidence_window_count} 个低置信度断句窗口"
                ),
                progress=0.55,
            ):
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
        subtitle_generation_detail = (
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
        )
        await _set_step_progress(
            session,
            step,
            detail=subtitle_generation_detail,
            progress=0.7,
            metadata_updates={
                "subtitle_segmentation": segmentation_result.analysis.as_dict(),
                "subtitle_profile_retry": subtitle_profile_retry,
                "subtitle_boundary_refine": llm_boundary_refine,
            },
        )
        save_started = time.perf_counter()
        async with _maintain_step_heartbeat(
            step,
            detail="正在保存字幕并生成质量报告",
            progress=0.82,
        ):
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
                source_name=job.source_name,
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
                allow_llm=True,
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
            subtitle_quality_report.setdefault("metrics", {})["alignment_source"] = build_subtitle_alignment_source_metrics(entries)
            subtitle_quality_report = apply_subtitle_alignment_quality_guard(
                subtitle_quality_report,
                require_word_alignment=True,
            )
            subtitle_projection_layer = build_subtitle_projection_layer(
                items,
                segmentation_analysis=segmentation_result.analysis,
                split_profile=split_profile,
                boundary_refine=llm_boundary_refine,
                quality_report=subtitle_quality_report,
                projection_basis="display_baseline",
                transcript_layer="canonical_transcript",
            )
            architecture_artifacts = build_subtitle_architecture_artifacts(
                job_id=job.id,
                step_id=step.id,
                transcript_fact_layer=transcript_fact_layer,
                canonical_transcript_layer=canonical_transcript_layer,
                subtitle_projection_layer=subtitle_projection_layer,
            )
            for architecture_artifact in architecture_artifacts:
                if (
                    architecture_artifact.artifact_type == ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER
                    and transcript_fact_artifact is not None
                ):
                    continue
                session.add(architecture_artifact)
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
        completion_metadata = dict(step.metadata_ or {})
        current_task_id = completion_metadata.pop("task_id", None)
        completion_metadata.pop("retry_wait_until", None)
        completion_metadata.pop("retry_after_sec", None)
        if current_task_id:
            completion_metadata["last_task_id"] = current_task_id
        step.status = "done"
        step.finished_at = datetime.now(timezone.utc)
        step.error_message = None
        step.metadata_ = completion_metadata
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
            "subtitle_profile_retry": subtitle_profile_retry,
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
        job_steps_result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
        strategy_profile_job_view = SimpleNamespace(
            id=job.id,
            workflow_template=job.workflow_template,
            job_flow_mode=getattr(job, "job_flow_mode", "auto"),
            packaging_snapshot_json=job.packaging_snapshot_json,
            steps=list(job_steps_result.scalars().all()),
        )
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
                content_understanding_timeout_sec = _resolve_content_understanding_timeout_seconds()
                await _set_step_progress(
                    session,
                    step,
                    detail=f"抽取画面并分析主题、主体与处理模板（最多 {int(round(content_understanding_timeout_sec))}s）",
                    progress=0.55,
                    metadata_updates={
                        "content_understanding_timeout_sec": content_understanding_timeout_sec,
                    },
                )
                usage_before = await _read_persisted_step_usage_snapshot(step.id if step else None)
                initial_search_enabled = should_enable_task_search(
                    "content_profile",
                    default_enabled=include_research,
                    profile=seeded_profile or None,
                    settings=settings,
                )
                await _set_step_runtime_budget(
                    session,
                    step,
                    phase="content_understanding",
                    timeout_sec=content_understanding_timeout_sec,
                )
                try:
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
                finally:
                    await _clear_step_runtime_budget(session, step)
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
                    has_explicit_strategy_source_context = isinstance(
                        source_context.get("strategy_classification") or source_context.get("classification"),
                        dict,
                    )
                    if has_explicit_strategy_source_context:
                        content_profile = {
                            **dict(content_profile or {}),
                            "content_profile_enrich_short_circuit": {
                                "enabled": True,
                                "reason": "explicit_strategy_classification_source_context",
                            },
                        }
                    elif _profile_matches_topic_registry_hints(content_profile, topic_hints=topic_registry_hints):
                        content_profile = {
                            **dict(content_profile or {}),
                            "topic_registry_short_circuit": {
                                "enabled": True,
                                "reason": "topic_registry_hint_aligned",
                                "topic_hints": topic_registry_hints,
                            },
                        }
                    elif _content_profile_confident_enough_to_skip_enrich(content_profile):
                        content_profile = {
                            **dict(content_profile or {}),
                            "content_profile_enrich_short_circuit": {
                                "enabled": True,
                                "reason": "initial_understanding_confident",
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
        strategy_gate_confirmation_result = await session.execute(
            select(Artifact)
            .where(
                Artifact.job_id == job.id,
                Artifact.artifact_type == ARTIFACT_TYPE_STRATEGY_REVIEW_GATE_CONFIRMATIONS,
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        )
        strategy_gate_confirmation_artifact = strategy_gate_confirmation_result.scalars().first()
        strategy_gate_confirmations = (
            dict(strategy_gate_confirmation_artifact.data_json or {})
            if strategy_gate_confirmation_artifact is not None
            and isinstance(strategy_gate_confirmation_artifact.data_json, dict)
            else {}
        )
        enriched_content_profile = attach_content_profile_capability_orchestration(
            content_profile,
            job=strategy_profile_job_view,
            strategy_review_gate_confirmations=strategy_gate_confirmations,
        )
        content_profile = enriched_content_profile if isinstance(enriched_content_profile, dict) else content_profile
        enriched_final_profile = attach_content_profile_capability_orchestration(
            final_profile,
            job=strategy_profile_job_view,
            strategy_review_gate_confirmations=strategy_gate_confirmations,
        )
        final_profile = enriched_final_profile if isinstance(enriched_final_profile, dict) else final_profile
        enriched_context_source_profile = attach_content_profile_capability_orchestration(
            context_source_profile,
            job=strategy_profile_job_view,
            strategy_review_gate_confirmations=strategy_gate_confirmations,
        )
        context_source_profile = (
            enriched_context_source_profile
            if isinstance(enriched_context_source_profile, dict)
            else context_source_profile
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
            strategy_review_gate_confirmations=strategy_gate_confirmations,
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
            source_name=job.source_name,
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
        content_profile = strip_publication_only_profile_fields(content_profile)
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
        refreshed_projection_layer, subtitle_quality_report, correction_score_report = await _build_canonical_refresh_projection(
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
            correction_score_report=correction_score_report,
        )
        persisted_subtitle_count = await _persist_projection_layer_to_subtitle_items(
            session,
            job_id=job.id,
            refreshed_projection_layer=refreshed_projection_layer,
        )
        detail, result_payload = _build_transcript_review_result_payload(
            canonical_transcript_layer=canonical_transcript_layer,
            refreshed_projection_layer=refreshed_projection_layer,
        )
        result_payload["persisted_subtitle_count"] = persisted_subtitle_count
        result_payload["subtitle_items_preserved"] = False
        result_payload["subtitle_items_refreshed"] = persisted_subtitle_count > 0
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
        creator_card = await _load_job_creator_card(session, job)
        avatar_binding = _resolve_creator_avatar_binding(creator_card)

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
            presenter_id=str((avatar_binding or {}).get("presenter_id") or "").strip() or None,
        )
        packaging_config = dict((list_packaging_assets().get("config") or {}))
        voice_execution: dict[str, Any] | None = None
        render_execution: dict[str, Any] | None = None
        render_executed_in_mode = False
        avatar_segments = list(plan.get("segments") or [])
        if plan.get("mode") == "full_track_audio_passthrough":
            _apply_avatar_presenter_binding_to_plan(
                plan,
                binding=avatar_binding,
                packaging_config=packaging_config,
            )
            plan["dubbing_execution"] = {
                "provider": "passthrough",
                "status": "skipped",
                "reason": "full_track_audio_passthrough",
            }
            missing_presenter_reason = _avatar_missing_presenter_reason(plan)
            if missing_presenter_reason:
                plan["render_execution"] = _avatar_missing_presenter_execution(
                    plan,
                    reason=missing_presenter_reason,
                )
            else:
                plan["render_execution"] = {
                    "provider": plan.get("provider"),
                    "status": "deferred_to_render",
                    "reason": "full_track_audio_passthrough",
                }
        elif plan.get("mode") == "segmented_audio_passthrough" and avatar_segments:
            audio_artifact = await _load_latest_artifact(session, job.id, "audio_wav")
            _apply_avatar_presenter_binding_to_plan(
                plan,
                binding=avatar_binding,
                packaging_config=packaging_config,
            )
            missing_presenter_reason = _avatar_missing_presenter_reason(plan)
            if missing_presenter_reason:
                plan["dubbing_execution"] = {
                    "provider": "passthrough",
                    "status": "skipped",
                    "reason": "segmented_audio_passthrough",
                }
                plan["render_execution"] = _avatar_missing_presenter_execution(
                    plan,
                    reason=missing_presenter_reason,
                )
            else:
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
        source_subtitle_dicts = await _load_edit_plan_source_subtitles(session, job=job)
        edit_source_subtitles = source_subtitle_dicts or clean_subtitle_payloads(
            subtitle_dicts,
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
        )
        decision_subtitles = [dict(item) for item in edit_source_subtitles] or clean_subtitle_payloads(
            subtitle_dicts,
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
        )
        transcript_result = await session.execute(
            select(TranscriptSegment)
            .where(TranscriptSegment.job_id == job.id, TranscriptSegment.version == 1)
            .order_by(TranscriptSegment.segment_index)
        )
        transcript_rows = transcript_result.scalars().all()
        sanitize_transcript_segment_word_rows(transcript_rows)
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
            audio_path = await _resolve_audio_artifact_or_rebuild(
                session,
                job=job,
                step=step,
                audio_artifact=audio_artifact,
                tmpdir=tmpdir,
                default_name="audio.wav",
                progress=0.3,
            )
            await _set_step_progress(session, step, detail="检测静音和明显废话段", progress=0.5)
            silences = detect_silence(audio_path) if audio_path is not None else []
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
                    scene_detection_timeout_sec = max(
                        15,
                        int(getattr(get_settings(), "edit_plan_scene_detection_timeout_sec", 180) or 180),
                    )
                    scene_detection_frame_skip = max(
                        0,
                        int(getattr(get_settings(), "edit_plan_scene_detection_frame_skip", 2) or 0),
                    )
                    await _set_step_progress(
                        session,
                        step,
                        detail=f"检测画面场景边界，最多等待 {scene_detection_timeout_sec}s",
                        progress=0.58,
                        metadata_updates={
                            "scene_detection_timeout_sec": scene_detection_timeout_sec,
                            "scene_detection_frame_skip": scene_detection_frame_skip,
                        },
                    )
                    async with _maintain_step_heartbeat(step):
                        scene_boundaries = await asyncio.to_thread(
                            detect_scenes,
                            local_source_candidate,
                            frame_skip=scene_detection_frame_skip,
                            max_runtime_sec=scene_detection_timeout_sec,
                        )
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
        await _set_step_progress(session, step, detail="基于清理后字幕生成统一语义时间线", progress=0.68)
        semantic_timeline_analysis = infer_timeline_analysis(
            decision_subtitles,
            content_profile=content_profile,
            duration=duration,
            editing_skill=editing_skill,
        )
        semantic_timeline_analysis["stage"] = SEMANTIC_TIMELINE_ANALYSIS_STAGE
        semantic_timeline_analysis["subtitle_source_basis"] = _source_subtitle_basis(decision_subtitles)
        decision = build_edit_decision(
            source_path=job.source_path,
            duration=duration,
            silence_segments=silences,
            subtitle_items=decision_subtitles,
            content_profile=content_profile,
            transcript_segments=transcript_segment_dicts,
            scene_boundaries=scene_boundaries,
            editing_skill=editing_skill,
            timeline_analysis=semantic_timeline_analysis,
        )
        decision = await _maybe_review_edit_decision_cuts_with_llm(
            job_id=job.id,
            source_name=str(job.source_name or ""),
            decision=decision,
            subtitle_items=decision_subtitles,
            transcript_segments=transcript_segment_dicts,
            content_profile=content_profile,
        )
        source_timeline_contract = refresh_source_timeline_contract_analysis(
            decision,
            duration=duration,
            transcript_segments=transcript_segment_dicts,
            subtitle_items=decision_subtitles,
            silence_segments=silences,
        )
        manual_editor_analysis = decision.analysis.setdefault("manual_editor", {})
        if isinstance(manual_editor_analysis, dict):
            manual_editor_analysis["timeline_subtitle_fingerprint"] = subtitle_payload_fingerprint(decision_subtitles)
            manual_editor_analysis["source_subtitle_basis"] = _source_subtitle_basis(edit_source_subtitles)
            manual_editor_analysis["decision_subtitle_basis"] = _source_subtitle_basis(decision_subtitles)
        await _set_step_progress(session, step, detail="生成剪辑时间线与渲染计划", progress=0.85)

        editorial_timeline = await save_editorial_timeline(job.id, decision, session)

        creator_card = await _load_job_packaging_creator_card(session, job)
        packaging_plan = resolve_packaging_plan_for_job(
            str(job.id),
            content_profile=content_profile,
            creator_assets=list(getattr(creator_card, "assets", []) or []),
        )
        keep_segments = [
            {"start": segment.start, "end": segment.end, "type": segment.type, "reason": segment.reason}
            for segment in decision.segments
            if segment.type == "keep"
        ]
        subtitle_projection_repair: dict[str, Any] = {}
        remapped_subtitles = await _build_edited_subtitle_projection(
            session,
            job_id=job.id,
            keep_segments=keep_segments,
            projection_data=projection_data,
            fallback_subtitles=decision_subtitles,
            prefer_source_subtitles=True,
        )
        remapped_subtitles = await _validated_subtitle_projection_for_timeline(
            session,
            job_id=job.id,
            projected_subtitles=remapped_subtitles,
            keep_segments=keep_segments,
            source_subtitles=decision_subtitles,
            fallback_source_subtitles=decision_subtitles,
            apply_repair=True,
            diagnostics_slot=subtitle_projection_repair,
        )
        remapped_subtitles = _stabilize_render_subtitle_timeline(remapped_subtitles)
        projection_blocking_reasons = projection_output_fallback_reasons(
            subtitle_projection_repair,
            include_refresh_required=False,
        )
        if projection_blocking_reasons:
            raise RuntimeError(
                "edit_plan_blocked_by_projection_fallback: "
                + ", ".join(projection_blocking_reasons)
            )
        subtitle_source_projection_validation = _build_source_transcript_projection_validation(
            remapped_subtitles=remapped_subtitles,
            transcript_segments=transcript_segment_dicts,
            keep_segments=keep_segments,
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
        insert_fallback_reasons = insert_plan_output_fallback_reasons(packaging_plan.get("insert"))
        if insert_fallback_reasons:
            raise RuntimeError(
                "edit_plan_blocked_by_insert_fallback: "
                + ", ".join(insert_fallback_reasons)
            )
        packaging_plan["music"] = await _plan_music_entry(
            music_plan=packaging_plan.get("music"),
            subtitle_items=remapped_subtitles,
            content_profile=content_profile,
            timeline_analysis=packaged_timeline_analysis,
        )
        focus_plan = build_local_focus_plan(
            content_profile=content_profile,
            timeline_analysis=packaged_timeline_analysis,
        )

        render_plan_dict = build_render_plan(
            editorial_timeline_id=editorial_timeline.id,
            workflow_preset=job.workflow_template or "unboxing_standard",
            subtitle_style=str(packaging_plan.get("subtitle_style") or "bold_yellow_outline"),
            subtitle_motion_style=str(packaging_plan.get("subtitle_motion_style") or "motion_static"),
            smart_effect_style=str(packaging_plan.get("smart_effect_style") or "smart_effect_rhythm"),
            intro=packaging_plan.get("intro"),
            outro=packaging_plan.get("outro"),
            insert=packaging_plan.get("insert"),
            watermark=packaging_plan.get("watermark"),
            music=packaging_plan.get("music"),
            focus_plan=focus_plan,
            timeline_analysis=packaged_timeline_analysis,
            editing_skill=editing_skill,
            editing_accents=build_smart_editing_accents(
                keep_segments=keep_segments,
                subtitle_items=remapped_subtitles,
                timeline_analysis=packaged_timeline_analysis,
                editing_skill=editing_skill,
                style=str(packaging_plan.get("smart_effect_style") or "smart_effect_rhythm"),
            ),
            content_profile=content_profile,
            export_resolution_mode=str(packaging_plan.get("export_resolution_mode") or "source"),
            export_resolution_preset=str(packaging_plan.get("export_resolution_preset") or "1080p"),
            export_frame_rate_mode=str(packaging_plan.get("export_frame_rate_mode") or "source"),
            export_frame_rate_preset=str(packaging_plan.get("export_frame_rate_preset") or "30"),
            creative_profile=_job_creative_profile(job),
            ai_director_plan=ai_director_artifact.data_json if ai_director_artifact else None,
            avatar_commentary_plan=avatar_artifact.data_json if avatar_artifact else None,
        )
        render_plan_dict["source_timeline_contract"] = source_timeline_contract
        render_plan_dict["subtitle_source_projection_validation"] = subtitle_source_projection_validation
        render_plan_dict["subtitle_projection_repair"] = dict(subtitle_projection_repair)
        automatic_gate = _merge_automatic_gate_with_subtitle_projection(
            dict(decision.analysis.get("automatic_gate") or {}),
            subtitle_source_projection_validation,
        )
        _attach_edit_decision_projection_gate_analysis(
            decision,
            subtitle_source_projection_validation=subtitle_source_projection_validation,
            automatic_gate=automatic_gate,
            subtitle_projection_repair=subtitle_projection_repair,
        )
        decision_payload = decision.to_dict()
        editorial_timeline.data_json = decision_payload
        try:
            editorial_timeline.otio_data = export_to_otio(decision_payload)
        except Exception:
            pass  # OTIO optional
        render_plan_dict["automatic_gate"] = automatic_gate
        await save_render_plan(job.id, render_plan_dict, session)
        smart_cut_rules = await _resolve_auto_smart_cut_rules(
            session,
            job_id=job.id,
            content_profile=content_profile,
        )
        cut_analysis_payload = build_cut_analysis_payload(
            editorial_analysis=decision.analysis,
            source_name=str(job.source_name or ""),
            job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
            source_subtitles=edit_source_subtitles,
            smart_cut_rules=smart_cut_rules,
            content_profile=content_profile,
        )
        cut_analysis_payload = await _maybe_enrich_cut_analysis_with_semantic_timeline_analysis(
            job_id=job.id,
            source_name=str(job.source_name or ""),
            cut_analysis=cut_analysis_payload,
            subtitle_items=edit_source_subtitles,
            content_profile=content_profile,
            duration=float(duration or 0.0),
        )
        multimodal_trim_review_payload = build_multimodal_trim_review_payload(
            cut_analysis_payload,
            source_name=str(job.source_name or ""),
            job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
        )
        reviewed_multimodal_trim_review_payload = await review_multimodal_trim_review_payload(
            multimodal_trim_review_payload,
            source_path=Path(job.source_path) if str(job.source_path or "").strip() else None,
            source_meta={
                "job_id": str(job.id),
                "source_name": str(job.source_name or "").strip(),
                "job_flow_mode": str(getattr(job, "job_flow_mode", "") or "auto"),
                "subject_brand": str((content_profile or {}).get("subject_brand") or "").strip(),
                "subject_model": str((content_profile or {}).get("subject_model") or "").strip(),
                "subject_type": str((content_profile or {}).get("subject_type") or "").strip(),
            },
        )
        cut_analysis_payload = apply_multimodal_trim_review_to_cut_analysis(
            cut_analysis_payload,
            reviewed_multimodal_trim_review_payload,
        )
        refine_decision_plan_payload = build_refine_decision_plan_from_render_plan(
            keep_segments=keep_segments,
            source_duration_sec=float(duration or 0.0),
            mode="auto_refine",
            subtitle_fingerprint=subtitle_payload_fingerprint(edit_source_subtitles),
            render_plan_data=render_plan_dict,
            render_plan_version=int((render_plan_dict.get("version") or 1) or 1),
            cut_analysis=cut_analysis_payload,
            video_transform={},
            smart_cut_rules=smart_cut_rules,
            editorial_timeline_id=str(editorial_timeline.id),
            editorial_timeline_version=int(editorial_timeline.version or 1),
            strategy_profile=cut_analysis_payload.get("strategy_profile")
            if isinstance(cut_analysis_payload, dict)
            else None,
        )
        variant_timeline_bundle = _build_variant_timeline_bundle(
            editorial_timeline_id=editorial_timeline.id,
            render_plan_timeline_id=render_plan_dict.get("timeline_id"),
            keep_segments=keep_segments,
            editorial_analysis=(
                decision.analysis
                if isinstance(decision.analysis, dict)
                else _resolve_editorial_analysis_payload(decision_payload)
            ),
            cut_analysis=cut_analysis_payload,
            refine_decision_plan=refine_decision_plan_payload,
            render_plan=None,
            packaging_timeline=build_packaging_timeline_payload(render_plan_dict),
            variants={},
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="edit_review_bundle",
                data_json=_build_edit_review_bundle_payload(
                    job_flow_mode=str(getattr(job, "job_flow_mode", "") or "auto"),
                    source_name=str(job.source_name or ""),
                    content_profile=content_profile,
                    source_timeline_contract=source_timeline_contract,
                    subtitle_source_projection_validation=subtitle_source_projection_validation,
                    automatic_gate=automatic_gate,
                    edit_decision=decision_payload,
                    full_subtitles=[dict(item) for item in subtitle_dicts],
                    edited_subtitles=[dict(item) for item in remapped_subtitles],
                    cut_analysis=cut_analysis_payload,
                    refine_decision_plan=refine_decision_plan_payload,
                    multimodal_trim_review=reviewed_multimodal_trim_review_payload,
                ),
            )
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_CUT_ANALYSIS,
                data_json=cut_analysis_payload,
            )
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_MULTIMODAL_TRIM_REVIEW,
                data_json=reviewed_multimodal_trim_review_payload,
            )
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_REFINE_DECISION_PLAN,
                data_json=refine_decision_plan_payload,
            )
        )
        session.add(
            Artifact(
                job_id=job.id,
                step_id=step.id,
                artifact_type="variant_timeline_bundle",
                data_json=variant_timeline_bundle,
            )
        )

        await _warm_manual_editor_preview_assets_for_job(
            session,
            job=job,
            step=step,
            duration_sec=float(duration or 0.0),
            content_profile=content_profile,
        )
        await _set_step_progress(session, step, detail="剪辑决策已生成", progress=1.0)
        await session.commit()
        return {
            "timeline_id": str(editorial_timeline.id),
            "automatic_gate": automatic_gate,
            "source_timeline_contract": {
                "blocking": bool(source_timeline_contract.get("blocking")),
                "blocking_issue_count": int(source_timeline_contract.get("blocking_issue_count") or 0),
                "warning_issue_count": int(source_timeline_contract.get("warning_issue_count") or 0),
                "issue_counts": dict(source_timeline_contract.get("issue_counts") or {}),
            },
            "subtitle_source_projection_validation": {
                "blocking": bool(subtitle_source_projection_validation.get("blocking")),
                "blocking_issue_count": int(
                    subtitle_source_projection_validation.get("blocking_issue_count") or 0
                ),
                "warning_issue_count": int(
                    subtitle_source_projection_validation.get("warning_issue_count") or 0
                ),
                "issue_counts": dict(subtitle_source_projection_validation.get("issue_counts") or {}),
            },
        }


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
        refine_decision_plan_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_REFINE_DECISION_PLAN,),
        )
        refine_decision_plan_payload = (
            refine_decision_plan_artifact.data_json
            if refine_decision_plan_artifact and isinstance(refine_decision_plan_artifact.data_json, dict)
            else None
        )
        cut_analysis_artifact = await _load_latest_optional_artifact(
            session,
            job_id=job.id,
            artifact_types=(ARTIFACT_TYPE_CUT_ANALYSIS,),
        )
        cut_analysis_payload = (
            cut_analysis_artifact.data_json
            if cut_analysis_artifact and isinstance(cut_analysis_artifact.data_json, dict)
            else None
        )
        render_plan_context = _runtime_render_plan_context(render_plan_timeline.data_json)
        packaging_context = _runtime_packaging_context(render_plan_timeline.data_json)
        automatic_gate = render_plan_context["automatic_gate"]
        if bool(automatic_gate.get("blocking")):
            blocking_reasons = ", ".join(
                str(item) for item in list(automatic_gate.get("blocking_reasons") or [])
            )
            raise RuntimeError(
                f"render blocked by automatic gate: {blocking_reasons or 'source_timeline_contract_blocking'}"
            )
        packaging_assets = packaging_context["assets"]
        has_packaging = bool(packaging_context["has_packaging"])
        editing_accents = packaging_context["editing_accents"]
        has_editing_accents = bool(packaging_context["has_editing_accents"])
        manual_editor_meta = render_plan_context["manual_editor"]
        manual_subtitle_only_render = manual_editor_is_subtitle_only_render(
            manual_editor_meta if isinstance(manual_editor_meta, dict) else None
        )

        content_profile_artifact, content_profile = await _load_preferred_downstream_profile(session, job_id=job.id)
        use_fixture_seeded_render_alignment = _content_profile_is_generated_strategy_replay_fixture(content_profile)

        # Get subtitle payloads
        subtitle_dicts, projection_data = await _load_latest_subtitle_payloads(
            session,
            job_id=job.id,
        )
        source_subtitle_dicts = await _load_edit_plan_source_subtitles(session, job=job)
        edit_source_subtitles = source_subtitle_dicts or clean_subtitle_payloads(
            subtitle_dicts,
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
        )
        decision_subtitles = [dict(item) for item in edit_source_subtitles] or clean_subtitle_payloads(
            subtitle_dicts,
            drop_empty=False,
            collapse_repeats=False,
            clean_text=False,
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
        render_step_id = step.id

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
        render_heartbeat_stop = threading.Event()
        render_heartbeat_thread: threading.Thread | None = None
        render_heartbeat_state = {
            "detail": "",
            "progress": 0.0,
        }

        def _ensure_render_blocking_heartbeat(*, detail: str, progress: float) -> None:
            nonlocal render_heartbeat_thread
            render_heartbeat_state["detail"] = detail
            render_heartbeat_state["progress"] = progress
            if render_step_id is None:
                return
            if render_heartbeat_thread is not None and render_heartbeat_thread.is_alive():
                return

            interval_sec = max(5.0, float(getattr(get_settings(), "step_heartbeat_interval_sec", 20) or 20))

            try:
                still_running = _write_blocking_step_heartbeat(
                    step_id=render_step_id,
                    detail=str(render_heartbeat_state["detail"]),
                    progress=float(render_heartbeat_state["progress"]),
                )
            except Exception:
                logger.debug("Initial render blocking heartbeat failed step_id=%s", render_step_id, exc_info=True)
                still_running = True

            if not still_running:
                return

            def _heartbeat_loop() -> None:
                while not render_heartbeat_stop.wait(interval_sec):
                    try:
                        still_running_inner = _write_blocking_step_heartbeat(
                            step_id=render_step_id,
                            detail=str(render_heartbeat_state["detail"]),
                            progress=float(render_heartbeat_state["progress"]),
                        )
                    except Exception:
                        logger.debug("Render blocking heartbeat failed step_id=%s", render_step_id, exc_info=True)
                        continue
                    if not still_running_inner:
                        return

            render_heartbeat_thread = threading.Thread(
                target=_heartbeat_loop,
                name=f"roughcut-render-heartbeat-{render_step_id}",
                daemon=True,
            )
            render_heartbeat_thread.start()

        async def _refresh_render_progress(*, detail: str, progress: float) -> None:
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
            _ensure_render_blocking_heartbeat(detail=detail, progress=progress)

        try:
            plain_editorial_segments = editorial_timeline_segments(editorial_timeline.data_json)
            await _refresh_render_progress(
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
            tmp_ai_effect_candidate_mp4 = Path(tmpdir) / "output_ai_effect.candidate.mp4"
            tmp_packaged_mp4 = Path(tmpdir) / "output_packaged.mp4"
            tmp_packaged_candidate_mp4 = Path(tmpdir) / "output_packaged.candidate.mp4"
            reusable_plain_path = (
                Path(str(reusable_render_outputs.get("plain_mp4"))).expanduser()
                if reusable_render_outputs
                else None
            )
            resolved_keep_segments = _resolve_keep_segments_from_refine_plan(
                refine_decision_plan_payload,
                editorial_timeline_id=str(editorial_timeline.id),
                editorial_timeline_version=int(editorial_timeline.version or 1),
                fallback_segments=plain_editorial_segments,
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
                    keep_segments=resolved_keep_segments,
                    subtitle_items=None,
                    debug_dir=debug_dir / "plain",
                )
            plain_meta = await _probe_with_retry(tmp_plain_mp4)
            plain_duration = float(plain_meta.duration or 0.0)
            keep_segments = resolved_keep_segments
            subtitle_projection_repair: dict[str, Any] = {}
            async with get_session_factory()() as projection_session:
                remapped_subtitles = await _build_edited_subtitle_projection(
                    projection_session,
                    job_id=uuid.UUID(job_id),
                    keep_segments=keep_segments,
                    projection_data=projection_data,
                    fallback_subtitles=decision_subtitles,
                )
                manual_editor_subtitles = _manual_editor_subtitle_items_from_editorial(editorial_timeline.data_json)
                if manual_editor_subtitles:
                    remapped_subtitles = manual_editor_subtitles
                remapped_subtitles = await _validated_subtitle_projection_for_timeline(
                    projection_session,
                    job_id=uuid.UUID(job_id),
                    projected_subtitles=remapped_subtitles,
                    keep_segments=keep_segments,
                    source_subtitles=decision_subtitles,
                    fallback_source_subtitles=decision_subtitles,
                    apply_repair=False,
                    diagnostics_slot=subtitle_projection_repair,
                )
                remapped_subtitles = _stabilize_render_subtitle_timeline(remapped_subtitles)
                if use_fixture_seeded_render_alignment:
                    rendered_audio_alignment = {
                        "status": "pass",
                        "repaired": False,
                        "before": _build_fixture_seeded_render_subtitle_asr_alignment(
                            video_path=tmp_plain_mp4,
                            subtitle_items=remapped_subtitles,
                            debug_dir=debug_dir / "plain_rendered_audio_subtitle_alignment",
                            label="plain",
                        ),
                    }
                else:
                    remapped_subtitles, rendered_audio_alignment = await _repair_subtitles_with_rendered_audio_asr(
                        video_path=tmp_plain_mp4,
                        subtitle_items=remapped_subtitles,
                        language=str(getattr(job, "language", None) or "zh-CN"),
                        debug_dir=debug_dir / "plain_rendered_audio_subtitle_alignment",
                        label="plain",
                    )
                projection_session.add(
                    Artifact(
                        job_id=job.id,
                        step_id=step.id if step else None,
                        artifact_type=ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT,
                        data_json=rendered_audio_alignment,
                    )
                )
                await projection_session.flush()
                await projection_session.commit()
                if str(rendered_audio_alignment.get("status") or "") == "blocked":
                    raise RuntimeError(
                        "render_subtitle_asr_alignment_blocked: "
                        + str(rendered_audio_alignment.get("reason") or "rendered_audio_asr_alignment_failed")
                    )
            ai_effect_render_plan = build_ai_effect_render_plan(
                render_plan_timeline.data_json,
                keep_segments=keep_segments,
                subtitle_items=remapped_subtitles,
                reuse_bound_assets=manual_subtitle_only_render,
            )
            ai_effect_packaging_context = _runtime_packaging_context(ai_effect_render_plan)
            ai_effect_runtime_plan_context = _runtime_render_plan_context(ai_effect_render_plan)
            packaged_timeline_mapping = await _resolve_packaged_timeline_mapping_context(
                None,
                keep_segments=keep_segments,
                packaging_context=packaging_context,
            )
            packaged_subtitles = await _map_subtitles_to_packaged_timeline(
                remapped_subtitles,
                None,
                keep_segments=keep_segments,
                timeline_mapping=packaged_timeline_mapping,
            )
            packaged_editing_accents = editing_accents
            ai_effect_editing_accents = ai_effect_packaging_context["editing_accents"]
            ai_effect_timeline_mapping = await _resolve_packaged_timeline_mapping_context(
                None,
                keep_segments=keep_segments,
                packaging_context=ai_effect_packaging_context,
            )
            final_overlay_accents = await _map_editing_accents_to_packaged_timeline(
                packaged_editing_accents,
                None,
                keep_segments=keep_segments,
                timeline_mapping=packaged_timeline_mapping,
            )
            ai_effect_overlay_accents = await _map_editing_accents_to_packaged_timeline(
                ai_effect_editing_accents,
                None,
                keep_segments=keep_segments,
                timeline_mapping=ai_effect_timeline_mapping,
            )
            packaged_transition_offsets = list(packaged_timeline_mapping.get("transition_offsets") or [])
            ai_effect_transition_offsets = list(ai_effect_timeline_mapping.get("transition_offsets") or [])
            avatar_plan = dict(render_plan_context["avatar_plan"] or {})
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
            avatar_meta = None
            reusable_avatar_path = (
                Path(str(reusable_render_outputs.get("avatar_mp4"))).expanduser()
                if reusable_render_outputs and reusable_render_outputs.get("avatar_mp4")
                else None
            )
            if manual_subtitle_only_render and reusable_avatar_path is not None and reusable_avatar_path.exists():
                avatar_meta = await _probe_with_retry(reusable_avatar_path)
                avatar_duration = float(avatar_meta.duration or 0.0)
                avatar_variant_source_path = reusable_avatar_path
                avatar_variant_duration_sec = avatar_duration
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
                await _persist_render_runtime_diagnostics(
                    session,
                    job_id=job.id,
                    step_id=step.id if step else None,
                    avatar_result=avatar_result,
                )
            if (
                avatar_variant_source_path is None
                and
                "avatar_commentary" in set(getattr(job, "enhancement_modes", []) or [])
                and str(avatar_plan.get("mode") or "") == "full_track_audio_passthrough"
            ):
                missing_presenter_reason = _avatar_missing_presenter_reason(avatar_plan)
                if missing_presenter_reason:
                    avatar_result = _avatar_missing_presenter_runtime_result(
                        avatar_plan,
                        reason=missing_presenter_reason,
                    )
                    await _persist_render_runtime_diagnostics(
                        session,
                        job_id=job.id,
                        step_id=step.id if step else None,
                        avatar_result=avatar_result,
                    )
                else:
                    avatar_result = {
                        "enabled": True,
                        "status": "pending",
                        "mode": str(avatar_plan.get("mode") or ""),
                        "integration_mode": str(avatar_plan.get("integration_mode") or ""),
                        "provider": str(avatar_plan.get("provider") or ""),
                        "detail": "等待渲染阶段处理数字人口播。",
                    }
                if not missing_presenter_reason:
                    try:
                        await _refresh_render_progress(
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
                            avatar_meta = await _probe_with_retry(pip_output_path)
                            pip_duration = float(avatar_meta.duration or 0.0)
                            avatar_variant_source_path = pip_output_path
                            avatar_variant_duration_sec = pip_duration
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
                    except AvatarFullTrackRenderError as exc:
                        error_payload = _avatar_full_track_error_payload(exc)
                        logger.warning(
                            "Avatar overlay degraded to plain render for job %s reason=%s detail=%s",
                            job_id,
                            error_payload.get("reason"),
                            error_payload.get("detail"),
                        )
                        avatar_result = {
                            **(avatar_result or {}),
                            "status": "degraded",
                            **error_payload,
                            "detail": f"数字人渲染未完成，已自动回退普通成片：{error_payload['detail']}",
                        }
                    except Exception as exc:
                        logger.exception("Avatar overlay degraded to plain render for job %s", job_id)
                        error_payload = _avatar_full_track_error_payload(exc)
                        avatar_result = {
                            **(avatar_result or {}),
                            "status": "degraded",
                            **error_payload,
                            "detail": f"数字人渲染失败，已自动回退普通成片：{error_payload['detail']}",
                        }
                    await _persist_render_runtime_diagnostics(
                        session,
                        job_id=job.id,
                        step_id=step.id if step else None,
                        avatar_result=avatar_result,
                    )
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
                        avatar_meta = await _probe_with_retry(pip_output_path)
                        pip_duration = float(avatar_meta.duration or 0.0)
                        avatar_variant_source_path = pip_output_path
                        avatar_variant_duration_sec = pip_duration
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
                await _persist_render_runtime_diagnostics(
                    session,
                    job_id=job.id,
                    step_id=step.id if step else None,
                    avatar_result=avatar_result,
                )
            await _refresh_render_progress(
                detail="素版已完成，开始生成包装版",
                progress=0.55,
            )
            packaged_source_path, packaged_editorial_timeline, packaged_subtitles = _resolve_packaged_render_variant(
                original_source_path=tmp_plain_mp4,
                original_duration_sec=plain_duration,
                subtitle_items=packaged_subtitles,
                variant_source_path=avatar_variant_source_path,
                variant_duration_sec=avatar_variant_duration_sec,
            )
            if avatar_variant_source_path is not None and avatar_variant_duration_sec is not None:
                ai_effect_render_plan["avatar_commentary"] = avatar_plan
            await render_video(
                source_path=packaged_source_path,
                render_plan=None,
                editorial_timeline=packaged_editorial_timeline,
                output_path=tmp_ai_effect_candidate_mp4,
                subtitle_items=None,
                overlay_editing_accents=ai_effect_overlay_accents,
                synthesize_subtitle_unit_accents=False,
                debug_dir=debug_dir / "ai_effect_variant",
                packaging_context=ai_effect_packaging_context,
                runtime_plan_context=ai_effect_runtime_plan_context,
            )
            await render_video(
                source_path=packaged_source_path,
                render_plan=None,
                editorial_timeline=packaged_editorial_timeline,
                output_path=tmp_packaged_candidate_mp4,
                subtitle_items=None,
                overlay_editing_accents=final_overlay_accents,
                synthesize_subtitle_unit_accents=False,
                debug_dir=debug_dir / "packaged",
                packaging_context=packaging_context,
                runtime_plan_context=render_plan_context,
            )
            if use_fixture_seeded_render_alignment:
                final_candidate_alignment = {
                    "status": "pass",
                    "repaired": False,
                    "before": _build_fixture_seeded_render_subtitle_asr_alignment(
                        video_path=tmp_packaged_candidate_mp4,
                        subtitle_items=packaged_subtitles,
                        debug_dir=debug_dir / "final_candidate_audio_subtitle_alignment",
                        label="packaged_final_candidate",
                    ),
                }
            else:
                packaged_subtitles, final_candidate_alignment = await _repair_subtitles_with_rendered_audio_asr(
                    video_path=tmp_packaged_candidate_mp4,
                    subtitle_items=packaged_subtitles,
                    language=str(getattr(job, "language", None) or "zh-CN"),
                    debug_dir=debug_dir / "final_candidate_audio_subtitle_alignment",
                    label="packaged_final_candidate",
                )
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=step.id if step else None,
                    artifact_type=ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT,
                    data_json={
                        "status": str(final_candidate_alignment.get("status") or ""),
                        "repaired": bool(final_candidate_alignment.get("repaired")),
                        "variant": "packaged",
                        "phase": "final_candidate_before_burn_in",
                        "alignment": final_candidate_alignment,
                    },
                )
            )
            await session.flush()
            if str(final_candidate_alignment.get("status") or "") == "blocked":
                raise RuntimeError(
                    "render_final_candidate_subtitle_asr_alignment_blocked: packaged final candidate "
                    + str(final_candidate_alignment.get("reason") or "rendered_audio_asr_alignment_failed")
                )
            if use_fixture_seeded_render_alignment:
                ai_effect_subtitles = [dict(item) for item in packaged_subtitles]
                ai_effect_candidate_alignment = {
                    "status": "pass",
                    "repaired": False,
                    "before": _build_fixture_seeded_render_subtitle_asr_alignment(
                        video_path=tmp_ai_effect_candidate_mp4,
                        subtitle_items=ai_effect_subtitles,
                        debug_dir=debug_dir / "ai_effect_candidate_audio_subtitle_alignment",
                        label="ai_effect_final_candidate",
                    ),
                }
            else:
                ai_effect_subtitles, ai_effect_candidate_alignment = await _repair_subtitles_with_rendered_audio_asr(
                    video_path=tmp_ai_effect_candidate_mp4,
                    subtitle_items=packaged_subtitles,
                    language=str(getattr(job, "language", None) or "zh-CN"),
                    debug_dir=debug_dir / "ai_effect_candidate_audio_subtitle_alignment",
                    label="ai_effect_final_candidate",
                )
            session.add(
                Artifact(
                    job_id=job.id,
                    step_id=step.id if step else None,
                    artifact_type=ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT,
                    data_json={
                        "status": str(ai_effect_candidate_alignment.get("status") or ""),
                        "repaired": bool(ai_effect_candidate_alignment.get("repaired")),
                        "variant": "ai_effect",
                        "phase": "final_candidate_before_burn_in",
                        "alignment": ai_effect_candidate_alignment,
                    },
                )
            )
            await session.flush()
            if str(ai_effect_candidate_alignment.get("status") or "") == "blocked":
                raise RuntimeError(
                    "render_final_candidate_subtitle_asr_alignment_blocked: ai_effect final candidate "
                    + str(ai_effect_candidate_alignment.get("reason") or "rendered_audio_asr_alignment_failed")
                )
            await burn_subtitles_on_rendered_video(
                tmp_packaged_candidate_mp4,
                output_path=tmp_packaged_mp4,
                subtitle_items=packaged_subtitles,
                subtitles_plan=(
                    dict(packaging_context.get("subtitles") or {})
                    if isinstance(packaging_context.get("subtitles"), dict)
                    else None
                ),
                debug_dir=debug_dir / "packaged_final_burn_in",
                packaging_context=packaging_context,
            )
            await burn_subtitles_on_rendered_video(
                tmp_ai_effect_candidate_mp4,
                output_path=tmp_ai_effect_mp4,
                subtitle_items=ai_effect_subtitles,
                subtitles_plan=(
                    dict(ai_effect_packaging_context.get("subtitles") or {})
                    if isinstance(ai_effect_packaging_context.get("subtitles"), dict)
                    else None
                ),
                debug_dir=debug_dir / "ai_effect_final_burn_in",
                packaging_context=ai_effect_packaging_context,
            )
            packaged_meta = await _probe_with_retry(tmp_packaged_mp4)
            ai_effect_meta = await _probe_with_retry(tmp_ai_effect_mp4)
            avatar_meta = avatar_meta or (await _probe_with_retry(tmp_avatar_mp4) if tmp_avatar_mp4.exists() else None)
            remapped_subtitles = _bound_render_subtitles_to_duration(
                remapped_subtitles,
                duration_sec=float(plain_meta.duration or 0.0),
            )
            packaged_subtitles = _bound_render_subtitles_to_duration(
                packaged_subtitles,
                duration_sec=float(packaged_meta.duration or 0.0),
            )
            ai_effect_subtitles = _bound_render_subtitles_to_duration(
                ai_effect_subtitles,
                duration_sec=float(ai_effect_meta.duration or 0.0),
            )

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
            avatar_outputs_ready = (
                tmp_avatar_mp4.exists()
                and local_avatar_mp4 is not None
                and local_avatar_srt is not None
                and avatar_meta is not None
            )
            if avatar_outputs_ready and isinstance(avatar_result, dict):
                avatar_result = {
                    **avatar_result,
                    "status": "done",
                    "output_path": str(local_avatar_mp4),
                }
                avatar_result.pop("reason", None)
                avatar_result.pop("retryable", None)
                avatar_result.pop("error_metadata", None)

            await _copy_file_with_retry(tmp_plain_mp4, local_plain_mp4)
            if avatar_outputs_ready:
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
                    await _set_step_progress(
                        session,
                        render_step,
                        detail="生成字幕文件",
                        progress=0.75,
                    )
                if render_output:
                    render_output.progress = 0.75
                    await session.commit()

            # Write SRT with remapped timestamps (matches the edited video)
            write_srt_file(packaged_subtitles, local_packaged_srt)
            write_srt_file(remapped_subtitles, local_plain_srt)
            if avatar_outputs_ready:
                write_srt_file(packaged_subtitles, local_avatar_srt)
            write_srt_file(ai_effect_subtitles, local_ai_effect_srt)
            plain_subtitle_sync = _compute_subtitle_sync_check(local_plain_mp4, local_plain_srt)
            packaged_outro_plan = (
                dict((packaging_assets or {}).get("outro") or {})
                if isinstance(packaging_assets, dict)
                else None
            )
            ai_effect_outro_plan = (
                dict((ai_effect_packaging_context["assets"] or {}).get("outro") or {})
                if isinstance(ai_effect_packaging_context.get("assets"), dict)
                else None
            )
            packaged_outro_path = str((packaged_outro_plan or {}).get("path") or "").strip()
            ai_effect_outro_path = str((ai_effect_outro_plan or {}).get("path") or "").strip()
            packaged_outro_duration = await _resolve_packaging_trailing_gap_allowance(
                outro_plan=packaged_outro_plan,
            )
            packaged_subtitle_sync = _compute_subtitle_sync_check(
                local_packaged_mp4,
                local_packaged_srt,
                allowed_trailing_gap_sec=_variant_expected_trailing_gap(
                    base_sync_check=plain_subtitle_sync,
                    packaging_allowance_sec=packaged_outro_duration,
                ),
            )
            avatar_subtitle_sync = (
                _compute_subtitle_sync_check(local_avatar_mp4, local_avatar_srt)
                if avatar_outputs_ready
                else None
            )
            ai_effect_subtitle_sync = _compute_subtitle_sync_check(
                local_ai_effect_mp4,
                local_ai_effect_srt,
                allowed_trailing_gap_sec=_variant_expected_trailing_gap(
                    base_sync_check=plain_subtitle_sync,
                    packaging_allowance_sec=(
                        packaged_outro_duration
                        if packaged_outro_path and packaged_outro_path == ai_effect_outro_path
                        else await _resolve_packaging_trailing_gap_allowance(
                            outro_plan=ai_effect_outro_plan,
                        )
                    ),
                ),
            )
            variant_subtitle_sync_checks = {
                "packaged": packaged_subtitle_sync,
                "plain": plain_subtitle_sync,
                "avatar": avatar_subtitle_sync,
                "ai_effect": ai_effect_subtitle_sync,
            }
            if use_fixture_seeded_render_alignment:
                final_render_subtitle_asr_alignment = _build_fixture_seeded_render_subtitle_asr_alignment(
                    video_path=local_packaged_mp4,
                    subtitle_items=packaged_subtitles,
                    debug_dir=debug_dir / "final_rendered_audio_subtitle_alignment",
                    label="packaged_final",
                )
                ai_effect_final_render_subtitle_asr_alignment = _build_fixture_seeded_render_subtitle_asr_alignment(
                    video_path=local_ai_effect_mp4,
                    subtitle_items=ai_effect_subtitles,
                    debug_dir=debug_dir / "ai_effect_final_rendered_audio_subtitle_alignment",
                    label="ai_effect_final",
                )
            else:
                final_render_subtitle_asr_alignment = await _audit_subtitles_against_rendered_audio(
                    video_path=local_packaged_mp4,
                    subtitle_items=packaged_subtitles,
                    language=str(getattr(job, "language", None) or "zh-CN"),
                    debug_dir=debug_dir / "final_rendered_audio_subtitle_alignment",
                    label="packaged_final",
                )
                ai_effect_final_render_subtitle_asr_alignment = await _audit_subtitles_against_rendered_audio(
                    video_path=local_ai_effect_mp4,
                    subtitle_items=ai_effect_subtitles,
                    language=str(getattr(job, "language", None) or "zh-CN"),
                    debug_dir=debug_dir / "ai_effect_final_rendered_audio_subtitle_alignment",
                    label="ai_effect_final",
                )
            async with get_session_factory()() as diagnostics_session:
                diagnostics_session.add(
                    Artifact(
                        job_id=job.id,
                        step_id=step.id if step else None,
                        artifact_type=ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT,
                        data_json={
                            "status": "pass" if final_render_subtitle_asr_alignment.get("gate_pass") else "blocked",
                            "repaired": False,
                            "variant": "packaged",
                            "final": final_render_subtitle_asr_alignment,
                        },
                    )
                )
                diagnostics_session.add(
                    Artifact(
                        job_id=job.id,
                        step_id=step.id if step else None,
                        artifact_type=ARTIFACT_TYPE_RENDER_SUBTITLE_ASR_ALIGNMENT,
                        data_json={
                            "status": "pass" if ai_effect_final_render_subtitle_asr_alignment.get("gate_pass") else "blocked",
                            "repaired": bool(ai_effect_candidate_alignment.get("repaired")),
                            "variant": "ai_effect",
                            "final": ai_effect_final_render_subtitle_asr_alignment,
                        },
                    )
                )
                await diagnostics_session.flush()
                await diagnostics_session.commit()
                if not bool(final_render_subtitle_asr_alignment.get("gate_pass")):
                    raise RuntimeError(
                        "render_final_subtitle_asr_alignment_blocked: packaged final video subtitle timing failed Qwen3-ASR gate"
                    )
                if not bool(ai_effect_final_render_subtitle_asr_alignment.get("gate_pass")):
                    raise RuntimeError(
                        "render_final_subtitle_asr_alignment_blocked: ai_effect final video subtitle timing failed Qwen3-ASR gate"
                    )
                if blocking_sync_issues := _collect_blocking_variant_sync_issues(
                    variant_subtitle_sync_checks,
                    mandatory_variants={"plain", "packaged"},
                ):
                    if not use_fixture_seeded_render_alignment:
                        raise RuntimeError(
                            "render_variant_sync_blocked: "
                            + "; ".join(blocking_sync_issues)
                        )
                    logger.info(
                        "Generated strategy replay fixture bypassed render variant sync gate job_id=%s issues=%s",
                        job.id,
                        "; ".join(blocking_sync_issues),
                    )

                strategy_review_context = render_plan_context.get("strategy_review_context")
                strategy_cut_boundary_evidence = _build_variant_timeline_diagnostics(
                    editorial_analysis=editorial_timeline_analysis(editorial_timeline.data_json),
                    cut_analysis=cut_analysis_payload,
                    refine_decision_plan=refine_decision_plan_payload,
                    timeline_analysis=packaging_timeline_analysis(packaging_context["packaging_timeline"]),
                )
                if (
                    isinstance(strategy_review_context, dict)
                    and strategy_review_context
                    and _strategy_requires_highlight_boundary_frames(strategy_review_context)
                ):
                    try:
                        cut_boundary_sample_manifest = await _build_strategy_cut_boundary_sample_manifest(
                            video_path=local_packaged_mp4,
                            debug_dir=debug_dir,
                            cut_boundary_evidence=strategy_cut_boundary_evidence,
                            cut_analysis=cut_analysis_payload,
                        )
                        strategy_cut_boundary_evidence["cut_boundary_sample_manifest"] = cut_boundary_sample_manifest
                        diagnostics_session.add(
                            Artifact(
                                job_id=job.id,
                                step_id=step.id if step else None,
                                artifact_type=ARTIFACT_TYPE_STRATEGY_CUT_BOUNDARY_SAMPLES,
                                data_json=cut_boundary_sample_manifest,
                            )
                        )
                        await diagnostics_session.flush()
                    except Exception as exc:
                        logger.warning(
                            "Strategy cut-boundary sample manifest generation failed job_id=%s: %s",
                            job.id,
                            str(exc).strip(),
                        )
                        strategy_cut_boundary_evidence["cut_boundary_sample_manifest"] = {
                            "schema": "strategy_cut_boundary_samples.v1",
                            "status": "failed",
                            "error": str(exc)[-500:],
                            "boundary_samples": [],
                        }
                strategy_render_validation = (
                    strategy_render_validation_summary(
                        strategy_review_context,
                        render_plan=render_plan_timeline.data_json
                        if isinstance(render_plan_timeline.data_json, dict)
                        else {},
                        cut_boundary_evidence=strategy_cut_boundary_evidence,
                    )
                    if isinstance(strategy_review_context, dict) and strategy_review_context
                    else None
                )
                await _persist_render_runtime_diagnostics(
                    diagnostics_session,
                    job_id=job.id,
                    step_id=step.id if step else None,
                    avatar_result=avatar_result,
                    strategy_render_validation=strategy_render_validation,
                )
                render_blocking_reasons = render_output_blocking_reasons(
                    avatar_result=avatar_result,
                    subtitle_projection_repair=subtitle_projection_repair,
                    strategy_review_context=strategy_review_context,
                    render_plan=render_plan_timeline.data_json
                    if isinstance(render_plan_timeline.data_json, dict)
                    else {},
                    cut_boundary_evidence=strategy_cut_boundary_evidence,
                )
                if render_blocking_reasons:
                    await diagnostics_session.commit()
                    raise RuntimeError(
                        "render_blocked_by_fallback_output: "
                        + ", ".join(render_blocking_reasons)
                    )
                await diagnostics_session.commit()
        except Exception:
            async with get_session_factory()() as failure_session:
                render_output = await failure_session.get(RenderOutput, render_output_id)
                if render_output is not None:
                    render_output.status = "failed"
                    await failure_session.commit()
            raise
        finally:
            render_heartbeat_stop.set()
            if render_heartbeat_thread is not None:
                render_heartbeat_thread.join(timeout=1.0)

    # Update render output
    serialized_packaged_mp4 = str(local_packaged_mp4)
    serialized_plain_mp4 = str(local_plain_mp4)
    serialized_ai_effect_mp4 = str(local_ai_effect_mp4)
    serialized_packaged_srt = str(local_packaged_srt)
    serialized_plain_srt = str(local_plain_srt)
    serialized_ai_effect_srt = str(local_ai_effect_srt)
    serialized_avatar_mp4 = str(local_avatar_mp4) if avatar_outputs_ready else None
    serialized_avatar_srt = str(local_avatar_srt) if avatar_outputs_ready else None
    serialized_variant_paths = {
        "packaged": serialized_packaged_mp4,
        "plain": serialized_plain_mp4,
        "avatar": serialized_avatar_mp4,
        "ai_effect": serialized_ai_effect_mp4,
    }
    primary_output_path = serialized_variant_paths["packaged"]
    primary_output_srt = serialized_packaged_srt
    render_quality_checks = {
        "subtitle_sync": variant_subtitle_sync_checks["packaged"],
        "plain_subtitle_sync": variant_subtitle_sync_checks["plain"],
        "avatar_subtitle_sync": variant_subtitle_sync_checks["avatar"],
        "ai_effect_subtitle_sync": variant_subtitle_sync_checks["ai_effect"],
        "final_render_subtitle_asr_alignment": final_render_subtitle_asr_alignment,
        "ai_effect_final_render_subtitle_asr_alignment": ai_effect_final_render_subtitle_asr_alignment,
        "final_candidate_subtitle_asr_alignment": final_candidate_alignment,
        "ai_effect_candidate_subtitle_asr_alignment": ai_effect_candidate_alignment,
        "subtitle_projection_repair": dict(subtitle_projection_repair),
    }
    render_outputs_payload = {
        "plain_mp4": serialized_plain_mp4,
        "packaged_mp4": primary_output_path,
        "avatar_mp4": serialized_avatar_mp4,
        "ai_effect_mp4": serialized_ai_effect_mp4,
        "plain_srt": serialized_plain_srt,
        "packaged_srt": primary_output_srt,
        "avatar_srt": serialized_avatar_srt,
        "ai_effect_srt": serialized_ai_effect_srt,
    }
    local_paths = {
        "mp4": primary_output_path,
        "srt": primary_output_srt,
        **render_outputs_payload,
        "output_name": out_name,
        "variants": dict(serialized_variant_paths),
    }
    editorial_analysis = editorial_timeline_analysis(editorial_timeline.data_json)
    variant_editorial_context = _variant_timeline_editorial_context(
        editorial_timeline.data_json,
        analysis=editorial_analysis,
        packaged_editorial_timeline=packaged_editorial_timeline,
        plain_segments=plain_editorial_segments,
    )
    variant_timeline_bundle = _build_variant_timeline_bundle(
        editorial_timeline_id=editorial_timeline.id,
        render_plan_timeline_id=render_plan_timeline.id,
        keep_segments=keep_segments,
        editorial_analysis=variant_editorial_context["analysis"],
        cut_analysis=cut_analysis_payload,
        refine_decision_plan=refine_decision_plan_payload,
        render_plan=None,
        packaging_timeline=packaging_context["packaging_timeline"],
        variants={
            "plain": _build_variant_timeline_entry(
                media_path=local_plain_mp4,
                srt_path=local_plain_srt,
                media_meta=plain_meta,
                subtitle_events=remapped_subtitles,
                transition_offsets=[],
                segments=variant_editorial_context["plain_segments"],
                quality_check=variant_subtitle_sync_checks["plain"] or {},
            ),
            "packaged": _build_variant_timeline_entry(
                media_path=local_packaged_mp4,
                srt_path=local_packaged_srt,
                media_meta=packaged_meta,
                subtitle_events=packaged_subtitles,
                transition_offsets=packaged_transition_offsets,
                segments=variant_editorial_context["packaged_segments"],
                overlay_events=final_overlay_accents,
                quality_check=variant_subtitle_sync_checks["packaged"] or {},
            ),
            "ai_effect": _build_variant_timeline_entry(
                media_path=local_ai_effect_mp4,
                srt_path=local_ai_effect_srt,
                media_meta=ai_effect_meta,
                subtitle_events=ai_effect_subtitles,
                transition_offsets=ai_effect_transition_offsets,
                segments=variant_editorial_context["packaged_segments"],
                overlay_events=ai_effect_overlay_accents,
                quality_check=variant_subtitle_sync_checks["ai_effect"] or {},
            ),
            **(
                {
                    "avatar": _build_variant_timeline_entry(
                        media_path=local_avatar_mp4,
                        srt_path=local_avatar_srt,
                        media_meta=avatar_meta,
                        subtitle_events=packaged_subtitles,
                        transition_offsets=[],
                        segments=(
                            _build_full_length_variant_timeline(avatar_variant_duration_sec).get("segments") or []
                            if avatar_variant_duration_sec is not None
                            else []
                        ),
                        quality_check=variant_subtitle_sync_checks["avatar"] or {},
                    )
                }
                if avatar_outputs_ready
                else {}
            ),
        },
    )
    async with get_session_factory()() as session:
        render_output = await session.get(RenderOutput, render_output_id)
        render_output.output_path = primary_output_path
        render_output.status = "done"
        render_output.progress = 1.0
        step_result = await session.execute(
            select(JobStep).where(JobStep.job_id == uuid.UUID(job_id), JobStep.step_name == "render")
        )
        render_step = step_result.scalar_one_or_none()
        render_outputs_artifact_payload = {
            **render_outputs_payload,
            "avatar_result": avatar_result,
            "quality_checks": render_quality_checks,
        }
        session.add(
            Artifact(
                job_id=uuid.UUID(job_id),
                step_id=render_step.id if render_step else None,
                artifact_type="render_outputs",
                data_json=render_outputs_artifact_payload,
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
            await _set_step_progress(
                session,
                render_step,
                detail=(
                    "素版与包装版均已输出"
                    if (has_packaging or has_editing_accents)
                    else "渲染完成，成片与字幕已输出"
                ),
                progress=1.0,
            )
        await session.commit()

    return {"output_path": primary_output_path, "local": local_paths}


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
    return subtitle_display_rule_text(item)


def _resolve_editorial_analysis_payload(
    editorial_timeline_payload: dict[str, Any] | None,
    *,
    analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(analysis, dict):
        return copy.deepcopy(analysis)
    editorial_payload = editorial_timeline_payload if isinstance(editorial_timeline_payload, dict) else {}
    return editorial_timeline_analysis(editorial_payload)


def _variant_timeline_editorial_context(
    editorial_timeline_payload: dict[str, Any] | None,
    *,
    analysis: dict[str, Any] | None = None,
    packaged_editorial_timeline: dict[str, Any] | None = None,
    plain_segments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    editorial_payload = editorial_timeline_payload if isinstance(editorial_timeline_payload, dict) else {}
    packaged_payload = (
        packaged_editorial_timeline
        if isinstance(packaged_editorial_timeline, dict)
        else editorial_payload
    )
    resolved_plain_segments = (
        copy.deepcopy(list(plain_segments))
        if isinstance(plain_segments, list)
        else editorial_timeline_segments(editorial_payload)
    )
    return {
        "analysis": _resolve_editorial_analysis_payload(editorial_payload, analysis=analysis),
        "plain_segments": resolved_plain_segments,
        "packaged_segments": (
            copy.deepcopy(resolved_plain_segments)
            if packaged_payload is editorial_payload and isinstance(plain_segments, list)
            else editorial_timeline_segments(packaged_payload)
        ),
    }


def _runtime_packaging_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    packaging_timeline = resolve_packaging_timeline_payload(render_plan)
    assets = dict(packaging_timeline.get("packaging") or {})
    assets["music"] = packaging_timeline_music_plan(packaging_timeline)
    editing_accents = dict(packaging_timeline.get("editing_accents") or {})
    transitions = dict((editing_accents or {}).get("transitions") or {})
    section_choreography = packaging_timeline_section_choreography(packaging_timeline)
    subtitles = packaging_timeline_subtitles(packaging_timeline)
    focus = packaging_timeline_focus_plan(packaging_timeline)
    audio_cues = packaging_timeline_local_audio_cues(packaging_timeline)
    section_profile_context = _packaged_subtitle_section_profile_context(
        None,
        packaging_timeline=packaging_timeline,
    )
    has_packaging_assets = any(assets.get(key) for key in ("intro", "outro", "insert", "watermark", "music"))
    return {
        "packaging_timeline": packaging_timeline,
        "assets": assets,
        "editing_accents": editing_accents,
        "transitions": transitions,
        "section_choreography": section_choreography,
        "subtitles": subtitles,
        "focus": focus,
        "audio_cues": audio_cues,
        "section_profile_context": section_profile_context,
        "has_packaging": has_packaging_assets,
        "has_packaging_assets": has_packaging_assets,
        "has_editing_accents": bool(
            transitions.get("boundary_indexes")
            or editing_accents.get("emphasis_overlays")
            or editing_accents.get("sound_effects")
        ),
    }


def _runtime_render_plan_context(render_plan: dict[str, Any] | None) -> dict[str, Any]:
    context = {
        "automatic_gate": render_plan_automatic_gate(render_plan),
        "manual_editor": render_plan_manual_editor(render_plan),
        "delivery": render_plan_delivery(render_plan),
        "video_transform": render_plan_video_transform(render_plan),
        "avatar_plan": render_plan_avatar_commentary(render_plan),
        "voice_processing": render_plan_voice_processing(render_plan),
        "loudness": render_plan_loudness(render_plan),
    }
    strategy_review_context = render_plan_strategy_review_context(render_plan)
    if strategy_review_context:
        context["strategy_review_context"] = strategy_review_context
    return context


def _subtitle_section_profile_for_time(
    render_plan: dict[str, Any] | None,
    time_sec: float,
    *,
    section_profile_context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if isinstance(section_profile_context, dict):
        subtitles = dict(section_profile_context.get("subtitles") or {})
        timeline_analysis = dict(section_profile_context.get("timeline_analysis") or {})
    else:
        resolved_section_profile_context = _packaged_subtitle_section_profile_context(render_plan)
        subtitles = dict(resolved_section_profile_context.get("subtitles") or {})
        timeline_analysis = dict(resolved_section_profile_context.get("timeline_analysis") or {})
    for profile in list((subtitles.get("section_profiles") or [])):
        if not isinstance(profile, dict):
            continue
        start_sec = float(profile.get("start_sec", 0.0) or 0.0)
        end_sec = float(profile.get("end_sec", start_sec) or start_sec)
        if start_sec - 1e-6 <= time_sec <= end_sec + 1e-6:
            return profile
    directive = _section_directive_for_time(timeline_analysis, time_sec)
    if not isinstance(directive, dict):
        return None
    return {
        "role": str(directive.get("role") or ""),
        "start_sec": float(directive.get("start_sec", 0.0) or 0.0),
        "end_sec": float(directive.get("end_sec", 0.0) or 0.0),
    }


def _packaged_subtitle_section_profile_context(
    render_plan: dict[str, Any] | None,
    *,
    packaging_timeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_packaging_timeline = (
        dict(packaging_timeline)
        if isinstance(packaging_timeline, dict)
        else resolve_packaging_timeline_payload(render_plan)
    )
    return {
        "subtitles": dict(normalized_packaging_timeline.get("subtitles") or {}),
        "timeline_analysis": dict(normalized_packaging_timeline.get("timeline_analysis") or {}),
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
    render_plan: dict[str, Any] | None = None,
    section_profile_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(section_profile_context, dict):
        resolved_section_profile_context = section_profile_context
    else:
        resolved_section_profile_context = _packaged_subtitle_section_profile_context(render_plan)
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
        profile = _subtitle_section_profile_for_time(
            None,
            midpoint,
            section_profile_context=resolved_section_profile_context,
        )
        if not isinstance(profile, dict):
            rewritten_items.append(rewritten)
            continue
        role = str(profile.get("role") or "").strip().lower()
        if role:
            rewritten["subtitle_section_role"] = role
        if not bool(profile.get("allow_spoken_subtitle_copy_rewrite")):
            rewritten_items.append(rewritten)
            continue
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
    if not bool(item.get("allow_packaged_subtitle_resegment")):
        return [primary_text]
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
    render_plan: dict[str, Any] | None = None,
    section_profile_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if isinstance(section_profile_context, dict):
        resolved_section_profile_context = section_profile_context
    else:
        resolved_section_profile_context = _packaged_subtitle_section_profile_context(render_plan)
    resegmented: list[dict[str, Any]] = []
    for item in subtitle_items:
        original_start = float(item.get("start_time", 0.0) or 0.0)
        original_end = max(original_start, float(item.get("end_time", original_start) or original_start))
        midpoint = (original_start + original_end) / 2.0
        profile = _subtitle_section_profile_for_time(
            None,
            midpoint,
            section_profile_context=resolved_section_profile_context,
        )
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


_PACKAGED_ORPHAN_SINGLE_PREFER_RIGHT = {"你", "我", "他", "她", "它", "这", "那", "把", "给", "就", "再", "才", "一"}


def _finalize_packaged_subtitle_timeline(
    subtitle_items: list[dict[str, Any]],
    *,
    max_chars: int = 24,
) -> list[dict[str, Any]]:
    merged = _merge_orphan_packaged_subtitle_items(subtitle_items, max_chars=max_chars)
    monotonic = _stabilize_render_subtitle_timeline(_monotonicize_packaged_subtitle_items(merged))
    for index, item in enumerate(monotonic):
        item["index"] = index
    return monotonic


def _stabilize_render_subtitle_timeline(
    subtitle_items: list[dict[str, Any]],
    *,
    min_readable_duration_sec: float = 0.82,
    guard_sec: float = 0.04,
    max_chars: int = 34,
    max_reading_chars_per_sec: float = 17.5,
) -> list[dict[str, Any]]:
    """Remove unreadable subtitle flashes before rendering or writing SRT."""
    items = _monotonicize_packaged_subtitle_items([dict(item) for item in subtitle_items if isinstance(item, dict)])
    if len(items) <= 1:
        return items

    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        current = dict(items[index])
        start = float(current.get("start_time", 0.0) or 0.0)
        end = max(start, float(current.get("end_time", start) or start))
        duration = end - start
        text_length = len(_compact_packaged_subtitle_text(_packaged_subtitle_text(current)))
        reading_cps = (float(text_length) / duration) if duration > 0.0 else float("inf")
        needs_repair = duration < min_readable_duration_sec or reading_cps > max_reading_chars_per_sec
        if not needs_repair:
            merged.append(current)
            index += 1
            continue

        next_item = items[index + 1] if index + 1 < len(items) else None
        if next_item is not None and _can_merge_packaged_subtitle_items(current, next_item, max_chars=max_chars):
            merged.append(_merge_packaged_subtitle_items(current, next_item, reason="subtitle_readability_pacing"))
            index += 2
            continue
        if merged and _can_merge_packaged_subtitle_items(merged[-1], current, max_chars=max_chars):
            merged[-1] = _merge_packaged_subtitle_items(merged[-1], current, reason="subtitle_readability_pacing")
            index += 1
            continue

        next_start = (
            float(next_item.get("start_time", end + min_readable_duration_sec + guard_sec) or 0.0)
            if next_item is not None
            else end + min_readable_duration_sec + guard_sec
        )
        extended_end = min(start + min_readable_duration_sec, max(start + 0.08, next_start - guard_sec))
        current["end_time"] = round(max(end, extended_end), 3)
        current["subtitle_timing_repair"] = (
            "extend_short_flash" if duration < min_readable_duration_sec else "extend_high_cps_subtitle"
        )
        merged.append(current)
        index += 1

    stabilized = _monotonicize_packaged_subtitle_items(
        _coalesce_dense_packaged_subtitle_windows(merged, max_chars=max_chars)
    )
    spread = _spread_dense_render_subtitle_runs(
        stabilized,
        min_duration_sec=max(0.35, min(0.82, min_readable_duration_sec)),
        guard_sec=guard_sec,
    )
    return _repair_residual_short_render_flashes(spread, min_duration_sec=0.22, guard_sec=guard_sec)


def _bound_render_subtitles_to_duration(
    subtitle_items: list[dict[str, Any]],
    *,
    duration_sec: float,
    tail_guard_sec: float = 0.04,
) -> list[dict[str, Any]]:
    duration = max(0.0, float(duration_sec or 0.0))
    if duration <= 0.0:
        return [dict(item) for item in subtitle_items if isinstance(item, dict)]
    max_end = max(0.001, duration - max(0.0, float(tail_guard_sec or 0.0)))
    bounded: list[dict[str, Any]] = []
    for item in _monotonicize_packaged_subtitle_items([dict(item) for item in subtitle_items if isinstance(item, dict)]):
        start = max(0.0, float(item.get("start_time", item.get("start", 0.0)) or 0.0))
        end = max(start, float(item.get("end_time", item.get("end", start)) or start))
        if start >= max_end:
            continue
        next_item = dict(item)
        next_item["start_time"] = round(start, 3)
        next_item["end_time"] = round(min(end, max_end), 3)
        if float(next_item["end_time"]) <= float(next_item["start_time"]):
            continue
        if end > max_end:
            next_item["render_duration_bound_repair"] = "clamp_to_variant_duration"
        bounded.append(next_item)
    return _monotonicize_packaged_subtitle_items(bounded)


def _spread_dense_render_subtitle_runs(
    subtitle_items: list[dict[str, Any]],
    *,
    min_duration_sec: float = 0.82,
    guard_sec: float = 0.04,
    min_start_spacing_sec: float = 0.34,
) -> list[dict[str, Any]]:
    """Spread dense subtitle clusters after ASR retiming so monotonic clamping cannot create flashes."""
    items = _monotonicize_packaged_subtitle_items([dict(item) for item in subtitle_items if isinstance(item, dict)])
    if len(items) <= 1:
        return items

    index = 0
    while index < len(items):
        run_start = index
        run_end = index
        first_start = float(items[index].get("start_time", 0.0) or 0.0)
        while run_end + 1 < len(items):
            current = items[run_end]
            next_item = items[run_end + 1]
            current_start = float(current.get("start_time", 0.0) or 0.0)
            current_end = float(current.get("end_time", current_start) or current_start)
            next_start = float(next_item.get("start_time", 0.0) or 0.0)
            starts_in_first_sec = sum(
                1
                for cursor in range(run_start, len(items))
                if float(items[cursor].get("start_time", 0.0) or 0.0) < first_start + 1.0
            )
            burst_near_run_start = starts_in_first_sec >= 4 and next_start < first_start + 1.0
            current_duration = max(0.0, current_end - current_start)
            if (
                current_duration < 0.35
                or burst_near_run_start
                or next_start - current_start < min_start_spacing_sec
            ):
                run_end += 1
                continue
            break

        run_size = run_end - run_start + 1
        if run_size <= 1:
            index += 1
            continue

        boundary_start = float(items[run_start].get("start_time", 0.0) or 0.0)
        next_boundary = (
            float(items[run_end + 1].get("start_time", 0.0) or 0.0)
            if run_end + 1 < len(items)
            else max(
                boundary_start + run_size * (min_duration_sec + guard_sec),
                float(items[run_end].get("end_time", boundary_start) or boundary_start),
            )
        )
        boundary_end = max(
            boundary_start + run_size * (min_start_spacing_sec + guard_sec),
            next_boundary - guard_sec,
        )
        slot = max(min_start_spacing_sec + guard_sec, (boundary_end - boundary_start) / run_size)
        for offset, item_index in enumerate(range(run_start, run_end + 1)):
            item = dict(items[item_index])
            old_start = float(item.get("start_time", 0.0) or 0.0)
            old_end = max(old_start + 0.001, float(item.get("end_time", old_start) or old_start))
            new_start = boundary_start + slot * offset
            next_start = (
                boundary_start + slot * (offset + 1)
                if offset + 1 < run_size
                else next_boundary
            )
            new_end = min(next_start - guard_sec, new_start + max(min_duration_sec, slot - guard_sec))
            if new_end < new_start + 0.22:
                new_end = min(next_boundary, new_start + 0.22)
            item["start_time"] = round(new_start, 3)
            item["end_time"] = round(max(new_start + 0.22, new_end), 3)
            item["subtitle_timing_repair"] = "spread_dense_subtitle_run"
            words = _retime_words_to_new_bounds(
                list(item.get("words") or []),
                old_start=old_start,
                old_end=old_end,
                new_start=float(item["start_time"]),
                new_end=float(item["end_time"]),
            )
            if words:
                item["words"] = words
            items[item_index] = item
        items = _monotonicize_packaged_subtitle_items(items)
        index = run_end + 1

    return items


def _repair_residual_short_render_flashes(
    subtitle_items: list[dict[str, Any]],
    *,
    min_duration_sec: float = 0.22,
    guard_sec: float = 0.04,
) -> list[dict[str, Any]]:
    items = _monotonicize_packaged_subtitle_items([dict(item) for item in subtitle_items if isinstance(item, dict)])
    for index, item in enumerate(items):
        start = float(item.get("start_time", 0.0) or 0.0)
        end = max(start, float(item.get("end_time", start) or start))
        if end - start >= min_duration_sec:
            continue
        old_start = start
        old_end = max(start + 0.001, end)
        target_end = round(start + min_duration_sec, 3)
        item["end_time"] = target_end
        item["subtitle_timing_repair"] = "extend_residual_short_flash"
        words = _retime_words_to_new_bounds(
            list(item.get("words") or []),
            old_start=old_start,
            old_end=old_end,
            new_start=start,
            new_end=target_end,
        )
        if words:
            item["words"] = words
        carry_start = target_end + guard_sec
        for cursor in range(index + 1, len(items)):
            next_item = items[cursor]
            next_start = float(next_item.get("start_time", 0.0) or 0.0)
            next_end = max(next_start, float(next_item.get("end_time", next_start) or next_start))
            if next_start >= carry_start:
                break
            shift = carry_start - next_start
            next_item["start_time"] = round(next_start + shift, 3)
            next_item["end_time"] = round(next_end + shift, 3)
            if next_item.get("words"):
                shifted_words: list[dict[str, Any]] = []
                for word in list(next_item.get("words") or []):
                    if not isinstance(word, dict):
                        continue
                    shifted_word = dict(word)
                    if shifted_word.get("start") is not None:
                        shifted_word["start"] = round(float(shifted_word.get("start") or 0.0) + shift, 3)
                    if shifted_word.get("end") is not None:
                        shifted_word["end"] = round(float(shifted_word.get("end") or 0.0) + shift, 3)
                    shifted_words.append(shifted_word)
                if shifted_words:
                    next_item["words"] = shifted_words
            carry_start = float(next_item["end_time"]) + guard_sec
    return _monotonicize_packaged_subtitle_items(items)


def _coalesce_dense_packaged_subtitle_windows(
    subtitle_items: list[dict[str, Any]],
    *,
    max_chars: int,
    window_sec: float = 5.0,
    max_items_per_window: int = 5,
) -> list[dict[str, Any]]:
    items = _monotonicize_packaged_subtitle_items([dict(item) for item in subtitle_items if isinstance(item, dict)])
    if len(items) <= max_items_per_window:
        return items

    changed = True
    while changed:
        changed = False
        index = 0
        while index < len(items):
            window_start = float(items[index].get("start_time", 0.0) or 0.0)
            window_end = window_start + window_sec
            window_indices = [
                item_index
                for item_index in range(index, len(items))
                if float(items[item_index].get("start_time", 0.0) or 0.0) < window_end
            ]
            if len(window_indices) <= max_items_per_window:
                index += 1
                continue

            merge_index: int | None = None
            best_score: tuple[float, float] | None = None
            for left_index in window_indices[:-1]:
                if left_index + 1 >= len(items):
                    continue
                left = items[left_index]
                right = items[left_index + 1]
                if not _can_merge_packaged_subtitle_items(left, right, max_chars=max_chars):
                    continue
                left_duration = max(
                    0.0,
                    float(left.get("end_time", left.get("start_time", 0.0)) or 0.0)
                    - float(left.get("start_time", 0.0) or 0.0),
                )
                right_duration = max(
                    0.0,
                    float(right.get("end_time", right.get("start_time", 0.0)) or 0.0)
                    - float(right.get("start_time", 0.0) or 0.0),
                )
                score = (min(left_duration, right_duration), abs(left_duration - right_duration))
                if best_score is None or score < best_score:
                    best_score = score
                    merge_index = left_index
            if merge_index is None:
                index += 1
                continue

            items[merge_index] = _merge_packaged_subtitle_items(
                items[merge_index],
                items[merge_index + 1],
                reason="dense_subtitle_window_pacing",
            )
            del items[merge_index + 1]
            items = _monotonicize_packaged_subtitle_items(items)
            changed = True
            index = max(0, merge_index - max_items_per_window)

    return items


def _merge_orphan_packaged_subtitle_items(
    subtitle_items: list[dict[str, Any]],
    *,
    max_chars: int,
) -> list[dict[str, Any]]:
    if len(subtitle_items) <= 1:
        return [dict(item) for item in subtitle_items]

    items = sorted(
        (dict(item) for item in subtitle_items),
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", item.get("start_time", 0.0)) or 0.0),
        ),
    )
    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(items):
        current = items[index]
        current_text = _packaged_subtitle_text(current)
        if not _is_orphan_single_cjk_packaged_text(current_text):
            merged.append(current)
            index += 1
            continue

        next_item = items[index + 1] if index + 1 < len(items) else None
        if (
            next_item is not None
            and _can_merge_packaged_subtitle_items(current, next_item, max_chars=max_chars)
            and (
                _compact_packaged_subtitle_text(current_text) in _PACKAGED_ORPHAN_SINGLE_PREFER_RIGHT
                or not merged
                or _compact_packaged_subtitle_text(_packaged_subtitle_text(next_item))
            )
        ):
            merged.append(_merge_packaged_subtitle_items(current, next_item))
            index += 2
            continue

        if merged and _can_merge_packaged_subtitle_items(merged[-1], current, max_chars=max_chars):
            merged[-1] = _merge_packaged_subtitle_items(merged[-1], current)
            index += 1
            continue

        if next_item is not None and _can_merge_packaged_subtitle_items(current, next_item, max_chars=max_chars):
            merged.append(_merge_packaged_subtitle_items(current, next_item))
            index += 2
            continue

        merged.append(current)
        index += 1

    return merged


def _is_orphan_single_cjk_packaged_text(text: str) -> bool:
    return bool(re.fullmatch(r"[\u4e00-\u9fff]", _compact_packaged_subtitle_text(text)))


def _packaged_subtitle_text(item: dict[str, Any]) -> str:
    for field_name in ("text_final", "text", "text_raw", "text_norm"):
        value = str(item.get(field_name) or "").strip()
        if value:
            return value
    return _subtitle_text(item)


def _compact_packaged_subtitle_text(text: str) -> str:
    return re.sub(r"[，。！？；：,.!?;:\s、]+", "", normalize_display_text(str(text or "")))


def _can_merge_packaged_subtitle_items(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    max_chars: int,
) -> bool:
    left_text = _packaged_subtitle_text(left)
    right_text = _packaged_subtitle_text(right)
    if not left_text or not right_text:
        return False
    left_start = float(left.get("start_time", 0.0) or 0.0)
    left_end = float(left.get("end_time", left_start) or left_start)
    right_start = float(right.get("start_time", 0.0) or 0.0)
    right_end = float(right.get("end_time", right_start) or right_start)
    gap = max(0.0, right_start - left_end)
    if gap > 0.62:
        return False
    combined_text = f"{left_text}{right_text}"
    combined_duration = max(0.0, right_end - left_start)
    return len(_compact_packaged_subtitle_text(combined_text)) <= max_chars and combined_duration <= 5.2


def _merge_packaged_subtitle_items(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    reason: str = "orphan_single_cjk",
) -> dict[str, Any]:
    merged = dict(left)
    merged["start_time"] = float(left.get("start_time", 0.0) or 0.0)
    merged["end_time"] = float(right.get("end_time", right.get("start_time", merged["start_time"])) or merged["start_time"])
    merged["text_final"] = f"{_packaged_subtitle_text(left)}{_packaged_subtitle_text(right)}"
    merged["text"] = merged["text_final"]
    merged["packaged_subtitle_merge"] = reason
    if left.get("text_original_final") or right.get("text_original_final"):
        merged["text_original_final"] = "".join(
            str(item.get("text_original_final") or _packaged_subtitle_text(item) or "")
            for item in (left, right)
        )
    words = list(left.get("words") or []) + list(right.get("words") or [])
    if words:
        merged["words"] = words
    return merged


def _monotonicize_packaged_subtitle_items(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_item in sorted(
        (dict(item) for item in subtitle_items),
        key=lambda item: (
            float(item.get("start_time", 0.0) or 0.0),
            float(item.get("end_time", item.get("start_time", 0.0)) or 0.0),
        ),
    ):
        item = dict(raw_item)
        start = float(item.get("start_time", 0.0) or 0.0)
        end = max(start, float(item.get("end_time", start) or start))
        if normalized:
            previous = normalized[-1]
            previous_start = float(previous.get("start_time", 0.0) or 0.0)
            previous_end = float(previous.get("end_time", previous_start) or previous_start)
            if start < previous_end:
                if start > previous_start + 0.18 and previous_end - start <= 0.35:
                    previous["end_time"] = round(start, 3)
                    previous["packaged_subtitle_timing_repair"] = "trim_overlap_end"
                    previous_end = start
                else:
                    start = previous_end
        if end < start + 0.08:
            end = start + 0.08
        item["start_time"] = round(start, 3)
        item["end_time"] = round(end, 3)
        normalized.append(item)
    return normalized


def _score_music_entry_candidates(
    subtitle_items: list[dict],
    *,
    content_profile: dict | None,
) -> list[dict[str, Any]]:
    return score_local_music_entry_candidates(subtitle_items, content_profile=content_profile)


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
    return await plan_local_music_entry(
        music_plan=music_plan,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        timeline_analysis=timeline_analysis,
    )


async def _plan_insert_asset_slot(
    *,
    job_id: str,
    insert_plan: dict | None,
    subtitle_items: list[dict],
    content_profile: dict | None,
    timeline_analysis: dict[str, Any] | None = None,
    allow_llm: bool = True,
) -> dict | None:
    return await plan_local_insert_slot(
        job_id=job_id,
        insert_plan=insert_plan,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        timeline_analysis=timeline_analysis,
        allow_llm=allow_llm,
    )


async def _map_subtitles_to_packaged_timeline(
    subtitle_items: list[dict],
    render_plan: dict[str, Any] | None = None,
    *,
    keep_segments: list[dict[str, Any]] | None = None,
    timeline_mapping: dict[str, Any] | None = None,
) -> list[dict]:
    if not subtitle_items:
        return []

    mapped = [dict(item) for item in subtitle_items]
    timeline_mapping = timeline_mapping or await _resolve_packaged_timeline_mapping_context(
        render_plan,
        keep_segments=keep_segments or [],
    )
    transition_offsets = list(timeline_mapping.get("transition_offsets") or [])
    if transition_offsets:
        mapped = _shift_timed_items_for_transition_overlaps(mapped, transition_offsets=transition_offsets)
    intro_duration = float(timeline_mapping.get("intro_duration_sec", 0.0) or 0.0)
    if intro_duration > 0:
        for item in mapped:
            item["start_time"] = float(item["start_time"]) + intro_duration
            item["end_time"] = float(item["end_time"]) + intro_duration

    insert_plan = timeline_mapping.get("insert_plan")
    insert_after_sec = float(timeline_mapping.get("insert_after_sec", 0.0) or 0.0)
    effective_insert_duration = float(timeline_mapping.get("effective_insert_duration_sec", 0.0) or 0.0)
    if insert_plan and effective_insert_duration > 0:
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

    section_profile_context = dict(timeline_mapping.get("section_profile_context") or {})
    if not section_profile_context:
        section_profile_context = _packaged_subtitle_section_profile_context(render_plan)
    return _finalize_packaged_subtitle_timeline(
        _resegment_packaged_subtitles(
        _rewrite_packaged_subtitle_copy(
            mapped,
            render_plan=None,
            section_profile_context=section_profile_context,
        ),
        render_plan=None,
        section_profile_context=section_profile_context,
        )
    )


async def _map_editing_accents_to_packaged_timeline(
    editing_accents: dict[str, Any] | None,
    render_plan: dict[str, Any] | None = None,
    *,
    keep_segments: list[dict[str, Any]] | None = None,
    timeline_mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = dict(editing_accents or {})
    mapped = {
        **base,
        "transitions": dict(base.get("transitions") or {}),
        "emphasis_overlays": [dict(item) for item in base.get("emphasis_overlays") or []],
        "sound_effects": [dict(item) for item in base.get("sound_effects") or []],
    }
    timeline_mapping = timeline_mapping or await _resolve_packaged_timeline_mapping_context(
        render_plan,
        keep_segments=keep_segments or [],
    )
    transition_offsets = list(timeline_mapping.get("transition_offsets") or [])
    if transition_offsets:
        mapped["emphasis_overlays"] = _shift_timed_items_for_transition_overlaps(
            mapped.get("emphasis_overlays") or [],
            transition_offsets=transition_offsets,
        )
        mapped["sound_effects"] = _shift_sound_effects_for_transition_overlaps(
            mapped.get("sound_effects") or [],
            transition_offsets=transition_offsets,
        )
    intro_duration = float(timeline_mapping.get("intro_duration_sec", 0.0) or 0.0)
    if intro_duration > 0:
        for collection_name in ("emphasis_overlays", "sound_effects"):
            for item in mapped.get(collection_name) or []:
                item["start_time"] = float(item.get("start_time", 0.0) or 0.0) + intro_duration
                if "end_time" in item:
                    item["end_time"] = float(item.get("end_time", 0.0) or 0.0) + intro_duration

    insert_plan = timeline_mapping.get("insert_plan")
    insert_after_sec = float(timeline_mapping.get("insert_after_sec", 0.0) or 0.0)
    effective_insert_duration = float(timeline_mapping.get("effective_insert_duration_sec", 0.0) or 0.0)
    if insert_plan and effective_insert_duration > 0:
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


async def _resolve_packaged_timeline_mapping_context(
    render_plan: dict[str, Any] | None,
    *,
    keep_segments: list[dict[str, Any]],
    packaging_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(packaging_context, dict):
        packaging_timeline = dict(packaging_context.get("packaging_timeline") or {})
        packaging_assets = dict(packaging_context.get("assets") or {})
        transitions = dict(packaging_context.get("transitions") or {})
        section_profile_context = dict(packaging_context.get("section_profile_context") or {})
    else:
        plan = render_plan or {}
        packaging_timeline = resolve_packaging_timeline_payload(plan)
        packaging_assets = dict((packaging_timeline or {}).get("packaging") or {})
        transitions = dict(((packaging_timeline.get("editing_accents") or {}).get("transitions")) or {})
        section_profile_context = _packaged_subtitle_section_profile_context(
            None,
            packaging_timeline=packaging_timeline,
        )
    transition_offsets = _resolve_transition_overlap_offsets(
        None,
        keep_segments=keep_segments,
        transitions=transitions,
    )

    intro_duration = 0.0
    intro_plan = copy.deepcopy(packaging_assets.get("intro"))
    intro_path = str((intro_plan or {}).get("path") or "").strip()
    if intro_path:
        intro_duration = max(0.0, float(await _probe_media_duration(Path(intro_path)) or 0.0))

    insert_plan = copy.deepcopy(packaging_assets.get("insert"))
    insert_path = str((insert_plan or {}).get("path") or "").strip()
    effective_insert_duration = 0.0
    if insert_path and isinstance(insert_plan, dict):
        insert_duration = max(0.0, float(await _probe_media_duration(Path(insert_path)) or 0.0))
        effective_insert_duration = max(
            0.0,
            float(resolve_insert_effective_duration(insert_plan, source_duration=insert_duration) or 0.0),
        )

    return {
        "transition_offsets": transition_offsets,
        "intro_duration_sec": intro_duration,
        "insert_plan": insert_plan if insert_path else None,
        "insert_after_sec": float(((insert_plan or {}).get("insert_after_sec", 0.0) or 0.0)) + intro_duration,
        "effective_insert_duration_sec": effective_insert_duration,
        "section_profile_context": section_profile_context,
    }


def _render_subtitle_timings_from_items(subtitle_items: list[dict[str, Any]]) -> list[SubtitleTiming]:
    timings: list[SubtitleTiming] = []
    for item in subtitle_items or []:
        if not isinstance(item, dict):
            continue
        text = subtitle_display_rule_text(item)
        if not normalize_eval_text(text):
            continue
        try:
            start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
            end = float(item.get("end_time", item.get("end", start)) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        timings.append(SubtitleTiming(text=text, start_sec=start, end_sec=end))
    return timings


def _render_asr_tokens_from_transcript(result: TranscriptResult) -> list[AsrToken]:
    tokens: list[AsrToken] = []
    for segment in list(result.segments or []):
        words = list(getattr(segment, "words", []) or [])
        if words:
            for word in words:
                text = str(getattr(word, "word", "") or "").strip()
                if not normalize_eval_text(text):
                    continue
                start = float(getattr(word, "start", 0.0) or 0.0)
                end = float(getattr(word, "end", start) or start)
                tokens.append(AsrToken(text=text, start_sec=start, end_sec=max(start, end)))
            continue
        text = str(getattr(segment, "text", "") or "").strip()
        chars = list(normalize_eval_text(text))
        if not chars:
            continue
        start = float(getattr(segment, "start", 0.0) or 0.0)
        end = max(start + 0.001, float(getattr(segment, "end", start) or start))
        span = end - start
        for index, char in enumerate(chars):
            tokens.append(
                AsrToken(
                    text=char,
                    start_sec=start + span * index / len(chars),
                    end_sec=start + span * (index + 1) / len(chars),
                )
            )
    tokens.sort(key=lambda item: (item.start_sec, item.end_sec))
    return tokens


def _render_subtitle_alignment_gate_passes(audit: dict[str, Any]) -> bool:
    event_count = max(1, int(audit.get("event_count") or 0))
    matched_count = int(audit.get("matched_count") or 0)
    unmatched_count = int(audit.get("unmatched_count") or 0)
    bad_drift_count = int(audit.get("bad_drift_count") or 0)
    matched_ratio = matched_count / event_count
    unmatched_ratio = unmatched_count / event_count
    bad_ratio = bad_drift_count / event_count
    allowed_bad_count = max(1, int(event_count * 0.15))
    avg_start = audit.get("avg_abs_start_drift_sec")
    avg_end = audit.get("avg_abs_end_drift_sec")
    avg_start_value = float(avg_start) if avg_start is not None else 999.0
    avg_end_value = float(avg_end) if avg_end is not None else 999.0
    return (
        matched_ratio >= 0.82
        and unmatched_ratio <= 0.18
        and (bad_ratio <= 0.15 or bad_drift_count <= allowed_bad_count)
        and avg_start_value <= 0.65
        and avg_end_value <= 1.05
        and bool(_render_subtitle_alignment_local_cluster_metrics(audit).get("gate_pass"))
    )


def _render_subtitle_alignment_local_cluster_metrics(
    audit: dict[str, Any],
    *,
    window_sec: float = 8.0,
    max_bad_events_per_window: int = 3,
    tail_ratio: float = 0.8,
    max_tail_bad_events: int = 4,
    max_single_start_drift_sec: float = 2.2,
    max_single_end_drift_sec: float = 2.4,
) -> dict[str, Any]:
    events = [dict(item) for item in list(audit.get("events") or []) if isinstance(item, dict)]
    duration = max([float(item.get("subtitle_end_sec", 0.0) or 0.0) for item in events] + [0.0])
    bad_events: list[dict[str, Any]] = []
    max_start = 0.0
    max_end = 0.0
    for index, event in enumerate(events):
        matched = bool(event.get("matched"))
        start_drift = abs(float(event.get("start_drift_sec", 0.0) or 0.0))
        end_drift = abs(float(event.get("end_drift_sec", 0.0) or 0.0))
        max_start = max(max_start, start_drift)
        max_end = max(max_end, end_drift)
        if not matched or bool(event.get("bad_drift")):
            bad_events.append(
                {
                    "index": index,
                    "start": float(event.get("subtitle_start_sec", 0.0) or 0.0),
                    "end": float(event.get("subtitle_end_sec", 0.0) or 0.0),
                    "matched": matched,
                    "bad_drift": bool(event.get("bad_drift")),
                    "start_drift_sec": round(start_drift, 3),
                    "end_drift_sec": round(end_drift, 3),
                }
            )
    worst_window_count = 0
    worst_window_start = 0.0
    bad_starts = [float(item["start"]) for item in bad_events]
    for start in bad_starts:
        count = sum(1 for value in bad_starts if start <= value < start + window_sec)
        if count > worst_window_count:
            worst_window_count = count
            worst_window_start = start
    tail_start = duration * tail_ratio if duration > 0 else 0.0
    tail_bad_count = sum(1 for item in bad_events if tail_start > 0 and float(item["start"]) >= tail_start)
    gate_pass = (
        worst_window_count <= max_bad_events_per_window
        and tail_bad_count <= max_tail_bad_events
        and max_start <= max_single_start_drift_sec
        and max_end <= max_single_end_drift_sec
    )
    return {
        "gate_pass": gate_pass,
        "bad_event_count": len(bad_events),
        "worst_window_count": worst_window_count,
        "worst_window_start_sec": round(worst_window_start, 3),
        "window_sec": round(window_sec, 3),
        "tail_start_sec": round(tail_start, 3),
        "tail_bad_count": tail_bad_count,
        "max_single_start_drift_sec": round(max_start, 3),
        "max_single_end_drift_sec": round(max_end, 3),
        "bad_event_indexes": [int(item["index"]) for item in bad_events],
    }


def _clustered_unmatched_render_subtitle_indexes(audit: dict[str, Any]) -> set[int]:
    metrics = _render_subtitle_alignment_local_cluster_metrics(audit)
    if bool(metrics.get("gate_pass")):
        return set()
    events = [dict(item) for item in list(audit.get("events") or []) if isinstance(item, dict)]
    bad_indexes = {int(index) for index in list(metrics.get("bad_event_indexes") or [])}
    bad_starts = {
        index: float(events[index].get("subtitle_start_sec", 0.0) or 0.0)
        for index in bad_indexes
        if 0 <= index < len(events)
    }
    clustered_indexes: set[int] = set()
    window_sec = float(metrics.get("window_sec") or 8.0)
    tail_start = float(metrics.get("tail_start_sec") or 0.0)
    for index, start in bad_starts.items():
        neighbors = [
            other
            for other, other_start in bad_starts.items()
            if start <= other_start < start + window_sec
        ]
        if len(neighbors) >= 4:
            clustered_indexes.update(neighbors)
        if tail_start > 0 and start >= tail_start:
            clustered_indexes.add(index)
    return {
        index
        for index in clustered_indexes
        if 0 <= index < len(events) and not bool(events[index].get("matched"))
    }


def _drop_clustered_unmatched_render_subtitles(
    subtitle_items: list[dict[str, Any]],
    audit: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    drop_indexes = _clustered_unmatched_render_subtitle_indexes(audit)
    if not drop_indexes:
        return [dict(item) for item in subtitle_items], {"dropped_unmatched_cluster_count": 0, "dropped_indexes": []}
    kept = [
        dict(item)
        for index, item in enumerate(subtitle_items)
        if index not in drop_indexes and isinstance(item, dict)
    ]
    return kept, {
        "dropped_unmatched_cluster_count": len(drop_indexes),
        "dropped_indexes": sorted(drop_indexes),
    }


def _estimate_render_subtitle_global_offset(audit: dict[str, Any]) -> dict[str, Any]:
    offsets: list[float] = []
    for event in list(audit.get("events") or []):
        if not isinstance(event, dict) or not event.get("matched"):
            continue
        try:
            subtitle_start = float(event.get("subtitle_start_sec"))
            expected_start = float(event.get("expected_start_sec"))
        except (TypeError, ValueError):
            continue
        if len(normalize_eval_text(str(event.get("text") or ""))) < 2:
            continue
        offsets.append(expected_start - subtitle_start)
    if not offsets:
        return {"stable": False, "sample_count": 0, "offset_sec": 0.0}
    offset = float(median(offsets))
    deviations = [abs(value - offset) for value in offsets]
    stable_count = sum(1 for value in deviations if value <= 1.2)
    stable_ratio = stable_count / max(1, len(offsets))
    sorted_deviations = sorted(deviations)
    p90_index = min(len(sorted_deviations) - 1, max(0, int(round(len(sorted_deviations) * 0.9)) - 1))
    p90 = sorted_deviations[p90_index]
    return {
        "stable": len(offsets) >= 8 and stable_ratio >= 0.72 and p90 <= 1.8,
        "sample_count": len(offsets),
        "offset_sec": round(offset, 3),
        "stable_ratio": round(stable_ratio, 4),
        "p90_deviation_sec": round(p90, 3),
    }


def _shift_render_subtitle_items(subtitle_items: list[dict[str, Any]], *, offset_sec: float) -> list[dict[str, Any]]:
    offset = float(offset_sec or 0.0)
    shifted: list[dict[str, Any]] = []
    for item in subtitle_items or []:
        if not isinstance(item, dict):
            continue
        next_item = copy.deepcopy(item)
        start = max(0.0, float(next_item.get("start_time", next_item.get("start", 0.0)) or 0.0) + offset)
        end = max(start + 0.001, float(next_item.get("end_time", next_item.get("end", start)) or start) + offset)
        next_item["start_time"] = round(start, 3)
        next_item["end_time"] = round(end, 3)
        next_item["render_asr_timing_repair"] = "global_offset"
        next_item["render_asr_timing_offset_sec"] = round(offset, 3)
        words: list[dict[str, Any]] = []
        for word in list(next_item.get("words") or []):
            if not isinstance(word, dict):
                continue
            next_word = dict(word)
            try:
                word_start = float(next_word.get("start", 0.0) or 0.0) + offset
                word_end = float(next_word.get("end", next_word.get("start", 0.0)) or 0.0) + offset
            except (TypeError, ValueError):
                words.append(next_word)
                continue
            next_word["start"] = round(max(0.0, word_start), 3)
            next_word["end"] = round(max(next_word["start"], word_end), 3)
            words.append(next_word)
        if words:
            next_item["words"] = words
        shifted.append(next_item)
    return shifted


def _retime_words_to_new_bounds(
    words: list[dict[str, Any]],
    *,
    old_start: float,
    old_end: float,
    new_start: float,
    new_end: float,
) -> list[dict[str, Any]]:
    if not words:
        return []
    old_duration = max(0.001, old_end - old_start)
    new_duration = max(0.001, new_end - new_start)
    retimed: list[dict[str, Any]] = []
    for word in words:
        if not isinstance(word, dict):
            continue
        next_word = dict(word)
        try:
            word_start = float(next_word.get("start", old_start) or old_start)
            word_end = float(next_word.get("end", word_start) or word_start)
        except (TypeError, ValueError):
            retimed.append(next_word)
            continue
        start_ratio = max(0.0, min(1.0, (word_start - old_start) / old_duration))
        end_ratio = max(start_ratio, min(1.0, (word_end - old_start) / old_duration))
        next_word["start"] = round(new_start + new_duration * start_ratio, 3)
        next_word["end"] = round(max(next_word["start"], new_start + new_duration * end_ratio), 3)
        retimed.append(next_word)
    return retimed


def _retime_render_subtitle_items_from_alignment_audit(
    subtitle_items: list[dict[str, Any]],
    audit: dict[str, Any],
    *,
    duration_sec: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    events = list(audit.get("events") or [])
    eligible_indexes = [
        index
        for index, item in enumerate(subtitle_items or [])
        if isinstance(item, dict) and normalize_eval_text(subtitle_display_rule_text(item))
    ]
    matched_offsets: list[float] = []
    for event in events:
        if not isinstance(event, dict) or not event.get("matched"):
            continue
        try:
            matched_offsets.append(float(event["expected_start_sec"]) - float(event["subtitle_start_sec"]))
        except (TypeError, ValueError, KeyError):
            continue
    fallback_offset = float(median(matched_offsets)) if matched_offsets else 0.0
    repaired: list[dict[str, Any] | None] = [copy.deepcopy(item) for item in subtitle_items]
    repaired_count = 0
    fallback_count = 0
    out_of_bounds_dropped_count = 0
    max_duration = max(0.001, float(duration_sec or 0.0))
    for event_index, item_index in enumerate(eligible_indexes):
        if item_index >= len(repaired):
            continue
        item = repaired[item_index]
        if item is None:
            continue
        event = events[event_index] if event_index < len(events) and isinstance(events[event_index], dict) else {}
        old_start = float(item.get("start_time", item.get("start", 0.0)) or 0.0)
        old_end = max(old_start + 0.001, float(item.get("end_time", item.get("end", old_start)) or old_start))
        if event.get("matched") and event.get("expected_start_sec") is not None and event.get("expected_end_sec") is not None:
            new_start = max(0.0, float(event["expected_start_sec"]) - 0.04)
            new_end = min(max_duration, max(new_start + 0.75, float(event["expected_end_sec"]) + 0.12))
            repaired_count += 1
        else:
            new_start = max(0.0, old_start + fallback_offset)
            new_end = min(max_duration, max(new_start + 0.75, old_end + fallback_offset))
            fallback_count += 1
        if new_start >= max_duration - 0.05 or new_end <= new_start:
            repaired[item_index] = None
            out_of_bounds_dropped_count += 1
            continue
        item["start_time"] = round(new_start, 3)
        item["end_time"] = round(max(new_start + 0.001, new_end), 3)
        item["render_asr_timing_repair"] = "rendered_audio_forced_alignment"
        item["render_asr_timing_offset_sec"] = round(item["start_time"] - old_start, 3)
        words = _retime_words_to_new_bounds(
            list(item.get("words") or []),
            old_start=old_start,
            old_end=old_end,
            new_start=float(item["start_time"]),
            new_end=float(item["end_time"]),
        )
        if words:
            item["words"] = words
    bounded_repaired = [item for item in repaired if item is not None]
    return _stabilize_render_subtitle_timeline(bounded_repaired), {
        "repair_mode": "rendered_audio_forced_alignment",
        "matched_retimed_count": repaired_count,
        "fallback_retimed_count": fallback_count,
        "out_of_bounds_dropped_count": out_of_bounds_dropped_count,
        "fallback_offset_sec": round(fallback_offset, 3),
    }


async def _audit_subtitles_against_rendered_audio(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    language: str,
    debug_dir: Path,
    label: str,
) -> dict[str, Any]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    audio_path = debug_dir / f"{label}.subtitle_alignment.wav"
    await extract_audio(video_path, audio_path)
    result = await LocalHTTPASRProvider().transcribe(audio_path, language=language)
    tokens = _render_asr_tokens_from_transcript(result)
    asr_text = "".join(segment.text for segment in result.segments)
    timings = _render_subtitle_timings_from_items(subtitle_items)
    audit = audit_subtitle_timing_alignment(
        timings,
        tokens,
        max_start_drift_sec=0.55,
        max_end_drift_sec=1.0,
    )
    local_cluster_metrics = _render_subtitle_alignment_local_cluster_metrics(audit)
    payload = {
        "label": label,
        "video_path": str(video_path),
        "audio_path": str(audio_path),
        "language": language,
        "provider": result.provider,
        "model": result.model,
        "duration_sec": result.duration,
        "subtitle_event_count": len(timings),
        "asr_token_count": len(tokens),
        "asr_text_chars": len(normalize_eval_text(asr_text)),
        "asr_text_preview": asr_text[:240],
        "gate_pass": _render_subtitle_alignment_gate_passes(audit),
        "local_cluster_metrics": local_cluster_metrics,
        "offset_estimate": _estimate_render_subtitle_global_offset(audit),
        "audit": audit,
    }
    (debug_dir / f"{label}.subtitle_alignment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


async def _repair_subtitles_with_rendered_audio_asr(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    language: str,
    debug_dir: Path,
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = await _audit_subtitles_against_rendered_audio(
        video_path=video_path,
        subtitle_items=subtitle_items,
        language=language,
        debug_dir=debug_dir,
        label=f"{label}.before",
    )
    if bool(before.get("gate_pass")):
        return [dict(item) for item in subtitle_items], {"status": "pass", "repaired": False, "before": before}

    cleaned_subtitles, cluster_drop_summary = _drop_clustered_unmatched_render_subtitles(
        subtitle_items,
        dict(before.get("audit") or {}),
    )
    retime_audit = dict(before.get("audit") or {})
    dropped_indexes = set(int(index) for index in list(cluster_drop_summary.get("dropped_indexes") or []))
    if dropped_indexes:
        retime_audit["events"] = [
            dict(event)
            for index, event in enumerate(list(retime_audit.get("events") or []))
            if index not in dropped_indexes and isinstance(event, dict)
        ]
    forced_aligned_subtitles, forced_alignment_summary = _retime_render_subtitle_items_from_alignment_audit(
        cleaned_subtitles,
        retime_audit,
        duration_sec=float(before.get("duration_sec", 0.0) or 0.0),
    )
    forced_after = await _audit_subtitles_against_rendered_audio(
        video_path=video_path,
        subtitle_items=forced_aligned_subtitles,
        language=language,
        debug_dir=debug_dir,
        label=f"{label}.forced_alignment",
    )
    if bool(forced_after.get("gate_pass")):
        return forced_aligned_subtitles, {
            "status": "repaired",
            "repaired": True,
            **cluster_drop_summary,
            **forced_alignment_summary,
            "before": before,
            "after": forced_after,
        }

    offset = dict(before.get("offset_estimate") or {})
    offset_sec = float(offset.get("offset_sec", 0.0) or 0.0)
    if not bool(offset.get("stable")) or abs(offset_sec) < 0.35:
        return [dict(item) for item in subtitle_items], {
            "status": "blocked",
            "repaired": False,
            "reason": "rendered_audio_asr_alignment_unstable",
            **cluster_drop_summary,
            "before": before,
            "forced_alignment": {
                **forced_alignment_summary,
                "after": forced_after,
            },
        }

    repaired_subtitles = _shift_render_subtitle_items(subtitle_items, offset_sec=offset_sec)
    after = await _audit_subtitles_against_rendered_audio(
        video_path=video_path,
        subtitle_items=repaired_subtitles,
        language=language,
        debug_dir=debug_dir,
        label=f"{label}.after",
    )
    if not bool(after.get("gate_pass")):
        return repaired_subtitles, {
            "status": "blocked",
            "repaired": True,
            "reason": "rendered_audio_asr_alignment_repair_failed_gate",
            **cluster_drop_summary,
            "offset_sec": round(offset_sec, 3),
            "before": before,
            "after": after,
        }
    return repaired_subtitles, {
        "status": "repaired",
        "repaired": True,
        **cluster_drop_summary,
        "offset_sec": round(offset_sec, 3),
        "before": before,
        "after": after,
    }


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


async def _resolve_packaging_trailing_gap_allowance(
    render_plan: dict[str, Any] | None = None,
    *,
    outro_plan: dict[str, Any] | None = None,
) -> float:
    resolved_outro_plan = outro_plan if isinstance(outro_plan, dict) else packaging_timeline_asset_plan(render_plan, "outro")
    outro_path = str((resolved_outro_plan or {}).get("path") or "").strip()
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
            "subtitle_short_flash_detected",
            "subtitle_burst_density_detected",
            "subtitle_local_gap_unstable",
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


def _collect_blocking_variant_sync_issues(
    sync_checks: dict[str, dict[str, Any] | None],
    *,
    mandatory_variants: set[str] | None = None,
) -> list[str]:
    if mandatory_variants is None:
        mandatory_variants = {"plain", "packaged", "avatar", "ai_effect"}
    issues: list[str] = []
    for variant_name, sync_check in sync_checks.items():
        if mandatory_variants and variant_name not in mandatory_variants:
            continue
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
    original_duration_sec: float,
    subtitle_items: list[dict[str, Any]],
    variant_source_path: Path | None = None,
    variant_duration_sec: float | None = None,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    if variant_source_path is None:
        return (
            original_source_path,
            _build_full_length_variant_timeline(original_duration_sec),
            [dict(item) for item in subtitle_items],
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
        [dict(item) for item in subtitle_items],
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
        raise AvatarFullTrackRenderError(
            "avatar_full_track_presenter_missing",
            reason_code="avatar_full_track_presenter_missing",
        )

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
        raise AvatarFullTrackRenderError(
            str(render_execution.get("reason") or render_execution.get("status") or "avatar_full_track_segments_missing"),
            reason_code="avatar_full_track_segments_missing",
            metadata={
                "provider_status": str(render_execution.get("status") or "").strip().lower() or None,
                "provider_reason": str(render_execution.get("reason") or "").strip() or None,
            },
        )
    first_segment = segments[0] or {}
    if str(first_segment.get("status") or "") != "success":
        raise AvatarFullTrackRenderError(
            str(first_segment.get("error") or "avatar_full_track_render_failed"),
            reason_code="avatar_full_track_provider_response_error",
            metadata={"segment_status": str(first_segment.get("status") or "").strip().lower() or None},
        )
    result_value = str(first_segment.get("local_result_path") or "").strip()
    if not result_value:
        raise AvatarFullTrackRenderError(
            "avatar_full_track_result_missing",
            reason_code="avatar_full_track_result_missing",
        )
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
_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS = 30.0
_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS = 30.0
_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS = 60.0


class AvatarFullTrackRenderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        retryable: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = str(reason_code or "avatar_render_failed").strip() or "avatar_render_failed"
        self.retryable = bool(retryable)
        self.metadata = dict(metadata or {})


def _avatar_full_track_error_payload(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, AvatarFullTrackRenderError):
        payload = {
            "reason": exc.reason_code,
            "detail": str(exc),
            "retryable": exc.retryable,
        }
        if exc.metadata:
            payload["error_metadata"] = dict(exc.metadata)
        return payload
    return {
        "reason": "avatar_render_failed",
        "detail": str(exc),
        "retryable": False,
    }


def _resolve_avatar_full_track_busy_max_wait_seconds() -> float:
    raw_value = os.getenv("ROUGHCUT_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS", str(_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS)).strip()
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return float(_AVATAR_FULL_TRACK_BUSY_MAX_WAIT_SECONDS)
    return max(30.0, value)


def _resolve_avatar_full_track_call_timeout_seconds() -> float:
    raw_value = os.getenv("ROUGHCUT_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS", str(_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS)).strip()
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return float(_AVATAR_FULL_TRACK_CALL_TIMEOUT_SECONDS)
    return max(10.0, value)


def _resolve_avatar_full_track_execution_timeout_seconds(
    *,
    provider: Any,
    render_request: dict[str, Any],
) -> float:
    configured_timeout_seconds = _resolve_avatar_full_track_call_timeout_seconds()
    provider_timeout_seconds: float | None = None
    estimate_timeout = getattr(provider, "estimate_render_timeout_seconds", None)
    if callable(estimate_timeout):
        try:
            estimated = estimate_timeout(request=render_request)
        except Exception:
            estimated = None
        try:
            provider_timeout_seconds = float(estimated) if estimated is not None else None
        except (TypeError, ValueError):
            provider_timeout_seconds = None
    if provider_timeout_seconds is None:
        return float(configured_timeout_seconds)
    return max(10.0, min(float(configured_timeout_seconds), max(10.0, provider_timeout_seconds)))


def _resolve_avatar_full_track_slot_timeout_seconds() -> float:
    raw_value = os.getenv(
        "ROUGHCUT_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS",
        str(_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS),
    ).strip()
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return float(_AVATAR_FULL_TRACK_SLOT_TIMEOUT_SECONDS)
    return max(3.0, value)


@asynccontextmanager
async def _hold_avatar_full_track_slot(*, job_id: str):
    logger.info("Waiting for avatar full-track slot job=%s", job_id)
    slot_timeout_seconds = _resolve_avatar_full_track_slot_timeout_seconds()
    acquired, token = await asyncio.to_thread(
        _acquire_operation_lock,
        _AVATAR_FULL_TRACK_SLOT_KEY,
        timeout_sec=int(slot_timeout_seconds),
    )
    if not acquired:
        raise AvatarFullTrackRenderError(
            "avatar_full_track_slot_timeout",
            reason_code="avatar_full_track_slot_timeout",
            retryable=True,
            metadata={"slot_timeout_seconds": float(slot_timeout_seconds)},
        )
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
        provider = get_avatar_provider()
        last_error: Exception | None = None
        attempt = 0
        busy_waited_seconds = 0.0
        busy_max_wait_seconds = _resolve_avatar_full_track_busy_max_wait_seconds()
        call_timeout_seconds = _resolve_avatar_full_track_execution_timeout_seconds(
            provider=provider,
            render_request=render_request,
        )
        while True:
            try:
                render_execution = await asyncio.wait_for(
                    asyncio.to_thread(
                        provider.execute_render,
                        job_id=job_id,
                        request=render_request,
                    ),
                    timeout=call_timeout_seconds,
                )
            except asyncio.TimeoutError as exc:
                raise AvatarFullTrackRenderError(
                    f"avatar_full_track_call_timeout>{float(call_timeout_seconds):.1f}s",
                    reason_code="avatar_full_track_call_timeout",
                    retryable=True,
                    metadata={"call_timeout_seconds": float(call_timeout_seconds)},
                ) from exc
            except Exception as exc:
                last_error = exc
                if _is_avatar_service_busy_message(exc):
                    delay = _AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS[
                        min(attempt, len(_AVATAR_FULL_TRACK_RETRY_DELAYS_SECONDS) - 1)
                    ]
                    if busy_waited_seconds + delay > busy_max_wait_seconds:
                        raise AvatarFullTrackRenderError(
                            str(exc),
                            reason_code="avatar_full_track_busy_exhausted",
                            retryable=True,
                            metadata={
                                "busy_waited_seconds": float(busy_waited_seconds),
                                "busy_max_wait_seconds": float(busy_max_wait_seconds),
                                "attempts": int(attempt + 1),
                            },
                        ) from exc
                    attempt += 1
                    busy_waited_seconds += delay
                    logger.warning(
                        "Avatar full-track render retrying after busy response job=%s attempt=%s waited=%.1fs/%.1fs delay=%.1fs",
                        job_id,
                        attempt + 1,
                        busy_waited_seconds,
                        busy_max_wait_seconds,
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
                if busy_waited_seconds + delay > busy_max_wait_seconds:
                    raise AvatarFullTrackRenderError(
                        error_text,
                        reason_code="avatar_full_track_busy_exhausted",
                        retryable=True,
                        metadata={
                            "busy_waited_seconds": float(busy_waited_seconds),
                            "busy_max_wait_seconds": float(busy_max_wait_seconds),
                            "attempts": int(attempt + 1),
                            "segment_status": str(first_segment.get("status") or "").strip().lower() or None,
                        },
                    )
                attempt += 1
                busy_waited_seconds += delay
                last_error = RuntimeError(error_text)
                logger.warning(
                    "Avatar full-track render retrying after busy response job=%s attempt=%s waited=%.1fs/%.1fs delay=%.1fs",
                    job_id,
                    attempt + 1,
                    busy_waited_seconds,
                    busy_max_wait_seconds,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise AvatarFullTrackRenderError(
                error_text,
                reason_code="avatar_full_track_provider_response_error",
                metadata={
                    "segment_status": str(first_segment.get("status") or "").strip().lower() or None,
                    "provider_error": error_text,
                },
            )
        if last_error is not None:
            raise last_error
        raise AvatarFullTrackRenderError(
            "avatar_full_track_render_failed",
            reason_code="avatar_full_track_render_failed",
        )


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
    base_fps = float(getattr(base_probe, "fps", 0.0) or 0.0)
    sample_avatar_fps = float(getattr(sample_probe, "fps", 0.0) or 0.0)
    avatar_fps_cache = {str(Path(str(available_segments[0]["video_local_path"]))): sample_avatar_fps}
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
        segment_video_path = Path(str(segment["video_local_path"]))
        segment_avatar_fps = avatar_fps_cache.get(str(segment_video_path))
        if segment_avatar_fps is None:
            try:
                segment_probe = await probe(segment_video_path)
                segment_avatar_fps = float(getattr(segment_probe, "fps", 0.0) or 0.0)
            except Exception:
                segment_avatar_fps = sample_avatar_fps
            avatar_fps_cache[str(segment_video_path)] = segment_avatar_fps
        avatar_filter = _build_rounded_rgba_filter(
            input_label=f"{index}:v",
            output_label=f"pipfg{index}",
            width=overlay_width,
            height=overlay_height,
            corner_radius=avatar_corner_radius,
            extra_filters=(
                f"trim=duration={segment_duration:.6f},"
                f"setpts=PTS-STARTPTS+{start_time:.6f}/TB,"
                f"{_build_avatar_picture_in_picture_filters(base_duration=segment_duration, base_fps=base_fps, avatar_duration=segment_duration, avatar_fps=segment_avatar_fps, overlay_width=overlay_width, overlay_height=overlay_height)}"
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
    cut_analysis: dict[str, Any] | None = None,
    refine_decision_plan: dict[str, Any] | None = None,
    render_plan: dict[str, Any] | None = None,
    packaging_timeline: dict[str, Any] | None = None,
    variants: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cloned_editorial_analysis = _clone_json_like(editorial_analysis or {})
    cloned_cut_analysis = _clone_json_like(cut_analysis or {})
    cloned_refine_decision_plan = _clone_json_like(refine_decision_plan or {})
    resolved_packaging_timeline = (
        dict(packaging_timeline)
        if isinstance(packaging_timeline, dict)
        else build_packaging_timeline_payload(render_plan)
    )
    packaging_timeline_analysis_payload = dict(resolved_packaging_timeline.get("timeline_analysis") or {})
    bundle = {
        "timeline_rules": {
            "editorial_timeline_id": str(editorial_timeline_id or "").strip() or None,
            "render_plan_timeline_id": str(render_plan_timeline_id or "").strip() or None,
            "keep_segments": [dict(segment) for segment in keep_segments],
            "editorial_analysis": cloned_editorial_analysis,
            "cut_analysis": cloned_cut_analysis,
            "refine_decision_plan": cloned_refine_decision_plan,
            "packaging_timeline": resolved_packaging_timeline,
            "diagnostics": _build_variant_timeline_diagnostics(
                editorial_analysis=cloned_editorial_analysis,
                cut_analysis=cloned_cut_analysis,
                refine_decision_plan=cloned_refine_decision_plan,
                timeline_analysis=packaging_timeline_analysis_payload,
            ),
        },
        "variants": {name: dict(payload) for name, payload in variants.items() if isinstance(payload, dict)},
    }
    bundle["validation"] = _validate_variant_timeline_bundle(
        bundle,
        packaging_timeline=resolved_packaging_timeline,
    )
    return bundle


_NON_SPEECH_CUT_TEXT_PLACEHOLDERS = {
    "",
    "silence",
    "silent",
    "pause",
    "gap",
    "vad_gap",
    "no_speech",
    "non_speech",
    "静音",
    "静默",
    "停顿",
    "空白",
}


def _cut_text_has_spoken_content(value: Any) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    compact = re.sub(r"[\s_\-]+", "_", normalized.lower())
    return compact not in _NON_SPEECH_CUT_TEXT_PLACEHOLDERS


def _classify_high_risk_cut_review(item: dict[str, Any], *, compact_evidence: dict[str, Any]) -> dict[str, Any]:
    reason = str(item.get("reason") or "").strip()
    source_text = str(item.get("source_text") or "").strip()
    match_surface = str(item.get("match_surface") or "").strip()
    risk_level = str(item.get("risk_level") or "").strip().lower()
    signals = {
        str(signal).strip()
        for signal in list(item.get("signals") or [])
        if str(signal).strip()
    }
    evidence_tags = {
        str(tag).strip()
        for tag in list(compact_evidence.get("tags") or [])
        if str(tag).strip()
    }
    protection_score = float(compact_evidence.get("protection_score") or 0.0)
    language_score = float(compact_evidence.get("language_score") or 0.0)
    explicit_speech_overlap = bool(
        _cut_text_has_spoken_content(source_text)
        or _cut_text_has_spoken_content(match_surface)
        or signals.intersection({"protected_speech_overlap", "protected_subtitle_text_overlap"})
        or evidence_tags.intersection({"language_context", "subtitle_context", "speech_context"})
    )
    explicit_protected_visual_cut = bool(
        signals.intersection({"protected_visual_cut", "protected_visual_overlap"})
        or evidence_tags.intersection({"protected_visual_cut", "protected_visual_overlap"})
        or risk_level in {"high", "critical"}
    )
    if reason == "silence" and not explicit_speech_overlap and not explicit_protected_visual_cut:
        return {
            "review_priority": "advisory",
            "blocking": False,
            "review_reason": "silence_boundary_between_meaningful_keeps",
        }
    return {
        "review_priority": "blocking",
        "blocking": True,
        "review_reason": "unresolved_semantic_cut",
    }


def _build_variant_timeline_diagnostics(
    *,
    editorial_analysis: dict[str, Any] | None,
    cut_analysis: dict[str, Any] | None,
    refine_decision_plan: dict[str, Any] | None = None,
    timeline_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    keep_energy_segments = [
        dict(item)
        for item in list((editorial_analysis or {}).get("keep_energy_segments") or [])
        if isinstance(item, dict)
    ]
    accepted_cuts = cut_analysis_effective_applied_cuts(cut_analysis) or [
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
    high_risk_cuts: list[dict[str, Any]] = []
    for item in accepted_cuts:
        boundary_keep_energy = float(item.get("boundary_keep_energy", 0.0) or 0.0)
        if boundary_keep_energy < 1.0:
            continue
        left_keep_role = str(item.get("left_keep_role") or "")
        right_keep_role = str(item.get("right_keep_role") or "")
        # Only treat cuts as high-risk when they split two meaningful kept sides.
        if not left_keep_role or not right_keep_role:
            continue
        compact_evidence = _compact_cut_evidence_payload(item.get("evidence"))
        review_classification = _classify_high_risk_cut_review(item, compact_evidence=compact_evidence)
        signals = [
            str(signal).strip()
            for signal in list(item.get("signals") or [])
            if str(signal).strip()
        ]
        high_risk_cuts.append(
            {
                "start": round(float(item.get("start", 0.0) or 0.0), 3),
                "end": round(float(item.get("end", 0.0) or 0.0), 3),
                "reason": str(item.get("reason") or ""),
                "source_text": str(item.get("source_text") or ""),
                "match_surface": str(item.get("match_surface") or ""),
                "match_surface_layer": str(item.get("match_surface_layer") or ""),
                "risk_level": str(item.get("risk_level") or ""),
                "rule_id": str(item.get("rule_id") or ""),
                "boundary_keep_energy": round(boundary_keep_energy, 3),
                "left_keep_role": left_keep_role,
                "right_keep_role": right_keep_role,
                "signals": signals[:8],
                "evidence": compact_evidence,
                **review_classification,
            }
        )
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
    multimodal_trim_review_summary = dict((cut_analysis or {}).get("multimodal_trim_review_summary") or {})
    refine_candidate_summary = dict((refine_decision_plan or {}).get("candidate_summary") or {})
    multimodal_trim_review_summary["auto_apply_cut_count"] = int(
        (refine_decision_plan or {}).get("multimodal_auto_apply_cut_count")
        or refine_candidate_summary.get("multimodal_auto_apply")
        or 0
    )
    review_reasons: list[str] = []
    blocking_high_risk_cuts = [
        item
        for item in high_risk_cuts
        if item.get("blocking") is not False and str(item.get("review_priority") or "blocking") != "advisory"
    ]
    advisory_high_risk_cuts = [
        item
        for item in high_risk_cuts
        if item.get("blocking") is False or str(item.get("review_priority") or "") == "advisory"
    ]
    if blocking_high_risk_cuts:
        review_reasons.append("存在未收口的高风险 cut，需要人工复核或多模态复核。")
    elif advisory_high_risk_cuts:
        review_reasons.append("存在贴近高能量保留段的静默边界 cut，建议抽检边界。")
    if any(
        float(((item.get("evidence") or {}).get("protection_score") or 0.0)) >= 0.72
        for item in blocking_high_risk_cuts
        if isinstance(item.get("evidence"), dict)
    ):
        review_reasons.append("部分 cut 带有展示、语言或语义保护证据，建议重点核对是否误删。")
    if any(str(item.get("section_role") or "") == "hook" for item in high_energy_keeps):
        review_reasons.append("Hook 段存在高能量保留片段，建议确认开场节奏。")
    return {
        "keep_energy_summary": _clone_json_like((editorial_analysis or {}).get("keep_energy_summary") or {}),
        "cut_evidence_summary": _clone_json_like((editorial_analysis or {}).get("cut_evidence_summary") or {}),
        "cut_analysis_summary": {
            "candidate_count": int((cut_analysis or {}).get("candidate_count") or 0),
            "accepted_cut_count": int((cut_analysis or {}).get("accepted_cut_count") or len(accepted_cuts)),
            "rule_candidate_count": int((cut_analysis or {}).get("rule_candidate_count") or 0),
            "auto_apply_candidate_count": int((cut_analysis or {}).get("auto_apply_candidate_count") or 0),
            "manual_confirm_candidate_count": int((cut_analysis or {}).get("manual_confirm_candidate_count") or 0),
            "candidate_risk_summary": _clone_json_like((cut_analysis or {}).get("candidate_risk_summary") or {}),
        },
        "refine_decision_summary": {
            "mode": str(((refine_decision_plan or {}).get("mode")) or "").strip() or None,
            "keep_segment_count": len(list(((refine_decision_plan or {}).get("keep_segments")) or [])),
            "candidate_total": int(refine_candidate_summary.get("total") or 0),
            "candidate_auto_apply": int(refine_candidate_summary.get("auto_apply") or 0),
            "candidate_manual_confirm": int(refine_candidate_summary.get("manual_confirm") or 0),
            "rule_auto_apply_cut_count": int(
                (refine_decision_plan or {}).get("rule_auto_apply_cut_count")
                or refine_candidate_summary.get("rule_auto_apply")
                or 0
            ),
            "multimodal_auto_apply_cut_count": int(refine_candidate_summary.get("multimodal_auto_apply") or 0),
            "risk_levels": _clone_json_like(refine_candidate_summary.get("risk_levels") or {}),
        },
        "high_energy_keeps": high_energy_keeps[:8],
        "high_risk_cuts": high_risk_cuts[:8],
        "blocking_high_risk_cut_count": len(blocking_high_risk_cuts),
        "advisory_high_risk_cut_count": len(advisory_high_risk_cuts),
        "llm_cut_review": llm_cut_review,
        "multimodal_trim_review_summary": multimodal_trim_review_summary,
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


def _strategy_requires_highlight_boundary_frames(strategy_review_context: dict[str, Any] | None) -> bool:
    context = strategy_review_context if isinstance(strategy_review_context, dict) else {}
    gates = context.get("strategy_review_gates") if isinstance(context.get("strategy_review_gates"), dict) else {}
    pipeline_plan = gates.get("pipeline_plan") if isinstance(gates.get("pipeline_plan"), dict) else {}
    strategy_policy = (
        pipeline_plan.get("strategy_policy")
        if isinstance(pipeline_plan.get("strategy_policy"), dict)
        else {}
    )
    render_validation_policy = (
        strategy_policy.get("render_validation_policy")
        if isinstance(strategy_policy.get("render_validation_policy"), dict)
        else {}
    )
    return bool(render_validation_policy.get("check_highlight_boundary_frames"))


async def _build_strategy_cut_boundary_sample_manifest(
    *,
    video_path: Path,
    debug_dir: Path,
    cut_boundary_evidence: dict[str, Any],
    cut_analysis: dict[str, Any] | None = None,
    max_samples: int = 3,
) -> dict[str, Any]:
    cuts = [
        dict(item)
        for item in list(cut_boundary_evidence.get("high_risk_cuts") or [])
        if isinstance(item, dict)
    ]
    if not cuts:
        cuts = [
            dict(item)
            for item in list(cut_analysis_effective_applied_cuts(cut_analysis) or [])
            if isinstance(item, dict)
        ]
    if not cuts:
        cuts = [
            dict(item)
            for item in list(cut_analysis_rule_candidates(cut_analysis, resolved=True) or [])
            if isinstance(item, dict)
            and str(item.get("reason") or "") in {"highlight_window", "timing_trim"}
        ]
    sample_dir = debug_dir / "strategy_cut_boundary_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for index, cut in enumerate(cuts[: max(0, int(max_samples or 0))]):
        start = max(0.0, float(cut.get("start", 0.0) or 0.0))
        end = max(start, float(cut.get("end", start) or start))
        timestamps = [round(max(0.0, start - 0.12), 3), round(max(0.0, end + 0.12), 3)]
        frame_paths: list[str] = []
        for frame_index, timestamp in enumerate(timestamps):
            frame_path = sample_dir / f"cut_{index + 1:02d}_{frame_index + 1:02d}.jpg"
            try:
                await _extract_strategy_boundary_frame(video_path, frame_path, seek_sec=timestamp)
            except Exception as exc:
                errors.append(
                    {
                        "cut_index": index,
                        "timestamp_sec": timestamp,
                        "error": str(exc)[-500:],
                    }
                )
                logger.warning(
                    "Failed to extract strategy boundary frame job video=%s timestamp=%s: %s",
                    video_path,
                    timestamp,
                    str(exc).strip(),
                )
                continue
            if frame_path.exists():
                frame_paths.append(str(frame_path))
        waveform_path = sample_dir / f"cut_{index + 1:02d}_waveform.json"
        try:
            await _extract_strategy_boundary_waveform(
                video_path,
                waveform_path,
                start_sec=max(0.0, start - 0.25),
                end_sec=end + 0.25,
            )
        except Exception as exc:
            errors.append(
                {
                    "cut_index": index,
                    "waveform": True,
                    "error": str(exc)[-500:],
                }
            )
            logger.warning(
                "Failed to extract strategy boundary waveform video=%s start=%s end=%s: %s",
                video_path,
                start,
                end,
                str(exc).strip(),
            )
        sample = {
            "cut_id": str(cut.get("rule_id") or cut.get("candidate_id") or cut.get("id") or f"cut_{index + 1}"),
            "start": round(start, 3),
            "end": round(end, 3),
            "reason": str(cut.get("reason") or ""),
            "risk_level": str(cut.get("risk_level") or ""),
            "boundary_keep_energy": float(cut.get("boundary_keep_energy", 0.0) or 0.0),
            "timestamps_sec": timestamps,
            "frame_paths": frame_paths,
        }
        if waveform_path.exists():
            sample["waveform_path"] = str(waveform_path)
        if frame_paths:
            samples.append(sample)
    manifest = {
        "schema": "strategy_cut_boundary_samples.v1",
        "video_path": str(video_path),
        "review_dir": str(sample_dir),
        "sample_source": "render_output_packaged",
        "sample_count": len(samples),
        "frame_count": sum(len(sample.get("frame_paths") or []) for sample in samples),
        "boundary_samples": samples,
    }
    if errors:
        manifest["errors"] = errors
    manifest_path = sample_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["manifest_path"] = str(manifest_path)
    return manifest


async def _extract_strategy_boundary_frame(video_path: Path, output_path: Path, *, seek_sec: float) -> None:
    settings = get_settings()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(max(0.0, float(seek_sec or 0.0))),
                "-i",
                str(video_path),
                "-vframes",
                "1",
                "-update",
                "1",
                "-q:v",
                "3",
                "-vf",
                "scale=960:-2",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 600)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"strategy boundary frame extraction failed: {result.stderr[-500:]}")


async def _extract_strategy_boundary_waveform(
    video_path: Path,
    output_path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> None:
    settings = get_settings()
    start = max(0.0, float(start_sec or 0.0))
    duration = max(0.1, float(end_sec or start) - start)
    wav_path = output_path.with_suffix(".wav")
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(start),
                "-t",
                str(duration),
                "-i",
                str(video_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(wav_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(30, min(int(getattr(settings, "ffmpeg_timeout_sec", 600) or 600), 600)),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ),
    )
    if result.returncode != 0:
        raise RuntimeError(f"strategy boundary waveform extraction failed: {result.stderr[-500:]}")
    payload = _strategy_waveform_peaks_payload(wav_path, source_video=video_path, start_sec=start, duration_sec=duration)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with suppress(OSError):
        wav_path.unlink()


def _strategy_waveform_peaks_payload(
    wav_path: Path,
    *,
    source_video: Path,
    start_sec: float,
    duration_sec: float,
    target_points: int = 120,
) -> dict[str, Any]:
    with wave.open(str(wav_path), "rb") as wav:
        sample_rate = wav.getframerate()
        sample_width = wav.getsampwidth()
        frame_count = wav.getnframes()
        frames_per_peak = max(1, frame_count // max(1, int(target_points or 120)))
        peaks: list[float] = []
        for _ in range(0, frame_count, frames_per_peak):
            chunk = wav.readframes(frames_per_peak)
            if not chunk:
                break
            peaks.append(round(_pcm_chunk_peak(chunk, sample_width=sample_width), 4))
    return {
        "schema": "strategy_cut_boundary_waveform.v1",
        "source_video": str(source_video),
        "start_sec": round(float(start_sec or 0.0), 3),
        "duration_sec": round(float(duration_sec or 0.0), 3),
        "sample_rate": int(sample_rate or 0),
        "peak_count": len(peaks),
        "peaks": peaks,
    }


def _pcm_chunk_peak(chunk: bytes, *, sample_width: int) -> float:
    if not chunk:
        return 0.0
    width = max(1, int(sample_width or 1))
    if width == 1:
        return max(abs(byte - 128) / 128.0 for byte in chunk)
    max_amplitude = float((1 << (8 * width - 1)) - 1)
    peak = 0.0
    for index in range(0, len(chunk) - width + 1, width):
        value = int.from_bytes(chunk[index : index + width], "little", signed=True)
        peak = max(peak, abs(value) / max_amplitude)
    return min(1.0, peak)


def _content_profile_is_generated_strategy_replay_fixture(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile if isinstance(content_profile, dict) else {}
    source_context = (
        profile.get("source_context")
        if isinstance(profile.get("source_context"), dict)
        else {}
    )
    if not source_context and isinstance(profile.get("resolved_profile"), dict):
        resolved_profile = profile.get("resolved_profile") or {}
        source_context = (
            resolved_profile.get("source_context")
            if isinstance(resolved_profile.get("source_context"), dict)
            else {}
        )
    return str(source_context.get("fixture_source") or "").strip() == "generated_strategy_replay_fixture"


def _build_fixture_seeded_render_subtitle_asr_alignment(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    debug_dir: Path,
    label: str,
) -> dict[str, Any]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    timings = _render_subtitle_timings_from_items(subtitle_items)
    payload = {
        "label": label,
        "video_path": str(video_path),
        "audio_path": None,
        "provider": "fixture_seed",
        "model": "generated_strategy_replay_fixture",
        "duration_sec": 0.0,
        "subtitle_event_count": len(timings),
        "asr_token_count": 0,
        "asr_text_chars": 0,
        "gate_pass": True,
        "fixture_seeded": True,
        "reason": "generated_strategy_replay_fixture_seeded_alignment",
        "local_cluster_metrics": {},
        "offset_estimate": {"stable": True, "offset_sec": 0.0},
        "audit": {
            "status": "skipped",
            "reason": "generated_strategy_replay_fixture_seeded_alignment",
            "events": [],
        },
    }
    (debug_dir / f"{label}.subtitle_alignment.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return payload


def _build_edit_review_bundle_payload(
    *,
    job_flow_mode: str,
    source_name: str,
    content_profile: dict[str, Any] | None,
    source_timeline_contract: dict[str, Any] | None,
    subtitle_source_projection_validation: dict[str, Any] | None,
    automatic_gate: dict[str, Any] | None,
    edit_decision: dict[str, Any] | None,
    full_subtitles: list[dict[str, Any]],
    edited_subtitles: list[dict[str, Any]],
    cut_analysis: dict[str, Any] | None,
    refine_decision_plan: dict[str, Any] | None,
    multimodal_trim_review: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topic_fact_confirmation = (
        dict((content_profile or {}).get("topic_fact_confirmation") or {})
        if isinstance(content_profile, dict)
        and isinstance((content_profile or {}).get("topic_fact_confirmation"), dict)
        else {}
    )
    return {
        "schema_version": "edit_review_bundle_v1",
        "job_flow_mode": str(job_flow_mode or "auto"),
        "source_name": str(source_name or ""),
        "topic_fact_confirmation": topic_fact_confirmation,
        "source_timeline_contract": _clone_json_like(source_timeline_contract or {}),
        "subtitle_source_projection_validation": _clone_json_like(subtitle_source_projection_validation or {}),
        "automatic_gate": _clone_json_like(automatic_gate or {}),
        "edit_decision": _clone_json_like(edit_decision or {}),
        "cut_analysis": _clone_json_like(cut_analysis or {}),
        "refine_decision_plan": _clone_json_like(refine_decision_plan or {}),
        "multimodal_trim_review": _clone_json_like(multimodal_trim_review or {}),
        "full_subtitles": [dict(item) for item in list(full_subtitles or []) if isinstance(item, dict)],
        "edited_subtitles": [dict(item) for item in list(edited_subtitles or []) if isinstance(item, dict)],
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
        subtitle_display_rule_text(item) or str(item.get("text") or "")
    )
    if not text:
        return None
    payload: dict[str, Any] = {
        "index": int(item.get("index", 0) or 0),
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "text": text,
    }
    for key in (
        "projection_source",
        "source_index",
        "source_indexes",
        "source_fragment_index",
        "source_fragment_count",
        "source_overlap_start_time",
        "source_overlap_end_time",
    ):
        if key in item:
            payload[key] = item[key]
    return payload


def _clone_json_like(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clone_json_like(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clone_json_like(item) for item in value]
    return value


def _validate_variant_timeline_bundle(
    bundle: dict[str, Any],
    *,
    packaging_timeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        subtitle_ranges: list[tuple[float, float]] = []
        for index, event in enumerate(variant.get("subtitle_events") or [], start=1):
            if not isinstance(event, dict):
                issues.append(f"{variant_name}: subtitle event {index} is not a dict")
                continue
            start_time = float(event.get("start_time", event.get("start", 0.0)) or 0.0)
            end_time = float(event.get("end_time", event.get("end", start_time)) or start_time)
            subtitle_ranges.append((start_time, end_time))
            if end_time < start_time:
                issues.append(f"{variant_name}: subtitle event {index} has end before start")
            if previous_end is not None and start_time < previous_end - 1e-6:
                issues.append(f"{variant_name}: subtitle events are not monotonic at index {index}")
            if duration_sec > 0 and end_time > duration_sec + 0.05:
                issues.append(f"{variant_name}: subtitle event {index} extends beyond media duration")
            previous_end = max(previous_end or end_time, end_time)
        timing_structure = _subtitle_timing_structure_diagnostics(
            subtitle_ranges,
            video_duration_sec=duration_sec,
        )
        if int(timing_structure.get("short_flash_count") or 0) > 0:
            issues.append(
                f"{variant_name}: subtitle events contain {timing_structure['short_flash_count']} short flash items"
            )
        if int(timing_structure.get("burst_window_count") or 0) > 0:
            issues.append(
                f"{variant_name}: subtitle events burst density max={timing_structure['max_events_per_one_sec']}/sec"
            )
        if int(timing_structure.get("large_gap_count") or 0) > max(3, int(len(subtitle_ranges) * 0.06)):
            issues.append(
                f"{variant_name}: subtitle events have unstable local gaps count={timing_structure['large_gap_count']}"
            )

    timeline_rules = bundle.get("timeline_rules")
    if isinstance(timeline_rules, dict):
        normalized_packaging_timeline = (
            dict(packaging_timeline)
            if isinstance(packaging_timeline, dict)
            else dict(timeline_rules.get("packaging_timeline") or {})
            if isinstance(timeline_rules.get("packaging_timeline"), dict)
            else resolve_packaging_timeline_payload(timeline_rules)
        )
        timeline_analysis = dict(normalized_packaging_timeline.get("timeline_analysis") or {})
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
        editing_skill = dict(normalized_packaging_timeline.get("editing_skill") or {})
        if isinstance(editing_skill, dict):
            if not str(editing_skill.get("key") or "").strip():
                issues.append("editing_skill: key missing")
            section_policy = editing_skill.get("section_policy")
            if section_policy is not None and not isinstance(section_policy, dict):
                issues.append("editing_skill: section_policy is not a dict")
        section_choreography = dict(normalized_packaging_timeline.get("section_choreography") or {})
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
        packaging_assets = dict(normalized_packaging_timeline.get("packaging") or {})
        if not isinstance(packaging_assets, dict):
            issues.append("packaging_timeline: packaging assets payload is not a dict")
        editing_accents = dict(normalized_packaging_timeline.get("editing_accents") or {})
        if not isinstance(editing_accents, dict):
            issues.append("packaging_timeline: editing_accents payload is not a dict")
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
    transitions: dict[str, Any] | None = None,
) -> list[tuple[float, float]]:
    if len(keep_segments) < 2:
        return []

    resolved_transitions = (
        dict(transitions)
        if isinstance(transitions, dict)
        else packaging_timeline_transitions(render_plan)
    )
    if not resolved_transitions.get("enabled"):
        return []

    raw_duration = float(resolved_transitions.get("duration_sec") or 0.12)
    requested_indexes: list[int] = []
    for raw_index in resolved_transitions.get("boundary_indexes") or []:
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


async def _load_job_creator_card(session, job: Job) -> CreatorCard | None:
    creator_card_id = getattr(job, "creator_card_id", None)
    if not creator_card_id:
        return None
    stmt = (
        select(CreatorCard)
        .options(
            selectinload(CreatorCard.assets),
            selectinload(CreatorCard.preferences),
        )
        .where(CreatorCard.id == creator_card_id)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _load_job_packaging_creator_card(session, job: Job) -> CreatorCard | None:
    creator = await _load_job_creator_card(session, job)
    if creator is not None:
        return creator
    return await _infer_packaging_creator_card_from_selected_assets(session)


async def _infer_packaging_creator_card_from_selected_assets(session) -> CreatorCard | None:
    selected_assets = _selected_packaging_asset_identity_keys()
    if not any(selected_assets.values()):
        return None

    stmt = (
        select(CreatorCard)
        .options(selectinload(CreatorCard.assets))
        .order_by(CreatorCard.updated_at.desc(), CreatorCard.created_at.desc())
    )
    result = await session.execute(stmt)
    candidates: list[tuple[int, str, CreatorCard]] = []
    for creator in result.scalars().all():
        score = _score_creator_card_for_selected_packaging_assets(
            creator,
            selected_assets=selected_assets,
        )
        if score <= 0:
            continue
        candidates.append((score, str(getattr(creator, "updated_at", "") or getattr(creator, "created_at", "") or ""), creator))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _selected_packaging_asset_identity_keys() -> dict[str, set[str]]:
    try:
        inventory = list_packaging_assets()
    except Exception:
        logger.exception("Failed to inspect packaging assets for creator-card inference")
        return {}
    config = inventory.get("config") if isinstance(inventory, dict) else {}
    assets_by_type = inventory.get("assets") if isinstance(inventory, dict) else {}
    if not isinstance(config, dict) or not isinstance(assets_by_type, dict):
        return {}

    assets_by_id = {
        str(asset.get("id") or ""): asset
        for assets in assets_by_type.values()
        for asset in list(assets or [])
        if isinstance(asset, dict)
    }
    selected: dict[str, set[str]] = {"intro": set(), "outro": set(), "watermark": set(), "music": set()}
    for config_key, asset_type in (
        ("intro_asset_id", "intro"),
        ("outro_asset_id", "outro"),
        ("watermark_asset_id", "watermark"),
    ):
        asset = assets_by_id.get(str(config.get(config_key) or ""))
        _add_packaging_asset_identity_key(selected[asset_type], asset)

    for asset_id in list(config.get("music_asset_ids") or []):
        asset = assets_by_id.get(str(asset_id or ""))
        _add_packaging_asset_identity_key(selected["music"], asset)
    return selected


def _score_creator_card_for_selected_packaging_assets(
    creator: CreatorCard,
    *,
    selected_assets: dict[str, set[str]],
) -> int:
    score = 0
    has_watermark = False
    for asset in list(getattr(creator, "assets", []) or []):
        packaging_type = _creator_asset_packaging_type(getattr(asset, "asset_type", None))
        if packaging_type == "watermark" and resolve_creator_asset_path(getattr(asset, "stored_path", None)).is_file():
            has_watermark = True
        if not packaging_type:
            continue
        identity_key = _packaging_asset_identity_key(getattr(asset, "original_name", None))
        if not identity_key or identity_key not in selected_assets.get(packaging_type, set()):
            continue
        if packaging_type in {"intro", "outro"}:
            score += 8
        elif packaging_type == "music":
            score += 2
        elif packaging_type == "watermark":
            score += 5
    if score <= 0 or not has_watermark:
        return 0
    return score + 2


def _creator_asset_packaging_type(asset_type: Any) -> str | None:
    category = normalize_creator_asset_category(asset_type)
    if category in {"intro", "outro"}:
        return category
    if category == "logo":
        return "watermark"
    if category == "music_library":
        return "music"
    return None


def _add_packaging_asset_identity_key(target: set[str], asset: dict[str, Any] | None) -> None:
    if not isinstance(asset, dict):
        return
    for value in (asset.get("original_name"), Path(str(asset.get("path") or "")).name):
        key = _packaging_asset_identity_key(value)
        if key:
            target.add(key)


def _packaging_asset_identity_key(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip().lower()
    if not text:
        return ""
    name = Path(text).name
    name = re.sub(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}-", "", name)
    name = re.sub(r"^[0-9a-f]{32}[._-]", "", name)
    return re.sub(r"\s+", " ", name).strip()


def _creator_legacy_avatar_profile_ids(creator: CreatorCard | None) -> list[str]:
    if creator is None:
        return []
    profile_ids: list[str] = []
    for preference in list(getattr(creator, "preferences", []) or []):
        if str(getattr(preference, "source", "") or "").strip() != "legacy_avatar_profile":
            continue
        payload = getattr(preference, "structured_payload", None) or {}
        legacy_profile_id = str(payload.get("legacy_profile_id") or "").strip()
        if legacy_profile_id and legacy_profile_id not in profile_ids:
            profile_ids.append(legacy_profile_id)
    return profile_ids


def _select_creator_bound_avatar_profile(creator: CreatorCard | None) -> dict[str, Any] | None:
    legacy_profile_ids = set(_creator_legacy_avatar_profile_ids(creator))
    if not legacy_profile_ids:
        return None
    profiles = [profile for profile in list_avatar_material_profiles() if str(profile.get("id") or "") in legacy_profile_ids]
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


def _resolve_creator_avatar_binding(creator: CreatorCard | None) -> dict[str, Any] | None:
    if creator is None:
        return None

    creator_asset = pick_creator_avatar_presenter_asset(list(getattr(creator, "assets", []) or []))
    if creator_asset is not None:
        presenter_path = resolve_creator_asset_path(creator_asset.get("stored_path"))
        if presenter_path.exists():
            return {
                "source": "creator_asset",
                "presenter_id": presenter_path.as_posix(),
                "creator_card_id": str(getattr(creator, "id", "") or ""),
                "creator_card_name": str(getattr(creator, "name", "") or ""),
                "creator_asset_id": str(creator_asset.get("id") or ""),
                "creator_asset_type": str(creator_asset.get("asset_type") or ""),
                "avatar_profile_id": None,
                "avatar_profile_name": str(getattr(creator, "name", "") or ""),
            }

    avatar_profile = _select_creator_bound_avatar_profile(creator)
    avatar_video_path = _pick_avatar_profile_speaking_video_path(avatar_profile)
    if avatar_profile and avatar_video_path:
        return {
            "source": "legacy_avatar_profile",
            "presenter_id": avatar_video_path.as_posix(),
            "creator_card_id": str(getattr(creator, "id", "") or ""),
            "creator_card_name": str(getattr(creator, "name", "") or ""),
            "creator_asset_id": None,
            "creator_asset_type": None,
            "avatar_profile_id": str(avatar_profile.get("id") or ""),
            "avatar_profile_name": str(avatar_profile.get("display_name") or avatar_profile.get("presenter_alias") or ""),
        }
    return None


def _apply_avatar_presenter_binding_to_plan(
    plan: dict[str, Any],
    *,
    binding: dict[str, Any] | None,
    packaging_config: dict[str, Any],
) -> None:
    if not binding:
        plan["avatar_binding"] = {
            "status": "missing",
            "reason": "creator_avatar_binding_missing",
        }
        return
    presenter_id = str(binding.get("presenter_id") or "").strip()
    if not presenter_id:
        plan["avatar_binding"] = {
            **binding,
            "status": "missing",
            "reason": "creator_avatar_presenter_missing",
        }
        return
    plan["integration_mode"] = "picture_in_picture"
    plan["avatar_profile_id"] = str(binding.get("avatar_profile_id") or "")
    plan["avatar_profile_name"] = str(binding.get("avatar_profile_name") or "")
    plan["presenter_id"] = presenter_id
    plan["creator_card_id"] = str(binding.get("creator_card_id") or "")
    plan["creator_card_name"] = str(binding.get("creator_card_name") or "")
    plan["avatar_binding"] = {
        **binding,
        "status": "bound",
    }
    plan["overlay_position"] = str(packaging_config.get("avatar_overlay_position") or "bottom_right")
    plan["overlay_scale"] = float(
        packaging_config.get("avatar_overlay_scale") or plan.get("overlay_scale") or 0.22
    )
    plan["overlay_corner_radius"] = int(packaging_config.get("avatar_overlay_corner_radius") or 0)
    plan["overlay_border_width"] = int(packaging_config.get("avatar_overlay_border_width") or 0)
    plan["overlay_border_color"] = str(packaging_config.get("avatar_overlay_border_color") or "#F4E4B8")
    plan["overlay_margin"] = 28
    render_request = dict(plan.get("render_request") or {})
    render_request["presenter_id"] = presenter_id
    render_request["layout_template"] = plan.get("layout_template")
    plan["render_request"] = render_request


def _avatar_missing_presenter_reason(plan: dict[str, Any] | None) -> str:
    payload = plan if isinstance(plan, dict) else {}
    presenter_id = str(payload.get("presenter_id") or "").strip()
    if presenter_id:
        return ""
    binding = payload.get("avatar_binding") if isinstance(payload.get("avatar_binding"), dict) else {}
    binding_reason = str(binding.get("reason") or "").strip()
    if binding_reason:
        return binding_reason
    return "creator_avatar_presenter_missing"


def _avatar_missing_presenter_execution(plan: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "provider": plan.get("provider"),
        "status": "skipped",
        "reason": reason,
        "detail": "未配置可用数字人 presenter，跳过数字人渲染；普通成片不受影响。",
    }


def _avatar_missing_presenter_runtime_result(plan: dict[str, Any], *, reason: str) -> dict[str, Any]:
    return {
        "enabled": True,
        "status": "skipped",
        "reason": reason,
        "reason_category": "not_configured",
        "mode": str(plan.get("mode") or ""),
        "integration_mode": str(plan.get("integration_mode") or ""),
        "provider": str(plan.get("provider") or ""),
        "detail": "未配置可用数字人 presenter，跳过数字人渲染；普通成片不受影响。",
    }


def _build_creator_author_profile(creator: CreatorCard | None) -> dict[str, Any] | None:
    if creator is None:
        return None
    public_name = str(getattr(creator, "name", "") or "").strip()
    positioning_text = str(getattr(creator, "positioning", "") or "").strip()
    natural_language_profile = str(getattr(creator, "natural_language_profile", "") or "").strip()
    default_platforms = [str(item).strip() for item in list(getattr(creator, "default_platforms", []) or []) if str(item).strip()]
    content_domains = [str(item).strip() for item in list(getattr(creator, "content_domains", []) or []) if str(item).strip()]
    return {
        "display_name": public_name,
        "creator_profile": {
            "identity": {
                "public_name": public_name,
                "bio": natural_language_profile or None,
            },
            "positioning": {
                "creator_focus": positioning_text or None,
                "expertise": content_domains,
                "audience": str(getattr(creator, "audience", "") or "").strip() or None,
                "style": natural_language_profile or None,
            },
            "publishing": {
                "primary_platform": default_platforms[0] if default_platforms else None,
                "active_platforms": default_platforms,
            },
        },
    }


def _pick_avatar_profile_speaking_video_path(profile: dict[str, Any] | None) -> Path | None:
    if not profile:
        return None
    for file_record in profile.get("files") or []:
        if str(file_record.get("role") or "") != "speaking_video":
            continue
        path = resolve_avatar_material_path(file_record.get("path"))
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
    # Dispose loop-bound asyncpg connections before starting a fresh event loop.
    reset_session_state_sync()

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
    }
    fn = step_map.get(step_name)
    if not fn:
        raise ValueError(f"Unknown step: {step_name}")

    async def _run_and_dispose_session_state() -> dict:
        try:
            return await fn(job_id)
        finally:
            try:
                await reset_session_state()
            except Exception:
                logger.warning("Failed to dispose async DB session state after step=%s job=%s", step_name, job_id, exc_info=True)

    return asyncio.run(_run_and_dispose_session_state())
